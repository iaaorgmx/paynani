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

Usage:
  claude_hook.py --print     show the fragment, change nothing
  claude_hook.py --check     report whether it is already registered
  claude_hook.py --install   merge it in, backing up first
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
TIMEOUT = 15


def command():
    return f"python3 {HOOK}"


def fragment():
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


def already_registered(settings):
    for entry in settings.get("hooks", {}).get(EVENT, []) or []:
        for hook in entry.get("hooks", []) or []:
            if str(HOOK) in (hook.get("command") or ""):
                return True
    return False


def merge(settings):
    """
    Add our hook, leaving every other hook exactly where it was.

    Appends to the SessionStart list rather than replacing it: a host may
    already run its own session-start hooks, and Claude Code runs all of them.
    """
    hooks = settings.setdefault("hooks", {})
    entries = hooks.setdefault(EVENT, [])
    entries.append({"hooks": [fragment()]})
    return settings


def install(path):
    settings, existed = load(path)
    if already_registered(settings):
        print(f"already registered in {path}; nothing to do")
        return 0

    merged = merge(settings)
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
    print(f"registered the {EVENT} hook in {path}")
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
        print(json.dumps({"hooks": {EVENT: [{"hooks": [fragment()]}]}}, indent=2))
        return 0
    if args.check:
        settings, _ = load(path)
        if already_registered(settings):
            print(f"registered in {path}")
            return 0
        print(f"NOT registered in {path}")
        return 1
    return install(path)


if __name__ == "__main__":
    sys.exit(main())
