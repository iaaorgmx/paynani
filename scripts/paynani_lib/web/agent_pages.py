"""
«AI Agent» (#644): el bloque del agente en el menú lateral y la página `/agent`, dentro
del marco de shell.py y con las clases del Dashboard (kpis, tarjeta-d, srv, pill).

- `block(summary, active)` va debajo del bloque del usuario, con su mismo estilo (Q294):
  el nombre del agente en 16 px y sin negritas (Q295), el harness y el estado (Q293), y el
  ícono de robot en el lugar del de Perfil. Es un enlace a `/agent` (Q292, Q298).
- `body(model)` es la página (Q296): el agente y su estado, las cuatro cifras de hoy,
  «The agent», «Channels» (Julian), lo que hizo hoy y qué hacer si cambia el estado.
"""
from __future__ import annotations

from .. import i18n
from . import dashboard_pages as dp
from .dashboard import _version_tuple
from .shell import e, icon

TONES = {"online": "ok", "no_session": "warn", "offline": "bad", "unknown": "off"}   # gris: sin evidencia


def _th(key: str, **kw) -> str:
    return i18n.th("web.agent." + key, **kw)


def _t(key: str, **kw) -> str:
    return i18n.t("web.agent." + key, **kw)


def chips(runtime_label: str, status: str) -> str:
    return (f'<span class="agente-chips"><span class="agente-chip">{e(runtime_label)}</span>'
            f'<span class="agente-chip agente-{e(TONES.get(status, "warn"))}"><i aria-hidden="true"></i>'
            f'{_th("status." + status)}</span></span>')


def block(summary: dict | None, active: bool = False) -> str:
    """El bloque del menú. Sin datos del agente no se dibuja."""
    if not summary:
        return ""
    current = ' aria-current="page"' if active else ""
    return f"""<a class="usuario agente-usuario{' activo' if active else ''}" href="/agent"{current}
     title="{_th('block', name=summary['name'])}">
    <div class="usuario-datos">
      <b>{e(summary["name"])}</b>
      {chips(summary["runtime_label"], summary["status"])}
    </div>
    <span class="perfil agente-icono" aria-hidden="true">{icon("agent")}</span>
  </a>"""


def _status_box(model: dict) -> str:
    now = model["now"]
    status = model["status"]
    lines = []
    runtime = model["runtime_label"]
    accepted = model["last_accepted"]
    if status == "offline":
        lines.append(_th("offline_push", runtime=runtime) if model["kind"] == "push"
                     and model["dispatcher"] == "active" else _th("offline_detail"))
    elif status == "unknown":
        lines.append(_th("unknown_detail"))
    elif status == "no_session":
        lines.append(_th("no_session_spool", runtime=runtime) if model["kind"] == "spool" else _th("no_session_detail"))
    elif model["kind"] != "watch":
        lines.append(_th("online_other", runtime=runtime))
        if accepted:
            lines.append(_th("accepted_at", when=dp.clock(accepted.astimezone(now.tzinfo), now)))
    else:
        session = model["session"]
        if session["armed_at"]:
            lines.append(_th("since", when=dp.clock(session["armed_at"].astimezone(now.tzinfo), now)))
        if session["expires_at"]:
            lines.append(_th("renews", when=dp.clock(session["expires_at"].astimezone(now.tzinfo), now)))
    small = "".join(f"<small>{line}</small>" for line in lines)
    return f"""<div class="salud salud-{TONES[status]}" role="status"><i aria-hidden="true"></i>
      <div><b>{_th("status." + status)}</b>{small}</div>
    </div>"""


