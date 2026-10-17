#!/usr/bin/env python3
"""
`paynani onboard` run with stdout to a pipe must print the form link while it
is still waiting for the form (#396). A harness that runs it in the background
reads a pipe or a file; with Python's block buffering the link only appeared
once the process exited, which is after the form is saved -- too late.

Runs against a temporary state directory and a credentials path that does not
exist, so nothing real is read or written.
"""
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f": {detail}" if detail else ""))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ)
    env["PAYNANI_STATE"] = str(Path(tmp) / "state")
    env["PAYNANI_ENV"] = str(Path(tmp) / "missing" / ".env")
    env.pop("PYTHONUNBUFFERED", None)   # the bug only shows without it
    port = free_port()
    proc = subprocess.Popen(
        [str(ROOT / "scripts" / "paynani"), "onboard", "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=str(ROOT),
    )
    seen = b""
    deadline = time.time() + 15
    try:
        while time.time() < deadline and b"/?t=" not in seen:
            ready, _, _ = select.select([proc.stdout], [], [], 0.5)
            if ready:
                chunk = os.read(proc.stdout.fileno(), 4096)
                if not chunk:
                    break
                seen += chunk
        still_running = proc.poll() is None
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    text = seen.decode("utf-8", "replace")
    check("the link reaches a pipe while onboard is still waiting",
          f"http://127.0.0.1:{port}/?t=" in text and still_running, text[-400:])

print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
