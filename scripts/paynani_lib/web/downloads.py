"""
Los documentos recibidos por WhatsApp y Telegram en PaynaniWeb (#676): cómo se ven en el
hilo y cómo se descargan. Lo comparten whatsapp_pages, telegram_pages y app.py.

- `row(href, name, size, kind_label)`: el documento en el globo, «📄 nombre · 1.6 MB», con
  el enlace a la descarga. Sin nombre queda el tipo, como antes; de más de FILE_MAX_BYTES
  queda el nombre sin enlace.
- `headers(name)`: la descarga siempre como archivo y nunca en la página, así un `.html` o
  un `.svg` que alguien mande no corre en el origen de PaynaniWeb.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from .shell import e, icon

# El mismo tope que el servicio (whatsapp.media.FILE_MAX_BYTES, telegram.outbound.FILE_MAX_BYTES):
# en base64 por control.sock son ~27 MB en una línea.
FILE_MAX_BYTES = 20 * 1024 * 1024
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\"]')


def size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def safe_name(name: str) -> str:
    """Sin `/`, `\\`, comillas ni caracteres de control; sin puntos al principio."""
    clean = _UNSAFE.sub("_", str(name or "")).strip().lstrip(".")[:150]
    return clean or "archivo"


def row(href: str, name: str, nbytes, kind_label: str) -> str:
    try:
        n = int(nbytes or 0)
    except (TypeError, ValueError):
        n = 0
    if not name:
        return kind_label
    label = f'{icon("file")}<span><b>{e(name)}</b>{f" <small>{e(size(n))}</small>" if n else ""}</span>'
    if n > FILE_MAX_BYTES:
        return f'<span class="tg-archivo">{label}</span>'
    return f'<a class="tg-archivo" href="{e(href)}" download>{label}</a>'


def headers(name: str) -> list[tuple[str, str]]:
    clean = safe_name(name)
    ascii_name = clean.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return [("Content-Disposition", f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(clean, safe="")}'),
            ("Content-Security-Policy", "default-src 'none'; sandbox")]
