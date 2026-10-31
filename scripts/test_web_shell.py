#!/usr/bin/env python3
"""
Tests for PaynaniWeb's frame (PRD #434 FR-10, FR-12; T4 of #435; PRD #537).
An assertion script, like the rest of this suite.

El menú lateral de PDSL-201 con el desplegable de cuentas (la del agente y las de
accounts.json), Messages, Roster y Log out; el menú del avatar; el menú del celular;
que no aparezca lo que la v1 deja fuera; que nada lleve `style=` (la CSP lo
bloquea); y que no quede ninguna clave sin traducir en los cinco idiomas.

PRD #537: un solo menú en todos los tamaños, el botón de colapsar y ☰ con sus
`aria-*`, la cookie `paynani_web_nav` que el servidor lee para dibujarlo colapsado,
y `nav.js` servido desde /assets/ con defer.
"""
from __future__ import annotations

import http.client
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, auth, notify, shell, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


check("iniciales de dos palabras", "JD", shell.initials("John Doe"))
check("iniciales de tres palabras: primera y última", "AR", shell.initials("Ana María Ruiz"))
check("una palabra: sus dos primeras letras", "AN", shell.initials("ana"))
check("sin nombre", "?", shell.initials(""))
check("sólo letras y números", "JB", shell.initials("John <b>Doe</b>"))
from paynani_lib import accounts as accounts_mod  # noqa: E402
check("la cuenta del agente usa el id que accounts.py reserva (main)", accounts_mod.MAIN, shell.AGENT_ID)

tmp = Path(tempfile.mkdtemp())
user_file = tmp / "web" / "user.json"
users.create("john@example.com", "John <b>Doe</b>", "una-contraseña-larga", user_file)
accounts_file = tmp / "accounts.json"
accounts_file.write_text(json.dumps({"accounts": [
    {"id": "ventas", "email": "ventas@example.com", "imap": {"host": "imap.example.com", "port": 993},
     "roster": "rosters/ventas.md", "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD", "mailboxes": ["INBOX"],
     "enabled": True},
    {"id": "soporte", "email": "soporte@example.com", "imap": {"host": "imap.example.com", "port": 993},
     "roster": "rosters/soporte.md", "password_env": "PAYNANI_ACCOUNT_SOPORTE_PASSWORD", "mailboxes": ["INBOX"],
     "enabled": False},
]}), encoding="utf-8")
agent = {"email": "agente@example.com"}
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email=lambda: agent["email"], accounts_file=accounts_file)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, cookie=""):
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.5"}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = f"https://{HOST}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


status, hdrs, _ = req("POST", "/login", form={"email": "john@example.com", "password": "una-contraseña-larga"})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


def get(path, lang="es-MX"):
    sep = "&" if "?" in path else "?"
    return req("GET", f"{path}{sep}lang={lang}", cookie=cookie)


status, _, page = get("/")
check("con sesión, / es el marco", (200, True), (status, 'class="web-shell"' in page))
check("con sesión, el marco enlaza el favicon", True, 'rel="icon" type="image/svg+xml" href="/assets/favicon.svg"' in page)
check("el menú lateral con la marca en línea", True, 'class="lateral"' in page and 'class="voluta"' in page)
check("el nombre escapado", (True, False), ("John &lt;b&gt;Doe&lt;/b&gt;" in page, "<b>Doe</b>" in page))
check("Email Accounts es un desplegable abierto", True, '<details class="cuentas" open>' in page)
# Sólo en el menú lateral: desde PRD #602 la página inicial es el Dashboard, con sus propios enlaces.
links = re.findall(r'href="(/email/[^"]+)"', page.split('<aside class="lateral"', 1)[1].split("</aside>", 1)[0])
check("una entrada por cuenta: la del agente primero, luego accounts.json en orden (un solo menú, PRD #537 FR-14)",
      ["/email/main", "/email/ventas", "/email/soporte"], links)
check("la cuenta apagada va marcada", True, 'class="sub apagada"' in page and "apagada</span>" in page)
check("Mensajes y Roster", True, 'href="/messages"' in page and 'href="/roster"' in page)
check("cerrar sesión: formularios POST con el token de la sesión", True,
      len(re.findall(r'<form method="post" action="/logout"[^>]*>\s*<input type="hidden" name="csrf" value="[^"]+">', page)) >= 2)
check("el menú del avatar con iniciales y correo", True,
      '<span class="iniciales">JB</span>' in page and "john@example.com" in page)
