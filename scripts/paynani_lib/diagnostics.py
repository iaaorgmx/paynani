"""Diagnostics commands for the paynani CLI."""

from __future__ import annotations

import json
import os
import re
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
HARNESS = ROOT / "harness"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HARNESS))

import healthcheck  # noqa: E402
try:
    import capabilities  # noqa: E402
except ImportError:  # pragma: no cover - only possible from a partial checkout
    capabilities = None
from paths import (  # noqa: E402
    env_file,
    manifest,
    install_root,
    repo_root,
    roster,
    runtime_env,
    state_dir,
)

STATUSES = {"ok", "warning", "blocked", "unknown"}
SECRET_NAME = re.compile(r"(PASSWORD|PASS|TOKEN|SECRET|KEY|AUTH|COOKIE|BEARER)", re.I)
EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
LONG_SECRET = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z0-9_./+-]{24,}(?![A-Za-z0-9_])")


def _safe_run(args: list[str], timeout: int = 10) -> dict:
    try:
        run = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"command": args, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {"command": args, "returncode": run.returncode,
            "stdout": run.stdout, "stderr": run.stderr}


def paths_data() -> dict:
    system = platform.system()
    if system == "Darwin":
        supervisor = {
            "type": "launchd",
            "launchd_labels": ["com.paynani.idle", "com.paynani.dispatch"],
        }
    else:
        supervisor = {
            "type": "systemd-user",
            "systemd_user_units": ["paynani-idle.service", "paynani-dispatch.service"],
        }
    return {
        "clone": str(repo_root()),
        "credentials": str(env_file()),
        "state": str(state_dir()),
        "roster": str(roster()),
        "runtime_env": str(runtime_env()),
        "supervisor": supervisor,
        "logs": {
            "listener_error": str(state_dir() / "idle.err.log"),
            "dispatcher_error": str(state_dir() / "dispatch.err.log"),
            "sent": str(state_dir() / "sent.log"),
            "journal": str(state_dir() / "events.jsonl"),
        },
        "install_manifest": str(manifest()),
        "install_root": str(install_root()),
    }



QUEUE_DRAIN_SAMPLE_SECONDS = float(os.environ.get("PAYNANI_DOCTOR_QUEUE_SAMPLE_SECONDS", 5))


def _queue_check(initial: dict) -> dict:
    if initial.get("damaged_at") is not None:
        return _check(
            "queue",
            "blocked",
            f"event journal is damaged at byte {initial['damaged_at']}; preserve a copy and open an issue with the three lines around that byte",
            initial,
        )
    if initial.get("pending", 0) == 0:
        return _check("queue", "ok", "no events are waiting", initial)

    if QUEUE_DRAIN_SAMPLE_SECONDS > 0:
        time.sleep(QUEUE_DRAIN_SAMPLE_SECONDS)
    second = healthcheck.queue_facts()
    facts = {"first": initial, "second": second, "sample_seconds": QUEUE_DRAIN_SAMPLE_SECONDS}

    first_cursor = initial.get("cursor")
    second_cursor = second.get("cursor")
    if isinstance(first_cursor, int) and isinstance(second_cursor, int) and second_cursor > first_cursor:
        return _check("queue", "ok", "queued events are draining", facts)
    if second.get("damaged_at") is not None:
        return _check(
            "queue",
            "blocked",
            f"event journal is damaged at byte {second['damaged_at']}; preserve a copy and open an issue with the three lines around that byte",
            facts,
        )
    if second.get("pending", 0) == 0:
        return _check("queue", "ok", "queue drained during the diagnostic sample", facts)
    age = second.get("oldest_age_seconds")
    if age is not None and age > healthcheck.STALE_QUEUE:
        return _check("queue", "blocked", "queued events are not draining and appear stalled", facts, _service_fix(healthcheck.DISPATCH_UNIT))
    return _check("queue", "warning", "queued events are not draining yet", facts, "scripts/healthcheck.py")


def _parse_environment_lines(text: str) -> dict[str, str]:
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name:
            values[name] = value.strip().strip('"').strip("'")
    return values


def _environmentd_values(directory: Path | None = None) -> dict[str, str]:
    directory = directory or (Path.home() / ".config" / "environment.d")
    values = {}
    try:
        files = sorted(directory.glob("*.conf"))
    except OSError:
        return values
    for path in files:
        try:
            values.update(_parse_environment_lines(path.read_text(encoding="utf-8-sig", errors="replace")))
        except OSError:
            continue
    return values


