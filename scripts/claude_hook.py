#!/usr/bin/env python3
"""
Register (or show) the session-start hook in Claude Code's settings.

**This file is not a managed artifact and never becomes one.** `settings.json`
belongs to the person using Claude Code and holds configuration this project
knows nothing about. The installer's ownership model is built on converging files
it owns, and converging this one would eventually overwrite somebody's unrelated
hooks with a copy of what we last wrote. So it stays outside the manifest, and
this script edits it by merge, additively, on request.

The same rule §5.0 applies to `~/.config/himalaya/config.toml`, for the same
reason and after the same near miss.

Two hooks since #170. SessionStart replays the spool, writes this session's
watch registry and says how to arm the watch. UserPromptSubmit adds one line
to a turn only when mail is waiting in the spool and no live watch will show
it: a Monitor Claude Code took away after 30 minutes, with mail arriving after,
used to stay invisible until the next session. Both are registered by this
script, additively, and --check reports each.

Usage:
  claude_hook.py --print     show the fragments, change nothing
  claude_hook.py --check     report whether both are registered
  claude_hook.py --install   merge in whichever is missing, backing up first
"""

import argparse
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = pathlib.Path.home() / ".claude" / "settings.json"
HOOK = ROOT / "harness" / "session_start.py"
EVENT = "SessionStart"
PROMPT_EVENT = "UserPromptSubmit"
TIMEOUT = 15
PROMPT_TIMEOUT = 5
EVENTS = (EVENT, PROMPT_EVENT)


def command(event=EVENT):
    if event == PROMPT_EVENT:
        return f"python3 {HOOK} --prompt-submit"
    return f"python3 {HOOK}"


def fragment(event=EVENT):
    if event == PROMPT_EVENT:
        return {
            "type": "command",
            "command": command(event),
            "timeout": PROMPT_TIMEOUT,
            "statusMessage": "Checking paynani for unseen mail",
        }
    return {
        "type": "command",
        "command": command(),
        "timeout": TIMEOUT,
        "statusMessage": "Checking paynani",
    }


def load(path):
    """Existing settings, or an empty document. A broken file is never guessed at."""
    if not path.is_file():
        return {}, False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}")
    if not text.strip():
        return {}, False
    try:
        return json.loads(text), True
    except json.JSONDecodeError as exc:
        # Refuse rather than repair. Rewriting a file we could not parse is how
        # an install eats configuration it was never asked to touch.
        raise SystemExit(
            f"{path} is not valid JSON ({exc}).\n"
            "Fix it by hand and run this again; nothing has been changed."
        )


def already_registered(settings, event=EVENT):
    for entry in settings.get("hooks", {}).get(event, []) or []:
        for hook in entry.get("hooks", []) or []:
            if str(HOOK) in (hook.get("command") or ""):
                return True
    return False


def missing_events(settings):
    return [event for event in EVENTS if not already_registered(settings, event)]


def merge(settings, events=EVENTS):
    """
    Add our hooks, leaving every other hook exactly where it was.

    Appends to each event's list rather than replacing it: a host may already
    run its own hooks on these events, and Claude Code runs all of them.
    """
    hooks = settings.setdefault("hooks", {})
    for event in events:
        entries = hooks.setdefault(event, [])
        entries.append({"hooks": [fragment(event)]})
    return settings


def install(path):
    settings, existed = load(path)
    missing = missing_events(settings)
    if not missing:
        print(f"already registered in {path}; nothing to do")
        return 0

    merged = merge(settings, missing)
    path.parent.mkdir(parents=True, exist_ok=True)

    if existed:
        backup = path.with_suffix(path.suffix + ".paynani.bak")
        shutil.copy2(path, backup)
        print(f"backed up {path} to {backup}")

    # Write beside and rename, so an interrupted write cannot leave a truncated
    # settings file behind. Claude Code reads this at every session start; a
    # half-written one breaks every session, not just ours.
    tmp = path.with_suffix(path.suffix + ".paynani.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    print(f"registered the {' and '.join(missing)} hook(s) in {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print", action="store_true", dest="show")
    group.add_argument("--check", action="store_true")
    group.add_argument("--install", action="store_true")
    parser.add_argument("--settings", default=None,
                        help="settings file to act on (default: ~/.claude/settings.json)")
    args = parser.parse_args()
    path = pathlib.Path(args.settings).expanduser() if args.settings else SETTINGS

    if args.show:
        print(json.dumps({"hooks": {event: [{"hooks": [fragment(event)]}] for event in EVENTS}}, indent=2))
        return 0
    if args.check:
        settings, _ = load(path)
        missing = missing_events(settings)
        if not missing:
            print(f"registered in {path}: {' and '.join(EVENTS)}")
            return 0
        print(f"NOT registered in {path}: {' and '.join(missing)}; run: {ROOT}/scripts/claude_hook.py --install")
        return 1
    return install(path)


if __name__ == "__main__":
    sys.exit(main())