panel = page.split('<div class="avatar-panel">', 1)[1].split("</div>", 1)[0]
usuario = page.split('<div class="usuario">', 1)[1].split("</aside>", 1)[0].split('<div class="grupo">', 1)[0]
check("#626 (Q265=B): «Perfil» ya no está en el menú del avatar", False, 'href="/profile"' in panel)
check("#626: el acceso a Perfil va junto al nombre, en el menú lateral, con su ícono y aria-label", (True, True, True),
      ('<a class="perfil" href="/profile" aria-label="Perfil"' in usuario, 'title="Perfil"' in usuario,
       shell.ICONS["profile"] in usuario))
_, _, prof = get("/profile")
usuario_p = prof.split('<div class="usuario">', 1)[1].split('<div class="grupo">', 1)[0]
check("#626 (Q266): en /profile el acceso queda activo", (True, True),
      ('class="perfil activo"' in usuario_p, 'aria-current="page"' in usuario_p))
_, _, page_en = get("/", lang="en-US")
check("#626: el aria-label en inglés", True, 'aria-label="Profile"' in page_en.split('<div class="usuario">', 1)[1][:600])
check("ya no hay segunda copia del menú para el celular (PRD #537 FR-14)", False, "menu-movil" in page)
check("☰ es un enlace al menú, para que sin JavaScript lo abra :target (FR-16)", True,
      '<a class="mostrar" href="#menu-lateral" aria-label="Mostrar el menú" title="Mostrar el menú">' in page)
mostrar = re.search(r'<a class="mostrar"[^>]*>', page).group(0)
check("☰ sin aria-expanded, aria-controls ni role en el HTML: :target no los cambiaría (revisión de #539)",
      [], [a for a in ("aria-expanded", "aria-controls", "role=") if a in mostrar])
check("el botón de colapsar, escondido hasta que corra nav.js (FR-5, FR-13)", True,
      re.search(r'<button type="button" class="colapsar" aria-controls="menu-lateral" aria-expanded="true"\s+'
                r'aria-label="Colapsar el menú" title="Colapsar el menú" hidden>', page) is not None)
check("el menú tiene el id al que apuntan los dos", 1, page.count('id="menu-lateral"'))
check("sin la cookie, el menú va abierto", True, '<body class="web-shell">' in page)
check("el velo del celular no se alcanza con Tab ni lo lee un lector", True,
      '<a class="velo" href="#menu-cerrado" tabindex="-1" aria-hidden="true"></a>' in page)
check("el velo no apunta a «#», que llevaría la página arriba sin JavaScript", False, 'class="velo" href="#"' in page)
check("nav.js con defer, desde /assets/ (la CSP no cambia, FR-12)", True,
      '<script src="/assets/nav.js" defer></script>' in page)
for absent in ("AI Assistant", "Settings", "Sessions", "Search", "Buscar", "Asistente"):
    check(f"lo que la v1 deja fuera no se dibuja: {absent}", False, absent in page)
check("sin atributos style (la CSP los bloquea)", [], re.findall(r'\sstyle="', page))
check("sin scripts en línea", [], re.findall(r"<script(?![^>]*\ssrc=)", page))
check("la página no carga nada de fuera", [], re.findall(r'(?:src|href)="(?:https?:)?//[^"]+"', page))

status, _, page = get("/email/ventas")
check("/email/ventas: 200 con la dirección en el encabezado", (200, True), (status, "<h1>ventas@example.com</h1>" in page))
check("y su entrada marcada en el menú", True,
      'class="sub activo" href="/email/ventas" title="ventas@example.com" aria-current="page"' in page)
status, _, page = get("/email/main")
check("/email/main es la cuenta del agente", (200, True), (status, "<h1>agente@example.com</h1>" in page))
status, _, page = get("/email/nope")
check("una cuenta que no existe: 404 dentro del marco", (404, True), (status, 'class="web-shell"' in page))
for path, key in (("/messages", "Mensajes"), ("/roster", "Roster")):
    status, _, page = get(path)
    check(f"{path}: 200, marcado en el menú", (200, True), (status, f'class="activo" aria-current="page">' in page and key in page))
status, _, page = get("/profile")
check("/profile con la flecha de regreso (PDSL-201)", (200, True), (status, 'class="atras" href="/"' in page))

for lang in i18n.LANGUAGES:
    for path in ("/", "/email/ventas", "/messages", "/roster", "/profile"):
        _, _, page = get(path, lang)
        leftover = re.findall(r">\s*(web\.[a-z_.]+)\s*<", page)
        if leftover:
            check(f"{lang} {path}: sin claves sin traducir", [], leftover)
            break
    else:
        check(f"{lang}: ninguna clave sin traducir en las cinco pantallas", True)
_, _, page = get("/", "en-US")
check("en inglés el menú dice Email Accounts, Messages y Roster", True,
      all(x in page for x in ("Email Accounts", "Messages", "Roster", "Sign out")))

