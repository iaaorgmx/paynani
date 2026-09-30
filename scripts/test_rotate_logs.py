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
from datetime import datetime, timedelta, timezone
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


def run(home, state, extra_env=None):
    environ = dict(os.environ, HOME=str(home), PAYNANI_STATE=str(state))
    if extra_env:
        environ.update(extra_env)
    return subprocess.run(
        [sys.executable, str(ROOT / "harness" / "rotate_logs.py")],
        capture_output=True, text=True, env=environ,
    )


def iso(days_ago):
    stamp = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_line(record):
    import json

    return (json.dumps(record, separators=(",", ":")) + "\n").encode()


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

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    state = Path(tmp) / "install" / "state"
    state.mkdir(parents=True)
    home.mkdir()

    lifecycle = state / "lifecycle.jsonl"
    lifecycle.write_bytes(b"".join([
        json_line({
            "event_id": "imap:ventas:INBOX:1:1",
            "state": "observed",
            "at": iso(120),
            "envelope": {"account_id": "ventas", "observed_at": iso(120)},
        }),
        json_line({"event_id": "imap:ventas:INBOX:1:1", "state": "dispatched", "at": iso(119)}),
        json_line({
            "event_id": "imap:soporte:INBOX:1:2",
            "state": "observed",
            "at": iso(2),
            "envelope": {"account_id": "soporte", "observed_at": iso(2)},
        }),
        json_line({
            "event_id": "imap:INBOX:1:3",
            "state": "observed",
            "at": iso(120),
            "envelope": {"observed_at": iso(120)},
        }),
    ]))

    delivered_additional = json_line({
        "event_id": "imap:ventas:INBOX:1:4",
        "account_id": "ventas",
        "observed_at": iso(120),
    })
    delivered_main = json_line({"event_id": "imap:INBOX:1:5", "observed_at": iso(120)})
    pending_additional = json_line({
        "event_id": "imap:ventas:INBOX:1:6",
        "account_id": "ventas",
        "observed_at": iso(120),
    })
    journal = state / "events.jsonl"
    journal.write_bytes(delivered_additional + delivered_main + pending_additional)
    (state / "dispatch.offset").write_text(str(len(delivered_additional) + len(delivered_main)))

    result = run(home, state, {"PAYNANI_RETENTION_DAYS": "90"})
    lifecycle_text = lifecycle.read_text()
    journal_bytes = journal.read_bytes()

    check("retention exits cleanly", 0, result.returncode)
    check("retention reports removed additional-account records", True, "retained" in result.stdout)
    check("old additional-account lifecycle event was removed",
          False, "imap:ventas:INBOX:1:1" in lifecycle_text)
    check("recent additional-account lifecycle event was kept",
          True, "imap:soporte:INBOX:1:2" in lifecycle_text)
    check("old main-account lifecycle event was kept",
          True, "imap:INBOX:1:3" in lifecycle_text)
    check("delivered old additional-account journal event was removed",
          False, b"imap:ventas:INBOX:1:4" in journal_bytes)
    check("old main-account journal event was kept",
          True, b"imap:INBOX:1:5" in journal_bytes)
    check("pending old additional-account journal event was kept",
          True, b"imap:ventas:INBOX:1:6" in journal_bytes)
    check("journal cursor was adjusted to the new delivered boundary",
          str(len(delivered_main)), (state / "dispatch.offset").read_text())

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
