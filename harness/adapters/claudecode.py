#!/usr/bin/env python3
"""
The Claude Code adapter: deliver an event by appending it to the session spool.

This runtime is different from the other two in one way that shapes everything
here. **Nothing outside a Claude Code session can speak into it.** There is no
`claude system event`; `claude -p --resume` starts a fresh headless turn and
never appears on the screen of the session a human is sitting in front of.

So delivery inverts. OpenClaw and Hermes are pushed to; Claude Code comes and
gets it. This adapter's whole job is to put the rendered line somewhere two
session-side readers can find it:

- the `SessionStart` hook, which replays what arrived while nothing was running;
- an armed `Monitor`, which reports each new line as it lands.

Both read by byte offset, which is what makes the two of them safe together: the
hook replays through byte N and asks for the monitor to be armed *at* N, so
nothing falls in the gap and nothing is shown twice.

**Why the spool is not named `*.log`.** `rotate_logs.py` rotates every `*.log` in
the state directory, and rotation renumbers bytes. Both readers index into this
file by offset, so a rotation between a hook replay and a monitor arming would
silently resume at the wrong place — showing mail twice, or stepping over mail
that was never shown. A skipped message and a quiet mailbox are indistinguishable
from the outside, which is the failure this project exists to prevent. The `.spool`
extension keeps it out of that glob deliberately; do not rename it to `.log`.

The file therefore grows without bound. That is a real cost, accepted for now
because it grows by one line per message, and preferable to a rotation scheme
that would have to move two independent readers' cursors atomically.
"""

import os
import shutil
import subprocess
from pathlib import Path

from . import accepted, config, retry

NAME = "claudecode"

# The rendered line goes here; the hook and the monitor read it.
SPOOL_RELATIVE = "session.spool"

# Claude Code keeps its per-user state here, and the credentials convention puts
# the mailbox settings in this root's workspace folder.
HARNESS_ROOT = "~/.claude"

# Same lesson as the OpenClaw adapter: a systemd user service gets a minimal
# PATH with nothing under $HOME, so a binary an interactive shell finds without
# trouble is invisible here.
CANDIDATES = (
    "~/.local/bin/claude",
    "~/.npm-global/bin/claude",
    "~/node_modules/.bin/claude",
    "/usr/local/bin/claude",
)

TIMEOUT = 120


def _state_dir():
    """Imported lazily so this module stays importable without the package path."""
    import paths
    return paths.state_dir()


def spool_path():
    return _state_dir() / SPOOL_RELATIVE


def find_binary():
    explicit = os.environ.get("CLAUDE", "").strip()
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("claude")
    if found:
        return found
    for candidate in CANDIDATES:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def detect():
    """
    True when this runtime looks present. Used only by auto-selection.

    Deliberately the binary and not `~/.claude`: that directory is created by
    anything that has ever run Claude Code once, including on a host whose agent
    lives in a different harness entirely. Auto-selection refusing to guess is
    worth more than auto-selection being clever.
    """
    return find_binary() is not None


def check():
    """
    Whether this adapter could deliver right now, without delivering anything.

    Note what is *not* checked: whether a session is running, or whether anyone
    has armed a monitor. Neither is knowable from here, and neither has to be —
    an event written to the spool with no session open is not lost, it is waiting
    for the next `SessionStart` hook to replay it. That is the property this
    design is built on, and it is why an unwritable spool is the only real
    failure.
    """
    spool = spool_path()
    try:
        spool.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return config(f"state directory {spool.parent} cannot be created: {exc}")
    if spool.exists() and not os.access(spool, os.W_OK):
        return config(f"{spool} exists but is not writable")
    if not os.access(spool.parent, os.W_OK):
        return config(f"{spool.parent} is not writable, so no event can be delivered")
    return accepted(str(spool))


def _append(text):
    """
    Append one line, durably, and report the offset the file now ends at.

    `fsync` before returning, for the same reason the journal does it: the
    listener advances its UID once delivery is acknowledged, and a record
    acknowledged but not on disk is a message nobody will ever fetch again.
    """
    spool = spool_path()
    spool.parent.mkdir(parents=True, exist_ok=True)
    # One record is exactly one line. A rendered notification can carry a line
    # break — a folded subject is the usual source — and letting it through would
    # make the monitor report one message as two and leave every later offset a
    # line out of step with the file it indexes into.
    flattened = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    line = flattened.rstrip() + "\n"
    with open(spool, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
        return handle.tell()


def _start_agent_run(text):
    """
    Opt-in: start a headless run so mail can reach an agent with no session open.

    Off unless PAYNANI_CLAUDE_MODE=agent, because it widens what an inbound
    message can cause. The spool write still happens either way — the run is in
    addition to delivery, never instead of it, so turning this off can never lose
    an event.
    """
    binary = find_binary()
    if not binary:
        return retry("no claude binary found for agent mode; event is spooled")
    try:
        run = subprocess.run([binary, "-p", text], capture_output=True,
                             text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return retry(f"{binary} -p did not return within {TIMEOUT}s; event is spooled")
    except OSError as exc:
        return retry(f"{binary} could not be run: {exc}; event is spooled")
    if run.returncode != 0:
        detail = (run.stderr or run.stdout or "no output").strip().splitlines()
        return retry(f"claude -p exit {run.returncode}: {detail[0] if detail else 'no output'}")
    return accepted()


def deliver(envelope):
    """
    Write the rendered line to the spool.

    Reaching the spool is `ACCEPTED` and the dispatcher's cursor moves past it.
    Be clear about what that does and does not claim: it means the event is
    durably where a session will find it, not that a session has seen it. The
    Hermes adapter makes the same bargain with HTTP 202, and states it in the
    same terms.

    The difference from Hermes is worth keeping in mind. There, something is
    always running to drain the queue. Here there may be no session for hours,
    and the `SessionStart` hook replaying from the offset is the only reason that
    is safe rather than a slow leak.
    """
    text = envelope.get("notification_text") or ""
    if not text:
        return config(f"event {envelope.get('event_id')} has no notification_text to send")

    try:
        _append(text)
    except OSError as exc:
        return config(
            f"could not write {spool_path()}: {exc}. Mail is being journalled but "
            "cannot reach a session."
        )

    if (os.environ.get("PAYNANI_CLAUDE_MODE") or "").strip().lower() == "agent":
        result = _start_agent_run(text)
        if not result.ok:
            # The event is already spooled and will be replayed at the next
            # session start, so a failed run must not hold the cursor: retrying
            # would append a duplicate line on every attempt.
            return accepted(f"spooled; agent run failed: {result.detail}")

    return accepted()
