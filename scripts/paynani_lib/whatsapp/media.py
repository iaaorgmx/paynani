"""
Las fotos de WhatsApp que PaynaniWeb puede mostrar (#573).

Lo usan el servicio (store.read_image) y PaynaniWeb (/whatsapp/media), que lo vuelve a
revisar. Por eso upgrade_plan.py reinicia los dos cuando cambia este archivo.
"""
from __future__ import annotations

IMAGE_MAX_BYTES = 10 * 1024 * 1024
# #676: un documento recibido que PaynaniWeb deja descargar. En base64 por control.sock son
# ~27 MB en una línea; la web pone el mismo tope (whatsapp_source.FILE_MAX_BYTES).
FILE_MAX_BYTES = 20 * 1024 * 1024


def image_mime(head: bytes) -> str | None:
    """El tipo de una imagen por sus primeros bytes, nunca por la extensión."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None
