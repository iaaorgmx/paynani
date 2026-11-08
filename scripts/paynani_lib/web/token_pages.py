"""Owner-only API token screens. All data placed in HTML is escaped here."""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path

from .. import i18n
from . import api_tokens, when
from .shell import ROW_CHEVRON

# Un permiso del Catch-All por canal (PRD #576 FR-13, FR-13b); se marcan a mano. El
# viejo catchall.write ya no se ofrece: la API lo lee como catchall.sms.write.
PERMISSIONS = ("read", "telegram.read", "sms.send", "roster.write", "accounts.write", "catchall.sms.write",
               "catchall.whatsapp.write", "catchall.telegram.write")
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


def create_from_values(values: dict, *, path: Path) -> tuple[str, dict]:
    """
    Crea un API Token con lo que llega del formulario de PaynaniWeb o de la API del dueño
    (`CreateApiToken`, iaaorgmx/paynani#721): la misma validación en los dos. `values` trae
    name, expiry, custom, permissions (lista), sms_per_hour, sms_per_day y agent_replies.
    ValueError si algo no vale; OSError si no se pudo guardar.
    """
    name = str(values.get("name", "")).strip()
    permissions = list(values.get("permissions") or [])
    if not name or len(name) > 100 or not permissions or any(p not in PERMISSIONS for p in permissions):
        raise ValueError("invalid name or permissions")
    hour, day = int(values.get("sms_per_hour", "")), int(values.get("sms_per_day", ""))
    if not (1 <= hour <= 100000 and 1 <= day <= 100000):
        raise ValueError("invalid limits")
    expiry = expiry_from_form(str(values.get("expiry", "")), str(values.get("custom", "")))
    return api_tokens.create(name, expires_at=expiry, permissions=permissions,
                             limits={"sms_per_hour": hour, "sms_per_day": day},
                             agent_replies=bool(values.get("agent_replies")), path=path)


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


