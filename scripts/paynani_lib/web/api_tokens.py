"""Local API token store. Cleartext tokens exist only at creation and in requests."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

from . import users


def path_for(user_file: Path | None = None) -> Path:
    return (Path(user_file) if user_file else users.user_path()).parent / "api_tokens.json"


@contextlib.contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with open(path.parent / ".api_tokens.lock", "a", encoding="utf-8") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _read(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(data, list) or any(not isinstance(item, dict) or
                                         not isinstance(item.get("sha256"), str) for item in data):
        raise ValueError("invalid API token store")
    return data


def _write(path: Path, data: list[dict]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".api_tokens.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create(name: str, *, expires_at: str | None = None, permissions=(), limits=None,
           agent_replies: bool = False,
           path: Path | None = None, now: dt.datetime | None = None) -> tuple[str, dict]:
    """Called by the future owner-only token screen; return the secret once."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("token name is required")
    if expires_at is not None:
        expiry = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("expiry needs a timezone")
    now = now or dt.datetime.now(dt.timezone.utc)
    secret = "pn_" + secrets.token_urlsafe(32)
    record = {"sha256": hashlib.sha256(secret.encode("ascii")).hexdigest(),
              "prefix": secret[:11], "name": name.strip(), "permissions": list(permissions),
              "limits": limits or {"sms_per_hour": 30, "sms_per_day": 200},
              "agent_replies": bool(agent_replies), "created_at": now.isoformat(), "expires_at": expires_at,
              "revoked_at": None, "last_used_at": None}
    target = Path(path) if path else path_for()
    with _locked(target):
        data = _read(target)
        data.append(record)
        _write(target, data)
    return secret, record


def migrate_catchall_write(*, path: Path | None = None) -> list[dict]:
    """
    PRD #576 FR-13a: el permiso viejo `catchall.write` pasa a `catchall.sms.write`, el
    más estrecho. Reescribe el archivo una vez y devuelve los tokens que cambiaron
    (`name`, `prefix`), para el correo al dueño. Sin nada que cambiar, no escribe.
    """
    target = Path(path) if path else path_for()
    if not target.exists():
        return []
    changed = []
    with _locked(target):
        records = _read(target)
        for record in records:
            perms = record.get("permissions") or []
            if "catchall.write" not in perms:
                continue
            new = [p for p in perms if p != "catchall.write"]
            if "catchall.sms.write" not in new:
                new.append("catchall.sms.write")
            record["permissions"] = new
            changed.append({"name": record.get("name", ""), "prefix": record.get("prefix", "")})
        if changed:
            _write(target, records)
    return changed


def list_records(*, path: Path | None = None) -> list[dict]:
    target = Path(path) if path else path_for()
    with _locked(target):
        return _read(target)


def update(sha256: str, *, path: Path | None = None, agent_replies: bool | None = None,
           revoke: bool = False, now: dt.datetime | None = None) -> dict | None:
    """Update a token by digest. Never returns or recreates its cleartext secret."""
    target = Path(path) if path else path_for()
    with _locked(target):
        records = _read(target)
        for record in records:
            if hmac.compare_digest(record["sha256"], sha256):
                if record.get("revoked_at"):
                    return None
                if agent_replies is not None:
                    record["agent_replies"] = bool(agent_replies)
                if revoke:
                    record["revoked_at"] = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
                _write(target, records)
                return record
    return None


def lookup(secret: str, *, path: Path | None = None,
           now: dt.datetime | None = None) -> tuple[str, dict | None]:
    if not isinstance(secret, str) or not re.fullmatch(r"pn_[A-Za-z0-9_-]{20,128}", secret):
        return "invalid_token", None
    digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
    target = Path(path) if path else path_for()
    with _locked(target):
        records = _read(target)
    record = next((item for item in records if hmac.compare_digest(item["sha256"], digest)), None)
    if record is None:
        return "invalid_token", None
    if record.get("revoked_at"):
        return "token_revoked", record
    if record.get("expires_at"):
        expiry = dt.datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
        if expiry <= (now or dt.datetime.now(dt.timezone.utc)):
            return "token_expired", record
    return "ok", record


def get_record(sha256: str, *, path: Path | None = None) -> dict | None:
    """Read current metadata by digest without exposing the cleartext token."""
    target = Path(path) if path else path_for()
    with _locked(target):
        return next((item for item in _read(target)
                     if hmac.compare_digest(item["sha256"], sha256)), None)


def touch(sha256: str, *, path: Path | None = None, now: dt.datetime | None = None) -> None:
    target = Path(path) if path else path_for()
    with _locked(target):
        records = _read(target)
        for item in records:
            if hmac.compare_digest(item["sha256"], sha256):
                item["last_used_at"] = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
                _write(target, records)
                return
