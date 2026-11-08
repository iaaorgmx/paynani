#!/usr/bin/env python3
"""
Antigravity CLI's mail credentials (#749 FR-4, T5).

`agy` keeps its files under ~/.gemini, which Gemini CLI shares, so its harness
root is ~/.gemini/antigravity-cli and the credentials are
~/.gemini/antigravity-cli/workspace/.env. scripts/test_paths.sh pins that the
shell and Python copies agree; this pins what the Python one answers.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import paths  # noqa: E402

passed = failed = 0


def check(desc, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {desc}")
    else:
        failed += 1
        print(f"FAIL {desc}\n     expected {expected!r}\n     got      {actual!r}")


def write_env(home: Path, relative: str) -> Path:
    path = home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("PAYNANI_EMAIL=agent@example.com\n")
    os.chmod(path, 0o600)
    return path


check("the root is listed, two levels down", True, "~/.gemini/antigravity-cli" in paths.HARNESS_ROOTS)
check("~/.gemini alone is not a root", False, "~/.gemini" in paths.HARNESS_ROOTS)

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    env = write_env(home, ".gemini/antigravity-cli/workspace/.env")
    check("its workspace/.env is found", [env], paths.harness_env_files(home))

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    write_env(home, ".gemini/workspace/.env")
    write_env(home, ".gemini/antigravity-cli/.env")
    check("~/.gemini/workspace/.env and antigravity-cli/.env are not credentials", [],
          paths.harness_env_files(home))

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    claude = write_env(home, ".claude/workspace/.env")
    agy = write_env(home, ".gemini/antigravity-cli/workspace/.env")
    check("with Claude Code too, both are seen (and so neither is adopted)", [claude, agy],
          paths.harness_env_files(home))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
