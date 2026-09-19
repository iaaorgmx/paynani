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
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import event as ev            # noqa: E402
import dispatch as dsp        # noqa: E402
from adapters import ACCEPTED, CONFIG   # noqa: E402
from paths import (env_file, harness_env_files, install_root,   # noqa: E402
                   recorded_env, repo_root, roster, runtime_env, state_dir)
from roster import notifiers, roster_addresses   # noqa: E402

# Taken at import, before runtime_facts() calls load_runtime_env() and layers
# runtime.env into os.environ. After that call, PAYNANI_ENV is in the environment
# whether a person put it there or the installer recorded it, and env_source()
# cannot tell the two apart by looking. Snapshot first, ask later.
ENV_OVERRIDE_AT_START = (os.environ.get("PAYNANI_ENV") or "").strip()

STATE_DIR = state_dir()
LISTENER_STATE = STATE_DIR / "idle.json"
JOURNAL = STATE_DIR / "events.jsonl"
CURSOR = STATE_DIR / "dispatch.offset"
DISPATCH_ERR = STATE_DIR / "dispatch.err.log"
DELIVERY = STATE_DIR / "delivery.json"
IDLE_ERR = STATE_DIR / "idle.err.log"
SENT_LOG = STATE_DIR / "sent.log"
OPENCLAW_PROBE = STATE_DIR / "openclaw.probe.json"

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

# A listener with no observable service manager needs its own pulse. This is
# deliberately wider than the listener's five-minute IDLE refresh, so one slow
# turn is not a fault but a dead process is still visible inside a session.
STALE_LISTENER_HEARTBEAT = 15 * 60
RECONNECT_WARN_PER_HOUR = 5

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
           "last_uid": None, "uidvalidity": None, "heartbeat_at": None,
           "version": None,
           "heartbeat_age_seconds": None, "last_error": None,
           "last_error_age_seconds": None,
           "imap_last_disconnect_at": None,
           "imap_last_disconnect_age_seconds": None,
           "imap_last_disconnect_error": None,
           "imap_last_recovered_at": None,
           "imap_last_recovered_age_seconds": None,
           "imap_reconnect_attempts": 0,
           "imap_reconnect_window": [],
           "imap_reconnects_last_hour": 0,
           "imap_current_backoff_seconds": 0}
    try:
        state = json.loads(LISTENER_STATE.read_text())
        out["mailbox"] = state.get("mailbox")
        out["last_uid"] = state.get("last_uid")
        out["uidvalidity"] = state.get("uidvalidity")
        out["heartbeat_at"] = state.get("heartbeat_at")
        out["version"] = state.get("version")
        heartbeat = _stamp_seconds(out["heartbeat_at"])
        if heartbeat is not None:
            out["heartbeat_age_seconds"] = max(0, int(time.time() - heartbeat))
        out["imap_last_disconnect_at"] = state.get("imap_last_disconnect_at")
        disconnected = _stamp_seconds(out["imap_last_disconnect_at"])
        if disconnected is not None:
            out["imap_last_disconnect_age_seconds"] = max(0, int(time.time() - disconnected))
        out["imap_last_disconnect_error"] = state.get("imap_last_disconnect_error")
        out["imap_last_recovered_at"] = state.get("imap_last_recovered_at")
        recovered = _stamp_seconds(out["imap_last_recovered_at"])
        if recovered is not None:
            out["imap_last_recovered_age_seconds"] = max(0, int(time.time() - recovered))
        out["imap_reconnect_attempts"] = int(state.get("imap_reconnect_attempts") or 0)
        window = _recent_reconnect_window(state.get("imap_reconnect_window") or [])
        out["imap_reconnect_window"] = window
        out["imap_reconnects_last_hour"] = len(window)
        out["imap_current_backoff_seconds"] = int(state.get("imap_current_backoff_seconds") or 0)
    except (OSError, ValueError):
        pass
    last = tail(IDLE_ERR)
    out["last_error"] = last[0] if last else None
    try:
        # Unlike queue and heartbeat ages, the useful fact here is the write
        # time itself: a retrying listener keeps touching the diagnostic file
        # even while it cannot complete an IDLE cycle.
        out["last_error_age_seconds"] = max(0, int(time.time() - IDLE_ERR.stat().st_mtime))
    except OSError:
        pass
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


