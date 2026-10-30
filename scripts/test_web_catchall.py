#!/usr/bin/env python3
"""
Tests de la pantalla «Catch-All» de PaynaniWeb (PRD #535 FR-1 a FR-8): el enlace en
«Mensajes», la página con la advertencia de los códigos, la contraseña para activarlo
o cambiar las instrucciones con él activo (y no para apagarlo), el bloqueo de
intentos, el conflict, activo sin instrucciones, el nombre reservado, CSRF y los
cinco idiomas. Un PaynaniWeb real en un puerto libre; nada sale de la máquina.
"""
from __future__ import annotations

import http.client
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
from paynani_lib import rules as rules_mod  # noqa: E402
from paynani_lib.web import app, auth, notify, users, whatsapp_source  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """| Name | Email | Type | GitHub | Phone | Rules |
|---|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | +525511112222 |  |
| Ana | ana@example.com | Human |  | +525511113333 |  |
"""
PASSWORD = "una-contraseña-larga"
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
clone.mkdir()
roster = clone / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
state = clone / "state"
state.mkdir()
catch_file = clone / "rules" / "catch-all-sms.md"
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
mail = []
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "no-accounts.json",
                  state_dir=state, roster_path=roster, roster_notifier=lambda to, s, b: mail.append((to, s, b)),
                  whatsapp_source=whatsapp_source.Demo(state="unlinked"), whatsapp_root=clone)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"
IP = ["203.0.113.5"]


def req(method, path, *, form=None, cookie="", origin=True):
    h = {"Host": HOST, "X-Forwarded-For": IP[0]}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        if origin:
            h["Origin"] = f"https://{HOST}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


def form_of(page):
    return (re.search(r'name="csrf" value="([^"]+)"', page).group(1),
            re.search(r'name="etag" value="([^"]*)"', page).group(1))


_, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
th = i18n.th

status, _, page = req("GET", "/messages?lang=es-MX", cookie=cookie)
check("FR-1: «Mensajes» enlaza a /messages/catch-all junto a las bajas", (True, True),
      ('href="/messages/catch-all"' in page, 'href="/messages/bajas"' in page))
status, _, page = req("GET", "/messages/catch-all?lang=es-MX", cookie=cookie)
check("la página abre", 200, status)
check("FR-3: explica qué hace y advierte de los códigos de verificación", (True, True),
      (th("web.catchall.lead") in page, th("web.catchall.codes") in page))
check("FR-2: casilla, instrucciones, contraseña y Guardar", True,
      'name="enabled"' in page and 'name="text"' in page and 'name="password"' in page
      and th("web.catchall.save") in page)
check("sin archivo: nunca se ha configurado", True, th("web.catchall.never") in page)
check("sin atributos style (la CSP los bloquea)", [], re.findall(r'\sstyle="', page))
csrf, etag = form_of(page)

# FR-5: activo sin instrucciones.
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "   ", "password": PASSWORD},
                      cookie=cookie)
check("FR-5: activo sin instrucciones no se guarda y dice por qué", (400, True, False),
      (status, th("web.catchall.err.empty") in page, catch_file.exists()))

# FR-4: activarlo pide la contraseña.
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "Avísame por Telegram."},
                      cookie=cookie)
check("FR-4: activarlo sin contraseña no se guarda", (403, True, False),
      (status, th("web.catchall.err.password") in page, catch_file.exists()))
check("y lo que escribió sigue en el cuadro", True, "Avísame por Telegram." in page)
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "Avísame por Telegram.",
                            "password": "mala"}, cookie=cookie)
check("FR-4: con la contraseña equivocada no se guarda", (403, False), (status, catch_file.exists()))
status, hdrs, _ = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "Avísame por Telegram.",
                            "password": PASSWORD}, cookie=cookie)
check("FR-4: con la contraseña se activa", (303, "/messages/catch-all?ok=on"),
      (status, hdrs.get("location")))
check("FR-9: rules/catch-all-sms.md activo, escrito desde PaynaniWeb", (True, True),
      (rules_mod.catch_all_notice("sms", clone) == {"file": "rules/catch-all-sms.md", "status": "active"},
       "updated_by: PaynaniWeb 203.0.113.5" in catch_file.read_text(encoding="utf-8")))
