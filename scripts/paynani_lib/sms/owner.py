"""
Mensajes de texto del dueño: lo que hacen las páginas de SMS de PaynaniWeb, sin HTML.

PaynaniWeb y la API del dueño (PaynaniWebMT PRD #2, FR-A6) llaman a estas mismas
funciones, para no tener dos copias de las reglas del canal:

- `phone_state`: si el teléfono emparejado acepta órdenes del dueño (PRD #489 FR-6).
- `region`: la región para normalizar números (FR-2).
- `offline_ttl`: en cuántos minutos vence una orden con el teléfono desconectado (FR-7).
- `send`: la orden del dueño, con «Pausar al agente» (FR-1 a FR-4b, FR-8, FR-9).
- `statuses`: el estado de cada mensaje de la web en una conversación (FR-5).
- `set_opt_out`: dar de baja o de alta un número para la API (PRD #491 FR-13).

Lo que no está aquí es de quien llama: la contraseña para un número fuera del roster
(FR-3), los textos y los códigos HTTP.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import api_replies, config, outgoing
from . import thread as sms_thread

PHONE_OK = "ok"
PHONE_NONE = "no_phone"
PHONE_OLD = "old_app"
PHONE_NO_SMS = "no_sms_phone"   # PaynaniApp sólo Webchat (PaynaniApp-Agentic#175): no manda SMS


def phone_state(store) -> str:
    """FR-6: ¿el teléfono emparejado acepta órdenes del dueño?"""
    if not store.device():
        return PHONE_NONE
    # Un teléfono «solo Webchat» (#671) no manda SMS: no es que la app sea vieja.
    if not store.sms_enabled():
        return PHONE_NO_SMS
    return PHONE_OK if store.accepts("owner") else PHONE_OLD


def region(store) -> str | None:
    """La región de la SIM del teléfono emparejado (FR-2), o la de la instalación."""
    import phone as phone_mod
    for sim in (store.device() or {}).get("sims") or []:
        country = str((sim or {}).get("country") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", country):
            return country
    return phone_mod.default_region()


def offline_ttl(state_dir: Path, state: str) -> int:
    """FR-7: con el teléfono emparejado pero desconectado, los minutos en que vence una
    orden; 0 si está conectado (o no hay a quién mandar)."""
    from . import health
    if state != PHONE_OK:
        return 0
    facts = health.phone_facts(state_dir)
    return 0 if facts and facts["online"] else outgoing.DEFAULT_TTL_MIN


class NotReady(Exception):
    """El teléfono no acepta órdenes del dueño; `state` dice por qué (FR-6)."""

    def __init__(self, state: str):
        super().__init__(state)
        self.state = state


def normalize(store, raw: str) -> str:
    """El número en E.164 con la región del teléfono. `outgoing.Refused` si no sirve."""
    return outgoing.normalize(raw, region(store))


def send(store, number: str, text: str, *, pause: bool, source: str) -> dict:
    """La orden del dueño a `number`, ya normalizado. Con `pause`, el agente no contesta a
    ese número por los minutos de `web_agent_pause_min`. Levanta `NotReady` si el teléfono
    no acepta órdenes y `outgoing.Refused` (con su `code`) si la orden no sale."""
    state = phone_state(store)
    if state != PHONE_OK:
        raise NotReady(state)
    return outgoing.queue(store, to=number, text=text.replace("\r\n", "\n"), origin="owner", source=source,
                          agent_pause_min=config.web_agent_pause_min() if pause else 0,
                          per_hour=config.web_sms_per_hour())


def statuses(store, state_dir: Path, number: str) -> dict:
    """FR-5: los mensajes de la web (`w_…`) en la conversación con `number`, con su estado
    y su error, y si el teléfono está desconectado."""
    items = [i for i in sms_thread.items(store, state_dir / "events.jsonl", calls=True)
             if number and i["number"] == number]
    return {"count": len(items),
            "offline": bool(offline_ttl(state_dir, phone_state(store))),
            "items": [{"id": i["id"], "status": i["status"], "error": i.get("error", "")}
                      for i in items if i.get("id", "").startswith("w_")]}


def set_opt_out(store, number: str, out: bool, *, by: str) -> bool:
    """Baja (`out`) o alta de `number`, ya normalizado. True si cambió."""
    return api_replies.set_opt_out(store, number, out, by=by)
