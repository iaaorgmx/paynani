#!/usr/bin/env python3
"""
The Antigravity CLI adapter: deliver an event by appending it to a spool (#749).

Antigravity CLI (`agy`) has the same shape as Claude Code for this purpose.
Nothing outside a running `agy` session can speak into it: there is no
documented command, socket or local API that puts a message into an open TUI.
Remote Control does, but through Google's service and a browser, which is not
something this project can call.

So delivery is a spool, read from inside the session by `agy`'s own hooks:

- `SessionStart`, which fires once when a new conversation starts;
- `PreInvocation` with `invocationNum == 0`, which marks the start of every
  turn. A resumed conversation (`agy -c`, `--conversation`, `/resume`) never
  fires `SessionStart`, so without this one mail that arrived while it was
  closed would wait until somebody opened a brand-new conversation.

Both hooks run `harness/session_start.py --antigravity`, which answers with
`injectSteps` (#749 FR-2). `scripts/antigravity_hook.py` registers them (FR-3).

The spool is `antigravity.spool` and not `*.log` for the reason the Claude Code
adapter gives: `rotate_logs.py` rotates every `*.log` in the state directory,
and the hook reads this file by byte offset.
"""

import os
import shutil
from pathlib import Path

from . import accepted, config

NAME = "antigravity"

SPOOL_RELATIVE = "antigravity.spool"

# `agy` keeps its settings, hooks and rules under ~/.gemini; the mailbox settings
# follow the harness convention in this root's workspace folder (#749 FR-4).
HARNESS_ROOT = "~/.gemini/antigravity-cli"

# The official installer puts `agy` in ~/.local/bin, which a systemd user
# service does not have on its PATH.
CANDIDATES = (
    "~/.local/bin/agy",
    "/usr/local/bin/agy",
)


def _state_dir():
    """Imported lazily so this module stays importable without the package path."""
    import paths
    return paths.state_dir()


def spool_path():
    return _state_dir() / SPOOL_RELATIVE


def find_binary():
    explicit = os.environ.get("AGY", "").strip()
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("agy")
    if found:
        return found
    for candidate in CANDIDATES:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def detect():
    """
    True when `agy` is installed. Used only by auto-selection.

    The binary and not `~/.gemini`: the Gemini CLI and the Antigravity IDE use
    that directory too, so it says nothing about which agent lives here.
    """
    return find_binary() is not None


def check():
    """
    Whether this adapter could deliver right now, without delivering anything.

    As with Claude Code, whether a session is open is neither knowable nor
    needed: an event in the spool with no session waits for the next hook. An
    unwritable spool is the only failure.
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

    `fsync` before returning: the listener advances its UID once delivery is
    acknowledged, and a record acknowledged but not on disk is lost.
    """
    spool = spool_path()
    spool.parent.mkdir(parents=True, exist_ok=True)
    # One record is one line; a folded subject must not become two records.
    flattened = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    line = flattened.rstrip() + "\n"
    with open(spool, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
        return handle.tell()


def deliver(envelope):
    """
    Write the rendered line to the spool.

    `ACCEPTED` means the event is durably where the next hook will find it, not
    that a session has seen it. Do not report more than that.
    """
    text = envelope.get("notification_text") or ""
    if not text:
        return config(f"event {envelope.get('event_id')} has no notification_text to send")
    try:
        _append(text)
    except OSError as exc:
        return config(
            f"could not write {spool_path()}: {exc}. Mail is being journalled but "
            "cannot reach an Antigravity session."
        )
    return accepted()
