"""
Telegram en PaynaniWeb (PRD #609 FR-28; TG-7 de #612), dentro del marco de shell.py.

- `/telegram`: «Bot de Telegram». El estado de `telegram.status`, el `@usuario` del bot
  y cambiar el token (FR-10): el token va en un campo `type="password"` con
  `autocomplete="off"`, se revisa con `telegram.token_check` después de la contraseña
  de la web, y se aplica con `telegram.token_apply` en un segundo paso con las
  confirmaciones. El token nunca vuelve a la página, ni en parte.
- `/telegram/messages`: las conversaciones, como «Mensajes de WhatsApp», sin mensaje
  nuevo. `/telegram/messages/ver?t=<hilo>`: una, con el cuadro de responder sólo si el
  servicio dice `can_reply` (FR-25), y «Agregar al roster» en el de alguien fuera del
  roster (FR-15).
- Fuera del roster sin el Catch-All de Telegram sólo se dibujan el nombre que dio
  (marcado «no verificado»), la dirección y la hora: el servicio no manda el texto.
- Todo lo que viene de Telegram pasa por `e()`. Un hilo se nombra por su id opaco
  (`t_…`), nunca por un id de Telegram.
"""
from __future__ import annotations

from urllib.parse import quote

from .. import i18n
from . import downloads, mail_pages, msgmenu
from .shell import e, icon
from .telegram_source import MAX_TEXT, STATES

KINDS = ("image", "voice", "audio", "video", "document", "sticker", "location", "contact")
PAGE = 50                # conversaciones por página de la lista
THREAD_PAGE = 20         # mensajes por página de un hilo (#680)
RUNNING = ("running",)


def _th(key: str, **kw) -> str:
    return i18n.th("web.tg." + key, **kw)


def _error(error: str) -> str:
    return f'<div class="error-caja" role="alert"><p>{e(error)}</p></div>' if error else ""


def _notice(notice: str) -> str:
    return f'<p class="aviso-ok" role="status">{e(notice)}</p>' if notice else ""


def error_text(code: str, fields: dict | None = None) -> str:
    """El texto de un `error` del servicio (TELEGRAM.md §4, «Errores»)."""
    fields = fields or {}
    if code == "rate_limited":
        return i18n.t("web.tg.err.rate_limited", s=fields.get("retry_after_s", "?"))
    if code in ("invalid", "missing_field"):
        return i18n.t(f"web.tg.err.{code}", field=fields.get("field", "?"))
    if code in ("unavailable", "not_allowed", "not_started", "not_found", "conflict", "too_big", "bad_type",
                "too_many", "bad_upload", "malformed", "send_unknown"):
        return i18n.t("web.tg.err." + code)
    return i18n.t("web.tg.err.other", code=code)


def state_label(state: str) -> str:
    return _th("state." + state) if state in STATES else e(state)


def state_tone(state: str) -> str:
    """El color de la píldora: ok, warn (arrancando o sin conexión) o bad."""
    if state == "running":
        return "ok"
    if state in ("starting", "offline"):
        return "warn"
    return "bad"


def kind_label(kind: str | None) -> str:
    return _th("kind." + kind) if kind in KINDS else _th("kind.other")


def _password(id_: str) -> str:
    return (f'<label for="{id_}">{_th("password")}</label>'
            f'<input id="{id_}" name="password" type="password" autocomplete="current-password" required>'
            f'<p class="hint">{_th("password_help")}</p>')