check("FR-0b: el dueño recibió el correo, sin las instrucciones", (True, False),
      (any("Catch-All" in s for _, s, _ in mail), any("Telegram" in b for _, _, b in mail)))
status, _, page = req("GET", "/messages/catch-all?ok=on&lang=es-MX", cookie=cookie)
check("FR-2: dice que está activo y desde dónde se cambió", (True, True, True),
      (th("web.catchall.ok_on", channel="SMS") in page, th("web.catchall.state_on") in page,
       "PaynaniWeb 203.0.113.5" in page))
csrf, etag = form_of(page)

# FR-4: cambiar las instrucciones con él activo también la pide; apagarlo no.
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "Otra cosa."}, cookie=cookie)
check("FR-4: cambiar las instrucciones con el Catch-All activo pide la contraseña", (403, True),
      (status, "Avísame" in catch_file.read_text(encoding="utf-8")))
status, _, _ = req("POST", "/messages/catch-all",
                   form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "Avísame por Telegram."}, cookie=cookie)
check("guardar activo sin cambiar nada no pide contraseña", 303, status)
status, _, page = req("GET", "/messages/catch-all", cookie=cookie)
csrf, etag = form_of(page)
status, hdrs, _ = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "text": "Avísame por Telegram."}, cookie=cookie)
check("FR-4: apagarlo no pide la contraseña", (303, "/messages/catch-all?ok=off", None),
      (status, hdrs.get("location"), rules_mod.catch_all_notice("sms", clone)))

# Conflict: alguien más lo cambió con el etag que tenía esta página.
status, hdrs, _ = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "Viejo", "password": PASSWORD},
                      cookie=cookie)
check("conflict: con el etag viejo no se guarda y lo dice", (409, False),
      (status, "Viejo" in catch_file.read_text(encoding="utf-8")))

# FR-6: más de 32 KB.
status, _, page = req("GET", "/messages/catch-all", cookie=cookie)
csrf, etag = form_of(page)
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "text": "x" * (rules_mod.MAX_BYTES + 10)}, cookie=cookie)
check("FR-6: más de 32 KB no se guarda y dice por qué", (400, True), (status, th("web.catchall.err.too_large") in page))

# FR-10: un contacto con el nombre reservado.
roster.write_text(ROSTER.replace("| +525511113333 |  |", "| +525511113333 | catch-all |"), encoding="utf-8")
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "text": "Apagado"}, cookie=cookie)
check("FR-10: con un contacto que usa catch-all, dice que hay que renombrarlo", (400, True),
      (status, th("web.catchall.err.reserved") in page))
roster.write_text(ROSTER, encoding="utf-8")

# La contraseña se recorta a users.MAX_PASSWORD antes de scrypt, como en las demás rutas.
status, _, page = req("GET", "/messages/catch-all", cookie=cookie)
csrf, etag = form_of(page)
seen = []
real_verify = users.verify_password
users.verify_password = lambda password, stored: seen.append(len(password)) or real_verify(password, stored)
status, _, _ = req("POST", "/messages/catch-all",
                   form={"csrf": csrf, "etag": etag, "enabled": "1", "text": "Hola", "password": "x" * 60000},
                   cookie=cookie)
users.verify_password = real_verify
check("una contraseña enorme llega recortada a scrypt", (403, [users.MAX_PASSWORD]), (status, seen))

# FR-6: casi 32 KB de Unicode y saltos de línea caben, aunque urlencoded pesen mucho más.
line = "é" * 40 + "\r\n"
near = line * ((rules_mod.MAX_BYTES - 512) // len(line.replace("\r\n", "\n").encode("utf-8")))
body_bytes = len(urlencode({"text": near}))
status, hdrs, _ = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "etag": etag, "enabled": "1", "text": near, "password": PASSWORD},
                      cookie=cookie)
check("FR-6: casi 32 KB de «é» y saltos de línea se guardan por la web", (True, 303, True),
      (body_bytes > app.MAX_BODY_BYTES, status, near.replace("\r\n", "\n") in catch_file.read_text(encoding="utf-8")))

