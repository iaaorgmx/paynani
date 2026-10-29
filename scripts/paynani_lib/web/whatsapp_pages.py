"""
WhatsApp en PaynaniWeb (PRD #550 FR-7, FR-24; WA-5 #557), dentro del marco de shell.py.

- `/whatsapp`: el estado de la cuenta, vincular con QR o con código, cancelar y
  desvincular (FR-7). Las tres acciones piden la contraseña y el CSRF (FR-6a). El QR
  se dibuja aquí, en memoria, con `sms/qr.py`; `whatsapp.js` lo cambia por el vigente
  cada pocos segundos (`GET /whatsapp/link/current`). El código se muestra una sola
  vez, en la respuesta del POST que lo pidió.
- `/whatsapp/messages`: las conversaciones, como «Messages» las de SMS, sin botón de
  mensaje nuevo (FR-24, Q189=A). `/whatsapp/messages/ver?n=<número>`: una, con el
  cuadro de responder sólo si el servicio dice `can_reply` (FR-20).
- Fuera del roster (FR-16a) sólo se dibujan el número, la dirección y la hora: el
  servicio ya no manda el texto, y si algún día lo mandara con `hidden`, aquí tampoco
  sale.
- Todo lo que viene de WhatsApp pasa por `e()`.
"""
from __future__ import annotations

from urllib.parse import quote

from .. import i18n
from ..sms import qr
from . import mail_pages
from .shell import e
from .whatsapp_source import MAX_TEXT

LINKED_STATES = ("connected", "connecting", "disconnected")
UNLINKED_STATES = ("unlinked", "logged_out")
KINDS = ("image", "audio", "video", "document", "sticker")
PAGE = 50


def _th(key: str, **kw) -> str:
    return i18n.th("web.wa." + key, **kw)


def _error(error: str) -> str:
    return f'<div class="error-caja" role="alert"><p>{e(error)}</p></div>' if error else ""


def _notice(notice: str) -> str:
    return f'<p class="aviso-ok" role="status">{e(notice)}</p>' if notice else ""


def error_text(code: str, fields: dict | None = None) -> str:
    """El texto de un `error` del servicio (§12)."""
    fields = fields or {}
    if code == "rate_limited":
        return i18n.t("web.wa.err.rate_limited", s=fields.get("retry_after_s", "?"))
    if code == "invalid":
        return i18n.t("web.wa.err.invalid", field=fields.get("field", "?"))
    if code in ("unavailable", "already_linked", "not_connected", "not_allowed", "not_started", "not_found"):
        return i18n.t("web.wa.err." + code)
    return i18n.t("web.wa.err.other", code=code)


def kind_label(kind: str | None) -> str:
    return _th("kind." + kind) if kind in KINDS else _th("kind.other")


def qr_svg(text: str) -> str:
    """El QR vigente como `<svg>` en línea, armado en memoria (FR-6a)."""
    return qr.to_svg(qr.encode(text), label=i18n.t("web.wa.qr_label"))


def qr_area(current: dict) -> str:
    """Lo de dentro de `#wa-qr`: el QR y cuánto le queda, o la espera. Lo usa la página
    y `GET /whatsapp/link/current`, para que el script sólo cambie este pedazo."""
    if current.get("qr"):
        return (f'<div class="wa-qr-imagen">{qr_svg(current["qr"])}</div>'
                f'<p class="quiet" data-wa-left="{int(current.get("expires_in_s") or 0)}" '
                f'data-tpl="{e(i18n.t("web.wa.qr_left", s="{s}"))}">'
                f'{_th("qr_left", s=int(current.get("expires_in_s") or 0))}</p>')
    return f'<p class="quiet">{_th("qr_wait")}</p>'


def _password(id_: str) -> str:
    return (f'<label for="{id_}">{_th("password")}</label>'
            f'<input id="{id_}" name="password" type="password" autocomplete="current-password" required>'
            f'<p class="hint">{_th("password_help")}</p>')


