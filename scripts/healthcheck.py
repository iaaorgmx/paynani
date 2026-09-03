#!/usr/bin/env python3
"""
Whether this install can currently detect mail and deliver it.

Not "is anything wrong right now", which a quiet mailbox answers the same way as
a dead listener. Every check here asks about a mechanism rather than about
traffic, because the failure this project exists to prevent is precisely the one
where everything looks calm and nothing is being seen.

Exits nonzero when mail cannot be detected or cannot be delivered. A backlog
waiting on a runtime that is down is a failure; a backlog moving through a
runtime that is up is not.

One check here asks a question the others do not: whether roster mail that was
delivered is being answered. It is a warning and never a failure, because what
happens after a runtime accepts an event is the runtime's and the agent's, not
this project's. See reply_facts().

    scripts/healthcheck.py            what a person reads
    scripts/healthcheck.py --json     the same thing for a script
"""

import argparse
import calendar
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import event as ev            # noqa: E402
import dispatch as dsp        # noqa: E402
from adapters import ACCEPTED, CONFIG   # noqa: E402
from paths import (env_file, install_root,   # noqa: E402
                   repo_root, roster, runtime_env, state_dir)
from roster import roster_addresses   # noqa: E402

STATE_DIR = state_dir()
LISTENER_STATE = STATE_DIR / "idle.json"
JOURNAL = STATE_DIR / "events.jsonl"
CURSOR = STATE_DIR / "dispatch.offset"
DISPATCH_ERR = STATE_DIR / "dispatch.err.log"
DELIVERY = STATE_DIR / "delivery.json"
IDLE_ERR = STATE_DIR / "idle.err.log"
SENT_LOG = STATE_DIR / "sent.log"

ROSTER = roster()

# scripts/send.sh runs `himalaya message send -a paynani`, and the name is
# spelled here a second time because one caller is shell and the other Python.
# scripts/test_roster_agree.sh pins the two spellings together, the same way it
# already pins the two roster parsers: a check that looked for the wrong account
# would report a healthy install that cannot send.
SEND_ACCOUNT = "paynani"

# Where himalaya reads its own configuration. It honours XDG_CONFIG_HOME, so
# this does too rather than hard-coding the path the documentation quotes.
HIMALAYA_CONFIG = (Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
                   / "himalaya" / "config.toml")

# `[accounts.paynani]`, with or without quotes around the name. Both are TOML
# and himalaya accepts either, so a config written by hand in the second style
# must not read as a missing account.
ACCOUNT_HEADER = re.compile(
    r'^[ \t]*\[accounts\.(?:"' + re.escape(SEND_ACCOUNT) + r'"|'
    + re.escape(SEND_ACCOUNT) + r')\][ \t]*$', re.MULTILINE)

LISTENER_UNIT = "paynani-idle.service"
DISPATCH_UNIT = "paynani-dispatch.service"
LISTENER_LAUNCHD_LABEL = "com.paynani.idle"
DISPATCH_LAUNCHD_LABEL = "com.paynani.dispatch"

# Long enough that a slow delivery is not a fault, short enough that a queue
# nobody is draining is noticed within a working session.
STALE_QUEUE = float(os.environ.get("HEALTH_STALE_QUEUE", 15 * 60))

# How long roster mail may sit answered by nothing before that is worth saying
# out loud. An agent reads the message, does what it asks and then replies, and
# what it was asked to do can legitimately take a while, so this is deliberately
# generous: the failure being looked for is a mailbox nobody is working, not a
# slow reply.
REPLY_GRACE = float(os.environ.get("HEALTH_REPLY_GRACE", 60 * 60))


def load_runtime_env(path=None):
    """
    Layer the installer's `runtime.env` under the real environment.

    The services are handed this file by systemd (`EnvironmentFile=` in
    paynani-dispatch.service). A hand-run healthcheck is handed it by
    nothing at all, and that is a real difference rather than a cosmetic one:
    `adapters/hermes.py` detects its runtime by reading five `HERMES_*`
    variables out of the environment, while `adapters/openclaw.py` detects its
    own by looking for a binary on the host. So this command has always worked
    when run by hand on OpenClaw and could not work on Hermes, where it reported
    no selected runtime on an install whose services were delivering mail.

    Read as data, never sourced. This is the inverse of the
    `generated-runtime-config` branch of `render_artifact()` in
    scripts/install.sh, including the backslash escaping that writes it; change
    both or neither. `runtime.env` holds no secrets — the two Hermes route
    secrets are named by path and never by value — and nothing here prints what
    it read either way.

    The real environment wins, so `PAYNANI_RUNTIME=... scripts/healthcheck.py`
    still overrides the file. Returns the path read, or None when there was
    nothing to read: a manual install, or an OpenClaw host, has no such file and
    that is not a fault.
    """
    path = runtime_env() if path is None else path
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            # Unescaping in this order is safe because the writer's escaping is
            # prefix-free: it doubles backslashes first, then escapes quotes.
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        os.environ.setdefault(name.strip(), value)
    return path


