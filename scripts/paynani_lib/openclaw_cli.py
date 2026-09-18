"""OpenClaw-specific CLI helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "harness"
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

from adapters import CONFIG, RETRY  # noqa: E402
from adapters import openclaw as openclaw_adapter  # noqa: E402
from paths import state_dir  # noqa: E402

PROBE_FILE = "openclaw.probe.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _one_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def _write_probe(record: dict, path: Path | None = None) -> Path:
    target = path or state_dir() / PROBE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return target


def _result_record(*, probe_id: str, binary: str | None, status: str,
                   detail: str = "", returncode: int | None = None,
                   stdout: str = "", stderr: str = "") -> dict:
    record = {
        "schema_version": 1,
        "probe_id": probe_id,
        "namespace": f"probe:{probe_id}",
        "at": _now(),
        "runtime": "openclaw",
        "dry_run": True,
        "status": status,
        "detail": detail,
        "binary": binary,
        "returncode": returncode,
    }
    if stdout:
        record["stdout"] = _one_line(stdout)
    if stderr:
        record["stderr"] = _one_line(stderr)
    return record


def run_probe(args) -> int:
    if not args.dry_run:
        print("paynani openclaw probe currently supports only --dry-run", file=sys.stderr)
        return 64

    probe_id = uuid.uuid4().hex
    namespace = f"probe:{probe_id}"
    binary = openclaw_adapter.find_binary()
    if not binary:
        record = _result_record(
            probe_id=probe_id,
            binary=None,
            status=CONFIG,
            detail="no openclaw binary found; set OPENCLAW=/full/path/to/openclaw or put it on PATH",
        )
        path = _write_probe(record)
        print(f"openclaw_probe={record['status']} namespace={namespace} state={path}")
        print(record["detail"], file=sys.stderr)
        return 78

    text = (
        f"paynani OpenClaw probe {namespace}: synthetic dry-run event; "
        "not mail, not from IMAP, not recorded in the paynani journal."
    )
    try:
        run = openclaw_adapter._system_event(binary, text)
    except subprocess.TimeoutExpired:
        record = _result_record(
            probe_id=probe_id,
            binary=binary,
            status=RETRY,
            detail=f"{binary} did not return within {openclaw_adapter.TIMEOUT}s",
        )
        path = _write_probe(record)
        print(f"openclaw_probe={record['status']} namespace={namespace} state={path}")
        print(record["detail"], file=sys.stderr)
        return 75
    except OSError as exc:
        record = _result_record(
            probe_id=probe_id,
            binary=binary,
            status=RETRY,
            detail=f"{binary} could not be run: {exc}",
        )
        path = _write_probe(record)
        print(f"openclaw_probe={record['status']} namespace={namespace} state={path}")
        print(record["detail"], file=sys.stderr)
        return 75

    if run.returncode == 0:
        record = _result_record(
            probe_id=probe_id,
            binary=binary,
            status="accepted",
            detail="openclaw system event accepted the synthetic probe",
            returncode=run.returncode,
            stdout=run.stdout,
            stderr=run.stderr,
        )
        path = _write_probe(record)
        print(f"openclaw_probe=accepted namespace={namespace} state={path}")
        return 0

    detail = _one_line(run.stderr) or _one_line(run.stdout) or "no output"
    record = _result_record(
        probe_id=probe_id,
        binary=binary,
        status=RETRY,
        detail=f"exit {run.returncode}: {detail}",
        returncode=run.returncode,
        stdout=run.stdout,
        stderr=run.stderr,
    )
    path = _write_probe(record)
    print(f"openclaw_probe={record['status']} namespace={namespace} state={path}")
    print(record["detail"], file=sys.stderr)
    return 75
