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
        "version_drift": {"disk": "0.test", "listener": "0.test",
                          "dispatcher": "0.test", "drift": []},
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

codex_facts = base_facts()
codex_facts["runtime"]["selected"] = "codex"
codex_facts["spool"] = {"bytes_unread": 0, "bytes_total": 12, "writable": True}
with mock.patch.object(d, "_codex_observation_facts", return_value={
    "session_id_present": True,
    "last_queue": {"event_id": "imap:INBOX:42:7", "at": "2026-01-01T00:00:00Z", "detail": "queued"},
    "last_spool": None,
    "last_agent_run": None,
}):
    codex_data = doctor_with(codex_facts)
check("doctor renders Codex registered_session from a measured session id", any(c["name"] == "registered_session" and c["status"] == "ok" for c in codex_data["checks"]))
check("doctor renders Codex last_queue_attempt from recorded status", any(c["name"] == "last_queue_attempt" and c["status"] == "ok" for c in codex_data["checks"]))
check("doctor renders Codex last_queue_result from recorded status", any(c["name"] == "last_queue_result" and c["status"] == "ok" for c in codex_data["checks"]))

codex_unknown = base_facts()
codex_unknown["runtime"]["selected"] = "codex"
with mock.patch.object(d, "_codex_observation_facts", return_value={
    "session_id_present": False,
    "last_queue": None,
    "last_spool": {"event_id": "imap:INBOX:42:8", "at": "2026-01-01T00:00:01Z", "detail": "spooled"},
}):
    codex_unknown_data = doctor_with(codex_unknown)
check("doctor gives Codex registered_session an explicit unknown reason", any(c["name"] == "registered_session" and c["status"] == "unknown" and "no Codex live session" in c["summary"] for c in codex_unknown_data["checks"]))
check("doctor gives Codex last_queue_attempt an explicit unknown reason", any(c["name"] == "last_queue_attempt" and c["status"] == "unknown" and "spooled without a queue attempt" in c["summary"] for c in codex_unknown_data["checks"]))

hermes_facts = base_facts()
hermes_facts["runtime"]["selected"] = "hermes"
with mock.patch.object(d, "_hermes_route_observation", side_effect=lambda route: d._check(f"{route}_route_configured", "ok", f"{route} configured", {"route": route})):
    hermes_data = doctor_with(hermes_facts)
check("doctor renders Hermes notify route configuration observation", any(c["name"] == "notify_route_configured" and c["status"] == "ok" for c in hermes_data["checks"]))
check("doctor renders Hermes roster route configuration observation", any(c["name"] == "roster_route_configured" and c["status"] == "ok" for c in hermes_data["checks"]))

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

service_env_facts = base_facts()
service_env_facts["dependencies"]["service_environment"] = {
    "supervisor": "systemd",
    "checked": ["PATH", "OPENCLAW"],
    "command": ["systemctl", "--user", "show-environment"],
    "returncode": 0,
    "live": {"PATH": "/usr/bin", "OPENCLAW": "/old/bin/openclaw"},
    "declared": {"PATH": "/usr/bin", "OPENCLAW": "/new/bin/openclaw"},
}
service_env = d._service_environment_check(service_env_facts)
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

path_fix_facts = base_facts()
path_fix_facts["dependencies"]["service_environment"] = {
    "supervisor": "systemd",
    "checked": ["PATH"],
    "command": ["systemctl", "--user", "show-environment"],
    "returncode": 0,
    "live": {"PATH": "/usr/bin:/bin"},
    "declared": {"PATH": "/opt/foo/bin:/usr/bin:/bin"},
}
path_fix = d._service_environment_check(path_fix_facts)
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

old_service_python = base_facts()
old_service_python["dependencies"]["python"] = {
    "minimum": "3.10",
    "listener": {"found": "3.9.6", "executable": "/old/python3",
                 "minimum": "3.10", "supported": False},
    "dispatcher": {"found": "3.12.3", "executable": "/new/python3",
                   "minimum": "3.10", "supported": True},
}
py_check = next(c for c in doctor_with(old_service_python)["checks"] if c["name"] == "python")
check("doctor blocks on the service Python interpreter", py_check["status"] == "blocked" and "/old/python3" in py_check["summary"])

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
check("himalaya 0.x is blocked as unsupported for sending", him_check["status"] == "blocked" and "v2.x" in him_check["summary"])

v1_himalaya = base_facts()
v1_himalaya["dependencies"]["himalaya"] = {"runnable": True, "version_output": "himalaya v1.2.0",
                                           "major": 1, "account_check_ok": None}
him_check = next(c for c in doctor_with(v1_himalaya)["checks"] if c["name"] == "himalaya")
check("himalaya 1.x is blocked and points at the v2 schema", him_check["status"] == "blocked" and "section 4.3 schema" in him_check.get("next_command", ""))

failed_account = base_facts()
failed_account["dependencies"]["himalaya"]["account_check_ok"] = False
him_check = next(c for c in doctor_with(failed_account)["checks"] if c["name"] == "himalaya")
check("himalaya v2 with a failed account check is blocked and mentions the schema", him_check["status"] == "blocked" and "section 4.3 schema" in him_check.get("next_command", ""))

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

