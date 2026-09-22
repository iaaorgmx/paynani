#!/usr/bin/env python3
"""
idle_listener.py — push-style new-mail listener for the paynani mailbox.

Holds an IMAP IDLE connection open. The server pushes an untagged EXISTS as soon
as mail arrives; we fetch headers for the new UIDs and print one line per message
on stdout.

Every message is reported, whoever sent it. Messages from an address on
`roster.md` are additionally tagged `roster` in the emitted line: that tag is
how the agent knows, without opening anything, that this is mail it may act on
and answer. Everything else is a notification and nothing more.

One stdout line == one harness notification. Output is line-buffered and never
contains credentials.

Usage:  python3 scripts/idle_listener.py [--env PATH] [--mailbox INBOX] [--once] [--roster PATH]
Exit:   0 clean shutdown · 1 configuration or login failure (not retryable)
"""

import argparse, calendar, datetime, email, email.utils, imaplib, json, os, pathlib, re
import select, signal, socket, ssl, subprocess, sys, time
from email.header import decode_header, make_header

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "harness"))
import python_floor  # noqa: E402
PYTHON_FACTS = python_floor.enforce()

from roster import (DEFAULT_ROSTER, normalise, notifier_headers, notifiers,
                    roster_addresses, roster_entries, sender_is_listed)

import event as ev
import ledger
from paths import env_file, state_dir

DEFAULT_ENV   = None   # resolved by harness/paths.py, see main()
DEFAULT_STATE = str(state_dir() / "idle.json")
DEFAULT_JOURNAL = str(state_dir() / "events.jsonl")


