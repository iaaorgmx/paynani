#!/usr/bin/env python3
"""
Register (or show, check, remove) the paynani hooks of Antigravity CLI (`agy`).

`~/.gemini/config/hooks.json` belongs to the person using `agy` and may hold
hooks of their own. Its top level maps a hook name of the user's choice to the
events it handles, so paynani keeps everything under one key of its own,
`paynani`, and never reads or writes the others (PRD #749, FR-3):

  {"paynani": {"SessionStart":  [{"type": "command", "command": "...", "timeout": 10}],
               "PreInvocation": [{"type": "command", "command": "...", "timeout": 10}]}}

Both events run `harness/session_start.py --antigravity`: SessionStart for a new
conversation, PreInvocation (which the hook acts on only when invocationNum is
0) for a resumed one, which SessionStart does not see.

Like claude_hook.py, this file is not a managed artifact: it is edited on
request, an existing file is backed up first, and the write is atomic. A file
that is not valid JSON, or whose top level is not an object, is refused, never
repaired.

Usage:
  antigravity_hook.py --print       show the block, change nothing
  antigravity_hook.py --check       exit 0 when the block is there and points to this clone
  antigravity_hook.py --install     write the block (showing it first), backing up first
  antigravity_hook.py --uninstall   remove the block, backing up first
"""

import argparse
import json
import os
import pathlib
import shlex
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = pathlib.Path.home() / ".gemini" / "config" / "hooks.json"
HOOK = ROOT / "harness" / "session_start.py"
KEY = "paynani"
EVENTS = ("SessionStart", "PreInvocation")
TIMEOUT = 10


def command():
    # agy runs each hook with `sh -c`, so a clone path with spaces must be quoted.
    return f"python3 {shlex.quote(str(HOOK))} --antigravity"


def handler():
    return {"type": "command", "command": command(), "timeout": TIMEOUT}


def block():
    return {event: [handler()] for event in EVENTS}


def load(path):
    """The parsed file and whether it existed with content. Refuses what it cannot parse."""
    if not path.is_file():
        return {}, False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}")
    if not text.strip():
        return {}, False
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"{path} is not valid JSON ({exc}).\n"
            "Fix it by hand and run this again; nothing has been changed."
        )
    if not isinstance(data, dict):
        raise SystemExit(
            f"{path} does not hold a JSON object at the top level.\n"
            "Fix it by hand and run this again; nothing has been changed."
        )
    return data, True


def state(settings):
    """'registered', 'missing', 'disabled', 'other-clone' or 'different' (stale or edited by hand)."""
    mine = settings.get(KEY)
    if mine is None:
        return "missing"
    if mine == block():
        return "registered"
    if not isinstance(mine, dict):
        return "different"
    if mine.get("enabled") is False:
        return "disabled"
    commands = [h.get("command", "") for event in EVENTS for h in (mine.get(event) or []) if isinstance(h, dict)]
    if commands and all("session_start.py" in c and c != command() for c in commands):
        return "other-clone"
    return "different"


def already_registered(settings):
    return state(settings) == "registered"


def write(path, data, existed):
    path.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        backup = path.with_suffix(path.suffix + ".paynani.bak")
        shutil.copy2(path, backup)
        print(f"backed up {path} to {backup}")
    tmp = path.with_suffix(path.suffix + ".paynani.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    if existed:
        # The file is the user's and may hold commands of their own: keep its mode
        # (a 0600 file must not come back 0644 from the umask of the new one).
        shutil.copymode(path, tmp)
    tmp.replace(path)


def install(path):
    settings, existed = load(path)
    if already_registered(settings):
        print(f"already registered in {path}; nothing to do")
        return 0
    print(f"writing this under the key {KEY!r} of {path} (other keys are left as they are):")
    print(json.dumps({KEY: block()}, indent=2))
    settings[KEY] = block()
    write(path, settings, existed)
    print(f"registered the paynani Antigravity hooks ({' and '.join(EVENTS)}) in {path}")
    return 0


def uninstall(path):
    settings, existed = load(path)
    if KEY not in settings:
        print(f"no {KEY!r} key in {path}; nothing to do")
        return 0
    del settings[KEY]
    write(path, settings, existed)
    print(f"removed the {KEY!r} key from {path}")
    return 0


def check(path):
    settings, _ = load(path)
    found = state(settings)
    if found == "registered":
        print(f"registered in {path}: {' and '.join(EVENTS)} run {command()}")
        return 0
    fix = f"run: {ROOT}/scripts/antigravity_hook.py --install"
    reasons = {
        "missing": f"no {KEY!r} key",
        "disabled": f"the {KEY!r} key is disabled (\"enabled\": false)",
        "other-clone": f"the {KEY!r} key points to another clone, not {ROOT}",
        "different": f"the {KEY!r} key is not what this clone writes",
    }
    print(f"NOT registered in {path}: {reasons[found]}; {fix}")
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print", action="store_true", dest="show")
    group.add_argument("--check", action="store_true")
    group.add_argument("--install", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    parser.add_argument("--settings", default=None,
                        help="hooks file to act on (default: ~/.gemini/config/hooks.json)")
    args = parser.parse_args()
    path = pathlib.Path(args.settings).expanduser() if args.settings else SETTINGS

    if args.show:
        print(json.dumps({KEY: block()}, indent=2))
        return 0
    if args.check:
        return check(path)
    if args.uninstall:
        return uninstall(path)
    return install(path)


if __name__ == "__main__":
    sys.exit(main())