def _cancel_form(csrf: str) -> str:
    return f"""<form method="post" action="/whatsapp/link/cancel" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  {_password("wa-cancel-password")}
  <button type="submit" class="secundario">{_th("cancel")}</button>
</form>"""


def account_body(status: dict, csrf: str, *, current: dict | None = None, code: dict | None = None,
                 notice: str = "", error: str = "", number: str = "") -> str:
    """La pantalla «WhatsApp» (FR-7). `status` es el de `whatsapp.status`; `current`,
    la vinculación por QR de esta sesión (de `link_current`); `code`, el código recién
    pedido, que sólo llega en el POST que lo pidió."""
    state = status.get("state", "service_down")
    out = [f'<p class="acciones"><a class="secundario" href="/whatsapp/messages">{_th("nav")}</a></p>',
           f'<p class="lead">{_th("lead")}</p>', _notice(notice), _error(error)]
    label = _th("state." + state) if state in (
        "unlinked", "linking", "connecting", "connected", "disconnected", "logged_out", "service_down") else e(state)
    facts = [f'<dt>{_th("state_label")}</dt><dd><span class="estado estado-wa-{e(state)}">{label}</span></dd>']
    if status.get("me"):
        facts.append(f'<dt>{_th("me")}</dt><dd>{e(status["me"])}</dd>')
    if status.get("since") and state in LINKED_STATES:
        facts.append(f'<dt>{_th("since")}</dt><dd>{mail_pages.list_time(status["since"])}</dd>')
    out.append(f'<dl class="wa-estado">{"".join(facts)}</dl>')
    if state == "service_down":
        return "\n".join(out) + "\n"

    if current is not None:
        out.append(f"""<section class="wa-vincular" aria-labelledby="wa-qr-h">
  <h3 id="wa-qr-h">{_th("qr_h")}</h3>
  <p>{_th("qr_steps")}</p>
  <div id="wa-qr" data-url="/whatsapp/link/current" aria-live="polite">{qr_area(current)}</div>
  <noscript><p class="quiet">{_th("qr_noscript")}</p></noscript>
</section>
{_cancel_form(csrf)}
<script src="/assets/whatsapp.js" defer></script>""")
        return "\n".join(out) + "\n"
    if code is not None:
        left = int(code.get("expires_in_s") or 0)
        out.append(f"""<section class="wa-vincular" aria-labelledby="wa-code-h">
  <h3 id="wa-code-h">{_th("code_h")}</h3>
  <p>{_th("code_steps")}</p>
  <p class="wa-codigo">{e(code.get("code", ""))}</p>
  <div id="wa-qr" data-url="/whatsapp/link/current" data-mode="code">
    <p class="quiet" data-wa-left="{left}" data-tpl="{e(i18n.t("web.wa.code_left", s="{s}"))}">{_th("code_left", s=left)}</p>
  </div>
</section>
{_cancel_form(csrf)}
<script src="/assets/whatsapp.js" defer></script>""")
        return "\n".join(out) + "\n"

    linking = status.get("linking")
    if state == "linking" and linking:
        by = linking.get("by", "")
        who = _th("by." + by) if by in ("web", "phone", "terminal") else e(by)
        out.append(f'<p class="aviso-caja" role="status">{_th("linking_by", by=who, s=int(linking.get("expires_in_s") or 0))}</p>')
        out.append(_cancel_form(csrf))
        return "\n".join(out) + "\n"
    if state in LINKED_STATES:
        out.append(f"""<form method="post" action="/whatsapp/unlink" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <label class="casilla"><input type="checkbox" name="confirm" value="1" required> {_th("unlink_confirm")}</label>
  {_password("wa-unlink-password")}
  <button type="submit" class="secundario peligro">{_th("unlink")}</button>
</form>""")
        return "\n".join(out) + "\n"
    # unlinked, logged_out (o un estado nuevo que no conocemos): vincular.
    value = number or status.get("link_number") or ""
    out.append(f"""<p class="aviso-caja" role="note">{_th("risk")}</p>
<form method="post" action="/whatsapp/link" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  {_password("wa-link-password")}
  <button type="submit" class="primario" name="mode" value="qr">{_th("link_qr")}</button>
  <label for="wa-link-number">{_th("link_number")}</label>
  <input id="wa-link-number" name="number" maxlength="40" inputmode="tel" value="{e(value)}">
  <p class="hint">{_th("link_number_help")}</p>
  <button type="submit" class="secundario" name="mode" value="code">{_th("link_code")}</button>
</form>""")
    return "\n".join(out) + "\n"