def _service_environment_check(facts: dict) -> dict:
    if platform.system() == "Darwin":
        return _check("service_environment", "unknown", "systemd --user is not available on macOS", {"supervisor": "launchd"})

    wanted = ["PATH"]
    if (facts.get("runtime") or {}).get("selected") == "openclaw":
        wanted.append("OPENCLAW")
    run = _safe_run(["systemctl", "--user", "show-environment"], timeout=5)
    if run.get("returncode") != 0:
        return _check("service_environment", "unknown", "systemd --user environment cannot be queried from this environment", {"command": run.get("command"), "returncode": run.get("returncode"), "stderr": run.get("stderr", "")})

    live = _parse_environment_lines(run.get("stdout", ""))
    declared_all = _environmentd_values()
    declared = {name: declared_all[name] for name in wanted if name in declared_all}
    if not declared:
        return _check("service_environment", "ok", "no persistent PATH/OPENCLAW declarations need comparison", {"checked": wanted, "declared": []})

    mismatches = {name: {"live": live.get(name), "declared": declared[name]}
                  for name in declared if live.get(name) != declared[name]}
    compare = {"checked": wanted, "declared": sorted(declared), "mismatches": mismatches}
    if not mismatches:
        return _check("service_environment", "ok", "systemd --user environment matches persistent declarations", compare)

    assignments = " ".join(f"{name}={shlex.quote(values['declared'])}" for name, values in mismatches.items())
    return _check(
        "service_environment",
        "warning",
        "systemd --user live environment differs from ~/.config/environment.d",
        compare,
        f"systemctl --user set-environment {assignments}",
    )


def _facts() -> dict:
    facts = {
        "listener": healthcheck.listener_facts(),
        "dispatcher_unit": healthcheck.unit_state(healthcheck.DISPATCH_UNIT),
        "queue": healthcheck.queue_facts(),
        "runtime": healthcheck.runtime_facts(),
        "delivery": healthcheck.delivery_facts(),
        "config": healthcheck.config_facts(),
        "roster": healthcheck.roster_facts(),
        "himalaya": healthcheck.himalaya_facts(),
        "git": healthcheck.git_facts(),
    }
    facts["spool"] = healthcheck.spool_facts(facts["runtime"].get("selected"))
    facts["reply"] = healthcheck.reply_facts(facts["queue"]["cursor"])
    return facts


def _check(name: str, status: str, summary: str, facts=None, fix: str | None = None) -> dict:
    assert status in STATUSES
    out = {"name": name, "status": status, "summary": summary}
    if fix:
        out["next_command"] = fix
    if facts is not None:
        out["facts"] = facts
    return out


def _service_fix(unit: str) -> str:
    return f"systemctl --user restart {unit}"


OBSERVATION_LABELS = {
    "binary_runnable": "runtime adapter can run its CLI",
    "gateway_reachable": "runtime gateway is reachable",
    "health_route_reachable": "Hermes health route is reachable",
    "notify_route_configured": "Hermes notify route is configured",
    "roster_route_configured": "Hermes roster route is configured",
    "spool_writable": "runtime spool is writable",
    "spool_unread_bytes": "runtime spool unread bytes are observable",
    "session_watch_state": "Claude Code session watcher state is observable",
    "registered_session": "Codex registered session is observable",
    "last_queue_attempt": "Codex last queue attempt is observable",
    "last_queue_result": "Codex last queue result is observable",
    "plugin_installed": "OpenCode plugin registration is observable",
    "open_processes": "OpenCode process list is observable",
    "session_destination_available": "runtime destination session is observable",
    "last_delivery_attempt": "last delivery attempt is observable",
    "last_delivery_result": "last delivery result is observable",
}


