#!/usr/bin/env python3
"""
Register (or show) the paynani Codex hooks.

`hooks.json` belongs to the person using Codex and may already contain unrelated
automation. This script edits it only when asked, by merge rather than replace,
and backs it up before changing an existing file.

Usage:
  codex_hook.py --print     show the fragments, change nothing
  codex_hook.py --check     report whether they are already registered
  codex_hook.py --install   merge them in, backing up first
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
START_EVENT = "SessionStart"
END_EVENT = "SessionEnd"
START_MATCHER = "startup|resume|clear|compact"
END_MATCHER = ".*"
START_TIMEOUT = 15
END_TIMEOUT = 3
ADDITIONAL_CONTEXT_LIMIT = 5000


def start_command():
    return f"python3 {HOOK}"


def end_command():
    return f"python3 {HOOK} --session-end"


def start_fragment():
    return {
        "type": "command",
        "command": start_command(),
        "timeout": START_TIMEOUT,
        "statusMessage": "Checking paynani",
        "additionalContextLimit": ADDITIONAL_CONTEXT_LIMIT,
    }


def end_fragment():
    return {
        "type": "command",
        "command": end_command(),
        "timeout": END_TIMEOUT,
        "statusMessage": "Clearing paynani session",
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


def _event_has_fragment(settings, event, matcher, fragment):
    for entry in settings.get("hooks", {}).get(event, []) or []:
        if entry.get("matcher") != matcher:
            continue
        for hook in entry.get("hooks", []) or []:
            if hook == fragment:
                return True
    return False


def already_registered(settings):
    return (_event_has_fragment(settings, START_EVENT, START_MATCHER, start_fragment())
            and _event_has_fragment(settings, END_EVENT, END_MATCHER, end_fragment()))


def _merge_event(hooks, event, matcher, fragment):
    entries = hooks.setdefault(event, [])
    command_text = fragment["command"]
    for entry in entries:
        hook_list = entry.get("hooks", []) or []
        for index, hook in enumerate(hook_list):
            if (hook.get("command") or "") == command_text:
                hook_list[index] = fragment
                if len(hook_list) == 1:
                    entry["matcher"] = matcher
                return
    entries.append({"matcher": matcher, "hooks": [fragment]})


def merge(settings):
    hooks = settings.setdefault("hooks", {})
    if not _event_has_fragment(settings, START_EVENT, START_MATCHER, start_fragment()):
        _merge_event(hooks, START_EVENT, START_MATCHER, start_fragment())
    if not _event_has_fragment(settings, END_EVENT, END_MATCHER, end_fragment()):
        _merge_event(hooks, END_EVENT, END_MATCHER, end_fragment())
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
    print(f"registered the paynani Codex hooks in {path}")
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
        print(json.dumps({"hooks": {
            START_EVENT: [{"matcher": START_MATCHER, "hooks": [start_fragment()]}],
            END_EVENT: [{"matcher": END_MATCHER, "hooks": [end_fragment()]}],
        }}, indent=2))
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
