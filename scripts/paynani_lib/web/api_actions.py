"""
Las acciones de lectura, roster, reglas y cuentas de la API (A3 #495 del PRD #491).

`POST /api/agent` autentica el token (A1 #493) y llega aquí con `action` y sus
parámetros. Cada acción pide un permiso (FR-5): sin él responde `forbidden` y dice
cuál falta. Las acciones usan los mismos servicios que PaynaniWeb y PaynaniApp:
el roster y las reglas pasan por `roster_api.RosterService` (§11 de SMS_GATEWAY.md),
el correo por `mail` y `thread`, y los SMS por `sms.thread`. Perfil y contraseña
de la web no están en la API (FR-4).
"""
from __future__ import annotations

import re
import secrets
import sys
import time

from .. import i18n
from . import mail, thread

READ = "read"
ROSTER_WRITE = "roster.write"
ACCOUNTS_WRITE = "accounts.write"
# PRD #535 FR-P2: activar el Catch-All deja que el agente lea los SMS de números fuera
# del roster, así que no va dentro de roster.write.
CATCHALL_WRITE = "catchall.write"
SMS_SEND = "sms.send"

PAGE = 50
MAX_FIELD = 320


_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"():,]+")


def _public(exc: Exception) -> str:
    """El mensaje de un error para la respuesta, sin rutas del servidor."""
    return _PATH.sub("<path>", str(exc))


