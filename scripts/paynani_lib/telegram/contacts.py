"""
Quién es quien escribe por Telegram (PRD #609 FR-11 a FR-13; TELEGRAM.md §1, links.json).

Un mensaje privado se reconoce sólo por el id numérico de quien lo manda (`from.id`):

1. si la columna `Telegram` de una fila tiene ese id, es esa fila;
2. si un `@usuario` de la columna ya quedó fijado a ese id en `links.json`, es la fila
   que hoy tiene ese `@usuario`;
3. si el `@usuario` con el que escribe está en la columna y todavía no está fijado, se
   fija a este id (el servicio guarda el vínculo y avisa al dueño);
4. si está en la columna pero fijado a otro id, no se reconoce: es alguien fuera del
   roster, y el dueño recibe un aviso.

Un vínculo cuyo `@usuario` ya no está en la columna (el dueño lo cambió o lo borró, o
quedó repetido) se borra. `decide()` no escribe nada: devuelve qué hacer.
"""
from __future__ import annotations


def decide(known: dict, links: dict, user_id: int, username: str | None) -> dict:
    """
    `known` es `roster.roster_telegram()`; `links` es `{usuario: {"id": int, ...}}`.

    Devuelve `{"entry": fila o None, "pin": usuario o None, "conflict": usuario o None,
    "drop": [usuarios]}`.
    """
    uid = int(user_id)
    drop = [u for u in links if u not in known["usernames"]]
    live = {u: link for u, link in links.items() if u not in drop}
    out = {"entry": None, "pin": None, "conflict": None, "drop": drop}
    entry = known["ids"].get(str(uid))
    if entry is not None:
        out["entry"] = entry
        return out
    for name, link in live.items():
        if _link_id(link) == uid:
            out["entry"] = known["usernames"][name]
            return out
    name = (username or "").lower()
    if not name or name not in known["usernames"]:
        return out
    if name in live:
        out["conflict"] = name
        return out
    out["entry"] = known["usernames"][name]
    out["pin"] = name
    return out


def recognized_now(known: dict, links: dict, user_id: int) -> dict | None:
    """
    La fila de ese id hoy, sin fijar nada: por su id en la columna o por un vínculo vivo.
    Para `event show --body`, que no debe fijar un `@usuario` (sólo lo hace un mensaje).
    """
    uid = int(user_id)
    entry = known["ids"].get(str(uid))
    if entry is not None:
        return entry
    for name, link in links.items():
        if name in known["usernames"] and _link_id(link) == uid:
            return known["usernames"][name]
    return None


def _link_id(link) -> int | None:
    try:
        return int((link or {}).get("id"))
    except (TypeError, ValueError):
        return None
