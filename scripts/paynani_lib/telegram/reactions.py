"""
Las reacciones de Telegram (PRD #685 F3, contrato de FR-14 en #685).

Un bot sólo puede poner las reacciones estándar de Telegram (`ReactionTypeEmoji` de la Bot
API), una por mensaje. `BOT_REACTIONS` es esa lista, en la forma exacta que pide la API.
`telegram.status` la manda a la web en su forma para mostrar (con el selector de variación
U+FE0F donde un emoji lo necesita para no verse como texto, p. ej. «❤️»), y el servicio
acepta las dos formas (Iris en #685: se compara sin U+FE0F).
"""
from __future__ import annotations

_VS16 = "️"

# La lista de la Bot API (ReactionTypeEmoji.emoji), en su orden.
BOT_REACTIONS = (
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩",
    "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆",
    "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈",
    "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄",
    "😘", "💊", "🙊", "😎", "👾", "🤷‍♂", "🤷", "🤷‍♀", "😡",
)

# Los que sin U+FE0F se dibujan como texto: su forma para mostrar.
_DISPLAY = {"❤": "❤️", "🕊": "🕊️", "❤‍🔥": "❤️‍🔥", "✍": "✍️", "☃": "☃️",
            "🤷‍♂": "🤷‍♂️", "🤷‍♀": "🤷‍♀️"}


def key(emoji: str) -> str:
    """El emoji sin U+FE0F, para comparar."""
    return str(emoji or "").replace(_VS16, "")


_BY_KEY = {key(e): e for e in BOT_REACTIONS}


def api_form(emoji: str) -> str | None:
    """La forma que pide la Bot API, o None si un bot no puede usar ese emoji."""
    return _BY_KEY.get(key(emoji))


def display(emoji: str) -> str:
    """La forma para mostrar de un emoji que guardó o mandó Telegram."""
    api = api_form(emoji)
    return _DISPLAY.get(api, api) if api else str(emoji or "")


def display_list() -> list[str]:
    """La lista de `telegram.status` (`reactions`), en la forma para mostrar."""
    return [_DISPLAY.get(e, e) for e in BOT_REACTIONS]


def first_emoji(items) -> str:
    """El emoji de una lista `ReactionType` de Telegram (`new_reaction`), o "" si no hay. Las
    personalizadas y las pagadas no se cuentan (PRD #685 §5)."""
    for r in items or []:
        if isinstance(r, dict) and r.get("type") == "emoji" and isinstance(r.get("emoji"), str):
            return r["emoji"]
    return ""


def view(current: dict | None) -> list[dict]:
    """
    `[{emoji, count, mine}]` de un mensaje (FR-14): `ours` es la del bot (la ponga el dueño
    desde la web o el agente desde la CLI) y `theirs` la del contacto. Primero la nuestra,
    luego por `count`; sin reacciones, lista vacía.
    """
    groups: dict[str, dict] = {}
    for side in ("ours", "theirs"):
        emoji = (current or {}).get(side) or ""
        if not emoji:
            continue
        g = groups.setdefault(key(emoji), {"emoji": display(emoji), "count": 0, "mine": False})
        g["count"] += 1
        if side == "ours":
            g["mine"] = True
    return sorted(groups.values(), key=lambda g: (not g["mine"], -g["count"]))
