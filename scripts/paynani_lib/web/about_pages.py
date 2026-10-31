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
"""
from __future__ import annotations

from urllib.parse import quote

from .. import i18n
from ..brand import brand_svg
from .shell import e, icon

REPO = "https://github.com/iaaorgmx/paynani"
WEB = "https://iaa.org.mx"


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


def _row(ico: str, title: str, detail: str, href: str = "") -> str:
    inner = (f'<span class="about-ico">{icon(ico)}</span>'
             f'<span class="about-txt"><b>{title}</b><small>{detail}</small></span>')
    if not href:
        return f'<li><div class="about-row">{inner}</div></li>'
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
  ])}
  <p class="about-copy">{_th("copyright")}</p>
</div>
<script src="/assets/about.js" defer></script>
"""
