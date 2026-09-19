#!/usr/bin/env python3
"""The service Python floor fails before a long-running process starts."""

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import python_floor

passed = failed = 0


def check(desc, condition):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}")
        failed += 1


buf = StringIO()
try:
    with redirect_stderr(buf):
        python_floor.enforce((3, 9, 6), "/old/python3")
    refused = False
except SystemExit as exc:
    refused = exc.code == 1

message = buf.getvalue()
check("Python below 3.10 is refused", refused)
check("the refusal names the version and executable",
      "this is 3.9.6 at\n/old/python3" in message)
check("the refusal points at INSTALL.md", "INSTALL.md explains the floor" in message)

facts = python_floor.enforce((3, 10, 0), "/new/python3")
check("Python 3.10 is accepted", facts["supported"] is True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
