"""
El Dashboard de la página inicial de PaynaniWeb (PRD #602, de #601): qué lee y cómo
lo resume. Sólo lee lo que ya existe (Q12); nada de aquí escribe en `state/`, marca
un aviso ni abre IMAP (FR-20).

- `Source` es lo que el Dashboard pregunta: las cuentas, los correos de cada una, lo
  enviado, los SMS, WhatsApp, el roster, los tokens, la versión, las revisiones y los
  servicios. `Core` lo lee de la instalación; `Fake` lo tiene en memoria, para las
  pruebas.
- `build(source, now)` lo vuelve el modelo de la página: el estado general, los
  indicadores de hoy, los servicios, lo que necesita atención, los 7 días y la
  actividad reciente. Es una función pura: con la misma fuente y la misma hora, el
  mismo resultado.
- `numbers(model)` es lo que va en `/dashboard.json` (FR-19): números y estados, sin
  direcciones, teléfonos, asuntos ni textos.

«Hoy» y los 7 días se cuentan en la zona horaria del host (Q6): la de `now`, que
`Core` da con `astimezone()`.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path

from .. import accounts

OPEN = ("observed", "dispatched", "presented")
CLOSED = ("handled", "replied", "closed")
DAYS = 7
ACTIVITY = 10
TOKEN_SOON_DAYS = 7
NOTICE_DAYS = 7                 # como el aviso de la sesión: avisos de los últimos 7 días
HEALTH_TTL_S = 60.0             # FR-6: las revisiones locales, con caché de 60 s
HEARTBEAT_STALE_S = 300
QUEUE_STALE_S = 600
DOCTOR_FILE = "doctor.json"     # el último `paynani doctor` completo, si el núcleo lo guarda
# Las revisiones de `doctor` que tocan la red: el Dashboard nunca las corre (FR-6).
# `himalaya` es la única que conecta (`himalaya account check`); `smtp` sólo mira si existe
# `[accounts.paynani]`, y la web la calcula en vivo (revisión de Metis en #605).
NETWORK_CHECKS = ("himalaya",)
NETWORK_MAX_AGE_S = 24 * 3600   # una revisión de red más vieja cuenta como unknown (revisión de Metis)
MODEL_TTL_S = 30.0              # el modelo, para no releer el ledger en cada /dashboard.json
STATUS_ORDER = {"ok": 0, "unknown": 1, "warning": 2, "blocked": 3}


# ---- Fechas ----------------------------------------------------------------------
def parse(stamp) -> dt.datetime | None:
    """Una hora ISO 8601 (con Z o con zona) como datetime con zona, o None."""
    if not stamp:
        return None
    try:
        value = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _from_epoch(epoch, tz) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(float(epoch), tz)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def zone_label(now: dt.datetime) -> str:
    """«CST (UTC−06:00)»: la zona del host, como la muestra la página (FR-7)."""
    offset = now.utcoffset() or dt.timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "−"
    minutes = abs(minutes)
    name = now.tzname() or ""
    utc = f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"
    return f"{name} ({utc})" if name and not name.startswith(("UTC", "+", "-")) else utc


# ---- La fuente -------------------------------------------------------------------
class Source:
    """Lo que el Dashboard pregunta. Cada método devuelve datos simples (dicts y listas)."""

    def accounts(self) -> list[dict]:
        """`[{id, email, enabled, agent}]`, la del agente primero."""
        raise NotImplementedError

    def mail(self, account_id: str) -> list[dict]:
        """Los recibidos de una cuenta: `{event_id, observed_at, state, roster, sender_name,
        sender_address, subject}`."""
        raise NotImplementedError

    def sent(self, account_id: str) -> list[dict]:
        """Los enviados de una cuenta: `{at, to, subject, message_id}`."""
        raise NotImplementedError

    def sms(self) -> list[dict]:
        """SMS y llamadas: `{epoch, kind, status, name, number}` (como `sms.thread.items`)."""
        raise NotImplementedError

    def whatsapp(self) -> dict | None:
        """None sin WhatsApp configurado; si no, `{status: {...}, received: [{at, name, number}]}`."""
        raise NotImplementedError

    def telegram(self) -> dict | None:
        """None sin Telegram configurado; si no, `{state, bot_username}` de `telegram.status`
        (PRD #609 FR-28). Nunca el token ni ids de Telegram."""
        return None

    def roster(self) -> dict:
        """`{count, changes: [{at, action, name, device_id}]}`."""
        raise NotImplementedError

    def tokens(self) -> list[dict]:
        """`[{name, expires_at, revoked_at}]`."""
        raise NotImplementedError

    def version(self) -> dict:
        """`{installed, latest, checked_at}`; los que no se saben, vacíos."""
        raise NotImplementedError

    def health(self) -> dict:
        """`{checks: [{name, status, summary}], network_at}`: las revisiones locales y, si
        hay un `doctor` guardado, sus revisiones de red con su hora."""
        raise NotImplementedError

    def services(self) -> dict:
        """`{listener, dispatcher, session, phone, additional: [...]}` (FR-10)."""
        raise NotImplementedError


# ---- La de la instalación ----------------------------------------------------------
class Core(Source):
    """Lee la instalación por medio del `Context` de la web. Las revisiones locales se
    guardan 60 s en memoria (FR-6); nada aquí abre una conexión de red."""

    def __init__(self, ctx, clock=time.time):
        self.ctx = ctx
        self.clock = clock
        self._health: tuple[float, dict] | None = None
        self._services: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    def accounts(self):
        found, _ = self.ctx.mail_accounts()
        return found

    def mail(self, account_id):
        from . import mail as mail_mod
        rows = mail_mod.mail_events(self.ctx.ledger_path(), account_id, self.ctx.known_ids())
        return [{k: r[k] for k in ("event_id", "observed_at", "state", "roster", "sender_name",
                                  "sender_address", "subject")} for r in rows]

    def sent(self, account_id):
        from . import thread
        recs = thread.sent_rows(thread.parse_sent_logs(self.ctx.state_dir() / "sent.log"), account_id)
        return [{"at": r["at"], "to": r["to"], "subject": r["subject"], "message_id": r["message_id"]}
                for r in recs]

    def sms(self):
        from ..sms import store as sms_store
        from ..sms import thread as sms_thread
        root = self.ctx.state_dir()
        if not (root / "sms").is_dir():
            return []
        # Sin pasar por Store.__init__, que crea y cambia los permisos de sus carpetas:
        # el Dashboard sólo lee (FR-20; revisión de Ximena en #605). `items()` sólo usa
        # métodos de lectura.
        store = sms_store.Store.__new__(sms_store.Store)
        store.root = root / "sms"
        try:
            items = sms_thread.items(store, root / "events.jsonl", calls=True)
        except OSError:
            return []
        return [{"epoch": i.get("epoch"), "kind": i.get("kind", ""), "status": i.get("status", ""),
                 "name": i.get("name", ""), "number": i.get("number", "")} for i in items]

    def whatsapp(self):
        if not self.ctx.whatsapp_configured():
            return None
        from . import whatsapp_source
        try:
            status = self.ctx.whatsapp().status()
        except whatsapp_source.Failed:
            status = {"state": "service_down"}
        received = []
        for record in _journal(self.ctx.state_dir() / "events.jsonl"):
            if record.get("event_type") != "whatsapp.received":
                continue
            sender = record.get("sender") or {}
            received.append({"at": str(record.get("sent_at") or record.get("observed_at") or ""),
                             "name": str(sender.get("name") or ""), "number": str(sender.get("address") or "")})
        return {"status": {"state": str(status.get("state") or "")}, "received": received}

    def telegram(self):
        if not self.ctx.telegram_configured():
            return None
        status = self.ctx.telegram().status()
        return {"state": str(status.get("state") or "service_down"),
                "bot_username": str(status.get("bot_username") or "")}

    def roster(self):
        import roster as roster_mod
        try:
            count = len(roster_mod.roster_entries(self.ctx.roster_path()))
        except OSError:
            count = 0
        changes = []
        for record in _jsonl(self.ctx.state_dir() / "roster_changes.jsonl"):
            if record.get("type") == "notify" or not record.get("action"):
                continue
            changes.append({"at": str(record.get("at") or ""), "action": str(record.get("action") or ""),
                            "name": str(record.get("name") or ""), "device_id": str(record.get("device_id") or "")})
        return {"count": count, "changes": changes}

    def tokens(self):
        from . import api_tokens
        try:
            recs = api_tokens.list_records(path=api_tokens.path_for(self.ctx.user_file))
        except (OSError, ValueError):
            return []
        return [{"name": str(r.get("name") or ""), "expires_at": r.get("expires_at"),
                 "revoked_at": r.get("revoked_at")} for r in recs]

    def version(self):
        import paths
        out = {"installed": "", "latest": "", "checked_at": ""}
        try:
            out["installed"] = (paths.repo_root() / "VERSION").read_text(encoding="utf-8").strip()
        except (OSError, AttributeError):
            pass
        try:
            first = (self.ctx.state_dir() / "version.check").read_text(encoding="utf-8").splitlines()[0].split()
            if len(first) == 2 and first[0].isdigit():
                out["checked_at"] = dt.datetime.fromtimestamp(int(first[0]), dt.timezone.utc).isoformat()
                out["latest"] = first[1]
        except (OSError, IndexError, ValueError):
            pass
        return out

    def health(self):
        with self._lock:
            if self._health and self.clock() - self._health[0] < HEALTH_TTL_S:
                return self._health[1]
            value = local_health(self.ctx.state_dir(), self.clock())
            self._health = (self.clock(), value)
            return value

    def services(self):
        with self._lock:
            if self._services and self.clock() - self._services[0] < HEALTH_TTL_S:
                return self._services[1]
            value = local_services(self.ctx.state_dir())
            self._services = (self.clock(), value)
            return value


def _jsonl(path: Path) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    out.append(record)
    except OSError:
        pass
    return out


def _journal(path: Path) -> list[dict]:
    import event as ev
    out = []
    for record, _ in ev.read_from(path, 0) or ():
        if isinstance(record, dict):
            out.append(record)
    return out


def _check(name: str, status: str, summary: str) -> dict:
    return {"name": name, "status": status, "summary": summary}


def local_health(state_dir: Path, now: float | None = None) -> dict:
    """Las revisiones rápidas y locales de `doctor` (FR-6): servicios, cola, archivos,
    roster, sesión y pasarela, con las funciones públicas de `healthcheck`. Las de red
    vienen del último `doctor` guardado (`state/doctor.json`), si existe."""
    import healthcheck as hc
    checks = []
    listener = hc.listener_facts()
    checks.append(_unit_check("listener", listener["unit"]))
    age = listener.get("heartbeat_age_seconds")
    if listener["unit"] == "active" and age is not None and age > HEARTBEAT_STALE_S:
        checks.append(_check("listener_heartbeat", "warning", f"the listener's last heartbeat was {age}s ago"))
    checks.append(_unit_check("dispatcher", hc.dispatcher_facts()["unit"]))
    queue = hc.queue_facts()
    if queue.get("damaged_at") is not None:
        checks.append(_check("queue", "blocked", "the event journal is damaged"))
    elif queue.get("pending") and (queue.get("oldest_age_seconds") or 0) > QUEUE_STALE_S:
        checks.append(_check("queue", "warning",
                             f"{queue['pending']} event(s) waiting, the oldest for {queue['oldest_age_seconds']}s"))
    else:
        checks.append(_check("queue", "ok", "the queue is moving"))
    env = hc.env_file()
    try:
        mode = env.stat().st_mode & 0o777
        checks.append(_check("credentials", "ok" if mode == 0o600 else "warning",
                             "credentials file exists with mode 0600" if mode == 0o600
                             else f"credentials file mode is {oct(mode)}"))
    except OSError:
        checks.append(_check("credentials", "blocked", "credentials file is missing"))
    ros = hc.roster_facts()
    checks.append(_check("roster", "ok" if ros.get("addresses") else "blocked",
                         f"roster has {ros.get('addresses', 0)} address(es)" if ros.get("addresses")
                         else "roster has no authorized addresses"))
    for entry in hc.accounts_facts().get("accounts", []):
        if entry.get("enabled"):
            unit = entry["listener"]["unit"]
            checks.append(_check(f"account:{entry['id']}", "ok" if unit == "active" else "warning",
                                 f"account {entry['id']}: listener is {unit}"))
    watch = hc.watch_registry_facts()
    if watch.get("watch_live"):
        checks.append(_check("session_watch", "ok", "an agent session is watching the mail"))
    elif watch.get("watch_expired") or watch.get("watch_orphan") or watch.get("watch_ended"):
        checks.append(_check("session_watch", "warning", "no agent session is watching the mail right now"))
    him = hc.himalaya_facts()
    checks.append(_check("smtp", "ok" if him.get("account_present") else "blocked",
                         "himalaya paynani account is configured" if him.get("account_present")
                         else "himalaya config is missing [accounts.paynani]"))
    phone = hc.sms_phone_facts()
    for text in hc.sms_phone_warnings(phone):
        checks.append(_check("sms_phone", "warning", text.split(":")[0]))
    if phone is not None and not hc.sms_phone_warnings(phone):
        checks.append(_check("sms_phone", "ok", "the paired phone is online"))
    network, network_at = network_checks(_jsonl_one(Path(state_dir) / DOCTOR_FILE),
                                         time.time() if now is None else now)
    return {"checks": checks + network, "network_at": network_at}


def network_checks(saved: dict | None, now: float) -> tuple[list[dict], str]:
    """Las revisiones de red del último `doctor` guardado, con su hora. Una de más de 24 h
    cuenta como `unknown`, con su antigüedad (revisión de Metis en #605): un `doctor`
    viejo no pinta el estado de verde. Sin archivo, una sola `network` en `unknown`."""
    if not saved:
        return [_check("network", "unknown", "the network checks have no saved result")], ""
    network_at = str(saved.get("generated_at") or "")
    at = parse(network_at)
    age = None if at is None else max(0, int(now - at.timestamp()))
    out = []
    for c in saved.get("checks") or []:
        if not isinstance(c, dict) or c.get("name") not in NETWORK_CHECKS:
            continue
        if age is None or age > NETWORK_MAX_AGE_S:
            days = "unknown" if age is None else f"{age // 86400} day(s)"
            out.append(_check(str(c["name"]), "unknown", f"the last {c['name']} check is {days} old"))
        else:
            out.append(_check(str(c["name"]), str(c.get("status") or "unknown"), str(c.get("summary") or "")))
    if not out:
        # Un doctor.json sin la revisión `himalaya` (de una versión anterior, o que no llegó a
        # ella) no deja el estado en verde sin revisión de red (revisión de Metis en #605).
        out.append(_check("network", "unknown", "the network checks have no saved result"))
    return out, network_at


def _jsonl_one(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _unit_check(name: str, unit: str) -> dict:
    if unit == "active":
        return _check(name, "ok", f"{name} service is active")
    if unit == "unknown":
        return _check(name, "unknown", f"{name} unit cannot be queried")
    return _check(name, "blocked", f"{name} service is {unit}")


def local_services(state_dir: Path) -> dict:
    import healthcheck as hc
    listener = hc.listener_facts()
    watch = hc.watch_registry_facts()
    live = watch.get("watch_live") or {}
    phone = hc.sms_phone_facts()
    additional = []
    for entry in hc.accounts_facts().get("accounts", []):
        unit = entry["listener"]["unit"] if entry.get("enabled") else "off"
        additional.append({"id": entry["id"], "email": entry["email"], "enabled": bool(entry.get("enabled")),
                           "unit": unit})
    return {
        "listener": {"unit": listener["unit"], "heartbeat_age_s": listener.get("heartbeat_age_seconds")},
        "dispatcher": {"unit": hc.dispatcher_facts()["unit"]},
        "session": {"live": bool(live), "armed_at": str(live.get("armed_at") or "")},
        "phone": None if phone is None else {
            "online": bool(phone["online"]), "model": phone.get("model", ""),
            "app_version": phone.get("app_version", ""), "last_seen_age_s": phone.get("last_seen_age_s"),
            "battery": (phone.get("battery") or {}).get("pct")},
        "additional": additional,
    }


# ---- En memoria, para las pruebas ------------------------------------------------
class Fake(Source):
    def __init__(self, **data):
        self.data = {"accounts": [{"id": accounts.MAIN, "email": "agent@example.com", "enabled": True,
                                   "agent": True}],
                     "mail": {}, "sent": {}, "sms": [], "whatsapp": None, "telegram": None,
                     "roster": {"count": 0, "changes": []}, "tokens": [],
                     "version": {"installed": "1.0.0", "latest": "1.0.0", "checked_at": ""},
                     "health": {"checks": [_check("listener", "ok", "listener service is active")], "network_at": ""},
                     "services": {"listener": {"unit": "active", "heartbeat_age_s": 5},
                                  "dispatcher": {"unit": "active"}, "session": {"live": True, "armed_at": ""},
                                  "phone": None, "additional": []}}
        self.data.update(data)
        self.calls: list[str] = []

    def _get(self, key):
        self.calls.append(key)
        return self.data[key]

    def accounts(self):
        return self._get("accounts")

    def mail(self, account_id):
        return self._get("mail").get(account_id, [])

    def sent(self, account_id):
        return self._get("sent").get(account_id, [])

    def sms(self):
        return self._get("sms")

    def whatsapp(self):
        return self._get("whatsapp")

    def telegram(self):
        return self._get("telegram")

    def roster(self):
        return self._get("roster")

    def tokens(self):
        return self._get("tokens")

    def version(self):
        return self._get("version")

    def health(self):
        return self._get("health")

    def services(self):
        return self._get("services")


# ---- El modelo de la página ------------------------------------------------------
def _version_tuple(value: str) -> tuple:
    parts = []
    for p in str(value or "").lstrip("v").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def overall(checks: list[dict]) -> str:
    """FR-5: `ok` (verde), `warning` (amarillo: algo en warning o unknown) o `blocked` (rojo)."""
    statuses = {c.get("status") for c in checks}
    if "blocked" in statuses:
        return "blocked"
    if statuses & {"warning", "unknown"}:
        return "warning"
    return "ok"


def build(source: Source, now: dt.datetime, account: str = "") -> dict:
    """
    El modelo de la página. `now` lleva la zona del host (Q6). `account` es el filtro
    del selector (FR-9): "" para todas; una cuenta que no existe cuenta como todas y
    `account_unknown` lo dice.
    """
    tz = now.tzinfo
    today = now.date()
    days = [today - dt.timedelta(days=DAYS - 1 - i) for i in range(DAYS)]
    all_accounts = source.accounts()
    ids = [a["id"] for a in all_accounts]
    unknown = bool(account) and account not in ids
    chosen = [account] if account and not unknown else ids

    # Correo recibido, por cuenta (FR-8, FR-14)
    mail_today = {"received": 0, "handled": 0, "replied": 0, "open": 0}
    per_day = {d: {"closed": 0, "open": 0} for d in days}
    open_notices = []
    activity = []
    notice_since = now - dt.timedelta(days=NOTICE_DAYS)
    mail_by_account = {account_id: source.mail(account_id) for account_id in ids}
    week_replied = 0
    for account_id in ids:
        for row in mail_by_account[account_id]:
            seen = parse(row.get("observed_at"))
            if seen is None:
                continue
            local = seen.astimezone(tz)
            state = row.get("state", "")
            activity.append({"at": local, "channel": "mail", "who": row.get("sender_name") or row.get("sender_address", ""),
                             "what": row.get("subject", ""), "state": state, "account": account_id,
                             "href": mail_href(account_id, row.get("event_id", ""))})
            if account_id not in chosen:
                continue
            is_open = state in OPEN
            if row.get("roster") and is_open and seen >= notice_since:
                open_notices.append({"at": local, "who": row.get("sender_name") or row.get("sender_address", ""),
                                     "subject": row.get("subject", ""), "account": account_id,
                                     "event_id": row.get("event_id", "")})
            day = local.date()
            if day in per_day:
                per_day[day]["open" if is_open else "closed"] += 1
                if state == "replied":
                    week_replied += 1
            if day == today:
                mail_today["received"] += 1
                if state in ("handled", "closed"):
                    mail_today["handled"] += 1
                elif state == "replied":
                    mail_today["replied"] += 1
                elif is_open:
                    mail_today["open"] += 1
        for rec in source.sent(account_id):
            at = parse(rec.get("at"))
            if at is not None:
                activity.append({"at": at.astimezone(tz), "channel": "sent", "who": rec.get("to", ""),
                                 "what": rec.get("subject", ""), "state": "sent", "account": account_id,
                                 "href": mail_href(account_id, sent=rec.get("message_id", ""))})
    open_notices.sort(key=lambda n: n["at"])
    week_received = sum(v["closed"] + v["open"] for v in per_day.values())

    # SMS (FR-8)
    sms_today = {"in": 0, "out": 0, "failed": 0}
    failed_sms = []
    for item in source.sms():
        at = _from_epoch(item.get("epoch"), tz)
        if at is None:
            continue
        kind = item.get("kind", "")
        status = item.get("status", "")
        if kind in ("received", "agent", "human"):
            activity.append({"at": at, "channel": "sms", "who": item.get("name") or item.get("number", ""),
                             "what": "", "state": status or kind, "account": "",
                             "href": "/messages/ver?n=" + _q(item.get("number", ""))})
        elif kind in ("call_missed", "call_answered"):
            activity.append({"at": at, "channel": "call", "who": item.get("name") or item.get("number", ""),
                             "what": "", "state": kind, "account": "",
                             "href": "/messages/ver?n=" + _q(item.get("number", ""))})
        if at.date() != today:
            continue
        if kind == "received":
            sms_today["in"] += 1
        elif kind in ("agent", "human"):
            sms_today["out"] += 1
            if status in ("failed", "rejected", "expired"):
                sms_today["failed"] += 1
                failed_sms.append({"at": at, "who": item.get("name") or item.get("number", ""), "status": status,
                                   "number": item.get("number", "")})

    # WhatsApp (FR-10, FR-16)
    wa = source.whatsapp()
    if wa is not None:
        for rec in wa.get("received") or []:
            at = parse(rec.get("at"))
            if at is not None:
                activity.append({"at": at.astimezone(tz), "channel": "whatsapp",
                                 "who": rec.get("name") or rec.get("number", ""), "what": "", "state": "received",
                                 "account": "", "href": "/whatsapp/messages/ver?n=" + _q(rec.get("number", ""))})

    # Telegram (PRD #609 FR-28): sólo su estado en Servicios.
    tg = source.telegram()

    # Roster (FR-8, FR-16)
    roster = source.roster()
    last_change = None
    for change in roster.get("changes") or []:
        at = parse(change.get("at"))
        if at is None:
            continue
        at = at.astimezone(tz)
        last_change = at if last_change is None or at > last_change else last_change
        activity.append({"at": at, "channel": "roster", "who": change.get("name", ""), "what": change.get("action", ""),
                         "state": "roster", "account": "", "href": "/roster"})

    activity.sort(key=lambda a: a["at"], reverse=True)

    # Estado general y lo que necesita atención (FR-5, FR-12)
    health = source.health()
    checks = list(health.get("checks") or [])
    services = source.services()
    attention = []
    for c in sorted(checks, key=lambda c: -STATUS_ORDER.get(c.get("status"), 1)):
        if c.get("status") != "ok" and not c.get("name", "").startswith("account:"):
            attention.append({"kind": "check", "status": c.get("status"), "name": c.get("name", ""),
                              "summary": c.get("summary", "")})
    for extra in services.get("additional") or []:
        if extra.get("enabled") and extra.get("unit") != "active":
            attention.append({"kind": "account", "status": "warning", "name": extra["id"],
                              "summary": extra.get("email", ""), "unit": extra.get("unit", "")})
    if open_notices:
        attention.append({"kind": "notices", "status": "warning", "count": len(open_notices),
                          "oldest": open_notices[0]})
    if failed_sms:
        attention.append({"kind": "sms_failed", "status": "warning", "count": len(failed_sms),
                          "first": failed_sms[0]})
    soon = []
    for token in source.tokens():
        if token.get("revoked_at"):
            continue
        expires = parse(token.get("expires_at"))
        if expires is not None and expires <= now + dt.timedelta(days=TOKEN_SOON_DAYS):
            # Uno ya vencido y sin revocar también (revisión de Metis en #605): un agente que lo
            # siga usando falla.
            soon.append({"name": token.get("name", ""), "expires": expires.astimezone(tz),
                         "days": max(0, (expires - now).days), "expired": expires < now})
    for token in sorted(soon, key=lambda t: t["expires"]):
        attention.append({"kind": "token", "status": "warning" if token["expired"] else "info", **token})
    version = source.version()
    newer = bool(version.get("latest")) and _version_tuple(version["latest"]) > _version_tuple(version.get("installed", ""))
    if newer:
        attention.append({"kind": "version", "status": "info", "installed": version.get("installed", ""),
                          "latest": version["latest"]})

    ok_count = sum(1 for c in checks if c.get("status") == "ok")
    return {
        "now": now,
        "zone": zone_label(now),
        "account": "" if unknown else account,
        "account_unknown": unknown,
        "accounts": all_accounts,
        "status": overall(checks),
        "checks": checks,
        "checks_ok": ok_count,
        "checks_total": len(checks),
        "network_at": health.get("network_at") or "",
        "mail_today": mail_today,
        "open_notices": len(open_notices),
        "oldest_notice": open_notices[0] if open_notices else None,
        "sms_today": sms_today,
        "roster_count": int(roster.get("count") or 0),
        "roster_last_change": last_change,
        "services": services,
        "whatsapp": None if wa is None else (wa.get("status") or {}).get("state", ""),
        "telegram": None if tg is None else {"state": tg.get("state", ""), "bot_username": tg.get("bot_username", "")},
        "attention": attention,
        "week": [{"day": d, **per_day[d]} for d in days],
        "week_received": week_received,
        "week_replied": week_replied,
        "activity": activity[:ACTIVITY],
        "version": version,
    }


def mail_href(account_id: str, event_id: str = "", *, sent: str = "") -> str:
    """El enlace a un correo, con el mismo ayudante que la lista de la cuenta (`?e=` o `?s=`)."""
    from . import mail_pages
    if sent:
        return mail_pages.href(account_id, {"kind": "out", "message_id": sent})
    return mail_pages.href(account_id, {"kind": "in", "event_id": event_id})


def _q(value: str) -> str:
    from urllib.parse import quote
    return quote(str(value or ""), safe="")


def numbers(model: dict) -> dict:
    """Lo de `/dashboard.json` (FR-19): sólo números y estados. Ni direcciones, ni
    teléfonos, ni asuntos, ni nombres de contactos o tokens."""
    services = model["services"]
    phone = services.get("phone")
    return {
        "status": model["status"],
        "checks_ok": model["checks_ok"],
        "checks_total": model["checks_total"],
        "mail_today": dict(model["mail_today"]),
        "open_notices": model["open_notices"],
        "sms_today": dict(model["sms_today"]),
        "roster_count": model["roster_count"],
        "services": {
            "listener": services["listener"]["unit"],
            "dispatcher": services["dispatcher"]["unit"],
            "session": "live" if services["session"]["live"] else "none",
            "phone": None if phone is None else ("online" if phone["online"] else "offline"),
            "whatsapp": model["whatsapp"],
            "telegram": None if model.get("telegram") is None else model["telegram"]["state"],
        },
        "attention": len(model["attention"]),
        "week": [{"day": w["day"].isoformat(), "closed": w["closed"], "open": w["open"]} for w in model["week"]],
        "updated_at": model["now"].isoformat(timespec="seconds"),
    }