def bot_body(status: dict, csrf: str, *, check: dict | None = None, notice: str = "", error: str = "") -> str:
    """«Bot de Telegram». `status` es el de `telegram.status`; `check`, el resultado de
    `telegram.token_check` de esta sesión (sin el token), si hay uno pendiente."""
    state = str(status.get("state") or "service_down")
    out = [f'<p class="acciones"><a class="secundario" href="/telegram/messages">{_th("nav")}</a></p>',
           f'<p class="lead">{_th("bot_lead")}</p>', _notice(notice), _error(error)]
    facts = [f'<dt>{_th("state_label")}</dt><dd><span class="estado estado-tg-{state_tone(state)}">'
             f'{state_label(state)}</span></dd>']
    if status.get("bot_username"):
        facts.append(f'<dt>{_th("bot")}</dt><dd>@{e(status["bot_username"])}</dd>')
    if status.get("since") and state != "service_down":
        facts.append(f'<dt>{_th("since")}</dt><dd>{mail_pages.list_time(status["since"])}</dd>')
    if status.get("last_poll_at") and state != "service_down":
        facts.append(f'<dt>{_th("last_poll")}</dt><dd>{mail_pages.list_time(status["last_poll_at"])}</dd>')
    counters = status.get("counters") or {}
    if "received_today" in counters:
        facts.append(f'<dt>{_th("received_today")}</dt><dd>{int(counters.get("received_today") or 0)}</dd>')
    if "sent_today" in counters:
        sent = int(counters.get("sent_today") or 0)
        limit = counters.get("send_limit_day")
        shown = _th("of_limit", n=sent, limit=int(limit)) if limit else str(sent)
        facts.append(f'<dt>{_th("sent_today")}</dt><dd>{shown}</dd>')
    out.append(f'<dl class="wa-estado">{"".join(facts)}</dl>')
    if state == "conflict":
        reason = "webhook" if status.get("reason") == "webhook" else "409"
        out.append(f'<p class="aviso-caja" role="status">{_th("conflict." + reason)}</p>')
    elif state == "token_invalid":
        out.append(f'<p class="aviso-caja" role="status">{_th("token_invalid_help")}</p>')
    if state == "service_down":
        return "\n".join(out) + "\n"

    if check is not None:
        same = bool(check.get("same_token"))
        lines = [f'<p>{_th("check_same") if same else _th("check_bot", bot=check.get("bot_username") or "?")}</p>']
        webhook = ""
        if check.get("webhook"):
            lines.append(f'<p class="aviso-caja" role="note">{_th("check_webhook")}</p>')
            webhook = (f'<label class="casilla"><input type="checkbox" name="confirm_webhook" value="1" required> '
                       f'{_th("confirm_webhook")}</label>')
        out.append(f"""<section class="tg-token" aria-labelledby="tg-check-h">
  <h3 id="tg-check-h">{_th("check_h")}</h3>
  {"".join(lines)}
  <form method="post" action="/telegram/token/apply" class="formulario">
    <input type="hidden" name="csrf" value="{e(csrf)}">
    <label class="casilla"><input type="checkbox" name="confirm_dedicated" value="1" required> {_th("confirm_dedicated")}</label>
    {webhook}
    <button type="submit" class="primario">{_th("apply")}</button>
  </form>
  <form method="post" action="/telegram/token/cancel" class="formulario">
    <input type="hidden" name="csrf" value="{e(csrf)}">
    <button type="submit" class="secundario">{_th("check_cancel")}</button>
  </form>
</section>""")
        return "\n".join(out) + "\n"

    out.append(f"""<section class="tg-token" aria-labelledby="tg-token-h">
  <h3 id="tg-token-h">{_th("token_h")}</h3>
  <p class="hint">{_th("token_help")}</p>
  <form method="post" action="/telegram/token/check" class="formulario" autocomplete="off">
    <input type="hidden" name="csrf" value="{e(csrf)}">
    <label for="tg-token">{_th("token_field")}</label>
    <input id="tg-token" name="token" type="password" autocomplete="off" spellcheck="false" maxlength="100" required>
    {_password("tg-token-password")}
    <button type="submit" class="primario">{_th("token_check")}</button>
  </form>
</section>""")
    return "\n".join(out) + "\n"


def _name(row: dict) -> str:
    """El nombre de un hilo. Fuera del roster, el que la persona dio, marcado «no
    verificado» si el servicio no lo marcó ya."""
    name = str(row.get("name") or "")
    if not row.get("in_roster") and _th("unverified") not in name and "(" not in name:
        name = f"{name} ({i18n.t('web.tg.unverified')})" if name else i18n.t("web.tg.unverified")
    return name


