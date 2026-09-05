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

import json, os, pathlib, platform, select, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import event as ev
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
SESSION_WATCH = REPO / "harness/session_watch.sh"
RUNTIME_ENV = REPO / "runtime.env"

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
    # Routine notes are dropped. The dispatcher marks them, because it is the
    # only party that knows which of its own lines is a complaint — and the line
    # it writes on every successful startup used to make this hook announce
    # PROBLEMS on every healthy install (#15).
    lines = [ln for ln in text.splitlines()
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


def main():
    runtime = selected_runtime()
    if "--session-end" in sys.argv[1:]:
        forget_codex_session()
        return 0
    if runtime == "codex":
        remember_codex_session(read_hook_input())
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

        parts.append(
            "ARM THE MAIL WATCH NOW, before doing anything else, with a persistent "
            "Monitor running exactly:\n\n"
            f"    bash {SESSION_WATCH} {STATE_DIR} {spool_through}\n\n"
            "Each stdout line is one new mail notification. The byte offset is not "
            "optional and must not be rounded: this hook has replayed the spool "
            "through exactly that byte, so starting anywhere else either repeats "
            "messages or steps over ones nobody has seen. Arming is also what "
            "acknowledges the replay above — if you skip it, the next session "
            "shows these same messages again, and no new mail reaches you for the "
            "rest of this one."
        )
    elif runtime == "codex":
        if spool_lines:
            parts.append(
                f"Mail that arrived before this Codex session event "
                f"({len(spool_lines)} message(s)"
                + (f", showing the oldest {MAX_REPLAY}" if spool_capped else "")
                + "):\n" + "\n".join(spool_lines)
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
    elif runtime not in ("claudecode", "codex"):
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
    system_message = (
        "Mail listener is DOWN — new mail is not being detected" if listener_state == "down"
        else "Mail dispatcher is DOWN — mail is journalled but not delivered" if dispatcher_state == "down"
        else "Mail service status unknown — could not query service manager"
        if listener_state == "unknown" or dispatcher_state == "unknown"
        else "Dispatcher reported errors — mail may not be reaching the session" if faults
        else (f"{len(lines)} unseen mail notification(s)" if lines else None)
    )
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
        acknowledge_spool(spool_offset, spool_through)
    # -----------------------------------------------------------------------
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # never let a hook failure block a session
