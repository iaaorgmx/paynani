"""
El marco de PaynaniWeb con sesión: el menú lateral, la barra de arriba y el
encabezado de PDSL-201 (PRD #434 FR-10, FR-12).

- **Menú** (FR-10): *Management* con Email Accounts (un desplegable con una
  entrada por cuenta: la del agente, del `.env`, y las de `accounts.json`),
  Messages, «WhatsApp messages» (sólo con WhatsApp configurado, PRD #550 FR-24) y
  Roster; *Tools* con Log out. Lo que el PRD deja fuera de la v1 (AI
  Assistant, Settings, Sessions, el buscador, el chat flotante) no se dibuja: un
  control que no hace nada es peor que no tenerlo.
- **Avatar** (FR-8): las iniciales arriba a la derecha abren un menú con el
  nombre, el correo, Profile y Log out. Es un `<details>`: no hace falta script.
- **Fijo y colapsable** (PRD #537, como el /dash de ServiceButton): el menú, la
  barra y el encabezado se quedan fijos al hacer scroll (`position: sticky` en
  `web.css`). El botón junto al logotipo colapsa el menú y ☰, en la barra, lo
  vuelve a abrir; `nav.js` guarda el estado en la cookie `paynani_web_nav`, que
  el servidor lee para dibujar la página ya colapsada, sin parpadeo.
- **Celular** (FR-12, PRD #537 FR-14 a FR-17): por debajo de 900 px el mismo menú
  empieza escondido y ☰ lo abre encima del contenido. Sin JavaScript, ☰ es un
  enlace normal a `#menu-lateral`, sin `aria-expanded`, y `:target` lo abre.
- **Marca:** sobre el menú oscuro va el logotipo claro. Se inserta en línea y lo
  repinta `web.css` por sus clases `.voluta` y `.logotipo` (brand/README.md), con
  los colores de `paynani-horizontal-claro.svg`.

Los íconos son trazos SVG en línea, sin atributos `style` (la CSP no los
permite): el color sale de `currentColor` y de las clases de `web.css`.
"""
from __future__ import annotations

import html
from http import cookies

from .. import i18n
from ..brand import brand_svg

# La cuenta del agente en las rutas (/email/main): `main` es el id que
# accounts.py reserva para el .env, así que ninguna cuenta adicional lo tiene.
AGENT_ID = "main"

ICONS = {
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
    "roster": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "profile": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="10" r="3"/><path d="M7 18.7a6 6 0 0 1 10 0"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "back": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "menu": '<path d="M3 6h18M3 12h18M3 18h18"/>',
    "panel": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M16 9l-3 3 3 3"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "key": '<circle cx="7" cy="15" r="4"/><path d="m10 12 10-10 2 2-3 3 2 2-3 3-2-2-3 3"/>',
    "chat": '<path d="M21 11.5a8.4 8.4 0 0 1-12.4 7.4L3 20.5l1.6-5.4A8.4 8.4 0 1 1 21 11.5z"/>',
    "warn": '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
}


# The brand favicon (brand/favicon.svg), served by app.STATIC.
FAVICON_LINK = '<link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">'

# PRD #537 FR-10: nav.js la escribe; sólo `collapsed` cuenta, cualquier otro valor
# (o ninguno) es el menú abierto.
NAV_COOKIE = "paynani_web_nav"
NAV_COLLAPSED = "collapsed"


