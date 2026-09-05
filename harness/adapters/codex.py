#!/usr/bin/env python3
"""
The OpenAI Codex adapter: deliver an event by appending it to the Codex spool.

Codex CLI has SessionStart hooks, so a session can be told what arrived before
it started. This adapter's job is narrower: put the rendered notification line
durably where that hook can find it. Reaching the spool is `ACCEPTED`; it means
the bytes are on disk for a future Codex session, not that a live session has
already seen them.

The spool is deliberately not a `*.log`. `rotate_logs.py` rotates log files, and
rotation renumbers bytes. The session-side replay reads by byte offset, so a
rotated spool would either repeat mail or step over mail nobody saw.
"""

import os
import shutil
from pathlib import Path

from . import accepted, config

NAME = "codex"
SPOOL_RELATIVE = "codex.spool"

CANDIDATES = (
    "~/.local/bin/codex",
    "~/.npm-global/bin/codex",
    "~/node_modules/.bin/codex",
    "/usr/local/bin/codex",
)


def _state_dir():
    """Imported lazily so this module stays importable without the package path."""
    import paths
    return paths.state_dir()


def spool_path():
    return _state_dir() / SPOOL_RELATIVE


def find_binary():
    explicit = os.environ.get("CODEX", "").strip()
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("codex")
    if found:
        return found
    for candidate in CANDIDATES:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def detect():
    """
    True when Codex CLI looks present. Used only by auto-selection.

    Deliberately the binary and not `~/.codex`: that directory can exist on a
    host whose active agent lives in another runtime. Auto-selection refusing to
    guess is worth more than treating a stale config directory as a live runtime.
    """
    return find_binary() is not None


def check():
    """
    Whether this adapter can accept an event right now.

    A Codex binary is useful for hook installation and future live delivery, but
    not required to deliver into the spool. The durable handoff is the file
    write; a missing or inactive session is not a dispatcher fault.
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
    Append one physical line and fsync it before reporting success.

    A folded subject can carry a newline. Letting it through would turn one mail
    event into two spool records and put every later byte offset out of step.
    """
    spool = spool_path()
    spool.parent.mkdir(parents=True, exist_ok=True)
    flattened = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    line = flattened.rstrip() + "\n"
    with open(spool, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
        return handle.tell()


def deliver(envelope):
    text = envelope.get("notification_text") or ""
    if not text:
        return config(f"event {envelope.get('event_id')} has no notification_text to send")

    try:
        _append(text)
    except OSError as exc:
        return config(
            f"could not write {spool_path()}: {exc}. Mail is being journalled but "
            "cannot reach a Codex session."
        )
    return accepted()
