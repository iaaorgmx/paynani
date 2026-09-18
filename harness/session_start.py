#!/usr/bin/env python3
"""
Session-start hook — make a new session aware of mail it would otherwise miss.

The listener notices mail within about a second and appends to mail.log. But a
systemd service cannot push into an agent session; only a live event source can.
So each session does two things: show what the watcher has not yet delivered, and
say which version is installed, since a session start is the only moment an agent
can be told either of them unprompted.

It does not start a watcher. The supervised service is the single consumer of the
log, and the sole writer of the cursor. A session that armed its own copy made two
consumers of one stream racing on one cursor file, which duplicated events and
corrupted the record of what had been seen.

Never fails the session: any unexpected error degrades to a quiet no-op, because a
broken hook must not be able to block startup.
"""

import calendar, json, os, pathlib, platform, re, secrets, select, shutil, subprocess, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import event as ev
import ledger
from paths import repo_root, state_dir

STATE_DIR = state_dir()
JOURNAL = STATE_DIR / "events.jsonl"
CURSOR = STATE_DIR / "dispatch.offset"
DISPATCH_ERR = STATE_DIR / "dispatch.err.log"
# Found from this file rather than assumed. The hard-coded OpenClaw path was
# wrong on every other host, and silently so: this hook swallows its own errors
# to keep a session from ever being blocked, so a clone anywhere else produced
# no version line and no complaint about why.
REPO = repo_root()
VERSION_SH = REPO / "scripts/version.sh"
SERVICE = "paynani-idle.service"
DISPATCH_SERVICE = "paynani-dispatch.service"
SERVICE_LABEL = "com.paynani.idle"
DISPATCH_SERVICE_LABEL = "com.paynani.dispatch"

# Claude Code and Codex both keep a spool for catch-up. Claude Code also arms a
# Monitor for mid-session lines. Codex records the active thread at SessionStart
# so the dispatcher can wake it with `codex queue`; this replay is the backstop
# for mail that arrived with no live session or before the hook was installed.
SPOOL = STATE_DIR / "session.spool"
SESSION_OFFSET = STATE_DIR / "session.offset"
CODEX_SPOOL = STATE_DIR / "codex.spool"
CODEX_OFFSET = STATE_DIR / "codex.offset"
CODEX_SESSION = STATE_DIR / "codex.session"
CODEX_STATUS = STATE_DIR / "codex.delivery.json"
LIFECYCLE = STATE_DIR / "lifecycle.jsonl"
# OpenCode keeps a spool too, but nothing in OpenCode runs this file as a hook.
# The paynani plugin inside the OpenCode process (harness/opencode/paynani.js)
# calls the --opencode-* modes below instead: it asks what is pending, hands the
# instruction to its own session, and acknowledges only once OpenCode took it.
# The lock makes that plugin a single consumer when two OpenCode processes are
# open, for the same reason session_watch.sh takes one.
OPENCODE_SPOOL = STATE_DIR / "opencode.spool"
OPENCODE_OFFSET = STATE_DIR / "opencode.offset"
OPENCODE_LOCK = STATE_DIR / "opencode.watch.lock.d"
# Presence, kept apart from the lock. The plugin takes the lock only once it has
# a session to deliver to, so a lock alone cannot tell "OpenCode is open and
# nobody has written in it yet" from "OpenCode is closed". Every plugin that
# loads writes its pid here and removes it when it goes (#160).
OPENCODE_PROCESSES = STATE_DIR / "opencode.processes"
# A lock directory whose owner file has not been written yet belongs to a
# plugin that is in the middle of claiming it, not to a dead one.
OPENCODE_LOCK_GRACE = 10
SESSION_WATCH = REPO / "harness/session_watch.sh"
RUNTIME_ENV = REPO / "runtime.env"
# One registry per Claude Code session, written by the SessionStart hook and
# kept by the watcher for as long as it lives (#170). The hook used to print a
# byte offset for the agent to copy into the Monitor command; a digit wrong
# repeated mail or skipped it, and nothing outside the session could say
# whether a watch was armed at all. Now the hook writes the offset here under
# the session's own id, the watcher reads it back with --from-hook, and the
# registry is what healthcheck.py and the UserPromptSubmit hook read.
SESSIONS_DIR = STATE_DIR / "sessions"
WATCH_REGISTRY = "watch.json"
# How long an armed watch is believed without word from it. Claude Code kills a
# Monitor after 30 minutes; a registry older than that with no end recorded is
# a watch that expired and was not re-armed.
WATCH_TTL = int(os.environ.get("PAYNANI_WATCH_TTL", "1800"))

MAX_REPLAY = 20   # enough to see overnight without flooding the context window
MAX_DISPATCH_ERR = 5   # the last few lines say whether it is still failing
MAX_LOCAL_FILES = 10   # name them, but do not paste a whole refactor
VERSION_TIMEOUT = 20   # above version.sh's own 10s, so its timeout fires first
CODEX_ACK_CONTEXT_LIMIT = int(os.environ.get("PAYNANI_CODEX_ACK_CONTEXT_LIMIT", "5000"))