def _preview(row: dict) -> str:
    if row.get("hidden") or row.get("last_excerpt") is None and row.get("last_kind") is None:
        return f'<span class="quiet">{_th("hidden_short")}</span>'
    who = (_th("sent_prefix") + ": ") if row.get("last_dir") == "out" else ""
    if row.get("last_kind") and row.get("last_kind") != "text":
        return e(who) + kind_label(row.get("last_kind"))
    text = " ".join(str(row.get("last_excerpt") or "").split())
    return e(who + text[:120] + ("…" if len(text) > 120 else ""))


def list_body(threads: list[dict], next_before: str | None, notice: str = "") -> str:
    """La lista de conversaciones, del más reciente al más viejo. Sin «nuevo» (FR-25)."""
    th = i18n.th
    head = (f'<p class="acciones"><a class="secundario" href="/telegram">{_th("bot_link")}</a> '
            f'<a class="secundario" href="/telegram/catch-all">{th("web.catchall.link")}</a></p>'
            f'<p class="lead">{_th("lead")}</p>{_notice(notice)}')
    if not threads:
        return head + f'\n<p class="lead">{_th("empty")}</p>\n'
    out = [head, f'<p class="quiet resumen">{_th("count", n=len(threads))}</p>',
           '<ul class="correos conversaciones wa-conversaciones">',
           f'<li class="correos-cabecera" aria-hidden="true"><span>{_th("col.who")}</span>'
           f'<span>{_th("col.last")}</span><span>{_th("col.when")}</span><span></span><span></span></li>']
    for row in threads:
        href = f"/telegram/messages/ver?t={quote(str(row.get('thread') or ''), safe='')}"
        roster = (f' <span class="marca-roster" title="{th("web.sms.roster_title")}">{th("web.mail.roster")}</span>'
                  if row.get("in_roster") else "")
        out.append(f"""<li><a href="{e(href)}">
  <span class="quien">{e(_name(row))}{roster}</span>
  <span class="asunto">{_preview(row)}</span>
  <span class="cuando">{mail_pages.list_time(row.get("last_at") or "")}</span>
  <span class="estado-celda"></span>
  <span class="flecha" aria-hidden="true">›</span>
</a></li>""")
    out.append("</ul>")
    if next_before:
        out.append(f'<p class="mas"><a class="secundario" href="/telegram/messages?antes={quote(next_before, safe="")}">'
                   f'{_th("more")}</a></p>')
    return "\n".join(out) + "\n"


def _status(m: dict) -> str:
    status = m.get("status")
    if m.get("dir") != "out" or status not in ("sending", "sent", "failed"):
        return ""
    tone = {"sending": "warn", "sent": "ok", "failed": "bad"}[status]
    return f' <span class="estado estado-tg-{tone}">{_th("status." + status)}</span>'


