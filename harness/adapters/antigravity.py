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

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import accepted, config

NAME = "antigravity"

SPOOL_RELATIVE = "antigravity.spool"

# The last headless run (#749 F2, FR-9/FR-10), for `paynani doctor`. Never the
# prompt or the reply: only ids, times, the outcome and a one-line reason.
STATUS_RELATIVE = "antigravity.json"

# PAYNANI_ANTIGRAVITY_MODE=agent turns on a headless `agy -p` per event.
MODE_VAR = "PAYNANI_ANTIGRAVITY_MODE"
# The turn limit handed to `agy --print-timeout`, in seconds. The dispatcher
# waits for the run, so this bounds how long one event can hold the queue.
TIMEOUT_VAR = "PAYNANI_ANTIGRAVITY_TIMEOUT"
DEFAULT_TIMEOUT = 300
# What subprocess waits beyond --print-timeout, so agy's own limit fires first
# and reports itself in JSON instead of being killed without a word.
KILL_GRACE = 30

# Text that means the Google login is not usable from here (FR-10). The owner
# fixes it; retrying does not.
LOGIN_MARKERS = ("authentication required", "secret keyring is locked", "not logged in")
# A rejected tool permission. agy 1.5.3 in agentMode "auto" decides with a
# classifier and was not seen to refuse in F0, so this follows the documented
# wording; a run that reports SUCCESS with one of these in stderr is a failure.
PERMISSION_RE = re.compile(r"permission[^\n]{0,80}\b(denied|rejected|refused)\b", re.IGNORECASE)

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


def status_path():
    return _state_dir() / STATUS_RELATIVE


def agent_mode():
    return (os.environ.get(MODE_VAR) or "").strip().lower() == "agent"


def run_timeout():
    try:
        value = int((os.environ.get(TIMEOUT_VAR) or "").strip() or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def _repo_root():
    import paths
    return paths.repo_root()


def _one_line(text, limit=300):
    line = " ".join(str(text or "").split())
    return line[:limit]


def _note_run(record):
    """Keep the last headless run in state/antigravity.json, atomically, mode 600."""
    path = status_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except (OSError, ValueError):
            current = {}
        current["last_agent_run"] = record
        fd, tmp = tempfile.mkstemp(prefix=".antigravity.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(current, indent=2, sort_keys=True) + "\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        # The record is for diagnosis only; failing to write it must not fail
        # a delivery that already reached the spool.
        pass


def _agy_error(stderr):
    """The JSON after `AGY_ERROR:` in stderr, or {}. agy prints it on a failed run."""
    for line in reversed((stderr or "").splitlines()):
        if line.startswith("AGY_ERROR:"):
            try:
                data = json.loads(line[len("AGY_ERROR:"):].strip())
            except ValueError:
                return {"short_error": _one_line(line[len("AGY_ERROR:"):])}
            return data if isinstance(data, dict) else {}
    return {}


def _result_json(stdout):
    """The `--output-format json` object: the last line of stdout that parses."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    return None


def classify_run(returncode, stdout, stderr):
    """
    Read what `agy -p --output-format json` reported (FR-10).

    Returns (ok, problem, detail, facts). `ok` is true only with exit 0,
    `status: SUCCESS` and no permission refusal in stderr; agy can exit 0 with a
    refused tool, and that must not read as done. `problem` is one of "",
    "login", "permission", "timeout" or "run".
    """
    result = _result_json(stdout) or {}
    agy_error = _agy_error(stderr)
    facts = {
        "exit": returncode,
        "status": str(result.get("status") or ""),
        "conversation_id": str(result.get("conversation_id") or ""),
        "finished_reason": str(result.get("finished_reason") or agy_error.get("reason") or ""),
    }
    error = _one_line(result.get("error") or agy_error.get("short_error") or "")
    refused = PERMISSION_RE.search(stderr or "")
    if returncode == 0 and facts["status"] == "SUCCESS":
        # agy writes log lines to stderr, so on a good run only a refused
        # permission turns it into a failure; a log line that mentions a
        # login is not one (Iris's review of #761).
        if refused:
            return False, "permission", _one_line(refused.group(0)), facts
        return True, "", "", facts
    haystack = " ".join((error, stderr or "")).lower()
    if any(marker in haystack for marker in LOGIN_MARKERS):
        return False, "login", error or _one_line(stderr), facts
    if refused:
        return False, "permission", _one_line(refused.group(0)), facts
    if facts["finished_reason"] == "print_timeout":
        return False, "timeout", error or "the turn did not finish within --print-timeout", facts
    if not result:
        tail = (stderr or stdout or "").strip().splitlines()
        return False, "run", _one_line(tail[-1] if tail else "no output"), facts
    return False, "run", error or f"status {facts['status'] or '?'} with exit {returncode}", facts


def agent_prompt(envelope):
    """The notice itself, then where to read the event and how to treat it."""
    import event as ev
    event_id = str(envelope.get("event_id") or "").strip()
    text = envelope.get("notification_text") or ""
    return f"{text}\n\n{ev.codex_event_prompt(event_id)}"


def _start_agent_run(envelope):
    """
    Opt-in: run `agy -p` in the clone so mail reaches an agent with no TUI open.

    Off unless PAYNANI_ANTIGRAVITY_MODE=agent, because it lets a roster message
    start work on this machine with nobody watching. Never with
    --dangerously-skip-permissions: agy's own permission rules and agentMode
    decide what the run may do. A new conversation per event: resuming one by id
    worked in F0 but took 105 s against 7 s, and a fresh one cannot collide with
    a TUI the owner has open.
    """
    binary = find_binary()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {"event_id": str(envelope.get("event_id") or ""), "at": started}
    if not binary:
        record.update(ok=False, problem="run", detail="no agy binary found (set AGY or install it in ~/.local/bin)")
        _note_run(record)
        return False, record
    limit = run_timeout()
    try:
        run = subprocess.run(
            [binary, "-p", agent_prompt(envelope), "--output-format", "json",
             "--print-timeout", f"{limit}s"],
            cwd=str(_repo_root()), capture_output=True, text=True, timeout=limit + KILL_GRACE)
    except subprocess.TimeoutExpired:
        record.update(ok=False, problem="timeout", detail=f"agy -p did not return within {limit + KILL_GRACE}s")
        _note_run(record)
        return False, record
    except OSError as exc:
        record.update(ok=False, problem="run", detail=_one_line(f"{binary} could not be run: {exc}"))
        _note_run(record)
        return False, record
    ok, problem, detail, facts = classify_run(run.returncode, run.stdout, run.stderr)
    record.update(facts)
    record.update(ok=ok, problem=problem, detail=detail,
                  finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    _note_run(record)
    return ok, record


def last_agent_run():
    """The record _note_run() kept, or None."""
    try:
        data = json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = data.get("last_agent_run") if isinstance(data, dict) else None
    return entry if isinstance(entry, dict) else None


def deliver(envelope):
    """
    Write the rendered line to the spool, and with agent mode run `agy -p`.

    `ACCEPTED` means the event is durably where the next hook will find it, not
    that a session has seen it. Do not report more than that.

    A failed headless run is still ACCEPTED: the spool already has the line and
    the next conversation's hook shows it, and retrying would append it again on
    every attempt. The failure is kept in state/antigravity.json for
    `paynani doctor`, and named in the detail the dispatcher logs.
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
    if agent_mode():
        ok, record = _start_agent_run(envelope)
        if not ok:
            return accepted(f"spooled; agy -p failed ({record.get('problem')}): {record.get('detail')}")
        return accepted("spooled; agy -p run completed")
    return accepted()
