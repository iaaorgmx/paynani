"""
Enviar por WhatsApp o Telegram como el dueño, con cita y archivos: lo que hacían los
handlers de PaynaniWeb, sin HTML (PaynaniWebMT PRD #2, FR-A6; paynani#722).

PaynaniWeb y la API del dueño llaman a `send`. Quien llama se queda con lo suyo: leer el
formulario o el JSON, los textos y los códigos HTTP.

El flujo, igual en los dos canales:

1. La cita (`reply_to`) sólo va si tiene forma de mensaje del canal y el servicio cita
   (`replies` en su estado, PRD #685 F2). Si no, el envío es el de siempre: un núcleo
   viejo no recibe un campo que no conoce.
2. Hace falta texto o archivos, y el texto no pasa del tope del canal.
3. Los archivos van primero al núcleo (#662, #670 FR-5): `uploads.save` los revisa por
   los bytes y da un `up_…` de un solo uso. Quien llama nunca elige una ruta.
4. El envío. Si falla:
   - con archivos, un corte por tiempo no dice si salieron (`unknown`): no se invita a
     mandarlos otra vez sin revisar el hilo;
   - un envío parcial (#667) dice cuáles salieron (`sent`);
   - un fallo definitivo borra ya los que no salieron, para no llenar los pendientes con
     reintentos (revisión de Metis en #666).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class SendError(Exception):
    """El envío no salió. `code` es el del canal (o de `uploads.Rejected`), `fields` lo que
    trajo el servicio, `sent` los nombres de los archivos que sí salieron y `unknown` si
    no se sabe si salió (un corte por tiempo con archivos)."""

    def __init__(self, code: str, fields: dict | None = None, *, sent: list[str] | None = None,
                 unknown: bool = False):
        super().__init__(code)
        self.code = code
        self.fields = fields or {}
        self.sent = sent or []
        self.unknown = unknown


@dataclass(frozen=True)
class Channel:
    """Lo que cambia entre canales. `failed` es la excepción del `Source` del canal y
    `timeout_codes` los códigos de error que, con archivos, cuentan como corte por tiempo."""
    kind: str                       # "whatsapp.send" o "telegram.send"
    uploads: object                 # el módulo con save, drop, MAX_FILES y Rejected
    max_text: int
    reply_refs: tuple[re.Pattern, ...]
    failed: type
    timeout_codes: tuple[str, ...] = field(default=())


def whatsapp() -> Channel:
    from .. import web_uploads
    from . import whatsapp_source
    from .app import WA_MESSAGE_ID, WA_SENT_ID
    return Channel("whatsapp.send", web_uploads, whatsapp_source.MAX_TEXT, (WA_MESSAGE_ID, WA_SENT_ID),
                   whatsapp_source.Failed, ("timeout",))


def telegram() -> Channel:
    from ..telegram import uploads as tg_uploads
    from . import telegram_source
    from .app import TG_ANY_REF
    return Channel("telegram.send", tg_uploads, telegram_source.MAX_TEXT, (TG_ANY_REF,), telegram_source.Failed)


def send(channel: Channel, source, root: Path, target: dict, text: str, files: list[dict],
         reply_to: str = "") -> dict:
    """Manda `text` y `files` (`[{"name", "data"}]`) a `target` (`{"number": …}` o
    `{"thread": …}`) por `source`. `root` es la carpeta del canal en el estado. Devuelve lo
    que contestó el servicio; levanta `SendError`."""
    text = text.replace("\r\n", "\n")
    extra = ({"reply_to": reply_to} if any(p.match(reply_to) for p in channel.reply_refs)
             and source.status().get("replies") is True else {})
    files = files[:channel.uploads.MAX_FILES + 1]
    if (not text.strip() and not files) or len(text) > channel.max_text:
        raise SendError("invalid", {"field": "text"})
    ups, names = [], {}
    try:
        if len(files) > channel.uploads.MAX_FILES:
            raise channel.uploads.Rejected("too_many")
        for f in files:
            saved = channel.uploads.save(root, f["name"][:200], f["data"])
            ups.append(saved["upload"])
            names[saved["upload"]] = saved["name"]
    except channel.uploads.Rejected as exc:
        for ref in ups:
            channel.uploads.drop(root, ref)
        raise SendError(exc.code) from None
    try:
        if ups:
            return source.request_slow(channel.kind, **target, text=text, uploads=ups, **extra) or {}
        return source.request(channel.kind, **target, text=text, **extra) or {}
    except channel.failed as exc:
        unknown = bool(ups) and (exc.code in channel.timeout_codes or bool(exc.fields.get("timed_out")))
        done = exc.fields.get("sent_uploads") or []
        if ups and not unknown:
            for ref in ups:
                if ref not in set(done):
                    channel.uploads.drop(root, ref)
        raise SendError(exc.code, exc.fields, sent=[names[u] for u in done if u in names],
                        unknown=unknown) from None
