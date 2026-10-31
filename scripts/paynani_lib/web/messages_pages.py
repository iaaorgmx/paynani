"""
Messages (PRD #434 FR-17 a FR-19): las conversaciones SMS de la pasarela, dentro
del marco de shell.py.

- `/messages`: una fila por número, la conversación con lo más reciente primero,
  de 50 en 50. Cada una dice quién es (el nombre del roster, o el que mandó el
  teléfono), lo último que pasó y si hubo llamadas perdidas.
- `/messages/ver?n=<número>`: la conversación como `paynani sms thread`, con lo
  que llegó, lo que mandó el agente con su estado y lo que contestó el dueño desde
  PaynaniApp, más las llamadas (FR-18). Los 50 más recientes, con «Ver anteriores».
- Desde el PRD #489 (T3 #506) también envía: un cuadro para responder al pie de
  la conversación y «Nuevo SMS» (`/messages/nuevo`). Los dos mandan a
  `POST /messages/enviar`, que crea la orden del dueño con `sms.outgoing.queue`.
- Todo lo que viene de un SMS pasa por `e()`.
"""
from __future__ import annotations

from urllib.parse import quote

from .. import i18n
from . import mail_pages
from .shell import e

PAGE = 50
MAX_TEXT = 1000

# Lo que dice el teléfono emparejado sobre las órdenes del dueño (FR-6).
PHONE_OK = "ok"
PHONE_NONE = "no_phone"
PHONE_OLD = "old_app"


def _who(conv_or_item: dict, names: dict) -> str:
    number = conv_or_item["number"]
    return names.get(number) or conv_or_item.get("name") or number


def _local(stamp: str) -> str:
    """`2026-10-21T03:09:45-05:00` como `2026-10-21 03:09` (hora del host)."""
    if len(stamp) >= 16 and "T" in stamp:
        return stamp[:10] + " " + stamp[11:16]
    return stamp


def local_time(stamp: str) -> str:
    """Una hora UTC `2026-10-24T14:05:00Z` en la hora del host, `14:05` (o con fecha si es otro día)."""
    import calendar
    import time
    try:
        epoch = calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return stamp
    local = time.localtime(epoch)
    same_day = time.strftime("%Y-%m-%d", local) == time.strftime("%Y-%m-%d", time.localtime())
    return time.strftime("%H:%M" if same_day else "%Y-%m-%d %H:%M", local)


def _preview(item: dict) -> str:
    t = i18n.t
    kind = item["kind"]
    if kind == "call_missed":
        return t("web.sms.call_missed_short")
    if kind == "call_answered":
        return t("web.sms.call_answered_short")
    prefix = {"agent": t("web.sms.by_agent") + ": ", "human": t("web.sms.by_owner") + ": "}.get(kind, "")
    text = " ".join(str(item.get("text") or "").split())
    return prefix + (text[:120] + ("…" if len(text) > 120 else ""))


def _new_button(phone_state: str) -> str:
    th = i18n.th
    optout = (f' <a class="secundario" href="/messages/catch-all">{th("web.catchall.link")}</a>'
              f' <a class="secundario" href="/messages/bajas">{th("web.sms.optout.link")}</a>')
    if phone_state == PHONE_OK:
        return f'<p class="acciones"><a class="boton primario" href="/messages/nuevo">{th("web.sms.new")}</a>{optout}</p>'
    return (f'<p class="acciones"><span class="boton primario deshabilitado" aria-disabled="true">{th("web.sms.new")}</span>'
            f' <span class="quiet">{th("web.sms." + phone_state)}</span>{optout}</p>')


