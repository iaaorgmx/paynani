"""
`whatsapp.env`: si WhatsApp está activado y sus ajustes (PRD #550, WHATSAPP_BRIDGE.md §11).

`configured()` es el único predicado de «WhatsApp configurado». Lo usan el servicio, la
pasarela SMS, PaynaniWeb, `doctor` y el instalador, para que nadie lo decida con su
propia heurística. Es verdadero sólo si `whatsapp.env`, junto a `runtime.env`:

- es un archivo regular, no un enlace simbólico;
- se puede leer como UTF-8;
- cada línea es vacía, un comentario `#` o `NOMBRE=valor`;
- trae `WHATSAPP_ENABLED=1`.

Cualquier otra cosa, incluido un archivo que falta, es «no configurado».
"""
from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

_HARNESS = Path(__file__).resolve().parents[3] / "harness"
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

import paths  # noqa: E402

FILE_NAME = "whatsapp.env"
ENABLED = "WHATSAPP_ENABLED"
_LINE = re.compile(r"^[A-Z][A-Z0-9_]*=.*$")

# Ajustes con su valor por omisión, su mínimo y su máximo (FR-16, FR-21).
DEFAULTS = {
    "WHATSAPP_MAX_MEDIA_MB": (25, 1, 100),
    "WHATSAPP_SEND_INTERVAL_S": (3, 1, 60),
    "WHATSAPP_SEND_PER_DAY": (200, 1, 1000),
}


def env_path(environ=None) -> Path:
    return Path(paths.config_dir(environ=environ)) / FILE_NAME


def read(path: Path | None = None, environ=None) -> dict[str, str] | None:
    """Las claves de `whatsapp.env`, o None si el archivo falta o no sirve (ver arriba)."""
    path = env_path(environ) if path is None else Path(path)
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
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
    """WhatsApp activado en esta instalación: `WHATSAPP_ENABLED=1` en un `whatsapp.env` válido."""
    values = read(path, environ)
    return values is not None and values.get(ENABLED) == "1"


def setting(name: str, values: dict[str, str] | None = None) -> int:
    """Un ajuste entero de DEFAULTS, dentro de su rango; el de omisión si falta o no sirve."""
    default, low, high = DEFAULTS[name]
    try:
        value = int((values or {}).get(name, default))
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default
