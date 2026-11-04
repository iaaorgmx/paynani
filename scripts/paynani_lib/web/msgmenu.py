"""
El menú al tocar un mensaje de una conversación (PRD #685, F1: «Copiar»).

Cada página de hilo marca con `data-menu` los renglones que tienen menú (FR-3, FR-4: no los
ocultos, ni los que se están enviando o fallaron) y le pone a la lista los textos del menú.
`assets/msgmenu.js` lo abre al tocar el globo, con clic derecho o con Enter; sin script no
pasa nada y el texto se sigue pudiendo seleccionar.
"""
from __future__ import annotations

from .. import i18n
from .shell import e

SCRIPT = '<script src="/assets/msgmenu.js" defer></script>'


def item(enabled: bool) -> str:
    """Los atributos de un `<li>` con menú: enfocable y con el aviso de que abre un menú."""
    return ' data-menu tabindex="0" aria-haspopup="menu"' if enabled else ""


def list_attrs() -> str:
    """Los textos del menú, en la `<ol>` del hilo, para msgmenu.js (en el idioma de la página)."""
    words = {"label": "label", "copy": "copy", "copied": "copied", "failed": "copy_failed"}
    return "".join(f' data-msgmenu-{name}="{e(i18n.t("web.msgmenu." + key))}"' for name, key in words.items())


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
