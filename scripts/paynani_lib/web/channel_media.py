"""
Las fotos y los documentos de WhatsApp, Telegram y Webchat que el dueño abre o baja: lo
que hacían `_whatsapp_image`, `_telegram_image`, `_download` y el `f_…` de Webchat en
PaynaniWeb, sin HTTP (PaynaniWebMT PRD #2, FR-A6 y FR-A9; paynani#722).

PaynaniWeb y la API del dueño llaman a estas funciones. Quien llama pone los encabezados
(inline o descarga, CSP, caché) y los códigos HTTP.

- `image`: la foto de un mensaje (#573, #662, #670 FR-4). El servicio decide en cada
  pedido (FR-16a, FR-17); el tipo sale de los primeros bytes, otra vez aquí.
- `document`: un documento recibido (#676). Siempre como descarga.
- `webchat_file`: un archivo de Webchat (`f_…`), foto o documento.

Cualquier rechazo (un ref inventado, de fuera del roster, que no es foto, sin archivo o
demasiado grande) es el mismo `MediaError("not_found")`; sólo un servicio caído es
`MediaError("unavailable")`.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from ..whatsapp import media as wa_media
from . import downloads, telegram_source, webchat_source, whatsapp_source

INLINE_IMAGES = ("image/jpeg", "image/png", "image/webp", "image/gif")


class MediaError(Exception):
    """`code` es `not_found` o `unavailable`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Media:
    data: bytes
    mime: str
    name: str = ""
    inline: bool = False


def _decode(data: dict) -> bytes:
    try:
        return base64.b64decode(str(data.get("data") or ""), validate=True)
    except (ValueError, TypeError):
        return b""


def _ask(source, failed, down: tuple[str, ...], kind: str, **fields) -> dict:
    try:
        return source.request(kind, **fields)
    except failed as exc:
        raise MediaError("unavailable" if exc.code in down else "not_found") from None


def image(channel: str, source, ref: str, index: str = "") -> Media:
    """La foto de `ref` en WhatsApp (`wa:…`, o `wo_…` con su índice) o Telegram (`tg:…`, o
    `tgo:…` con su índice)."""
    from .app import TG_FILE_INDEX, TG_OUT_REF, TG_REF, WA_MESSAGE_ID, WA_SENT_ID
    if channel == "whatsapp":
        if not (WA_MESSAGE_ID.match(ref) and not index) and not (WA_SENT_ID.match(ref) and TG_FILE_INDEX.match(index)):
            raise MediaError("not_found")
        fields = {"message_id": ref, **({"index": int(index)} if ref.startswith("wo_") else {})}
        data = _ask(source, whatsapp_source.Failed, ("service_down", "unavailable"), "whatsapp.image", **fields)
    else:
        if not (TG_REF.match(ref) and not index) and not (TG_OUT_REF.match(ref) and TG_FILE_INDEX.match(index)):
            raise MediaError("not_found")
        fields = {"ref": ref, **({"index": int(index)} if ref.startswith("tgo:") else {})}
        data = _ask(source, telegram_source.Failed, ("unavailable",), "telegram.image", **fields)
    body = _decode(data)
    mime = wa_media.image_mime(body[:16])
    if not body or len(body) > wa_media.IMAGE_MAX_BYTES or mime is None:
        raise MediaError("not_found")
    return Media(body, mime, inline=True)


def document(channel: str, source, ref: str) -> Media:
    """El documento recibido `ref` (`wa:…` en WhatsApp, `tg:…` en Telegram), como descarga."""
    from .app import TG_REF, WA_MESSAGE_ID
    if channel == "whatsapp":
        if not WA_MESSAGE_ID.match(ref):
            raise MediaError("not_found")
        data = _ask(source, whatsapp_source.Failed, ("service_down", "unavailable"), "whatsapp.file", message_id=ref)
    else:
        if not TG_REF.match(ref):
            raise MediaError("not_found")
        data = _ask(source, telegram_source.Failed, ("service_down", "unavailable"), "telegram.file", ref=ref)
    body = _decode(data)
    if not body or len(body) > downloads.FILE_MAX_BYTES:
        raise MediaError("not_found")
    return Media(body, "application/octet-stream", str(data.get("name") or ""))


def webchat_file(store, ref: str) -> Media:
    """El archivo `f_…` de Webchat. Las fotos se muestran; lo demás, como descarga."""
    found = store.file_path(ref) if store is not None and webchat_source.REF_RE.match(ref) else None
    if not found:
        raise MediaError("not_found")
    path, mime, name = found
    try:
        data = Path(path).read_bytes()
    except OSError:
        raise MediaError("not_found") from None
    inline = mime in INLINE_IMAGES
    return Media(data, mime if inline else "application/octet-stream", str(name or "archivo"), inline)
