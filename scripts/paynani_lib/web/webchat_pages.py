"""
Webchat (#648): el dueño platica con su agente desde PaynaniWeb, con archivos y fotos
(Q305 = B, Q306 = A). Sólo con la sesión de PaynaniWeb (Q307 = A).

- `body(...)` es la página: el agente y su estado arriba, la conversación en burbujas (el
  dueño a la derecha, el agente a la izquierda con su nombre), con un separador por día,
  «escribiendo…» y el cuadro de escribir con el clip.
- `bubbles(messages, ...)` son los renglones de la conversación; `/webchat/updates` los
  manda ya dibujados y `assets/webchat.js` los agrega al final, así que se dibujan en un
  solo lugar.
- Las fotos y los archivos salen por `/webchat/file?ref=f_…`, nunca por una ruta del disco.
"""
from __future__ import annotations

import datetime as dt
from urllib.parse import quote

from .. import i18n
from . import agent_pages, when
from .dashboard import parse
from .shell import e, icon

MAX_FILES = 10


def _th(key: str, **kw) -> str:
    return i18n.th("web.wc." + key, **kw)


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _file_url(ref: str) -> str:
    return "/webchat/file?ref=" + quote(ref, safe="")


def _files(files: list[dict]) -> str:
    out = []
    for f in files:
        url = _file_url(f.get("ref", ""))
        name = f.get("name", "")
        if f.get("kind") == "image":
            out.append(f'<a class="wc-foto" href="{e(url)}"><img src="{e(url)}" alt="{_th("photo", name=name)}" '
                       f'loading="lazy"></a>')
        else:
            out.append(f'<a class="wc-archivo" href="{e(url)}" title="{_th("download", name=name)}">{icon("file")}'
                       f'<span><b>{e(name)}</b><small>{e(_size(int(f.get("size") or 0)))}</small></span></a>')
    return "".join(out)


def _day_label(day: dt.date, today: dt.date) -> str:
    if day == today:
        return _th("today")
    if day == today - dt.timedelta(days=1):
        return _th("yesterday")
    months = when.MONTHS.get(i18n.current_lang()[:2], when.MONTHS["en"])
    return e(f"{day.day} {months[day.month - 1]}" + (f" {day.year}" if day.year != today.year else ""))


def bubbles(messages: list[dict], now: dt.datetime, agent_name: str, last_day: dt.date | None = None) -> str:
    """Los renglones (`<li>`) de la conversación, con el separador de cada día nuevo."""
    rows = []
    for m in messages:
        at = parse(m.get("at"))
        local = at.astimezone(now.tzinfo) if at else now
        if local.date() != last_day:
            last_day = local.date()
            rows.append(f'<li class="wc-dia" data-day="{last_day.isoformat()}"><span>{_day_label(last_day, now.date())}</span></li>')
        mine = m.get("by") == "owner"
        who = "" if mine else f'<div class="de">{e(agent_name)}</div>'
        text = f'<div class="texto">{e(m.get("text", ""))}</div>' if m.get("text") else ""
        stamp = f'<time datetime="{e(m.get("at", ""))}">{local.strftime("%H:%M")}</time>'
        rows.append(f'<li class="wc {"wc-yo" if mine else "wc-agente"}" id="{e(m.get("id", ""))}">'
                    f'<div class="globo">{who}{_files(m.get("files") or [])}{text}{stamp}</div></li>')
    return "".join(rows)


def render(messages: list[dict], now: dt.datetime, agent_name: str, day: str) -> tuple[str, str]:
    """Para /webchat/ws: los mensajes nuevos dibujados y el día del último separador."""
    try:
        last_day = dt.date.fromisoformat(day) if day else None
    except ValueError:
        last_day = None
    html = bubbles(messages, now, agent_name, last_day)
    at = parse(messages[-1].get("at")) if messages else None
    return html, (at.astimezone(now.tzinfo).date().isoformat() if at else day)