def launchd_state(label):
    """active / loaded / inactive / unknown for a per-user macOS LaunchAgent."""
    try:
        run = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if run.returncode != 0:
        return "inactive"
    if "state = running" in (run.stdout or ""):
        return "active"
    return "loaded"


def unit_state(unit):
    """active / inactive / failed / unknown, without guessing when we cannot ask."""
    if platform.system() == "Darwin":
        labels = {
            LISTENER_UNIT: LISTENER_LAUNCHD_LABEL,
            DISPATCH_UNIT: DISPATCH_LAUNCHD_LABEL,
        }
        return launchd_state(labels.get(unit, unit))
    try:
        run = subprocess.run(["systemctl", "--user", "is-active", unit],
                             capture_output=True, text=True, timeout=5)
        return (run.stdout or "").strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def tail(path, lines=1):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if ln.strip()][-lines:]


def listener_facts():
    out = {"unit": unit_state(LISTENER_UNIT), "mailbox": None,
           "last_uid": None, "uidvalidity": None, "last_error": None}
    try:
        state = json.loads(LISTENER_STATE.read_text())
        out["mailbox"] = state.get("mailbox")
        out["last_uid"] = state.get("last_uid")
        out["uidvalidity"] = state.get("uidvalidity")
    except (OSError, ValueError):
        pass
    last = tail(IDLE_ERR)
    out["last_error"] = last[0] if last else None
    return out


def queue_facts():
    """
    What is waiting, and how long the oldest of it has waited.

    Depth alone says nothing: a burst of mail arriving in the last second looks
    identical to a queue nothing has touched since yesterday. The age is what
    separates them, and it is read from the record rather than the file's mtime,
    which compaction and rotation both disturb.
    """
    out = {"pending": 0, "oldest_age_seconds": None, "damaged_at": None,
           "cursor": ev.read_cursor(CURSOR), "journal_bytes": 0}
    try:
        out["journal_bytes"] = JOURNAL.stat().st_size
    except OSError:
        return out

    oldest = None
    for record, _ in ev.read_from(JOURNAL, out["cursor"]):
        if isinstance(record, ev.Corrupt):
            out["damaged_at"] = record.offset
            break
        out["pending"] += 1
        if oldest is None:
            oldest = record.get("observed_at")

    if oldest:
        try:
            # timegm, not mktime: the stamp is UTC and mktime would read it as
            # local, which puts the age out by the offset and turns a stale queue
            # into a fresh one on any host east of Greenwich.
            seen = calendar.timegm(time.strptime(oldest, "%Y-%m-%dT%H:%M:%SZ"))
            out["oldest_age_seconds"] = max(0, int(time.time() - seen))
        except (ValueError, OverflowError):
            pass
    return out


def delivery_facts():
    """
    What the runtime last said, as the dispatcher recorded it.

    Read rather than inferred, and never reconstructed from a reachability
    check: a gateway answering now is not evidence that something accepted an
    hour ago was ever acted on. Where a runtime only acknowledges receipt, that
    distinction is the difference between "we handed it over" and "it was done",
    and only the first is ever known here.
    """
    out = {"last_accepted": None, "last_error": None}
    try:
        stored = json.loads(DELIVERY.read_text())
    except (OSError, ValueError):
        return out
    for key in out:
        entry = stored.get(key)
        if isinstance(entry, dict):
            out[key] = {k: entry.get(k) for k in ("event_id", "at", "runtime", "detail")}
    return out


def _stamp_seconds(stamp):
    """A `%Y-%m-%dT%H:%M:%SZ` stamp as epoch seconds, or None if it is not one."""
    try:
        # timegm, not mktime, for the same reason as queue_facts(): the stamps
        # this project writes are UTC, and reading them as local time moves every
        # age by the host's offset.
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError, OverflowError):
        return None


