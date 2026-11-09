"""Python version floor shared by long-running paynani services."""

# This file must keep parsing under Python 3.9: it is what tells an old host why
# it cannot start. An `X | None` annotation here turns that message into a
# SyntaxError.

from __future__ import annotations

import os
import sys

MIN_PYTHON = (3, 10)
MINIMUM = "3.10"


def _version_text(version_info=None):
    version_info = sys.version_info if version_info is None else version_info
    return ".".join(str(part) for part in version_info[:3])


def facts(version_info=None, executable=None):
    version_info = sys.version_info if version_info is None else version_info
    executable = sys.executable if executable is None else executable
    return {
        "found": _version_text(version_info),
        "executable": executable,
        "minimum": MINIMUM,
        "supported": tuple(version_info[:2]) >= MIN_PYTHON,
    }


def refusal(facts):
    return (
        f"paynani needs Python {facts['minimum']} or newer; this is {facts['found']} at\n"
        f"{facts['executable']}\n"
        "INSTALL.md explains the floor. Point the service at a newer interpreter."
    )


REEXEC_MARK = "PAYNANI_PYTHON_REEXEC"


def installed_python(environ=None):
    """
    The interpreter the install recorded (#777): $PAYNANI_PYTHON, else the
    PAYNANI_PYTHON line of runtime.env. None when there is none. Kept 3.9-safe:
    it runs exactly when the interpreter is too old.
    """
    environ = os.environ if environ is None else environ
    value = environ.get("PAYNANI_PYTHON", "").strip()
    if value:
        return value
    try:
        import paths
        text = paths.runtime_env(environ).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 -- no record is an answer, not an error
        return None
    for line in text.splitlines():
        name, sep, raw = line.partition("=")
        if sep and name.strip() == "PAYNANI_PYTHON":
            return raw.strip().strip('"').strip("'") or None
    return None


def reexec_target(py, environ=None):
    """The interpreter to re-run this command with, or None (no record, the same one, gone, or tried)."""
    environ = os.environ if environ is None else environ
    if environ.get(REEXEC_MARK):
        return None  # already re-run once: never loop
    target = installed_python(environ)
    if not target or not os.path.isfile(target) or not os.access(target, os.X_OK):
        return None
    if os.path.realpath(target) == os.path.realpath(py["executable"] or ""):
        return None
    return target


def enforce(version_info=None, executable=None, execv=None, environ=None):
    py = facts(version_info, executable)
    if py["supported"]:
        return py
    environ = os.environ if environ is None else environ
    target = reexec_target(py, environ)
    if target:
        # An agent's shell found an older python3 than the one the install uses
        # (Apple's 3.9 on macOS, #777): run the same command again with that one.
        environ[REEXEC_MARK] = "1"
        argv = [target] + list(sys.argv)
        (execv or os.execv)(target, argv)
    message = refusal(py)
    recorded = installed_python(environ)
    if recorded:
        message += f"\nThe install recorded {recorded}; run the command with it."
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(1)
