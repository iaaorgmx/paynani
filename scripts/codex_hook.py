#!/usr/bin/env python3
"""
Register (or show) the paynani SessionStart hook in Codex.

`hooks.json` belongs to the person using Codex and may already contain unrelated
automation. This script edits it only when asked, by merge rather than replace,
and backs it up before changing an existing file.

Usage:
  codex_hook.py --print     show the fragment, change nothing
  codex_hook.py --check     report whether it is already registered
  codex_hook.py --install   merge it in, backing up first
"""

import argparse
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = pathlib.Path(os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex")) / "hooks.json"
HOOK = ROOT / "harness" / "session_start.py"
EVENT = "SessionStart"
MATCHER = "startup|resume|clear|compact"
TIMEOUT = 15
ADDITIONAL_CONTEXT_LIMIT = 5000


def command():
    return f"python3 {HOOK}"


def fragment():
    return {
        "type": "command",
        "command": command(),
        "timeout": TIMEOUT,
        "statusMessage": "Checking paynani",
        "additionalContextLimit": ADDITIONAL_CONTEXT_LIMIT,
    }


def load(path):
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
    hooks = settings.setdefault("hooks", {})
    entries = hooks.setdefault(EVENT, [])
    entries.append({"matcher": MATCHER, "hooks": [fragment()]})
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
                        help="hooks file to act on (default: $CODEX_HOME/hooks.json or ~/.codex/hooks.json)")
    args = parser.parse_args()
    path = pathlib.Path(args.settings).expanduser() if args.settings else SETTINGS

    if args.show:
        print(json.dumps({"hooks": {EVENT: [{"matcher": MATCHER, "hooks": [fragment()]}]}}, indent=2))
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