def _observation_check(name: str, facts: dict) -> dict:
    runtime = facts.get("runtime") or {}
    delivery = facts.get("delivery") or {}
    spool = facts.get("spool")
    selected = runtime.get("selected")

    if name in {"binary_runnable", "gateway_reachable", "health_route_reachable"}:
        reachable = runtime.get("reachable")
        if reachable is True:
            return _check(name, "ok", OBSERVATION_LABELS.get(name, name), runtime)
        if reachable is False:
            return _check(name, "blocked", OBSERVATION_LABELS.get(name, name), runtime, "scripts/healthcheck.py")
        return _check(name, "unknown", OBSERVATION_LABELS.get(name, name), runtime, "scripts/healthcheck.py")

    if name in {"last_delivery_attempt", "last_delivery_result"}:
        if delivery.get("last_accepted"):
            return _check(name, "ok", OBSERVATION_LABELS.get(name, name), delivery)
        if delivery.get("last_error"):
            return _check(name, "blocked", OBSERVATION_LABELS.get(name, name), delivery, "scripts/healthcheck.py")
        return _check(name, "unknown", OBSERVATION_LABELS.get(name, name), delivery)

    if name == "spool_writable":
        if isinstance(spool, dict):
            if spool.get("writable") is True:
                return _check(name, "ok", OBSERVATION_LABELS[name], spool)
            if spool.get("writable") is False:
                return _check(name, "blocked", OBSERVATION_LABELS[name], spool, "scripts/healthcheck.py")
        return _check(name, "unknown", OBSERVATION_LABELS[name], spool)

    if name == "spool_unread_bytes":
        if isinstance(spool, dict) and spool.get("bytes_unread") is not None:
            status = "warning" if spool.get("bytes_unread", 0) else "ok"
            return _check(name, status, OBSERVATION_LABELS[name], spool)
        return _check(name, "unknown", OBSERVATION_LABELS[name], spool)

    if name in {"plugin_installed", "open_processes", "session_destination_available"} and selected == "opencode":
        plugin = healthcheck.opencode_plugin_facts(state_dir())
        if name == "plugin_installed" and plugin.get("plugin_registered") is not None:
            status = "ok" if plugin["plugin_registered"] else "blocked"
            return _check(name, status, OBSERVATION_LABELS[name], plugin, "scripts/install.sh --runtime opencode --upgrade" if status == "blocked" else None)
        if name == "open_processes" and plugin.get("open_pids") is not None:
            status = "ok" if plugin.get("open_pids") else "warning"
            return _check(name, status, OBSERVATION_LABELS[name], plugin)
        if name == "session_destination_available" and plugin.get("consumer_pid") is not None:
            return _check(name, "ok", OBSERVATION_LABELS[name], plugin)
        return _check(name, "unknown", OBSERVATION_LABELS.get(name, name), plugin)

    return _check(name, "unknown", OBSERVATION_LABELS.get(name, name), {"runtime": selected})


def _capability_checks(facts: dict) -> list[dict]:
    selected = (facts.get("runtime") or {}).get("selected")
    if not selected or capabilities is None:
        return []
    spec = capabilities.CAPABILITIES.get(selected)
    if not spec:
        return [_check("capabilities", "unknown", f"no capability declaration for {selected}", {"runtime": selected})]
    checks = []
    for observation in spec.get("dynamic_observations", ()):
        checks.append(_observation_check(observation, facts))
    return checks


def doctor_data() -> dict:
    facts = _facts()
    checks = []

    listener = facts["listener"]
    lu = listener.get("unit")
    if lu == "active":
        status, summary, fix = "ok", "listener service is active", None
    elif lu == "unknown":
        status, summary, fix = "unknown", "listener unit cannot be queried from this environment", "scripts/healthcheck.py"
    else:
        status, summary, fix = "blocked", f"listener service is {lu}", _service_fix(healthcheck.LISTENER_UNIT)
    checks.append(_check("listener", status, summary, listener, fix))

    du = facts["dispatcher_unit"]
    if du == "active":
        status, summary, fix = "ok", "dispatcher service is active", None
    elif du == "unknown":
        status, summary, fix = "unknown", "dispatcher unit cannot be queried from this environment", "scripts/healthcheck.py"
    else:
        status, summary, fix = "blocked", f"dispatcher service is {du}", _service_fix(healthcheck.DISPATCH_UNIT)
    checks.append(_check("dispatcher", status, summary, {"unit": du}, fix))

    runtime = facts["runtime"]
    if runtime.get("selected") is None:
        checks.append(_check("runtime", "blocked", "no runtime is selected", runtime, "scripts/install.sh --runtime <runtime> --upgrade"))
    elif runtime.get("reachable") is True:
        checks.append(_check("runtime", "ok", f"{runtime['selected']} runtime is reachable", runtime))
    elif runtime.get("reachable") is False:
        checks.append(_check("runtime", "blocked", f"{runtime['selected']} runtime is not reachable", runtime, "scripts/healthcheck.py"))
    else:
        checks.append(_check("runtime", "unknown", "runtime reachability is unknown", runtime, "scripts/healthcheck.py"))

    q = facts["queue"]
    checks.append(_queue_check(q))
    checks.append(_service_environment_check(facts))

    config = facts["config"]
    if config.get("env_present") and config.get("env_mode") == "0o600":
        checks.append(_check("credentials", "ok", "credentials file exists with mode 0600", config))
    elif config.get("env_present"):
        checks.append(_check("credentials", "warning", f"credentials file mode is {config.get('env_mode')}", config, f"chmod 600 {config.get('env')}"))
    else:
        checks.append(_check("credentials", "blocked", "credentials file is missing", config, "scripts/paynani onboard"))

    ros = facts["roster"]
    if ros.get("present") and ros.get("addresses", 0) > 0:
        checks.append(_check("roster", "ok", f"roster has {ros['addresses']} address(es)", ros))
    elif ros.get("present"):
        checks.append(_check("roster", "blocked", "roster has no authorized addresses", ros, "scripts/paynani roster add NAME ADDRESS"))
    else:
        checks.append(_check("roster", "blocked", "roster.md is missing", ros, "scripts/paynani roster add NAME ADDRESS"))

    checks.extend(_capability_checks(facts))

    him = facts["himalaya"]
    if him.get("account_present"):
        checks.append(_check("smtp", "ok", "himalaya paynani account is configured", him))
    elif him.get("config_present"):
        checks.append(_check("smtp", "blocked", "himalaya config is missing [accounts.paynani]", him, "himalaya account configure"))
    else:
        checks.append(_check("smtp", "blocked", "himalaya config is missing", him, "himalaya account configure"))

    overall = "ok"
    if any(c["status"] == "blocked" for c in checks):
        overall = "blocked"
    elif any(c["status"] == "warning" for c in checks):
        overall = "warning"
    elif any(c["status"] == "unknown" for c in checks):
        overall = "unknown"

    return {"schema_version": 1, "status": overall, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "checks": checks, "paths": paths_data()}