def optout_body(rows: list[dict], csrf: str, notice: str = "", error: str = "", value: str = "") -> str:
    """
    La lista de bajas de la API (PRD #491 FR-13): los números que mandaron STOP (o que
    el dueño dio de baja aquí), con «Quitar de la lista», y un formulario para agregar.
    """
    th = i18n.th
    out = [f'<p class="volver"><a href="/messages">← {th("web.sms.back")}</a></p>',
           f'<p class="lead">{th("web.sms.optout.lead")}</p>']
    if notice:
        out.append(f'<p class="aviso-ok" role="status">{e(notice)}</p>')
    out.append(_error_box(error))
    out.append(f"""<form method="post" action="/messages/bajas" class="formulario en-linea">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="accion" value="agregar">
  <label for="optout-n">{th("web.sms.optout.add_label")}</label>
  <input id="optout-n" name="n" required maxlength="40" inputmode="tel" value="{e(value)}">
  <button type="submit" class="secundario">{th("web.sms.optout.add")}</button>
</form>""")
    if not rows:
        out.append(f'<p class="quiet">{th("web.sms.optout.empty")}</p>')
        return "\n".join(out) + "\n"
    out.append('<ul class="contactos bajas">')
    for row in rows:
        how = (th("web.sms.optout.by_sms", word=str(row.get("keyword", "")).upper())
               if row.get("by") == "sms" else th("web.sms.optout.by_web"))
        out.append(f"""<li>
  <div class="contacto"><b>{e(row["number"])}</b> <span class="quiet">{e(how)} · {e(_local(str(row.get("at", ""))))}</span></div>
  <form method="post" action="/messages/bajas" class="acciones-fila">
    <input type="hidden" name="csrf" value="{e(csrf)}">
    <input type="hidden" name="accion" value="quitar">
    <input type="hidden" name="n" value="{e(row["number"])}">
    <button type="submit" class="secundario">{th("web.sms.optout.remove")}</button>
  </form>
</li>""")
    out.append("</ul>")
    return "\n".join(out) + "\n"


def list_body(convs: list[dict], names: dict, offset: int, next_offset: int | None, total: int,
              phone_state: str = PHONE_OK) -> str:
    th = i18n.th
    if not total:
        return _new_button(phone_state) + f'\n<p class="lead">{th("web.sms.empty")}</p>\n'
    # La misma tabla que la lista de correos (pedido de Julian): a todo lo ancho, con la
    # cabecera gris y una flecha por fila.
    out = [_new_button(phone_state),
           f'<p class="quiet resumen">{th("web.sms.count", n=total)}</p>',
           '<ul class="correos conversaciones">',
           f'<li class="correos-cabecera" aria-hidden="true"><span>{th("web.sms.col.who")}</span>'
           f'<span>{th("web.sms.col.last")}</span><span>{th("web.sms.col.when")}</span>'
           f'<span>{th("web.sms.col.count")}</span><span></span></li>']
    for c in convs:
        href = f"/messages/ver?n={quote(c['number'], safe='')}"
        missed = (f' <span class="marca-llamada">{th("web.sms.missed_1" if c["missed"] == 1 else "web.sms.missed_n", n=c["missed"])}</span>'
                  if c["missed"] else "")
        roster = (f' <span class="marca-roster" title="{th("web.sms.roster_title")}">{th("web.mail.roster")}</span>'
                  if c["number"] in names else "")
        out.append(f"""<li><a href="{href}">
  <span class="quien">{e(_who(c, names))}{roster}</span>
  <span class="asunto">{e(_preview(c['last']))}</span>
  <span class="cuando">{mail_pages.list_time(c['last']['local'])}</span>
  <span class="estado-celda"><span class="estado">{th('web.sms.n_items', n=c['count'])}</span>{missed}</span>
  <span class="flecha" aria-hidden="true">›</span>
</a></li>""")
    out.append("</ul>")
    if next_offset is not None:
        out.append(f'<p class="mas"><a class="secundario" href="/messages?desde={next_offset}">{th("web.mail.more")}</a></p>')
    return "\n".join(out) + "\n"


def status_label(status: str, error: str = "") -> str:
    """El estado como se lee en la conversación: «falló (código)», «rechazado (razón)» (FR-5)."""
    label = i18n.t(f"web.sms.status.{status}")
    label = status if label.startswith("web.") else label
    return f"{label} ({error})" if error and status in ("failed", "rejected") else label