def list_body(records: list[dict], query: str, selected: str, *, notice: str = "") -> str:
    t = i18n.th
    flash = f'<p class="aviso-ok" role="status">{e(notice)}</p>' if notice else ""
    shown = [r for r in records if (not selected or status(r) == selected)
             and (not query or query.casefold() in r.get("name", "").casefold()
                  or query.casefold() in r.get("prefix", "").casefold())]
    shown.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    rows = "".join(
        f'<tr><td><a href="/api-tokens/detail?id={e(r["sha256"])}">{e(r.get("name", ""))}</a><br><code>{e(r.get("prefix", ""))}…</code></td>'
        f'<td>{e(", ".join(r.get("permissions", [])))}</td><td>{e(r.get("created_at", ""))}</td>'
        f'<td>{e(r.get("expires_at") or t("web.tokens.never"))}</td>'
        f'<td>{e(r.get("last_used_at") or "—")}</td><td>{t("web.tokens.status." + status(r))}</td>'
        # El chevron de las listas (#717): también abre el detalle.
        f'<td class="token-ir"><a href="/api-tokens/detail?id={e(r["sha256"])}" aria-label="{e(r.get("name", ""))}">{ROW_CHEVRON}</a></td></tr>'
        for r in shown)
    options = "".join(f'<option value="{e(value)}"{" selected" if selected == value else ""}>{e(label)}</option>'
                      for value, label in (("", t("web.tokens.all")), ("active", t("web.tokens.status.active")),
                                           ("expired", t("web.tokens.status.expired")),
                                           ("revoked", t("web.tokens.status.revoked"))))
    empty_row = f'<tr><td colspan="7">{t("web.tokens.empty")}</td></tr>'
    return (f'{flash}<div class="acciones"><a class="primario" href="/api-tokens/new">{t("web.tokens.create")}</a></div>'
            f'<form method="get" action="/api-tokens" class="token-filter">'
            f'<label>{t("web.tokens.search")} <input name="q" value="{e(query)}"></label>'
            f'<label>{t("web.tokens.filter")} <select name="status">{options}</select></label>'
            f'<button type="submit">{t("web.tokens.apply")}</button></form>'
            f'<div class="token-table-wrap"><table class="token-table"><thead><tr>'
            f'<th>{t("web.tokens.name")}</th><th>{t("web.tokens.permissions")}</th>'
            f'<th>{t("web.tokens.created")}</th><th>{t("web.tokens.expires")}</th>'
            f'<th>{t("web.tokens.last_used")}</th><th>{t("web.tokens.status")}</th><th aria-hidden="true"></th>'
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


def _time(stamp: str | None) -> str:
    """Fecha y hora legibles, como en «Connected apps»: `<time>` que time.js pasa a la zona del navegador."""
    if not stamp:
        return i18n.th("web.tokens.never")
    iso, shown, title = when.render(stamp, i18n.current_lang())
    if not iso:
        return e(shown)
    return f'<time datetime="{e(iso)}" title="{e(title)}">{e(shown)}</time>'


def _relative(stamp: str | None, now: dt.datetime) -> str:
    """«en 22 días», «hace 3 días», «hoy»: por días de calendario en UTC. Texto plano: se escapa al usarlo."""
    moment = when.parse(stamp or "")
    if moment is None:
        return ""
    days = (moment.astimezone(dt.timezone.utc).date() - now.astimezone(dt.timezone.utc).date()).days
    t = i18n.t
    if days == 0:
        return t("web.tokens.rel.today")
    if days == 1:
        return t("web.tokens.rel.in_day")
    if days == -1:
        return t("web.tokens.rel.day_ago")
    return t("web.tokens.rel.in_days", n=days) if days > 0 else t("web.tokens.rel.days_ago", n=-days)


def _row(label: str, value: str, small: str = "") -> str:
    note = f"<small>{small}</small>" if small else ""
    return f'<div class="tok-fila"><dt>{label}</dt><dd>{value}{note}</dd></div>'


def _password_form(action: str, csrf: str, digest: str, button: str, button_class: str, extra: str = "") -> str:
    t = i18n.th
    return (f'<form method="post" action="{action}" class="formulario-fila">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="id" value="{digest}">{extra}'
            f'<label>{t("web.tokens.password")}<input type="password" name="password" autocomplete="current-password" required></label>'
            f'<button class="{button_class}" type="submit">{button}</button></form>')


def detail_body(record: dict, csrf: str, state_dir: Path, *, error: str = "", ok: str = "",
                now: dt.datetime | None = None) -> str:
    """
    El detalle de un token (#760, mockup aprobado por Julian, Iris[Q72]=A): la cabecera con el
    estado y el vencimiento, «Details», «SMS limits» y «Agent», y al final «Revoke this token»
    (activo) o «Delete this token» (vencido o revocado). Nada de estilo en línea: la barra de uso
    es un `<progress>`.
    """
    t = i18n.th
    now = now or dt.datetime.now(dt.timezone.utc)
    digest = e(record["sha256"])
    state = status(record, now)
    limits = record.get("limits", {})
    per_hour, per_day = limits.get("sms_per_hour", 30), limits.get("sms_per_day", 200)
    usage = usage_today(state_dir, record.get("prefix", ""), now)

    # La línea lleva un `<time>`: el texto del catálogo se escapa entero y luego entra la etiqueta.
    slot = "\x00when\x00"
    if state == "revoked":
        line = e(i18n.t("web.tokens.line.revoked", when=slot)).replace(e(slot), _time(record.get("revoked_at")))
    elif record.get("expires_at"):
        key = "web.tokens.line.expired" if state == "expired" else "web.tokens.line.expires"
        line = e(i18n.t(key, when=slot, rel=_relative(record.get("expires_at"), now))).replace(
            e(slot), _time(record.get("expires_at")))
    else:
        line = t("web.tokens.line.never")
    head = (f'<div class="tok-cabeza"><div><h2>{e(record.get("name", ""))}</h2>'
            f'<code class="tok-prefijo">{e(record.get("prefix", ""))}…</code>'
            f'<span class="tok-vence">{line}</span></div>'
            f'<span class="estado estado-token-{state}">{t("web.tokens.status." + state)}</span></div>')

    chips = "".join(f"<code>{e(p)}</code>" for p in record.get("permissions", []))
    expires = record.get("expires_at")
    details = (f'<section class="tok-tarjeta"><h3>{t("web.tokens.sec.details")}</h3><dl>'
               + _row(t("web.tokens.permissions"), f'<div class="tok-permisos">{chips or "—"}</div>')
               + _row(t("web.tokens.created"), _time(record.get("created_at")))
               + _row(t("web.tokens.expires"), _time(expires), e(_relative(expires, now)) if expires else "")
               + _row(t("web.tokens.last_used"), _time(record.get("last_used_at")))
               + "</dl></section>")

    sms = (f'<section class="tok-tarjeta"><h3>{t("web.tokens.sec.limits")}</h3><div class="tok-cifras">'
           f'<div><b>{e(per_hour)}</b><span>{t("web.tokens.per_hour")}</span></div>'
           f'<div><b>{e(per_day)}</b><span>{t("web.tokens.per_day")}</span></div>'
           f'<div><b>{e(usage)}</b><span>{t("web.tokens.sent_today")}</span>'
           f'<progress class="tok-uso" max="{e(per_day)}" value="{e(min(usage, int(per_day or 0)))}"></progress></div>'
           f'</div></section>')

    replies = bool(record.get("agent_replies", False))
    if state == "active":
        checked = " checked" if replies else ""
        agent = (f'<section class="tok-tarjeta"><h3>{t("web.tokens.sec.agent")}</h3><div class="tok-ajuste">'
                 + _password_form("/api-tokens/agent-replies", csrf, digest, t("web.tokens.save"), "primario",
                                  f'<label class="casilla"><input type="checkbox" name="agent_replies" value="1"{checked}> '
                                  f'{t("web.tokens.agent_replies")}</label>')
                 + "</div></section>")
        danger = (f'<section class="zona-peligro"><h2>{t("web.tokens.revoke_title")}</h2><p>{t("web.tokens.revoke_hint")}</p>'
                  + _password_form("/api-tokens/revoke", csrf, digest, t("web.tokens.revoke"), "peligro") + "</section>")
    else:
        agent = (f'<section class="tok-tarjeta"><h3>{t("web.tokens.sec.agent")}</h3><dl>'
                 + _row(t("web.tokens.agent_replies"), t("web.tokens.yes") if replies else t("web.tokens.no"),
                        t("web.tokens.readonly"))
                 + "</dl></section>")
        danger = (f'<section class="zona-peligro zona-borrar"><h2>{t("web.tokens.delete_title")}</h2><p>{t("web.tokens.delete_hint")}</p>'
                  + _password_form("/api-tokens/delete", csrf, digest, t("web.tokens.delete"), "peligro") + "</section>")

    # `error` ya viene escapado (i18n.th en app.py): escaparlo otra vez mostraba «&amp;#x27;» en francés.
    error_notice = f'<p class="error" role="alert">{error}</p>' if error else ""
    saved_notice = f'<p class="aviso-ok" role="status">{t("web.tokens.saved")}</p>' if ok else ""
    crumb = f'<p class="migas"><a href="/api-tokens">← {t("web.tokens.title")}</a></p>'
    return f'{crumb}{error_notice}{saved_notice}<div class="tok">{head}{details}{sms}{agent}{danger}</div>'
