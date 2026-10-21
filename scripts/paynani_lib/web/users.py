"""
El usuario de PaynaniWeb (PRD #434 FR-5, FR-6): uno solo, el dueño de la
instalación, creado en el host con `paynani web user add`.

Vive en `<config>/web/user.json`, con modo 600 dentro de una carpeta 700, fuera de
git (`/web/` en .gitignore) y fuera de `state/`, que es lo que junta un
`support-bundle`. Guarda la contraseña sólo como hash `scrypt`, nunca en claro:

    scrypt$<n>$<r>$<p>$<sal en hex>$<hash en hex>

Los parámetros van en la cadena, así que subirlos después no invalida un hash
viejo: se verifica con los suyos.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness"))
import paths  # noqa: E402

# 16 MB de memoria por intento (128 * r * n): por debajo de los 32 MB que OpenSSL
# permite sin `maxmem`, y suficiente para que probar contraseñas fuera de línea
# cueste.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
HASH_BYTES = 64
MIN_PASSWORD = 12     # FR-21, propuesta del PRD; vale igual al crear
MAX_PASSWORD = 1024   # un tope para no hashear un cuerpo entero
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VERSION = 1


class UserError(ValueError):
    """Un dato que no se puede guardar; el mensaje es para la terminal."""


def user_path(environ=None) -> Path:
    """`PAYNANI_WEB_USER` si está (como `PAYNANI_ENV` para el `.env`: las pruebas y un
    host que lo quiera en otro lado), si no `<config>/web/user.json`."""
    environ = os.environ if environ is None else environ
    override = (environ.get("PAYNANI_WEB_USER") or "").strip()
    if override:
        return Path(override).expanduser()
    return paths.config_dir(environ) / "web" / "user.json"


def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=HASH_BYTES)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Compara en tiempo constante. Un hash mal formado nunca deja pasar."""
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        expected = bytes.fromhex(digest)
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(got, expected)


def password_problem(password: str) -> str:
    """Por qué no sirve esta contraseña, o "" si sirve."""
    if len(password) < MIN_PASSWORD:
        return f"the password must have at least {MIN_PASSWORD} characters"
    if len(password) > MAX_PASSWORD:
        return f"the password must have at most {MAX_PASSWORD} characters"
    if password != password.strip():
        return "the password cannot start or end with a space"
    return ""


def load(path: Path | None = None) -> dict | None:
    """El usuario, o None si todavía no existe. Un archivo que no se puede leer
    o no valida también es None: la web vuelve a «crea tu usuario» en lugar de
    dejar entrar con un registro roto."""
    path = user_path() if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("password"), str) \
            or not str(data.get("password", "")).startswith("scrypt$") or not data.get("email"):
        return None
    return data


def exists(path: Path | None = None) -> bool:
    return load(path) is not None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".user.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def create(email: str, name: str, password: str, path: Path | None = None) -> dict:
    """El usuario nuevo. Se niega si ya hay uno (FR-6): para cambiar la contraseña
    está `set_password`."""
    path = user_path() if path is None else Path(path)
    email = (email or "").strip()
    name = (name or "").strip()
    if not EMAIL.match(email):
        raise UserError(f"{email!r} is not an email address")
    if not name:
        raise UserError("a name is needed: it is shown in Profile")
    problem = password_problem(password)
    if problem:
        raise UserError(problem)
    if path.exists():
        if load(path) is None:
            # Sin esto, un archivo roto deja al dueño sin salida: la web pide
            # «crea tu usuario», create() diría «usa passwd» y passwd «no hay usuario».
            raise UserError(f"{path} exists but is not a valid PaynaniWeb user file; move it aside "
                            f"(mv {path} {path}.broken) and run `scripts/paynani web user add` again")
        raise UserError(f"PaynaniWeb already has a user ({path}); change its password with "
                        "`scripts/paynani web passwd`")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data = {"version": VERSION, "email": email, "name": name, "password": hash_password(password),
            "created_at": now, "password_changed_at": now}
    _write(path, data)
    return data


def set_password(password: str, path: Path | None = None) -> dict:
    path = user_path() if path is None else Path(path)
    data = load(path)
    if data is None:
        raise UserError("PaynaniWeb has no user yet; create it with `scripts/paynani web user add`")
    problem = password_problem(password)
    if problem:
        raise UserError(problem)
    data["password"] = hash_password(password)
    data["password_changed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write(path, data)
    return data


def public(data: dict) -> dict:
    """Lo que se puede mostrar: todo menos el hash."""
    return {k: v for k, v in data.items() if k != "password"}