def _process_version():
    """Version loaded by this process, fixed at startup rather than per heartbeat."""
    try:
        value = (pathlib.Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
    except OSError:
        return None
    return value or None


def _process_commit():
    """Git HEAD this process's checkout was on at startup, fixed like
    PROCESS_VERSION: a `VERSION` match can still hide a `git pull` on `main`
    that landed between tagged releases (#260)."""
    try:
        run = subprocess.run(
            ["git", "-C", str(pathlib.Path(__file__).resolve().parent.parent), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if run.returncode != 0:
        return None
    return (run.stdout or "").strip() or None


PROCESS_VERSION = _process_version()
PROCESS_COMMIT = _process_commit()

# RFC 2177: a client must re-issue IDLE at least every 29 minutes. We stay well
# under the ceiling on purpose: this interval is also the longest a dead
# connection can sit unnoticed, so 25 minutes bought nothing and cost a
# 25-minute blind window. See keepalive() for the primary defence.
IDLE_REFRESH = 5 * 60
BACKOFF_MIN, BACKOFF_MAX = 5, 300

# Optional: collapse GitHub notification subjects into something scannable.
# Delete this and the branch in describe() if you do not get GitHub mail.
GH_SUBJECT = re.compile(r"^\s*(?:Re:\s*)?\[([\w.\-]+/[\w.\-]+)\]\s*(.+?)\s*(?:\((?:(?:Issue|PR|Pull Request|Discussion)\s+)?([#!]\d+)\)\s*)?$")

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True


def emit(line):
    """One line on stdout, which the unit appends to mail.log for a person."""
    print(line, flush=True)


class NotQueued(Exception):
    """The journal could not take a record, so nothing may be acknowledged."""


def record(journal_path, envelope):
    """
    Put one event in the journal, and the same event on the operator's log.

    Both, always, and from here only. The journal is what a runtime adapter
    delivers from; mail.log is what a human reads when they want to know what
    happened. Writing them in two places is how they start describing different
    mail.

    **Raises if the journal could not take it**, and the caller must not advance
    the last-seen UID when it does. That UID is the only thing that decides
    whether a message is ever fetched again: acknowledging one that reached
    neither the queue nor a runtime loses it for good, on a full disk or a
    permission error, with a line in mail.log as the only trace. Writing the
    operator line is not queueing.
    """
    if envelope.get("event_type") == ev.MAIL_RECEIVED:
        command = envelope.get("inspection_command")
        if command and command not in envelope.get("notification_text", ""):
            envelope = dict(envelope)
            envelope["notification_text"] = (
                envelope.get("notification_text", "") + f" [{command}]"
            )
    try:
        ev.append(journal_path, envelope)
        ledger.observed(ledger.path_for(journal_path), envelope)
    except (OSError, ValueError) as exc:
        log(f"could not write the event journal at {journal_path}: {exc}")
        log("This message is NOT queued for delivery, so its UID is deliberately "
            "not being acknowledged. It will be picked up again once the journal "
            "is writable. Nothing is lost; nothing is moving either.")
        raise NotQueued(str(exc)) from exc
    emit(envelope.get("notification_text", ""))


RECOVERED = "listener recovered; mail is being seen again"


def journal_fault(journal_path, account, message):
    """
    Put a listener fault in the same stream as the mail. True only if it landed.

    A fault reported only where nobody looks is a fault nobody sees, and silence
    that reads as an empty mailbox is the failure this project exists to prevent.
    So it travels the path that is already being watched.
    """
    try:
        ev.append(journal_path, ev.listener_error(account=account, message=message))
        return True
    except (OSError, ValueError) as exc:
        log(f"could not journal the listener fault: {exc}")
        return False


class FaultLog:
    """
    What the journal has actually been told about the listener's health.

    Two pieces of state, and the distinction between them is the whole point:

    - `recorded` is the fault the journal really holds. It suppresses repeats,
      because an outage retries every few seconds for hours and one record per
      attempt would bury the mail sitting beside it.
    - `pending` is a transition that has not been written yet, because the
      attempt to write it failed.

    Keeping only the first loses whole outages. A failed append left nothing
    owed, and the retry meant to fix it never came: on the pass where the
    listener recovers, nothing asks about the fault again, so the recovery finds
    no recorded outage and writes nothing either. The episode goes entirely
    unreported, which is exactly the silence this design refuses.

    So what is owed is carried until it is written, and recovery settles that
    debt before declaring itself, which also keeps the two in the order they
    happened.
    """

    def __init__(self, journal_path, account):
        self.journal = journal_path
        self.account = account
        self.recorded = None
        self.pending = None

    def flush(self):
        """Write what is owed. Safe on every pass; does nothing when nothing is."""
        if self.pending is None:
            return
        if journal_fault(self.journal, self.account, self.pending):
            self.recorded = self.pending
            self.pending = None

    def fault(self, message):
        """Something is wrong, and this is what it is."""
        if message != self.recorded:
            self.pending = message
        self.flush()

    def recovered(self):
        """
        Working again. Writes the outage first if it never made it in.

        Nothing is written when nothing went wrong, and nothing is cleared until
        the recovery itself is durable: a recovery that could not be written must
        leave the outage open rather than quietly ending it.
        """
        self.flush()
        if self.recorded is None:
            return
        if journal_fault(self.journal, self.account, RECOVERED):
            self.recorded = None


def log(line):
    """Diagnostics go to stderr so they never become notifications."""
    print(line, file=sys.stderr, flush=True)


def load_env(path):
    """Parse KEY=VALUE. Tolerates CRLF and a UTF-8 BOM — both have bitten me."""
    env = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def decode_hdr(value):
    if not value:
        return ""
    try:
        text = str(make_header(decode_header(value)))
    except Exception:
        text = str(value)
    return re.sub(r"\s+", " ", text).strip()


def describe(sender, subject, date, trusted=False):
    """The operator's line. `parts` returns the same thing plus the fields the
    envelope needs, so nothing downstream has to parse this back apart."""
    return parts(sender, subject, date, trusted)["notification_text"]


def parts(sender, subject, date, trusted=False, message_id="", provider_id="", recipient_role="to"):
    """
    One message, rendered and structured at the same time.

    Both come from here so they cannot disagree. Rendering in one place and
    extracting fields somewhere else is how a log line and a payload end up
    describing different messages.
    """
    name, addr = email.utils.parseaddr(sender)
    who = name or addr or "unknown"

    # Two clocks matter: when the sender stamped it, and when we noticed. The gap
    # is the latency this design exists to shrink, so report both.
    sent = ""
    sent_iso = ""
    try:
        stamped = email.utils.parsedate_to_datetime(date)
        sent = stamped.astimezone().strftime("%H:%M:%S")
        sent_iso = stamped.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    when = time.strftime("%H:%M:%S") + (f", sent {sent}" if sent else "")
    # The tag goes inside the timestamp bracket so one grep finds actionable
    # mail in the log, and so its absence is visible rather than merely implied.
    if trusted:
        when += ", roster"
    # `to` is the known shape and stays silent (#221's PRD: "con to la línea no
    # cambia"). `cc` and `undisclosed` are the two roles a message can carry
    # without being an instruction to whoever received it, and both need to
    # show in the line a human or another agent greps -- a role that changes
    # behaviour but not the log is exactly the silent failure DESIGN.md rules
    # out.
    if recipient_role in ("cc", "undisclosed"):
        when += f", {recipient_role}"

    m = GH_SUBJECT.match(subject or "")
    if m:
        repo, title, ref = m.groups()
        head = f"GitHub {repo}" + (f" {ref}" if ref else "")
        body = f"{head} — {title} (via {who})"
    else:
        body = f"{who} — {subject or '(no subject)'}"
    return {
        "notification_text": f"[mail {when}] {body}",
        "sender_name": name,
        "sender_address": addr,
        "subject": subject or "",
        "sent_at": sent_iso,
        "roster_match": bool(trusted),
        "message_id": (message_id or "").strip(),
        "provider_id": (provider_id or "").strip(),
        "recipient_role": recipient_role,
    }


def recipient_role_for(msg, account):
    """
    `to`, `cc` or `undisclosed`, by comparing `account` against the addresses
    this message actually names -- not whether it was addressed to us by
    display name, which display names cannot guarantee.

    `undisclosed` covers BCC and mailing lists alike: both leave us out of
    every header the message carries, and neither is an instruction the way a
    direct `To` is.
    """
    target = normalise(account or "")
    to_addrs = {normalise(addr) for _, addr in email.utils.getaddresses(msg.get_all("To", []))}
    if target in to_addrs:
        return "to"
    cc_addrs = {normalise(addr) for _, addr in email.utils.getaddresses(msg.get_all("Cc", []))}
    if target in cc_addrs:
        return "cc"
    return "undisclosed"


def provider_identifier(message_id):
    """A stable provider-side identity when the Message-ID exposes one."""
    value = (message_id or "").strip()
    match = re.fullmatch(r"<([^<>]+)@github\.com>", value, re.IGNORECASE)
    return f"github:{match.group(1).lower()}" if match else ""


# Two key schemas are accepted, so a host that already keeps credentials for its
# agent does not have to duplicate them. PAYNANI_* wins where both are set:
# an install that named them explicitly meant to.
KEYS = {
    "host": ("PAYNANI_IMAP_HOST", "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"),
    "port": ("PAYNANI_IMAP_PORT", "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT"),
    "user": ("PAYNANI_EMAIL", "AGENT_EMAIL_ACCOUNT"),
    "password": ("PAYNANI_PASSWORD", "AGENT_EMAIL_PASSWORD"),
}

# An older schema named these after servers and stored ports in them. Reading one
# as a hostname connects nowhere useful, so say what is wrong instead.
LEGACY_AMBIGUOUS = (
    "AGENT_EMAIL_INCOMING_SERVER_IMAP",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP",
)


def lookup(env, field, default=None):
    """First non-empty value among the accepted names for a field."""
    for key in KEYS[field]:
        value = env.get(key, "").strip()
        if value:
            return value
    if default is not None:
        return default
    tried = " or ".join(KEYS[field])
    log(f"missing {tried} in the env file")
    sys.exit(1)


# How long a connection may sit idle before the kernel probes it, how far apart
# the probes go, and how many go unanswered before the socket is declared dead.
#
# The idle timer has two names. Linux calls it TCP_KEEPIDLE; macOS calls it
# TCP_KEEPALIVE, and each platform exposes only its own -- so listing both and
# asking for each by name costs one skipped lookup either way and covers both.
# Naming only TCP_KEEPIDLE, as this did at first, does not fail on macOS: it
# leaves SO_KEEPALIVE on with the system default of two hours, so no probe fires
# inside any window that matters and the protection quietly falls back to
# IDLE_REFRESH. A silent downgrade is the exact failure this whole function
# exists to remove, so the macOS name is not an optional extra.
KEEPALIVE_OPTIONS = (
    ("TCP_KEEPIDLE", 60),     # Linux
    ("TCP_KEEPALIVE", 60),    # macOS, same knob
    ("TCP_KEEPINTVL", 20),
    ("TCP_KEEPCNT", 3),
)


def resolve_keepalive_option(name):
    """Return the platform's numeric socket option for a keepalive name.

    Apple's Python 3.9 does not expose TCP_KEEPALIVE even though Darwin's
    tcp.h defines it as 0x10 and the kernel accepts it.  Without this fallback
    SO_KEEPALIVE is enabled but its idle timer stays at the two-hour system
    default, which defeats the early dead-connection detection this function
    exists to provide.
    """
    option = getattr(socket, name, None)
    if option is None and sys.platform == "darwin" and name == "TCP_KEEPALIVE":
        return 0x10
    return option


def keepalive(sock):
    """Make a dead connection announce itself.

    Behind NAT — WSL2, or most home routers — an idle connection is dropped
    without a FIN, and from this side the socket still reads ESTAB until
    something tries to write. The listener sits in select() waiting for an
    EXISTS that can no longer arrive, and the mailbox looks exactly like a quiet
    one. Keepalive probes turn that into a read error, which the retry loop
    already handles: recovery was never the missing piece, noticing was.
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError as exc:
        log(f"could not enable SO_KEEPALIVE: {exc}")
        return
    # Every tunable is asked for by name before it is set, because which ones
    # exist depends on the platform. A missing one costs sensitivity, not
    # correctness -- see KEEPALIVE_OPTIONS for why both idle-timer names are
    # listed rather than only Linux's.
    for name, value in KEEPALIVE_OPTIONS:
        option = resolve_keepalive_option(name)
        if option is None:
            continue
        try:
            sock.setsockopt(socket.IPPROTO_TCP, option, value)
        except OSError as exc:
            log(f"could not set {name}={value}: {exc}")


def connect(env):
    # The old schema is a trap rather than an inconvenience: the key is named for
    # a server and holds a port, so a literal reading sends you somewhere else.
    for key in LEGACY_AMBIGUOUS:
        if env.get(key, "").strip().isdigit():
            log(
                f"{key} holds a port, not a hostname — that is the old schema. "
                f"Split it into {key}_HOST and {key}_PORT."
            )
            sys.exit(1)

    host = lookup(env, "host")
    # A hostname field holding a bare number is a misconfiguration, not a host.
    # Failing here beats connecting somewhere unintended.
    if host.isdigit():
        log(f"IMAP host is {host!r}, which is a port, not a hostname")
        sys.exit(1)
    port = int(lookup(env, "port", default="993"))
    user = lookup(env, "user")
    password = lookup(env, "password")

    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=30)
    keepalive(conn.sock)
    try:
        conn.login(user, password)
    except imaplib.IMAP4.error as exc:
        # Bad credentials never succeed on retry. Fail loudly rather than spin.
        log(f"login rejected by {host} for {user}: {exc}")
        raise SystemExit(1)
    return conn


def load_state(path):
    if str(path) == "none":
        return {}
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        log(f"ignoring unreadable state at {path}: {exc}")
        return {}


def timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _timestamp_seconds(stamp):
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def record_imap_reconnect(telemetry, now=None):
    now = timestamp() if now is None else now
    now_seconds = _timestamp_seconds(now)
    window = []
    for stamp in telemetry.get("imap_reconnect_window") or []:
        stamp_seconds = _timestamp_seconds(stamp)
        if stamp_seconds is None or now_seconds is None:
            continue
        if now_seconds - stamp_seconds <= 3600:
            window.append(stamp)
    window.append(now)
    telemetry["imap_reconnect_window"] = window
    telemetry["imap_reconnects_last_hour"] = len(window)
    return telemetry


def save_state(path, mailbox, validity, last_uid, telemetry=None):
    state = {
        "mailbox": mailbox,
        "uidvalidity": validity,
        "last_uid": last_uid,
        "heartbeat_at": timestamp(),
        "version": PROCESS_VERSION,
        "commit": PROCESS_COMMIT,
        "pid": os.getpid(),
        "python": PYTHON_FACTS,
    }
    if telemetry:
        state.update({k: v for k, v in telemetry.items() if v is not None})
    if str(path) == "none":
        return state
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, path)          # atomic: a crash cannot truncate it
    except OSError as exc:
        log(f"could not persist state to {path}: {exc}")
    return state


def uidvalidity(conn, mailbox):
    typ, data = conn.status(mailbox, "(UIDVALIDITY)")
    if typ != "OK" or not data or not data[0]:
        return None
    m = re.search(rb"UIDVALIDITY\s+(\d+)", data[0])
    return m.group(1).decode() if m else None


def newest_uid(conn):
    typ, data = conn.uid("search", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return 0
    return max(int(u) for u in data[0].split())


def fetch_since(conn, last_uid, listed, account):
    """[(uid, parts)] for every message with UID > last_uid.

    Headers only — BODY.PEEK. The listener never downloads a body and never
    marks anything read; reading is the agent's job, through Himalaya, after it
    sees the notification.

    Which headers to ask for is not fixed: a declared notifier names one, and
    the roster is what declares them, so the field list is built from the roster
    rather than written here. Asking for a header nobody declared would be free,
    but asking for none of them would silently make every notifier fail to match.

    `account` is this mailbox's own address, needed to work out `recipient_role`
    (#221): TO and CC are fetched alongside the rest precisely so that can be
    answered without a second round trip.
    """
    typ, data = conn.uid("search", None, f"UID {last_uid + 1}:*")
    if typ != "OK" or not data or not data[0]:
        return []
    # "UID n:*" always matches at least the highest message — filter explicitly.
    uids = sorted(u for u in (int(x) for x in data[0].split()) if u > last_uid)
    out = []
    for uid in uids:
        fields_wanted = " ".join(["FROM", "TO", "CC", "SUBJECT", "DATE", "MESSAGE-ID"]
                                 + [h.upper() for h in notifier_headers(listed.notifiers)])
        typ, payload = conn.uid("fetch", str(uid),
                                f"(BODY.PEEK[HEADER.FIELDS ({fields_wanted})])")
        if typ != "OK" or not payload or not isinstance(payload[0], tuple):
            continue
        msg = email.message_from_bytes(payload[0][1])
        message_id = decode_hdr(msg.get("Message-ID"))
        fields = parts(decode_hdr(msg.get("From")),
                       decode_hdr(msg.get("Subject")),
                       msg.get("Date", ""),
                       sender_is_listed(msg, listed.allowed,
                                        listed.entries, listed.notifiers),
                       message_id, provider_identifier(message_id),
                       recipient_role_for(msg, account))
        notifier_values = {
            header: decode_hdr(msg.get(header))
            for header in notifier_headers(listed.notifiers)
            if decode_hdr(msg.get(header))
        }
        if notifier_values:
            fields["notifier_headers"] = notifier_values
        out.append((uid, fields))
    return out


def idle(conn, timeout):
    """Enter IDLE; block until the mailbox changes or the refresh window ends."""
    tag = conn._new_tag()
    conn.send(b"%s IDLE\r\n" % tag)

    ready = conn.readline()
    if not ready.startswith(b"+"):
        raise ConnectionError(f"server refused IDLE: {ready!r}")

    deadline = time.monotonic() + timeout
    try:
        while not _stop:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select([conn.sock], [], [], min(remaining, 30))
            if not readable:
                continue
            line = conn.readline()
            if not line:
                raise ConnectionError("server closed the connection during IDLE")
            if b"EXISTS" in line or b"RECENT" in line:
                break
    finally:
        conn.send(b"DONE\r\n")
        # Drain to the tagged completion so the connection stays usable.
        while True:
            line = conn.readline()
            if not line or line.startswith(tag):
                break


class Listed:
    """The three answers the roster gives, read together.

    Read as one because they have to describe the same file: a notifier matched
    against entries from an earlier read would be judging a handle against a
    list that has since changed.
    """

    __slots__ = ("allowed", "entries", "notifiers")

    def __init__(self, roster_path):
        self.allowed = roster_addresses(roster_path)
        self.entries = roster_entries(roster_path)
        self.notifiers = notifiers(roster_path)


def run(env_path, mailbox, once, state_path, roster_path, journal_path):
    env = load_env(env_path)
    account = lookup(env, "user")
    if not roster_path.is_file():
        # Not fatal. Mail still gets reported; nothing gets tagged, so the agent
        # treats everything as read-only until a human writes the file.
        log(f"no roster at {roster_path}; no sender will be tagged as trusted")
    backoff = BACKOFF_MIN
    state = load_state(state_path)
    # IMAP reconnection telemetry lives beside the UID cursor so doctor can
    # distinguish a quiet, healthy mailbox from a listener that is only retrying.
    telemetry = {
        "imap_last_disconnect_at": state.get("imap_last_disconnect_at"),
        "imap_last_disconnect_error": state.get("imap_last_disconnect_error"),
        "imap_last_recovered_at": state.get("imap_last_recovered_at"),
        "imap_reconnect_attempts": int(state.get("imap_reconnect_attempts") or 0),
        "imap_reconnect_window": state.get("imap_reconnect_window") or [],
        "imap_reconnects_last_hour": int(state.get("imap_reconnects_last_hour") or 0),
        "imap_current_backoff_seconds": int(state.get("imap_current_backoff_seconds") or 0),
    }
    # What the journal has been told about the listener's own health.
    faults = FaultLog(journal_path, account)
    last_uid = state.get("last_uid") if state.get("mailbox") == mailbox else None

    while not _stop:
        conn = None
        try:
            conn = connect(env)
            conn.select(mailbox)

            if "IDLE" not in conn.capabilities:
                log("server does not advertise IDLE; cannot run in push mode")
                return 1

            # UIDs are only comparable within one UIDVALIDITY epoch. If the mailbox
            # was recreated the server reassigns them, and a stored uid would
            # silently point at the wrong message.
            validity = uidvalidity(conn, mailbox)
            if last_uid is not None and state.get("uidvalidity") not in (None, validity):
                log(f"UIDVALIDITY changed ({state.get('uidvalidity')} -> {validity}); "
                    "discarding stored position")
                last_uid = None

            if last_uid is None:
                last_uid = newest_uid(conn)
                state = save_state(state_path, mailbox, validity, last_uid, telemetry)
                log(f"listening on {mailbox}, baseline uid {last_uid}")
            else:
                # Write immediately on a resumed process. Upgrade verification
                # must distinguish the new listener from the old one without
                # waiting for the next five-minute IDLE heartbeat.
                state = save_state(state_path, mailbox, validity, last_uid)
                log(f"listening on {mailbox}, resuming from uid {last_uid}")

            # Anything that landed while this process was not running: a reboot, a
            # dropped connection, a machine that was off overnight.
            pending = fetch_since(conn, last_uid, Listed(roster_path), account)
            if len(pending) > 1:
                emit(f"[mail] catching up — {len(pending)} messages arrived while offline")
            for uid, fields in pending:
                record(journal_path, ev.mail_event(
                    account=account, mailbox=mailbox, uidvalidity=validity, uid=uid, **fields))
                # Only now. The record is on disk and flushed, so acknowledging
                # this UID cannot outlive the thing it is acknowledging.
                last_uid = uid
                state = save_state(state_path, mailbox, validity, last_uid, telemetry)

            # Settles anything owed from an earlier outage before saying it is over.
            faults.recovered()
            if telemetry.get("imap_last_disconnect_at") and telemetry.get("imap_current_backoff_seconds"):
                telemetry["imap_last_recovered_at"] = timestamp()
            telemetry["imap_current_backoff_seconds"] = 0
            state = save_state(state_path, mailbox, validity, last_uid, telemetry)
            backoff = BACKOFF_MIN

            while not _stop:
                idle(conn, IDLE_REFRESH)
                state = save_state(state_path, mailbox, validity, last_uid, telemetry)
                # Check unconditionally, not only when IDLE reported a change:
                # mail landing between DONE and the next IDLE produces no EXISTS we
                # can see, and would sit unnoticed until the *next* message arrived.
                found = False
                # Re-read the roster every batch. Adding someone takes effect on
                # their next message, with no restart and no lost notification.
                for uid, fields in fetch_since(conn, last_uid, Listed(roster_path), account):
                    record(journal_path, ev.mail_event(
                        account=account, mailbox=mailbox, uidvalidity=validity, uid=uid, **fields))
                    last_uid = uid
                    found = True
                    # Persist per message, not per batch: a crash mid-batch must
                    # not replay what was already reported.
                    state = save_state(state_path, mailbox, validity, last_uid, telemetry)
                if found and once:
                    return 0

        except NotQueued as exc:
            if _stop:
                break
            # The mailbox is fine; the disk is not. The UID was not advanced, so
            # the same messages come back on the next pass. Wait rather than spin.
            faults.fault(f"journal unwritable: {exc}")
            log(f"journal unwritable; retrying in {backoff}s")
            slept = 0
            while slept < backoff and not _stop:
                time.sleep(1)
                slept += 1
            backoff = min(backoff * 2, BACKOFF_MAX)
        except (imaplib.IMAP4.error, ConnectionError, OSError, socket.error) as exc:
            if _stop:
                break
            message = f"connection lost ({type(exc).__name__}: {exc})"
            telemetry["imap_last_disconnect_at"] = timestamp()
            telemetry["imap_last_disconnect_error"] = message
            telemetry["imap_reconnect_attempts"] = int(telemetry.get("imap_reconnect_attempts") or 0) + 1
            record_imap_reconnect(telemetry, telemetry["imap_last_disconnect_at"])
            telemetry["imap_current_backoff_seconds"] = backoff
            try:
                save_state(state_path, mailbox, state.get("uidvalidity"), last_uid, telemetry)
            except UnboundLocalError:
                pass
            faults.fault(message)
            log(f"{message}; retrying in {backoff}s")
            slept = 0
            while slept < backoff and not _stop:
                time.sleep(1)
                slept += 1
            backoff = min(backoff * 2, BACKOFF_MAX)
        finally:
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env", default=None,
                   help="credentials file (default: resolved by harness/paths.py)")
    p.add_argument("--mailbox", default="INBOX")
    p.add_argument("--once", action="store_true", help="exit after the first batch")
    p.add_argument("--state", default=DEFAULT_STATE,
                   help="where to persist the last reported UID ('none' to disable)")
    p.add_argument("--journal", default=DEFAULT_JOURNAL,
                   help="append-only event journal the dispatcher reads")
    p.add_argument("--roster", default=str(DEFAULT_ROSTER),
                   help="trusted-sender list; their mail is tagged 'roster'")
    args = p.parse_args()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    env_path = pathlib.Path(args.env).expanduser() if args.env else env_file()
    if not env_path.is_file():
        log(f"no env file at {env_path}")
        return 1
    return run(
        env_path,
        args.mailbox,
        args.once,
        pathlib.Path(args.state).expanduser(),
        pathlib.Path(args.roster).expanduser(),
        pathlib.Path(args.journal).expanduser(),
    )


if __name__ == "__main__":
    sys.exit(main())
