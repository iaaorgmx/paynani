#!/usr/bin/env python3
"""Print one value from a KEY=VALUE env file for command-based secret readers."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: env_secret.py ENV_FILE KEY", file=sys.stderr)
        return 2
    path = Path(argv[0]).expanduser()
    key = argv[1]
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 1
    prefix = key + "="
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line.split("=", 1)[1].strip().strip('"').strip("'")
        print(value)
        return 0
    print(f"{key} not found in {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
