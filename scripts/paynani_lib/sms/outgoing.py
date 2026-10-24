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
import contextlib
import fcntl
import hashlib
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
DAY_S = 86400


class Refused(Exception):
    """La orden no se crea. `code` es estable (lo usan la web y la API); `message` es para personas."""

    def __init__(self, code: str, message: str, retry_at: str | None = None, order_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_at = retry_at
        self.order_id = order_id


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


def _pause(value) -> int:
    """`agent_pause_min` del dueño: None es 0 (sin pausa); cualquier otra cosa, un entero de 0 a 1,440."""
    if value is None:
        return 0
    if isinstance(value, bool):
        value = "bool"
    try:
        pause = int(str(value).strip())
    except ValueError:
        raise Refused("invalid_pause", f"invalid_pause: {value!r} is not a whole number of minutes.") from None
    if not 0 <= pause <= MAX_PAUSE_MIN:
        raise Refused("invalid_pause", f"invalid_pause: {pause} is outside 0 to {MAX_PAUSE_MIN} minutes.")
    return pause


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _epoch(stamp: str) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def recent_queued(store: Store, origin: str, token: str | None = None,
                  now: float | None = None, window_s: int = HOUR_S, token_id: str | None = None) -> list[float]:
    """Las horas (época) de las órdenes de ese origen, y de ese token si se da, en la última ventana.
    `token_id` (el prefijo `pn_…` del token, PRD #491) filtra mejor que el nombre, que se puede repetir."""
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
            if token_id is not None and rec.get("token_id") != token_id:
                continue
            at = _epoch(str(rec.get("at", "")))
            if at is not None and now - window_s < at <= now:
                found.append(at)
    return sorted(found)


def queue(store: Store, *, to: str, text: str, origin: str = "agent", ttl_min: int = DEFAULT_TTL_MIN,
          sim_slot: int | None = None, per_hour: int | None = None, source: str | None = None,
          token: str | None = None, agent_pause_min: int | None = None, region: str | None = None,
          now: float | None = None, per_day: int | None = None, token_id: str | None = None,
          idempotency_key: str | None = None) -> dict:
    """
    Crea la orden y la deja en outbox/. Devuelve la orden. Lanza `Refused` sin
    escribir nada si el número o el texto no sirven, o si el origen llegó a su tope.

    - `per_hour`: el tope del origen (y del token, si se da) en la última hora: un
      entero de 1 o más. None = sin tope aquí; el del agente lo aplica el teléfono
      (`max_out_per_hour`). 0, negativo o no entero: `invalid_limit`.
    - `source`: de dónde vino (la dirección de la web), para orders.jsonl (FR-16).
      Obligatorio para el dueño.
    - `token`: el nombre del token de la API (PRD #491). Obligatorio para la API.
    - `agent_pause_min`: sólo para el dueño (PRD #489 FR-14): None o 0 no pausa.
    - `per_day`: como `per_hour`, en las últimas 24 horas (PRD #491 FR-9). Pasarlo
      lanza `quota_exceeded`.
    - `token_id`: el prefijo del token de la API. Con él cuentan los topes y la llave.
    - `idempotency_key`: sólo para la API (PRD #491 FR-7). Si ese token ya creó una
      orden con esa llave y el mismo número y texto, devuelve esa orden con
      `"duplicate": True` (en la copia que devuelve, no en el archivo) y no escribe
      nada; con otro número o texto lanza `idempotency_conflict`.
    """
    if origin not in ORDER_PREFIX:
        raise ValueError(f"origen desconocido: {origin!r}")
    # Todo rechazo pasa aquí arriba, antes de escribir nada en outbox/ u orders.jsonl.
    check_text(text)
    if ttl_min < 1:
        raise Refused("invalid_ttl", "--ttl must be at least 1 minute.")
    number = normalize(to, region)
    if origin == "api" and not str(token or "").strip():
        raise Refused("missing_token", "missing_token: an API order needs the token name (PRD #491 FR-6).")
    if origin == "owner" and not str(source or "").strip():
        raise Refused("missing_source", "missing_source: an owner order needs the web address (PRD #489 FR-16).")
    pause = None
    if origin == "owner":
        pause = _pause(agent_pause_min)
    for name, limit in (("per_hour", per_hour), ("per_day", per_day)):
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise Refused("invalid_limit", f"invalid_limit: {name} must be a whole number of 1 or more, not {limit!r}.")
    if idempotency_key is not None and origin != "api":
        raise ValueError("idempotency_key es sólo para la API")
    with _queue_lock(store):
        now = time.time() if now is None else now
        if idempotency_key is not None:
            earlier = find_idempotent(store, token_id, idempotency_key)
            if earlier is not None:
                if earlier.get("content_sha256") != content_sha256(number, text):
                    raise Refused("idempotency_conflict",
                                  "idempotency_conflict: this idempotency_key was already used with another number or text.",
                                  order_id=earlier["order_id"])
                order = dict(store.order(earlier["order_id"]) or {"id": earlier["order_id"], "to": number,
                                                                  "text": text, "origin": "api"})
                order["duplicate"] = True
                return order
        return _count_and_write(store, origin=origin, number=number, text=text, ttl_min=ttl_min,
                                sim_slot=sim_slot, per_hour=per_hour, source=source, token=token,
                                pause=pause, now=now, per_day=per_day, token_id=token_id,
                                idempotency_key=idempotency_key)


def content_sha256(number: str, text: str) -> str:
    """Lo que la llave de idempotencia compara: el número ya normalizado y el texto."""
    return hashlib.sha256(f"{number}\n{text}".encode("utf-8")).hexdigest()


def find_idempotent(store: Store, token_id: str | None, key: str) -> dict | None:
    """El registro `queued` de orders.jsonl con esa llave de ese token, o None."""
    path = store.root / "orders.jsonl"
    if not path.exists() or not token_id:
        return None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if (rec.get("status") == "queued" and rec.get("token_id") == token_id
                    and rec.get("idempotency_key") == key):
                return rec
    return None


@contextlib.contextmanager
def _queue_lock(store: Store):
    """
    Contar las órdenes de la última hora y escribir la nueva es una sola operación:
    sin este candado, dos envíos al mismo tiempo (PaynaniWeb atiende cada pedido en
    su hilo; la API y `paynani sms send` corren en otros procesos) ven el mismo
    conteo y los dos rebasan el tope (revisión de #519). `flock` sobre un archivo del
    store excluye a hilos y procesos, porque cada llamada abre su propio descriptor.
    """
    store.root.mkdir(parents=True, exist_ok=True)
    with open(store.root / "queue.lock", "a+b") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _count_and_write(store: Store, *, origin, number, text, ttl_min, sim_slot, per_hour, source, token,
                     pause, now, per_day=None, token_id=None, idempotency_key=None) -> dict:
    scope = {"token_id": token_id} if token_id else {"token": token}
    if per_day is not None:
        today = recent_queued(store, origin, now=now, window_s=DAY_S, **scope)
        if len(today) >= per_day:
            retry_at = _iso(today[0] + DAY_S)
            raise Refused("quota_exceeded",
                          f"quota_exceeded: {len(today)} SMS in the last 24 hours, the limit is {per_day}. "
                          f"Try again after {retry_at}.", retry_at=retry_at)
    if per_hour is not None:
        recent = recent_queued(store, origin, now=now, **scope)
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
    if token_id:
        record["token_id"] = token_id
    if idempotency_key is not None:
        record["idempotency_key"] = idempotency_key
        record["content_sha256"] = content_sha256(number, text)
    store.append_status(record)
    return order
