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




def _validate_type(schema_type, value):
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return True


def schema_errors(schema, value, path="$"):
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}")
    if "type" in schema and not _validate_type(schema["type"], value):
        errors.append(f"{path}: expected {schema['type']}")
        return errors
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required {key}")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in value:
                errors.extend(schema_errors(subschema, value[key], f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(schema_errors(schema["items"], item, f"{path}[{i}]"))
    return errors

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
        "dependencies": {
            "python": {"found": "3.12.3", "minimum": "3.10", "supported": True},
            "himalaya": {"runnable": True, "version_output": "himalaya v2.1.0",
                        "major": 2, "account_check_ok": True},
        },
    }


def doctor_with(facts):
    with mock.patch.object(d, "_facts", return_value=facts):
        return d.doctor_data()


schema = json.loads((ROOT / "examples" / "doctor.schema.json").read_text(encoding="utf-8"))

data = doctor_with(base_facts())
check("doctor reports unknown when declared observations have no harness signal", data["status"] == "unknown")
check("doctor JSON output validates against published schema", not schema_errors(schema, data))
invalid = dict(data)
invalid.pop("checks")
check("doctor schema test rejects missing required output", bool(schema_errors(schema, invalid)))
check("every doctor check has a four-state status", all(c["status"] in d.STATUSES for c in data["checks"]))
check("doctor includes runtime capability observations", any(c["name"] == "gateway_reachable" for c in data["checks"]))
check("doctor reports missing observation signals as unknown", any(c["name"] == "session_destination_available" and c["status"] == "unknown" for c in data["checks"]))
spool_facts = base_facts()
spool_facts["runtime"]["selected"] = "claudecode"
spool_facts["spool"] = {"bytes_unread": 9, "bytes_total": 9, "writable": True}
spool_data = doctor_with(spool_facts)
check("doctor reads published spool bytes_unread signal", any(c["name"] == "spool_unread_bytes" and c["status"] == "warning" for c in spool_data["checks"]))
check("doctor reads measured spool writable signal", any(c["name"] == "spool_writable" and c["status"] == "ok" for c in spool_data["checks"]))

queue_first = {"pending": 1, "oldest_age_seconds": 1, "damaged_at": None, "cursor": 10, "journal_bytes": 20}
queue_second = {"pending": 1, "oldest_age_seconds": 1, "damaged_at": None, "cursor": 15, "journal_bytes": 25}
with mock.patch.object(d, "QUEUE_DRAIN_SAMPLE_SECONDS", 0), \
     mock.patch.object(d.healthcheck, "queue_facts", return_value=queue_second):
    draining = d._queue_check(queue_first)
check("doctor measures cursor advancement before calling a queue stalled", draining["status"] == "ok" and draining["summary"] == "queued events are draining")

damaged_second = dict(queue_second, damaged_at=99)
with mock.patch.object(d, "QUEUE_DRAIN_SAMPLE_SECONDS", 0), \
     mock.patch.object(d.healthcheck, "queue_facts", return_value=damaged_second):
    damaged_after_sample = d._queue_check(queue_first)
check("doctor reports second-sample journal damage before cursor advancement", damaged_after_sample["status"] == "blocked" and "damaged at byte 99" in damaged_after_sample["summary"])

stale_second = dict(queue_second, cursor=10, oldest_age_seconds=d.healthcheck.STALE_QUEUE + 1)
with mock.patch.object(d, "QUEUE_DRAIN_SAMPLE_SECONDS", 0), \
     mock.patch.object(d.healthcheck, "queue_facts", return_value=stale_second):
    stalled = d._queue_check(queue_first)
check("doctor marks a non-draining stale queue blocked", stalled["status"] == "blocked")

with mock.patch.object(d, "platform") as platform_mock, \
     mock.patch.object(d, "_safe_run", return_value={"command": ["systemctl", "--user", "show-environment"], "returncode": 0, "stdout": "PATH=/usr/bin\nOPENCLAW=/old/bin/openclaw\n", "stderr": ""}), \
     mock.patch.object(d, "_environmentd_values", return_value={"PATH": "/usr/bin", "OPENCLAW": "/new/bin/openclaw"}):
    platform_mock.system.return_value = "Linux"
    service_env = d._service_environment_check(base_facts()["runtime"] and base_facts())
check("doctor warns when systemd live environment differs from environment.d", service_env["status"] == "warning" and service_env.get("next_command") == "systemctl --user set-environment OPENCLAW=/new/bin/openclaw")

with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=True):
    environmentd = d._parse_environment_lines("""
PATH=/opt/foo/bin:$PATH
TOOL=${PATH}/tool
CACHE=${MISSING:-/tmp/paynani-cache}
MARKER=${PATH:+enabled}
""")
check("environment.d expands $PATH before emitting fixes", environmentd["PATH"] == "/opt/foo/bin:/usr/bin:/bin")
check("environment.d expands ${PATH} from earlier declarations", environmentd["TOOL"] == "/opt/foo/bin:/usr/bin:/bin/tool")
check("environment.d expands default and alternate forms", environmentd["CACHE"] == "/tmp/paynani-cache" and environmentd["MARKER"] == "enabled")

