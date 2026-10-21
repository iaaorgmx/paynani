"""
Las pantallas de Email Accounts (PRD #434 FR-13 a FR-15), dentro del marco de
shell.py. Todo lo que viene de un correo pasa por `e()`: un asunto o un cuerpo no
puede meter marcado en la página.
"""
from __future__ import annotations

from urllib.parse import quote

from .. import i18n
from .shell import e


def _when(stamp: str) -> str:
    """`2026-10-21T08:08:03Z` como `2026-10-21 08:08 UTC`: la hora del ledger es UTC."""
    if len(stamp) >= 16 and "T" in stamp:
        return stamp[:10] + " " + stamp[11:16] + " UTC"
    return stamp


def _state(state: str) -> str:
    if not state:
        return ""
    label = i18n.t(f"web.state.{state}")
    return f'<span class="estado estado-{e(state)}">{e(label if not label.startswith("web.") else state)}</span>'


def account_head(account_id: str, *, removable: bool, ok: str = "") -> str:
    """El aviso de lo que acaba de pasar (agregada, quitada) y «Quitar esta cuenta»
    para una cuenta adicional (FR-16)."""
    th = i18n.th
    out = ""
    if ok in ("added", "added_noservice", "removed"):
        cls = "aviso-ok" if ok != "added_noservice" else "aviso-caja"
        out += f'<p class="{cls}" role="status">{th("web.acct.ok." + ok)}</p>\n'
    if removable:
        out += (f'<p class="acciones-cuenta"><a class="peligro-enlace" href="/cuentas/{quote(account_id)}/quitar">'
                f'{th("web.acct.remove_nav")}</a></p>\n')
    return out


def href(account_id: str, row: dict) -> str:
    """El enlace a un correo de la lista: `?e=<evento>` si se recibió, `?s=<Message-ID>` si se envió."""
    if row["kind"] == "out":
        return f"/email/{quote(account_id)}/ver?s={quote(row['message_id'], safe='')}"
    return f"/email/{quote(account_id)}/ver?e={quote(row['event_id'], safe='')}"


def _who(row: dict) -> str:
    """«De: Ana» de un recibido, «Para: ana@…» de un enviado, con su flecha."""
    th = i18n.th
    if row["kind"] == "out":
        return (f'<span class="dir dir-out" title="{th("web.mail.dir_out")}">↗</span> '
                f'{th("web.mail.to_who", who=row["to"] or row["cc"])}')
    return (f'<span class="dir dir-in" title="{th("web.mail.dir_in")}">↙</span> '
            f'{th("web.mail.from_who", who=row["sender_name"] or row["sender_address"])}')


def _roster(row: dict) -> str:
    th = i18n.th
    if row["kind"] == "in" and row["roster"]:
        return f' <span class="marca-roster" title="{th("web.mail.roster_title")}">{th("web.mail.roster")}</span>'
    return ""


def _mark(row: dict) -> str:
    """El estado de un recibido; «enviado» de un enviado."""
    if row["kind"] == "out":
        return f'<span class="estado estado-sent">{i18n.th("web.mail.dir_out")}</span>'
    return _state(row["state"])


def list_body(account_id: str, rows: list[dict], total: int, offset: int, next_offset: int | None) -> str:
    """FR-13 como un webmail: lo recibido y lo enviado de la cuenta, el más reciente primero."""
    th = i18n.th
    if not total:
        return f'<p class="lead">{th("web.mail.empty")}</p>\n'
    out = [f'<p class="quiet resumen">{th("web.mail.count", n=total)} · {th("web.mail.readonly")}</p>',
           '<ul class="correos">']
    for r in rows:
        subject = r["subject"] or i18n.t("web.mail.no_subject")
        out.append(f"""<li class="correo-{r['kind']}"><a href="{href(account_id, r)}">
  <span class="quien">{_who(r)}{_roster(r)}</span>
  <span class="asunto">{e(subject)}</span>
  <span class="cuando">{e(_when(r['at']))}</span>
  {_mark(r)}
</a></li>""")
    out.append("</ul>")
    if next_offset is not None:
        out.append(f'<p class="mas"><a class="secundario" href="/email/{quote(account_id)}?desde={next_offset}">'
                   f'{th("web.mail.more")}</a></p>')
    return "\n".join(out) + "\n"


def _back(account_id: str) -> str:
    return f'<p class="volver"><a href="/email/{quote(account_id)}">← {i18n.th("web.mail.back")}</a></p>'


