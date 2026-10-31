"""
El Dashboard de la página inicial (PRD #602), dentro del marco de shell.py.

`body(model, name)` dibuja el modelo de `dashboard.build()`: el saludo y el estado
general, los cuatro indicadores, Servicios, «Necesita tu atención», la gráfica de 7
días y la actividad reciente (FR-2). Las horas van en la zona del host (Q6). Nada de
estilo en línea: la CSP sólo deja `style-src 'self'`; los colores van en web.css y la
gráfica es SVG con atributos.

Los elementos que `assets/dashboard.js` actualiza llevan `data-dash="<clave>"`, la
misma clave que `/dashboard.json` (FR-18).
"""
from __future__ import annotations

import datetime as dt
import html
from urllib.parse import quote as urlquote

from .. import i18n
from . import when
from .dashboard import mail_href
from .shell import e, icon


def _th(key: str, **kw) -> str:
    return i18n.th("web.dash." + key, **kw)


def _t(key: str, **kw) -> str:
    return i18n.t("web.dash." + key, **kw)


def _lang2() -> str:
    return i18n.current_lang()[:2]


def ago(seconds) -> str:
    if seconds is None:
        return _t("never")
    seconds = max(0, int(seconds))
    if seconds < 60:
        return _t("ago.s", n=seconds)
    if seconds < 3600:
        return _t("ago.m", n=seconds // 60)
    if seconds < 86400:
        return _t("ago.h", n=seconds // 3600)
    return _t("ago.d", n=seconds // 86400)


def clock(at: dt.datetime, now: dt.datetime) -> str:
    """«23:01» si es de hoy; si no, «29 oct 23:01», en la zona del host."""
    hm = at.strftime("%H:%M")
    if at.date() == now.date():
        return hm
    months = when.MONTHS.get(_lang2(), when.MONTHS["en"])
    return f"{at.day} {months[at.month - 1]} {hm}"


def _greeting(now: dt.datetime, name: str) -> str:
    part = "morning" if 5 <= now.hour < 12 else "afternoon" if 12 <= now.hour < 19 else "evening"
    first = (name or "").split(" ")[0]
    return _th(f"hello.{part}", name=first)


def _pill(tone: str, label: str, key: str = "") -> str:
    data = f' data-dash="{e(key)}"' if key else ""
    return f'<span class="pill pill-{e(tone)}"{data}><i aria-hidden="true"></i>{e(label)}</span>'


def _live(key: str, **parts) -> str:
    """Un texto del catálogo con sus cifras en `<span data-dash>`, para que dashboard.js las
    cambie (revisión de Andy en #605). `parts` es `{nombre: (valor, clave del JSON)}`."""
    marks = {name: f"\x00{name}\x00" for name in parts}
    text = html.escape(i18n.t("web.dash." + key, **marks), quote=False)
    for name, (value, dash) in parts.items():
        text = text.replace(f"\x00{name}\x00", f'<span data-dash="{e(dash)}">{e(value)}</span>')
    return text


def _kpi(ico: str, label: str, value, sub: str, *, key: str, tone: str = "") -> str:
    cls = f"kpi kpi-{tone}" if tone else "kpi"
    return f"""<div class="{cls}" data-dash-kpi="{e(key)}">
  <div class="kpi-top">{icon(ico)}<span>{label}</span></div>
  <div class="kpi-valor" data-dash="{e(key)}">{e(value)}</div>
  <div class="kpi-sub">{sub}</div>
</div>"""


def _unit_pill(unit: str, key: str) -> str:
    if unit == "active":
        return _pill("ok", _t("state.active"), key)
    if unit == "unknown":
        return _pill("unknown", _t("state.unknown"), key)
    return _pill("bad", _t("state.inactive"), key)


def _row(ico: str, name: str, detail: str, pill: str) -> str:
    return f"""<li class="srv">
  <span class="srv-ico">{icon(ico)}</span>
  <div class="srv-txt"><b>{name}</b><small>{e(detail)}</small></div>
  {pill}
</li>"""


def services(model: dict) -> str:
    svc = model["services"]
    now = model["now"]
    rows = []
    listener = svc["listener"]
    main = next((a for a in model["accounts"] if a.get("agent")), None)
    detail = " · ".join(x for x in ((main or {}).get("email", ""),
                                    _t("svc.heartbeat", age=ago(listener.get("heartbeat_age_s")))) if x)
    rows.append(_row("mail", _th("svc.listener"), detail, _unit_pill(listener["unit"], "svc.listener")))
    rows.append(_row("inbox", _th("svc.dispatcher"), "", _unit_pill(svc["dispatcher"]["unit"], "svc.dispatcher")))
    session = svc["session"]
    if session["live"]:
        armed = session.get("armed_at") and _parse_local(session["armed_at"], now)
        rows.append(_row("profile", _th("svc.session"), _t("svc.armed", when=clock(armed, now)) if armed else "",
                         _pill("ok", _t("state.live"), "svc.session")))
    else:
        rows.append(_row("profile", _th("svc.session"), _t("svc.no_session"),
                         _pill("warn", _t("state.none"), "svc.session")))
    phone = svc.get("phone")
    if phone is None:
        rows.append(_row("inbox", _th("svc.phone"), _t("svc.no_phone"), _pill("off", _t("state.unpaired"), "svc.phone")))
    else:
        battery = f"{phone['battery']} %" if phone.get("battery") is not None else "—"
        detail = _t("svc.phone_detail", model=phone.get("model") or "—", version=phone.get("app_version") or "—",
                    battery=battery, age=ago(phone.get("last_seen_age_s")))
        rows.append(_row("inbox", _th("svc.phone"), detail,
                         _pill("ok", _t("state.online"), "svc.phone") if phone["online"]
                         else _pill("bad", _t("state.offline"), "svc.phone")))
    wa = model.get("whatsapp")
    if wa is not None:
        label = i18n.t(f"web.dash.state.wa.{wa}")
        if label.startswith("web."):
            label = wa or _t("state.unknown")
        tone = "ok" if wa == "connected" else "bad" if wa == "service_down" else "warn"
        rows.append(_row("chat", _th("svc.whatsapp"), "", _pill(tone, label, "svc.whatsapp")))
    for extra in svc.get("additional") or []:
        if extra.get("enabled"):
            rows.append(_row("mail", _th("svc.account"), extra.get("email", ""), _unit_pill(extra.get("unit", ""), "")))
        else:
            rows.append(_row("mail", _th("svc.account"), _t("svc.off_detail", email=extra.get("email", "")),
                             _pill("off", _t("state.off"))))
    return f"""<section class="tarjeta-d servicios" aria-labelledby="dash-svc">
  <h3 id="dash-svc">{_th("services")}</h3>
  <ul>{"".join(rows)}</ul>
</section>"""


def _parse_local(stamp: str, now: dt.datetime):
    from .dashboard import parse
    value = parse(stamp)
    return value.astimezone(now.tzinfo) if value else None


def attention(model: dict) -> str:
    now = model["now"]
    items = []
    for a in model["attention"]:
        kind = a["kind"]
        tone = "warn" if a.get("status") in ("warning", "unknown") else "bad" if a.get("status") == "blocked" else "info"
        ico, title, sub, link, action = "warn", "", "", "", ""
        if kind == "check":
            title = _th("att.check", name=a["name"])
            sub = e(a.get("summary", ""))
        elif kind == "account":
            ico = "mail"
            title = _th("att.account", name=a["name"])
            sub = e(a.get("summary", ""))
            link, action = f"/email/{urlquote(a['name'], safe='')}", _th("att.open")
        elif kind == "notices":
            first = a["oldest"]
            title = _th("att.notices.one") if a["count"] == 1 else _th("att.notices", count=a["count"])
            sub = _th("att.notices.sub", who=first["who"], subject=first["subject"], when=clock(first["at"], now))
            link = mail_href(first["account"], first["event_id"])
            action = _th("att.open")
        elif kind == "sms_failed":
            ico = "inbox"
            first = a["first"]
            status = i18n.t(f"web.sms.status.{first['status']}")
            title = _th("att.sms.one") if a["count"] == 1 else _th("att.sms", count=a["count"])
            sub = _th("att.sms.sub", who=first["who"], status=status)
            link, action = "/messages/ver?n=" + urlquote(first.get("number", ""), safe=""), _th("att.open")
        elif kind == "token":
            ico = "key"
            if a.get("expired"):
                title = _th("att.token_expired", name=a["name"])
                sub = _th("att.token_expired.sub", when=clock(a["expires"], now))
            else:
                title = _th("att.token", name=a["name"], days=a["days"])
                sub = _th("att.token.sub", when=clock(a["expires"], now))
            link, action = "/api-tokens", _th("att.renew")
        elif kind == "version":
            ico = "home"
            title = _th("att.version", latest=a["latest"])
            sub = _th("att.version.sub", installed=a["installed"])
            link = "https://github.com/iaaorgmx/paynani/blob/main/CHANGELOG.md"
            action = _th("att.notes")
        button = f'<a href="{e(link)}">{action}</a>' if link else ""
        items.append(f'<li class="att att-{tone}">{icon(ico)}<div><b>{title}</b><small>{sub}</small></div>{button}</li>')
    content = f"<ul>{''.join(items)}</ul>" if items else f'<p class="quiet nada">{_th("attention.none")}</p>'
    return f"""<section class="tarjeta-d atencion" id="atencion" aria-labelledby="dash-att">
  <h3 id="dash-att">{_th("attention")}</h3>
  {content}
</section>"""


def week(model: dict) -> str:
    """FR-14, FR-15: barras en SVG con atributos, y una tabla para lectores de pantalla."""
    data = model["week"]
    labels = [_day_label(w["day"]) for w in data]
    top = max([w["closed"] + w["open"] for w in data] + [1])
    bw, gap, h = 34, 18, 120
    parts = []
    for i, w in enumerate(data):
        x = i * (bw + gap)
        ch = round(w["closed"] / top * h, 1)
        oh = round(w["open"] / top * h, 1)
        parts.append(f'<rect class="b-ok" x="{x}" y="{h - ch}" width="{bw}" height="{ch}" rx="3"/>')
        if w["open"]:
            parts.append(f'<rect class="b-pend" x="{x}" y="{h - ch - oh - 2}" width="{bw}" height="{oh}" rx="3"/>')
        total = w["closed"] + w["open"]
        parts.append(f'<text class="b-num" x="{x + bw / 2}" y="{h - ch - oh - 8}">{total}</text>')
        parts.append(f'<text class="b-lab" x="{x + bw / 2}" y="{h + 18}">{e(labels[i])}</text>')
    width = len(data) * (bw + gap) - gap
    summary = ", ".join(f"{labels[i]} {w['closed'] + w['open']}" for i, w in enumerate(data))
    rows = "".join(f"<tr><th scope=\"row\">{e(labels[i])}</th><td>{w['closed']}</td><td>{w['open']}</td></tr>"
                   for i, w in enumerate(data))
    return f"""<section class="tarjeta-d semana" aria-labelledby="dash-week">
  <div class="cab"><h3 id="dash-week">{_th("week")}</h3>
    <span class="leyenda" aria-hidden="true"><i class="l-ok"></i>{_th("week.closed")} <i class="l-pend"></i>{_th("week.open")}</span></div>
  <svg class="barras" viewBox="0 -24 {width} {h + 48}" role="img" aria-label="{e(_t('week.label', days=summary))}">{"".join(parts)}</svg>
  <table class="solo-lector"><caption>{_th("week")}</caption>
    <thead><tr><th scope="col">{_th("week.day")}</th><th scope="col">{_th("week.closed")}</th><th scope="col">{_th("week.open")}</th></tr></thead>
    <tbody>{rows}</tbody></table>
  <p class="quiet pie">{_th("week.foot", received=model["week_received"], replied=model["week_replied"])}</p>
</section>"""


def _day_label(day: dt.date) -> str:
    months = when.MONTHS.get(_lang2(), when.MONTHS["en"])
    return f"{day.day} {months[day.month - 1]}"


ACT_ICONS = {"mail": "mail", "sent": "mail", "sms": "inbox", "call": "inbox", "whatsapp": "chat", "roster": "roster"}


def _act_state(a: dict) -> str:
    channel, state = a["channel"], a["state"]
    if channel == "mail":
        label = i18n.t(f"web.state.{state}")
        return f'<span class="estado estado-{e(state)}">{e(label if not label.startswith("web.") else state)}</span>'
    if channel == "sent":
        return f'<span class="estado estado-sent">{_th("act.sent")}</span>'
    if channel == "sms" and state not in ("received", "agent", "human"):
        label = i18n.t(f"web.sms.status.{state}")
        return f'<span class="estado estado-sms-{e(state)}">{e(label if not label.startswith("web.") else state)}</span>'
    return ""


def _act_what(a: dict) -> str:
    channel = a["channel"]
    if channel in ("mail", "sent"):
        return e(a["what"])
    if channel == "sms":
        return _th("act.sms")
    if channel == "call":
        return _th("act." + a["state"])
    if channel == "whatsapp":
        return _th("act.whatsapp")
    action = a["what"] if a["what"] in ("add", "edit", "delete") else "other"
    return _th(f"act.roster.{action}")


def activity(model: dict) -> str:
    now = model["now"]
    rows = []
    for a in model["activity"]:
        rows.append(f"""<li>
  <span class="act-ico">{icon(ACT_ICONS.get(a["channel"], "home"))}</span>
  <a class="act-txt" href="{e(a["href"])}"><b>{e(a["who"])}</b> <span>{_act_what(a)}</span></a>
  {_act_state(a)}
  <time datetime="{e(a["at"].isoformat(timespec="seconds"))}">{e(clock(a["at"], now))}</time>
</li>""")
    content = f"<ul>{''.join(rows)}</ul>" if rows else f'<p class="quiet nada">{_th("activity.none")}</p>'
    return f"""<section class="tarjeta-d actividad" aria-labelledby="dash-act">
  <h3 id="dash-act">{_th("activity")}</h3>
  {content}
</section>"""


def _account_picker(model: dict) -> str:
    if len(model["accounts"]) < 2:
        return ""
    options = [f'<option value=""{" selected" if not model["account"] else ""}>{_th("account.all")}</option>']
    for a in model["accounts"]:
        sel = " selected" if model["account"] == a["id"] else ""
        options.append(f'<option value="{e(a["id"])}"{sel}>{e(a["email"])}</option>')
    return f"""<form method="get" action="/" class="selector-cuenta">
  <label for="dash-cuenta">{_th("account")}</label>
  <select id="dash-cuenta" name="cuenta">{"".join(options)}</select>
  <button type="submit" class="secundario">{_th("account.show")}</button>
</form>"""


def body(model: dict, name: str) -> str:
    now = model["now"]
    status = model["status"]
    tone = {"ok": "ok", "warning": "warn", "blocked": "bad"}[status]
    mt = model["mail_today"]
    st = model["sms_today"]
    oldest = model["oldest_notice"]
    notices_sub = (_th("kpi.notices.sub", when=clock(oldest["at"], now), who=oldest["who"]) if oldest
                   else _th("kpi.notices.none"))
    last = model["roster_last_change"]
    roster_sub = _th("kpi.roster.sub", when=clock(last, now)) if last else _th("kpi.roster.never")
    see = (f' · <a href="#atencion">{_th("checks.see")}</a>'
           if model["checks_ok"] < model["checks_total"] else "")
    network = ""
    if model["network_at"]:
        at = _parse_local(model["network_at"], now)
        network = f'<small>{_th("network_at", when=clock(at, now))}</small>' if at else ""
    unknown = f'<p class="aviso-caja" role="status">{_th("account.unknown")}</p>' if model["account_unknown"] else ""
    query = f"?cuenta={urlquote(model['account'], safe='')}" if model["account"] else ""
    return f"""<div class="dash" data-dash-src="/dashboard.json{e(query)}">
  {unknown}
  <div class="saludo">
    <div>
      <h2>{_greeting(now, name)}</h2>
      <p class="quiet">{_th("lead", time=now.strftime("%H:%M"), zone=model["zone"])}</p>
    </div>
    <div class="salud salud-{tone}" data-dash="status" role="status" data-label-ok="{_th('status.ok')}"
         data-label-warning="{_th('status.warning')}" data-label-blocked="{_th('status.blocked')}"
         data-checks="{e(_t('checks', ok='{ok}', total='{total}'))}">
      <i aria-hidden="true"></i>
      <div><b data-dash="status.text">{_th("status." + status)}</b>
        <small><span data-dash="checks">{_th("checks", ok=model["checks_ok"], total=model["checks_total"])}</span>{see}</small>
        {network}</div>
    </div>
  </div>
  <p class="dash-cambios aviso-caja" role="status" hidden>{_th("changed")} · <a href="">{_th("reload")}</a></p>
  {_account_picker(model)}
  <section class="kpis">
    {_kpi("mail", _th("kpi.mail"), mt["received"], _live("kpi.mail.sub", handled=(mt["handled"], "mail_today.handled"), replied=(mt["replied"], "mail_today.replied"), open=(mt["open"], "mail_today.open")), key="mail_today.received")}
    {_kpi("warn", _th("kpi.notices"), model["open_notices"], notices_sub, key="open_notices", tone="warn" if model["open_notices"] else "")}
    {_kpi("inbox", _th("kpi.sms"), st["in"] + st["out"], _live("kpi.sms.sub", inn=(st["in"], "sms_today.in"), out=(st["out"], "sms_today.out"), failed=(st["failed"], "sms_today.failed")), key="sms_today.total")}
    {_kpi("roster", _th("kpi.roster"), model["roster_count"], roster_sub, key="roster_count")}
  </section>
  <div class="rejilla">
    {services(model)}
    {attention(model)}
    {week(model)}
    {activity(model)}
  </div>
</div>
<script src="/assets/dashboard.js" defer></script>
"""