def reply_box(thread: dict, csrf: str, running: bool, values: dict | None = None, error: str = "",
              web_files: bool = False, replies: bool = False) -> str:
    """Responder al pie del hilo, sólo si el servicio dice `can_reply` (FR-25)."""
    head = f'<h3 id="responder">{_th("reply")}</h3>{_error(error)}'
    if not thread.get("in_roster"):
        return f'<section class="responder">{head}<p class="quiet">{_th("no_reply_roster")}</p></section>'
    if not thread.get("can_reply"):
        return f'<section class="responder">{head}<p class="quiet">{_th("no_reply_started")}</p></section>'
    if not running:
        return f'<section class="responder">{head}<p class="aviso-caja" role="status">{_th("no_reply_state")}</p></section>'
    text = (values or {}).get("text", "")
    # La barra de Webchat (Julian, mockup aprobado; Q337 = B): el cuadro con todo el ancho,
    # que crece solo (barra.js), y «Enviar» redondo, pegada abajo. El clip con «Foto» y
    # «Archivo» sólo si el servicio acepta archivos de la web (`web_files`, #662); entonces
    # el texto puede ir vacío y el formulario es multipart.
    name = str(thread.get("name") or "")
    placeholder = _th("placeholder", name=name) if name else _th("reply_text")
    clip = attach = ""
    form_attrs = ""
    required = " required"
    if web_files:
        form_attrs = ' enctype="multipart/form-data"'
        required = ""
        wc = lambda key, **kw: i18n.th("web.wc." + key, **kw)  # noqa: E731 -- los textos del clip son los de Webchat
        attach = f'\n  <div class="wc-adjuntos" id="tg-adjuntos" data-remove="{wc("remove", name="{name}")}"></div>'
        clip = f"""
    <details class="wc-adjuntar">
      <summary class="wc-clip" title="{_th('files_note')}">{icon("clip")}<span class="solo-lector">{wc('attach')}</span></summary>
      <div class="wc-menu">
        <label class="wc-opcion">{icon("photo")}<span>{wc("opt_photo")}</span>
          <input type="file" name="files" class="wc-archivos" multiple accept="image/jpeg,image/png,image/webp,image/gif"></label>
        <label class="wc-opcion">{icon("file")}<span>{wc("opt_file")}</span>
          <input type="file" name="files" class="wc-archivos" multiple accept=".pdf,.txt,.csv,.docx,.xlsx,.zip,application/pdf,text/plain,text/csv,application/zip"></label>
        <p class="wc-menu-nota">{_th("files_note")}</p>
      </div>
    </details>"""
    scripts = ('<script src="/assets/adjuntos.js" defer></script>\n' if web_files else "") + \
        '<script src="/assets/barra.js" defer></script>'
    return f"""<form method="post" action="/telegram/messages/enviar" class="wc-escribir barra-escribir tg-escribir{' barra-con-clip' if web_files else ''}" id="responder"{form_attrs}>
  <h3 class="solo-lector">{_th("reply")}</h3>{_error(error)}
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="t" value="{e(thread["thread"])}">{msgmenu.reply_field(replies, (values or {}).get("reply_to", ""))}{attach}
  <div class="wc-barra">{clip}
    <label for="tg-text" class="solo-lector">{_th("reply_text")}</label>
    <textarea id="tg-text" name="text" rows="1" maxlength="{MAX_TEXT}"{required} placeholder="{placeholder}">{e(text)}</textarea>
    <button type="submit" class="wc-enviar" aria-label="{_th("send")}" title="{_th("send")}">{icon("send")}</button>
  </div>
</form>
{scripts}"""


def add_box(thread: dict, csrf: str, error: str = "") -> str:
    """«Agregar al roster» (FR-15) en el hilo de alguien fuera del roster. El id de
    Telegram no está aquí: lo pide el POST, después de la contraseña."""
    if thread.get("in_roster"):
        return ""
    return f"""<section class="tg-agregar" aria-labelledby="tg-add-h">
  <h3 id="tg-add-h">{_th("add_h")}</h3>{_error(error)}
  <p class="hint">{_th("add_help")}</p>
  <form method="post" action="/telegram/roster" class="formulario">
    <input type="hidden" name="csrf" value="{e(csrf)}">
    <input type="hidden" name="t" value="{e(thread["thread"])}">
    {_password("tg-add-password")}
    <button type="submit" class="secundario">{_th("add_btn")}</button>
  </form>
</section>"""


def sender(by) -> str:
    """Quién mandó un mensaje que salió, según el `by` de TELEGRAM.md §4: el dueño desde
    PaynaniWeb (`web`) o desde PaynaniApp (`phone:<device_id>`), el agente (`agent` o
    `terminal`) o la API (`api`). Cualquier otro valor no se adivina: ""."""
    by = str(by or "")
    if by in ("web", "owner") or by.startswith("phone:"):
        return "owner"
    if by in ("agent", "terminal"):
        return "agent"
    return "api" if by == "api" else ""


