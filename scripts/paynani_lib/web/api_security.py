"""Private, bounded API audit journal. Never accepts a token or SMS body."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import ipaddress
import json
import os
import re
import tempfile
import time
from pathlib import Path

RETENTION_S = 90 * 86400
PRUNE_INTERVAL_S = 86400
KINDS = frozenset({"call", "invalid_token", "token_revoked", "token_expired",
                   "too_many_attempts", "rate_limited", "quota_exceeded", "opted_out",
                   "forbidden", "internal_error", "daily_quota_alert", "opt_out", "opt_in"})
PREFIX = re.compile(r"pn_[A-Za-z0-9_-]{8}\Z")
REQUEST_ID = re.compile(r"[a-f0-9]{16}\Z")


def safe_prefix(value: str) -> str:
    """Only the public 11-character prefix, even for a malformed bearer value."""
    if not isinstance(value, str):
        return ""
    candidate = value[:11]
    return candidate if PREFIX.fullmatch(candidate) else ""


class Journal:
    def __init__(self, state_dir: Path, clock=time.time):
        self.root = Path(state_dir)
        self.path = self.root / "api_security.jsonl"
        self.lock_path = self.root / ".api_security.lock"
        self.clock = clock
        self._pruned_at = 0.0

    @contextlib.contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        with open(self.lock_path, "a+b") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _rows(self) -> list[dict]:
        try:
            with self.path.open(encoding="utf-8") as stream:
                rows = []
                for line in stream:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
                return rows
        except FileNotFoundError:
            return []

    def _prune(self, now: float) -> None:
        if now - self._pruned_at < PRUNE_INTERVAL_S:
            return
        self._pruned_at = now
        if not self.path.exists():
            return
        rows = [row for row in self._rows() if isinstance(row.get("epoch"), (int, float))
                and row["epoch"] >= now - RETENTION_S]
        fd, temporary = tempfile.mkstemp(prefix=".api_security.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _append(self, kind: str, request_id: str, prefix: str, address: str, now: float) -> None:
        if kind not in KINDS or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("invalid audit event")
        try:
            address = str(ipaddress.ip_address(address))
        except ValueError:
            address = address if isinstance(address, str) and re.fullmatch(r"\+[1-9][0-9]{7,14}", address) else ""
        row = {"at": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(), "epoch": now,
               "kind": kind, "request_id": request_id, "prefix": safe_prefix(prefix), "address": address}
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def record(self, kind: str, request_id: str, prefix: str, address: str) -> None:
        now = self.clock()
        with self._locked():
            self._prune(now)
            self._append(kind, request_id, prefix, address, now)

    def record_once(self, kind: str, request_id: str, prefix: str, address: str,
                    window_s: int = 86400) -> bool:
        """Append once per prefix and rolling window. Return true only for the first."""
        now = self.clock()
        prefix = safe_prefix(prefix)
        with self._locked():
            self._prune(now)
            if any(row.get("kind") == kind and row.get("prefix") == prefix
                   and isinstance(row.get("epoch"), (int, float)) and row["epoch"] > now - window_s
                   for row in self._rows()):
                return False
            self._append(kind, request_id, prefix, address, now)
            return True

    def calls(self, prefix: str) -> dict[str, int]:
        now = self.clock()
        prefix = safe_prefix(prefix)
        with self._locked():
            self._prune(now)
            ages = [now - row["epoch"] for row in self._rows()
                    if row.get("kind") == "call" and row.get("prefix") == prefix
                    and isinstance(row.get("epoch"), (int, float)) and 0 <= now - row["epoch"] < 86400]
        return {"minute": sum(age < 60 for age in ages),
                "hour": sum(age < 3600 for age in ages), "day": len(ages)}
