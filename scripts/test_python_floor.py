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


import tempfile  # noqa: E402
import paths  # noqa: E402

NO_RECORD = {"PAYNANI_PYTHON": ""}
_real_runtime_env = paths.runtime_env
_tmp = tempfile.TemporaryDirectory()
paths.runtime_env = lambda environ=None, home=None: Path(_tmp.name) / "runtime.env"

buf = StringIO()
try:
    with redirect_stderr(buf):
        python_floor.enforce((3, 9, 6), "/old/python3", environ=dict(NO_RECORD))
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

# --- #777: re-run with the interpreter the install recorded ----------------------
new_python = sys.executable  # a real, executable file


def run_old(environ, executable="/usr/bin/python3-old"):
    calls, err = [], StringIO()

    def fake_execv(path, argv):
        calls.append((path, argv))
        raise SystemExit(0)  # the real execv never returns

    try:
        with redirect_stderr(err):
            python_floor.enforce((3, 9, 6), executable, execv=fake_execv, environ=environ)
        code = None
    except SystemExit as exc:
        code = exc.code
    return calls, code, err.getvalue()


env = {"PAYNANI_PYTHON": new_python}
calls, code, _ = run_old(env)
check("with $PAYNANI_PYTHON, an old Python re-runs the command with it",
      len(calls) == 1 and calls[0][0] == new_python and calls[0][1] == [new_python] + sys.argv)
check("and marks the environment, so the new process never loops", env.get(python_floor.REEXEC_MARK) == "1")

calls, code, message = run_old({"PAYNANI_PYTHON": new_python, python_floor.REEXEC_MARK: "1"})
check("already re-run once: refuses instead of looping", (calls, code) == ([], 1))

calls, code, message = run_old({"PAYNANI_PYTHON": "/nowhere/python3.13"})
check("a recorded Python that is gone: refuses, names it, and says to re-run the installer",
      calls == [] and code == 1
      and "The install recorded /nowhere/python3.13, but it is not an executable file; re-run the installer" in message)

calls, code, message = run_old({"PAYNANI_PYTHON": new_python, python_floor.REEXEC_MARK: "1"})
check("a usable recorded Python: the refusal says to run the command with it",
      f"The install recorded {new_python}; run the command with it." in message)

calls, code, _ = run_old({"PAYNANI_PYTHON": new_python}, executable=new_python)
check("the recorded one is this one: refuses (no pointless re-run)", (calls, code) == ([], 1))

(Path(_tmp.name) / "runtime.env").write_text(
    f'PAYNANI_RUNTIME="openclaw"\nPAYNANI_PYTHON="{new_python}"\nPAYNANI_SUPERVISOR="launchd"\n', encoding="utf-8")
calls, code, _ = run_old(dict(NO_RECORD))
check("without the variable, runtime.env's PAYNANI_PYTHON is used", len(calls) == 1 and calls[0][0] == new_python)
check("installed_python reads it", python_floor.installed_python(dict(NO_RECORD)) == new_python)
(Path(_tmp.name) / "runtime.env").unlink()
check("no variable and no runtime.env: nothing recorded", python_floor.installed_python(dict(NO_RECORD)) is None)

calls = []
facts = python_floor.enforce((3, 12, 0), "/x", execv=lambda *a: calls.append(a), environ={"PAYNANI_PYTHON": new_python})
check("a supported Python never re-runs", facts["supported"] and calls == [])

env = {"PAYNANI_PYTHON": new_python, python_floor.REEXEC_MARK: "1"}
python_floor.enforce((3, 13, 0), "/x", environ=env)
check("the re-run process drops the mark, so its own children can re-run (Iris, #778)",
      python_floor.REEXEC_MARK not in env)

import ast  # noqa: E402
for rel in ("harness/python_floor.py", "harness/paths.py"):
    try:
        ast.parse((ROOT / rel).read_text(encoding="utf-8"), feature_version=(3, 9))
        ok = True
    except SyntaxError:
        ok = False
    check(f"{rel} still parses as Python 3.9 (it runs exactly then)", ok)
paths.runtime_env = _real_runtime_env

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
