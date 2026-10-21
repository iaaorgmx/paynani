"""
El acceso a PaynaniWeb (PRD #434 FR-5 a FR-9).

- **Quién llama.** PaynaniWeb sólo ve 127.0.0.1: todo le llega por la pasarela, y a
  la pasarela por el túnel. La dirección del cliente es entonces el *último* valor
  de `X-Forwarded-For`, el que agregó el túnel; los anteriores los escribió el
  cliente y no valen nada (nota de Metis en #436). Sin el encabezado (alguien en el
  host, o por `ssh -L`), es la del socket.
- **Bloqueo** (FR-7): 5 fallos en 15 minutos desde una dirección la bloquean 15
  minutos. Un intento mientras está bloqueada no se verifica ni cuenta.
- **Sesión** (FR-8): un id de 32 bytes al azar en una cookie `HttpOnly`, `Secure`
  y `SameSite=Strict`, que vence tras 8 horas sin uso. Vive en memoria: reiniciar
  PaynaniWeb cierra todas. Cada sesión recuerda el `password_changed_at` del
  usuario con que se abrió, así que cambiar la contraseña (en el host o en
  Profile) cierra las que había.
- **Direcciones conocidas** (FR-9): la primera entrada desde una dirección nueva le
  avisa al dueño por correo. Se recuerdan en `web/known_ips.json`, junto al usuario.
"""
from __future__ import annotations

import collections
import hmac
import ipaddress
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

from . import users

MAX_FAILURES = 5
FAILURE_WINDOW_S = 15 * 60
LOCK_S = 15 * 60
IDLE_S = 8 * 3600
MAX_KNOWN_IPS = 200
SESSION_COOKIE = "paynani_web_session"
# Para verificar algo aunque el correo no sea el del dueño: así un correo
# equivocado tarda lo mismo que una contraseña equivocada.
_DUMMY_HASH = users.hash_password(secrets.token_hex(16))


def client_ip(headers, peer: str) -> str:
    """El último valor de X-Forwarded-For si es una dirección, si no `peer`."""
    raw = headers.get("X-Forwarded-For", "") if headers is not None else ""
    if raw:
        last = raw.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            pass
    return peer


class Lockout:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.failures: dict[str, collections.deque] = {}
        self.locked_until: dict[str, float] = {}
        self.lock = threading.Lock()

    def remaining(self, ip: str) -> int:
        """Segundos que le faltan al bloqueo de `ip`, o 0."""
        with self.lock:
            until = self.locked_until.get(ip, 0)
            left = until - self.clock()
            if left <= 0:
                self.locked_until.pop(ip, None)
                return 0
            return int(left) + 1

    def fail(self, ip: str) -> bool:
        """Anota un fallo. True si con este queda bloqueada."""
        now = self.clock()
        with self.lock:
            q = self.failures.setdefault(ip, collections.deque())
            q.append(now)
            while q and now - q[0] > FAILURE_WINDOW_S:
                q.popleft()
            if len(q) >= MAX_FAILURES:
                self.locked_until[ip] = now + LOCK_S
                q.clear()
                return True
            return False

    def success(self, ip: str) -> None:
        with self.lock:
            self.failures.pop(ip, None)


class Sessions:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.items: dict[str, dict] = {}
        self.lock = threading.Lock()

    def create(self, ip: str, user: dict, user_agent: str = "") -> str:
        sid = secrets.token_urlsafe(32)
        now = self.clock()
        with self.lock:
            self.items[sid] = {"created": now, "seen": now, "ip": ip, "csrf": secrets.token_urlsafe(32),
                               "pw_at": user.get("password_changed_at", ""), "agent": user_agent[:200]}
        return sid

    def get(self, sid: str, user: dict | None) -> dict | None:
        """La sesión si sigue viva para este usuario, y la marca como usada."""
        if not sid or user is None:
            return None
        now = self.clock()
        with self.lock:
            s = self.items.get(sid)
            if s is None:
                return None
            if now - s["seen"] > IDLE_S or s["pw_at"] != user.get("password_changed_at", ""):
                del self.items[sid]
                return None
            s["seen"] = now
            return dict(s, sid=sid)

    def drop(self, sid: str) -> None:
        with self.lock:
            self.items.pop(sid, None)

    def drop_others(self, keep: str) -> int:
        with self.lock:
            others = [sid for sid in self.items if sid != keep]
            for sid in others:
                del self.items[sid]
            return len(others)

    def rebind(self, sid: str, user: dict) -> None:
        """Después de que esta misma sesión cambió la contraseña: sigue viva."""
        with self.lock:
            if sid in self.items:
                self.items[sid]["pw_at"] = user.get("password_changed_at", "")


def check_csrf(session: dict | None, given: str) -> bool:
    expected = (session or {}).get("csrf", "")
    return bool(expected) and hmac.compare_digest(expected, given or "")


def verify_login(user: dict | None, email: str, password: str) -> bool:
    """Correo (sin importar mayúsculas) y contraseña. Siempre corre scrypt."""
    if user is None:
        users.verify_password(password, _DUMMY_HASH)
        return False
    same_email = hmac.compare_digest((email or "").strip().lower().encode("utf-8"),
                                     str(user.get("email", "")).strip().lower().encode("utf-8"))
    ok = users.verify_password(password, user["password"] if same_email else _DUMMY_HASH)
    return same_email and ok


def known_ips_path(user_file: Path) -> Path:
    return Path(user_file).parent / "known_ips.json"


def remember_ip(user_file: Path, ip: str) -> bool:
    """Anota `ip`. True si era nueva (y hay que avisar, FR-9)."""
    path = known_ips_path(user_file)
    try:
        known = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(known, list):
            known = []
    except (OSError, ValueError):
        known = []
    if ip in known:
        return False
    known = (known + [ip])[-MAX_KNOWN_IPS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".known.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            json.dump(known, fh)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return True