def _recent_reconnect_window(window, now=None):
    """Reconnect timestamps still inside the last hour."""
    if not isinstance(window, list):
        return []
    now = time.time() if now is None else now
    recent = []
    for stamp in window:
        seconds = _stamp_seconds(stamp)
        if seconds is not None and now - seconds <= 3600:
            recent.append(stamp)
    return recent


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
    How much of a pull-runtime spool no session has picked up yet.

    **Reported, never judged.** Unread bytes with no session open is the normal
    resting state of these runtimes, not a fault — mail waits in the spool exactly
    so a session that starts tomorrow still sees it.

    The check the PRD originally asked for, "unread bytes and no watch attached",
    is not implementable honestly: a Monitor is armed inside a session and cannot
    be seen from out here. Rather than infer it from a proxy and call the guess a
    health state, this reports what is true and says what it does not know.
    """
    if selected not in ("claudecode", "codex", "opencode"):
        return None
    out = {"spool": None, "bytes_total": 0, "bytes_unread": 0,
           "session_arming": "unobservable"}
    try:
        if selected == "claudecode":
            from adapters import claudecode as adapter
            offset_name = "session.offset"
        elif selected == "opencode":
            from adapters import opencode as adapter
            offset_name = "opencode.offset"
        else:
            from adapters import codex as adapter
            offset_name = "codex.offset"
        spool = adapter.spool_path()
    except Exception:
        return out
    out["spool"] = str(spool)
    probe_dir = spool.parent
    probe = probe_dir / f".paynani-writable-probe-{uuid.uuid4().hex}"
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        probe.unlink()
        out["writable"] = True
    except OSError as exc:
        out["writable"] = False
        out["writable_error"] = exc.__class__.__name__
    try:
        out["bytes_total"] = spool.stat().st_size
    except OSError:
        return out
    try:
        offset = int((spool.parent / offset_name).read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        offset = 0
    out["bytes_unread"] = max(0, out["bytes_total"] - offset)
    if selected == "claudecode":
        out["session_arming"] = "session-registry"
        out.update(watch_registry_facts())
    if selected == "codex":
        out["session_arming"] = "queue-or-replay"
    if selected == "opencode":
        out["session_arming"] = "opencode-plugin"
        out.update(opencode_plugin_facts(spool.parent))
    return out


def watch_registry_facts():
    """
    Which Claude Code sessions have armed a watch, from their registries (#170).

    Each session's SessionStart hook writes state/sessions/<id>/watch.json and
    its watcher keeps it: armed with a pid and an expiry, a heartbeat, ended on
    exit. So the question this file used to call unobservable has an answer:
    a live owner (pid alive, not expired), an expired or orphaned one (the
    Monitor ran out or was killed and nobody re-armed), sessions that yielded
    to a holder, and registries still pending (the hook ran, nothing armed).
    """
    out = {"watch_live": None, "watch_expired": [], "watch_orphan": [],
           "watch_pending": [], "watch_yielded": 0, "watch_ended": 0,
           "watch_ended_last": None}
    try:
        import session_start as ss
    except Exception:
        return out
    try:
        entries = ss.list_registries()
    except Exception:
        return out
    for session_id, record, state in entries:
        brief = {"session_id": session_id, "offset": record.get("offset"),
                 "armed_at": record.get("armed_at"), "expires_at": record.get("expires_at"),
                 "heartbeat_at": record.get("heartbeat_at"), "written_at": record.get("written_at"),
                 "watcher_pid": record.get("watcher_pid")}
        if state == "live":
            out["watch_live"] = brief
        elif state == "expired":
            out["watch_expired"].append(brief)
        elif state == "orphan":
            out["watch_orphan"].append(brief)
        elif state == "pending":
            out["watch_pending"].append(brief)
        elif state == "yielded":
            out["watch_yielded"] += 1
        elif state == "ended":
            out["watch_ended"] += 1
            # The newest ended watch is the one that mattered: Claude Code
            # retires a Monitor after 30 minutes with a signal the watcher
            # catches, so "ended" is what an expiry looks like in practice.
            brief["ended_at"] = record.get("ended_at")
            last = out["watch_ended_last"]
            if last is None or (brief["ended_at"] or "") > (last.get("ended_at") or ""):
                out["watch_ended_last"] = brief
    return out


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def opencode_open_pids(state):
    """
    The OpenCode processes that have the paynani plugin loaded, live ones only.

    The plugin writes `opencode.processes/<pid>` when it loads and removes it when
    it goes. A process killed hard leaves its file behind, so a dead or
    unreadable entry is removed here rather than reported as open (#160).
    """
    folder = state / "opencode.processes"
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    alive = []
    for entry in entries:
        try:
            pid = int(entry.name)
        except ValueError:
            pid = None
        if pid is not None and pid > 0 and _pid_alive(pid):
            alive.append(pid)
            continue
        try:
            entry.unlink()
        except OSError:
            pass
    return sorted(alive)


def opencode_plugin_facts(state):
    """
    Whether the OpenCode plugin is registered, and whether one is consuming now.

    Both are facts about this host rather than about a session. Registered means
    the file OpenCode loads from its global plugin directory is the one paynani
    writes; it cannot show that the OpenCode a person opens reads that
    directory. A live consumer is the process named in the plugin's lock; none
    is the normal state while OpenCode is closed.
    """
    out = {"plugin_registered": None, "plugin_path": None, "consumer_pid": None,
           "open_pids": opencode_open_pids(state)}
    try:
        import opencode_plugin
        path = opencode_plugin.default_target()
        out["plugin_path"] = str(path)
        out["plugin_registered"] = opencode_plugin.read(path) == opencode_plugin.content()
    except (Exception, SystemExit):
        pass
    try:
        text = (state / "opencode.watch.lock.d" / "owner").read_text(encoding="utf-8")
        pid = int(text.strip().partition("=")[2])
    except (OSError, ValueError):
        return out
    try:
        os.kill(pid, 0)
    except PermissionError:
        pass
    except OSError:
        return out
    out["consumer_pid"] = pid
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


def _git(*args):
    """One git command in the clone, or None. Never raises, never blocks long."""
    try:
        run = subprocess.run(["git", "-C", str(repo_root()), *args],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if run.returncode != 0:
        return None
    return (run.stdout or "").strip()


def git_facts():
    """
    Which code this install is actually running.

    Every other answer in this file describes an install that is assumed to be
    the published one. When it is not, none of them mean what they appear to:
    a host can pass every check here while running code nobody else has, and
    that is not hypothetical — it is #11, which went a full day unnoticed
    because nothing ever asked.

    Reported, never judged beyond a warning. A dirty tree does not stop mail,
    and an install legitimately carrying a local layer is a real thing. What
    cannot continue is that it goes unsaid.
    """
    out = {"is_repo": False, "commit": None, "branch": None,
           "in_origin": None, "dirty_tracked": None, "ahead": None,
           "behind": None}
    if _git("rev-parse", "--is-inside-work-tree") != "true":
        return out
    out["is_repo"] = True
    out["commit"] = _git("rev-parse", "--short", "HEAD")
    out["branch"] = _git("branch", "--show-current") or None   # empty when detached

    remote = _git("branch", "-r", "--contains", "HEAD")
    if remote is not None:
        out["in_origin"] = bool(remote.strip())

    # Tracked changes only. Untracked files are the normal state here: roster.md,
    # .env and state/ are all deliberately outside git.
    status = _git("status", "--porcelain", "--untracked-files=no")
    if status is not None:
        out["dirty_tracked"] = len([ln for ln in status.splitlines() if ln.strip()])

    counts = _git("rev-list", "--left-right", "--count", "@{u}...HEAD")
    if counts:
        parts = counts.split()
        if len(parts) == 2 and all(x.isdigit() for x in parts):
            out["behind"], out["ahead"] = int(parts[0]), int(parts[1])
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
    out = {"path": str(ROSTER), "present": False, "addresses": 0, "notifiers": []}
    try:
        out["present"] = ROSTER.is_file()
    except OSError:
        return out
    out["addresses"] = len(roster_addresses(ROSTER))
    # Which platforms may speak for the people above, and why each one counts:
    # a row of the Notifiers table, or the GitHub column on its own (#188). The
    # whole team channel arriving untagged had no line anywhere saying so.
    out["notifiers"] = [{"address": n["address"], "header": n["header"],
                         "column": n["column"],
                         "source": n.get("implied_by", "notifiers table")}
                        for n in notifiers(ROSTER)]
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


def env_source():
    """
    Which of the four rules decided the credentials path.

    Named because "no credentials at X" does not say where to go and change it.
    A path that came from `runtime.env` is fixed in `runtime.env`; one that came
    from a harness is fixed by the harness; one that fell through to the clone
    means nothing said anything, which is its own answer.
    """
    if ENV_OVERRIDE_AT_START:
        return "PAYNANI_ENV in this environment"
    if recorded_env():
        return f"PAYNANI_ENV recorded in {runtime_env()}"
    if len(harness_env_files()) == 1:
        return "the one harness on this host"
    return "the clone, because nothing named a file"


def config_facts():
    out = {"env": None, "env_mode": None, "env_present": False,
           "env_source": env_source(),
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


def instructions_facts(selected):
    """
    On OpenClaw, whether the agent has been told what the roster tag means.

    The adapter hands OpenClaw one line per message and the heartbeat shows it.
    What turns that line into a reply is a rule in the agent's own AGENTS.md,
    which `scripts/openclaw_rules.py --install` writes. Its absence is the one
    state in which every other row here is green and no roster mail is ever
    answered (#186), so it is a row of its own rather than a sentence under the
    replies warning. Other runtimes carry the instruction in the prompt itself.
    """
    if selected != "openclaw":
        return None
    out = {"path": None, "state": "unknown"}
    try:
        import openclaw_rules
        path = openclaw_rules.default_target()
        out["path"] = str(path)
        out["state"] = openclaw_rules.state(path)
    except (Exception, SystemExit):
        pass
    return out


def openclaw_probe_facts(selected):
    """
    The last explicit OpenClaw route probe, separate from real mail delivery.

    `paynani openclaw probe --dry-run` sends a synthetic `probe:<uuid>` event
    through OpenClaw without writing the paynani journal or touching IMAP. This
    row reports that receipt so nobody has to read the real delivery cursor as
    evidence of a synthetic smoke test.
    """
    if selected != "openclaw":
        return None
    out = {"path": str(OPENCLAW_PROBE), "present": False}
    try:
        stored = json.loads(OPENCLAW_PROBE.read_text(encoding="utf-8"))
    except OSError:
        return out
    except ValueError as exc:
        out.update({"present": True, "status": "unknown",
                    "detail": f"cannot parse probe record: {exc.__class__.__name__}"})
        return out
    out["present"] = True
    for key in ("probe_id", "namespace", "at", "runtime", "dry_run", "status",
                "detail", "returncode"):
        if key in stored:
            out[key] = stored.get(key)
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

    if listener["unit"] == "unknown":
        heartbeat_age = listener.get("heartbeat_age_seconds")
        if heartbeat_age is None:
            warnings.append("the listener state has no heartbeat_at; this listener is from "
                            "a version that does not report heartbeat, so its liveness is unknown")
        elif heartbeat_age > STALE_LISTENER_HEARTBEAT:
            error_age = listener.get("last_error_age_seconds")
            if error_age is not None and error_age < STALE_LISTENER_HEARTBEAT:
                problems.append(f"the listener last completed a cycle {heartbeat_age}s ago "
                                "but is still logging retries: it is running and cannot "
                                "reach the mail server, so restarting it will not help")
            else:
                problems.append(f"the listener last reported {heartbeat_age}s ago and its unit "
                                "cannot be queried: it is probably dead, and this host has no "
                                "supervisor to restart it")
        else:
            warnings.append("the listener unit cannot be queried on this host "
                            "(no observable service manager); its state is unknown, not stopped")
    elif listener["unit"] != "active":
        problems.append(f"the listener is {listener['unit']}: no new mail is being detected at all")
    if listener["last_uid"] is None:
        warnings.append("the listener has no recorded position yet, so it has not "
                        "completed a first pass over the mailbox")
    if listener.get("imap_reconnects_last_hour", 0) > RECONNECT_WARN_PER_HOUR:
        warnings.append(
            f"{listener['imap_reconnects_last_hour']} IMAP reconnects in the last hour, "
            f"above the threshold of {RECONNECT_WARN_PER_HOUR}")

    if facts["dispatcher_unit"] == "unknown":
        warnings.append("the dispatcher unit cannot be queried on this host "
                        "(no observable service manager); its state is unknown, not stopped")
    elif facts["dispatcher_unit"] != "active":
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

    spool = facts.get("spool") or {}
    if spool.get("session_arming") == "session-registry":
        stranded = list(spool.get("watch_expired", []) + spool.get("watch_orphan", []))
        if spool.get("watch_ended_last"):
            stranded.append(spool["watch_ended_last"])
        if spool.get("bytes_unread") and not spool.get("watch_live") and stranded:
            newest = max(stranded, key=lambda w: w.get("ended_at") or w.get("expires_at") or w.get("armed_at") or "")
            if newest in spool.get("watch_expired", []):
                how = "expired at " + str(newest.get("expires_at"))
            elif newest is spool.get("watch_ended_last"):
                how = "ended at " + str(newest.get("ended_at")) + " (the Monitor was retired)"
            else:
                how = "was killed"
            warnings.append(
                f"{spool['bytes_unread']} byte(s) of mail are in the spool and no session is "
                f"watching: the last watch (session {str(newest['session_id'])[:8]}) {how} "
                "and nobody re-armed. The next prompt in that session says so; a new session replays it")

    instructions = facts.get("instructions")
    if instructions and instructions["state"] != "present":
        state = instructions["state"]
        path = instructions["path"] or "~/.openclaw/workspace/AGENTS.md"
        if state == "unknown":
            warnings.append(f"whether the paynani standing rule is in {path} could not be "
                            "checked; the agent may not know what the roster tag means")
        else:
            what = ("is not in" if state == "absent" else "is out of date in")
            warnings.append(f"the paynani standing rule {what} {path}: OpenClaw will show "
                            "each roster message and the agent has nothing telling it to "
                            "read, do and reply. Run: python3 scripts/openclaw_rules.py "
                            "--install")

    # A warning and never a problem. Delivery is working in this case — that is
    # what makes it worth saying at all — and the two readings of it are answered
    # in different places: the agent was told and did not act, or nothing was
    # attached to be told (#108). This command cannot tell them apart, so it
    # reports the shape and says so rather than picking one.
    reply = facts.get("reply") or {}
    unanswered = reply.get("unanswered_age_seconds")
    # On pull runtimes, "delivered" means the bytes are in the spool, and mail
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
        problems.append(f"no credentials at {config['env']}, which is where "
                        f"{config['env_source']} points")
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

    # Warning and never a problem, and the distinction is the point. A tree that
    # differs from what was published does not stop mail, and an install carrying
    # a local layer its human asked for is legitimate. What is not legitimate is
    # nobody knowing — the code an install runs is the thing every other answer
    # here is implicitly about (#12).
    git = facts["git"]
    if git["is_repo"]:
        if git["dirty_tracked"]:
            warnings.append(
                f"{git['dirty_tracked']} tracked file(s) differ from commit "
                f"{git['commit']}: this install is not running the published code. "
                "If that is a local layer somebody asked for, it is expected and "
                "will be lost by the next `git pull`; if it is not, it is a change "
                "nobody reported. `git status --short` says which files")
        if git["in_origin"] is False:
            warnings.append(
                f"commit {git['commit']} is on no remote branch, so the code this "
                "install runs exists only on this machine")

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
        if spool.get("session_arming") == "queue-or-replay":
            out.append("             Codex wakes a registered live session with codex queue; "
                       "unread bytes wait for SessionStart replay")
            out.append("             picked up here means shown to SessionStart, not that "
                       "the agent read the mail body or answered it")
        elif spool.get("session_arming") == "opencode-plugin":
            registered = spool.get("plugin_registered")
            out.append("             OpenCode plugin "
                       + ("registered" if registered else
                          "NOT registered" if registered is False else "registration unknown")
                       + (f" at {spool['plugin_path']}" if spool.get("plugin_path") else ""))
            if registered is False:
                out.append("             run: python3 scripts/opencode_plugin.py --install")
            if spool.get("consumer_pid"):
                out.append(f"             delivering from OpenCode process {spool['consumer_pid']}")
            elif spool.get("open_pids"):
                pids = ", ".join(str(p) for p in spool["open_pids"])
                out.append(f"             OpenCode is open (process {pids}) but not delivering yet: "
                           "write in a session and delivery starts when it is idle")
            else:
                out.append("             no OpenCode process is open; unread bytes wait "
                           "until OpenCode is open, which is normal")
            out.append("             picked up here means handed to an OpenCode session, not "
                       "that the agent read the mail body or answered it")
        elif spool.get("session_arming") == "session-registry":
            live = spool.get("watch_live")
            if live:
                out.append(f"watch        armed by session {str(live['session_id'])[:8]} since "
                           f"{live.get('armed_at')}, expires {live.get('expires_at')}"
                           + (f", last heartbeat {live.get('heartbeat_at')}" if live.get("heartbeat_at") else ""))
            elif spool.get("watch_expired") or spool.get("watch_orphan") or spool.get("watch_ended_last"):
                stranded = list(spool.get("watch_expired", []) + spool.get("watch_orphan", []))
                if spool.get("watch_ended_last"):
                    stranded.append(spool["watch_ended_last"])
                newest = max(stranded, key=lambda w: w.get("ended_at") or w.get("expires_at") or w.get("armed_at") or "")
                if newest in spool.get("watch_expired", []):
                    how = "expired at " + str(newest.get("expires_at"))
                elif newest is spool.get("watch_ended_last"):
                    how = "ended at " + str(newest.get("ended_at")) + " (the Monitor was retired)"
                else:
                    how = "was killed (pid gone)"
                out.append(f"watch        none armed: the last one (session {str(newest['session_id'])[:8]}) "
                           f"{how} without re-arming")
            else:
                out.append("watch        no session has armed a watch; unread bytes with no session open is normal")
            if spool.get("watch_pending"):
                out.append(f"             {len(spool['watch_pending'])} session(s) ran the hook and never armed")
            out.append("             picked up here means shown by a watch, not that the agent "
                       "read the mail body or answered it")
        else:
            out.append("             whether a session has armed a watch is not "
                       "observable from here; unread bytes with no session open is normal")
    if runtime["selected"]:
        reach = "reachable" if runtime["reachable"] else "NOT REACHABLE"
        out.append(f"             {reach}" + (f": {runtime['detail']}" if runtime["detail"] else ""))
        out.append("             this proves the runtime answers, not that a delivered "
                   "event reaches anyone")
    instructions = facts.get("instructions")
    if instructions:
        state = instructions["state"]
        path = instructions["path"] or "~/.openclaw/workspace/AGENTS.md"
        if state == "present":
            out.append(f"instructions standing rule in place in {path}")
        elif state == "unknown":
            out.append(f"instructions standing rule in {path}: could not check")
        else:
            out.append(f"instructions standing rule {state.upper()} in {path}")
            out.append("             run: python3 scripts/openclaw_rules.py --install")
    probe = facts.get("openclaw_probe")
    if probe:
        if probe.get("present"):
            out.append("openclaw probe "
                       + f"{probe.get('status', 'unknown')} at {probe.get('at', 'unknown-time')}"
                       + (f" ({probe.get('namespace')})" if probe.get("namespace") else ""))
            if probe.get("detail"):
                out.append(f"             {probe['detail']}")
        else:
            out.append(f"openclaw probe no synthetic probe recorded at {probe['path']}")
    out.append(f"listener     {listener['unit']}"
               + (f", {listener['mailbox']} at uid {listener['last_uid']}"
                  if listener["last_uid"] is not None else ", no position recorded yet"))
    if listener.get("imap_reconnects_last_hour", 0) > RECONNECT_WARN_PER_HOUR:
        out.append(f"             warning: {listener['imap_reconnects_last_hour']} IMAP "
                   f"reconnects in the last hour, above the threshold of "
                   f"{RECONNECT_WARN_PER_HOUR}")
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
    out.append(f"             from {config['env_source']}")
    ros = facts["roster"]
    out.append(f"roster       {ros['path']}"
               + (f"  {ros['addresses']} address(es)" if ros["present"] else "  MISSING"))
    if ros["present"]:
        if ros.get("notifiers"):
            listed = "; ".join(f"{n['address']} via {n['header']}, from the {n['source']}"
                               for n in ros["notifiers"])
            out.append(f"             notifiers: {listed}")
        else:
            out.append("             no notifiers: mail sent on someone's behalf "
                       "(GitHub, Jira) arrives untagged")
    him = facts["himalaya"]
    if not him["config_present"]:
        account = "no himalaya configuration"
    elif him["account_present"]:
        account = f"[accounts.{him['account']}] present"
    else:
        account = f"[accounts.{him['account']}] MISSING"
    out.append(f"sending      {him['config']}  {account}")
    out.append(f"repo         {config['repo']}")
    git = facts["git"]
    if git["is_repo"]:
        where = f"{git['commit']}"
        if git["branch"]:
            where += f" on {git['branch']}"
        if git["ahead"] or git["behind"]:
            where += f" ({git['ahead'] or 0} ahead, {git['behind'] or 0} behind upstream)"
        if git["in_origin"] is False:
            where += ", on no remote branch"
        out.append(f"code         {where}")
        out.append(f"             {git['dirty_tracked']} tracked file(s) modified"
                   if git["dirty_tracked"] else "             tree matches the commit")
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
        "git": git_facts(),
    }
    facts["spool"] = spool_facts(facts["runtime"].get("selected"))
    facts["instructions"] = instructions_facts(facts["runtime"].get("selected"))
    facts["openclaw_probe"] = openclaw_probe_facts(facts["runtime"].get("selected"))
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