def _preview(row: dict) -> str:
    if row.get("hidden") or not row.get("in_roster"):
        return f'<span class="quiet">{_th("hidden_short")}</span>'
    # La lista no dice quién mandó lo último (§12 no trae `by` en el hilo), sólo que salió.
    who = (_th("sent_prefix") + ": ") if row.get("last_dir") == "out" else ""
    if row.get("last_kind") and row.get("last_kind") != "text":
        return e(who) + kind_label(row.get("last_kind"))
    text = " ".join(str(row.get("last_excerpt") or "").split())
    return e(who + text[:120] + ("…" if len(text) > 120 else ""))


def list_body(threads: list[dict], next_before: str | None) -> str:
    """La lista de conversaciones (FR-24), del más reciente al más viejo. Sin «nuevo»."""
    th = i18n.th
    head = f'<p class="acciones"><a class="secundario" href="/whatsapp">{_th("account_link")}</a></p>'
    if not threads:
        return head + f'\n<p class="lead">{_th("empty")}</p>\n'
    out = [head, f'<p class="quiet resumen">{_th("count", n=len(threads))}</p>',
           '<ul class="correos conversaciones wa-conversaciones">',
           f'<li class="correos-cabecera" aria-hidden="true"><span>{_th("col.who")}</span>'
           f'<span>{_th("col.last")}</span><span>{_th("col.when")}</span><span></span><span></span></li>']
    for row in threads:
        href = f"/whatsapp/messages/ver?n={quote(row['number'], safe='')}"
        name = row.get("name") if row.get("in_roster") else None
        roster = (f' <span class="marca-roster" title="{th("web.sms.roster_title")}">{th("web.mail.roster")}</span>'
                  if row.get("in_roster") else "")
        out.append(f"""<li><a href="{href}">
  <span class="quien">{e(name or row["number"])}{roster}</span>
  <span class="asunto">{_preview(row)}</span>
  <span class="cuando">{mail_pages.list_time(row.get("last_at") or "")}</span>
  <span class="estado-celda"></span>
  <span class="flecha" aria-hidden="true">›</span>
</a></li>""")
    out.append("</ul>")
    if next_before:
        out.append(f'<p class="mas"><a class="secundario" href="/whatsapp/messages?antes={quote(next_before, safe="")}">'
                   f'{_th("more")}</a></p>')
    return "\n".join(out) + "\n"


def _status(m: dict) -> str:
    status = m.get("status")
    if m.get("dir") != "out" or not status:
        return ""
    label = i18n.t("web.wa.status." + status)
    label = e(status) if label.startswith("web.") else e(label)
    return f' <span class="estado estado-wa-{e(status)}">{label}</span>'


def reply_box(thread: dict, csrf: str, connected: bool, values: dict | None = None, error: str = "") -> str:
    """Responder al pie del hilo, sólo si el servicio dice `can_reply` (FR-20, FR-24)."""
    # Un envío rechazado se dice aquí aunque el cuadro no se dibuje (not_allowed,
    # not_started, not_connected).
    head = f'<h3 id="responder">{_th("reply")}</h3>{_error(error)}'
    if not thread.get("in_roster"):
        return f'<section class="responder">{head}<p class="quiet">{_th("no_reply_roster")}</p></section>'
    if not thread.get("can_reply"):
        return f'<section class="responder">{head}<p class="quiet">{_th("no_reply_started")}</p></section>'
    if not connected:
        return f'<section class="responder">{head}<p class="aviso-caja" role="status">{_th("no_reply_connected")}</p></section>'
    text = (values or {}).get("text", "")
    return f"""<section class="responder">{head}
<form method="post" action="/whatsapp/messages/enviar" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="n" value="{e(thread["number"])}">
  <label for="wa-text">{_th("reply_text")}</label>
  <textarea id="wa-text" name="text" rows="4" maxlength="{MAX_TEXT}" required>{e(text)}</textarea>
  <button type="submit" class="primario">{_th("send")}</button>
</form></section>"""


