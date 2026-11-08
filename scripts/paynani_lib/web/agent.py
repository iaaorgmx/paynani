"""
El agente de IA en PaynaniWeb (#644): el bloque del menú lateral y la página «AI Agent».
Como el Dashboard, sólo lee lo que ya existe, por medio de `dashboard.Source`; nada de
aquí escribe en `state/`, marca un aviso ni abre IMAP o la red.

- `status(...)` es el semáforo (Q293): `online` (verde), `no_session` (ámbar), `offline`
  (rojo) o `unknown` (gris, cuando todavía no hay evidencia; revisión de Ximena en #645).
- `summary(source)` es lo del bloque del menú: nombre, runtime y estado.
- `build(source, now)` es el modelo de la página: el agente, las cuatro cifras de hoy,
  los canales y lo que el agente hizo hoy, por correo, SMS, WhatsApp y Telegram
  (revisión de Metis en #645).
"""
from __future__ import annotations

import datetime as dt
import statistics

from .dashboard import CLOSED, Source, parse

RUNTIMES = {"claudecode": "Claude Code", "openclaw": "OpenClaw", "hermes": "Hermes",
            "codex": "Codex", "opencode": "OpenCode", "antigravity": "Antigravity CLI"}
# Claude Code: la sesión arma una vigilancia (watch_registry_facts), y eso es la evidencia.
WATCH_RUNTIME = "claudecode"
# Codex y OpenCode: el despachador escribe en un spool y la sesión lo lee; «aceptado» sólo
# quiere decir que quedó en el spool. La evidencia es que la sesión lo tome (`presented`):
# un evento que el despachador le dio a este runtime y nadie toma en STUCK_S es que no hay
# sesión. Los que se quedaron `dispatched` con otro runtime no cuentan.
SPOOL_RUNTIMES = ("codex", "opencode")
# OpenClaw y Hermes: el runtime contesta al entregarle el evento; lo que dijo queda en
# state/delivery.json (healthcheck.delivery_facts). Un rechazo más nuevo que la última
# aceptación, o una cola atorada más de STUCK_S, es que no le llega nada.
PUSH_RUNTIMES = ("openclaw", "hermes")
# Antigravity CLI (#749): el despachador escribe en un spool y los hooks de `agy` lo muestran
# al empezar cada conversación. Que espere en el spool es lo normal, no una falla
# (healthcheck.spool_facts), así que no hay «no_session»: lo que se sabe es si quedó en el spool.
REPLAY_RUNTIMES = ("antigravity",)
STUCK_S = 600
ACTIVITY = 10


def runtime_label(runtime: str) -> str:
    return RUNTIMES.get(runtime, runtime or "?")


def evidence(runtime: str) -> str:
    """Qué dice si el agente recibe los mensajes (#757): `watch` (la vigilancia de Claude Code),
    `delivery` (lo que contestó un runtime push), `spool` (que la sesión tome lo del spool),
    `replay` (lo que espera la siguiente conversación de `agy`), o "" si no se conoce."""
    if runtime == WATCH_RUNTIME:
        return "watch"
    if runtime in PUSH_RUNTIMES:
        return "delivery"
    if runtime in SPOOL_RUNTIMES:
        return "spool"
    if runtime in REPLAY_RUNTIMES:
        return "replay"
    return ""


def session(services: dict, runtime: str, events: list[dict] | None = None,
            now: dt.datetime | None = None) -> dict:
    """
    `services.session` con lo que corresponde al runtime (#757). Conserva `live`, `armed_at` y
    `expires_at` (la vigilancia de Claude Code, como antes) y agrega `runtime`, `runtime_label`,
    `evidence`, `status` (el mismo semáforo del menú), `last_accepted` (sólo de este runtime) y,
    con `replay`, `unread` (si hay algo esperando la siguiente conversación). PaynaniWeb y
    PaynaniWebMT pintan la fila «Agent session» con esto.
    """
    base = services.get("session") or {}
    out = {"live": bool(base.get("live")), "armed_at": str(base.get("armed_at") or ""),
           "expires_at": str(base.get("expires_at") or ""),
           "runtime": runtime, "runtime_label": runtime_label(runtime) if runtime else "",
           "evidence": evidence(runtime), "status": status(services, runtime, events, now),
           "last_accepted": delivered(services, "last_accepted", runtime)}
    if not out["evidence"] and out["live"] and out["status"] != "offline":
        # Sin saber el runtime, una vigilancia armada sigue siendo evidencia: se dice como antes.
        out["evidence"], out["status"] = "watch", "online"
    if out["evidence"] == "replay":
        unread = base.get("unread_bytes")
        out["unread"] = None if unread is None else int(unread) > 0
    return out


def _newer(a: str, b: str) -> bool:
    """¿La hora `a` es posterior a la `b`? Una que falta nunca es más nueva."""
    ta, tb = parse(a), parse(b)
    return ta is not None and (tb is None or ta > tb)


def delivered(services: dict, key: str, runtime: str) -> str:
    """La hora de `last_accepted` o `last_error` sólo si la dio este runtime: al cambiar de
    runtime, lo que dijo el anterior no es evidencia del nuevo (revisión de Ximena en #645)."""
    entry = (services.get("delivery") or {}).get(key) or {}
    return str(entry.get("at") or "") if entry.get("runtime") == runtime and runtime else ""


