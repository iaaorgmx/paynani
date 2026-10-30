"""Owner-only API token screens. All data placed in HTML is escaped here."""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path

from .. import i18n
from . import api_tokens

# Un permiso del Catch-All por canal (PRD #576 FR-13, FR-13b); se marcan a mano. El
# viejo catchall.write ya no se ofrece: la API lo lee como catchall.sms.write.
PERMISSIONS = ("read", "sms.send", "roster.write", "accounts.write", "catchall.sms.write",
               "catchall.whatsapp.write")
EXPIRIES = {"5m": dt.timedelta(minutes=5), "1h": dt.timedelta(hours=1),
            "1d": dt.timedelta(days=1), "7d": dt.timedelta(days=7),
            "30d": dt.timedelta(days=30)}


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def status(record: dict, now: dt.datetime | None = None) -> str:
    if record.get("revoked_at"):
        return "revoked"
    expiry = record.get("expires_at")
    if expiry and dt.datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= (now or dt.datetime.now(dt.timezone.utc)):
        return "expired"
    return "active"


def expiry_from_form(choice: str, custom: str, now: dt.datetime | None = None) -> str | None:
    now = now or dt.datetime.now(dt.timezone.utc)
    if choice == "never":
        return None
    if choice in EXPIRIES:
        return (now + EXPIRIES[choice]).isoformat()
    if choice != "custom":
        raise ValueError("invalid expiry")
    try:
        value = dt.datetime.fromisoformat(custom.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid expiry") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    if value <= now:
        raise ValueError("expiry must be in the future")
    return value.isoformat()


def usage_today(state_dir: Path, prefix: str, now: dt.datetime | None = None) -> int:
    """Count accepted API SMS orders for this prefix on the current UTC date."""
    day = (now or dt.datetime.now(dt.timezone.utc)).date()
    count = 0
    try:
        with (Path(state_dir) / "sms" / "orders.jsonl").open(encoding="utf-8") as rows:
            for line in rows:
                try:
                    row = json.loads(line)
                    stamp = dt.datetime.fromisoformat(str(row.get("at", "")).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
                if (row.get("status") == "queued" and row.get("token_id") == prefix
                        and stamp.astimezone(dt.timezone.utc).date() == day):
                    count += 1
    except FileNotFoundError:
        pass
    return count


def list_body(records: list[dict], query: str, selected: str) -> str:
    t = i18n.th
    shown = [r for r in records if (not selected or status(r) == selected)
             and (not query or query.casefold() in r.get("name", "").casefold()
                  or query.casefold() in r.get("prefix", "").casefold())]
    shown.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    rows = "".join(
        f'<tr><td><a href="/api-tokens/detail?id={e(r["sha256"])}">{e(r.get("name", ""))}</a><br><code>{e(r.get("prefix", ""))}…</code></td>'
        f'<td>{e(", ".join(r.get("permissions", [])))}</td><td>{e(r.get("created_at", ""))}</td>'
        f'<td>{e(r.get("expires_at") or t("web.tokens.never"))}</td>'
        f'<td>{e(r.get("last_used_at") or "—")}</td><td>{t("web.tokens.status." + status(r))}</td></tr>'
        for r in shown)
    options = "".join(f'<option value="{e(value)}"{" selected" if selected == value else ""}>{e(label)}</option>'
                      for value, label in (("", t("web.tokens.all")), ("active", t("web.tokens.status.active")),
                                           ("expired", t("web.tokens.status.expired")),
                                           ("revoked", t("web.tokens.status.revoked"))))
    empty_row = f'<tr><td colspan="6">{t("web.tokens.empty")}</td></tr>'
    return (f'<div class="acciones"><a class="primario" href="/api-tokens/new">{t("web.tokens.create")}</a></div>'
            f'<form method="get" action="/api-tokens" class="token-filter">'
            f'<label>{t("web.tokens.search")} <input name="q" value="{e(query)}"></label>'
            f'<label>{t("web.tokens.filter")} <select name="status">{options}</select></label>'
            f'<button type="submit">{t("web.tokens.apply")}</button></form>'
            f'<div class="token-table-wrap"><table class="token-table"><thead><tr>'
            f'<th>{t("web.tokens.name")}</th><th>{t("web.tokens.permissions")}</th>'
            f'<th>{t("web.tokens.created")}</th><th>{t("web.tokens.expires")}</th>'
            f'<th>{t("web.tokens.last_used")}</th><th>{t("web.tokens.status")}</th>'
            f'</tr></thead><tbody>{rows or empty_row}</tbody></table></div>')


def new_body(csrf: str, *, error: str = "", values: dict | None = None) -> str:
    t = i18n.th
    values = values or {}
    choices = [("5m", "5 min"), ("1h", "1 h"), ("1d", "1 d"), ("7d", "7 d"),
               ("30d", "30 d"), ("custom", t("web.tokens.custom")), ("never", t("web.tokens.never"))]
    options = "".join(f'<option value="{e(key)}"{" selected" if values.get("expiry", "30d") == key else ""}>{e(label)}</option>'
                      for key, label in choices)
    checks = "".join(f'<label class="casilla"><input type="checkbox" name="permission_{p}" value="1"'
                     f'{" checked" if p in values.get("permissions", ["read"]) else ""}> {e(p)}</label>'
                     for p in PERMISSIONS)
    error_notice = f'<p class="error" role="alert">{e(error)}</p>' if error else ""
    return (error_notice +
            f'<form method="post" action="/api-tokens/new" class="formulario">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
            f'<label for="token-name">{t("web.tokens.name")}</label><input id="token-name" name="name" maxlength="100" required value="{e(values.get("name", ""))}">'
            f'<label for="token-expiry">{t("web.tokens.expires")}</label><select id="token-expiry" name="expiry">{options}</select>'
            f'<label for="token-custom">{t("web.tokens.custom_utc")}</label><input id="token-custom" type="datetime-local" name="custom" value="{e(values.get("custom", ""))}">'
            f'<fieldset><legend>{t("web.tokens.permissions")}</legend>{checks}'
            f'<p class="hint">{t("web.tokens.catchall_hint")}</p></fieldset>'
            f'<label for="token-hour">{t("web.tokens.hour")}</label><input id="token-hour" name="sms_per_hour" type="number" min="1" value="{e(values.get("sms_per_hour", "30"))}">'
            f'<label for="token-day">{t("web.tokens.day")}</label><input id="token-day" name="sms_per_day" type="number" min="1" value="{e(values.get("sms_per_day", "200"))}">'
            f'<label class="casilla"><input type="checkbox" name="agent_replies" value="1"{" checked" if values.get("agent_replies") else ""}> {t("web.tokens.agent_replies")}</label>'
            f'<label for="token-password">{t("web.tokens.password")}</label><input id="token-password" name="password" type="password" autocomplete="current-password" required>'
            f'<button class="primario" type="submit">{t("web.tokens.create")}</button></form>')


def created_body(secret: str, record: dict, url: str) -> str:
    t = i18n.th
    message = t("web.tokens.agent_message", token=secret, expires=record.get("expires_at") or t("web.tokens.never"), url=url)
    return (f'<p class="aviso-ok">{t("web.tokens.created_ok")}</p><p>{t("web.tokens.once")}</p>'
            f'<div class="token-secret"><code>{e(secret)}</code> <button type="button" data-copy="secret">{t("web.tokens.copy")}</button></div>'
            f'<label for="token-agent-message">{t("web.tokens.agent_message_label")}</label>'
            f'<textarea id="token-agent-message" class="token-agent-message" readonly>{e(message)}</textarea>'
            f'<button type="button" data-copy="message">{t("web.tokens.copy")}</button>'
            f'<p><a href="/api-tokens">{t("web.tokens.back")}</a></p><script src="/assets/api_tokens.js" defer></script>')


def detail_body(record: dict, csrf: str, state_dir: Path, *, error: str = "", ok: str = "") -> str:
    t = i18n.th
    digest = e(record["sha256"])
    usage = usage_today(state_dir, record.get("prefix", ""))
    fields = (("name", record.get("name")), ("prefix", record.get("prefix")),
              ("permissions", ", ".join(record.get("permissions", []))),
              ("created", record.get("created_at")), ("expires", record.get("expires_at") or t("web.tokens.never")),
              ("last_used", record.get("last_used_at") or "—"),
              ("status", t("web.tokens.status." + status(record))),
              ("hour", record.get("limits", {}).get("sms_per_hour", 30)),
              ("day", record.get("limits", {}).get("sms_per_day", 200)),
              ("used_today", usage))
    details = "".join(f'<dt>{t("web.tokens." + key)}</dt><dd>{e(value)}</dd>' for key, value in fields)
    editable = status(record) == "active"
    forms = ""
    if editable:
        forms = (f'<form method="post" action="/api-tokens/agent-replies" class="formulario">'
                 f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="id" value="{digest}">'
                 f'<label class="casilla"><input type="checkbox" name="agent_replies" value="1"{" checked" if record.get("agent_replies", False) else ""}> {t("web.tokens.agent_replies")}</label>'
                 f'<label>{t("web.tokens.password")}<input type="password" name="password" autocomplete="current-password" required></label>'
                 f'<button class="primario" type="submit">{t("web.tokens.save")}</button></form>'
                 f'<form method="post" action="/api-tokens/revoke" class="formulario">'
                 f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="id" value="{digest}">'
                 f'<label>{t("web.tokens.password")}<input type="password" name="password" autocomplete="current-password" required></label>'
                 f'<button class="peligro" type="submit">{t("web.tokens.revoke")}</button></form>')
    error_notice = f'<p class="error" role="alert">{e(error)}</p>' if error else ""
    saved_notice = f'<p class="aviso-ok">{t("web.tokens.saved")}</p>' if ok else ""
    return (error_notice + saved_notice +
            f'<dl class="token-detail">{details}</dl><p>{t("web.tokens.agent_replies")}: '
            f'{t("web.tokens.yes") if record.get("agent_replies", False) else t("web.tokens.no")}</p>{forms}')
