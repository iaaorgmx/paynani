"""
The one per-harness step that makes mail reach the agent's session (#474).

Each runtime but Hermes needs something registered in the harness's own
configuration before a roster message can reach a session:

- Claude Code: the SessionStart and UserPromptSubmit hooks in ~/.claude/settings.json
- Codex: the SessionStart and SessionEnd hooks in $CODEX_HOME/hooks.json
- OpenCode: the paynani plugin in OpenCode's plugin directory
- OpenClaw: the standing rule in ~/.openclaw/workspace/AGENTS.md (#186)

The scripts that write them already exist and stay the only writers
(`scripts/claude_hook.py` and the rest): they merge, back up the file first and
do nothing on a second run. This module only knows which script belongs to
which runtime and reads whether its step is in place, so `bootstrap_user.py`
can register it and `paynani doctor` can refuse to call an install healthy
without it. Those files live outside the agent's workspace and, under Claude
Code's auto mode or Codex's sandbox, are exactly what the agent cannot write,
which is why the sudo installer does it.

Hermes has no such step: its delivery is the webhook route `install.sh` sets up.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"

# runtime -> (script, the option that names the file it writes, what it registers)
STEPS = {
    "claudecode": ("claude_hook.py", "--settings", "the Claude Code session hooks"),
    "codex": ("codex_hook.py", "--settings", "the Codex session hooks"),
    "opencode": ("opencode_plugin.py", "--target", "the paynani OpenCode plugin"),
    "openclaw": ("openclaw_rules.py", "--target", "the paynani standing rule for OpenClaw"),
}


def has_step(runtime: str) -> bool:
    return runtime in STEPS


def _module(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(name)


def target(runtime: str, home: Path | None = None) -> Path:
    """The file the runtime's step writes, resolved now rather than at import time."""
    home = Path(home) if home else Path.home()
    if runtime == "claudecode":
        return home / ".claude" / "settings.json"
    if runtime == "codex":
        codex_home = os.environ.get("CODEX_HOME", "").strip()
        return (Path(codex_home).expanduser() if codex_home else home / ".codex") / "hooks.json"
    if runtime == "opencode":
        explicit = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
        if explicit:
            return Path(explicit).expanduser() / "plugins" / "paynani.js"
        xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
        base = Path(xdg).expanduser() if xdg else home / ".config"
        return base / "opencode" / "plugins" / "paynani.js"
    if runtime == "openclaw":
        return home / ".openclaw" / "workspace" / "AGENTS.md"
    raise ValueError(f"{runtime} has no harness step")


def command(runtime: str, action: str = "--install") -> str:
    script, _, _ = STEPS[runtime]
    return f"python3 {SCRIPTS / script} {action}"


def _read_json(path: Path):
    """The document, {} when the file is missing or empty, None when it cannot be read or parsed."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def state(runtime: str, home: Path | None = None) -> str:
    """
    "present", "absent", "stale" or "unknown"; "none" for a runtime without a step.

    "stale" is a step written for another clone or an older version: on
    OpenClaw the block differs, and on OpenCode the plugin file points elsewhere.
    "unknown" means the file exists and could not be read or parsed; it is never
    taken as present.
    """
    if runtime not in STEPS:
        return "none"
    path = target(runtime, home)
    try:
        if runtime == "claudecode":
            settings = _read_json(path)
            if settings is None:
                return "unknown"
            return "absent" if _module("claude_hook").missing_events(settings) else "present"
        if runtime == "codex":
            settings = _read_json(path)
            if settings is None:
                return "unknown"
            return "present" if _module("codex_hook").already_registered(settings) else "absent"
        if runtime == "opencode":
            plugin = _module("opencode_plugin")
            try:
                current = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return "absent"
            return "present" if current == plugin.content() else "stale"
        return _module("openclaw_rules").state(path)
    except (Exception, SystemExit):
        return "unknown"


def describe(runtime: str) -> str:
    return STEPS[runtime][2]


def show(runtime: str, home: Path | None = None, runner=subprocess.run) -> str:
    """What the script would write (its --print), for the owner to read before saying yes."""
    script, _, _ = STEPS[runtime]
    done = runner([sys.executable, str(SCRIPTS / script), "--print"],
                  capture_output=True, text=True, timeout=30)
    return (done.stdout or "").rstrip()


def install(runtime: str, home: Path | None = None, runner=subprocess.run) -> tuple[bool, str]:
    """Run the runtime's own script with --install against target(); (ok, its output)."""
    script, option, _ = STEPS[runtime]
    path = target(runtime, home)
    done = runner([sys.executable, str(SCRIPTS / script), "--install", option, str(path)],
                  capture_output=True, text=True, timeout=60)
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, output