def nav_collapsed(cookie_header: str) -> bool:
    """FR-11: si la cookie dice que el menú va colapsado."""
    try:
        morsel = cookies.SimpleCookie(cookie_header or "").get(NAV_COOKIE)
    except cookies.CookieError:
        return False
    return morsel is not None and morsel.value == NAV_COLLAPSED


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def icon(name: str, extra: str = "") -> str:
    cls = f"i {extra}".strip()
    return (f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def initials(name: str) -> str:
    """Las iniciales del avatar: sólo letras y números de cada palabra."""
    parts = ["".join(c for c in p if c.isalnum()) for p in (name or "").split()]
    parts = [p for p in parts if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def mail_accounts(agent_email: str, additional: list[dict]) -> list[dict]:
    """Las entradas del desplegable: la cuenta del agente primero y luego las de
    accounts.json en su orden. Una cuenta apagada se muestra, marcada."""
    out = []
    if agent_email:
        out.append({"id": AGENT_ID, "email": agent_email, "enabled": True, "agent": True})
    for account in additional:
        out.append({"id": account["id"], "email": account["email"],
                    "enabled": account.get("enabled", True), "agent": False})
    return out


def _nav(accounts: list[dict], active: str, active_account: str, csrf: str, accounts_error: str,
         whatsapp: bool = False) -> str:
    th = i18n.th
    open_attr = " open"   # abierto siempre, como en PDSL-201: las cuentas son el centro
    items = []
    for a in accounts:
        cls = ["sub"]
        if a["id"] == active_account:
            cls.append("activo")
        if not a["enabled"]:
            cls.append("apagada")
        tag = f' <span class="etiqueta">{th("web.nav.off")}</span>' if not a["enabled"] else ""
        current = ' aria-current="page"' if a["id"] == active_account else ""
        items.append(f'<a class="{" ".join(cls)}" href="/email/{e(a["id"])}" title="{e(a["email"])}"{current}>'
                     f'<span class="dir">{e(a["email"])}</span>{tag}</a>')
    if accounts_error:
        items.append(f'<span class="sub aviso-menu" role="status">{icon("warn")}{th("web.nav.accounts_error")}</span>')
    if not items:
        items.append(f'<span class="sub vacio">{th("web.nav.no_accounts")}</span>')
    items.append(f'<a class="sub agregar" href="/cuentas/nueva">+ {th("web.acct.add_nav")}</a>')

    def entry(key, href, ico, label_key):
        current = ' aria-current="page"' if active == key else ""
        cls = ' class="activo"' if active == key else ""
        return f'<a href="{href}"{cls}{current}>{icon(ico)}<span>{th(label_key)}</span></a>'

    return f"""
  <div class="grupo">{th('web.nav.management')}</div>
  <nav aria-label="{th('web.nav.management')}">
    <details class="cuentas"{open_attr}>
      <summary{' class="activo"' if active == 'email' else ''}>{icon('mail')}<span>{th('web.nav.email')}</span>{icon('chevron', 'flecha')}</summary>
      {''.join(items)}
    </details>
    {entry('messages', '/messages', 'inbox', 'web.nav.messages')}
    {entry('whatsapp', '/whatsapp/messages', 'chat', 'web.wa.nav') if whatsapp else ''}
    {entry('roster', '/roster', 'roster', 'web.nav.roster')}
    {entry('api_tokens', '/api-tokens', 'key', 'web.tokens.title')}
  </nav>
  <div class="grupo separa">{th('web.nav.tools')}</div>
  <nav aria-label="{th('web.nav.tools')}">
    <form method="post" action="/logout" class="salir">
      <input type="hidden" name="csrf" value="{e(csrf)}">
      <button type="submit">{icon('logout')}<span>{th('web.logout')}</span></button>
    </form>
  </nav>
"""


def page(lang: str, user: dict, csrf: str, *, title: str, body: str, active: str = "",
         active_account: str = "", accounts: list[dict] | None = None, accounts_error: str = "",
         icon_name: str = "home", back: str = "", wide: bool = False, collapsed: bool = False,
         whatsapp: bool = False) -> str:
    """Una página con sesión. `body` ya viene escapado. `wide` deja que el panel use todo el ancho
    (la lista de correos, como Orders en el /dash). `collapsed` dibuja el menú colapsado
    (PRD #537 FR-11); en el celular no cuenta, ahí el menú siempre empieza escondido. `whatsapp`
    agrega «WhatsApp messages» al menú, sólo con WhatsApp configurado (PRD #550 FR-24)."""
    th = i18n.th
    accounts = accounts or []
    logo = brand_svg("paynani-horizontal.svg")
    nav = _nav(accounts, active, active_account, csrf, accounts_error, whatsapp)
    name = user.get("name", "")
    back_link = (f'<a class="atras" href="{e(back)}" aria-label="{th("web.back")}">{icon("back")}</a>'
                 if back else "")
    # Sólo el botón de colapsar, que sin JavaScript no se muestra. ☰ sale como un
    # enlace normal a #menu-lateral: sin JavaScript lo abre :target, que no cambia
    # atributos, así que no afirma ningún estado; nav.js le pone role, aria-controls
    # y aria-expanded al arrancar (revisión de Ximena y Metis en #539).
    expanded = "false" if collapsed else "true"
    return f"""<!doctype html>
<html lang="{e(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · PaynaniWeb</title>
{FAVICON_LINK}
<link rel="stylesheet" href="/assets/app.css">
<link rel="stylesheet" href="/assets/web.css">
<script src="/assets/time.js" defer></script>
<script src="/assets/nav.js" defer></script>
</head>
<body class="web-shell{' menu-colapsado' if collapsed else ''}">
<aside class="lateral" id="menu-lateral">
  <div class="marca-lateral">
    <a href="/" aria-label="PaynaniWeb">{logo}</a>
    <button type="button" class="colapsar" aria-controls="menu-lateral" aria-expanded="{expanded}"
            aria-label="{th('web.nav.collapse')}" title="{th('web.nav.collapse')}" hidden>{icon('panel')}</button>
  </div>
  <div class="usuario">
    <b>{e(name)}</b>
    <small>paynani</small>
  </div>
  {nav}
</aside>
<a class="velo" href="#menu-cerrado" tabindex="-1" aria-hidden="true"></a>
<div class="columna">
  <header class="barra">
    <a class="mostrar" href="#menu-lateral" aria-label="{th('web.nav.expand')}" title="{th('web.nav.expand')}">{icon('menu')}</a>
    <a class="marca-barra" href="/" aria-label="PaynaniWeb">{logo}</a>
    <details class="avatar">
      <summary aria-label="{th('web.nav.account_menu')}"><span class="iniciales">{e(initials(name))}</span></summary>
      <div class="avatar-panel">
        <b>{e(name)}</b>
        <small>{e(user.get('email', ''))}</small>
        <a href="/profile">{icon('profile')}<span>{th('web.nav.profile')}</span></a>
        <form method="post" action="/logout">
          <input type="hidden" name="csrf" value="{e(csrf)}">
          <button type="submit">{icon('logout')}<span>{th('web.logout')}</span></button>
        </form>
      </div>
    </details>
  </header>
  <div class="encabezado">
    {icon(icon_name)}
    <h1>{e(title)}</h1>
    {back_link}
  </div>
  <main class="panel{' panel-ancho' if wide else ''}">
{body}
  </main>
</div>
</body>
</html>
"""
