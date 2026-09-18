#!/usr/bin/env python3
"""
The OpenClaw adapter.

Mail is delivered as a notification to the live session. The notification line
still carries the roster tag when the listener matched the sender, and for
roster mail a second line says what to do with it (`event.openclaw_text`). This
adapter intentionally does not start an agent run from incoming mail: the
heartbeat that shows the line is the run, and the agent's own instructions,
which `scripts/openclaw_rules.py` puts in place, are what make it act.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import accepted, config, retry

# `event` is imported by its bare name, as dispatch.py does. The dispatcher puts
# harness/ on the path already; this makes the import hold under any other
# package name too, the way hermes.py does for `paths`.
_HARNESS = Path(__file__).resolve().parent.parent
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

import event as ev   # noqa: E402

NAME = "openclaw"

# A systemd user service gets a minimal PATH with nothing under $HOME, so a
# binary installed by npm is invisible to it while an interactive shell finds it
# without trouble. That split is the worst kind: every check passes, the log
# fills, and nothing is ever delivered. Look where it actually gets installed.
CANDIDATES = (
    "~/.npm-global/bin/openclaw",
    "~/.local/bin/openclaw",
    "~/node_modules/.bin/openclaw",
    "/usr/local/bin/openclaw",
)

TIMEOUT = 30


def find_binary():
    explicit = os.environ.get("OPENCLAW", "").strip()
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    found = shutil.which("openclaw")
    if found:
        return found
    for candidate in CANDIDATES:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    for nvm in sorted(Path("~/.nvm/versions/node").expanduser().glob("*/bin/openclaw")):
        if os.access(nvm, os.X_OK):
            return str(nvm)
    return None


def detect():
    """True when this runtime looks present. Used only by auto-selection."""
    return find_binary() is not None


def check():
    """
    Whether this adapter could deliver right now, without delivering anything.

    Finding the binary is not the same as being able to run it: openclaw is a
    Node program, and the service PATH decides which node it gets. A version
    mismatch leaves it present, executable, and failing on every call.
    """
    binary = find_binary()
    if not binary:
        return config(
            "no openclaw binary found. Set OPENCLAW=/full/path/to/openclaw in the "
            "unit, or put it on PATH."
        )
    try:
        run = subprocess.run([binary, "--version"], capture_output=True,
                             text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return config(f"{binary} could not be run: {exc}")
    if run.returncode != 0:
        return config(
            f"{binary} --version exited {run.returncode}. It is installed but not "
            "runnable in this environment, which is usually the wrong node on the "
            "service PATH."
        )
    return accepted((run.stdout or "").strip())


def _system_event(binary, text):
    return subprocess.run([binary, "system", "event", "--mode", "now", "--text", text],
                          capture_output=True, text=True, timeout=TIMEOUT)


def deliver(envelope):
    """
    Push one event into the live session.

    A nonzero exit is retryable rather than fatal: openclaw restarting, or a
    session not yet up, is a condition that clears on its own. Only a missing or
    unrunnable binary is reported as configuration, because no amount of retrying
    installs one.
    """
    binary = find_binary()
    if not binary:
        return config(
            "no openclaw binary found. Mail is being journalled but cannot be "
            "delivered. Set OPENCLAW=/full/path/to/openclaw in the unit, or put "
            "it on PATH."
        )

    text = ev.openclaw_text(envelope)
    if not text:
        return config(f"event {envelope.get('event_id')} has no notification_text to send")

    try:
        run = _system_event(binary, text)
    except subprocess.TimeoutExpired:
        return retry(f"{binary} did not return within {TIMEOUT}s")
    except OSError as exc:
        return retry(f"{binary} could not be run: {exc}")

    if run.returncode == 0:
        return accepted()
    detail = (run.stderr or run.stdout or "no output").strip().splitlines()
    return retry(f"exit {run.returncode}: {detail[0] if detail else 'no output'}")
