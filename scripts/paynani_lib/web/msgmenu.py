"""
El menú al tocar un mensaje de una conversación (PRD #685, F1: «Copiar»).

Cada página de hilo marca con `data-menu` los renglones que tienen menú (FR-3, FR-4: no los
ocultos, ni los que se están enviando o fallaron) y le pone a la lista los textos del menú.
`assets/msgmenu.js` lo abre al tocar el globo, con clic derecho o con Enter; sin script no
pasa nada y el texto se sigue pudiendo seleccionar.

F2 (Responder, FR-6 a FR-9): con un canal que dice `replies: true`, el menú suma
«Responder». La barra de cita va arriba del cuadro y el `reply_to` en un campo oculto del
formulario. La cita se dibuja dentro del globo con `quote()`. El contrato está en #685.
"""
from __future__ import annotations

from .. import i18n
from .shell import e

SCRIPT = '<script src="/assets/msgmenu.js" defer></script>'


def item(enabled: bool, ref: str = "", name: str = "") -> str:
    """Los atributos de un `<li>` con menú: enfocable y con el aviso de que abre un menú. `ref`
    es el id del mensaje en su canal (para «Responder» y para saltar a él desde una cita) y
    `name`, quién lo escribió, para la barra de cita."""
    out = f' data-ref="{e(ref)}"' if ref else ""
    if enabled:
        out += ' data-menu tabindex="0" aria-haspopup="menu"' + (f' data-name="{e(name)}"' if name else "")
    return out


def list_attrs(reply: bool = False) -> str:
    """Los textos del menú, en la `<ol>` del hilo, para msgmenu.js (en el idioma de la página).
    Con `reply`, también los de «Responder» (F2): sólo si el canal lo permite."""
    words = {"label": "label", "copy": "copy", "copied": "copied", "failed": "copy_failed"}
    if reply:
        words.update({"reply": "reply", "replying": "replying", "remove": "remove_quote", "hidden": "hidden_quote",
                      "notloaded": "not_loaded"})
    return "".join(f' data-msgmenu-{name}="{e(i18n.t("web.msgmenu." + key))}"' for name, key in words.items())


def quote(reply_to) -> str:
    """La cita dentro del globo de un mensaje que es respuesta (FR-8, FR-9). `reply_to` es
    `{ref, name, excerpt, missing}` del canal, o None. Un original oculto no deja ver su texto
    (`name`/`excerpt` en null); uno anterior a la instalación (`ref` null) no lleva a ningún lado;
    `missing` dice que el canal la mandó sin cita (FR-7)."""
    if not isinstance(reply_to, dict):
        return ""
    ref = str(reply_to.get("ref") or "")
    name = reply_to.get("name")
    excerpt = reply_to.get("excerpt")
    if name is None and excerpt is None:
        who, text = "", i18n.t("web.msgmenu.hidden_quote")
    else:
        who, text = str(name or ""), " ".join(str(excerpt or "").split())[:100]
    missing = (f'<small class="cita-perdida">{e(i18n.t("web.msgmenu.quote_missing"))}</small>'
               if reply_to.get("missing") else "")
    inner = (f'<b>{e(who)}</b>' if who else "") + f'<span>{e(text)}</span>' + missing
    if ref:
        return f'<a class="cita" href="#" data-cita="{e(ref)}">{inner}</a>'
    return f'<span class="cita">{inner}</span>'


def reply_field(enabled: bool, value: str = "") -> str:
    """El campo oculto `reply_to` del formulario de responder (FR-7). msgmenu.js lo llena al
    elegir «Responder» y lo vacía con la ✕; después de un error, vuelve con lo que traía."""
    return f'<input type="hidden" name="reply_to" value="{e(value)}">' if enabled else ""


# Los estados que todavía no son un mensaje entregado (FR-4), por canal.
NOT_YET = {
    "telegram": {"sending", "failed"},
    "whatsapp": {"sending", "failed"},
    "sms": {"queued", "accepted", "failed", "rejected", "expired"},
}


def has_menu(channel: str, message: dict) -> bool:
    """Si el mensaje lleva menú: no oculto (fuera del roster sin Catch-All) y, si salió de aquí,
    ya enviado."""
    if message.get("hidden"):
        return False
    return str(message.get("status") or "") not in NOT_YET.get(channel, set())
