#!/usr/bin/env python3
"""Tests for paynani doctor, paths and support-bundle."""

import json
import os
import pathlib
import shutil
import sys
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from paynani_lib import diagnostics as d

passed = failed = 0


def check(desc, condition):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}")
        failed += 1


def base_facts(listener="active", dispatcher="active", runtime_reachable=True, pending=0):
    return {
        "listener": {"unit": listener, "mailbox": "INBOX", "last_uid": 7,
                     "uidvalidity": 42, "heartbeat_at": "2026-01-01T00:00:00Z"},
        "dispatcher_unit": dispatcher,
        "queue": {"pending": pending, "oldest_age_seconds": 1 if pending else None,
                  "damaged_at": None, "cursor": 0, "journal_bytes": 0},
        "runtime": {"selected": "openclaw", "available": ["openclaw"],
                    "reachable": runtime_reachable, "detail": None,
                    "proves_route_readiness": False, "runtime_env": None},
        "delivery": {"last_accepted": None, "last_error": None},
        "config": {"env": "/tmp/.env", "env_mode": "0o600", "env_present": True,
                   "env_source": "test", "repo": str(ROOT), "version": "paynani 0.test"},
        "roster": {"path": "/tmp/roster.md", "present": True, "addresses": 1},
        "himalaya": {"config": "/tmp/himalaya.toml", "account": "paynani",
                     "config_present": True, "account_present": True},
        "git": {"is_repo": True, "commit": "abc1234", "branch": "main",
                "in_origin": True, "dirty_tracked": 0, "ahead": 0, "behind": 0},
        "spool": None,
        "reply": {},
    }


def doctor_with(facts):
    with mock.patch.object(d, "_facts", return_value=facts):
        return d.doctor_data()


data = doctor_with(base_facts())
check("doctor reports ok when all core checks pass", data["status"] == "ok")
check("doctor JSON shape has the published required keys", {"schema_version", "status", "generated_at", "checks", "paths"}.issubset(data))
check("every doctor check has a four-state status", all(c["status"] in d.STATUSES for c in data["checks"]))

blocked = doctor_with(base_facts(listener="failed"))
listener = next(c for c in blocked["checks"] if c["name"] == "listener")
check("failed service is blocked", blocked["status"] == "blocked" and listener["status"] == "blocked")
check("failed service names a safe repair command", listener.get("next_command") == "systemctl --user restart paynani-idle.service")

unknown = doctor_with(base_facts(listener="unknown", dispatcher="unknown"))
check("unqueryable service is unknown, not blocked", any(c["status"] == "unknown" for c in unknown["checks"]) and unknown["status"] == "unknown")

paths = d.paths_data()
for key in ["clone", "credentials", "state", "roster", "runtime_env", "supervisor", "logs"]:
    check(f"paths includes {key}", key in paths)

bundle_dir = pathlib.Path(tempfile.mkdtemp(prefix="paynani-bundle-test-"))
fake_env = bundle_dir / "secret.env"
fake_state = bundle_dir / "state"
fake_state.mkdir()
fake_env.write_text("AGENT_EMAIL_ACCOUNT=human@example.com\nAGENT_EMAIL_PASSWORD=hunter2-secret-token-value\nAPI_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
(fake_state / "idle.err.log").write_text("wrote to human@example.com with ghp_abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
try:
    with mock.patch.object(d, "env_file", return_value=fake_env), \
         mock.patch.object(d, "runtime_env", return_value=bundle_dir / "runtime.env"), \
         mock.patch.object(d, "state_dir", return_value=fake_state), \
         mock.patch.object(d, "doctor_data", return_value=data):
        out = d.support_bundle(bundle_dir / "out")
    combined = "\n".join(p.read_text(encoding="utf-8") for p in out.iterdir() if p.is_file())
    check("support-bundle redacts email addresses", "human@example.com" not in combined and "email-1@redacted.local" in combined)
    check("support-bundle redacts secret-valued env keys", "hunter2-secret-token-value" not in combined and "AGENT_EMAIL_PASSWORD=<redacted>" in combined)
    check("support-bundle redacts long token-looking strings", "ghp_abcdefghijklmnopqrstuvwxyz" not in combined)
finally:
    shutil.rmtree(bundle_dir, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