def launchd_state(label):
    """active / down / unknown for a per-user macOS LaunchAgent."""
    try:
        r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return "down"
        return "active" if "state = running" in (r.stdout or "") else "down"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def unit_state(unit):
    """active / down / unknown, without treating a blocked query as a dead unit."""
    if platform.system() == "Darwin":
        labels = {
            SERVICE: SERVICE_LABEL,
            DISPATCH_SERVICE: DISPATCH_SERVICE_LABEL,
        }
        return launchd_state(labels.get(unit, unit))
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", unit],
                           capture_output=True, text=True, timeout=5)
        state = (r.stdout or "").strip()
        if r.returncode == 0 and state == "active":
            return "active"
        if state in {"inactive", "failed", "deactivating"}:
            return "down"
        return "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# dispatch.py:main() writes exactly this line, once, right after it claims the
# lock and before it delivers anything — the only line that names a process
# starting rather than something that happened during one. That makes it the
# marker for "the current dispatcher startup" that dispatcher_faults() cuts on.
_STARTUP_PREFIX = ev.ROUTINE_PREFIX + ev.STARTUP_NOTE


def dispatcher_faults():
    """
    Recent watcher complaints, newest last.

    The watcher delivers events by calling openclaw, so it cannot use that path
    to report that calling openclaw is broken. Its stderr goes to a file, and
    reading that file here is the only thing that closes the loop: without it, an
    install where injection fails looks exactly like an install with no new mail.
    """
    try:
        if not DISPATCH_ERR.is_file() or DISPATCH_ERR.stat().st_size == 0:
            return []
        text = DISPATCH_ERR.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    all_lines = text.splitlines()
    # A line written before the dispatcher now running was even born describes a
    # process that is gone, not a problem this install has. Without this cut, one
    # unmarked line from before the ok: prefix existed (#15) stayed a permanent
    # false PROBLEMS report, surviving every later restart that started clean
    # (#59). When no startup line is found — an install too old to have written
    # one — nothing is cut and every line is still weighed, which is the
    # pre-existing, safe-side behaviour.
    start = 0
    for i, ln in enumerate(all_lines):
        if ln.startswith(_STARTUP_PREFIX):
            start = i + 1
    # Routine notes are dropped. The dispatcher marks them, because it is the
    # only party that knows which of its own lines is a complaint — and the line
    # it writes on every successful startup used to make this hook announce
    # PROBLEMS on every healthy install (#15).
    lines = [ln for ln in all_lines[start:]
             if ln.strip() and not ln.startswith(ev.ROUTINE_PREFIX)]
    return lines[-MAX_DISPATCH_ERR:]


