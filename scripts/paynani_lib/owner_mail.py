"""
Mail the owner writes from PaynaniWeb, «Nuevo correo» (#590 change 2, core N1 in #591).

The agent writes only to its roster: `scripts/send.sh` refuses anyone else with
exit 2, and nothing here changes that. `send.sh` has no new flag, and the API
still goes through it. The owner may write to anyone, after typing the web
password again when an address is outside the roster (Q5 and Q8 on #590). This
module is the way PaynaniWeb does that, and only PaynaniWeb uses it. AGENTS.md
forbids agents to.

**Authorization.** The web checks the password and then calls `authorize()`,
which returns a `Grant`: one use, 60 s, bound to the account, the canonical
recipients and the operation `owner_send`. It lives only in the memory of the
PaynaniWeb process. `send()` consumes it under a lock, so a second use fails
even from another thread. Nothing is written to disk, so there is no file to
forge or symlink to follow.

This is an operational authorization, not a privilege separation. It guards
against mistakes and against mail that tries to talk the agent into writing to
someone new. It is no boundary against malicious code running as the same
system user: that user can already read `.env` and run himalaya directly. Real
separation needs PaynaniWeb under its own system user with its own secrets,
which #591 leaves for a separate issue. Within that limit, `send.sh` stays closed
to anyone outside the roster, and every send outside it is recorded and reported
to the owner.

Authorization and sending happen in the same request of the same PaynaniWeb
process. A grant lost to a restart or another worker fails closed.

**The send** is the same as `send.sh` makes for a plain-text message: the same
From (the agent's, or the additional account's), signature, headers, the SMTP
envelope with Bcc kept out of the headers, the copy in Sent (`sent_copy.py`) and
the line in `state/sent.log`.

**The record.** Every call leaves one line in `state/owner_sends.jsonl`: when,
who (`by`), the account, the recipients, which were outside the roster, the
result and the Message-ID. Never the subject, the body or a password.

**The notice.** When an address outside the roster got the message and the grant
carries `owner_email` (the PaynaniWeb user's address), the owner gets a short
notice through plain `send.sh`, so it still meets the roster check and cannot
come back here. `Result.notice` says whether it went out. It never changes
`ok`: the message itself has already left.
"""
from __future__ import annotations