# FR-7: CSRF y Origin.
status, _, _ = req("POST", "/messages/catch-all", form={"csrf": "malo", "etag": etag, "text": ""}, cookie=cookie)
check("FR-7: sin el token CSRF, 403", 403, status)
status, _, _ = req("POST", "/messages/catch-all", form={"csrf": csrf, "etag": etag, "text": ""}, cookie=cookie,
                   origin=False)
check("FR-7: sin Origin, 403", 403, status)

# Archivo roto a mano: la página lo dice.
catch_file.write_text("---\nversion: uno\n", encoding="utf-8")
status, _, page = req("GET", "/messages/catch-all?lang=es-MX", cookie=cookie)
check("archivo roto: la página lo dice y nombra el archivo", (200, True),
      (status, th("web.catchall.err.invalid_file", file="rules/catch-all-sms.md") in page))

# FR-4: el bloqueo de intentos de la entrada vale aquí.
IP[0] = "198.51.100.77"
_, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
cookie2 = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
_, _, page = req("GET", "/messages/catch-all?lang=es-MX", cookie=cookie2)
csrf2, etag2 = form_of(page)
codes = []
for _ in range(7):
    status, _, page = req("POST", "/messages/catch-all",
                          form={"csrf": csrf2, "etag": etag2, "enabled": "1", "text": "Hola", "password": "mala"},
                          cookie=cookie2)
    codes.append(status)
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf2, "etag": etag2, "enabled": "1", "text": "Hola", "password": PASSWORD},
                      cookie=cookie2)
check("FR-4: tras varios fallos, ni la buena entra (bloqueo de la entrada)", (403, False),
      (status, "Hola" in catch_file.read_text(encoding="utf-8")))

# FR-8: cinco idiomas.
missing = [lang for lang in ("es-MX", "en-US", "es-ES", "fr-FR", "pt-BR")
           if "web.catchall.codes" not in i18n.CATALOGUES[lang]]
check("FR-8: las cadenas en los cinco idiomas", [], missing)
IP[0] = "203.0.113.5"
for lang in ("en-US", "fr-FR", "pt-BR"):
    _, _, page = req("GET", f"/messages/catch-all?lang={lang}", cookie=cookie)
    check(f"{lang}: la advertencia de los códigos", True,
          i18n.CATALOGUES[lang]["web.catchall.codes"].replace("’", "&#x27;").split(" ")[0] in page)


# --- PRD #576 FR-9, FR-10 y #588: una página por canal -------------------------------------
catch_file.write_text("---\nversion: 1\nenabled: false\n---\nApagado.\n", encoding="utf-8")
status, _, page = req("GET", "/messages/catch-all?lang=es-MX", cookie=cookie)
check("#588: /messages/catch-all muestra solo SMS, sin WhatsApp ni Telegram", (True, False, False, 1),
      ('id="catchall-sms"' in page, 'id="catchall-whatsapp"' in page, 'id="catchall-telegram"' in page,
       page.count('name="channel"')))
check("FR-10: dice qué abre y dónde está el de WhatsApp", (True, True, False),
      (th("web.catchall.opens.sms") in page, th("web.catchall.elsewhere.sms") in page,
       th("web.catchall.opens.whatsapp") in page))
check("el texto ya no dice que un cambio aplica a los dos canales", False,
      "cambia los dos canales" in page)
csrf, sms_etag = form_of(page)

# Sin WhatsApp configurado no hay página ni liga.
status, _, _ = req("GET", "/whatsapp/catch-all", cookie=cookie)
check("#588: sin WhatsApp configurado, GET /whatsapp/catch-all es 404", 404, status)
status, _, _ = req("POST", "/whatsapp/catch-all",
                   form={"csrf": csrf, "channel": "whatsapp", "etag": "", "enabled": "1", "text": "Guarda.",
                         "password": PASSWORD}, cookie=cookie)
check("#588: sin WhatsApp configurado, POST /whatsapp/catch-all es 404 y no guarda", (404, False),
      (status, rules_mod.catch_all_active("whatsapp", clone)))
