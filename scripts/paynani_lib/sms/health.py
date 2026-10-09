"""
Cómo está el teléfono (SRV-5): lo que muestran `paynani status` y `healthcheck`.

Sólo lee `state/sms/` y nunca la crea: preguntar por la salud no debe dejar
carpetas en una instalación que no usa SMS. Sin teléfono emparejado no hay nada
que decir, y eso tampoco es un fallo.
"""
from __future__ import annotations

import calendar
import json
import time
from pathlib import Path

HEARTBEAT_S = 30
# Un latido más viejo que esto no cuenta como conectado aunque device.json diga
# que sí: si la pasarela murió, nadie borró la marca.
STALE_AFTER_S = 3 * HEARTBEAT_S


def _epoch(stamp):
    try:
        return float(calendar.timegm(time.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def phone_facts(state_dir, now=None):
    """None si no hay teléfono emparejado; si no, un diccionario con su estado."""
    now = time.time() if now is None else now
    root = Path(state_dir) / "sms"
    try:
        device = json.loads((root / "device.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    seen = _epoch(device.get("last_seen"))
    age = None if seen is None else max(0, int(now - seen))
    online = bool(device.get("connected")) and age is not None and age <= STALE_AFTER_S
    try:
        queued = len(list((root / "outbox").glob("o_*.json")))
    except OSError:
        queued = 0
    return {
        "device_id": device.get("device_id", ""),
        "model": device.get("model", ""),
        "app_version": device.get("app_version", ""),
        "paired_at": device.get("paired_at"),
        "online": online,
        "last_seen": device.get("last_seen"),
        "last_seen_age_s": age,
        "orders_queued": queued,
        "offline_notified": bool(device.get("offline_notified")),
    }


def _span(seconds):
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min {secs} s" if minutes else f"{secs} s"


def describe(facts):
    """Las líneas de texto de un `phone_facts`, sin formato de ningún comando."""
    if facts is None:
        return ["no phone is paired"]
    who = facts["device_id"] + (f" ({facts['model']})" if facts["model"] else "")
    if facts["last_seen_age_s"] is None:
        beat = "never connected"
    else:
        beat = f"last heartbeat {_span(facts['last_seen_age_s'])} ago ({facts['last_seen']})"
    state = "online" if facts["online"] else "OFFLINE"
    queue = f"{facts['orders_queued']} order(s) queued"
    line = f"{who}: {state}, {beat}, {queue}"
    if not facts["online"] and facts["offline_notified"]:
        line += "; sms.gateway.offline was sent to the agent"
    if not facts["online"] and facts["last_seen_age_s"] is not None:
        line += "; if it does not come back, open Paynani on the phone (the maker may have closed it, INSTALL.md §5.2 step 4)"
    return [line]