import email.utils
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from email.header import Header
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_REPO_ROOT / "scripts"), str(_REPO_ROOT / "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import paths  # noqa: E402
import roster as roster_mod  # noqa: E402

SEND_SH = _REPO_ROOT / "scripts" / "send.sh"
SENT_COPY = _REPO_ROOT / "scripts" / "paynani_lib" / "sent_copy.py"
SENDS_LOG = "owner_sends.jsonl"
OPERATION = "owner_send"
GRANT_TTL = 60
TIMEOUT = 120
MAX_SUBJECT = 998

CODES = ("sent", "invalid_address", "no_recipients", "unknown_account", "not_authorized", "send_failed")

# One plain address: no display name, no list, nothing a header could split on.
_FORBIDDEN = set(" \t\r\n,;<>\"'()[]\\:")


@dataclass
class Result:
    ok: bool
    code: str
    message_id: str = ""
    sent_copy: str = ""          # saved | skipped | failed, as in sent.log; "" when nothing went out
    outside_roster: list[str] = field(default_factory=list)
    notice: str = "skipped"      # sent | failed | skipped
    detail: str = ""             # never the subject, the body or a password


class Grant:
    """
    What `authorize()` returns. Opaque to the web: it only hands it back to
    `send()`. It cannot be copied, pickled or turned into JSON, and `send()`
    accepts only the very object `authorize()` registered.
    """
    __slots__ = ("_token", "account", "to", "cc", "bcc", "by", "owner_email", "operation", "_expires")

    def __init__(self, token, account, to, cc, bcc, by, owner_email, expires):
        for name, value in (("_token", token), ("account", account), ("to", tuple(to)), ("cc", tuple(cc)),
                            ("bcc", tuple(bcc)), ("by", by), ("owner_email", owner_email),
                            ("operation", OPERATION), ("_expires", expires)):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError("a grant cannot be changed")

    def __reduce__(self):
        raise TypeError("a grant cannot be serialized")

    def __copy__(self):
        raise TypeError("a grant cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("a grant cannot be copied")

    def __repr__(self):
        return f"<owner_mail.Grant {self.account} to={len(self.to)} cc={len(self.cc)} bcc={len(self.bcc)}>"


class UnknownAccount(Exception):
    pass


class InvalidAddress(ValueError):
    pass


# --- addresses -------------------------------------------------------------------

def canonical(address: str) -> str:
    """
    The form two addresses are compared in: no spaces, NFC, local part lower case
    (as `roster.normalise` does), domain in IDNA (punycode) and lower case.
    Raises InvalidAddress for anything that is not one plain address.
    """
    raw = unicodedata.normalize("NFC", re.sub(r"\s+", "", address or ""))
    if raw.count("@") != 1 or any(ch in _FORBIDDEN for ch in raw) or any(ord(ch) < 32 for ch in raw):
        raise InvalidAddress(address)
    local, domain = raw.split("@")
    if not local or not domain or "." not in domain.strip(".") or domain != domain.strip("."):
        raise InvalidAddress(address)
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidAddress(address) from exc
    return f"{local.lower()}@{domain.lower()}"


def valid_address(address: str) -> bool:
    try:
        canonical(address)
        return True
    except InvalidAddress:
        return False


def _split(to, cc, bcc) -> tuple[list[str], list[str], list[str]]:
    """Canonical To, Cc and Bcc, with no address repeated in or across them (To wins, then Cc)."""
    seen: set[str] = set()
    out = []
    for group in (to or [], cc or [], bcc or []):
        kept = []
        for address in group:
            key = canonical(address)
            if key not in seen:
                seen.add(key)
                kept.append(key)
        out.append(kept)
    return out[0], out[1], out[2]


def _is_main(account: str | None) -> bool:
    return account in (None, "", "main")


def _account_entry(account: str | None) -> dict | None:
    if _is_main(account):
        return None
    from paynani_lib import accounts

    try:
        return accounts.get(account, Path(_env_file()).parent / accounts.FILENAME)
    except accounts.AccountsError as exc:
        raise UnknownAccount(str(exc)) from exc


def roster_for(account: str | None) -> Path:
    """`roster.md` for the agent's own account; the account's `rosters/<id>.md` for another."""
    entry = _account_entry(account)
    if entry is None:
        override = os.environ.get("ROSTER")
        return Path(override) if override else paths.roster()
    from paynani_lib import accounts

    return accounts.roster_path(entry, Path(_env_file()).parent / accounts.FILENAME)


def outside_roster(account: str | None, addresses: list[str]) -> list[str]:
    """
    The addresses that are not on that account's roster, canonical and without
    repeats, in order. Raises InvalidAddress or UnknownAccount.
    """
    allowed = {canonical(a) for a in roster_mod.roster_addresses(roster_for(account)) if valid_address(a)}
    out: list[str] = []
    for address in addresses:
        key = canonical(address)
        if key not in allowed and key not in out:
            out.append(key)
    return out


# --- the grant -------------------------------------------------------------------

_lock = threading.Lock()
_live: dict[str, Grant] = {}


def authorize(account: str | None, to, cc, bcc, *, by: str, owner_email: str | None = None,
              now: float | None = None) -> Grant:
    """
    Call only after the web checked the owner's password (when `outside_roster()`
    is not empty) or the session (when it is), in the same request and process
    that will call `send()`. One use, GRANT_TTL seconds on the monotonic clock.
    `owner_email` is where the notice goes; it is bound to the grant too.
    Raises InvalidAddress or UnknownAccount.
    """
    to_c, cc_c, bcc_c = _split(to, cc, bcc)
    _account_entry(account)  # unknown account: raise now, not at send time
    owner = canonical(owner_email) if owner_email else None
    now = time.monotonic() if now is None else now
    grant = Grant(secrets.token_hex(32), "main" if _is_main(account) else account, to_c, cc_c, bcc_c,
                  by, owner, now + GRANT_TTL)
    with _lock:
        for token in [t for t, (_, g) in _live.items() if g._expires < now]:
            del _live[token]
        _live[grant._token] = (_fingerprint(grant), grant)
    return grant


def _fingerprint(grant: Grant) -> tuple:
    return (grant.operation, grant.account, grant.to, grant.cc, grant.bcc, grant.by, grant.owner_email,
            grant._expires)


def _consume(grant, now: float) -> str | None:
    """None when this is the live grant we issued, unchanged; otherwise why not. Removed either way."""
    if not isinstance(grant, Grant):
        return "no grant"
    with _lock:
        issued = _live.pop(getattr(grant, "_token", ""), None)
    if issued is None:
        return "grant unknown or already used"
    fingerprint, original = issued
    if original is not grant or _fingerprint(grant) != fingerprint or grant.operation != OPERATION:
        return "grant does not match what was authorized"
    if now > grant._expires:
        return "grant expired"
    return None


# --- the message -------------------------------------------------------------------

def _env_file() -> str:
    return os.environ.get("ENV_FILE") or str(paths.env_file())


def _env_values(path: str) -> dict:
    from paynani_lib.envfile import _KEY_VALUE_RE

    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    out = {}
    for line in re.split(r"\r\n|\n|\r", raw):
        m = _KEY_VALUE_RE.match(line)
        if m and m.group(1) not in out:
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            out[m.group(1)] = value
    return out


def _sender(account: str | None) -> tuple[str, str, str, str]:
    """(himalaya account, from address, display name, signature path or "")."""
    entry = _account_entry(account)
    if entry is None:
        env = _env_values(_env_file())
        address = env.get("PAYNANI_EMAIL") or env.get("AGENT_EMAIL_ACCOUNT") or ""
        name = env.get("PAYNANI_FROM_NAME") or env.get("AGENT_EMAIL_FROM_NAME") or ""
        signature = env.get("PAYNANI_SIGNATURE_FILE") or env.get("AGENT_EMAIL_SIGNATURE_FILE") or ""
        himalaya = "paynani"
    else:
        from paynani_lib import accounts

        if not entry.get("smtp"):
            raise UnknownAccount(f"account {account!r} has no smtp server")
        address = entry["email"]
        name = str(entry.get("from_name") or "")
        signature = str(accounts.signature_path(entry, Path(_env_file()).parent / accounts.FILENAME) or "")
        himalaya = f"paynani-{account}"
    address = "".join(address.split())
    name = " ".join(name.split())
    if "@" not in address:
        raise UnknownAccount("no sender address configured")
    return himalaya, address, name, signature.strip()


def _encode(value: str) -> str:
    return Header(value, "utf-8").encode() if any(ord(c) > 126 for c in value) else value


def build_message(from_addr: str, from_name: str, to, cc, subject: str, body: str, signature: str) -> tuple[str, str]:
    """(message text, Message-ID), shaped like send.sh's single-part plain message."""
    domain = from_addr.rsplit("@", 1)[1]
    msgid = f"<{time.strftime('%Y%m%d%H%M%S', time.gmtime())}.{os.getpid()}.{secrets.randbelow(32768)}@{domain}>"
    if from_name and any(ord(c) > 126 for c in from_name):
        from_hdr = f"{_encode(from_name)} <{from_addr}>"
    elif from_name:
        quoted = from_name.replace("\\", "\\\\").replace('"', '\\"')
        from_hdr = f'"{quoted}" <{from_addr}>'
    else:
        from_hdr = from_addr
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    if signature:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n-- \n" + Path(signature).read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    lines = [f"Date: {email.utils.formatdate(localtime=True)}", f"Message-ID: {msgid}", "MIME-Version: 1.0",
             "Content-Type: text/plain; charset=UTF-8", "Content-Transfer-Encoding: 8bit", f"From: {from_hdr}",
             f"To: {', '.join(to)}"]
    if cc:
        lines.append(f"Cc: {', '.join(cc)}")
    lines.append(f"Subject: {_encode(subject)}")
    return "\n".join(lines) + "\n\n" + text, msgid


def _sent_log(state_dir: Path, to, cc, bcc, subject, copy_state, msgid, account) -> None:
    line = "\t".join([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), f"to={', '.join(to)}",
                      f"cc={', '.join(cc)}", f"bcc={', '.join(bcc)}", f"subject={subject}",
                      f"sent-copy={copy_state}", f"message-id={msgid}"])
    if not _is_main(account):
        line += f"\taccount={account}"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / "sent.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        print(f"warning: sent, but could not record it in {state_dir / 'sent.log'}", file=sys.stderr)


