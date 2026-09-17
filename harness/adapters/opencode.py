#!/usr/bin/env python3
"""
The OpenCode adapter: deliver an event by appending it to the OpenCode spool.

OpenCode has an HTTP API, and it would be easy to read that as "push runtime".
It is not one here, for three reasons that do not go away with more code:

- The TUI serves its API on a random port. A systemd unit or a LaunchAgent has
  no stable way to learn which port, or which of several sessions is the one a
  person is sitting in front of.
- That server asks for no credentials unless `OPENCODE_SERVER_PASSWORD` is set,
  so pushing into it means either an open local endpoint or one more secret for
  this project to own.
- On a push runtime the cursor waits until the session took the event. A TUI is
  closed most of the day, and the dispatcher would stall every time it was.

So delivery inverts, as on Claude Code and Codex. This adapter writes each event
id plus its rendered notification to `state/opencode.spool` and stops there. The
session side is `harness/opencode/paynani.js`, a plugin that runs inside the
OpenCode process: it already holds a client connected to its own server, sees
its own sessions go idle, and lives exactly as long as OpenCode is open. It asks
`session_start.py --opencode-pending` what is unread and acknowledges with
`--opencode-ack` once OpenCode took the prompt.

`accepted()` therefore means the line is durable in the spool. It does not mean
an OpenCode session has seen it.

The spool is deliberately not a `*.log`. `rotate_logs.py` rotates log files, and
rotation renumbers bytes. The plugin reads by byte offset, so a rotated spool
would either repeat mail or step over mail nobody saw.
"""

import json
import os
import shutil
from pathlib import Path

from . import accepted, config

NAME = "opencode"
SPOOL_RELATIVE = "opencode.spool"
OFFSET_RELATIVE = "opencode.offset"

# Same lesson as the other adapters: a systemd user service gets a minimal PATH
# with nothing under $HOME. `~/.opencode/bin` is where OpenCode's own installer
# puts the binary.
CANDIDATES = (
    "~/.opencode/bin/opencode",
    "~/.local/bin/opencode",
    "~/.npm-global/bin/opencode",
    "~/node_modules/.bin/opencode",
    "/usr/local/bin/opencode",
)


def _state_dir():
    """Imported lazily so this module stays importable without the package path."""
    import paths
    return paths.state_dir()


def spool_path():
    return _state_dir() / SPOOL_RELATIVE


def offset_path():
    return _state_dir() / OFFSET_RELATIVE


def find_binary():
    explicit = os.environ.get("OPENCODE", "").strip()
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("opencode")
    if found:
        return found
    for candidate in CANDIDATES:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def detect():
    """
    True when OpenCode looks present. Used only by auto-selection.

    Deliberately the binary and not `~/.config/opencode`: that directory can
    exist on a host whose active agent lives in another runtime. Auto-selection
    refusing to guess is worth more than treating a stale config directory as a
    live runtime.
    """
    return find_binary() is not None


def check():
    """
    Whether this adapter can accept an event right now.

    No OpenCode binary is required: the durable handoff is the file write, and
    a closed OpenCode is not a dispatcher fault. The event waits in the spool
    until the plugin in the next OpenCode process picks it up.
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


def _one_line(text):
    return str(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _append(text, event_id):
    """
    Append one physical line and fsync it before reporting success.

    A folded subject can carry a newline. Letting it through would turn one mail
    event into two spool records and put every later byte offset out of step.
    """
    spool = spool_path()
    spool.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event_id": _one_line(event_id),
        "notification_text": _one_line(text).rstrip(),
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(spool, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def deliver(envelope):
    text = envelope.get("notification_text") or ""
    if not text:
        return config(f"event {envelope.get('event_id')} has no notification_text to send")
    event_id = _one_line(envelope.get("event_id") or "").strip()
    if not event_id:
        return config("event has no event_id to spool")
    try:
        _append(text, event_id)
    except OSError as exc:
        return config(
            f"could not write {spool_path()}: {exc}. Mail is being journalled but "
            "cannot reach an OpenCode session."
        )
    return accepted()
