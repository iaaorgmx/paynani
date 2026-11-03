"""
«About» de PaynaniWeb (#636), como el About de PaynaniApp (`AboutFragment`), dentro del
marco de shell.py.

- La tarjeta: el logo, «PaynaniWeb», la versión con su commit (Q275=A) y el párrafo de
  código abierto. `assets/about.js` agrega el botón «Copiar»; sin script, el texto se
  puede seleccionar.
- Proyecto, Ayuda y Créditos, como renglones con ícono, título y detalle. Los enlaces
  externos abren en otra pestaña con `rel="noopener noreferrer"`. «Reportar un problema»
  abre un issue nuevo en paynani con la versión ya escrita (Q276=A).
- El estado de la instalación no va aquí: está en el Dashboard (Q277=A).
- «Development team» (#686): un renglón de Créditos que abre `/about/team`, la tabla de
  humanos y agentes con su avatar de GitHub. Los datos y los avatares son una copia
  (`team.json`, `assets/team/`, `scripts/update_team.py`): la página no le pide nada a
  GitHub (Iris[Q33] = A).
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from .. import i18n
from ..brand import brand_svg
from .shell import e, icon

REPO = "https://github.com/iaaorgmx/paynani"
WEB = "https://iaa.org.mx"
TEAM_FILE = Path(__file__).with_name("team.json")
TEAM_DIR = Path(__file__).resolve().parents[1] / "assets" / "team"
PROJECTS = ("paynani", "paynaniweb", "paynaniapp")


def _th(key: str, **kw) -> str:
    return i18n.th("web.about." + key, **kw)


def version_text(version: str, commit: str) -> str:
    """«Versión 0.18.0 · 9d1935d», o sin commit si no se sabe."""
    version = version or "?"
    return (i18n.t("web.about.version", version=version, commit=commit) if commit
            else i18n.t("web.about.version_plain", version=version))


def report_url(version: str, commit: str) -> str:
    """Un issue nuevo en paynani con la versión al final del cuerpo, como la app."""
    body = f"\n\n---\nPaynaniWeb {version or '?'}" + (f" ({commit})" if commit else "")
    return f"{REPO}/issues/new?body={quote(body, safe='')}"


def _row(ico: str, title: str, detail: str, href: str = "", internal: bool = False) -> str:
    inner = (f'<span class="about-ico">{icon(ico)}</span>'
             f'<span class="about-txt"><b>{title}</b><small>{detail}</small></span>')
    if not href:
        return f'<li><div class="about-row">{inner}</div></li>'
    if internal:
        return (f'<li><a class="about-row" href="{e(href)}">{inner}'
                f'<span class="about-flecha" aria-hidden="true">›</span></a></li>')
    return (f'<li><a class="about-row" href="{e(href)}" target="_blank" rel="noopener noreferrer">{inner}'
            f'<span class="about-flecha" aria-hidden="true">↗</span>'
            f'<span class="solo-lector">{_th("new_tab")}</span></a></li>')


def _section(key: str, rows: list[str]) -> str:
    return (f'<section aria-labelledby="about-{key}"><h3 class="about-h" id="about-{key}">{_th("section_" + key)}</h3>'
            f'<ul class="about-list">{"".join(rows)}</ul></section>')


def body(version: str, commit: str) -> str:
    shown = version_text(version, commit)
    return f"""<div class="about">
  <section class="about-card">
    <div class="about-logo">{brand_svg("paynani-vertical.svg")}</div>
    <p class="about-name">PaynaniWeb</p>
    <p class="about-version"><span id="about-version">{e(shown)}</span>
      <button type="button" class="about-copiar" data-copied="{_th('copied')}" hidden>{_th("copy")}</button></p>
    <p class="about-p">{_th("p1")}</p>
  </section>
  {_section("project", [
      _row("web", _th("web"), "iaa.org.mx", WEB),
      _row("code", _th("source"), "github.com/iaaorgmx/paynani", REPO),
      _row("license", _th("license"), _th("license_detail"), f"{REPO}/blob/main/LICENSE"),
  ])}
  {_section("help", [
      _row("bug", _th("report"), _th("report_detail"), report_url(version, commit)),
      _row("news", _th("news"), _th("news_detail"), f"{REPO}/blob/main/CHANGELOG.md"),
      _row("book", _th("guide"), _th("guide_detail"), f"{REPO}/blob/main/PAYNANI_WEB.md"),
  ])}
  {_section("credits", [
      _row("python", _th("built"), _th("built_detail")),
      _row("font", _th("logo_font"), _th("logo_font_detail")),
      _row("shapes", _th("icons"), _th("icons_detail")),
      _row("roster", _th("team"), _th("team_detail"), "/about/team", internal=True),
  ])}
  <p class="about-copy">{_th("copyright")}</p>
