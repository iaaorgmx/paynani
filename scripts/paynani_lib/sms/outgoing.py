"""
Una sola forma de crear una orden de envío de SMS (PRD #489 FR-13).

La usan `paynani sms send` (el agente), PaynaniWeb (el dueño, PRD #489) y la
API (PRD #491). Cada quien hace antes sus propias revisiones: el agente, el
roster, las reglas y la pausa; la web, la contraseña fuera del roster; la API,
los permisos del token y las bajas. Aquí sólo vive lo que es igual para todos:
validar el número y el texto, aplicar el tope por hora del origen, escribir la
orden en `outbox/` y anotar `queued` en `orders.jsonl`.

La pasarela todavía manda sólo las órdenes del agente (`Store.pending_orders`).
Las del dueño y las de la API las manda T2 de #490, después de saber si el
teléfono las acepta.
"""
from __future__ import annotations

import calendar
import json
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "harness") not in sys.path:
    sys.path.insert(0, str(ROOT / "harness"))

import phone  # noqa: E402

from .gateway import status_id  # noqa: E402
from .store import ORDER_PREFIX, Store  # noqa: E402

MAX_TEXT = 1000
DEFAULT_TTL_MIN = 15
MAX_PAUSE_MIN = 1440
HOUR_S = 3600


class Refused(Exception):
    """La orden no se crea. `code` es estable (lo usan la web y la API); `message` es para personas."""

    def __init__(self, code: str, message: str, retry_at: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_at = retry_at


def new_order_id(origin: str) -> str:
    return f"{ORDER_PREFIX[origin]}_{secrets.token_hex(16)}"


def check_text(text: str) -> None:
    if not str(text or "").strip():
        raise Refused("empty_text", "empty_text: there is nothing to send.")
    if len(text) > MAX_TEXT:
        raise Refused("text_too_long", f"text_too_long: {len(text)} characters, the limit is {MAX_TEXT}.")


def normalize(number: str, region: str | None = None) -> str:
    e164 = phone.to_e164(number, region) if region else phone.to_e164(number)
    if e164 is None:
        raise Refused("invalid_number",
                      f"{number!r} is not a phone number. Write it in E.164, for example +525511112222.")
    return e164


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _epoch(stamp: str) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def recent_queued(store: Store, origin: str, token: str | None = None,
                  now: float | None = None, window_s: int = HOUR_S) -> list[float]:
    """Las horas (época) de las órdenes de ese origen, y de ese token si se da, en la última ventana."""
    now = time.time() if now is None else now
    path = store.root / "orders.jsonl"
    found = []
    if not path.exists():
        return found
    prefix = ORDER_PREFIX[origin] + "_"
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("status") != "queued" or not str(rec.get("order_id", "")).startswith(prefix):
                continue
            if token is not None and rec.get("token") != token:
                continue
            at = _epoch(str(rec.get("at", "")))
            if at is not None and now - window_s < at <= now:
                found.append(at)
    return sorted(found)


def queue(store: Store, *, to: str, text: str, origin: str = "agent", ttl_min: int = DEFAULT_TTL_MIN,
          sim_slot: int | None = None, per_hour: int | None = None, source: str | None = None,
          token: str | None = None, agent_pause_min: int | None = None, region: str | None = None,
          now: float | None = None) -> dict:
    """
    Crea la orden y la deja en outbox/. Devuelve la orden. Lanza `Refused` sin
    escribir nada si el número o el texto no sirven, o si el origen llegó a su tope.

    - `per_hour`: el tope del origen (y del token, si se da) en la última hora.
      None = sin tope aquí; el del agente lo aplica el teléfono (`max_out_per_hour`).
    - `source`: de dónde vino (la dirección de la web), para orders.jsonl (FR-16).
    - `token`: el nombre del token de la API (PRD #491).
    - `agent_pause_min`: sólo para el dueño (PRD #489 FR-14): 0 no pausa.
    """
    if origin not in ORDER_PREFIX:
        raise ValueError(f"origen desconocido: {origin!r}")
    check_text(text)
    if ttl_min < 1:
        raise Refused("invalid_ttl", "--ttl must be at least 1 minute.")
    number = normalize(to, region)
    now = time.time() if now is None else now
    if per_hour is not None:
        recent = recent_queued(store, origin, token=token, now=now)
        if len(recent) >= per_hour:
            retry_at = _iso(recent[0] + HOUR_S)
            raise Refused("rate_limited",
                          f"rate_limited: {len(recent)} SMS in the last hour, the limit is {per_hour}. "
                          f"Try again after {retry_at}.", retry_at=retry_at)

    order_id = new_order_id(origin)
    order = {"id": order_id, "to": number, "text": text, "expires_at": _iso(now + ttl_min * 60)}
    if sim_slot is not None:
        order["sim_slot"] = sim_slot
    if origin != "agent":
        order["origin"] = origin
    if origin == "owner":
        pause = int(agent_pause_min or 0)
        if not 0 <= pause <= MAX_PAUSE_MIN:
            raise Refused("invalid_pause", f"invalid_pause: {pause} is outside 0 to {MAX_PAUSE_MIN} minutes.")
        order["agent_pause_min"] = pause
    if origin == "api" and token:
        order["token"] = token

    store.queue_order(order)
    record = {"id": status_id(order_id, "queued"), "order_id": order_id, "status": "queued",
              "at": _iso(now)}
    if origin != "agent":
        record["origin"] = origin
    if source:
        record["source"] = source
    if token:
        record["token"] = token
    store.append_status(record)
    return order
