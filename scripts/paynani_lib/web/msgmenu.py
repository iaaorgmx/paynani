"""
El menú al tocar un mensaje de una conversación (PRD #685, F1: «Copiar»).

Cada página de hilo marca con `data-menu` los renglones que tienen menú (FR-3, FR-4: no los
ocultos, ni los que se están enviando o fallaron) y le pone a la lista los textos del menú.
`assets/msgmenu.js` lo abre al tocar el globo, con clic derecho o con Enter; sin script no
pasa nada y el texto se sigue pudiendo seleccionar.

F2 (Responder, FR-6 a FR-9): con un canal que dice `replies: true`, el menú suma
«Responder». La barra de cita va arriba del cuadro y el `reply_to` en un campo oculto del
formulario. La cita se dibuja dentro del globo con `quote()`. El contrato está en #685.

F3 (reacciones, FR-10 a FR-13): con un canal que dice `reactions` («any» o la lista que acepta un
bot de Telegram), el menú trae arriba la fila de 7 reacciones y una flecha al selector. Elegir
una la manda por `react_url` (JSON); las del mensaje se dibujan bajo el globo con `reactions()`.
"""
from __future__ import annotations

import json

from .. import i18n
from .shell import e

SCRIPT = '<script src="/assets/msgmenu.js" defer></script>'


def item(enabled: bool, ref: str = "", name: str = "", actions: bool = True) -> str:
    """Los atributos de un `<li>` con menú: enfocable y con el aviso de que abre un menú. `ref`
    es el id del mensaje en su canal (para «Responder» y para saltar a él desde una cita) y
    `name`, quién lo escribió, para la barra de cita."""
    out = f' data-ref="{e(ref)}"' if ref else ""
    if enabled:
        out += ' data-menu tabindex="0" aria-haspopup="menu"' + (f' data-name="{e(name)}"' if name else "")
        if not actions:   # #707: sin id en el canal no se cita ni se reacciona; sólo «Copiar»
            out += " data-solo-copiar"
    return out


# FR-10: la fila del menú, como Telegram Web.
ROW = ("👍", "👌", "❤️", "👀", "🔥", "😭", "👎")


def list_attrs(reply: bool = False, reactions=None, react_url: str = "", csrf: str = "", poll_url: str = "") -> str:
    """Los textos del menú, en la `<ol>` del hilo, para msgmenu.js (en el idioma de la página).
    Con `reply`, también los de «Responder» (F2); con `reactions` («any» o una lista) y
    `react_url`, los de las reacciones (F3). Sólo lo que el canal permite."""
    words = {"label": "label", "copy": "copy", "copied": "copied", "failed": "copy_failed"}
    if reply:
        words.update({"reply": "reply", "replying": "replying", "remove": "remove_quote", "hidden": "hidden_quote",
                      "notloaded": "not_loaded"})
    out = "".join(f' data-msgmenu-{name}="{e(i18n.t("web.msgmenu." + key))}"' for name, key in words.items())
    allowed = reactions_allowed(reactions)
    if allowed is not None and react_url:
        texts = {"more": "more", "reactwith": "react_with", "search": "search", "tgnote": "tg_note",
                 "pickertitle": "picker_title", "close": "close", "reactfailed": "react_failed"}
        out += "".join(f' data-msgmenu-{name}="{e(i18n.t("web.msgmenu." + key))}"' for name, key in texts.items())
        out += (f' data-msgmenu-react="{e(json.dumps(allowed, ensure_ascii=False))}"'
                f' data-msgmenu-react-url="{e(react_url)}" data-msgmenu-csrf="{e(csrf)}"')
        if poll_url:   # Telegram y WhatsApp: las reacciones que llegan se ven sin recargar
            out += f' data-msgmenu-poll="{e(poll_url)}"'
    return out


def reactions_allowed(value):
    """Lo que el canal acepta (FR-10): "any", una lista de emojis, o None si no reacciona."""
    if value == "any":
        return "any"
    if isinstance(value, list):
        clean = [str(x) for x in value if isinstance(x, str) and valid_emoji(x)]
        return clean or None
    return None


def valid_emoji(value: str) -> bool:
    """Un emoji, o nada (quitar la nuestra): hasta 16 caracteres, sin letras, espacios ni marcas
    de HTML. La lista exacta la revisa el servicio (FR-14)."""
    if not isinstance(value, str) or len(value) > 16:
        return False
    return all(ord(c) >= 0x2000 or c in "#*0123456789" for c in value)


def reactions(items) -> str:
    """Las reacciones bajo el globo (FR-12): un botón por emoji, con cuántas si son más de una,
    y la nuestra resaltada (`aria-pressed`). msgmenu.js las usa para quitar o sumar la nuestra."""
    if not isinstance(items, list) or not items:
        return ""
    out = []
    for r in items:
        if not isinstance(r, dict) or not valid_emoji(str(r.get("emoji") or "")) or not r.get("emoji"):
            continue
        n = r.get("count") if isinstance(r.get("count"), int) else 1
        mine = bool(r.get("mine"))
        out.append(f'<button type="button" class="reac{" reac-mia" if mine else ""}" data-emoji="{e(r["emoji"])}"'
                   f' aria-pressed="{"true" if mine else "false"}">{e(r["emoji"])}'
                   + (f"<small>{n}</small>" if n > 1 else "") + "</button>")
    return f'<div class="reacciones">{"".join(out)}</div>' if out else ""


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
