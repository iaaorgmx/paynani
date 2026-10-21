"""
Las pantallas de Email Accounts (PRD #434 FR-13 a FR-15), dentro del marco de
shell.py. Todo lo que viene de un correo pasa por `e()`: un asunto o un cuerpo no
puede meter marcado en la página.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import getaddresses
from urllib.parse import quote as urlquote

from .. import i18n
from . import quote, shell
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
        out += (f'<p class="acciones-cuenta"><a class="peligro-enlace" href="/cuentas/{urlquote(account_id)}/quitar">'
                f'{th("web.acct.remove_nav")}</a></p>\n')
    return out


def href(account_id: str, row: dict) -> str:
    """El enlace a un correo de la lista: `?e=<evento>` si se recibió, `?s=<Message-ID>` si se envió."""
    if row["kind"] == "out":
        return f"/email/{urlquote(account_id)}/ver?s={urlquote(row['message_id'], safe='')}"
    return f"/email/{urlquote(account_id)}/ver?e={urlquote(row['event_id'], safe='')}"


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
           '<ul class="correos">',
           f'<li class="correos-cabecera" aria-hidden="true"><span>{th("web.mail.col.from")}</span>'
           f'<span>{th("web.mail.col.subject")}</span><span>{th("web.mail.col.when")}</span>'
           f'<span>{th("web.mail.col.state")}</span><span></span></li>']
    for r in rows:
        subject = r["subject"] or i18n.t("web.mail.no_subject")
        out.append(f"""<li class="correo-{r['kind']}"><a href="{href(account_id, r)}#{anchor(r)}">
  <span class="quien">{_who(r)}{_roster(r)}</span>
  <span class="asunto">{e(subject)}</span>
  <span class="cuando">{e(_when(r['at']))}</span>
  <span class="estado-celda">{_mark(r)}</span>
  <span class="flecha" aria-hidden="true">›</span>