def _status(status: str, error: str = "", order_id: str = "") -> str:
    if not status:
        return ""
    # Los de la web llevan su orden: sms.js los actualiza sin recargar (FR-5).
    data = f' data-sms-id="{e(order_id)}"' if order_id.startswith("w_") else ""
    return (f' <span class="estado estado-sms-{e(status)}"{data} aria-live="polite">'
            f'{e(status_label(status, error))}</span>')


def _error_box(error: str) -> str:
    return f'<div class="error-caja" role="alert"><b>{i18n.th("web.sms.not_sent")}</b><p>{e(error)}</p></div>' if error else ""


def _compose_fields(csrf: str, pause_min: int, need_password: str, values: dict) -> str:
    """El texto con su contador, la casilla de pausa y, si hace falta, la contraseña (FR-3, FR-4, FR-4b).
    `need_password`: "yes" (fuera del roster), "maybe" (Nuevo SMS: aún no se sabe) o "no"."""
    th = i18n.th
    checked = " checked" if values.get("pause") else ""
    out = [f'<input type="hidden" name="csrf" value="{e(csrf)}">',
           f'<label for="sms-text">{th("web.sms.text")}</label>',
           f'<textarea id="sms-text" name="text" rows="4" maxlength="{MAX_TEXT}" required data-sms-counter="sms-count"'
           f' data-tpl="{th("web.sms.counter")}">{e(values.get("text", ""))}</textarea>',
           f'<p id="sms-count" class="quiet contador" aria-live="polite">{th("web.sms.limit", n=MAX_TEXT)}</p>',
           f'<label class="casilla"><input type="checkbox" name="pause" value="1"{checked}> '
           f'{th("web.sms.pause", min=pause_min)}</label>']
    if need_password != "no":
        hint = th("web.sms.password_hint" if need_password == "maybe" else "web.sms.password_needed")
        out += [f'<label for="sms-current">{th("web.sms.password")}</label>',
                f'<input id="sms-current" name="current" type="password" autocomplete="current-password"'
                f'{" required" if need_password == "yes" else ""}>',
                f'<p class="quiet">{hint}</p>']
    out.append(f'<button type="submit" class="primario">{th("web.sms.send")}</button>')
    return "\n  ".join(out)


def _unavailable(phone_state: str) -> str:
    return f'<p class="aviso-caja" role="status">{i18n.th("web.sms." + phone_state)}</p>'


def reply_box(number: str, csrf: str, phone_state: str, pause_min: int, in_roster: bool,
              values: dict | None = None, error: str = "") -> str:
    """El cuadro para responder al pie de la conversación (FR-1)."""
    th = i18n.th
    head = f'<h3 id="responder">{th("web.sms.reply")}</h3>'
    if phone_state != PHONE_OK:
        return f'<section class="responder">{head}{_unavailable(phone_state)}</section>'
    return f"""<section class="responder">{head}{_error_box(error)}
<form method="post" action="/messages/enviar" class="formulario">
  <input type="hidden" name="n" value="{e(number)}">
  <input type="hidden" name="desde_hilo" value="1">
  {_compose_fields(csrf, pause_min, "no" if in_roster else "yes", values or {})}
</form></section>"""


