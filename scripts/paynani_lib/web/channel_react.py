"""
Las reacciones del dueño en WhatsApp, Telegram y Webchat (PRD #685 F3): lo que hacían
`_react_post` y `_reactions_get` de PaynaniWeb, sin HTML ni HTTP (PaynaniWebMT PRD #2,
FR-A6; paynani#722).

PaynaniWeb y la API del dueño llaman a `react` y a `thread_reactions`. Quien llama se queda
con lo suyo: si el canal está configurado, los textos y los códigos HTTP.

- `react`: pone o quita («» quita) la reacción del dueño en un mensaje. Sólo si el canal
  reacciona y el `ref` tiene la forma de un mensaje de ese canal; el servicio revisa la
  lista, el hilo y el roster.
- `thread_reactions`: las reacciones de los mensajes más recientes de un hilo, para
  redibujar los globos que cambiaron.
"""
from __future__ import annotations

from . import msgmenu, telegram_pages, telegram_source, webchat_pages, webchat_source, whatsapp_pages, whatsapp_source

CHANNELS = ("whatsapp", "telegram", "webchat")


class ReactError(Exception):
    """La reacción no se puso. `kind` dice de dónde vino:

    - `invalid`: el emoji no es de los que se aceptan;
    - `not_allowed`: el canal no reacciona o el `ref` no es de ese canal;
    - `service`: el servicio de WhatsApp o Telegram dijo que no (`code` es el suyo);
    - `store`: el almacén de Webchat lo rechazó (`code` es el de `Rejected`).
    """

    def __init__(self, code: str, kind: str):
        super().__init__(code)
        self.code = code
        self.kind = kind


def _refs(channel: str) -> tuple:
    from .app import TG_ANY_REF, WA_MESSAGE_ID, WA_SENT_ID, WC_ID
    return {"whatsapp": (WA_MESSAGE_ID, WA_SENT_ID), "telegram": (TG_ANY_REF,), "webchat": (WC_ID,)}[channel]


def react(channel: str, source, ref: str, emoji: str) -> list[dict]:
    """La reacción del dueño en `ref`. `source` es el `Source` del canal, o el almacén de
    Webchat; None si el canal no está configurado. Devuelve las reacciones del mensaje;
    levanta `ReactError`."""
    if not msgmenu.valid_emoji(emoji):
        raise ReactError("invalid_emoji", "invalid")
    if source is None and channel != "webchat":
        raise ReactError("not_allowed", "not_allowed")
    good = any(p.match(ref) for p in _refs(channel))
    if channel == "webchat":
        try:
            if not webchat_pages.reacts(source) or not good:
                raise ReactError("not_allowed", "not_allowed")
            data = source.react(ref, emoji, by="owner") or {}
        except ReactError:
            raise
        except Exception as exc:  # noqa: BLE001 -- el Rejected del almacén de Webchat
            raise ReactError(webchat_source.rejected_code(exc) or "failed", "store") from None
    else:
        try:
            if not good or msgmenu.reactions_allowed(source.status().get("reactions")) is None:
                raise ReactError("not_allowed", "not_allowed")
            data = source.request(f"{channel}.react", ref=ref, emoji=emoji)
        except (telegram_source.Failed, whatsapp_source.Failed) as exc:
            raise ReactError(exc.code, "service") from None
    return [r for r in data.get("reactions") or [] if isinstance(r, dict)]


def thread_reactions(channel: str, source, target: str) -> dict[str, list]:
    """`{ref: [reacciones]}` de los mensajes más recientes del hilo `target` (el número en
    WhatsApp, el `t_…` en Telegram), sin los ocultos. `ReactError("not_allowed")` si el
    hilo no sirve, el canal no está configurado (`source` None), no reacciona o el servicio
    no contesta."""
    from .app import TG_THREAD
    if source is None:
        raise ReactError("not_allowed", "not_allowed")
    try:
        if channel == "telegram":
            if not TG_THREAD.match(target):
                raise ReactError("not_allowed", "not_allowed")
            kind, fields, key = "telegram.thread", {"thread": target, "limit": telegram_pages.THREAD_PAGE}, "ref"
        else:
            if not target:
                raise ReactError("not_allowed", "not_allowed")
            kind, fields, key = "whatsapp.thread", {"number": target, "limit": whatsapp_pages.THREAD_PAGE}, "id"
        if msgmenu.reactions_allowed(source.status().get("reactions")) is None:
            raise ReactError("not_allowed", "not_allowed")
        data = source.request(kind, **fields)
    except (telegram_source.Failed, whatsapp_source.Failed):
        raise ReactError("not_allowed", "not_allowed") from None
    return {str(m.get(key)): m.get("reactions") or [] for m in data.get("messages") or []
            if m.get(key) and not m.get("hidden")}