def thread_body(thread: dict, reply: str, add: str = "", notice: str = "", replies: bool = False,
                reactions=None, csrf: str = "", agent_name: str = "") -> str:
    """Un hilo. `thread` es el `data` de `telegram.thread`: los mensajes llegan del más
    reciente al más viejo (como `whatsapp.thread`) y se dibujan en orden de hora."""
    tid = str(thread.get("thread") or "")
    in_roster = bool(thread.get("in_roster"))
    who = _name(thread)
    out = [f'<p class="volver"><a href="/telegram/messages">← {_th("back")}</a></p>',
           f'<h2 class="asunto-correo">{e(who)}</h2>', _notice(notice)]
    hidden = bool(thread.get("hidden")) or (not in_roster and not thread.get("messages"))
    if hidden:
        out.append(f'<p class="aviso-caja" role="note">{_th("hidden")}</p>')
    if thread.get("next_before"):
        out.append(f'<p class="mas"><a class="secundario" href="/telegram/messages/ver?t={quote(tid, safe="")}'
                   f'&amp;antes={quote(str(thread["next_before"]), safe="")}">{_th("older")}</a></p>')
    # PRD #685 F2: con `replies` (telegram.status), el menú suma «Responder».
    # F3: con `reactions` (telegram.status), la fila y el selector, sólo con la lista del bot.
    bubbles = [f'<ol class="hilo"{msgmenu.list_attrs(reply=replies, reactions=reactions, react_url="/telegram/messages/reaccionar", csrf=csrf, poll_url="/telegram/messages/reacciones?t=" + quote(tid, safe=""))}>']
    messages = sorted(thread.get("messages") or [], key=lambda m: str(m.get("at") or ""))
    for m in messages:
        out_dir = m.get("dir") == "out"
        who_sent = sender(m.get("by")) if out_dir else ""
        css = ("sms-human" if who_sent == "owner" else "sms-agent") if out_dir else "sms-received"
        label = {"agent": _th("by_agent"), "owner": _th("by_owner"), "api": _th("by_api")}.get(
            who_sent, _th("sent_prefix")) if out_dir else e(who)
        if m.get("hidden"):
            body = f'<span class="quiet">{_th("hidden_short")}</span>'
        elif m.get("kind") == "image" and not out_dir:
            # La foto la sirve /telegram/media, que vuelve a pedirle permiso al servicio
            # en cada carga (telegram.image); aquí sólo va la referencia opaca.
            src = "/telegram/media?ref=" + quote(str(m.get("ref") or ""), safe="")
            caption = e(m.get("text") or "")
            body = (f'<a class="wa-foto" href="{e(src)}" target="_blank" rel="noopener">'
                    f'<img src="{e(src)}" alt="{kind_label("image")}" loading="lazy"></a>'
                    + (f'<span class="wa-pie">{caption}</span>' if caption else ""))
        elif out_dir and m.get("files"):
            # Lo que mandó el dueño desde la web (#662): las fotos por /telegram/media con
            # su índice, que vuelve a pedirle permiso al servicio; de un archivo, el nombre.
            body = _sent_files(str(m.get("ref") or ""), m["files"]) + (
                f'<span class="wa-pie">{e(m.get("text") or "")}</span>' if m.get("text") else "")
        elif m.get("kind") == "document" and not out_dir and m.get("filename") and (m.get("media") or {}):
            # #676: el nombre y el tamaño, con la descarga por /telegram/file, que vuelve a
            # pedirle permiso al servicio en cada pedido.
            href = "/telegram/file?ref=" + quote(str(m.get("ref") or ""), safe="")
            body = downloads.row(href, m["filename"], m["media"].get("bytes"), kind_label("document")) + (
                f'<span class="wa-pie">{e(m.get("text") or "")}</span>' if m.get("text") else "")
        elif m.get("kind") and m.get("kind") != "text":
            caption = e(m.get("text") or "")
            body = kind_label(m.get("kind")) + (f" {caption}" if caption else "")
        else:
            body = e(m.get("text") or "")
        edited = f' <span class="quiet">({_th("edited")})</span>' if m.get("edited") else ""
        when = mail_pages.list_time(m.get("at") or "")
        # PRD #685: el menú al tocar el mensaje, sólo en los que ya llegaron o salieron.
        # Quién lo escribió, en texto (item() lo escapa), para la barra «Respondiendo a…».
        # #707: el del agente es su nombre (como en la cita que guarda el servicio), no «Agente».
        name = agent_name if out_dir and m.get("by") == "agent" and agent_name else i18n.t("web.tg." + {"agent": "by_agent", "owner": "by_owner", "api": "by_api"}.get(
            who_sent, "sent_prefix")) if out_dir else who
        bubbles.append(f'<li class="sms {css}"{msgmenu.item(msgmenu.has_menu("telegram", m), str(m.get("ref") or ""), name, m.get("actions") is not False)}>'
                       f'<div class="globo"><div class="de">{label}{_status(m)}{edited}</div>'
                       f'{msgmenu.quote(m.get("reply_to"))}<div class="texto">{body}</div>{when}'
                       f'{msgmenu.reactions(m.get("reactions"))}</div></li>')
    bubbles.append("</ol>")
    # #680: hilo.js baja al último mensaje al abrir, como Webchat.
    return "\n".join(out + bubbles + [add, reply, '<script src="/assets/hilo.js" defer></script>', msgmenu.SCRIPT]) + "\n"


