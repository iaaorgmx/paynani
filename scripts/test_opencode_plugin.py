#!/usr/bin/env python3
"""
Runs the OpenCode plugin's own tests, harness/opencode/paynani.test.mjs.

The plugin is JavaScript because OpenCode loads plugins with Bun. Its tests use
`node:test`, which both Node and Bun understand, so this runs them with whichever
is installed. GitHub's Linux and macOS runners ship Node.

With neither installed the suite is reported as skipped, loudly, rather than as
passed: a green run that verified nothing is the failure the CI workflow's own
"refuse to run a suite that would silently skip checks" step exists to catch.
"""

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "harness" / "opencode" / "paynani.test.mjs"


def command():
    node = shutil.which("node")
    if node:
        return [node, "--test", str(TESTS)]
    bun = shutil.which("bun")
    if bun:
        return [bun, "test", str(TESTS)]
    return None


def main():
    cmd = command()
    if cmd is None:
        print("\n0 passed, 0 failed, 1 suite skipped (neither node nor bun is installed)")
        return 0
    run = subprocess.run(cmd, cwd=TESTS.parent, capture_output=True, text=True, timeout=120)
    sys.stdout.write(run.stdout)
    sys.stderr.write(run.stderr)
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
