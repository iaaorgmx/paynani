"""
El agente de IA en PaynaniWeb (#644): el bloque del menú lateral y la página «AI Agent».
Como el Dashboard, sólo lee lo que ya existe, por medio de `dashboard.Source`; nada de
aquí escribe en `state/`, marca un aviso ni abre IMAP.

- `status(services, runtime)` es el semáforo (Q293): `online` (verde), `no_session`
  (ámbar) u `offline` (rojo).
- `summary(source)` es lo del bloque del menú: nombre, runtime y estado.
- `build(source, now)` es el modelo de la página: el agente, las cuatro cifras de hoy,
  los canales y lo que el agente hizo hoy.
"""
from __future__ import annotations

import datetime as dt
import statistics

from .dashboard import CLOSED, Source, parse

RUNTIMES = {"claudecode": "Claude Code", "openclaw": "OpenClaw", "hermes": "Hermes"}
WATCH_RUNTIME = "claudecode"     # el único que vigila con una sesión (watch_registry_facts)
ACTIVITY = 10


def runtime_label(runtime: str) -> str:
    return RUNTIMES.get(runtime, runtime or "?")


def status(services: dict, runtime: str) -> str:
    """
    Q293. Con el despachador detenido no le llega nada al agente: `offline`. En Claude Code
    el agente es una sesión que vigila el correo: sin una vigilancia viva, `no_session`.
    OpenClaw y Hermes no tienen sesión que vigilar (siempre escuchan): con el despachador
    activo, `online`.
    """
    if (services.get("dispatcher") or {}).get("unit") != "active":
        return "offline"
    if runtime == WATCH_RUNTIME and not (services.get("session") or {}).get("live"):
        return "no_session"
    return "online"


def summary(source: Source) -> dict:
    """El bloque del menú: `{name, runtime, runtime_label, status}`."""
    info = source.agent()
    runtime = info.get("runtime", "")
    name = info.get("name") or (info.get("email") or "").split("@")[0]
    return {"name": name, "runtime": runtime, "runtime_label": runtime_label(runtime),
            "status": status(source.services(), runtime)}


def build(source: Source, now: dt.datetime) -> dict:
    """El modelo de la página. «Hoy» es en la zona del host, como en el Dashboard."""
    tz = now.tzinfo
    today = now.date()
    info = source.agent()
    services = source.services()
    runtime = info.get("runtime", "")

    handled = {"replied": 0, "closed": 0}
    reply_seconds = []
    activity = []
    for account in source.accounts():
        for row in source.mail(account["id"]):
            state = row.get("state", "")
            if state not in CLOSED:
                continue
            at = parse(row.get("state_at"))
            if at is None or at.astimezone(tz).date() != today:
                continue
            handled["replied" if state == "replied" else "closed"] += 1
            seen = parse(row.get("observed_at"))
            if state == "replied" and seen is not None and at >= seen:
                reply_seconds.append((at - seen).total_seconds())
            activity.append({"at": at.astimezone(tz), "channel": "mail", "state": state,
                             "who": row.get("sender_name") or row.get("sender_address", ""),
                             "what": row.get("subject", ""),
                             "href": _mail_href(account["id"], row.get("event_id", ""))})

    # La última respuesta: lo último que el agente mandó, por correo o por SMS.
    last = None
    for account in source.accounts():
        for rec in source.sent(account["id"]):
            at = parse(rec.get("at"))
            if at is not None and (last is None or at > last["at"]):
                last = {"at": at.astimezone(tz), "who": rec.get("to", ""), "channel": "mail"}
    for item in source.sms():
        if item.get("kind") != "agent":
            continue
        try:
            at = dt.datetime.fromtimestamp(float(item.get("epoch")), tz)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if last is None or at > last["at"]:
            last = {"at": at, "who": item.get("name") or item.get("number", ""), "channel": "sms"}
        if at.date() == today:
            activity.append({"at": at, "channel": "sms", "state": "sent", "who": item.get("name") or item.get("number", ""),
                             "what": "", "href": "/messages/ver?n=" + _q(item.get("number", ""))})
    activity.sort(key=lambda a: a["at"], reverse=True)

    session = services.get("session") or {}
    wa = source.whatsapp()
    tg = source.telegram()
    return {
        "now": now,
        "name": info.get("name") or (info.get("email") or "").split("@")[0],
        "email": info.get("email", ""),
        "runtime": runtime,
        "runtime_label": runtime_label(runtime),
        "watches": runtime == WATCH_RUNTIME,
        "status": status(services, runtime),
        "session": {"live": bool(session.get("live")), "armed_at": parse(session.get("armed_at")),
                    "expires_at": parse(session.get("expires_at"))},
        "dispatcher": (services.get("dispatcher") or {}).get("unit", "unknown"),
        "listener": (services.get("listener") or {}).get("unit", "unknown"),
        "handled": handled,
        "waiting": int((services.get("queue") or {}).get("pending") or 0),
        "last_reply": last,
        "reply_median_s": statistics.median(reply_seconds) if reply_seconds else None,
        "version": source.version(),
        "roster_count": int(source.roster().get("count") or 0),
        "phone": services.get("phone"),
        "whatsapp": None if wa is None else (wa.get("status") or {}).get("state", ""),
        "telegram": tg,
        "activity": activity[:ACTIVITY],
    }


def _mail_href(account_id: str, event_id: str) -> str:
    from .dashboard import mail_href
    return mail_href(account_id, event_id)


def _q(value: str) -> str:
    from urllib.parse import quote
    return quote(str(value or ""), safe="")

