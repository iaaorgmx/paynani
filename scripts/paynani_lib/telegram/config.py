"""
`telegram.env`: si Telegram está activado, su token y sus ajustes (PRD #609, TELEGRAM.md §4).

`configured()` es el único predicado de «Telegram configurado». Es verdadero sólo si
`telegram.env`, junto a `runtime.env`:

- es un archivo regular, no un enlace simbólico, sin permisos para el grupo ni otros;
- se puede leer como UTF-8;
- cada línea es vacía, un comentario `#` o `NOMBRE=valor`;
- trae `TELEGRAM_ENABLED=1` y un `TELEGRAM_TOKEN` con forma de token.

El token nunca se imprime ni se registra (FR-8). `token()` lo devuelve para la Bot API
y nada más.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

_HARNESS = Path(__file__).resolve().parents[3] / "harness"
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

import paths  # noqa: E402

FILE_NAME = "telegram.env"
ENABLED = "TELEGRAM_ENABLED"
TOKEN = "TELEGRAM_TOKEN"
API_ENV = "PAYNANI_TELEGRAM_API"        # sólo pruebas: la base del servidor falso (TELEGRAM.md §9)
DEFAULT_API = "https://api.telegram.org"
_LINE = re.compile(r"^[A-Z][A-Z0-9_]*=.*$")
TOKEN_RE = re.compile(r"^[0-9]{3,20}:[A-Za-z0-9_-]{20,100}$")

# Ajustes con su valor por omisión, su mínimo y su máximo (FR-18, FR-26).
DEFAULTS = {
    "TELEGRAM_MAX_MEDIA_MB": (20, 1, 20),
    "TELEGRAM_SEND_PER_DAY": (300, 1, 5000),
    "TELEGRAM_SEND_INTERVAL_S": (1, 1, 60),
}


def env_path(environ=None) -> Path:
    return Path(paths.config_dir(environ=environ)) / FILE_NAME


def read(path: Path | None = None, environ=None) -> dict[str, str] | None:
    """Las claves de `telegram.env`, o None si el archivo falta o no sirve (ver arriba)."""
    path = env_path(environ) if path is None else Path(path)
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            text = fh.read(64 * 1024)
    except (OSError, UnicodeDecodeError):
        return None
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _LINE.match(line):
            return None
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def configured(path: Path | None = None, environ=None) -> bool:
    values = read(path, environ)
    return (values is not None and values.get(ENABLED) == "1"
            and bool(TOKEN_RE.match(values.get(TOKEN, ""))))


def token(values: dict[str, str] | None) -> str | None:
    value = (values or {}).get(TOKEN, "")
    return value if TOKEN_RE.match(value) else None


def setting(name: str, values: dict[str, str] | None = None) -> int:
    default, low, high = DEFAULTS[name]
    try:
        value = int((values or {}).get(name, default))
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


def api_base(environ=None) -> str:
    env = os.environ if environ is None else environ
    return (env.get(API_ENV) or DEFAULT_API).rstrip("/")


def bot_dir_name(bot_id: int) -> str:
    """El nombre de la carpeta de un bot (FR-3a): un prefijo del hash, nunca el id."""
    return hashlib.sha256(f"paynani-telegram-bot:{int(bot_id)}".encode()).hexdigest()[:16]


BACKUP_NAME = "telegram.env.bak"


def _write_private(path: Path, text: str) -> None:
    """Escribe completo o nada, 0600, sin seguir un enlace (archivo temporal, fsync, replace)."""
    path = Path(path)
    if path.is_symlink():
        raise OSError(f"{path.name} es un enlace simbólico")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-telegram-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def render(values: dict[str, str]) -> str:
    lines = ["# paynani-telegram (PRD #609). Lo escribe `paynani telegram setup`; 0600.",
             "# El token nunca se copia a otro archivo, a un log ni a la línea de comandos."]
    for name in sorted(values):
        value = str(values[name])
        if "\n" in value or not _LINE.match(f"{name}={value}"):
            raise ValueError(f"valor inválido para {name}")
        lines.append(f"{name}={value}")
    return "\n".join(lines) + "\n"


def write(values: dict[str, str], path: Path | None = None, environ=None) -> Path:
    """`telegram.env` con estas claves, completo o nada, en 0600 (FR-8)."""
    path = env_path(environ) if path is None else Path(path)
    _write_private(path, render(values))
    return path


def backup_path(path: Path | None = None, environ=None) -> Path:
    path = env_path(environ) if path is None else Path(path)
    return path.with_name(BACKUP_NAME)


def save_backup(path: Path | None = None, environ=None) -> Path | None:
    """Copia el `telegram.env` actual a `telegram.env.bak` (0600) antes de cambiar el token (FR-10 paso 3)."""
    values = read(path, environ)
    if values is None:
        return None
    target = backup_path(path, environ)
    _write_private(target, render(values))
    return target


def with_token(values: dict[str, str] | None, new_token: str) -> dict[str, str]:
    if not TOKEN_RE.match(new_token or ""):
        raise ValueError("el token no tiene la forma de un token de bot")
    out = dict(values or {})
    out[ENABLED] = "1"
    out[TOKEN] = new_token
    return out