def typing_row(agent_name: str, on: bool) -> str:
    return (f'<li class="wc wc-agente wc-escribe" id="wc-escribe"{"" if on else " hidden"}><div class="globo">'
            f'<span class="wc-puntos" aria-hidden="true"><i></i><i></i><i></i></span> {_th("writing", name=agent_name)}'
            f'</div></li>')


def draft_row(agent_name: str) -> str:
    """La respuesta que el agente va escribiendo (`message.delta`, Q309); vacía hasta que llega."""
    return (f'<li class="wc wc-agente wc-borrador" id="wc-borrador" hidden><div class="globo">'
            f'<div class="de">{e(agent_name)}</div><div class="texto"></div></div></li>')


def _error(text: str) -> str:
    return f'<p class="error-caja" role="alert">{e(text)}</p>' if text else ""


def composer(csrf: str, agent_name: str, text: str = "", error: str = "") -> str:
    """
    Una sola barra, como Telegram (Julian, Q321): el clip pequeño dentro, a la izquierda, que
    abre «Foto» y «Archivo» (un `<details>`, sin script); el
    cuadro de escribir con todo el espacio, que crece solo hasta unas 6 líneas (webchat.js);
    y «Enviar» como botón redondo. Los límites de los adjuntos van en el título del clip.
    """
    return f"""<form class="wc-escribir" method="post" action="/webchat/enviar" enctype="multipart/form-data">
    {_error(error)}
    <input type="hidden" name="csrf" value="{e(csrf)}">
    <div class="wc-adjuntos" id="wc-adjuntos" data-remove="{_th('remove', name='{name}')}"></div>
    <div class="wc-barra">
      <details class="wc-adjuntar">
        <summary class="wc-clip" title="{_th('note')}">{icon("clip")}<span class="solo-lector">{_th('attach')}</span></summary>
        <div class="wc-menu">
          <label class="wc-opcion">{icon("photo")}<span>{_th("opt_photo")}</span>
            <input type="file" name="files" class="wc-archivos" multiple accept="image/jpeg,image/png,image/webp,image/gif"></label>
          <label class="wc-opcion">{icon("file")}<span>{_th("opt_file")}</span>
            <input type="file" name="files" class="wc-archivos" multiple accept=".pdf,.txt,.csv,.docx,.xlsx,.zip,application/pdf,text/plain,text/csv,application/zip"></label>
        </div>
      </details>
      <textarea name="text" rows="1" maxlength="4000" placeholder="{_th('placeholder', name=agent_name)}"
                aria-label="{_th('placeholder', name=agent_name)}">{e(text)}</textarea>
      <button type="submit" class="wc-enviar" aria-label="{_th('send')}" title="{_th('send')}">{icon("send")}</button>
    </div>
  </form>"""


def body(messages: list[dict], now: dt.datetime, summary: dict | None, csrf: str, *, typing: bool = False,
         available: bool = True, text: str = "", error: str = "") -> str:
    name = (summary or {}).get("name") or "AI agent"
    head = f"""<div class="wc-cab">
    <span class="wc-avatar" aria-hidden="true">{icon("agent")}</span>
    <div><b>{e(name)}</b>{agent_pages.chips(summary["runtime_label"], summary["status"]) if summary else ""}</div>
  </div>"""
    if not available:
        return f'<div class="wc-pag">{head}<p class="aviso-caja" role="status">{_th("unavailable")}</p></div>'
    convo = bubbles(messages, now, name)
    empty = "" if messages else f'<li class="wc-vacio quiet" id="wc-vacio">{_th("empty")}</li>'
    last = messages[-1]["id"] if messages else ""
    return f"""<div class="wc-pag" data-after="{e(last)}">
  {head}
  <ol class="wc-hilo" id="wc-hilo" aria-live="polite">{empty}{convo}{typing_row(name, typing)}{draft_row(name)}</ol>
  {composer(csrf, name, text, error)}
</div>
<script src="/assets/webchat.js" defer></script>
"""