def thread_body(thread: dict, reply: str, notice: str = "") -> str:
    """Un hilo (FR-24). `thread` es el `data` de `whatsapp.thread`: los mensajes llegan
    del más reciente al más viejo y se dibujan en orden de hora."""
    number = thread["number"]
    in_roster = bool(thread.get("in_roster"))
    who = (thread.get("name") if in_roster else None) or number
    out = [f'<p class="volver"><a href="/whatsapp/messages">← {_th("back")}</a></p>',
           f'<h2 class="asunto-correo">{e(who)}</h2>',
           f'<p class="quiet">{e(number)}</p>' if who != number else "", _notice(notice)]
    if not in_roster:
        out.append(f'<p class="aviso-caja" role="note">{_th("hidden")}</p>')
    if thread.get("next_before"):
        out.append(f'<p class="mas"><a class="secundario" href="/whatsapp/messages/ver?n={quote(number, safe="")}'
                   f'&amp;antes={quote(thread["next_before"], safe="")}">{_th("older")}</a></p>')
    bubbles = ['<ol class="hilo">']
    for m in reversed(thread.get("messages") or []):
        out_dir = m.get("dir") == "out"
        css = {"agent": "sms-agent", "owner": "sms-human", "api": "sms-agent"}.get(m.get("by"), "sms-agent") \
            if out_dir else "sms-received"
        # §12: `by` es agent, owner o api. Otro valor no se adivina: sólo dice que salió.
        label = {"agent": _th("by_agent"), "owner": _th("by_owner"), "api": _th("by_api")}.get(
            m.get("by"), _th("sent_prefix")) if out_dir else e(who)
        if m.get("hidden") or not in_roster:
            body = f'<span class="quiet">{_th("hidden_short")}</span>'
        elif m.get("kind") == "image" and m.get("dir") == "in" and _shows_image(m):
            # #573: la foto la sirve /whatsapp/media, que vuelve a pedirle permiso al
            # servicio en cada carga; aquí sólo va el id del mensaje, nunca una ruta.
            src = "/whatsapp/media?id=" + quote(str(m.get("id") or ""), safe="")
            caption = e(m.get("text") or "")
            body = (f'<a class="wa-foto" href="{e(src)}" target="_blank" rel="noopener">'
                    f'<img src="{e(src)}" alt="{kind_label("image")}" loading="lazy"></a>'
                    + (f'<span class="wa-pie">{caption}</span>' if caption else ""))
        elif m.get("kind") and m.get("kind") != "text":
            caption = e(m.get("text") or "")
            body = kind_label(m.get("kind")) + (f" {caption}" if caption else "")
        else:
            body = e(m.get("text") or "")
        when = mail_pages.list_time(m.get("at") or "")
        bubbles.append(f'<li class="sms {css}"><div class="globo"><div class="de">{label}{_status(m)}</div>'
                       f'<div class="texto">{body}</div>{when}</div></li>')
    bubbles.append("</ol>")
    return "\n".join(out + bubbles + [reply]) + "\n"


IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp")


def _shows_image(m: dict) -> bool:
    """Una foto que PaynaniWeb puede pedir: JPEG, PNG o WebP según el servicio (#573)."""
    media = m.get("media") if isinstance(m.get("media"), dict) else {}
    return str(media.get("mime") or "").split(";")[0].strip().lower() in IMAGE_MIMES


def not_configured_body() -> str:
    return f'<p class="lead">{_th("not_configured")}</p>\n'
