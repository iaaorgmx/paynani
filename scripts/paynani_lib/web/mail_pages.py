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


def list_body(account_id: str, rows: list[dict], total: int, offset: int, next_offset: int | None) -> str:
    th = i18n.th
    if not total:
        return f'<p class="lead">{th("web.mail.empty")}</p>\n'
    out = [f'<p class="quiet resumen">{th("web.mail.count", n=total)} · {th("web.mail.readonly")}</p>',
           '<ul class="correos">']
    for r in rows:
        href = f"/email/{quote(account_id)}/ver?e={quote(r['event_id'], safe='')}"
        who = r["sender_name"] or r["sender_address"]
        roster = (f' <span class="marca-roster" title="{th("web.mail.roster_title")}">{th("web.mail.roster")}</span>'
                  if r["roster"] else "")
        subject = r["subject"] or i18n.t("web.mail.no_subject")
        out.append(f"""<li><a href="{href}">
  <span class="quien">{e(who)}{roster}</span>
  <span class="asunto">{e(subject)}</span>
  <span class="cuando">{e(_when(r['observed_at']))}</span>
  {_state(r['state'])}
</a></li>""")
    out.append("</ul>")
    if next_offset is not None:
        out.append(f'<p class="mas"><a class="secundario" href="/email/{quote(account_id)}?desde={next_offset}">'
                   f'{th("web.mail.more")}</a></p>')
    return "\n".join(out) + "\n"


def message_body(account_id: str, row: dict, message: dict | None, error=None) -> str:
    th = i18n.th
    back = f'<p class="volver"><a href="/email/{quote(account_id)}">← {th("web.mail.back")}</a></p>'
    head = [back]
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
    thread = (f'<h3>{th("web.mail.thread_h")}</h3>\n<p class="quiet">{th("web.mail.thread_soon")}</p>')
    return "\n".join(head + notes + [body, thread, f'<p class="quiet">{th("web.mail.readonly")}</p>']) + "\n"


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