with mock.patch.object(d, "platform") as platform_mock, \
     mock.patch.object(d, "_safe_run", return_value={"command": ["systemctl", "--user", "show-environment"], "returncode": 0, "stdout": "PATH=/usr/bin:/bin\n", "stderr": ""}), \
     mock.patch.object(d, "_environmentd_values", return_value={"PATH": "/opt/foo/bin:/usr/bin:/bin"}):
    platform_mock.system.return_value = "Linux"
    path_fix = d._service_environment_check(base_facts())
check("doctor emits resolved PATH repair command, not literal $PATH", path_fix.get("next_command") == "systemctl --user set-environment PATH=/opt/foo/bin:/usr/bin:/bin")

imap_ok = base_facts()
imap_ok["listener"].update({
    "heartbeat_age_seconds": 10,
    "imap_last_disconnect_at": "2026-01-01T00:00:00Z",
    "imap_last_disconnect_age_seconds": 30,
    "imap_last_disconnect_error": "connection lost",
    "imap_last_recovered_at": "2026-01-01T00:00:20Z",
    "imap_last_recovered_age_seconds": 10,
    "imap_reconnect_attempts": 2,
    "imap_current_backoff_seconds": 0,
})
imap_check = next(c for c in doctor_with(imap_ok)["checks"] if c["name"] == "imap_telemetry")
check("doctor reports IMAP reconnection telemetry when healthy", imap_check["status"] == "ok" and imap_check["facts"]["reconnect_attempts"] == 2)

imap_retry = base_facts()
imap_retry["listener"].update({
    "heartbeat_age_seconds": 900,
    "imap_last_disconnect_at": "2026-01-01T00:00:00Z",
    "imap_last_disconnect_error": "connection lost",
    "imap_reconnect_attempts": 3,
    "imap_current_backoff_seconds": 40,
})
imap_check = next(c for c in doctor_with(imap_retry)["checks"] if c["name"] == "imap_telemetry")
check("doctor warns while IMAP listener is backing off", imap_check["status"] == "warning" and imap_check["facts"]["current_backoff_seconds"] == 40)

blocked = doctor_with(base_facts(listener="failed"))
listener = next(c for c in blocked["checks"] if c["name"] == "listener")
check("failed service is blocked", blocked["status"] == "blocked" and listener["status"] == "blocked")
check("failed service names a safe repair command", listener.get("next_command") == "systemctl --user restart paynani-idle.service")

# #173: minimum-version checks (python, himalaya, opencode-only-on-opencode).
old_python = base_facts()
old_python["dependencies"]["python"] = {"found": "3.9.6", "minimum": "3.10", "supported": False}
py_check = next(c for c in doctor_with(old_python)["checks"] if c["name"] == "python")
check("python below 3.10 is blocked and names the version found", py_check["status"] == "blocked" and "3.9.6" in py_check["summary"] and "3.10" in py_check["summary"])

ok_python = doctor_with(base_facts())
check("python at or above 3.10 is ok", next(c for c in ok_python["checks"] if c["name"] == "python")["status"] == "ok")

no_himalaya = base_facts()
no_himalaya["dependencies"]["himalaya"] = {"runnable": False, "version_output": ""}
him_check = next(c for c in doctor_with(no_himalaya)["checks"] if c["name"] == "himalaya")
check("himalaya binary that cannot run is unknown, not blocked", him_check["status"] == "unknown")

old_himalaya = base_facts()
old_himalaya["dependencies"]["himalaya"] = {"runnable": True, "version_output": "himalaya v0.9.0",
                                            "major": 0, "account_check_ok": None}
him_check = next(c for c in doctor_with(old_himalaya)["checks"] if c["name"] == "himalaya")
check("himalaya 0.x is blocked as an unrecognized schema", him_check["status"] == "blocked")

failed_account = base_facts()
failed_account["dependencies"]["himalaya"]["account_check_ok"] = False
him_check = next(c for c in doctor_with(failed_account)["checks"] if c["name"] == "himalaya")
check("himalaya with a recognized schema but a failed account check is blocked", him_check["status"] == "blocked")