</a></li>""")
    out.append("</ul>")
    if next_offset is not None:
        out.append(f'<p class="mas"><a class="secundario" href="/email/{urlquote(account_id)}?desde={next_offset}">'
                   f'{th("web.mail.more")}</a></p>')
    return "\n".join(out) + "\n"


def _back(account_id: str) -> str:
    return f'<p class="volver"><a href="/email/{urlquote(account_id)}">← {i18n.th("web.mail.back")}</a></p>'


def anchor(row: dict) -> str:
    """El id de un mensaje en la página del hilo (`#m-<id>`), sin datos del correo en claro."""
    return "m-" + hashlib.sha256(row_key(row).encode("utf-8")).hexdigest()[:12]


def row_key(row: dict) -> str:
    return row["event_id"] if row["kind"] == "in" else "s:" + row["message_id"]


def _local(stamp: str) -> tuple[str, str]:
    """(ISO 8601 en UTC para `<time datetime>`, la fecha y la hora en la zona del host). T4
    la cambia a la zona del navegador; esta es la que queda si el script no corre (Q50 = A)."""
    if not stamp:
        return "", ""
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return "", stamp
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    utc = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return utc, when.astimezone().strftime("%Y-%m-%d %H:%M")


def display_subject(subject: str) -> str:
    """El asunto del hilo como Gmail: sin «Re:» ni «Fw:» delante, con sus mayúsculas."""
    s = (subject or "").strip()
    while True:
        new = re.sub(r"^(re|fw|fwd|rv|res)\s*:\s*", "", s, flags=re.IGNORECASE)
        if new == s:
            return s
        s = new


def _people(header: str, own: str) -> str:
    """«Ana, mí» de una cabecera To o Cc: el nombre si lo trae, si no la dirección, y «mí» para la cuenta."""
    names = []
    for name, address in getaddresses([header or ""]):
        if not address:
            continue
        if address.strip().lower() == own:
            names.append(i18n.t("web.mail.me"))
        else:
            names.append(name.strip() or address.strip())
    return ", ".join(names)


def _header(row: dict, message: dict | None, own: str, own_name: str) -> tuple[str, str, str, str]:
    """(nombre, dirección, para, cc) de un mensaje, del correo leído o, si no se leyó, del
    sobre del ledger o de la línea de sent.log."""
    if message and message.get("from"):
        pairs = getaddresses([message["from"]])
        name, address = pairs[0] if pairs else ("", "")
    elif row["kind"] == "in":
        name, address = row.get("sender_name", ""), row.get("sender_address", "")
    else:
        name, address = own_name, own
    if not name and address.strip().lower() == own:
        name = own_name
    to = (message or {}).get("to") if message else (row.get("to", "") if row["kind"] == "out" else own)
    cc = (message or {}).get("cc") if message else row.get("cc", "")
    return name or address, address, _people(to or "", own), _people(cc or "", own)


def _body(message: dict) -> str:
    """El cuerpo como texto escapado, con el texto citado plegado detrás de «•••» (4.5)."""
    th = i18n.th
    parts = quote.split(message.get("text") or "")
    if not parts:
        return f'<p class="quiet">{th("web.mail.nobody")}</p>'
    out = []
    for kind, text in parts:
        if kind == "text":
            out.append(f'<div class="texto">{e(text)}</div>')
        else:
            out.append(f'<details class="cita"><summary title="{th("web.mail.show_quote")}" '
                       f'aria-label="{th("web.mail.show_quote")}">•••</summary><div class="texto">{e(text)}</div></details>')
    return "\n".join(out)


def _message_li(account_id: str, row: dict, got: dict, current: dict, own: str, own_name: str) -> str:
    th = i18n.th
    message, error = got.get("message"), got.get("error")
    name, address, to, cc = _header(row, message, own, own_name)
    iso, shown = _local((message or {}).get("date") or row.get("at", ""))
    who = "agente" if row["kind"] == "out" else "contacto"
    marks = (_state(row["state"]) + _roster(row)) if row["kind"] == "in" else ""
    dest = th("web.mail.to_line", who=to) if to else ""
    if cc:
        dest += f' · {th("web.mail.cc_line", who=cc)}'
    notes = []
    if message:
        if message["source"] == "html":
            notes.append(f'<p class="quiet nota">{th("web.mail.html_note")}</p>')
        if message["truncated"]:
            notes.append(f'<p class="quiet nota">{th("web.mail.truncated", n=len(message["text"]))}</p>')
        if message["attachments"]:
            notes.append(f'<p class="quiet nota">{th("web.mail.attachments", names=", ".join(message["attachments"]))}</p>')
        body = _body(message)
    else:
        code = error.code if error is not None else "gone"
        # Un enviado sin copia en Enviados es lo normal en un servidor que no la guarda:
        # una nota. Lo demás (no se pudo leer un recibido) es un aviso.
        cls = "quiet nota sin-copia" if code in ("no_copy", "no_sent") else "aviso-caja"
        body = f'<p class="{cls}">{th("web.mail.err." + code, detail=getattr(error, "detail", ""))}</p>'
    addr = f' <span class="direccion">&lt;{e(address)}&gt;</span>' if address and address != name else ""
    return f"""<li id="{anchor(row)}" class="mensaje{' abierto' if row is current else ''}">
  <div class="cabecera">
    <div class="avatar-mensaje avatar-{who}" aria-hidden="true">{e(shell.initials(name))}</div>
    <div class="quien"><b>{e(name)}</b>{addr}<div class="para">{dest}</div></div>
    <div class="cuando">{marks}<time datetime="{e(iso)}">{e(shown)}</time></div>
  </div>
  {''.join(notes)}
  {body}
</li>"""


FOLD = 10        # con más de 10 mensajes se pliegan los del medio (4.8)
KEEP_HEAD, KEEP_TAIL = 2, 3


def thread_page(account_id: str, current: dict, convo: list[dict], loaded: dict, *, own: str,
                own_name: str = "") -> str:
    """
    La página de un correo abierto como un hilo de Gmail (PRD #455): el asunto una vez y
    todos los mensajes, del más viejo al más nuevo, con el mismo formato. El abierto va con
    un borde suave y su `id` es el `#m-<id>` del enlace. Con más de 10, los del medio se
    pliegan en «N mensajes más», salvo el abierto.
    """
    th = i18n.th
    own = (own or "").strip().lower()
    items = [_message_li(account_id, r, loaded.get(row_key(r), {}), current, own, own_name) for r in convo]
    shown = set(range(len(convo)))
    if len(convo) > FOLD:
        shown = set(range(KEEP_HEAD)) | set(range(len(convo) - KEEP_TAIL, len(convo)))
        shown |= {i for i, r in enumerate(convo) if r is current}
    out, hidden = [], []

    def close_fold():
        if hidden:
            out.append(f'<li class="plegados"><details><summary>{th("web.mail.more_messages", n=len(hidden))}'
                       f'</summary><ol class="mensajes">{"".join(hidden)}</ol></details></li>')
            hidden.clear()
    for i, item in enumerate(items):
        if i in shown:
            close_fold()
            out.append(item)
        else:
            hidden.append(item)
    close_fold()
    subject = display_subject(current.get("subject", "")) or i18n.t("web.mail.no_subject")
    return "\n".join([
        _back(account_id),
        f'<h2 class="asunto-correo">{e(subject)}</h2>',
        '<ol class="mensajes">', *out, "</ol>",
    ]) + "\n"