# --- version drift (#257) ---------------------------------------------------

vd_ok = d._version_drift_check({"disk": "0.7.2", "listener": "0.7.2",
                              "dispatcher": "0.7.2", "drift": []})
check("matching versions is ok", vd_ok["status"] == "ok")

vd_stale = d._version_drift_check({"disk": "0.7.2", "listener": "0.7.1",
                                 "dispatcher": "0.7.2", "drift": ["listener"]})
check("a stale listener is a warning, not blocked", vd_stale["status"] == "warning")
check("the warning names both versions", "0.7.2" in vd_stale["summary"] and "0.7.1" in vd_stale["summary"])
check("the fix is the restart command", "systemctl --user restart" in vd_stale["next_command"]
     and "paynani-idle.service" in vd_stale["next_command"]
     and "paynani-dispatch.service" in vd_stale["next_command"])

vd_unknown = d._version_drift_check({"disk": "0.7.2", "listener": None,
                                   "dispatcher": None, "drift": []})
check("neither service reporting yet is unknown, not a mismatch", vd_unknown["status"] == "unknown")

# #260: same VERSION, different commit -- version_drift_facts() names the
# mismatch by commit once the versions already agree.
vd_commit = d._version_drift_check({
    "disk": "0.7.2", "disk_commit": "c3a5de4111111111111111111111111111111111",
    "listener": "0.7.2", "dispatcher": "0.7.2", "drift": ["listener"],
    "drift_detail": {"listener": {"field": "commit",
                                  "disk": "c3a5de4111111111111111111111111111111111",
                                  "process": "eba16ec222222222222222222222222222222222"}},
})
check("a same-version commit drift is a warning, not blocked", vd_commit["status"] == "warning")
check("named by commit, abbreviated to 7 chars, not by version",
      vd_commit["summary"] == "paynani 0.7.2 on disk (c3a5de4), but the listener is running eba16ec")
check("the fix is still the restart command", "systemctl --user restart" in vd_commit["next_command"]
     and "paynani-idle.service" in vd_commit["next_command"]
     and "paynani-dispatch.service" in vd_commit["next_command"])

# #258's nit: VERSION missing on disk means nothing was compared, so this must
# read `unknown`, not the `ok` it used to claim.
vd_no_version = d._version_drift_check({"disk": None, "listener": "0.7.2",
                                      "dispatcher": "0.7.2", "drift": []})
check("VERSION missing on disk is unknown, not ok, even with both services reporting",
      vd_no_version["status"] == "unknown")

facts = base_facts()
facts["version_drift"] = {"disk": "0.7.2", "listener": "0.7.1",
                          "dispatcher": "0.7.2", "drift": ["listener"]}
data = doctor_with(facts)
names = {c["name"]: c for c in data["checks"]}
check("doctor includes the version_drift check", "version_drift" in names)
check("and it drives the overall status to warning", data["status"] == "warning")
check("doctor JSON with a drift still validates against the schema", not schema_errors(schema, data))

# #269: session_watch_state was declared for claudecode but nothing computed it,
# so every Claude Code host closed doctor on unknown. It reads the registry
# summary healthcheck already puts in facts["spool"].
def watch_spool(**overrides):
    spool = {"watch_live": None, "watch_expired": [], "watch_orphan": [],
             "watch_pending": [], "watch_yielded": 0, "watch_ended": 0,
             "watch_ended_last": None}
    spool.update(overrides)
    return spool

def watch_state(spool):
    return d._observation_check("session_watch_state",
                                {"runtime": {"selected": "claudecode"}, "spool": spool})

brief = {"session_id": "59d7250d-dda4-43a7-a980-3ce605eda909",
         "armed_at": "2026-09-23T03:15:39Z", "expires_at": "2026-09-23T03:45:39Z",
         "heartbeat_at": "2026-09-23T03:16:39Z", "watcher_pid": 808}

sw_live = watch_state(watch_spool(watch_live=brief))
check("a live watch is ok", sw_live["status"] == "ok")
check("and names the session and its last heartbeat",
      sw_live["summary"] == "watch armed by session 59d7250d, last heartbeat 2026-09-23T03:16:39Z")
check("the spool summary rides along as facts", sw_live.get("facts", {}).get("watch_live") == brief)

sw_expired = watch_state(watch_spool(watch_expired=[brief]))
check("an expired watch with no live one is a warning", sw_expired["status"] == "warning")
check("that says mail waits in the spool",
      sw_expired["summary"] == "no Claude Code session is watching mail; mail waits in the spool")
check("and says to re-arm with --from-hook",
      sw_expired.get("next_command") == "re-arm the Monitor with harness/session_watch.sh <state> --from-hook")

sw_ended = watch_state(watch_spool(watch_ended=1, watch_ended_last=dict(brief, ended_at="2026-09-23T03:45:39Z")))
check("a retired watch (ended, nothing live) is a warning", sw_ended["status"] == "warning")

sw_none = watch_state(watch_spool())
check("no registry at all is unknown, the honest never-armed answer", sw_none["status"] == "unknown")
check("with the usual label", sw_none["summary"] == d.OBSERVATION_LABELS["session_watch_state"])

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
