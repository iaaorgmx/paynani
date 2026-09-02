#!/usr/bin/env python3
"""
The log rotator writes where the rest of the install reads.

This exists because of a specific silent failure. `rotate_logs.py` used to hard
-code `~/.local/state/paynani` and was the only consumer with no way to
redirect it. Once the units started writing somewhere else, `main()` recreated
that directory empty, globbed no logs, printed nothing and returned 0 — so the
weekly timer reported success forever while the real logs grew without bound.

Both halves are asserted here. The second one — that the old path is never
created — is the one that fails when the resolver is bypassed, and it is the
half a test written from the happy path would leave out.

    scripts/test_rotate_logs.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

passed = 0
failed = 0


def check(description, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"ok   {description}")
        passed += 1
    else:
        print(f"FAIL {description}\n       expected: {expected}\n       actual:   {actual}")
        failed += 1


def run(home, state):
    environ = dict(os.environ, HOME=str(home), PAYNANI_STATE=str(state))
    return subprocess.run(
        [sys.executable, str(ROOT / "harness" / "rotate_logs.py")],
        capture_output=True, text=True, env=environ,
    )


with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    state = Path(tmp) / "install" / "state"
    state.mkdir(parents=True)
    home.mkdir()

    log = state / "mail.log"
    log.write_text("a message that has been sitting here a while\n")

    # Old enough to rotate: the rotator keeps a per-file timestamp and will not
    # touch anything it has seen within the last week.
    result = run(home, state)

    rotated = state / "mail.log.1"

    check("rotator exits cleanly", 0, result.returncode)
    check("the log was rotated where the install actually is", True, rotated.exists())
    # Read defensively. When this test fails it is usually because the rotator
    # went somewhere else entirely, and a traceback here would hide the
    # assertion below that says where it actually went.
    check("the rotated copy kept the content", True,
          rotated.exists()
          and "a message that has been sitting here a while" in rotated.read_text())
    check("the live log was truncated, not unlinked", True, log.exists() and log.stat().st_size == 0)
    check("it said what it did", True, "rotated" in result.stdout)

    # The assertion that catches a bypassed resolver. A rotator still pointed at
    # the old hard-coded path would create this and report success.
    check("no state directory is created outside the clone",
          False, (home / ".local" / "state" / "paynani").exists())

    # A second run inside the interval is a no-op, and still must not wander.
    result = run(home, state)
    check("a second run within the interval rotates nothing", "", result.stdout.strip())
    check("and still creates nothing outside the clone",
          False, (home / ".local" / "state" / "paynani").exists())
    check("and does not stack up rotations", False, (state / "mail.log.2").exists())

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
