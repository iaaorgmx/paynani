"""
Restart a mail listener from PaynaniWeb and tell when it is back (#591, N3;
W2 of #590 calls it after saving the mailbox settings).

No CLI: only the web calls this, and it runs as the same user as the services,
so `systemctl --user` on Linux and `launchctl` on macOS are enough. Nothing uses
sudo, and the only thing it can restart is a paynani listener: the unit or label
comes from a fixed name or from account_service, never from the caller.

The listener writes its heartbeat to idle.json as soon as it is in the mailbox
("listening on ..."), not only on the five-minute IDLE, and records which
account it is reading. So "back" means: a heartbeat with heartbeat_at at or
after the restart, from the expected account. When the server rejects the
password the listener records imap_last_login_error in the same file without
touching the heartbeat, and it comes back here as last_error.
"""

from __future__ import annotations

import calendar
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_HARNESS = Path(__file__).resolve().parents[2] / "harness"
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

from paths import state_dir  # noqa: E402

from . import account_service  # noqa: E402

MAIN_UNIT = "paynani-idle.service"
MAIN_LABEL = "com.paynani.idle"
# healthcheck.py's STALE_LISTENER_HEARTBEAT: every IDLE renews the heartbeat.
STALE_S = 15 * 60
POLL_S = 1.0


@dataclass
class Restart:
    ok: bool
    code: str            # "requested" | "unknown_account" | "no_service_manager" | "failed"
    requested_at: str    # ISO 8601 UTC; pass it to status(since=...)
    previous_pid: int | None
    detail: str = ""


@dataclass
class Status:
    state: str           # "connected" | "waiting" | "stale" | "unknown"
    heartbeat_at: str = ""
    pid: int | None = None
    mailbox: str = ""
    account: str = ""    # the address the listener is reading, as it recorded it
    last_error: str = ""
    detail: str = ""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _seconds(stamp) -> int | None:
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def _platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def state_path(account: str | None = None) -> Path:
    """idle.json of the main listener, or of an additional account's."""
    if account is None:
        return state_dir() / "idle.json"
    return state_dir() / "accounts" / account_service.validate_id(account) / "idle.json"


def _read_state(account: str | None) -> dict:
    try:
        data = json.loads(state_path(account).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def _command(account: str | None) -> list[str] | None:
    platform = _platform()
    if platform == "linux":
        unit = MAIN_UNIT if account is None else account_service.systemd_unit(account)
        return ["systemctl", "--user", "restart", unit]
    if platform == "macos":
        label = MAIN_LABEL if account is None else account_service.launchd_label(account)
        return ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"]
    return None


def restart(account: str | None = None) -> Restart:
    """
    Ask for the restart and return without waiting for the listener to come
    back. requested_at is taken after the service manager has stopped the old
    process (`systemctl restart` and `kickstart -k` both stop first), so any
    heartbeat at or after it comes from the new one.
    """
    try:
        if account is not None:
            account_service.validate_id(account)
    except account_service.AccountServiceError as exc:
        return Restart(False, "unknown_account", "", None, str(exc))
    previous = _read_state(account)
    previous_pid = previous.get("pid") if isinstance(previous.get("pid"), int) else None

    argv = _command(account)
    if argv is None:
        return Restart(False, "no_service_manager", "", previous_pid,
                       f"cannot restart services on {sys.platform}")
    try:
        result = _run(argv)
    except FileNotFoundError:
        return Restart(False, "no_service_manager", "", previous_pid, f"{argv[0]} is not installed")
    except (OSError, subprocess.SubprocessError) as exc:
        return Restart(False, "failed", "", previous_pid, str(exc))
    requested_at = _now()
    if result.returncode != 0:
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        return Restart(False, "failed", requested_at, previous_pid,
                       lines[-1] if lines else f"{argv[0]} exited {result.returncode}")
    return Restart(True, "requested", requested_at, previous_pid)


def status(account: str | None = None, *, since: str | None = None, expect: str | None = None,
           previous_pid: int | None = None, now: float | None = None) -> Status:
    """
    With since: "connected" once there is a heartbeat at or after since, from a
    process other than previous_pid and from the expected address when those are
    given, with no login or connection error after it; "waiting" until then,
    carrying that error in last_error.
    Without since: "connected" if the heartbeat is recent, "stale" if not.
    """
    try:
        data = _read_state(account)
    except account_service.AccountServiceError as exc:
        return Status("unknown", detail=str(exc))
    if not data:
        return Status("waiting" if since else "unknown", detail="no heartbeat yet")

    heartbeat_at = data.get("heartbeat_at") or ""
    pid = data.get("pid") if isinstance(data.get("pid"), int) else None
    mailbox = data.get("mailbox") or ""
    reading = data.get("account") or ""
    heartbeat = _seconds(heartbeat_at)
    base = dict(heartbeat_at=heartbeat_at, pid=pid, mailbox=mailbox, account=reading)

    if since is not None:
        floor = _seconds(since)
        if floor is None:
            return Status("unknown", **base, detail=f"since is not a timestamp: {since!r}")
        last_error = ""
        for at_key, error_key in (("imap_last_login_error_at", "imap_last_login_error"),
                                  ("imap_last_disconnect_at", "imap_last_disconnect_error")):
            at = _seconds(data.get(at_key))
            # An error counts only if it is newer than the request and than the
            # last heartbeat: a listener that failed once and then got in is back.
            if at is not None and at >= floor and (heartbeat is None or at >= heartbeat):
                last_error = data.get(error_key) or ""
                break
        fresh = heartbeat is not None and heartbeat >= floor and (previous_pid is None or pid != previous_pid)
        right_account = expect is None or reading.lower() == expect.strip().lower()
        if fresh and right_account and not last_error:
            return Status("connected", **base)
        if fresh and not right_account:
            return Status("waiting", **base, last_error=last_error,
                          detail=f"the listener is reading {reading or 'an unknown account'}, not {expect}")
        return Status("waiting", **base, last_error=last_error, detail="the listener is not connected yet")

    if heartbeat is None:
        return Status("unknown", **base, detail="idle.json has no heartbeat")
    age = (time.time() if now is None else now) - heartbeat
    if age > STALE_S:
        return Status("stale", **base, detail=f"last heartbeat {int(age // 60)} min ago")
    return Status("connected", **base)


def wait(since: str, account: str | None = None, timeout_s: float = 60, *, expect: str | None = None,
         previous_pid: int | None = None, sleep=time.sleep, clock=time.monotonic) -> Status:
    """status(since=...) until it says "connected" or timeout_s runs out."""
    deadline = clock() + timeout_s
    current = status(account, since=since, expect=expect, previous_pid=previous_pid)
    while current.state != "connected" and clock() < deadline:
        sleep(POLL_S)
        current = status(account, since=since, expect=expect, previous_pid=previous_pid)
    return current
