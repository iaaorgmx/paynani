"""
`paynani config` and its two children -- see issue #232 (part 2 of #230).

`config` on its own is read-only and always exits 0: it answers "what do I
have set", never "is it healthy" (that question belongs to `paynani doctor`).
`config web` reuses the exact server `setup`/`onboard` already runs -- it
prefills every field but the password from whatever is on disk (server.py's
_render()), so the same form works as an editor, not only a first-run wizard.
`config edit` is the one command here a human runs, never an agent: it opens
.env directly in $EDITOR, which is the whole file, credentials and all --
AGENTS.md carries that rule, this module only enforces the mechanics around
it (no $EDITOR, no tty, post-edit validation, the mode bit).
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import envfile, onboard, validate

PASSWORD_KEY = "AGENT_EMAIL_PASSWORD"
# The one ENV_FIELDS key validate() never requires: send.sh falls back
# without it. Absent, it prints "(not set)" and is not called missing.
OPTIONAL_IN_ENV = {"AGENT_EMAIL_FROM_NAME"}


def _fingerprint(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "absent"


def _mode_is_600(path: Path) -> bool:
    try:
        return (path.stat().st_mode & 0o777) == 0o600
    except OSError:
        return False


def run_print(args) -> int:
    stored = envfile.read_env()
    path = envfile.env_path()

    print(f"Configuration from {path}")
    print()
    missing = []
    for key in envfile.ENV_FIELDS:
        present = bool(stored.get(key))
        if key == PASSWORD_KEY:
            value = "(set, not shown)" if present else "(not set)"
        else:
            value = stored.get(key, "") if present else "(not set)"
        line = f"  {key:<40} {value}"
        if not present and key not in OPTIONAL_IN_ENV:
            line += "   MISSING"
            missing.append(key)
        print(line)

    for key in envfile.OPTIONAL_ENV_FIELDS:
        if stored.get(key):
            print(f"  {key:<40} {stored[key]}")

    # Only paynani's own keys are ever read above -- a foreign key's value
    # never reaches a variable this function prints, by construction, not by
    # filtering it back out after the fact.
    other = sorted(k for k in stored if k not in envfile.WRITABLE_ENV_FIELDS)
    print()
    if other:
        noun = "key" if len(other) == 1 else "keys"
        verb = "is" if len(other) == 1 else "are"
        print(f"  {len(other)} other {noun} in this file {verb} not paynani's and {verb} not shown.")
    if missing:
        print()
        print("Missing: " + ", ".join(missing))

    print()
    print("Edit in a browser:  paynani config web")
    print("Edit in $EDITOR:    paynani config edit")
    return 0


def run_web(args) -> int:
    return onboard.run(port=args.port, mode="config_web")


def run_edit(args) -> int:
    editor = os.environ.get("EDITOR", "")
    if not editor:
        print("EDITOR is not set. Refusing to guess an editor to open .env in.", file=sys.stderr)
        print("Set EDITOR and try again, e.g.: EDITOR=nano paynani config edit", file=sys.stderr)
        return 64

    if not sys.stdin.isatty():
        # An unattended process (a script, a scheduled job) that reaches this
        # line would otherwise launch an interactive editor with nothing to
        # drive it and nothing watching it hang forever.
        print("Standard input is not a terminal. Refusing to launch an interactive", file=sys.stderr)
        print("editor from an unattended process -- it would hang forever.", file=sys.stderr)
        return 64

    path = envfile.env_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Could not prepare {path.parent}: {exc}", file=sys.stderr)
        return 1
    if not path.exists():
        path.touch()
    try:
        path.chmod(0o600)
    except OSError:
        pass

    before = _fingerprint(path)
    # shlex.split, not editor.split(): EDITOR="code --wait" is a real, common
    # shape, and treating it as one binary literally named "code --wait"
    # would fail to launch anything.
    command = shlex.split(editor) + [str(path)]
    try:
        result = subprocess.run(command)
    except OSError as exc:
        print(f"Could not run {editor!r}: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"{editor!r} exited with status {result.returncode}; .env left as it was.",
              file=sys.stderr)
        return result.returncode

    try:
        path.chmod(0o600)
    except OSError:
        pass
    mode_ok = _mode_is_600(path)

    stored = envfile.read_env()
    errors = validate.validate_env(stored)
    if errors:
        print(f"{path} was saved, but has problems:", file=sys.stderr)
        for key, message in errors.items():
            print(f"  {key}: {message}", file=sys.stderr)
        return 1

    if not mode_ok:
        print(f"Warning: could not confirm {path} is mode 600.", file=sys.stderr)

    if _fingerprint(path) == before:
        print(f"{path} was not changed.")
    else:
        print(f"{path} updated.")
    return 0