class ApiError(Exception):
    """Una respuesta de error de la API: estado HTTP, código, mensaje y campos extra."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


class Call:
    """Lo que una acción necesita: el contexto de la web, el token, la dirección y los parámetros."""

    def __init__(self, ctx, record: dict, ip: str, params: dict, request_id: str = ""):
        self.ctx = ctx
        self.record = record
        self.ip = ip
        self.params = params
        self.request_id = request_id

    def text(self, key: str, default: str = "", limit: int = MAX_FIELD) -> str:
        value = self.params.get(key, default)
        if value is None:
            return default
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ApiError(400, "invalid_parameter", f"{key} must be text.", field=key)
        return str(value)[:limit]

    def number(self, key: str, default: int | None = None) -> int | None:
        value = self.params.get(key)
        if value in (None, ""):
            return default
        if isinstance(value, bool):
            raise ApiError(400, "invalid_parameter", f"{key} must be a whole number.", field=key)
        # Sólo un entero de JSON o un texto de dígitos: 1.5 o "1.5" no se truncan a 1, porque en
        # SaveRosterContact o DeleteRosterContact eso tocaría otra fila.
        if isinstance(value, int):
            out = value
        elif isinstance(value, str) and re.fullmatch(r"\s*[+-]?[0-9]+\s*", value):
            out = int(value)
        else:
            raise ApiError(400, "invalid_parameter", f"{key} must be a whole number.", field=key)
        if out < 0:
            raise ApiError(400, "invalid_parameter", f"{key} cannot be negative.", field=key)
        return out

    def required(self, key: str, limit: int = MAX_FIELD) -> str:
        value = self.text(key, limit=limit).strip()
        if not value:
            raise ApiError(400, "missing_parameter", f"{key} is required.", field=key)
        return value

    def roster(self, kind: str, **fields) -> dict:
        """Un pedido de §11 al servicio del roster, como lo hacen la web y PaynaniApp."""
        msg = {"type": kind, "id": "q_" + secrets.token_hex(16), **fields}
        res = self.ctx.roster_service().handle(msg, f"api:{self.record.get('prefix', '')}:{self.ip}")
        if res.get("type") == "result":
            return res.get("data") or {}
        code = str(res.get("code") or "invalid")
        status = {"conflict": 409, "not_found": 404, "owner_row": 403, "busy": 503}.get(code, 400)
        extra = {k: res[k] for k in ("field", "reason", "detail", "etag") if k in res}
        raise ApiError(status, code, str(res.get("detail") or code), **extra)


def _account_value(value: str):
    """`main` o vacío es la cuenta del agente, como en la web."""
    return None if value in ("", "main") else value


def _mail_account(call: Call) -> dict:
    account_id = call.text("account", "main").strip() or "main"
    accounts, _ = call.ctx.mail_accounts()
    match = next((a for a in accounts if a["id"] == account_id), None)
    if match is None:
        raise ApiError(404, "not_found", "No such mail account.", field="account")
    return match


def _mail_rows(call: Call, account_id: str) -> list[dict]:
    received = mail.mail_events(call.ctx.ledger_path(), account_id, call.ctx.known_ids())
    sent = thread.sent_rows(thread.parse_sent_logs(call.ctx.state_dir() / "sent.log"), account_id)
    return thread.mailbox(received, sent)


def _mail_row(row: dict) -> dict:
    """Una fila de la lista sin el sobre interno."""
    if row["kind"] == "in":
        keys = ("event_id", "sender_name", "sender_address", "subject", "observed_at", "sent_at", "roster",
                "state", "state_at")
    else:
        keys = ("message_id", "to", "cc", "bcc", "subject")
    out = {"kind": row["kind"], "at": row.get("at", "")}
    out.update({k: row.get(k, "") for k in keys})
    return out


# ---- cuentas, correo y SMS (read) -------------------------------------------------

def list_accounts(call: Call) -> dict:
    accounts, error = call.ctx.mail_accounts()
    out = {"accounts": [{"id": a["id"], "email": a["email"], "enabled": a["enabled"], "agent": a["agent"]}
                        for a in accounts]}
    if error:
        out["warning"] = "accounts.json could not be read; only the agent account is listed."
    return out


def list_mail(call: Call) -> dict:
    account = _mail_account(call)
    rows = _mail_rows(call, account["id"])
    offset = call.number("offset", 0)
    chunk, nxt = mail.page_of(rows, offset)
    return {"account": account["id"], "total": len(rows), "offset": offset, "next_offset": nxt,
            "mail": [_mail_row(r) for r in chunk]}


def get_mail_thread(call: Call) -> dict:
    account = _mail_account(call)
    event_id = call.text("event_id").strip()
    message_id = call.text("message_id").strip()
    if not event_id and not message_id:
        raise ApiError(400, "missing_parameter", "event_id or message_id is required.", field="event_id")
    rows = _mail_rows(call, account["id"])
    if message_id:
        row = next((r for r in rows if r["kind"] == "out" and r["message_id"] == message_id), None)
    else:
        row = next((r for r in rows if r["kind"] == "in" and r["event_id"] == event_id), None)
    if row is None:
        raise ApiError(404, "not_found", "No such mail in this account.")
    convo = thread.conversation(rows, row, own=account["email"])
    try:
        env = mail.env_for(account["id"], call.ctx.accounts_file, call.ctx.env_path())
        loaded = thread.load(env, convo, connect=call.ctx.imap_connect, uidvalidity=call.ctx.imap_uidvalidity)
    except mail.MailError as exc:
        loaded = {thread.key(r): {"error": exc} for r in convo}
    messages = []
    for r in convo:
        item = _mail_row(r)
        got = loaded.get(thread.key(r), {})
        if "message" in got:
            item["message"] = got["message"]
        else:
            item["error"] = getattr(got.get("error"), "code", "gone")
        item["selected"] = r is row
        messages.append(item)
    return {"account": account["id"], "messages": messages}


def _sms_items(call: Call) -> list[dict]:
    from ..sms import store as sms_store
    from ..sms import thread as sms_thread
    store = sms_store.Store(call.ctx.state_dir())
    return sms_thread.items(store, call.ctx.state_dir() / "events.jsonl", calls=True)


def list_sms_conversations(call: Call) -> dict:
    from ..sms import thread as sms_thread
    convs = sms_thread.conversations(_sms_items(call))
    names = call.ctx.phone_names()
    offset = call.number("offset", 0)
    chunk = convs[offset:offset + PAGE]
    nxt = offset + PAGE if offset + PAGE < len(convs) else None
    out = []
    for c in chunk:
        out.append({"number": c["number"], "name": names.get(c["number"]) or c["name"], "count": c["count"],
                    "missed_calls": c["missed"], "last": c["last"]})
    return {"total": len(convs), "offset": offset, "next_offset": nxt, "conversations": out}


def get_sms_thread(call: Call) -> dict:
    from ..sms import cli as sms_cli
    from ..sms import store as sms_store
    number = call.required("number", 40)
    mine = [i for i in _sms_items(call) if i["number"] == number]
    if not mine:
        raise ApiError(404, "not_found", "No messages with that number.", field="number")
    # Como la web: los PAGE más recientes desde `offset`, en orden de hora.
    offset = call.number("offset", 0)
    end = max(0, len(mine) - offset)
    start = max(0, end - PAGE)
    names = call.ctx.phone_names()
    who = names.get(number) or next((i["name"] for i in mine if i["name"]), "")
    pause = sms_cli.human_pause(sms_store.Store(call.ctx.state_dir()), number)
    return {"number": number, "name": who, "total": len(mine), "offset": offset,
            "next_offset": offset + PAGE if start > 0 else None, "agent_paused_until": pause,
            "items": mine[start:end]}


# ---- WhatsApp (WA-6 #558, PRD #550 FR-26) -------------------------------------------
# Sólo lectura, con el permiso `read`. Las dos acciones le preguntan al servicio
# paynani-whatsapp por control.sock, como PaynaniWeb, con `by: api`. El servicio aplica
# FR-16a: de un número fuera del roster sólo salen la hora y la dirección (`hidden`),
# salvo un mensaje que llegó con el Catch-All mientras siga activo. La API no tiene su
# propia copia de los hilos y no puede saltarse esa regla.
WA_LIMIT_MAX = 100
_WA_BEFORE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$")


def _wa_page(call: Call) -> dict:
    limit = call.number("limit", PAGE)
    if not 1 <= limit <= WA_LIMIT_MAX:
        raise ApiError(400, "invalid_parameter", f"limit must be from 1 to {WA_LIMIT_MAX}.", field="limit")
    before = call.text("before", limit=40).strip() or None
    if before is not None and not _WA_BEFORE.match(before):
        raise ApiError(400, "invalid_parameter", "before must be the next_before you got.", field="before")
    return {"limit": limit, "before": before}


def _whatsapp(call: Call, kind: str, **fields) -> dict:
    from . import whatsapp_source
    if not call.ctx.whatsapp_configured():
        raise ApiError(503, "whatsapp_unavailable", "WhatsApp is not set up on this install.")
    try:
        return call.ctx.whatsapp().request(kind, by="api", **fields)
    except whatsapp_source.Failed as exc:
        if exc.code == "not_found":
            raise ApiError(404, "not_found", "No WhatsApp messages with that number.", field="number") from None
        if exc.code == "invalid":
            field = str(exc.fields.get("field") or "number")
            raise ApiError(400, "invalid_parameter", f"{field} is not valid.", field=field) from None
        raise ApiError(503, "whatsapp_unavailable",
                       "The WhatsApp service is not answering; try again in a minute.") from None


def list_whatsapp_conversations(call: Call) -> dict:
    data = _whatsapp(call, "whatsapp.threads", **_wa_page(call))
    return {"threads": data.get("threads") or [], "next_before": data.get("next_before")}


def get_whatsapp_thread(call: Call) -> dict:
    import phone as phone_mod
    raw = call.required("number", 40)
    number = phone_mod.to_e164(raw, phone_mod.default_region()) or raw
    return _whatsapp(call, "whatsapp.thread", number=number, **_wa_page(call))


# ---- roster y reglas ---------------------------------------------------------------

def list_roster(call: Call) -> dict:
    data = call.roster("roster.list", account=_account_value(call.text("account").strip()))
    accounts = call.roster("roster.accounts")
    return {**data, "accounts": accounts.get("accounts", [])}


def _phones(call: Call) -> list[str]:
    import phone as phone_mod
    raw = call.params.get("phones", "")
    if isinstance(raw, list):
        values = [str(p) for p in raw if isinstance(p, (str, int)) and not isinstance(p, bool)]
    elif isinstance(raw, str):
        values = raw.split(",")
    else:
        raise ApiError(400, "invalid_parameter", "phones must be a list or comma-separated text.", field="phones")
    region = phone_mod.default_region()
    # Como la web y PaynaniApp: E.164 si se puede; si no, tal cual y el servicio dice qué campo falla.
    return [phone_mod.to_e164(p.strip(), region) or p.strip() for p in values if p.strip()]


def save_roster_contact(call: Call) -> dict:
    member = {"name": call.text("name").strip(), "email": call.text("email").strip(),
              "type": call.text("type").strip(), "github": call.text("github").strip(), "phones": _phones(call)}
    return call.roster("roster.save", account=_account_value(call.text("account").strip()),
                       row=call.number("row"), member=member, etag=call.text("etag"))


def delete_roster_contact(call: Call) -> dict:
    row = call.number("row")
    if row is None:
        raise ApiError(400, "missing_parameter", "row is required.", field="row")
    return call.roster("roster.delete", account=_account_value(call.text("account").strip()), row=row,
                       etag=call.text("etag"))


def _rules_row(call: Call) -> int:
    row = call.number("row")
    if row is None:
        raise ApiError(400, "missing_parameter", "row is required.", field="row")
    return row


def get_rules(call: Call) -> dict:
    return call.roster("rules.get", account=_account_value(call.text("account").strip()), row=_rules_row(call),
                       roster_etag=call.text("roster_etag"))


def save_rules(call: Call) -> dict:
    return call.roster("rules.save", account=_account_value(call.text("account").strip()), row=_rules_row(call),
                       text=call.text("text", limit=20000).replace("\r\n", "\n"), etag=call.text("etag"),
                       roster_etag=call.text("roster_etag"))


def get_default_rules(call: Call) -> dict:
    return call.roster("rules.get_default")


def save_default_rules(call: Call) -> dict:
    return call.roster("rules.save_default", text=call.text("text", limit=20000).replace("\r\n", "\n"),
                       etag=call.text("etag"))


# ---- Catch-All (PRD #535 FR-P1, FR-P2) ----------------------------------------------

def get_catch_all(call: Call) -> dict:
    return call.roster("catchall.get")


def save_catch_all(call: Call) -> dict:
    enabled = call.params.get("enabled")
    if not isinstance(enabled, bool):
        raise ApiError(400, "invalid_parameter", "enabled must be true or false.", field="enabled")
    return call.roster("catchall.save", enabled=enabled,
                       text=call.text("text", limit=40000).replace("\r\n", "\n"), etag=call.text("etag"))


# ---- cuentas (accounts.write) ------------------------------------------------------

def _notify(call: Call, kind: str, account_id: str, email: str) -> None:
    """El mismo aviso al dueño que manda la web, diciendo que vino de la API."""
    when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
    what = i18n.t(f"web.acctmail.what_{kind}", email=email, id=account_id)
    what += f" (API token {call.record.get('name', '')} {call.record.get('prefix', '')}…)"
    user = call.ctx.user()
    if user:
        call.ctx.notifier.owner(user, i18n.t(f"web.acctmail.{kind}", email=email),
                                i18n.t("web.acctmail.body", ip=call.ip, when=when, what=what))


def add_account(call: Call) -> dict:
    from .. import accounts_cli
    values = {k: call.text(k).strip() for k in
              ("id", "email", "from_name", "imap_host", "imap_port", "smtp_host", "smtp_port", "mailbox")}
    password = call.text("password", limit=1024).strip("\r\n")
    if not password:
        raise ApiError(400, "missing_parameter", "password is required.", field="password")
    if any(c in password for c in "\r\n\0"):
        raise ApiError(400, "invalid_parameter", "password cannot contain line breaks.", field="password")
    ops = call.ctx.account_ops
    try:
        prep = ops.prepare_add(values["id"], values["email"], values["imap_host"], values["imap_port"] or 993,
                               values["smtp_host"], values["smtp_port"] or 465, values["from_name"],
                               [values["mailbox"]] if values["mailbox"] else None)
    except accounts_cli.AccountOpError as exc:
        raise ApiError(400, "invalid_account", _public(exc)) from None
    entry = prep["entry"]
    checks = []
    imap = call.ctx.probe_imap(entry["imap"]["host"], entry["imap"]["port"], entry["email"], password)
    checks.append({"step": "imap", "ok": imap["ok"], "detail": imap["steps"]})
    ok = imap["ok"]
    if ok and entry.get("smtp"):
        smtp = call.ctx.probe_smtp(entry["smtp"]["host"], entry["smtp"]["port"], entry["email"], password)
        checks.append({"step": "smtp", "ok": smtp["ok"], "detail": smtp["steps"]})
        ok = smtp["ok"]
    if not ok:
        raise ApiError(400, "probe_failed", "The mail server rejected the connection or the login.", checks=checks)
    try:
        ops.commit_add(prep, password)
    except accounts_cli.AccountOpError as exc:
        # El detalle (rutas, el error del sistema) va al log; la respuesta es genérica.
        sys.stderr.write(f"paynani-web: api AddAccount commit failed: {exc}\n")
        raise ApiError(500, "internal_error", "The account could not be saved. Nothing was changed.",
                       checks=checks) from None
    started = ops._service("enable", entry["id"])
    _notify(call, "added", entry["id"], entry["email"])
    return {"account": {"id": entry["id"], "email": entry["email"]}, "listener_started": bool(started),
            "checks": checks}


def remove_account(call: Call) -> dict:
    from .. import accounts_cli
    account_id = call.required("account")
    accounts, _ = call.ctx.mail_accounts()
    account = next((a for a in accounts if a["id"] == account_id), None)
    if account is None:
        raise ApiError(404, "not_found", "No such mail account.", field="account")
    if account["agent"]:
        raise ApiError(403, "agent_account", "The agent's own account cannot be removed.", field="account")
    try:
        call.ctx.account_ops.remove_account(account_id)
    except accounts_cli.AccountOpError as exc:
        raise ApiError(400, "invalid_account", _public(exc)) from None
    _notify(call, "removed", account_id, account["email"])
    return {"removed": account_id}


# --- SMS por la API (A4 #496, PRD #491 FR-6 a FR-10) ---------------------------------

IDEMPOTENCY_KEY = re.compile(r"[\x21-\x7e]{1,128}")
API_ORDER = re.compile(r"a_[0-9a-f]{32}")


def _sms_store(call: Call):
    from ..sms import store as sms_store
    return sms_store.Store(call.ctx.state_dir())


def _sms_region(store) -> str | None:
    """La región de la SIM del teléfono emparejado, o la de la instalación (como la web)."""
    import phone as phone_mod
    for sim in (store.device() or {}).get("sims") or []:
        country = str((sim or {}).get("country") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", country):
            return country
    return phone_mod.default_region()


def _phone_online(call: Call) -> bool:
    from ..sms import health
    facts = health.phone_facts(call.ctx.state_dir())
    return bool(facts and facts["online"])


def _order_view(store, order: dict) -> dict:
    """Una orden de la API como la ve quien la creó: su último estado y la historia."""
    from ..sms import thread as sms_thread
    oid = order["id"]
    history = []
    for rec in store.order_statuses(oid):
        item = {"status": rec.get("status", ""), "at": rec.get("at", "")}
        if rec.get("error") not in (None, ""):
            item["error"] = str(rec["error"])
        history.append(item)
    queued_at = next((h["at"] for h in history if h["status"] == "queued"), "")
    current = next((h for h in reversed(history) if h["status"] != "queued"), None)
    status = current["status"] if current else "queued"
    # Como en la web (PRD #489 FR-7): en cola después de su hora es vencida, aunque la
    # pasarela sólo la marque cuando el teléfono vuelva.
    if status == "queued" and sms_thread._past(order.get("expires_at")):
        status = "expired"
    view = {"id": oid, "to": order.get("to", ""), "status": status, "queued_at": queued_at,
            "expires_at": order.get("expires_at", ""), "history": history}
    if current and current.get("error"):
        view["error"] = current["error"]
    return view


def send_sms(call: Call) -> dict:
    from ..sms import cli as sms_cli
    from ..sms import outgoing
    key = call.required("idempotency_key", limit=129)
    if not IDEMPOTENCY_KEY.fullmatch(key):
        raise ApiError(400, "invalid_parameter",
                       "idempotency_key must be 1 to 128 printable ASCII characters without spaces.",
                       field="idempotency_key")
    to = call.required("to", limit=41)
    text = call.text("text", limit=outgoing.MAX_TEXT + 1)
    store = _sms_store(call)
    try:
        number = outgoing.normalize(to, _sms_region(store))
    except outgoing.Refused as exc:
        raise ApiError(400, exc.code, "to is not a phone number that can be read.", field="to") from None
    token_id = call.record.get("prefix", "")
    # Una llave repetida devuelve la misma orden antes de cualquier otra revisión: el
    # reintento de un SendSms que sí salió no debe responder no_phone, app_outdated,
    # opted_out ni quota_exceeded aunque el estado haya cambiado (revisión de #522).
    earlier = outgoing.find_idempotent(store, token_id, key)
    if earlier is None:
        if not store.device():
            raise ApiError(409, "no_phone", "There is no paired phone to send from.")
        if not store.accepts("api"):
            raise ApiError(409, "app_outdated", "The paired phone runs a PaynaniApp that does not accept API orders. "
                                                "Update it to 0.9.0 or later.")
        if store.opted_out(number):
            raise ApiError(403, "opted_out", "This number opted out of API messages (STOP).", to=number)
        until = sms_cli.human_pause(store, number)
        if until:
            raise ApiError(409, "human_replied",
                           "The owner just texted this number; the API cannot write to it until then.",
                           to=number, until=until)
    limits = call.record.get("limits") or {}
    per_hour = limits.get("sms_per_hour", 30)
    per_day = limits.get("sms_per_day", 200)
    try:
        order = outgoing.queue(store, to=number, text=text, origin="api", token=call.record.get("name", ""),
                               token_id=token_id, idempotency_key=key, per_hour=per_hour, per_day=per_day,
                               source=call.ip, region=_sms_region(store))
    except outgoing.Refused as exc:
        if exc.code in ("rate_limited", "quota_exceeded"):
            if exc.code == "quota_exceeded":
                _daily_limit_alert(call, store, per_day)
            raise ApiError(429, "quota_exceeded", exc.message, retry_at=exc.retry_at) from None
        if exc.code == "idempotency_conflict":
            raise ApiError(409, "idempotency_conflict",
                           "This idempotency_key was already used with another number or text.",
                           order_id=exc.order_id) from None
        if exc.code in ("empty_text", "text_too_long"):
            raise ApiError(400, exc.code, exc.message, field="text") from None
        raise ApiError(400, exc.code, exc.message) from None
    duplicate = bool(order.pop("duplicate", False))
    if not duplicate:
        _daily_limit_alert(call, store, per_day)
    online = _phone_online(call)
    out = {"order": _order_view(store, order), "duplicate": duplicate, "phone_online": online}
    if not online:
        out["notice"] = (f"The phone is disconnected. The order stays queued and expires after "
                         f"{outgoing.DEFAULT_TTL_MIN} minutes if the phone does not reconnect.")
    return out


def _daily_limit_alert(call: Call, store, per_day: int) -> None:
    """One owner alert when this token reaches its rolling 24-hour SMS limit."""
    from ..sms import outgoing
    prefix = call.record.get("prefix", "")
    if len(outgoing.recent_queued(store, "api", token_id=prefix, window_s=outgoing.DAY_S)) < per_day:
        return
    try:
        first = call.ctx.api_security.record_once("daily_quota_alert", call.request_id, prefix, call.ip)
    except (OSError, ValueError):
        sys.stderr.write(f"paynani-web: API daily quota audit unavailable for {call.request_id}\n")
        return
    if first:
        call.ctx.notifier.owner(call.ctx.user(), "Paynani API: tope diario de SMS",
                                f"El token {call.record.get('name', '')} ({prefix}) alcanzó su tope "
                                f"de {per_day} SMS en 24 horas. Revisa state/api_security.jsonl.")


def get_token_info(call: Call) -> dict:
    """Metadata for the calling token; never its digest or cleartext value."""
    from . import api_tokens
    record = api_tokens.get_record(call.record["sha256"], path=api_tokens.path_for(call.ctx.user_path())) or call.record
    return {key: record.get(key) for key in ("name", "prefix", "permissions", "limits", "created_at",
                                              "expires_at", "last_used_at")}


def get_usage(call: Call) -> dict:
    """Accepted API calls and queued SMS for this token in rolling windows."""
    from ..sms import outgoing
    store = _sms_store(call)
    prefix = call.record.get("prefix", "")
    hour = len(outgoing.recent_queued(store, "api", token_id=prefix, window_s=outgoing.HOUR_S))
    day = len(outgoing.recent_queued(store, "api", token_id=prefix, window_s=outgoing.DAY_S))
    limits = call.record.get("limits") or {}
    return {"calls": {**call.ctx.api_security.calls(prefix), "per_minute": 60},
            "sms": {"hour": hour, "day": day,
                    "per_hour": limits.get("sms_per_hour", 30), "per_day": limits.get("sms_per_day", 200)}}


def get_sms_status(call: Call) -> dict:
    order_id = call.required("order_id", limit=40)
    if not API_ORDER.fullmatch(order_id):
        raise ApiError(400, "invalid_parameter", "order_id must be an API order id (a_…).", field="order_id")
    store = _sms_store(call)
    order = store.order(order_id)
    queued = next((r for r in store.order_statuses(order_id) if r.get("status") == "queued"), None)
    # Sólo el token que la creó la ve: otro token recibe lo mismo que una orden inexistente.
    if order is None or not queued or queued.get("token_id") != call.record.get("prefix"):
        raise ApiError(404, "not_found", "No such order for this token.", field="order_id")
    return {"order": _order_view(store, order)}


# --- Respuestas a la API (A5 #497, PRD #491 FR-11) ----------------------------------------

REPLIES_MAX = 200
REPLIES_WINDOW_S = 7 * 86400


def list_sms_replies(call: Call) -> dict:
    """
    Los SMS que llegaron desde `since` y que responden a una conversación de ESTE token
    (la pasarela los marca con `api_reply`), del más viejo al más nuevo, hasta 200.
    `since` es una hora ISO 8601 con zona, de hace 7 días como mucho.
    """
    import event as ev
    from ..sms import api_replies
    from ..sms import thread as sms_thread
    since_raw = call.required("since", limit=40)
    since = api_replies._epoch(since_raw) if re.search(r"(Z|[+-]\d\d:?\d\d)$", since_raw) else None
    now = time.time()
    if since is None or since > now + 60:
        raise ApiError(400, "invalid_parameter", "since must be an ISO 8601 time with a time zone, not in the future.",
                       field="since")
    if since < now - REPLIES_WINDOW_S:
        raise ApiError(400, "invalid_parameter", "since can be at most 7 days ago.", field="since")
    store = _sms_store(call)
    token_id = call.record.get("prefix", "")
    out = []
    truncated = False
    for record, _ in ev.read_from(call.ctx.state_dir() / "events.jsonl", 0) or ():
        if not isinstance(record, dict) or record.get("event_type") != ev.SMS_RECEIVED:
            continue
        reply = record.get("api_reply") or {}
        if reply.get("token_id") != token_id:
            continue
        stamp = str(record.get("sent_at") or record.get("observed_at") or "")
        epoch, _local = sms_thread.when(stamp)
        if epoch < since:
            continue
        if len(out) >= REPLIES_MAX:
            truncated = True
            break
        message_id = str(record.get("provider_id", "")).split(":", 1)[-1]
        saved = store.inbox(message_id) or {}
        item = {"event_id": record.get("event_id", ""), "from": (record.get("sender") or {}).get("address", ""),
                "text": str(saved.get("text", "")), "received_at": stamp, "in_reply_to": reply.get("order_id", "")}
        if record.get("api_optout"):
            item["opt_out"] = record["api_optout"]
        out.append(item)
    return {"since": since_raw, "replies": out, "truncated": truncated}


# Acción → (permiso, función). None means any valid API token may call it.
ACTIONS = {
    "GetTokenInfo": (None, get_token_info),
    "GetUsage": (None, get_usage),
    "ListAccounts": (READ, list_accounts),
    "ListMail": (READ, list_mail),
    "GetMailThread": (READ, get_mail_thread),
    "ListSmsConversations": (READ, list_sms_conversations),
    "GetSmsThread": (READ, get_sms_thread),
    "ListWhatsAppConversations": (READ, list_whatsapp_conversations),
    "GetWhatsAppThread": (READ, get_whatsapp_thread),
    "ListRoster": (READ, list_roster),
    "SaveRosterContact": (ROSTER_WRITE, save_roster_contact),
    "DeleteRosterContact": (ROSTER_WRITE, delete_roster_contact),
    "GetRules": (READ, get_rules),
    "SaveRules": (ROSTER_WRITE, save_rules),
    "GetDefaultRules": (READ, get_default_rules),
    "SaveDefaultRules": (ROSTER_WRITE, save_default_rules),
    "GetCatchAll": (READ, get_catch_all),
    "SaveCatchAll": (CATCHALL_WRITE, save_catch_all),
    "AddAccount": (ACCOUNTS_WRITE, add_account),
    "RemoveAccount": (ACCOUNTS_WRITE, remove_account),
    "SendSms": (SMS_SEND, send_sms),
    "GetSmsStatus": (SMS_SEND, get_sms_status),
    "ListSmsReplies": (READ, list_sms_replies),
}


def run(ctx, record: dict, ip: str, params: dict, request_id: str = "") -> dict:
    """La respuesta de una acción (sin `result` ni `request_id`), o ApiError."""
    action = params.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise ApiError(400, "invalid_action", "Unknown API action.")
    permission, handler = ACTIONS[action]
    granted = record.get("permissions") or []
    if permission is not None and permission not in granted:
        raise ApiError(403, "forbidden", f"This token lacks the {permission} permission.", permission=permission)
    return handler(Call(ctx, record, ip, params, request_id))
