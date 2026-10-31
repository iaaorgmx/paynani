#!/usr/bin/env python3
"""
Tests de «Acerca de» en PaynaniWeb (#636), como el About de PaynaniApp: la entrada del
menú debajo de «API Tokens», la versión con su commit (Q275=A), los enlaces externos en
otra pestaña con `noopener noreferrer`, «Reportar un problema» con la versión en el
issue (Q276=A), sin estado de la instalación (Q277=A), los cinco idiomas, el script del
botón «Copiar» y que la página pide sesión.

Un PaynaniWeb real en un puerto libre; la versión la pasa la prueba.
"""
from __future__ import annotations

import http.client
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import unquote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import about_pages, about_strings, app, auth, notify, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


PASSWORD = "una-contraseña-larga"
tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
user_file = tmp / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda l: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", state_dir=tmp / "state",
                  roster_path=tmp / "roster.md", version=("0.18.0", "9d1935d"))
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


status, hdrs, _ = req("GET", "/about")
check("sin sesión, /about va a la entrada", (303, True), (status, hdrs.get("location", "").startswith("/login")))
_, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]

status, _, page = req("GET", "/?lang=en-US", cookie=cookie)
nav = page.split('<aside class="lateral"', 1)[1].split("</aside>", 1)[0]
check("el menú tiene «About» justo debajo de «API Tokens»", True,
      bool(re.search(r'href="/api-tokens"[^>]*>.*?</a>\s*<a href="/about"[^>]*>.*?<span>About</span></a>', nav, re.S)))

status, hdrs, page = req("GET", "/about?lang=en-US", cookie=cookie)
check("/about: 200, título «About» y la entrada activa", (200, True, True),
      (status, "<h1>About</h1>" in page, 'href="/about" class="activo" aria-current="page"' in page))
check("Q275: la versión con su commit", True, 'id="about-version">Version 0.18.0 · 9d1935d</span>' in page)
check("el botón «Copiar» viene oculto; lo muestra about.js", True,
      '<button type="button" class="about-copiar" data-copied="Version copied" hidden>Copy</button>' in page)
check("el script se carga con defer", True, '<script src="/assets/about.js" defer></script>' in page)
check("el párrafo de código abierto de la app", True, "Paynani is open source software. PaynaniWeb is part of paynani" in page)
links = re.findall(r'<a class="about-row" href="([^"]+)" target="_blank" rel="noopener noreferrer">', page)
check("seis enlaces externos, todos en otra pestaña con noopener noreferrer", 6, len(links))
check("sitio, código, licencia, CHANGELOG y la guía", True, all(any(link.startswith(x) for link in links) for x in (
    "https://iaa.org.mx", "https://github.com/iaaorgmx/paynani", "https://github.com/iaaorgmx/paynani/blob/main/LICENSE",
    "https://github.com/iaaorgmx/paynani/blob/main/CHANGELOG.md",
    "https://github.com/iaaorgmx/paynani/blob/main/PAYNANI_WEB.md")))
report = next((link for link in links if "/issues/new?body=" in link), "")
check("Q276: «Report a problem» abre un issue nuevo con la versión y el commit", True,
      unquote(report.split("body=", 1)[1]).endswith("---\nPaynaniWeb 0.18.0 (9d1935d)") if report else False)
check("Créditos sin enlace: biblioteca estándar, Spectral e íconos", 3, page.count('<div class="about-row">'))
check("Q277: sin estado de la instalación (eso está en el Dashboard)", (False, False),
      ("svc." in page, "Services" in page))
check("sin atributos style", [], re.findall(r'\sstyle="', page))
status, hdrs, js = req("GET", "/assets/about.js")
check("/assets/about.js se sirve como JavaScript", (200, True, True),
      (status, hdrs.get("content-type", "").startswith("application/javascript"), "about-copiar" in js))

i18n.set_current("es-MX")
check("sin commit, sólo el número de versión", "Versión 0.18.0", about_pages.version_text("0.18.0", ""))
check("sin commit, el issue tampoco lo trae", True, about_pages.report_url("0.18.0", "").endswith(
      "PaynaniWeb%200.18.0"))
for lang in about_strings.STRINGS:
    status, _, page = req("GET", f"/about?lang={lang}", cookie=cookie)
    check(f"{lang}: sin claves sin traducir", (200, []), (status, re.findall(r"web\.about\.[a-z_]+", page)))

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
