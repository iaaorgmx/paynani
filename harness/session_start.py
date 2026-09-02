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

import json, os, pathlib, platform, subprocess, sys

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

# Claude Code cannot be pushed into, so its session is the consumer: the
# dispatcher writes the spool and never reads it, and these two files are how a
# session knows where it got to. See DESIGN.md, "Why one runtime pulls".
SPOOL = STATE_DIR / "session.spool"
SESSION_OFFSET = STATE_DIR / "session.offset"
SESSION_WATCH = REPO / "harness/session_watch.sh"
RUNTIME_ENV = REPO / "runtime.env"

MAX_REPLAY = 20   # enough to see overnight without flooding the context window
MAX_DISPATCH_ERR = 5   # the last few lines say whether it is still failing
VERSION_TIMEOUT = 20   # above version.sh's own 10s, so its timeout fires first


def launchd_down(label):
    """True only if launchd positively reports that a label is not running."""
    try:
        r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return True
        return "state = running" not in (r.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def unit_down(unit):
    """True only if we positively confirmed the unit is not active."""
    if platform.system() == "Darwin":
        labels = {
            SERVICE: SERVICE_LABEL,
            DISPATCH_SERVICE: DISPATCH_SERVICE_LABEL,
        }
        return launchd_down(labels.get(unit, unit))
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit],
                           timeout=5)
        return r.returncode != 0
    except (OSError, subprocess.SubprocessError):
        # Could not ask. Stay quiet rather than cry wolf about a live service.
        return False


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
    return [ln for ln in text.splitlines() if ln.strip()][-MAX_DISPATCH_ERR:]


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


def read_spool_backlog():
    """
    (rendered lines, capped, byte offset read through) for the Claude Code spool.

    **This does not advance the offset**, and that asymmetry is deliberate. The
    watch writes the offset when it is armed, so an agent that reads this and
    never arms the watch replays the same messages next time. Replaying is the
    survivable error; skipping is not, and a hook that acknowledged on the
    agent's behalf would be claiming an arming it cannot observe.
    """
    try:
        start = int(SESSION_OFFSET.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        start = 0
    try:
        size = SPOOL.stat().st_size
    except OSError:
        return [], False, start
    # A spool shorter than the recorded offset means the file was replaced or
    # truncated underneath us. Trusting the stale offset would step over
    # everything now in it, so start again rather than skip.
    if size < start:
        start = 0
    try:
        with open(SPOOL, "rb") as handle:
            handle.seek(start)
            data = handle.read()
    except OSError:
        return [], False, start
    lines = [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
    return lines[-MAX_REPLAY:], len(lines) > MAX_REPLAY, start + len(data)


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
    lines, capped = read_backlog()
    spool_lines, spool_capped, spool_through = ([], False, 0)
    if runtime == "claudecode":
        spool_lines, spool_capped, spool_through = read_spool_backlog()
    down = unit_down(SERVICE)
    dispatch_down = unit_down(DISPATCH_SERVICE)
    faults = dispatcher_faults()

    parts = []
    if down:
        check = (f"`launchctl print gui/$(id -u)/{SERVICE_LABEL}`" if platform.system() == "Darwin"
                 else f"`systemctl --user status {SERVICE}`")
        parts.append(
            f"MAIL LISTENER IS DOWN — {SERVICE} is not active, so no new mail is "
            f"being detected at all. Check {check} and "
            "restart it before relying on mail notifications."
        )

    if dispatch_down:
        check = (f"`launchctl print gui/$(id -u)/{DISPATCH_SERVICE_LABEL}`" if platform.system() == "Darwin"
                 else f"`systemctl --user status {DISPATCH_SERVICE}`")
        parts.append(
            f"MAIL DISPATCHER IS DOWN — {DISPATCH_SERVICE} is not active. Mail is still "
            "being detected and journalled, but nothing is delivering it into a "
            f"session. Check {check}."
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
                + (f", trimmed to the most recent {MAX_REPLAY}" if spool_capped else "")
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

    if lines:
        header = (f"Mail queued but not yet delivered ({len(lines)} message(s)"
                  + (f", trimmed to the most recent {MAX_REPLAY}" if capped else "")
                  + "). It stays in the journal until a runtime accepts it, so "
                  "expect the dispatcher to deliver it as well rather than "
                  "treating this as the only copy:")
        parts.append(header + "\n" + "\n".join(lines))
    elif runtime != "claudecode":
        parts.append("No unseen mail since the last session acknowledged the log.")

    version = version_line()
    if version:
        parts.append(version)

    # ---- CLAUDE CODE'S HOOK CONTRACT ---------------------------------------
    # This is the payload Claude Code's SessionStart hook accepts, and this hook
    # runs on Claude Code only. `scripts/claude_hook.py --install` registers it
    # there; nothing on OpenClaw or Hermes invokes this script, and nothing
    # should -- on a push runtime the queue is the catch-up, because delivery
    # can fail and the cursor does not move until it succeeds. DESIGN.md, "What
    # the other two runtimes use instead", has the full account.
    #
    # This comment used to read "ADAPT THIS BLOCK TO OPENCLAW'S HOOK CONTRACT",
    # which sent operators of a runtime that never runs this file looking for
    # what was calling it. If you are porting to a fourth runtime, the question
    # to answer first is not what shape to emit -- it is whether that runtime's
    # delivery can fail. If it can, it needs no hook at all.
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        },
    }
    system_message = (
        "Mail listener is DOWN — new mail is not being detected" if down
        else "Mail dispatcher is DOWN — mail is journalled but not delivered" if dispatch_down
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
    print(json.dumps(payload))
    # -----------------------------------------------------------------------
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # never let a hook failure block a session
