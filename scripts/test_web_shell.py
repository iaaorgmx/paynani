#!/usr/bin/env python3
"""
Tests for PaynaniWeb's frame (PRD #434 FR-10, FR-12; T4 of #435).
An assertion script, like the rest of this suite.

El menú lateral de PDSL-201 con el desplegable de cuentas (la del agente y las de
accounts.json), Messages, Roster y Log out; el menú del avatar; el menú del celular;
que no aparezca lo que la v1 deja fuera; que nada lleve `style=` (la CSP lo
bloquea); y que no quede ninguna clave sin traducir en los cinco idiomas.
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
links = re.findall(r'href="(/email/[^"]+)"', page)
check("una entrada por cuenta: la del agente primero, luego accounts.json en orden (dos veces: lateral y celular)",
      ["/email/main", "/email/ventas", "/email/soporte"] * 2, links)
check("la cuenta apagada va marcada", True, 'class="sub apagada"' in page and "apagada</span>" in page)
check("Mensajes y Roster", True, 'href="/messages"' in page and 'href="/roster"' in page)
check("cerrar sesión: formularios POST con el token de la sesión", True,
      len(re.findall(r'<form method="post" action="/logout"[^>]*>\s*<input type="hidden" name="csrf" value="[^"]+">', page)) >= 2)
check("el menú del avatar con iniciales, correo y Perfil", True,
      '<span class="iniciales">JB</span>' in page and 'href="/profile"' in page and "john@example.com" in page)
check("el menú del celular (FR-12)", True, '<details class="menu-movil">' in page)
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
check("con la cuenta del agente y el aviso", (["/email/main"] * 2, True),
      (re.findall(r'href="(/email/[^"]+)"', page), "No se pudo leer accounts.json" in page))
accounts_file.unlink()
agent["email"] = ""
status, _, page = get("/")
check("sin cuentas: lo dice en el desplegable", True, "Sin cuentas configuradas" in page)

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