def status(services: dict, runtime: str, events: list[dict] | None = None,
           now: dt.datetime | None = None) -> str:
    """
    Q293, con una señal observable para cada runtime (revisión de Ximena en #645). Con el
    despachador detenido no le llega nada al agente: `offline`. Si no hay evidencia todavía
    (nada entregado, o un runtime que no se conoce), `unknown`: no se afirma que esté en línea.
    """
    if (services.get("dispatcher") or {}).get("unit") != "active":
        return "offline"
    accepted, error = delivered(services, "last_accepted", runtime), delivered(services, "last_error", runtime)
    if runtime == WATCH_RUNTIME:
        return "online" if (services.get("session") or {}).get("live") else "no_session"
    if runtime in SPOOL_RUNTIMES:
        now = now or dt.datetime.now(dt.timezone.utc)
        for event in events or ():
            at = parse(event.get("state_at"))
            if (event.get("state") == "dispatched" and event.get("runtime") == runtime and at is not None
                    and (now - at).total_seconds() > STUCK_S):
                return "no_session"
        return "online" if accepted else "unknown"
    if runtime in PUSH_RUNTIMES:
        oldest = (services.get("queue") or {}).get("oldest_age_s")
        if _newer(error, accepted) or (oldest is not None and oldest > STUCK_S):
            return "offline"
        return "online" if accepted else "unknown"
    if runtime in REPLAY_RUNTIMES:
        return "online" if accepted else "unknown"
    return "unknown"


def summary(source: Source, now: dt.datetime | None = None) -> dict:
    """El bloque del menú: `{name, runtime, runtime_label, status}`. Sólo lee el ledger
    cuando el runtime lo necesita (Codex y OpenCode)."""
    info = source.agent()
    runtime = info.get("runtime", "")
    events = source.events() if runtime in SPOOL_RUNTIMES else None
    name = info.get("name") or (info.get("email") or "").split("@")[0]
    return {"name": name, "runtime": runtime, "runtime_label": runtime_label(runtime),
            "status": status(source.services(), runtime, events, now)}


def _href(event: dict) -> str:
    from urllib.parse import quote
    channel = event["channel"]
    if channel == "mail":
        from .dashboard import mail_href
        return mail_href(event.get("account") or "main", event["event_id"])
    if channel == "sms":
        return "/messages/ver?n=" + quote(event.get("sender_address", ""), safe="")
    if channel == "whatsapp":
        return "/whatsapp/messages/ver?n=" + quote(event.get("sender_address", ""), safe="")
    if channel == "webchat":
        return "/webchat"
    return "/telegram/messages"


def build(source: Source, now: dt.datetime) -> dict:
    """El modelo de la página. «Hoy» es en la zona del host, como en el Dashboard."""
    tz = now.tzinfo
    today = now.date()
    info = source.agent()
    services = source.services()
    runtime = info.get("runtime", "")
    events = source.events()

    handled = {"replied": 0, "closed": 0}
    reply_seconds = []
    activity = []
    last = None
    for event in events:
        # Respondido es haber tenido una transición `replied`, aunque después se cerrara;
        # su hora es la de la respuesta (revisión de Ximena en #645).
        replied_at = parse(event.get("replied_at"))
        if replied_at is not None:
            state, at = "replied", replied_at
        elif event.get("state", "") in CLOSED:
            state, at = event["state"], parse(event.get("state_at"))
        else:
            continue
        if at is None:
            continue
        at = at.astimezone(tz)
        who = event.get("sender_name") or event.get("sender_address", "")
        # La última respuesta: lo último que el agente respondió, en cualquier canal. No
        # sale de sent.log, que también tiene los avisos de PaynaniWeb al dueño (Metis).
        if state == "replied" and (last is None or at > last["at"]):
            last = {"at": at, "who": who, "channel": event["channel"]}
        if at.date() != today:
            continue
        handled["replied" if state == "replied" else "closed"] += 1
        seen = parse(event.get("observed_at"))
        if state == "replied" and seen is not None and at >= seen:
            reply_seconds.append((at - seen).total_seconds())
        activity.append({"at": at, "channel": event["channel"], "state": state, "who": who,
                         "what": event.get("subject", ""), "href": _href(event)})

    # Los SMS que el agente mandó: no tienen un evento propio en el ledger.
    for item in source.sms():
        if item.get("kind") != "agent":
            continue
        try:
            at = dt.datetime.fromtimestamp(float(item.get("epoch")), tz)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        who = item.get("name") or item.get("number", "")
        if last is None or at > last["at"]:
            last = {"at": at, "who": who, "channel": "sms"}
        if at.date() == today:
            activity.append({"at": at, "channel": "sms", "state": "sent", "who": who, "what": "",
                             "href": "/messages/ver?n=" + _q(item.get("number", ""))})
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
        "kind": ("watch" if runtime == WATCH_RUNTIME else "spool" if runtime in SPOOL_RUNTIMES
                 else "push" if runtime in PUSH_RUNTIMES else "replay" if runtime in REPLAY_RUNTIMES else ""),
        "status": status(services, runtime, events, now),
        "session": {"live": bool(session.get("live")), "armed_at": parse(session.get("armed_at")),
                    "expires_at": parse(session.get("expires_at"))},
        "last_accepted": parse(delivered(services, "last_accepted", runtime)),
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


def _q(value: str) -> str:
    from urllib.parse import quote
    return quote(str(value or ""), safe="")