def _record(state_dir: Path, entry: dict) -> bool:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / SENDS_LOG).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except OSError:
        print(f"warning: could not record the owner send in {state_dir / SENDS_LOG}", file=sys.stderr)
        return False


def _notice(owner_email: str, account: str, outside: list[str], msgid: str) -> str:
    """Tell the owner which addresses outside the roster got a message. Never the subject or body."""
    body = ("PaynaniWeb sent a message to addresses that are not on the roster"
            + ("" if _is_main(account) else f" of the account {account}") + ":\n\n"
            + "".join(f"  {a}\n" for a in outside)
            + f"\nMessage-ID: {msgid}\n\nIf you did not send it, change the PaynaniWeb password.\n")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
        fh.write(body)
        bodyfile = fh.name
    try:
        done = subprocess.run(["bash", str(SEND_SH), owner_email, "[PaynaniWeb] Sent outside the roster", bodyfile],
                              capture_output=True, text=True, timeout=TIMEOUT)
        return "sent" if done.returncode == 0 else "failed"
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    finally:
        Path(bodyfile).unlink(missing_ok=True)


def send(grant: Grant, subject: str, body: str, *, state_dir: Path | None = None,
         now: float | None = None) -> Result:
    """
    Send what `grant` authorizes. The grant is used up, whatever the result, and a
    lost or refused grant is never retried here: the web asks the owner again.
    """
    state_dir = Path(state_dir) if state_dir else paths.state_dir()
    now = time.monotonic() if now is None else now
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "by": getattr(grant, "by", ""), "account": getattr(grant, "account", ""),
             "to": list(getattr(grant, "to", ())), "cc": list(getattr(grant, "cc", ())),
             "bcc": list(getattr(grant, "bcc", ()))}

    def finish(result: Result) -> Result:
        _record(state_dir, {**entry, "outside_roster": result.outside_roster, "ok": result.ok,
                            "code": result.code, "message_id": result.message_id, "notice": result.notice})
        return result

    reason = _consume(grant, now)
    if reason:
        return finish(Result(False, "not_authorized", detail=reason))
    if not grant.to:
        return finish(Result(False, "no_recipients", detail="at least one To address is required"))
    subject = " ".join((subject or "").split())[:MAX_SUBJECT]
    everyone = list(grant.to + grant.cc + grant.bcc)
    try:
        outside = outside_roster(grant.account, everyone)
        himalaya, from_addr, from_name, signature = _sender(grant.account)
    except UnknownAccount as exc:
        return finish(Result(False, "unknown_account", detail=str(exc)))
    except InvalidAddress as exc:
        return finish(Result(False, "invalid_address", detail=str(exc)))
    if signature and not os.access(signature, os.R_OK):
        return finish(Result(False, "send_failed", outside_roster=outside, detail="signature file is not readable"))

    message, msgid = build_message(from_addr, from_name, grant.to, grant.cc, subject, body, signature)
    cmd = ["himalaya", "-a", himalaya, "smtp", "send", "--mail-from", from_addr]
    for address in everyone:
        cmd += ["--rcpt-to", address]
    fd, message_file = tempfile.mkstemp(prefix="paynani-owner-send.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(message)
        try:
            with open(message_file, "rb") as fh:
                done = subprocess.run(cmd, stdin=fh, capture_output=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return finish(Result(False, "send_failed", outside_roster=outside, detail=type(exc).__name__))
        if done.returncode != 0:
            last = next((l for l in reversed(done.stderr.decode("utf-8", "replace").splitlines()) if l.strip()), "")
            return finish(Result(False, "send_failed", outside_roster=outside,
                                 detail=last[:300] or f"himalaya exit {done.returncode}"))
        try:
            copy = subprocess.run([sys.executable, str(SENT_COPY), himalaya, message_file],
                                  capture_output=True, text=True, timeout=TIMEOUT).stdout.split(" ", 1)[0].strip()
        except (OSError, subprocess.TimeoutExpired):
            copy = "failed"
    finally:
        Path(message_file).unlink(missing_ok=True)
    copy = copy if copy in ("saved", "skipped", "failed") else "failed"
    _sent_log(state_dir, grant.to, grant.cc, grant.bcc, subject, copy, msgid, grant.account)
    result = Result(True, "sent", message_id=msgid, sent_copy=copy, outside_roster=outside)
    if outside and grant.owner_email:
        result.notice = _notice(grant.owner_email, grant.account, outside, msgid)
    return finish(result)