no_opencode_check = doctor_with(base_facts())
check("opencode check is absent when opencode is not the selected runtime", not any(c["name"] == "opencode" for c in no_opencode_check["checks"]))

opencode_facts = base_facts()
opencode_facts["runtime"]["selected"] = "opencode"
opencode_facts["dependencies"]["opencode"] = {"runnable": True, "version_output": "1.18.31",
                                              "field_tested": "1.18.31", "found": "1.18.31"}
oc_check = next(c for c in doctor_with(opencode_facts)["checks"] if c["name"] == "opencode")
check("opencode at the field-tested version is ok", oc_check["status"] == "ok")

older_opencode = base_facts()
older_opencode["runtime"]["selected"] = "opencode"
older_opencode["dependencies"]["opencode"] = {"runnable": True, "version_output": "1.10.0",
                                              "field_tested": "1.18.31", "found": "1.10.0"}
oc_check = next(c for c in doctor_with(older_opencode)["checks"] if c["name"] == "opencode")
check("opencode below the field-tested version is a warning, not blocked", oc_check["status"] == "warning")

missing_opencode = base_facts()
missing_opencode["runtime"]["selected"] = "opencode"
missing_opencode["dependencies"]["opencode"] = {"runnable": False, "version_output": "", "field_tested": "1.18.31"}
oc_check = next(c for c in doctor_with(missing_opencode)["checks"] if c["name"] == "opencode")
check("missing opencode binary on the opencode runtime is blocked", oc_check["status"] == "blocked")

unknown = doctor_with(base_facts(listener="unknown", dispatcher="unknown"))
check("unqueryable service is unknown, not blocked", any(c["status"] == "unknown" for c in unknown["checks"]) and unknown["status"] == "unknown")

paths = d.paths_data()
for key in ["clone", "credentials", "state", "roster", "runtime_env", "supervisor", "logs"]:
    check(f"paths includes {key}", key in paths)

bundle_dir = pathlib.Path(tempfile.mkdtemp(prefix="paynani-bundle-test-"))
fake_env = bundle_dir / "secret.env"
fake_state = bundle_dir / "state"
fake_state.mkdir()
fake_env.write_text("AGENT_EMAIL_ACCOUNT=human@example.com\nAGENT_EMAIL_PASSWORD=hunter2-secret-token-value\nAPI_TOKEN=ghp_ab...wxyz\nLONG_SERVICE_NAME=metisclaudetobvalueover24chars\nHOST_URL=https://example.test/some/really/long/path\nPLAIN_SETTING=visible-value\n", encoding="utf-8")
(fake_state / "idle.err.log").write_text("wrote to human@example.com with ghp_abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
try:
    with mock.patch.object(d, "env_file", return_value=fake_env), \
         mock.patch.object(d, "runtime_env", return_value=bundle_dir / "runtime.env"), \
         mock.patch.object(d, "state_dir", return_value=fake_state), \
         mock.patch.object(d, "doctor_data", return_value=data):
        out = d.support_bundle(bundle_dir / "out")
    combined = "\n".join(p.read_text(encoding="utf-8") for p in out.iterdir() if p.is_file())
    names = {p.name for p in out.iterdir()}
    check("support-bundle writes credential keys, not credential values", "credentials.keys.txt" in names and "credentials.env.txt" not in names)
    keys = (out / "credentials.keys.txt").read_text(encoding="utf-8")
    expected_keys = {"AGENT_EMAIL_ACCOUNT", "AGENT_EMAIL_PASSWORD", "API_TOKEN", "LONG_SERVICE_NAME", "HOST_URL", "PLAIN_SETTING"}
    check("support-bundle preserves every credential key name", all(f"{key}=present" in keys for key in expected_keys))
    check("support-bundle omits every credential value", all(value not in combined for value in ["human@example.com", "hunter2-secret-token-value", "ghp_ab...wxyz", "metisclaudetobvalueover24chars", "https://example.test/some/really/long/path", "visible-value"]))
    check("support-bundle redacts email addresses in logs", "human@example.com" not in combined and "email-1@redacted.local" in combined)
    check("support-bundle redacts long token-looking strings in logs", "ghp_ab...wxyz" not in combined)
    contaminated = bundle_dir / "contaminated-out"
    contaminated.mkdir()
    (contaminated / "credentials.env.txt").write_text("SECRET=leftover\n", encoding="utf-8")
    try:
        d.support_bundle(contaminated)
        rejected_contaminated = False
    except FileExistsError:
        rejected_contaminated = True
    check("support-bundle rejects non-empty output directories", rejected_contaminated)
finally:
    shutil.rmtree(bundle_dir, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
