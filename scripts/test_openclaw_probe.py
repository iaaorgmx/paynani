#!/usr/bin/env python3
"""
The OpenClaw probe is synthetic: it must not touch IMAP, the journal, or the
dispatch cursor, and healthcheck reports it on its own row.

    python3 scripts/test_openclaw_probe.py
"""

from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import healthcheck as hc  # noqa: E402

passed = failed = 0


def check(desc, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}\n       expected: {expected!r}\n       actual:   {actual!r}")
        failed += 1


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    state = root / "state"
    bin_dir = root / "bin"
    bin_dir.mkdir()
    openclaw = bin_dir / "openclaw"
    calls = root / "calls.jsonl"
    openclaw.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"path = pathlib.Path({str(calls)!r})\n"
        "path.write_text(path.read_text() + json.dumps(sys.argv[1:]) + '\\n' if path.exists() else json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['system', 'event'] and '--mode' in sys.argv and '--text' in sys.argv:\n"
        "    print('accepted')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    openclaw.chmod(openclaw.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env.update({
        "PAYNANI_STATE": str(state),
        "OPENCLAW": str(openclaw),
    })
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "paynani"), "openclaw", "probe", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    check("probe exits successfully", 0, run.returncode)
    check("probe says it was accepted", True, "openclaw_probe=accepted" in run.stdout)
    record_path = state / "openclaw.probe.json"
    check("probe writes its own state file", True, record_path.is_file())
    record = json.loads(record_path.read_text(encoding="utf-8"))
    check("probe record is synthetic", True,
          record["dry_run"] and record["namespace"].startswith("probe:"))
    check("probe does not create a journal", False, (state / "events.jsonl").exists())
    check("probe does not create a cursor", False, (state / "dispatch.offset").exists())
    argv = json.loads(calls.read_text(encoding="utf-8").splitlines()[0])
    check("probe uses openclaw system event --mode now", True,
          argv[:2] == ["system", "event"] and "--mode" in argv and "now" in argv)

    old_probe = hc.OPENCLAW_PROBE
    try:
        hc.OPENCLAW_PROBE = record_path
        facts = hc.openclaw_probe_facts("openclaw")
        check("healthcheck reads the probe status", "accepted", facts["status"])
        text = hc.render({
            "listener": {"unit": "active", "mailbox": "INBOX", "last_uid": 1,
                         "last_error": None},
            "queue": {"pending": 0, "oldest_age_seconds": None, "cursor": 0,
                      "journal_bytes": 0, "damaged_at": None},
            "runtime": {"selected": "openclaw", "available": ["openclaw"],
                        "reachable": True, "detail": None, "runtime_env": None},
            "config": {"env": "/tmp/env", "env_mode": "0o600", "env_present": True,
                       "env_source": "test", "repo": str(ROOT), "version": None},
            "spool": None,
            "instructions": None,
            "openclaw_probe": facts,
            "dispatcher_unit": "active",
            "delivery": {"last_accepted": None, "last_error": None},
            "reply": None,
            "roster": {"path": "/tmp/roster.md", "present": True,
                       "addresses": 1, "notifiers": []},
            "himalaya": {"config": "/tmp/himalaya.toml", "config_present": True,
                         "account_present": True, "account": "paynani"},
            "git": {"is_repo": False},
        }, [], [])
        check("healthcheck renders a separate probe row", True,
              "openclaw probe accepted" in text and record["namespace"] in text)
    finally:
        hc.OPENCLAW_PROBE = old_probe

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
