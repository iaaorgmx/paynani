#!/usr/bin/env python3
"""Small, dependency-free diagnostics shared by the portable test scripts.

The suite runs on Linux and on the Python and Bash shipped by macOS. When a
platform assertion fails, the useful question is not only *what* differed but
which runtime exposed it. Keep this module Python 3.9 compatible so the
diagnostic itself cannot fail on the oldest supported macOS host.
"""

import argparse
import socket
import subprocess
import sys


TCP_NAMES = (
    "TCP_KEEPIDLE",
    "TCP_KEEPALIVE",
    "TCP_KEEPINTVL",
    "TCP_KEEPCNT",
)


def _first_line(command):
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "unavailable ({})".format(exc)

    output = (completed.stdout or completed.stderr or "").splitlines()
    if output:
        return output[0].strip()
    return "exited {} without version output".format(completed.returncode)


def diagnostic_lines(mime_observed=None, mime_expected=None):
    """Return stable one-line diagnostics suitable for CI failure output."""
    symbols = []
    for name in TCP_NAMES:
        value = getattr(socket, name, None)
        symbols.append("{}={}".format(name, value if value is not None else "missing"))

    return [
        "diagnostic: python={}".format(sys.version.replace("\n", " ")),
        "diagnostic: bash={}".format(_first_line(["bash", "--version"])),
        "diagnostic: file={}".format(_first_line(["file", "--version"])),
        "diagnostic: tcp_symbols={}".format(", ".join(symbols)),
        "diagnostic: mime_expected={}".format(mime_expected or "not observed"),
        "diagnostic: mime_observed={}".format(mime_observed or "not observed"),
    ]


def print_diagnostics(mime_observed=None, mime_expected=None, stream=None):
    stream = stream or sys.stderr
    for line in diagnostic_lines(mime_observed, mime_expected):
        print(line, file=stream)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mime-observed")
    parser.add_argument("--mime-expected")
    args = parser.parse_args()
    print_diagnostics(args.mime_observed, args.mime_expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
