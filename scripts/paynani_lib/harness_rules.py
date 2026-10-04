"""
Permission rules for the agent's harness, scoped to paynani's own commands
(BOOT-4, #344; PRD in #335, step 12).

The sudo installer (`bootstrap.sh` -> `bootstrap_user.py`) calls `plan()` to
show what it would add and `apply()` to add it. The rules cover exactly three
scripts of this clone, by absolute path, and nothing else: the agent can mark
events, send to the roster and arm the mail watch without asking, and every
other command stays under the harness's own policy. Security profiles
(OpenClaw `tools.profile`, Claude Code's permission mode) are never touched:
that is a decision for the human, not for an installer (#335, P9).

- Claude Code: `permissions.allow` in ~/.claude/settings.json, every other key
  kept as it was.
- OpenClaw: `openclaw approvals allowlist add --agent main <path>`, the public
  CLI. The allowlist lives in OpenClaw's SQLite store, which is not ours to
  edit (confirmed by Ximena in #344).
- Hermes, Codex, OpenCode: no rules are written; `plan()` says what to add by
  hand and `apply()` prints the same.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RUNTIMES = ("claudecode", "openclaw", "hermes", "codex", "opencode")
OPENCLAW_AGENT = "main"


def scripts(clone) -> list[str]:
    """The three commands the rules cover, by absolute path."""
    root = Path(clone).resolve()
    return [str(root / "scripts" / "paynani"),
            str(root / "scripts" / "send.sh"),
            str(root / "harness" / "session_watch.sh")]


def claude_rules(clone) -> list[str]:
    paynani, send, watch = scripts(clone)
    return [f"Bash({paynani} *)", f"Bash({send} *)", f"Bash(bash {watch} *)"]


def claude_settings(home=None) -> Path:
    return Path(home or Path.home()) / ".claude" / "settings.json"


def _read_settings(path: Path) -> dict:
    """The settings as a dict; {} if the file does not exist. Raises ValueError if it is not a JSON object."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    allow = data.get("permissions", {}).get("allow", []) if isinstance(data.get("permissions", {}), dict) else None
    if allow is None or not isinstance(allow, list):
        raise ValueError(f"{path}: permissions.allow is not a list")
    return data


def _missing_claude(clone, home=None) -> list[str]:
    allow = _read_settings(claude_settings(home)).get("permissions", {}).get("allow", [])
    return [r for r in claude_rules(clone) if r not in allow]


def _indent_of(path: Path) -> int:
    """The indentation the file already uses, so a dotfiles diff shows only our lines."""
    try:
        m = re.search(r'\n( +)"', path.read_text(encoding="utf-8"))
    except OSError:
        return 2
    return len(m.group(1)) if m else 2


def _write_json(path: Path, data: dict) -> None:
    """
    Replace the file whole, keeping its mode and indentation; a reader never
    sees half a file. A symlinked settings.json (dotfiles managers) is written
    at its target, and the link stays a link: os.replace on the link itself
    would swap it for a plain file and leave the target without the rules.
    """
    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    indent = _indent_of(path) if path.exists() else 2
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=indent, ensure_ascii=False)
            fh.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _openclaw_allowed(binary: str, runner) -> set[str] | None:
    """
    The exact patterns in agent main's allowlist, or None if they could not be read.

    `openclaw approvals get` takes no --agent (OpenClaw 2026.9.2); its --json view
    is the whole config, redacted, with entries under file.agents.<id>.allowlist,
    each {"pattern": ...} or, from older files, a plain string (Ximena, #352).
    Matching is on the exact path: a substring test would read
    scripts/paynani_old as scripts/paynani already allowed.
    """
    try:
        done = runner([binary, "approvals", "get", "--json"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        data = json.loads(done.stdout)
        entries = (data.get("file") or {}).get("agents", {}).get(OPENCLAW_AGENT, {}).get("allowlist", [])
    except (ValueError, AttributeError):
        return None
    if not isinstance(entries, list):
        return None
    out = set()
    for item in entries:
        pattern = item.get("pattern") if isinstance(item, dict) else item
        if isinstance(pattern, str):
            out.add(pattern)
    return out


def manual_text(runtime, clone) -> str:
    paths = "\n".join(f"  {p}" for p in scripts(clone))
    return (f"harness rules: {runtime} is not configured automatically. To let the agent run "
            f"paynani without asking, allow these three commands in its harness, and nothing more:\n{paths}")


def plan(runtime, clone, home=None, which=shutil.which, runner=subprocess.run) -> list[str]:
    """What apply() would do, one line per action. Empty when there is nothing to add."""
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime: {runtime}")
    if runtime == "claudecode":
        return [f"add to {claude_settings(home)} permissions.allow: {r}" for r in _missing_claude(clone, home)]
    if runtime == "openclaw":
        binary = which("openclaw")
        if not binary:
            return [manual_text(runtime, clone)]
        current = _openclaw_allowed(binary, runner)
        if current is None:
            return [manual_text(runtime, clone)]
        return [f"openclaw approvals allowlist add --agent {OPENCLAW_AGENT} {p}"
                for p in scripts(clone) if p not in current]
    return [manual_text(runtime, clone)]


def apply(runtime, clone, assume_yes=False, home=None, confirm=input, out=print,
          which=shutil.which, runner=subprocess.run) -> tuple[bool, str]:
    """
    Show the plan, ask (unless assume_yes), then add the rules.

    Returns (ok, detail). A runtime without automatic rules returns ok after
    printing what to add by hand: that is the designed outcome, not a failure.
    """
    try:
        steps = plan(runtime, clone, home=home, which=which, runner=runner)
    except (ValueError, OSError) as exc:
        return False, f"harness rules: {exc}"
    if not steps:
        return True, "harness rules: already in place"
    if runtime not in ("claudecode", "openclaw") or (runtime == "openclaw" and steps[0].startswith("harness rules:")):
        out(steps[0])
        return True, "harness rules: printed for manual setup"
    out("harness rules: paynani needs these, and only these:")
    for line in steps:
        out(f"  {line}")
    if not assume_yes:
        try:
            answer = confirm("Add them? [y/N] ").strip().lower()
        except EOFError:
            # No terminal under sudo -u: a "no" nobody said would hide that the
            # rules were not written.
            return False, "harness rules: no terminal to confirm; run again with --yes to add them"
        if answer not in ("y", "yes", "s", "si", "sí"):
            return True, "harness rules: skipped by the owner"
    if runtime == "claudecode":
        path = claude_settings(home)
        try:
            data = _read_settings(path)
        except (ValueError, OSError) as exc:
            return False, f"harness rules: {exc}"
        allow = data.setdefault("permissions", {}).setdefault("allow", [])
        allow.extend(r for r in claude_rules(clone) if r not in allow)
        _write_json(path, data)
        return True, f"harness rules: {len(steps)} added to {path}"
    binary = which("openclaw")
    for p in scripts(clone):
        if not any(line.endswith(p) for line in steps):
            continue
        done = runner([binary, "approvals", "allowlist", "add", "--agent", OPENCLAW_AGENT, p],
                      capture_output=True, text=True, timeout=30)
        if done.returncode != 0:
            return False, f"harness rules: openclaw refused {p}: {(done.stderr or done.stdout).strip()}"
    return True, f"harness rules: {len(steps)} added to the OpenClaw allowlist of agent {OPENCLAW_AGENT}"
