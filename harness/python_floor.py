"""Python version floor shared by long-running paynani services."""

# This file must keep parsing under Python 3.9: it is what tells an old host why
# it cannot start. An `X | None` annotation here turns that message into a
# SyntaxError.

from __future__ import annotations

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


def enforce(version_info=None, executable=None):
    py = facts(version_info, executable)
    if py["supported"]:
        return py
    print(refusal(py), file=sys.stderr, flush=True)
    raise SystemExit(1)