</div>
<script src="/assets/about.js" defer></script>
"""


# ---- Development team (#686) -------------------------------------------------------------

def team() -> list[dict]:
    """Los miembros de team.json que se pueden mostrar: con tipo decidido (human o agent) y
    un avatar que existe en assets/team/. Todos en orden alfabético por nombre (Julian,
    2026-11-03), humanos y agentes juntos."""
    try:
        members = json.loads(TEAM_FILE.read_text(encoding="utf-8"))["members"]
    except (OSError, ValueError, KeyError):
        return []
    shown = [m for m in members if m.get("type") in ("human", "agent") and avatar_path(m.get("avatar", ""))]
    return sorted(shown, key=lambda m: str(m.get("name") or m["login"]).casefold())


def avatar_path(name: str) -> Path | None:
    """El archivo de un avatar de assets/team/, sólo con un nombre limpio (`login.png` o `.jpg`)."""
    import re
    if not re.fullmatch(r"[a-z0-9-]{1,39}\.(png|jpg)", name or ""):
        return None
    path = TEAM_DIR / name
    return path if path.is_file() else None


def team_assets() -> dict:
    """Las entradas de STATIC para los avatares (`/assets/team/<archivo>`)."""
    out = {}
    for m in team():
        kind = "image/png" if m["avatar"].endswith(".png") else "image/jpeg"
        out[f"/assets/team/{m['avatar']}"] = (TEAM_DIR / m["avatar"], kind)
    return out


def team_body() -> str:
    """La tabla: avatar y nombre (los dos llevan al perfil de GitHub), el @usuario, si es
    humano o agente, y en qué proyectos colaboró. En el teléfono, cada fila es una tarjeta."""
    rows = []
    for m in team():
        profile = f"https://github.com/{quote(m['login'], safe='')}"
        name = e(m.get("name") or m["login"])
        chips = "".join(f'<span class="team-chip">{_th("project_" + p)}</span>'
                        for p in PROJECTS if p in (m.get("projects") or []))
        kind = _th("type_" + m["type"])
        rows.append(
            f'<tr><td class="team-avatar"><a href="{e(profile)}" target="_blank" rel="noopener noreferrer"'
            f' title="{_th("profile", name=name)}">'
            f'<img src="/assets/team/{e(m["avatar"])}" alt="{_th("avatar_alt", name=name)}" width="48" height="48"'
            f' loading="lazy"></a></td>'
            f'<td class="team-name"><a href="{e(profile)}" target="_blank" rel="noopener noreferrer">{name}</a>'
            f'<span class="solo-lector"> {_th("new_tab")}</span><small>@{e(m["login"])}</small></td>'
            f'<td class="team-type"><span class="team-tipo team-{m["type"]}">{kind}</span></td>'
            f'<td class="team-projects">{chips}</td></tr>')
    table = (f'<table class="team-tabla"><caption class="solo-lector">{_th("team")}</caption>'
             f'<thead><tr><th scope="col"><span class="solo-lector">{_th("col_avatar")}</span></th>'
             f'<th scope="col">{_th("col_name")}</th><th scope="col">{_th("col_type")}</th>'
             f'<th scope="col">{_th("col_projects")}</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>') if rows else f'<p class="quiet">{_th("team_empty")}</p>'
    return (f'<p class="volver"><a href="/about">← {_th("back")}</a></p>'
            f'<p class="lead">{_th("team_lead")}</p>\n<div class="team">{table}</div>\n')