def _send_records():
    """
    Every send this command can still see, newest stamp last.

    Two files, not one: `sent.log` matches `rotate_logs.py`'s `*.log` glob, so a
    weekly rotation leaves it empty with the history in `sent.log.1`. Reading
    only the live file would report "nothing has ever been sent" on a host that
    sent something yesterday, which is precisely the wrong answer to give about
    an audit log.
    """
    stamps = []
    present = False
    for path in (SENT_LOG, SENT_LOG.with_name(SENT_LOG.name + ".1")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        present = True
        for line in text.splitlines():
            if not line.strip():
                continue
            seconds = _stamp_seconds(line.split("\t", 1)[0].strip())
            if seconds is not None:
                stamps.append(seconds)
    return present, sorted(stamps)


def reply_facts(cursor):
    """
    Whether roster mail that was delivered is being answered.

    Every other check here asks whether mail can move. This one asks whether the
    loop closes, which is a different question and was unanswerable until #117
    started recording sends: the record of what came in has always existed, and
    there was nothing to compare it against.

    **Reported, never judged**, on the same grounds as spool_facts(). Roster mail
    with no reply after it is not proof of a fault — the answer may be in
    progress, the human may have handled it out of band, the message may not have
    warranted one. What this can say is that mail a human vouched for was handed
    to the runtime and nothing went back out afterwards, and that a person should
    look. It cannot say the agent failed, and it must not imply it.

    Only records the dispatcher has already delivered are counted. Mail still
    queued is queue_facts()'s subject, and holding an agent responsible for a
    message it was never handed would put the blame one process too far along.

    The counts are "since the journal was last compacted", never "since this
    install began": the journal is a queue the dispatcher empties once everything
    in it has been delivered. Both callers of this say so in what they print.
    """
    out = {"sent_log": str(SENT_LOG), "sent_log_present": False,
           "sends_seen": None, "last_sent_at": None,
           "roster_delivered": 0, "roster_newest_at": None,
           "unanswered_age_seconds": None}

    present, stamps = _send_records()
    out["sent_log_present"] = present
    if present:
        out["sends_seen"] = len(stamps)
        if stamps:
            out["last_sent_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime(stamps[-1]))

    newest = None
    for record, end in ev.read_from(JOURNAL, 0):
        if isinstance(record, ev.Corrupt):
            break
        if end > cursor:
            break
        if record.get("event_type") != ev.MAIL_RECEIVED:
            continue
        if not record.get("roster_match"):
            continue
        out["roster_delivered"] += 1
        seen = _stamp_seconds(record.get("observed_at"))
        if seen is not None and (newest is None or seen > newest):
            newest = seen

    if newest is None:
        return out
    out["roster_newest_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(newest))
    if stamps and stamps[-1] >= newest:
        return out
    out["unanswered_age_seconds"] = max(0, int(time.time() - newest))
    return out


def spool_facts(selected):
    """
    How much of the Claude Code spool no session has picked up yet.

    **Reported, never judged.** Unread bytes with no session open is the normal
    resting state of this runtime, not a fault — mail waits in the spool exactly
    so a session that starts tomorrow still sees it.

    The check the PRD originally asked for, "unread bytes and no watch attached",
    is not implementable honestly: a Monitor is armed inside a session and cannot
    be seen from out here. Rather than infer it from a proxy and call the guess a
    health state, this reports what is true and says what it does not know.
    """
    if selected != "claudecode":
        return None
    out = {"spool": None, "bytes_total": 0, "bytes_unread": 0,
           "session_arming": "unobservable"}
    try:
        from adapters import claudecode as cc
        spool = cc.spool_path()
    except Exception:
        return out
    out["spool"] = str(spool)
    try:
        out["bytes_total"] = spool.stat().st_size
    except OSError:
        return out
    try:
        offset = int((spool.parent / "session.offset").read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        offset = 0
    out["bytes_unread"] = max(0, out["bytes_total"] - offset)
    return out


def runtime_facts():
    """
    Which runtime is selected, and whether it could take an event right now.

    `check()` proves the adapter can reach its runtime. It does not prove an
    event would arrive anywhere a person is looking: for a webhook runtime a
    healthy gateway says nothing about whether the route, its secret, or its
    delivery target are right. Said here rather than implied, because "health:
    ok" is exactly the phrase somebody stops reading after.
    """
    out = {"selected": None, "available": dsp.available(), "reachable": None,
           "detail": None, "proves_route_readiness": False,
           "runtime_env": None}
    # Before anything reads the environment: on a Hermes install every value
    # that decides the answers below arrives in this file and nowhere else.
    loaded = load_runtime_env()
    out["runtime_env"] = str(loaded) if loaded else None
    try:
        out["selected"] = dsp.select_runtime(os.environ.get("PAYNANI_RUNTIME", "auto"))
    except SystemExit as exc:
        out["detail"] = str(exc)
        return out
    try:
        adapter = dsp.load_adapter(out["selected"])
    except SystemExit as exc:
        out["detail"] = str(exc)
        return out

    result = adapter.check()
    out["reachable"] = result.status == ACCEPTED
    out["detail"] = result.detail or None
    return out


def roster_facts():
    """
    Whether there is anybody this install may write to, or act for.

    Read here for the first time, and the omission was the point: an empty or
    absent allowlist is the one fault with no symptom at all. `send.sh` refuses
    every address and arriving mail stops being tagged `roster`, which looks
    exactly like nobody having written. `harness/paths.py` says that about this
    file in so many words, and nothing checked it.

    Parsed with `roster.roster_addresses`, the same function the listener uses,
    so this cannot report a list the listener does not see.
    """
    out = {"path": str(ROSTER), "present": False, "addresses": 0}
    try:
        out["present"] = ROSTER.is_file()
    except OSError:
        return out
    out["addresses"] = len(roster_addresses(ROSTER))
    return out


def himalaya_facts():
    """
    Whether the account `send.sh` sends with exists.

    Everything else in this file watches mail coming in. This is the one thing
    that has to be true for mail to go out, and it lives in a file this project
    does not own: an install can pass every other check with credentials in
    `.env` and still have no `[accounts.paynani]` block for himalaya to send
    through. Reported in #1 from a real host, where four green checks stood
    while sending was impossible.

    Only the account block is looked for. Whether its settings are correct is a
    question for `himalaya account check`, which needs the network; whether it
    is there at all does not.
    """
    out = {"config": str(HIMALAYA_CONFIG), "account": SEND_ACCOUNT,
           "config_present": False, "account_present": False}
    try:
        text = HIMALAYA_CONFIG.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    out["config_present"] = True
    out["account_present"] = bool(ACCOUNT_HEADER.search(text))
    return out


def config_facts():
    out = {"env": None, "env_mode": None, "env_present": False,
           "repo": str(repo_root()), "version": None}
    path = env_file()
    out["env"] = str(path)
    try:
        st = path.stat()
        out["env_present"] = True
        out["env_mode"] = oct(st.st_mode & 0o777)
    except OSError:
        pass
    try:
        run = subprocess.run([str(repo_root() / "scripts/version.sh"), "--line"],
                             capture_output=True, text=True, timeout=20)
        out["version"] = (run.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def assess(facts):
    """
    The failures, in the order they stop mail.

    Detection first: nothing downstream matters if the mailbox is not being
    watched. Then delivery. A queue is only a fault when nothing is draining it.
    """
    problems = []
    warnings = []

    listener, queue, runtime, config = (facts["listener"], facts["queue"],
                                        facts["runtime"], facts["config"])

    if listener["unit"] != "active":
        problems.append(f"the listener is {listener['unit']}: no new mail is being detected at all")
    if listener["last_uid"] is None:
        warnings.append("the listener has no recorded position yet, so it has not "
                        "completed a first pass over the mailbox")

    if facts["dispatcher_unit"] != "active":
        problems.append(f"the dispatcher is {facts['dispatcher_unit']}: mail is being "
                        "journalled but nothing is delivering it")

    if runtime["selected"] is None:
        detail = (runtime["detail"] or "unknown reason").rstrip()
        if not runtime["runtime_env"]:
            # The difference between "no runtime here" and "this command could
            # not see the one that is here" is the whole of #61, and it sends
            # the next person to a different place.
            detail = detail.rstrip(".") + (
                f". No runtime.env was read from {runtime_env()}, so a runtime "
                "configured only by that file is invisible to this command")
        problems.append("no runtime is selected: " + detail)
    elif runtime["reachable"] is False:
        problems.append(f"the {runtime['selected']} runtime cannot be reached: "
                        + (runtime["detail"] or "no detail"))

    if queue["damaged_at"] is not None:
        problems.append(f"the event journal has a damaged record at byte {queue['damaged_at']}; "
                        "delivery has stopped there and everything behind it is waiting")

    if queue["pending"] and queue["oldest_age_seconds"] is not None \
            and queue["oldest_age_seconds"] > STALE_QUEUE:
        problems.append(f"{queue['pending']} event(s) queued, the oldest for "
                        f"{queue['oldest_age_seconds'] // 60} minutes: it is not moving")

    # A warning and never a problem. Delivery is working in this case — that is
    # what makes it worth saying at all — and the two readings of it are answered
    # in different places: the agent was told and did not act, or nothing was
    # attached to be told (#108). This command cannot tell them apart, so it
    # reports the shape and says so rather than picking one.
    reply = facts.get("reply") or {}
    unanswered = reply.get("unanswered_age_seconds")
    # On Claude Code, "delivered" means the bytes are in the spool, and mail
    # waiting there for a session that has not started yet is the resting state
    # of that runtime rather than a fault — spool_facts() says so, and this must
    # agree with it. Unread bytes mean the mail demonstrably has not reached an
    # agent, so there is nobody to have failed to answer it.
    spool = facts.get("spool") or {}
    unread_in_spool = bool(spool.get("bytes_unread"))
    if unanswered is not None and unanswered > REPLY_GRACE and not unread_in_spool:
        warnings.append(
            f"{reply['roster_delivered']} roster message(s) have been delivered "
            f"and nothing has been sent since the newest one, {unanswered // 60} "
            "minutes ago. Delivery is healthy, so this is about what happened "
            "after it: either the agent was told and did not reply, or nothing "
            "was attached to be told. The standing rule is in AGENTS.md, "
            "\"roster.md decides what a message is\" — check it reached the "
            "agent's own persistent instructions")
        if not reply.get("sent_log_present"):
            # Two readings again, and both are worth the extra sentence: an
            # install that has genuinely never replied to anyone, or one older
            # than the record itself.
            warnings.append(
                f"there is no send record at {reply['sent_log']} at all, so this "
                "install has either never sent anything or predates the log")

    if not config["env_present"]:
        problems.append(f"no credentials at {config['env']}")
    elif config["env_mode"] not in ("0o600", "0o400"):
        warnings.append(f"credentials at {config['env']} are mode {config['env_mode']}, "
                        "which is more readable than they should be")

    # The last two are a different kind of failure from everything above, and
    # they are problems rather than warnings for one reason: mail does not move.
    # Above, something that should be running is not. Here, everything runs
    # perfectly and the install still cannot do the thing it exists to do — it
    # may write to nobody, or it has no account to write with. That is the
    # quietest failure this command can be asked about, and it reported healthy
    # through both of them (#6).
    ros = facts["roster"]
    if not ros["present"]:
        problems.append(f"no roster at {ros['path']}: nobody may be written to, and "
                        "no arriving mail becomes actionable")
    elif not ros["addresses"]:
        problems.append(f"the roster at {ros['path']} lists no address: sending "
                        "refuses everyone and arriving mail is never tagged "
                        "'roster', which looks exactly like nobody having written")

    him = facts["himalaya"]
    if not him["config_present"]:
        problems.append(f"no himalaya configuration at {him['config']}: "
                        "scripts/send.sh has nothing to send through")
    elif not him["account_present"]:
        problems.append(f"the himalaya configuration at {him['config']} has no "
                        f"[accounts.{him['account']}] block, which is the account "
                        "scripts/send.sh sends with: sending is impossible")

    return problems, warnings


def render(facts, problems, warnings):
    listener, queue, runtime, config = (facts["listener"], facts["queue"],
                                        facts["runtime"], facts["config"])
    out = []
    out.append(f"runtime      {runtime['selected'] or 'NONE SELECTED'}"
               + (f"  (available: {', '.join(runtime['available'])})" if runtime["available"] else ""))
    if runtime["runtime_env"]:
        out.append(f"             configured by {runtime['runtime_env']}")
    spool = facts.get("spool")
    if spool and spool.get("spool"):
        out.append(f"spool        {spool['spool']}")
        out.append(f"             {spool['bytes_unread']} byte(s) not yet picked up "
                   f"by a session, of {spool['bytes_total']}")
        out.append("             whether a session has armed a watch is not "
                   "observable from here; unread bytes with no session open is normal")
    if runtime["selected"]:
        reach = "reachable" if runtime["reachable"] else "NOT REACHABLE"
        out.append(f"             {reach}" + (f": {runtime['detail']}" if runtime["detail"] else ""))
        out.append("             this proves the runtime answers, not that a delivered "
                   "event reaches anyone")
    out.append(f"listener     {listener['unit']}"
               + (f", {listener['mailbox']} at uid {listener['last_uid']}"
                  if listener["last_uid"] is not None else ", no position recorded yet"))
    if listener["last_error"]:
        out.append(f"             last diagnostic: {listener['last_error']}")
    out.append(f"dispatcher   {facts['dispatcher_unit']}")
    delivery = facts["delivery"]
    accepted = delivery["last_accepted"]
    if accepted:
        out.append(f"             last accepted {accepted['event_id']} "
                   f"by {accepted['runtime']} at {accepted['at']}")
        if accepted["detail"]:
            out.append(f"             runtime said: {accepted['detail']}")
    else:
        out.append("             nothing has been accepted by a runtime yet")
    if delivery["last_error"]:
        err = delivery["last_error"]
        out.append(f"             last refusal {err['event_id']} at {err['at']}: {err['detail']}")
    age = queue["oldest_age_seconds"]
    out.append(f"queue        {queue['pending']} waiting"
               + (f", oldest {age // 60}m{age % 60:02d}s" if age is not None else "")
               + f"  (cursor {queue['cursor']} of {queue['journal_bytes']} bytes)")
    if queue["damaged_at"] is not None:
        out.append(f"             DAMAGED RECORD at byte {queue['damaged_at']}")
    reply = facts.get("reply")
    if reply:
        if reply["sent_log_present"]:
            sends = f"{reply['sends_seen']} send(s) recorded"
            if reply["last_sent_at"]:
                sends += f", last {reply['last_sent_at']}"
        else:
            sends = "no send record yet"
        out.append(f"replies      {reply['roster_delivered']} roster message(s) "
                   f"delivered; {sends}")
        if reply["unanswered_age_seconds"] is not None:
            out.append(f"             nothing sent since the newest one at "
                       f"{reply['roster_newest_at']}")
        out.append("             counted since the journal was last compacted, and "
                   "whether a reply was owed is not judged here")
    out.append(f"credentials  {config['env']}"
               + (f"  mode {config['env_mode']}" if config["env_present"] else "  MISSING"))
    ros = facts["roster"]
    out.append(f"roster       {ros['path']}"
               + (f"  {ros['addresses']} address(es)" if ros["present"] else "  MISSING"))
    him = facts["himalaya"]
    if not him["config_present"]:
        account = "no himalaya configuration"
    elif him["account_present"]:
        account = f"[accounts.{him['account']}] present"
    else:
        account = f"[accounts.{him['account']}] MISSING"
    out.append(f"sending      {him['config']}  {account}")
    out.append(f"repo         {config['repo']}")
    if config["version"]:
        out.append(f"version      {config['version']}")

    if not facts["delivery"]["last_accepted"] and not facts["delivery"]["last_error"]:
        recent = tail(DISPATCH_ERR)
        if recent:
            out.append(f"             dispatcher log: {recent[0]}")

    if problems:
        out.append("")
        out.append("NOT HEALTHY:")
        out.extend(f"  - {p}" for p in problems)
    if warnings:
        out.append("")
        out.append("worth knowing:")
        out.extend(f"  - {w}" for w in warnings)
    if not problems:
        out.append("")
        out.append("Mail can be detected and delivered. An empty queue here means the "
                   "path is clear,")
        out.append("not that the mailbox is quiet; those are different facts and only "
                   "the first is checked.")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    facts = {
        "listener": listener_facts(),
        "dispatcher_unit": unit_state(DISPATCH_UNIT),
        "queue": queue_facts(),
        "runtime": runtime_facts(),
        "delivery": delivery_facts(),
        "config": config_facts(),
        "roster": roster_facts(),
        "himalaya": himalaya_facts(),
    }
    facts["spool"] = spool_facts(facts["runtime"].get("selected"))
    facts["reply"] = reply_facts(facts["queue"]["cursor"])
    problems, warnings = assess(facts)

    if args.json:
        print(json.dumps({"facts": facts, "problems": problems,
                          "warnings": warnings, "healthy": not problems},
                         indent=2, sort_keys=True))
    else:
        print(render(facts, problems, warnings))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