def _sent_files(ref: str, files: list) -> str:
    out = []
    for i, f in enumerate(files):
        if not isinstance(f, dict):
            continue
        fname = str(f.get("name") or "")
        if f.get("media") and ref.startswith("tgo:"):
            src = f"/telegram/media?ref={quote(ref, safe='')}&i={i}"
            out.append(f'<a class="wa-foto" href="{e(src)}" target="_blank" rel="noopener">'
                       f'<img src="{e(src)}" alt="{e(fname) or kind_label("image")}" loading="lazy"></a>')
        else:
            out.append(f'<span class="tg-archivo">{icon("file")}<span>{e(fname) or kind_label(f.get("kind"))}</span></span>')
    return "".join(out)


def not_configured_body() -> str:
    """Sin bot: el aviso y la entrada a «Cuenta de Telegram» (#635)."""
    return (f'<p class="acciones"><a class="secundario" href="/telegram">{_th("bot_link")}</a></p>'
            f'<p class="lead">{_th("not_configured")}</p>\n')


def setup_body(csrf: str, *, error: str = "", username: str = "", owner_telegram: str = "") -> str:
    """
    «Cuenta de Telegram» sin bot (#635): el token (`type="password"`, nunca vuelve), el
    usuario del bot, que se compara con `getMe` (Q282), el Telegram del dueño, que se guarda
    en su fila del roster para que el bot le conteste desde el primer mensaje (#682), la
    casilla «sólo de esta instalación», que también autoriza borrar un webhook (Q283), y la
    contraseña de la web. Sin el enlace a «Mensajes de Telegram»: sin bot esa página es un
    404 (#641).
    """
    return f"""<p class="lead">{_th("setup.lead")}</p>
{_error(error)}
<section class="tg-token" aria-labelledby="tg-setup-h">
  <h3 id="tg-setup-h">{_th("bot_title")}</h3>
  <form method="post" action="/telegram/setup" class="formulario" autocomplete="off">
    <input type="hidden" name="csrf" value="{e(csrf)}">
    <label for="tg-setup-token">{_th("setup.token")}</label>
    <input id="tg-setup-token" name="token" type="password" autocomplete="off" spellcheck="false" maxlength="100" required>
    <p class="hint">{_th("setup.token_help")}</p>
    <label for="tg-setup-user">{_th("setup.username")}</label>
    <input id="tg-setup-user" name="bot_username" type="text" autocomplete="off" spellcheck="false" maxlength="40"
           value="{e(username)}" placeholder="@" required>
    <p class="hint">{_th("setup.username_help")}</p>
    <label for="tg-setup-owner">{_th("setup.owner")}</label>
    <input id="tg-setup-owner" name="owner_telegram" type="text" autocomplete="off" spellcheck="false" maxlength="64"
           value="{e(owner_telegram)}" placeholder="@" required>
    <p class="hint">{_th("setup.owner_help")}</p>
    <label class="casilla"><input type="checkbox" name="confirm_dedicated" value="1" required> {_th("setup.dedicated")}</label>
    {_password("tg-setup-password")}
    <button type="submit" class="primario">{_th("setup.save")}</button>
  </form>
</section>
"""


def disabled_body() -> str:
    """Hay token pero Telegram está desactivado (#641): el aviso, sin el formulario, que
    de todos modos se negaría con `already_configured`."""
    return f'<p class="lead">{_th("setup.disabled")}</p>\n'