def new_body(csrf: str, phone_state: str, pause_min: int, roster: dict, values: dict | None = None,
             error: str = "") -> str:
    """«Nuevo SMS» (FR-2): el número, escrito o elegido de los contactos del roster con teléfono."""
    th = i18n.th
    values = values or {}
    back = f'<p class="volver"><a href="/messages">← {th("web.sms.back")}</a></p>'
    if phone_state != PHONE_OK:
        return back + _unavailable(phone_state)
    options = "".join(f'<option value="{e(number)}">{e(name)}</option>' for number, name in sorted(roster.items(),
                                                                                                key=lambda kv: kv[1].lower()))
    return f"""{back}{_error_box(error)}
<form method="post" action="/messages/enviar" class="formulario">
  <label for="sms-to">{th("web.sms.to")}</label>
  <input id="sms-to" name="n" required maxlength="40" inputmode="tel" list="sms-roster" value="{e(values.get("n", ""))}">
  <datalist id="sms-roster">{options}</datalist>
  <p class="quiet">{th("web.sms.to_hint")}</p>
  {_compose_fields(csrf, pause_min, "maybe", values)}
</form>
<script src="/assets/sms.js" defer></script>
"""


def thread_body(number: str, who: str, items: list[dict], offset: int, pause_until: str | None,
                reply: str = "", notice: str = "", offline_ttl: int = 0) -> str:
    """`items` en orden de hora; se muestran los `PAGE` más recientes desde `offset`
    contado desde el final. `reply` es el cuadro de reply_box(); `notice`, un aviso arriba.
    `offline_ttl` > 0: el teléfono está desconectado y lo que se mande vence a esos
    minutos (FR-7)."""
    th = i18n.th
    back = f'<p class="volver"><a href="/messages">← {th("web.sms.back")}</a></p>'
    head = [back, f'<h2 class="asunto-correo">{e(who)}</h2>',
            f'<p class="quiet">{e(number)} · {th("web.sms.n_items", n=len(items))}</p>']
    if notice:
        head.append(f'<p class="aviso-ok" role="status">{e(notice)}</p>')
    if pause_until:
        head.append(f'<p class="aviso-caja" role="status">{th("web.sms.paused", until=_local(pause_until))}</p>')
    if offline_ttl:
        head.append(f'<p class="aviso-caja" role="status" id="sms-offline">{th("web.sms.offline", min=offline_ttl)}</p>')
    if not items:
        head.append(f'<p class="lead">{th("web.sms.thread_empty")}</p>')
        return "\n".join(head + [reply]) + "\n"
    end = max(0, len(items) - offset)
    start = max(0, end - PAGE)
    if start > 0:
        head.append(f'<p class="mas"><a class="secundario" href="/messages/ver?n={quote(number, safe="")}'
                    f'&amp;desde={offset + PAGE}">{th("web.sms.older")}</a></p>')
    bubbles = ['<ol class="hilo">']
    for item in items[start:end]:
        kind = item["kind"]
        when = e(_local(item["local"]))
        if kind in ("call_missed", "call_answered"):
            if kind == "call_missed":
                text = th("web.sms.call_missed", who=who)
            else:
                secs = item.get("duration_s")
                text = th("web.sms.call_answered", who=who) + (
                    " · " + th("web.sms.duration", m=int(secs) // 60, s=int(secs) % 60) if isinstance(secs, int) else "")
            bubbles.append(f'<li class="llamada"><span>{text}</span> <time>{when}</time></li>')
            continue
        owner = th("web.sms.by_owner_web") if item.get("via") == "web" else th("web.sms.by_owner")
        label = {"received": e(who), "agent": th("web.sms.by_agent"), "human": owner}[kind]
        body = e(item.get("text") or "") or f'<span class="quiet">{th("web.sms.no_text")}</span>'
        bubbles.append(f'<li class="sms sms-{kind}"><div class="globo"><div class="de">{label}{_status(item["status"], item.get("error", ""), item.get("id", ""))}</div>'
                       f'<div class="texto">{body}</div><time>{when}</time></div></li>')
    bubbles.append("</ol>")
    # sms.js pregunta los estados a /messages/estados y recarga si llegó algo nuevo (FR-5).
    watch = (f'<div hidden id="sms-watch" data-url="/messages/estados?n={e(quote(number, safe=""))}"'
             f' data-count="{len(items)}"></div>')
    script = '<script src="/assets/sms.js" defer></script>'
    return "\n".join(head + bubbles + [reply, watch, script]) + "\n"


CATCHALL_CHANNELS = ("sms", "whatsapp", "telegram")
# Por canal: la página del Catch-All, a dónde vuelve y el texto de esa liga (#588).
CATCHALL_PAGES = {
    "sms": ("/messages/catch-all", "/messages", "web.sms.back"),
    "whatsapp": ("/whatsapp/catch-all", "/whatsapp/messages", "web.wa.back"),
    "telegram": ("/telegram/catch-all", "/telegram/messages", "web.tg.back"),
}


def catchall_body(state: dict, csrf: str, *, channel: str, notice: str = "", error: str = "",
                  values: dict | None = None) -> str:
    """
    El Catch-All de un canal (PRD #535 FR-1 a FR-7, PRD #576 FR-9 y FR-10, #588): qué
    hace, la advertencia de los códigos de verificación, qué abre, la casilla, las
    instrucciones y la contraseña, que se pide para activarlo o cambiar las
    instrucciones con él activo (FR-4). El de SMS vive en «Mensajes de texto» y el de WhatsApp
    en «Mensajes de WhatsApp» (#588); cada página dice dónde está el otro. `state` es
    la respuesta de catchall.get de ese canal; `values` es lo que el dueño escribió
    si no se guardó.
    """
    th = i18n.th
    page, back, back_key = CATCHALL_PAGES[channel]
    state = state or {}
    shown = values if values is not None else {"enabled": state.get("enabled", False),
                                               "text": state.get("text", "")}
    status = state.get("status", "off")
    if not state.get("exists"):
        when = th("web.catchall.never")
    else:
        label = th("web.catchall.state_on" if status == "active" else
                   "web.catchall.state_invalid" if status == "invalid" else "web.catchall.state_off")
        when = (th("web.catchall.changed", state=label, at=state.get("updated_at", ""),
                   by=state.get("updated_by", "")) if state.get("updated_at") else label)
    out = [f'<p class="volver"><a href="{back}">← {th(back_key)}</a></p>',
           f'<p class="lead">{th("web.catchall.lead")}</p>',
           f'<p class="aviso-caja" role="note">{th("web.catchall.codes")}</p>',
           f'<section class="catchall-canal" id="catchall-{channel}" aria-labelledby="catchall-{channel}-h">',
           f'<h2 id="catchall-{channel}-h">{th("web.catchall.section." + channel)}</h2>',
           f'<p>{th("web.catchall.opens." + channel)}</p>',
           f'<p class="hint">{th("web.catchall.elsewhere." + channel)}</p>',
           f'<p class="quiet">{when}</p>']
    if state.get("exists") and state.get("file") == "rules/catch-all.md":
        out.append(f'<p class="hint">{th("web.catchall.legacy")}</p>')
    if notice:
        out.append(f'<p class="aviso-ok" role="status">{e(notice)}</p>')
    if error:
        out.append(f'<div class="error-caja" role="alert"><p>{e(error)}</p></div>')
    checked = " checked" if shown.get("enabled") else ""
    out.append(f"""<form method="post" action="{page}" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="channel" value="{channel}">
  <input type="hidden" name="etag" value="{e(state.get("etag", ""))}">
  <label class="casilla"><input type="checkbox" name="enabled" value="1"{checked}> {th("web.catchall.enabled")}</label>
  <label for="catchall-{channel}-text">{th("web.catchall.instructions")}</label>
  <textarea id="catchall-{channel}-text" name="text" rows="8" maxlength="32768" placeholder="{th("web.catchall.placeholder")}">{e(shown.get("text", ""))}</textarea>
  <label for="catchall-{channel}-password">{th("web.catchall.password")}</label>
  <input id="catchall-{channel}-password" name="password" type="password" autocomplete="current-password">
  <p class="hint">{th("web.catchall.password_help")}</p>
  <button class="primario" type="submit">{th("web.catchall.save")}</button>
</form>""")
    out.append("</section>")
    return "\n".join(out) + "\n"
