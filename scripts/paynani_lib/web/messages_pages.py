"""
Messages (PRD #434 FR-17 a FR-19): las conversaciones SMS de la pasarela, dentro
del marco de shell.py.

- `/messages`: una fila por número, la conversación con lo más reciente primero,
  de 50 en 50. Cada una dice quién es (el nombre del roster, o el que mandó el
  teléfono), lo último que pasó y si hubo llamadas perdidas.
- `/messages/ver?n=<número>`: la conversación como `paynani sms thread`, con lo
  que llegó, lo que mandó el agente con su estado y lo que contestó el dueño desde
  PaynaniApp, más las llamadas (FR-18). Los 50 más recientes, con «Ver anteriores».
- Sólo muestra (FR-19). Todo lo que viene de un SMS pasa por `e()`.
"""
from __future__ import annotations

from urllib.parse import quote

from .. import i18n
from .shell import e

PAGE = 50


def _who(conv_or_item: dict, names: dict) -> str:
    number = conv_or_item["number"]
    return names.get(number) or conv_or_item.get("name") or number


def _local(stamp: str) -> str:
    """`2026-10-21T03:09:45-05:00` como `2026-10-21 03:09` (hora del host)."""
    if len(stamp) >= 16 and "T" in stamp:
        return stamp[:10] + " " + stamp[11:16]
    return stamp


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


def list_body(convs: list[dict], names: dict, offset: int, next_offset: int | None, total: int) -> str:
    th = i18n.th
    if not total:
        return f'<p class="lead">{th("web.sms.empty")}</p>\n'
    out = [f'<p class="quiet resumen">{th("web.sms.count", n=total)} · {th("web.mail.readonly")}</p>',
           '<ul class="correos conversaciones">']
    for c in convs:
        href = f"/messages/ver?n={quote(c['number'], safe='')}"
        missed = (f' <span class="marca-llamada">{th("web.sms.missed_n", n=c["missed"])}</span>'
                  if c["missed"] else "")
        roster = (f' <span class="marca-roster" title="{th("web.sms.roster_title")}">{th("web.mail.roster")}</span>'
                  if c["number"] in names else "")
        out.append(f"""<li><a href="{href}">
  <span class="quien">{e(_who(c, names))}{roster}</span>
  <span class="asunto">{e(_preview(c['last']))}</span>
  <span class="cuando">{e(_local(c['last']['local']))}</span>
  <span class="estado">{th('web.sms.n_items', n=c['count'])}{missed}</span>
</a></li>""")
    out.append("</ul>")
    if next_offset is not None:
        out.append(f'<p class="mas"><a class="secundario" href="/messages?desde={next_offset}">{th("web.mail.more")}</a></p>')
    return "\n".join(out) + "\n"


def _status(status: str) -> str:
    if not status:
        return ""
    label = i18n.t(f"web.sms.status.{status}")
    return f' <span class="estado estado-sms-{e(status)}">{e(label if not label.startswith("web.") else status)}</span>'


def thread_body(number: str, who: str, items: list[dict], offset: int, pause_until: str | None) -> str:
    """`items` en orden de hora; se muestran los `PAGE` más recientes desde `offset`
    contado desde el final."""
    th = i18n.th
    back = f'<p class="volver"><a href="/messages">← {th("web.sms.back")}</a></p>'
    head = [back, f'<h2 class="asunto-correo">{e(who)}</h2>',
            f'<p class="quiet">{e(number)} · {th("web.sms.n_items", n=len(items))}</p>']
    if pause_until:
        head.append(f'<p class="aviso-caja" role="status">{th("web.sms.paused", until=_local(pause_until))}</p>')
    if not items:
        head.append(f'<p class="lead">{th("web.sms.thread_empty")}</p>')
        return "\n".join(head) + "\n"
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
        label = {"received": e(who), "agent": th("web.sms.by_agent"), "human": th("web.sms.by_owner")}[kind]
        body = e(item.get("text") or "") or f'<span class="quiet">{th("web.sms.no_text")}</span>'
        bubbles.append(f'<li class="sms sms-{kind}"><div class="globo"><div class="de">{label}{_status(item["status"])}</div>'
                       f'<div class="texto">{body}</div><time>{when}</time></div></li>')
    bubbles.append("</ol>")
    return "\n".join(head + bubbles + [f'<p class="quiet">{th("web.sms.readonly")}</p>']) + "\n"