def local_code_line():
    """
    One line when this clone is not running the published code, and nothing
    otherwise.

    A session starting on a modified tree is the moment to say so: every other
    line this hook prints, and every check the agent will run afterwards,
    silently assumes the code is what the repository published. #11 spent a day
    invisible because nobody was ever told to look, and the person who could have
    said it in one sentence was the one reading a report that did not mention it.
    """
    def git(*args):
        try:
            run = subprocess.run(["git", "-C", str(repo_root()), *args],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return (run.stdout or "").strip() if run.returncode == 0 else None

    if git("rev-parse", "--is-inside-work-tree") != "true":
        return ""
    status = git("status", "--porcelain", "--untracked-files=no")
    if not status:
        return ""
    # Split rather than slice a fixed width: the helper strips the whole output,
    # so the first line loses the leading space of its two-character status
    # field and a fixed `ln[3:]` eats the first letter of that one filename.
    names = [ln.split(maxsplit=1)[-1] for ln in status.splitlines() if ln.strip()]
    files = names[:MAX_LOCAL_FILES]
    commit = git("rev-parse", "--short", "HEAD") or "HEAD"
    more = ""
    count = len(names)
    if count > len(files):
        more = f" (and {count - len(files)} more)"
    return ("THIS INSTALL IS NOT RUNNING THE PUBLISHED CODE — "
            f"{count} tracked file(s) differ from commit {commit}: "
            + ", ".join(files) + more + ". "
            "If your human asked for these, they are expected, and a `git pull` "
            "will silently take them away. If you did not know they were there, "
            "say so before reporting that anything was verified: every check you "
            "are about to run describes this tree, not the published one.")


def version_line():
    """
    One line: which version is installed, and whether anything newer exists.

    A session is the only moment this can be said unprompted, and an agent that
    is never told never asks. The cost is one line of context per session.

    `version.sh --line` owns the question, including its own once-a-day cache,
    so this stays a wrapper. That keeps one implementation of the comparison
    rather than two, and a harness that rewrites this file inherits the
    behaviour rather than reimplementing it.

    Nonzero exit is not silence. Out of date exits 2 and could-not-check exits
    1, and those are the two answers worth hearing, so the line is read from
    stdout whatever the status says.
    """
    try:
        r = subprocess.run([str(VERSION_SH), "--line"], capture_output=True,
                           text=True, timeout=VERSION_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None   # no clone at the expected path, or it hung: not worth a line
    return r.stdout.strip() or None


def selected_runtime():
    """
    Which runtime this install delivers to, or None if it cannot be determined.

    Read rather than detected. Detection asks what is installed on the host; this
    asks what the installer chose, and on a host with two harnesses present those
    are different questions with different answers.
    """
    name = (os.environ.get("PAYNANI_RUNTIME") or "").strip().lower()
    if name and name != "auto":
        return name
    try:
        for raw in RUNTIME_ENV.read_text(encoding="utf-8").splitlines():
            key, _, value = raw.partition("=")
            if key.strip() == "PAYNANI_RUNTIME":
                value = value.strip().strip('"').strip("'").lower()
                return value if value and value != "auto" else None
    except OSError:
        pass
    return None


def spool_paths(runtime):
    if runtime == "codex":
        return CODEX_SPOOL, CODEX_OFFSET
    if runtime == "opencode":
        return OPENCODE_SPOOL, OPENCODE_OFFSET
    return SPOOL, SESSION_OFFSET


def read_spool_backlog(spool_path=None, offset_path=None):
    """
    (rendered lines, capped, byte offset read through) for a session spool.

    By default this reads the Claude Code spool for compatibility with the
    existing tests. The caller decides whether and when an offset can be
    acknowledged; reading alone never does it.
    """
    spool_path = SPOOL if spool_path is None else pathlib.Path(spool_path)
    offset_path = SESSION_OFFSET if offset_path is None else pathlib.Path(offset_path)
    try:
        start = int(offset_path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        start = 0
    try:
        size = spool_path.stat().st_size
    except OSError:
        return [], False, start
    # A spool shorter than the recorded offset means the file was replaced or
    # truncated underneath us. Trusting the stale offset would step over
    # everything now in it, so start again rather than skip.
    if size < start:
        start = 0
    try:
        with open(spool_path, "rb") as handle:
            handle.seek(start)
            data = handle.read()
    except OSError:
        return [], False, start
    lines = []
    through = start
    position = start
    capped = False
    for raw in data.splitlines(keepends=True):
        position += len(raw)
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            if not lines:
                through = position
            continue
        if len(lines) >= MAX_REPLAY:
            capped = True
            break
        lines.append(line)
        through = position
    return lines, capped, through


def write_text_atomic(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def acknowledge_spool(offset_path, through):
    """
    Record the byte offset a Codex SessionStart hook has emitted through.

    Claude Code acknowledges by arming its Monitor. Codex has no monitor in this
    MVP, so the hook acknowledges after it has written valid JSON to stdout. If
    this write fails, the same messages replay next time; duplicate replay is
    preferable to a skipped message.
    """
    try:
        write_text_atomic(offset_path, str(int(through)))
    except (OSError, ValueError):
        pass


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stamp_seconds(stamp):
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def _safe_session_id(session_id):
    """
    A session id usable as a directory name, or None.

    It comes from the hook's stdin JSON and is a UUID on every Claude Code seen;
    the check is there so a payload with a path in it cannot write outside
    SESSIONS_DIR.
    """
    session_id = str(session_id or "").strip()
    if not session_id or len(session_id) > 128:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]+", session_id) or session_id in (".", ".."):
        return None
    return session_id


def registry_path(session_id):
    return SESSIONS_DIR / session_id / WATCH_REGISTRY


def write_registry(session_id, offset):
    """
    Record, for this session alone, the offset its watcher must start from.

    Written pending: the hook has replayed the spool through `offset`, and
    nothing has been acknowledged yet. The watcher turns it into armed when it
    takes the lock, or yielded when another session already holds it, so a
    pending registry that stays pending is a session that never armed.
    """
    record = {
        "schema_version": 1,
        "session_id": session_id,
        "offset": int(offset),
        "token": secrets.token_hex(8),
        "status": "pending",
        "written_at": _utc_now(),
        "armed_at": None,
        "expires_at": None,
        "watcher_pid": None,
        "heartbeat_at": None,
        "ended_at": None,
        "holder_session": None,
    }
    write_text_atomic(registry_path(session_id), json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def read_registry(session_id):
    try:
        data = json.loads(registry_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def update_registry(session_id, **fields):
    """Merge fields into the session's registry, atomically. Missing: no-op, False."""
    record = read_registry(session_id)
    if record is None:
        return False
    record.update(fields)
    try:
        write_text_atomic(registry_path(session_id), json.dumps(record, indent=2, sort_keys=True) + "\n")
    except OSError:
        return False
    return True


def registry_state(record, now=None):
    """
    live, expired, orphan, pending, yielded or ended: one word per registry.

    live: armed, the watcher's pid answers, and expires_at is ahead. expired:
    armed, but past expires_at, or a heartbeat older than the TTL. orphan: armed
    and the watcher's pid is gone without an ended_at, which is a hard kill or
    a Monitor Claude Code took away. pending: the hook wrote it and nothing
    armed. The other two are what they say.
    """
    if not isinstance(record, dict):
        return "orphan"
    now = time.time() if now is None else now
    status = record.get("status")
    if status in ("pending", "yielded", "ended"):
        return status
    if status != "armed":
        return "orphan"
    pid = record.get("watcher_pid")
    if not (isinstance(pid, int) and pid > 0 and _pid_alive(pid)):
        return "orphan"
    expires = _stamp_seconds(record.get("expires_at"))
    if expires is not None and now >= expires:
        return "expired"
    beat = _stamp_seconds(record.get("heartbeat_at") or record.get("armed_at"))
    if beat is not None and now - beat > WATCH_TTL:
        return "expired"
    return "live"


def list_registries():
    """Every session registry on this host, as (session_id, record, state)."""
    out = []
    try:
        entries = sorted(SESSIONS_DIR.iterdir())
    except OSError:
        return out
    for entry in entries:
        record = read_registry(entry.name)
        if record is None:
            continue
        out.append((entry.name, record, registry_state(record)))
    return out


def live_watch():
    """The registry of the live watcher, or None. There is at most one lock."""
    for _, record, state in list_registries():
        if state == "live":
            return record
    return None


def unseen_spool_bytes():
    """Bytes in the spool past session.offset: mail delivered and shown to nobody."""
    try:
        total = SPOOL.stat().st_size
    except OSError:
        return 0
    try:
        offset = int(SESSION_OFFSET.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        offset = 0
    return max(0, total - offset)


def prompt_submit(payload):
    """
    The UserPromptSubmit hook: say something only when mail is waiting unseen.

    Quiet when the spool has nothing past the offset, and quiet when a live
    watcher covers it (this session's or another's): a watcher that is alive
    reads from the offset onward, so anything above it will be shown. It speaks
    only when bytes are waiting and no live owner will ever render them, which
    is exactly the state a killed Monitor leaves behind (#170).
    """
    unseen = unseen_spool_bytes()
    if unseen <= 0:
        return None
    owner = live_watch()
    if owner is not None:
        return None
    lines = 0
    try:
        with SPOOL.open("rb") as fh:
            fh.seek(max(0, SPOOL.stat().st_size - unseen))
            lines = sum(1 for chunk in fh if chunk.strip())
    except OSError:
        lines = 0
    what = f"{lines} mail notification(s)" if lines else f"{unseen} byte(s) of mail notifications"
    return (f"paynani: {what} arrived and no watch is showing them. Re-arm the "
            f"watch now, before answering, with a Monitor running exactly:\n\n"
            f"    bash {SESSION_WATCH} {STATE_DIR} --from-hook\n\n"
            "It replays what is waiting first and then keeps watching.")


def prompt_submit_command():
    payload = read_hook_input()
    context = prompt_submit(payload)
    if context:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context}}), flush=True)
    return 0


def registry_command(args):
    """
    `--registry <verb> <session-id> [k=v ...]`: the watcher's side of the
    registry, in the same code that writes it. bash has no JSON; this has.
    """
    verb = args[0] if args else ""
    session_id = _safe_session_id(args[1] if len(args) > 1 else "")
    if not session_id:
        print("registry: session id missing or unusable", file=sys.stderr)
        return 2
    fields = {}
    for pair in args[2:]:
        key, _, value = pair.partition("=")
        if key == "state":
            # The watcher names the state directory it was armed on, which is
            # the tests' temporary one as often as this checkout's.
            global SESSIONS_DIR
            SESSIONS_DIR = pathlib.Path(value) / "sessions"
            continue
        if value.isdigit():
            fields[key] = int(value)
        elif value in ("", "null"):
            fields[key] = None
        else:
            fields[key] = value
    if verb == "offset":
        # Pending: the offset the hook replayed through. Ended, expired or
        # orphan: the cursor as of the last line the watcher showed, which the
        # beat after every line keeps current, so a re-arm repeats nothing and
        # skips nothing. Live: another watcher of this session is running, and
        # the lock will say so; do not hand out an offset to race it.
        # Claude Code retires a Monitor after 30 minutes and the agent re-arms
        # with the same command, so the registry has to answer more than once.
        record = read_registry(session_id)
        if record is None or registry_state(record) == "live":
            return 1
        print(record.get("offset", 0))
        return 0
    if verb == "arm":
        now = time.time()
        fields.update({"status": "armed", "ended_at": None, "holder_session": None,
                       "armed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                       "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + WATCH_TTL)),
                       "heartbeat_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))})
        return 0 if update_registry(session_id, **fields) else 1
    if verb == "beat":
        # The cursor rides on every beat, and the watcher beats after each
        # line it shows (Atenea, #202), so a watcher killed hard leaves a
        # registry at the last line it showed. A re-arm from an orphan then
        # repeats nothing and skips nothing.
        return 0 if update_registry(session_id, heartbeat_at=_utc_now(), **fields) else 1
    if verb == "yield":
        return 0 if update_registry(session_id, status="yielded", ended_at=_utc_now(), **fields) else 1
    if verb == "end":
        return 0 if update_registry(session_id, status="ended", ended_at=_utc_now(), **fields) else 1
    if verb == "show":
        record = read_registry(session_id)
        if record is None:
            return 1
        print(json.dumps({"state": registry_state(record), **record}, sort_keys=True))
        return 0
    print(f"registry: unknown verb {verb!r}", file=sys.stderr)
    return 2


def read_hook_input():
    """
    Read Codex's hook JSON if it is waiting on stdin.

    A missing or malformed payload is not a hook failure. Older tests and manual
    invocations call this script with no stdin at all, and the startup context is
    still useful without the optional session registration.
    """
    try:
        if sys.stdin.isatty():
            return {}
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 0)
        except (OSError, TypeError, ValueError):
            ready = [sys.stdin]
        if not ready:
            return {}
        text = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def remember_codex_session(payload):
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return
    try:
        write_text_atomic(CODEX_SESSION, session_id + "\n")
    except OSError:
        pass


def forget_codex_session():
    try:
        CODEX_SESSION.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def read_backlog():
    """
    (rendered lines, whether it was capped) for events not yet delivered.

    Read-only in every sense. The cursor belongs to the dispatcher, which is the
    only thing that knows whether a runtime actually took an event, and a hook
    that moved it would be claiming delivery it did not perform. So this shows
    what is still owed and changes nothing: if the dispatcher is healthy the list
    is empty, and if it is not, these are the events waiting for it.
    """
    try:
        cursor = ev.read_cursor(CURSOR)
        lines = [r.get("notification_text", "") for r, _ in ev.read_from(JOURNAL, cursor)]
    except OSError:
        return [], False
    lines = [ln for ln in lines if ln.strip()]
    return lines[-MAX_REPLAY:], len(lines) > MAX_REPLAY


def _journal_events_by_notification(wanted_counts=None):
    """
    notification_text -> queued event ids, in journal order.

    Older Codex spools held only rendered notification lines, not bodies.
    SessionStart still needs to turn those lines back into the same event-id
    instruction the live `codex queue` path sends, so old records are resolved
    against the local journal when the record is still available.
    """
    found = {}
    wanted_counts = wanted_counts or {}
    try:
        records = ev.read_from(JOURNAL, 0)
        if records is None:
            return found
        for record, _ in records:
            if isinstance(record, ev.Corrupt):
                continue
            line = str(record.get("notification_text") or "").strip()
            event_id = str(record.get("event_id") or "").strip()
            if line and event_id:
                found.setdefault(line, []).append(event_id)
    except OSError:
        return found
    for line, count in wanted_counts.items():
        if count > 0 and line in found:
            found[line] = found[line][-count:]
    return found


def _codex_spool_record(line):
    try:
        record = json.loads(line)
    except (TypeError, ValueError):
        return "", str(line or "").strip()
    if not isinstance(record, dict):
        return "", str(line or "").strip()
    event_id = str(record.get("event_id") or "").strip()
    notification = str(record.get("notification_text") or "").strip()
    return event_id, notification or str(line or "").strip()


def codex_replay_instructions(spool_lines):
    records = [_codex_spool_record(line) for line in spool_lines]
    wanted_counts = {}
    for event_id, notification in records:
        if not event_id and notification:
            wanted_counts[notification] = wanted_counts.get(notification, 0) + 1
    by_line = _journal_events_by_notification(wanted_counts) if wanted_counts else {}
    event_ids = []
    fallbacks = []
    for event_id, notification in records:
        if not event_id:
            candidates = by_line.get(notification)
            event_id = candidates.pop(0) if candidates else ""
        if event_id:
            event_ids.append(event_id)
        else:
            fallbacks.append(notification)
    out = []
    if event_ids:
        out.append(ev.codex_events_prompt(event_ids))
    if fallbacks:
        out.append(ev.codex_events_fallback_prompt(fallbacks))
    return out


def codex_replayed(spool_lines):
    """Record only after the replay payload was successfully printed."""
    event_ids = [event_id for event_id, _ in map(_codex_spool_record, spool_lines) if event_id]
    for event_id in event_ids:
        try:
            ledger.transition(LIFECYCLE, event_id, "presented", runtime="codex",
                              detail="session-start replay")
        except (OSError, ValueError):
            pass
    try:
        current = json.loads(CODEX_STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    current["last_replay"] = {
        "event_id": event_ids[-1] if event_ids else "",
        "count": len(spool_lines),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        write_text_atomic(CODEX_STATUS, json.dumps(current, indent=2, sort_keys=True))
        os.chmod(CODEX_STATUS, 0o600)
    except OSError:
        pass


def system_message_parts(listener_state, dispatcher_state, faults, runtime,
                         spool_lines, lines):
    messages = []
    if listener_state == "down":
        messages.append("Mail listener is DOWN — new mail is not being detected")
    if dispatcher_state == "down":
        messages.append("Mail dispatcher is DOWN — mail is journalled but not delivered")
    if listener_state == "unknown" or dispatcher_state == "unknown":
        messages.append("Mail service status unknown — could not query service manager")
    if faults:
        messages.append("Dispatcher reported errors — mail may not be reaching the session")
    if runtime == "codex" and spool_lines:
        messages.append(f"{len(spool_lines)} replayed paynani mail event(s) require processing")
    if lines:
        messages.append(f"{len(lines)} unseen mail notification(s)")
    return messages


def opencode_pending(with_status=False):
    """
    What the OpenCode plugin should hand to its session, without acknowledging.

    `through` is the byte offset the plugin passes back to --opencode-ack once
    OpenCode accepted the prompt. The prompt carries event ids and the fixed
    instruction Codex uses, never a mail body. `system` is only computed when
    asked, because the plugin polls this and the service checks shell out.
    """
    lines, capped, through = read_spool_backlog(OPENCODE_SPOOL, OPENCODE_OFFSET)
    prompt = "\n".join(codex_replay_instructions(lines)) if lines else ""
    system = ""
    if with_status:
        system = ". ".join(system_message_parts(
            unit_state(SERVICE), unit_state(DISPATCH_SERVICE), dispatcher_faults(),
            "opencode", [], []))
    return {"through": through, "count": len(lines), "capped": capped,
            "prompt": prompt, "system": system}


def opencode_ack(value):
    """
    Move opencode.offset forward to `value`, and never backward or past the end.

    A value behind the recorded offset is an older plugin call finishing late;
    honouring it would replay mail that was already handed over. A value past the
    end of the spool cannot have come from --opencode-pending on this spool.
    """
    try:
        through = int(value)
    except (TypeError, ValueError):
        return None
    try:
        size = OPENCODE_SPOOL.stat().st_size
    except OSError:
        size = 0
    if through < 0 or through > size:
        return None
    try:
        current = int(OPENCODE_OFFSET.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        current = 0
    if current > size:
        current = 0
    if through > current:
        event_ids = []
        try:
            with open(OPENCODE_SPOOL, "rb") as handle:
                handle.seek(current)
                acknowledged = handle.read(through - current)
            for raw in acknowledged.splitlines():
                event_id, _ = _codex_spool_record(raw.decode("utf-8", "replace"))
                if event_id:
                    event_ids.append(event_id)
        except OSError:
            event_ids = []
        write_text_atomic(OPENCODE_OFFSET, str(through))
        current = through
        for event_id in event_ids:
            try:
                ledger.transition(
                    LIFECYCLE, event_id, "presented", runtime="opencode",
                    detail="opencode plugin acknowledged prompt",
                )
            except (OSError, ValueError):
                pass
    return current


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _opencode_lock_owner():
    try:
        text = (OPENCODE_LOCK / "owner").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "pid":
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def _opencode_take_lock(pid):
    try:
        OPENCODE_LOCK.mkdir(parents=True)
    except FileExistsError:
        return False
    write_text_atomic(OPENCODE_LOCK / "owner", f"pid={pid}\n")
    return True


def opencode_claim(pid):
    """
    Whether the plugin in process `pid` is the one OpenCode consumer.

    Two consumers of one spool advancing one offset is how events get repeated
    and the record of what was handed over gets corrupted. The first plugin to
    create the lock directory wins; a later one takes over only when the owner
    process is gone. The takeover renames the stale directory away first, so two
    plugins noticing the same dead owner still leave exactly one winner.
    """
    pid = int(pid)
    if pid <= 0:
        raise ValueError("pid must be positive")
    if _opencode_take_lock(pid):
        return True, pid
    owner = _opencode_lock_owner()
    if owner == pid:
        return True, pid
    if owner is not None and _pid_alive(owner):
        return False, owner
    if owner is None:
        try:
            age = time.time() - OPENCODE_LOCK.stat().st_mtime
        except OSError:
            age = OPENCODE_LOCK_GRACE
        if age < OPENCODE_LOCK_GRACE:
            return False, None
    stale = OPENCODE_LOCK.with_name(f"{OPENCODE_LOCK.name}.stale.{pid}")
    try:
        os.rename(OPENCODE_LOCK, stale)
    except OSError:
        return False, _opencode_lock_owner()
    shutil.rmtree(stale, ignore_errors=True)
    if _opencode_take_lock(pid):
        return True, pid
    return False, _opencode_lock_owner()


def opencode_release(pid):
    """Remove the lock, but only the one this process holds."""
    if _opencode_lock_owner() == int(pid):
        shutil.rmtree(OPENCODE_LOCK, ignore_errors=True)
        return True
    return False


def _positive_pid(value):
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def opencode_hello(pid):
    """Record that the OpenCode process `pid` has the paynani plugin loaded."""
    OPENCODE_PROCESSES.mkdir(parents=True, exist_ok=True)
    write_text_atomic(OPENCODE_PROCESSES / str(pid), f"pid={pid}\n")
    return True


def opencode_bye(pid):
    """Forget the OpenCode process `pid`; whether there was anything to forget."""
    try:
        (OPENCODE_PROCESSES / str(pid)).unlink()
    except FileNotFoundError:
        return False
    return True


def opencode_command(args):
    """
    The --opencode-* modes. Each prints one JSON object or nothing.

    Nothing printed means "do not act": the plugin neither delivers nor
    acknowledges without a parsed answer, so a failure here repeats mail at
    worst and never skips it.
    """
    mode = args[0]
    if mode == "--opencode-pending":
        print(json.dumps(opencode_pending("--status" in args[1:]), ensure_ascii=False),
              flush=True)
        return 0
    if mode == "--opencode-ack" and len(args) == 2:
        offset = opencode_ack(args[1])
        if offset is None:
            return 2
        print(json.dumps({"offset": offset}), flush=True)
        return 0
    if mode == "--opencode-claim" and len(args) == 2:
        owner, holder = opencode_claim(args[1])
        print(json.dumps({"owner": owner, "holder": holder}), flush=True)
        return 0
    if mode == "--opencode-release" and len(args) == 2:
        print(json.dumps({"released": opencode_release(args[1])}), flush=True)
        return 0
    if mode in ("--opencode-hello", "--opencode-bye") and len(args) == 2:
        pid = _positive_pid(args[1])
        if pid is None:
            return 2
        if mode == "--opencode-hello":
            print(json.dumps({"registered": opencode_hello(pid)}), flush=True)
        else:
            print(json.dumps({"removed": opencode_bye(pid)}), flush=True)
        return 0
    return 2


def main():
    if sys.argv[1:2] and sys.argv[1].startswith("--opencode-"):
        return opencode_command(sys.argv[1:])
    if sys.argv[1:2] == ["--registry"]:
        return registry_command(sys.argv[2:])
    if sys.argv[1:2] == ["--prompt-submit"]:
        return prompt_submit_command()
    runtime = selected_runtime()
    if "--session-end" in sys.argv[1:]:
        forget_codex_session()
        return 0
    payload = read_hook_input() if runtime in ("codex", "claudecode") else {}
    if runtime == "codex":
        remember_codex_session(payload)
    lines, capped = read_backlog()
    spool_lines, spool_capped, spool_through = ([], False, 0)
    spool_path, spool_offset = spool_paths(runtime)
    if runtime == "claudecode":
        spool_lines, spool_capped, spool_through = read_spool_backlog()
    elif runtime == "codex":
        spool_lines, spool_capped, spool_through = read_spool_backlog(spool_path, spool_offset)
    listener_state = unit_state(SERVICE)
    dispatcher_state = unit_state(DISPATCH_SERVICE)
    faults = dispatcher_faults()

    parts = []
    if listener_state == "down":
        check = (f"`launchctl print gui/$(id -u)/{SERVICE_LABEL}`" if platform.system() == "Darwin"
                 else f"`systemctl --user status {SERVICE}`")
        parts.append(
            f"MAIL LISTENER IS DOWN — {SERVICE} is not active, so no new mail is "
            f"being detected at all. Check {check} and "
            "restart it before relying on mail notifications."
        )
    elif listener_state == "unknown":
        check = (f"`launchctl print gui/$(id -u)/{SERVICE_LABEL}`" if platform.system() == "Darwin"
                 else f"`systemctl --user status {SERVICE}`")
        parts.append(
            f"MAIL LISTENER STATUS UNKNOWN — this session could not query {SERVICE}. "
            f"Check {check} outside this context before treating the listener as down."
        )

    if dispatcher_state == "down":
        check = (f"`launchctl print gui/$(id -u)/{DISPATCH_SERVICE_LABEL}`" if platform.system() == "Darwin"
                 else f"`systemctl --user status {DISPATCH_SERVICE}`")
        parts.append(
            f"MAIL DISPATCHER IS DOWN — {DISPATCH_SERVICE} is not active. Mail is still "
            "being detected and journalled, but nothing is delivering it into a "
            f"session. Check {check}."
        )
    elif dispatcher_state == "unknown":
        check = (f"`launchctl print gui/$(id -u)/{DISPATCH_SERVICE_LABEL}`" if platform.system() == "Darwin"
                 else f"`systemctl --user status {DISPATCH_SERVICE}`")
        parts.append(
            f"MAIL DISPATCHER STATUS UNKNOWN — this session could not query {DISPATCH_SERVICE}. "
            f"Check {check} outside this context before treating the dispatcher as down."
        )

    if faults:
        parts.append(
            "THE DISPATCHER REPORTED PROBLEMS — the most recent lines of "
            f"{DISPATCH_ERR} are below. If the last one is not a recovery, new mail "
            "is being logged but not delivered, and every other check will still "
            "look healthy:\n" + "\n".join(faults)
        )

    if runtime == "claudecode":
        # Everything below is this runtime only. The other two are pushed to by a
        # supervised service; here nothing can speak into a session, so the
        # session has to come and get it, and this hook is where it is told how.
        if spool_lines:
            parts.append(
                f"Mail that arrived while no session was watching "
                f"({len(spool_lines)} message(s)"
                + (f", showing the oldest {MAX_REPLAY}" if spool_capped else "")
                + "):\n" + "\n".join(spool_lines)
            )
        else:
            parts.append("No unseen mail since the last session armed the watch.")

        # The offset goes into this session's registry, not into the text: a
        # number the agent has to copy is a number it can get wrong, and one
        # digit repeated mail or skipped it (#170). The watcher reads it back
        # by the session id Claude Code puts in its environment.
        session_id = _safe_session_id(payload.get("session_id"))
        registered = False
        if session_id:
            try:
                write_registry(session_id, spool_through)
                registered = True
            except OSError:
                registered = False
        if registered:
            arm = f"    bash {SESSION_WATCH} {STATE_DIR} --from-hook\n\n"
            offset_note = (
                "The offset is not in this text on purpose: this hook wrote it to "
                f"{registry_path(session_id)} and --from-hook reads it back, so "
                "there is nothing to copy and nothing to get wrong. "
            )
        else:
            arm = f"    bash {SESSION_WATCH} {STATE_DIR} {spool_through}\n\n"
            offset_note = (
                "The byte offset is not optional and must not be rounded: this "
                "hook has replayed the spool through exactly that byte, so "
                "starting anywhere else either repeats messages or steps over "
                "ones nobody has seen. "
            )
        parts.append(
            "ARM THE MAIL WATCH NOW, before doing anything else, with a persistent "
            "Monitor running exactly:\n\n"
            + arm +
            "Each stdout line is one new mail notification, except a line saying "
            "the watch could not be armed because another session already holds "
            "it — that one is not mail. " + offset_note +
            "Arming is also what acknowledges the replay above — if you skip it, "
            "the next session shows these same messages again, and no new mail "
            "reaches you for the rest of this one. When the Monitor expires, "
            "re-arm it with the same command."
        )
    elif runtime == "codex":
        if spool_lines:
            replay_instructions = codex_replay_instructions(spool_lines)
            parts.append(
                f"PAYNANI REPLAYED MAIL REQUIRES ACTION — mail arrived before "
                f"this Codex session event "
                f"({len(spool_lines)} message(s)"
                + (f", showing the oldest {MAX_REPLAY}" if spool_capped else "")
                + "). Treat each instruction below as pending work until you "
                "read or deliberately dismiss the exact mail body:\n"
                + "\n".join(replay_instructions)
            )
        else:
            parts.append("No unseen mail since the last Codex session-start replay.")

        parts.append(
            "Codex paynani delivery uses `codex queue` when a live session has "
            "registered its thread. Mail is still written durably to codex.spool; "
            "this SessionStart replay is the fallback for anything not already "
            "acknowledged by live queue delivery."
        )

    if lines:
        header = (f"Mail queued but not yet delivered ({len(lines)} message(s)"
                  + (f", trimmed to the most recent {MAX_REPLAY}" if capped else "")
                  + "). It stays in the journal until a runtime accepts it, so "
                  "expect the dispatcher to deliver it as well rather than "
                  "treating this as the only copy:")
        parts.append(header + "\n" + "\n".join(lines))
    elif runtime not in ("claudecode", "codex", "opencode"):
        parts.append("No unseen mail since the last session acknowledged the log.")

    local = local_code_line()
    if local:
        parts.append(local)

    version = version_line()
    if version:
        parts.append(version)

    # ---- CODEX AND CLAUDE CODE'S HOOK CONTRACT -----------------------------
    # This is the payload their SessionStart command hooks accept. Codex also
    # feeds JSON on stdin, which we used above only to record the active thread;
    # the stdout contract stays the same. Nothing on OpenClaw or Hermes invokes
    # this script, and nothing should -- on a push runtime the queue is the
    # catch-up, because delivery can fail and the cursor does not move until it
    # succeeds. DESIGN.md, "What the push runtimes use instead", has the full
    # account.
    #
    # This comment used to read "ADAPT THIS BLOCK TO OPENCLAW'S HOOK CONTRACT",
    # which sent operators of a runtime that never runs this file looking for
    # what was calling it. If you are porting to a fourth runtime, the question
    # to answer first is not what shape to emit -- it is whether that runtime's
    # delivery can fail. If it can, it needs no hook at all.
    additional_context = "\n\n".join(parts)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        },
    }
    system_messages = system_message_parts(listener_state, dispatcher_state,
                                           faults, runtime, spool_lines, lines)
    system_message = ". ".join(system_messages) if system_messages else None
    # Omitted rather than sent as null when there is nothing to say. Claude Code
    # validates this payload and rejects `"systemMessage": null` with
    # `Hook JSON output validation failed — (root): Invalid input`, which kills
    # the whole hook: no replay, no watch command, no offset.
    #
    # The failure is inverted, which is what made it survive. Every branch above
    # that produces a string is a branch where something is wrong, so the hook
    # worked whenever the install was broken and failed only once it was healthy
    # with mail waiting in the spool — the one case it exists to serve. The first
    # Claude Code host saw it work on day one because its dispatcher was still
    # reporting errors from a crash-loop; the same host's next session, after the
    # install was repaired, got nothing at all.
    if system_message is not None:
        payload["systemMessage"] = system_message
    print(json.dumps(payload), flush=True)
    if (runtime == "codex" and spool_lines
            and len(additional_context.encode("utf-8")) <= CODEX_ACK_CONTEXT_LIMIT):
        codex_replayed(spool_lines)
        acknowledge_spool(spool_offset, spool_through)
    # -----------------------------------------------------------------------
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # never let a hook failure block a session