def _minutes(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


def _kpis(model: dict) -> str:
    now = model["now"]
    handled = model["handled"]
    waiting = model["waiting"]
    last = model["last_reply"]
    median = model["reply_median_s"]
    return "".join([
        dp._kpi("mail", _th("kpi.handled"), handled["replied"] + handled["closed"],
                _th("kpi.handled.sub", replied=handled["replied"], closed=handled["closed"]), key="agent.handled"),
        dp._kpi("inbox", _th("kpi.waiting"), waiting,
                _th("kpi.waiting.sub") if waiting else _th("kpi.waiting.none"), key="agent.waiting",
                tone="warn" if waiting else ""),
        dp._kpi("send", _th("kpi.last"), dp.clock(last["at"], now) if last else "—",
                _th("kpi.last.sub", who=last["who"], channel=_t("channel." + last["channel"])) if last
                else _th("kpi.last.none"), key="agent.last"),
        dp._kpi("clock", _th("kpi.median"), _minutes(median) if median is not None else "—",
                _th("kpi.median.sub") if median is not None else _th("kpi.median.none"), key="agent.median"),
    ])


def _agent_rows(model: dict) -> str:
    now = model["now"]
    status = model["status"]
    rows = [dp._row("agent", _th("row.harness"), model["runtime_label"],
                    dp._pill(TONES[status], _t("status." + status)))]
    if model["kind"] == "watch":
        session = model["session"]
        if session["live"]:
            armed = session["armed_at"]
            detail = _t("row.watch.armed", when=dp.clock(armed.astimezone(now.tzinfo), now)) if armed else ""
            rows.append(dp._row("clock", _th("row.watch"), detail, dp._pill("ok", _t("pill.armed"))))
        else:
            rows.append(dp._row("clock", _th("row.watch"), _t("row.watch.none"), dp._pill("warn", _t("pill.not_armed"))))
    else:
        # Sin vigilancia: lo que se sabe es cuándo el runtime aceptó lo último.
        accepted = model["last_accepted"]
        detail = (_t("row.delivery.at", when=dp.clock(accepted.astimezone(now.tzinfo), now)) if accepted
                  else _t("row.delivery.none"))
        rows.append(dp._row("clock", _th("row.delivery"), detail,
                            dp._pill(TONES[status], _t("status." + status))))
    rows.append(dp._row("inbox", _th("row.dispatcher"), _t("row.dispatcher.detail"),
                        dp._unit_pill(model["dispatcher"], "")))
    version = model["version"]
    installed, latest = version.get("installed", ""), version.get("latest", "")
    newer = bool(latest) and _version_tuple(latest) > _version_tuple(installed)
    rows.append(dp._row("info", _th("row.version"), _t("row.version.detail", version=installed or "?"),
                        dp._pill("warn", _t("pill.update", latest=latest)) if newer
                        else dp._pill("ok", _t("pill.latest")) if latest else ""))
    return "".join(rows)


def _channel_rows(model: dict) -> str:
    rows = [dp._row("mail", _th("ch.email"),
                    _t("ch.email.detail", email=model["email"], count=model["roster_count"]),
                    dp._unit_pill(model["listener"], ""))]
    rows.append(dp.phone_row(model["phone"], _th("ch.sms")))
    if model["whatsapp"] is not None:
        rows.append(dp.whatsapp_row(model["whatsapp"]))
    if model["telegram"] is not None:
        rows.append(dp.telegram_row(model["telegram"], _th("ch.telegram")))
    return "".join(rows)


def body(model: dict) -> str:
    rows = dp.activity_rows(model["activity"], model["now"])
    activity = f"<ul>{''.join(rows)}</ul>" if rows else f'<p class="quiet nada">{_th("activity.none")}</p>'
    help_rows = "".join(
        f"<dt>{dp._pill(TONES[key], _t('status.' + key))}</dt><dd>{_th('help.' + key)}</dd>"
        for key in ("no_session", "offline", "unknown"))
    return f"""<div class="dash agente-pag">
  <div class="saludo">
    <div class="agente-id">
      <span class="agente-grande" aria-hidden="true">{icon("agent")}</span>
      <div><h2>{e(model["name"])}</h2>
        <p class="quiet">{_th("lead", email=model["email"], runtime=model["runtime_label"])}</p></div>
    </div>
    {_status_box(model)}
  </div>
  <section class="kpis">{_kpis(model)}</section>
  <div class="rejilla">
    <section class="tarjeta-d servicios" aria-labelledby="agente-sec-agent">
      <h3 id="agente-sec-agent">{_th("sec.agent")}</h3><ul>{_agent_rows(model)}</ul>
    </section>
    <section class="tarjeta-d servicios" aria-labelledby="agente-sec-channels">
      <h3 id="agente-sec-channels">{_th("sec.channels")}</h3><ul>{_channel_rows(model)}</ul>
    </section>
    <section class="tarjeta-d actividad" aria-labelledby="agente-sec-activity">
      <h3 id="agente-sec-activity">{_th("sec.activity")}</h3>
      {activity}
    </section>
    <section class="tarjeta-d agente-ayuda" aria-labelledby="agente-sec-help">
      <h3 id="agente-sec-help">{icon("help")}{_th("sec.help")}</h3>
      <dl>{help_rows}</dl>
    </section>
  </div>
</div>
"""