def message_body(account_id: str, row: dict, message: dict | None, error=None, thread=None, texts=None) -> str:
    """Un correo recibido, leído de IMAP, y debajo su conversación."""
    th = i18n.th
    head = [_back(account_id)]
    if error is not None:
        head.append(f'<div class="error-caja" role="alert"><b>{th("web.mail.err_h")}</b>'
                    f'<p>{th("web.mail.err." + error.code, detail=error.detail)}</p></div>')
        head.append(_envelope(row, None))
        return "\n".join(head) + "\n"
    head.append(_envelope(row, message))
    notes = []
    if message["source"] == "html":
        notes.append(f'<p class="quiet">{th("web.mail.html_note")}</p>')
    if message["truncated"]:
        notes.append(f'<p class="quiet">{th("web.mail.truncated", n=len(message["text"]))}</p>')
    if message["attachments"]:
        notes.append(f'<p class="quiet">{th("web.mail.attachments", names=", ".join(message["attachments"]))}</p>')
    text = message["text"] or ""
    body = (f'<pre class="cuerpo">{e(text)}</pre>' if text.strip()
            else f'<p class="quiet">{th("web.mail.nobody")}</p>')
    convo = thread_html(account_id, row, thread or [row], texts or {})
    return "\n".join(head + notes + [body, convo, f'<p class="quiet">{th("web.mail.readonly")}</p>']) + "\n"


def sent_body(account_id: str, row: dict, thread: list[dict], texts: dict) -> str:
    """Un correo enviado: lo que anotó sent.log, su texto si el servidor guardó copia, y su conversación."""
    th = i18n.th
    fields = [("web.mail.f.to", row["to"])]
    if row["cc"]:
        fields.append(("web.mail.f.cc", row["cc"]))
    if row["bcc"]:
        fields.append(("web.mail.f.bcc", row["bcc"]))
    fields.append(("web.mail.f.date", _when(row["at"])))
    dl = "".join(f"<dt>{th(k)}</dt><dd>{e(v)}</dd>" for k, v in fields)
    subject = row["subject"] or i18n.t("web.mail.no_subject")
    text = texts.get(row["message_id"])
    body = (f'<pre class="cuerpo">{e(text)}</pre>' if text and text.strip()
            else f'<p class="aviso-caja">{th("web.mail.no_copy")}</p>')
    return "\n".join([
        _back(account_id),
        f'<h2 class="asunto-correo">{e(subject)}</h2>',
        f'<dl class="sobre">{dl}<dt>{th("web.mail.f.state")}</dt><dd>{_mark(row)}</dd></dl>',
        body,
        thread_html(account_id, row, thread, texts),
        f'<p class="quiet">{th("web.mail.readonly")}</p>',
    ]) + "\n"


def thread_html(account_id: str, current: dict, thread: list[dict], texts: dict) -> str:
    """
    La conversación (web/thread.py), en orden de hora. El correo abierto va marcado;
    un recibido es un enlace para abrirlo, y un enviado trae su texto si el servidor
    guardó copia en Enviados.
    """
    th = i18n.th
    out = [f'<h3>{th("web.mail.thread_h")}</h3>']
    if len(thread) <= 1:
        out.append(f'<p class="quiet">{th("web.mail.thread_alone")}</p>')
        return "\n".join(out)
    out.append(f'<p class="quiet">{th("web.mail.thread_lead", n=len(thread))}</p>')
    out.append('<ol class="hilo">')
    for r in thread:
        this = r is current
        cc = f' · Cc {e(r["cc"])}' if r["kind"] == "out" and r.get("cc") else ""
        meta = f'{e(_when(r["at"]))} · {e(r["subject"] or i18n.t("web.mail.no_subject"))}'
        if this:
            extra = f'<span class="estado estado-actual">{th("web.mail.thread_this")}</span>'
        elif r["kind"] == "in":
            extra = f'<a href="{href(account_id, r)}">{th("web.mail.open")}</a> {_mark(r)}'
        else:
            text = texts.get(r["message_id"])
            extra = (f'<pre class="cuerpo">{e(text)}</pre>' if text and text.strip()
                     else f'<p class="quiet">{th("web.mail.no_copy")}</p>')
        out.append(f"""<li class="hilo-{r['kind']}{' hilo-actual' if this else ''}">
  <div class="de">{_who(r)}{cc}{_roster(r)}</div>
  <div class="quiet">{meta}</div>
  {extra}
</li>""")
    out.append("</ol>")
    return "\n".join(out)


def _envelope(row: dict, message: dict | None) -> str:
    th = i18n.th
    sender = row["sender_name"] + (f" <{row['sender_address']}>" if row["sender_address"] else "")
    fields = [("web.mail.f.from", (message or {}).get("from") or sender)]
    if message:
        if message.get("to"):
            fields.append(("web.mail.f.to", message["to"]))
        if message.get("cc"):
            fields.append(("web.mail.f.cc", message["cc"]))
    fields.append(("web.mail.f.date", _when(row["observed_at"])))
    rows = "".join(f"<dt>{th(k)}</dt><dd>{e(v)}</dd>" for k, v in fields)
    state = _state(row["state"])
    roster = (f' <span class="marca-roster" title="{th("web.mail.roster_title")}">{th("web.mail.roster")}</span>'
              if row["roster"] else "")
    subject = (message or {}).get("subject") or row["subject"] or i18n.t("web.mail.no_subject")
    return (f'<h2 class="asunto-correo">{e(subject)}</h2>\n'
            f'<dl class="sobre">{rows}<dt>{th("web.mail.f.state")}</dt><dd>{state}{roster}</dd></dl>')
