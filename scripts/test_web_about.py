#!/usr/bin/env python3
"""
Tests de «Acerca de» en PaynaniWeb (#636), como el About de PaynaniApp: la entrada del
menú debajo de «API Tokens», la versión con su commit (Q275=A), los enlaces externos en
otra pestaña con `noopener noreferrer`, «Reportar un problema» con la versión en el
issue (Q276=A), sin estado de la instalación (Q277=A), los cinco idiomas, el script del
botón «Copiar» y que la página pide sesión.

#686: «Development team» en Créditos abre /about/team, la tabla de humanos y agentes con
su avatar copiado en assets/team/ (Iris[Q33] = A: la página no le pide nada a GitHub),
cada avatar y nombre con el enlace a su perfil, y Daniel y Ares (Iris[Q35]).

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
check("#686: «Development team» en Créditos, sin otra pestaña, a /about/team", True,
      bool(re.search(r'<a class="about-row" href="/about/team"><span class="about-ico">.*?<b>Development team</b>', page)))
check("Q277: sin estado de la instalación (eso está en el Dashboard)", (False, False),
      ("svc." in page, "Services" in page))
check("sin atributos style", [], re.findall(r'\sstyle="', page))
status, hdrs, js = req("GET", "/assets/about.js")
check("/assets/about.js se sirve como JavaScript", (200, True, True),
      (status, hdrs.get("content-type", "").startswith("application/javascript"), "about-copiar" in js))

# ---- #686: Development team ----------------------------------------------------------
import json  # noqa: E402

TEAM = json.loads(about_pages.TEAM_FILE.read_text(encoding="utf-8"))["members"]
check("team.json: cada miembro con login, nombre, tipo decidido, proyectos conocidos y avatar", [],
      [m.get("login") for m in TEAM if not (m.get("login") and m.get("name") and m.get("type") in ("human", "agent")
       and set(m.get("projects") or []) <= set(about_pages.PROJECTS) and about_pages.avatar_path(m.get("avatar", "")))])
check("team.json: sin la cuenta de la organización y sin logins repetidos", (False, len(TEAM)),
      ("iaaorgmx" in {m["login"] for m in TEAM}, len({m["login"].lower() for m in TEAM})))
check("Iris[Q32] y [Q35], y Julian después: los humanos son Julian, Esteban, Daniel y David",
      ["EstebanRodriguezG", "despana76", "dlibradosmbmx", "julianflores"], sorted(m["login"] for m in TEAM if m["type"] == "human"))
status, hdrs, page = req("GET", "/about/team")
check("sin sesión, /about/team va a la entrada", (303, True), (status, hdrs.get("location", "").startswith("/login")))
status, hdrs, page = req("GET", "/about/team?lang=es-MX", cookie=cookie)
check("/about/team: 200, título, «Acerca de» activo y el regreso a /about", (200, True, True, True),
      (status, "<h1>Development team</h1>" in page, 'href="/about" class="activo" aria-current="page"' in page,
       '<a href="/about">← Volver a Acerca de</a>' in page))
rows = re.findall(r"<tr><td class=\"team-avatar\">.*?</tr>", page, re.S)
check("una fila por miembro", len(TEAM), len(rows))
names = [re.search(r'<td class="team-name"><a [^>]*>([^<]+)</a>', r).group(1) for r in rows]
kinds = [re.search(r'class="team-tipo team-(human|agent)"', r).group(1) for r in rows]
check("todos en orden alfabético por nombre, humanos y agentes juntos (Julian)", sorted(names, key=str.casefold),
      names)
check("y la tabla trae humanos y agentes", {"human", "agent"}, set(kinds))
check("cada avatar y cada nombre llevan a su perfil de GitHub, en otra pestaña", True, all(
    len(re.findall(r'<a href="https://github\.com/[A-Za-z0-9-]+" target="_blank" rel="noopener noreferrer"', r)) == 2
    for r in rows))
check("Iris[Q33]: los avatares son de /assets/team/, ninguno de GitHub", (len(TEAM), False),
      (len(re.findall(r'<img src="/assets/team/[a-z0-9-]+\.(?:png|jpg)"', page)), "githubusercontent" in page))
daniel = next(r for r in rows if "@dlibradosmbmx" in r)
check("Iris[Q35]: Daniel Librado, humano, en paynani", (True, True),
      ("team-human" in daniel, '<span class="team-chip">paynani</span>' in daniel))
ares = next(r for r in rows if "@aresclaudetob" in r)
check("Iris[Q35]: Ares Claude-Tob, agente, en paynani", (True, True),
      ("team-agent" in ares, '<span class="team-chip">paynani</span>' in ares))
check("sin la etiqueta «Tester» (Julian)", (False, False), ("Tester" in page, "team-rol" in page))
metis = next(r for r in rows if "@metisclaudetob" in r)
julian = next(r for r in rows if "@julianflores" in r)
check("Julian: su fila trae paynani, PaynaniWeb y PaynaniApp", 3, julian.count('class="team-chip"'))
check("debajo de «Agente de IA», el harness; un humano no lleva", (True, False),
      ('<small class="team-harness">Claude Code</small>' in metis, "team-harness" in julian))
check("cada harness de team.json sale en su fila", sorted(m["harness"] for m in TEAM if m.get("harness")),
      sorted(re.findall(r'<small class="team-harness">([^<]+)</small>', page)))
check("sin atributos style en /about/team", [], re.findall(r'\sstyle="', page))
first = next(m for m in TEAM)
status, hdrs, data = req("GET", f"/assets/team/{first['avatar']}")
check("un avatar se sirve sin sesión, con su tipo y ETag", (200, True, True),
      (status, hdrs.get("content-type") in ("image/png", "image/jpeg"), bool(hdrs.get("etag"))))
for bad in ("/assets/team/../team.json", "/assets/team/nadie.png", "/assets/team/x.svg"):
    status, _, _ = req("GET", bad)
    check(f"{bad}: no se sirve", True, status in (303, 404))
check("avatar_path no acepta nombres raros", [None, None, None],
      [about_pages.avatar_path(n) for n in ("../x.png", "A.png", "x.gif")])
saved = about_pages.TEAM_FILE
about_pages.TEAM_FILE = Path(tempfile.mkdtemp()) / "no-hay.json"
check("sin team.json, la página dice que no hay nadie todavía", True,
      "Todavía no hay nadie en la lista." in about_pages.team_body())
about_pages.TEAM_FILE = saved

i18n.set_current("es-MX")
check("sin commit, sólo el número de versión", "Versión 0.18.0", about_pages.version_text("0.18.0", ""))
check("sin commit, el issue tampoco lo trae", True, about_pages.report_url("0.18.0", "").endswith(
      "PaynaniWeb%200.18.0"))
for lang in about_strings.STRINGS:
    for path in ("/about", "/about/team"):
        status, _, page = req("GET", f"{path}?lang={lang}", cookie=cookie)
        check(f"{lang} {path}: sin claves sin traducir", (200, []), (status, re.findall(r"web\.about\.[a-z_]+", page)))

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