def _redactor():
    emails: dict[str, str] = {}
    secrets: dict[str, str] = {}
    def repl_email(m):
        s = m.group(0)
        emails.setdefault(s, f"email-{len(emails)+1}@redacted.local")
        return emails[s]
    def repl_secret(m):
        s = m.group(0)
        if '/' in s and (s.startswith('/') or s.startswith('./')):
            return s
        secrets.setdefault(s, f"secret-{len(secrets)+1}")
        return secrets[s]
    def redact(text: str) -> str:
        lines = []
        for line in text.splitlines():
            if "=" in line and SECRET_NAME.search(line.split("=", 1)[0]):
                line = line.split("=", 1)[0] + "=<redacted>"
            line = EMAIL.sub(repl_email, line)
            line = LONG_SECRET.sub(repl_secret, line)
            lines.append(line)
        return "\n".join(lines)
    return redact


def _credentials_keys(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        mode = oct(path.stat().st_mode & 0o777)
    except OSError:
        return None
    lines = [f"mode {mode}"]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            lines.append(f"{key}=present")
    return "\n".join(lines) + "\n"


def _read_redacted(path: Path, redact, max_bytes=20000) -> str | None:
    try:
        data = path.read_bytes()[-max_bytes:]
    except OSError:
        return None
    return redact(data.decode("utf-8", errors="replace"))


def support_bundle(output: str | Path) -> Path:
    out = Path(output)
    if out.exists():
        if not out.is_dir():
            raise FileExistsError(f"support bundle output path exists and is not a directory: {out}")
        if any(out.iterdir()):
            raise FileExistsError(f"support bundle output directory is not empty: {out}")
    else:
        out.mkdir(parents=True)
    redact = _redactor()
    data = {"doctor": doctor_data(), "paths": paths_data()}
    (out / "summary.json").write_text(redact(json.dumps(data, indent=2, sort_keys=True)), encoding="utf-8")
    (out / "git-status.txt").write_text(redact(_safe_run(["git", "-C", str(repo_root()), "status", "--short", "--branch"])["stdout"]), encoding="utf-8")
    credentials = _credentials_keys(env_file())
    if credentials is not None:
        (out / "credentials.keys.txt").write_text(credentials, encoding="utf-8")
    for name, path in {
        "runtime.env.txt": runtime_env(),
        "idle.err.log.txt": state_dir() / "idle.err.log",
        "dispatch.err.log.txt": state_dir() / "dispatch.err.log",
    }.items():
        text = _read_redacted(path, redact)
        if text is not None:
            (out / name).write_text(text, encoding="utf-8")
    return out


def print_paths(as_json: bool) -> int:
    data = paths_data()
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        for k, v in data.items():
            print(f"{k:16} {json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v}")
    return 0


def print_doctor(as_json: bool) -> int:
    data = doctor_data()
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"paynani doctor: {data['status']}")
        for c in data["checks"]:
            print(f"{c['status']:8} {c['name']}: {c['summary']}")
            if c.get("next_command"):
                print(f"         next: {c['next_command']}")
    return 1 if data["status"] == "blocked" else 0
