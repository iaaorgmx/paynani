#!/usr/bin/env python3
"""The failure diagnostic must remain useful on every supported platform."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from failure_diagnostics import diagnostic_lines


def main():
    lines = diagnostic_lines("application/octet-stream", "text/plain")
    expected = (
        "diagnostic: python=",
        "diagnostic: bash=",
        "diagnostic: file=",
        "diagnostic: tcp_symbols=",
        "diagnostic: tcp_resolved=",
        "diagnostic: mime_expected=text/plain",
        "diagnostic: mime_observed=application/octet-stream",
    )
    assert len(lines) == len(expected), lines
    for line, prefix in zip(lines, expected):
        assert line.startswith(prefix), (line, prefix)

    tcp = next(line for line in lines if line.startswith("diagnostic: tcp_symbols="))
    for name in ("TCP_KEEPIDLE", "TCP_KEEPALIVE", "TCP_KEEPINTVL", "TCP_KEEPCNT"):
        assert "{}=".format(name) in tcp, tcp

    resolved = next(line for line in lines if line.startswith("diagnostic: tcp_resolved="))
    for name in ("TCP_KEEPIDLE", "TCP_KEEPALIVE"):
        assert "{}=".format(name) in resolved, resolved

    print("test diagnostics passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
