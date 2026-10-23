"""Per-account listener service control for paynani."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))

from paths import env_file, state_dir  # noqa: E402
from paynani_lib.accounts import ID_PATTERN, MAIN  # noqa: E402

STATES = {"active", "inactive", "failed", "unknown"}


class AccountServiceError(RuntimeError):
    pass


def validate_id(account_id: str) -> str:
    value = (account_id or "").strip()
    if value == MAIN or not ID_PATTERN.fullmatch(value):
        raise AccountServiceError(
            f"account id must match {ID_PATTERN.pattern} and must not be {MAIN!r}"
        )
    return value


def _platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _run(argv: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AccountServiceError(str(exc)) from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise AccountServiceError(f"{' '.join(argv)} failed: {detail}")
    return result


def systemd_unit(account_id: str) -> str:
    return f"paynani-idle@{validate_id(account_id)}.service"


def launchd_label(account_id: str) -> str:
    return f"com.paynani.idle.{validate_id(account_id)}"


def launchd_plist_path(account_id: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{launchd_label(account_id)}.plist"


def _launchd_env(runtime: str | None = None) -> dict[str, str]:
    path_parts = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    return {
        "PAYNANI_RUNTIME": runtime or os.environ.get("PAYNANI_RUNTIME", "auto"),
        "PAYNANI_ENV": str(env_file()),
        "PATH": ":".join(dict.fromkeys(path_parts)),
    }


def launchd_plist(account_id: str, *, python: str | None = None,
                  runtime: str | None = None) -> dict:
    account_id = validate_id(account_id)
    account_state = state_dir() / "accounts" / account_id
    return {
        "Label": launchd_label(account_id),
        "ProgramArguments": [
            python or sys.executable,
            str(ROOT / "scripts" / "idle_listener.py"),
            "--account",
            account_id,
            "--env",
            str(env_file()),
            "--journal",
            str(state_dir() / "events.jsonl"),
        ],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": _launchd_env(runtime),
        "StandardOutPath": str(account_state / "mail.log"),
        "StandardErrorPath": str(account_state / "idle.err.log"),
    }


def _write_plist(path: Path, payload: dict) -> bool:
    old = path.read_bytes() if path.exists() else None
    data = plistlib.dumps(payload, sort_keys=True)
    if old == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o644)
    tmp.replace(path)
    return True


def _launchctl_state(label: str) -> str:
    result = _run(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
    if result.returncode != 0:
        return "inactive"
    text = result.stdout
    if "state = running" in text:
        return "active"
    if "state = crashed" in text:
        return "failed"
    return "inactive"


def _enable_linux(account_id: str) -> str:
    unit = systemd_unit(account_id)
    account_dir = state_dir() / "accounts" / account_id
    account_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(account_dir, 0o700)
    _run(["systemctl", "--user", "daemon-reload"], check=True)
    _run(["systemctl", "--user", "enable", "--now", unit], check=True)
    return state(account_id)


# How long removing an account waits for its listener to stop. systemd allows a unit
# 90 s by default (TimeoutStopSec) before it kills it, so wait a little longer than that.
STOP_WAIT_S = 120
# `systemctl is-active` values that mean the unit has not finished stopping.
_STILL_UP = {"active", "activating", "deactivating", "reloading", "refreshing"}


def _disable_linux(account_id: str, *, sleeper=time.sleep, clock=time.monotonic) -> str:
    """Disable the unit, then stop it and wait for it. One `disable --now` inside _run's
    20 s timeout failed whenever the listener took longer to stop (an IDLE in flight took
    ~25 s), and the account was left half removed (#471). `disable` is immediate; the
    stop is queued with --no-block and waited for here, up to STOP_WAIT_S."""
    unit = systemd_unit(account_id)
    _run(["systemctl", "--user", "disable", unit])
    _run(["systemctl", "--user", "stop", "--no-block", unit])
    deadline = clock() + STOP_WAIT_S
    while True:
        # The raw value: _state_linux maps "deactivating" (exit 3) to "inactive",
        # which would end this wait while the unit is still stopping.
        raw = (_run(["systemctl", "--user", "is-active", unit]).stdout or "").strip()
        if raw not in _STILL_UP:
            break
        if clock() >= deadline:
            # Still stopping: say so. state() would report "inactive" here, and the
            # caller would go on removing the account under a live listener (#473 review).
            raise AccountServiceError(f"{unit} is still {raw} after {STOP_WAIT_S} s")
        sleeper(0.5)
    return state(account_id)


def _state_linux(account_id: str) -> str:
    unit = systemd_unit(account_id)
    result = _run(["systemctl", "--user", "is-active", unit])
    value = (result.stdout or "").strip()
    if value in STATES:
        return value
    if result.returncode == 3:
        return "inactive"
    return "unknown"


def _enable_macos(account_id: str) -> str:
    account_id = validate_id(account_id)
    account_dir = state_dir() / "accounts" / account_id
    account_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(account_dir, 0o700)
    path = launchd_plist_path(account_id)
    payload = launchd_plist(account_id)
    label = launchd_label(account_id)
    if path.exists():
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)])
    _write_plist(path, payload)
    _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
    _run(["launchctl", "enable", f"gui/{os.getuid()}/{label}"], check=True)
    for _ in range(20):
        current = _launchctl_state(label)
        if current == "active":
            return current
        time.sleep(0.25)
    return state(account_id)


def _disable_macos(account_id: str) -> str:
    path = launchd_plist_path(account_id)
    _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)])
    if path.exists():
        path.unlink()
    return state(account_id)


def enable(account_id: str) -> str:
    platform = _platform()
    if platform == "linux":
        if not shutil.which("systemctl"):
            raise AccountServiceError("systemctl not found")
        return _enable_linux(account_id)
    if platform == "macos":
        if not shutil.which("launchctl"):
            raise AccountServiceError("launchctl not found")
        return _enable_macos(account_id)
    raise AccountServiceError(f"unsupported platform: {sys.platform}")


def disable(account_id: str) -> str:
    platform = _platform()
    if platform == "linux":
        return _disable_linux(account_id)
    if platform == "macos":
        return _disable_macos(account_id)
    return "unknown"


def state(account_id: str) -> str:
    platform = _platform()
    if platform == "linux":
        return _state_linux(account_id)
    if platform == "macos":
        return _launchctl_state(launchd_label(account_id))
    return "unknown"
