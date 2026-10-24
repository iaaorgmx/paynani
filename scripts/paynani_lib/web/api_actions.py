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

import secrets
import time

from .. import i18n
from . import mail, thread

READ = "read"
ROSTER_WRITE = "roster.write"
ACCOUNTS_WRITE = "accounts.write"

PAGE = 50
MAX_FIELD = 320


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

    def __init__(self, ctx, record: dict, ip: str, params: dict):
        self.ctx = ctx
        self.record = record
        self.ip = ip
        self.params = params

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
        try:
            out = int(value)
        except (TypeError, ValueError):
            raise ApiError(400, "invalid_parameter", f"{key} must be a whole number.", field=key) from None
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
        raise ApiError(400, "invalid_account", str(exc)) from None
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
        raise ApiError(500, "internal_error", str(exc), checks=checks) from None
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
        raise ApiError(400, "invalid_account", str(exc)) from None
    _notify(call, "removed", account_id, account["email"])
    return {"removed": account_id}


# Acción → (permiso, función). GetTokenInfo y GetUsage (A7), SendSms y GetSmsStatus
# (A4) y ListSmsReplies (A5) se suman aquí en sus tareas.
ACTIONS = {
    "ListAccounts": (READ, list_accounts),
    "ListMail": (READ, list_mail),
    "GetMailThread": (READ, get_mail_thread),
    "ListSmsConversations": (READ, list_sms_conversations),
    "GetSmsThread": (READ, get_sms_thread),
    "ListRoster": (READ, list_roster),
    "SaveRosterContact": (ROSTER_WRITE, save_roster_contact),
    "DeleteRosterContact": (ROSTER_WRITE, delete_roster_contact),
    "GetRules": (READ, get_rules),
    "SaveRules": (ROSTER_WRITE, save_rules),
    "GetDefaultRules": (READ, get_default_rules),
    "SaveDefaultRules": (ROSTER_WRITE, save_default_rules),
    "AddAccount": (ACCOUNTS_WRITE, add_account),
    "RemoveAccount": (ACCOUNTS_WRITE, remove_account),
}


def run(ctx, record: dict, ip: str, params: dict) -> dict:
    """La respuesta de una acción (sin `result` ni `request_id`), o ApiError."""
    action = params.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise ApiError(400, "invalid_action", "Unknown API action.")
    permission, handler = ACTIONS[action]
    granted = record.get("permissions") or []
    if permission not in granted:
        raise ApiError(403, "forbidden", f"This token lacks the {permission} permission.", permission=permission)
    return handler(Call(ctx, record, ip, params))
