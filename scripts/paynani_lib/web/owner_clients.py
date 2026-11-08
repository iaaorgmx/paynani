"""
Los clientes web del dueño: PaynaniWebMT y lo que venga después (PaynaniWebMT#2, A1 #719).

Un cliente web administra esta instalación a distancia con la API del dueño
(`/api/owner`). Se empareja como PaynaniApp, con la dirección del túnel y un
código de un solo uso, pero no ocupa el lugar del teléfono: puede haber varios, y
cada uno se revoca por separado.

Dos archivos, junto a `web/user.json`, ambos en modo 600:

    owner_clients.json   un registro por cliente: id, nombre, app, fechas y el
                         SHA-256 del token (el token en claro sólo existe al emparejar)
    owner_pairing.json   el código vigente, como hash, con su vencimiento y los fallos

El código tiene las mismas reglas que el del teléfono (`sms/store.py`): 8
caracteres sin letras confusas, 10 minutos, un solo uso, y 10 códigos equivocados
en 10 minutos bloquean el emparejamiento hasta generar uno nuevo. El tope es
global y no por dirección: detrás del túnel todo llega desde 127.0.0.1.
"""
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
import time
from pathlib import Path

from . import users

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_S = 600
FAIL_WINDOW_S = 600
FAIL_LIMIT = 10
TOKEN_PREFIX = "pw_"
MAX_NAME = 80
MAX_APP = 40
_TOKEN = re.compile(r"pw_[A-Za-z0-9_-]{20,128}")
_CLIENT_ID = re.compile(r"w_[0-9a-f]{8}")


def clients_path(user_file: Path | None = None) -> Path:
    return (Path(user_file) if user_file else users.user_path()).parent / "owner_clients.json"


def _pairing_path(target: Path) -> Path:
    return target.parent / "owner_pairing.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(dt.timezone.utc)).isoformat()


@contextlib.contextmanager
def _locked(target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    with open(target.parent / ".owner_clients.lock", "a", encoding="utf-8") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write(path: Path, data) -> None:
    fd, temporary = tempfile.mkstemp(prefix="." + path.stem + ".", dir=path.parent)
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


def _clients(target: Path) -> list[dict]:
    data = _read(target, [])
    if not isinstance(data, list) or any(not isinstance(item, dict) or not isinstance(item.get("sha256"), str)
                                         for item in data):
        raise ValueError("invalid owner client store")
    return data


# ---- el código ---------------------------------------------------------------

def new_code(*, path: Path | None = None, now: float | None = None) -> str:
    """Un código nuevo. Reemplaza al anterior, y con él se levanta un bloqueo."""
    target = Path(path) if path else clients_path()
    now = time.time() if now is None else now
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    with _locked(target):
        _write(_pairing_path(target), {"code_sha256": _sha256(code), "expires": now + CODE_TTL_S,
                                       "used": False, "fails": [], "blocked": False})
    return code


def _redeem(target: Path, code: str, now: float) -> str:
    """'ok', 'expired' (vencido, usado, equivocado o sin código) o 'blocked'. Llamar con el candado."""
    path = _pairing_path(target)
    pairing = _read(path, None)
    if not isinstance(pairing, dict):
        return "expired"
    fails = [t for t in pairing.get("fails", []) if isinstance(t, (int, float)) and now - t < FAIL_WINDOW_S]
    if pairing.get("blocked") or len(fails) >= FAIL_LIMIT:
        pairing.update(blocked=True, fails=fails)
        _write(path, pairing)
        return "blocked"
    candidate = str(code or "").strip().upper()
    if not hmac.compare_digest(pairing.get("code_sha256", ""), _sha256(candidate)):
        fails.append(now)
        pairing.update(fails=fails, blocked=len(fails) >= FAIL_LIMIT)
        _write(path, pairing)
        return "blocked" if pairing["blocked"] else "expired"
    if pairing.get("used") or now > pairing.get("expires", 0):
        return "expired"
    pairing["used"] = True
    _write(path, pairing)
    return "ok"


def pair(code: str, name: str, *, app_name: str = "", app_version: str = "", ip: str = "",
         path: Path | None = None, now: float | None = None) -> tuple[str, dict | str]:
    """
    Gasta el código y crea el cliente. Devuelve ('ok', (token, registro)) o
    ('expired' | 'blocked', ''). El código queda gastado aunque la respuesta no llegue
    al cliente, igual que con el teléfono.
    """
    target = Path(path) if path else clients_path()
    now = time.time() if now is None else now
    with _locked(target):
        outcome = _redeem(target, code, now)
        if outcome != "ok":
            return outcome, ""
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        stamp = _now_iso(dt.datetime.fromtimestamp(now, dt.timezone.utc))
        record = {"client_id": "w_" + secrets.token_hex(4), "sha256": _sha256(token), "prefix": token[:11],
                  "name": (str(name or "").strip() or "PaynaniWebMT")[:MAX_NAME],
                  "app_name": str(app_name or "")[:MAX_APP], "app_version": str(app_version or "")[:MAX_APP],
                  "paired_at": stamp, "paired_ip": str(ip or "")[:64], "last_used_at": None, "revoked_at": None}
        clients = _clients(target)
        clients.append(record)
        _write(target, clients)
    return "ok", (token, record)


# ---- los clientes --------------------------------------------------------------

def list_clients(*, path: Path | None = None) -> list[dict]:
    target = Path(path) if path else clients_path()
    with _locked(target):
        return _clients(target)


def public(record: dict) -> dict:
    """El registro sin el hash del token, para mostrarlo."""
    return {key: value for key, value in record.items() if key != "sha256"}


def lookup(token: str, *, path: Path | None = None) -> tuple[str, dict | None]:
    """('ok' | 'invalid_token' | 'token_revoked', registro). Nunca acepta un token de agente."""
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return "invalid_token", None
    digest = _sha256(token)
    target = Path(path) if path else clients_path()
    with _locked(target):
        clients = _clients(target)
    record = next((item for item in clients if hmac.compare_digest(item["sha256"], digest)), None)
    if record is None:
        return "invalid_token", None
    if record.get("revoked_at"):
        return "token_revoked", record
    return "ok", record


def revoke(client_id: str, *, path: Path | None = None, now: dt.datetime | None = None) -> dict | None:
    """Revoca un cliente por su id. None si no existe o ya estaba revocado."""
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        return None
    target = Path(path) if path else clients_path()
    with _locked(target):
        clients = _clients(target)
        for record in clients:
            if record.get("client_id") == client_id and not record.get("revoked_at"):
                record["revoked_at"] = _now_iso(now)
                _write(target, clients)
                return record
    return None


def delete(client_id: str, *, path: Path | None = None) -> str:
    """
    Borra una app ya revocada (#769): "deleted", "active" (primero se revoca) o "missing".
    La bitácora de la API no se toca: guarda el prefijo del token, no el registro.
    """
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        return "missing"
    target = Path(path) if path else clients_path()
    with _locked(target):
        clients = _clients(target)
        for index, record in enumerate(clients):
            if record.get("client_id") == client_id:
                if not record.get("revoked_at"):
                    return "active"
                del clients[index]
                _write(target, clients)
                return "deleted"
    return "missing"


def touch(sha256: str, *, path: Path | None = None, now: dt.datetime | None = None) -> None:
    target = Path(path) if path else clients_path()
    with _locked(target):
        clients = _clients(target)
        for record in clients:
            if hmac.compare_digest(record["sha256"], sha256):
                record["last_used_at"] = _now_iso(now)
                _write(target, clients)
                return