(clone / "whatsapp.env").write_text("WHATSAPP_ENABLED=1\n", encoding="utf-8")

status, _, page = req("GET", "/whatsapp/messages?lang=es-MX", cookie=cookie)
check("#588: «Mensajes de WhatsApp» tiene la liga al Catch-All junto a la de la cuenta", (200, True, True),
      (status, 'href="/whatsapp/catch-all"' in page, 'href="/whatsapp"' in page))
status, _, page = req("GET", "/whatsapp/catch-all?lang=es-MX", cookie=cookie)
check("#588: /whatsapp/catch-all muestra solo WhatsApp y vuelve a «Mensajes de WhatsApp»",
      (200, True, False, 1, True, True),
      (status, 'id="catchall-whatsapp"' in page, 'id="catchall-sms"' in page, page.count('name="channel"'),
       'href="/whatsapp/messages"' in page, th("web.catchall.elsewhere.whatsapp") in page))
check("#588: el formulario de WhatsApp se manda a su propia página", True,
      'action="/whatsapp/catch-all"' in page)
wa_csrf, wa_etag = form_of(page)
status, _, page = req("POST", "/whatsapp/catch-all",
                      form={"csrf": wa_csrf, "channel": "whatsapp", "etag": wa_etag, "enabled": "1", "text": "Guarda."},
                      cookie=cookie)
check("FR-9: WhatsApp también pide la contraseña", (403, True),
      (status, 'id="catchall-whatsapp"' in page and 'role="alert"' in page))
status, hdrs, _ = req("POST", "/whatsapp/catch-all",
                      form={"csrf": wa_csrf, "channel": "whatsapp", "etag": wa_etag, "enabled": "1",
                            "text": "Guarda.", "password": PASSWORD}, cookie=cookie)
check("FR-9: activar WhatsApp no toca SMS y vuelve a su página", (303, "/whatsapp/catch-all?ok=on", True, None),
      (status, hdrs.get("location"), rules_mod.catch_all_active("whatsapp", clone),
       rules_mod.catch_all_notice("sms", clone)))
status, _, page = req("GET", "/whatsapp/catch-all?ok=on&lang=es-MX", cookie=cookie)
check("el aviso de guardado nombra WhatsApp", True, th("web.catchall.ok_on", channel="WhatsApp") in page)

# Una página vieja (de antes de #588) que manda channel=whatsapp a /messages/catch-all no guarda nada.
before = catch_file.read_text(encoding="utf-8")
status, _, page = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "channel": "whatsapp", "etag": wa_etag, "text": ""}, cookie=cookie)
check("#588: channel de otra página no guarda nada", (400, True, before, True),
      (status, th("web.catchall.err.wrong_page") in page, catch_file.read_text(encoding="utf-8"),
       rules_mod.catch_all_active("whatsapp", clone)))
status, _, page = req("GET", "/messages/catch-all?lang=es-MX", cookie=cookie)
sms_etag = form_of(page)[1]
status, hdrs, _ = req("POST", "/messages/catch-all",
                      form={"csrf": csrf, "channel": "sms", "etag": sms_etag, "text": "Apagado."}, cookie=cookie)
check("apagar SMS deja WhatsApp activo y vuelve a /messages/catch-all",
      (303, "/messages/catch-all?ok=off", True),
      (status, hdrs.get("location"), rules_mod.catch_all_active("whatsapp", clone)))
status, _, page = req("GET", "/messages/catch-all?lang=es-MX", cookie=cookie)
sms_etag = form_of(page)[1]
status, _, _ = req("POST", "/messages/catch-all",
                   form={"csrf": csrf, "etag": sms_etag, "text": "Apagado."}, cookie=cookie)
check("sin `channel` en el formulario, la ruta decide (SMS)", (303, True),
      (status, rules_mod.catch_all_active("whatsapp", clone)))
for lang in ("en-US", "es-ES", "fr-FR", "pt-BR"):
    check(f"{lang}: textos de #588", True,
          all(k in i18n.CATALOGUES[lang] for k in ("web.catchall.elsewhere.sms", "web.catchall.elsewhere.whatsapp",
                                                  "web.catchall.err.wrong_page")))

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