# accounts.json roto: queda la del agente y el menú lo dice.
accounts_file.write_text("{roto", encoding="utf-8")
status, _, page = get("/")
check("accounts.json roto: la página sale igual", 200, status)
check("con la cuenta del agente y el aviso", (["/email/main"], True),
      (re.findall(r'href="(/email/[^"]+)"', page.split('<aside class="lateral"', 1)[1].split("</aside>", 1)[0]),
       "No se pudo leer accounts.json" in page))
accounts_file.unlink()
agent["email"] = ""
status, _, page = get("/")
check("sin cuentas: lo dice en el desplegable", True, "Sin cuentas configuradas" in page)

# PRD #537 FR-10, FR-11: la cookie paynani_web_nav.
for value, collapsed in (("collapsed", True), ("open", False), ("Collapsed", False), ("x<script>", False)):
    _, _, page = req("GET", "/messages?lang=es-MX", cookie=f"{cookie}; {shell.NAV_COOKIE}={value}")
    check(f"cookie {value!r}: {'colapsado' if collapsed else 'abierto'}", collapsed,
          '<body class="web-shell menu-colapsado">' in page)
    check(f"cookie {value!r}: el botón de colapsar lo dice", 0 if collapsed else 1, page.count('aria-expanded="true"'))
    check(f"cookie {value!r}: el valor no llega al HTML", False, "x<script>" in page)
_, _, page = req("GET", "/messages?lang=es-MX", cookie=f'{cookie}; {shell.NAV_COOKIE}="mal')
check("una cabecera Cookie rota no tumba la página: abierto", True, '<body class="web-shell">' in page)
check("nav_collapsed: sólo 'collapsed'", (True, False, False, False),
      (shell.nav_collapsed("a=1; paynani_web_nav=collapsed"), shell.nav_collapsed("paynani_web_nav=open"),
       shell.nav_collapsed(""), shell.nav_collapsed('paynani_web_nav="')))
for lang, label in (("en-US", "Collapse the menu"), ("fr-FR", "Réduire le menu"), ("pt-BR", "Recolher o menu")):
    _, _, page = get("/", lang)
    check(f"{lang}: el botón dice {label!r}", True, f'aria-label="{label}"' in page)

status, hdrs, js = req("GET", "/assets/nav.js")
check("/assets/nav.js se sirve como JavaScript", (200, True),
      (status, hdrs.get("content-type", "").startswith("application/javascript")))
check("nav.js escribe la cookie que lee el servidor, con SameSite=Strict y un año", True,
      "'paynani_web_nav=' + (collapsed ? 'collapsed' : 'open')" in js and "SameSite=Strict" in js
      and "Max-Age=31536000" in js)
check("nav.js: Secure cuando la página llegó por https", True, "location.protocol === 'https:' ? '; Secure'" in js)
check("nav.js: Esc y el velo cierran el menú del celular (FR-15)", True, "'Escape'" in js and "backdrop.addEventListener" in js)
check("nav.js: Espacio abre ☰, que es un enlace con role=button (FR-7)", True, "ev.key === ' '" in js)
check("nav.js: al cambiar de ancho no queda el velo abierto (FR-17)", True, "phone.addEventListener('change'" in js)
check("nav.js: con el menú encima en el celular, el resto de la página es inert", True, "page.inert = on" in js)
check("nav.js: mover el foco no desplaza la página (Chromium, revisión de #539)", (2, 0),
      (js.count(".focus({ preventScroll: true })"), len(re.findall(r"\.focus\(\)", js))))
check("nav.js: le pone a ☰ role, aria-controls y el estado", True,
      "expand.setAttribute('role', 'button')" in js and "expand.setAttribute('aria-controls', 'menu-lateral')" in js
      and "expand.setAttribute('aria-expanded', open)" in js)

css = (ROOT / "scripts" / "paynani_lib" / "assets" / "web.css").read_text(encoding="utf-8")
check("web.css: el menú, la barra y el encabezado son sticky (FR-1, FR-2)", 3,
      len(re.findall(r"position: sticky; top: (?:0|64px)", css)))
check("web.css: scroll-padding-top para los #m-<id> del hilo (FR-3)", True,
      "scroll-padding-top: 145px" in css and "scroll-padding-top: 128px" in css)
check("web.css: sin animación con prefers-reduced-motion (FR-8)", True, "prefers-reduced-motion: reduce" in css)
check("web.css: el celular usa :target sin JavaScript (FR-16)", True, ".lateral:target + .velo" in css)
check("web.css: el escritorio es el complemento exacto del celular, sin hueco entre 900 y 901 px", True,
      "@media not all and (max-width: 900px)" in css and "min-width: 901px" not in css)

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
