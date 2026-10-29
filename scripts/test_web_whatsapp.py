#!/usr/bin/env python3
"""
Tests de WhatsApp en PaynaniWeb (PRD #550 FR-6a, FR-7, FR-16a, FR-20, FR-24; WA-5 #557):
el menú sólo con WhatsApp configurado, la pantalla /whatsapp con vincular por QR o
código, cancelar y desvincular (contraseña, CSRF, Origin, bloqueo de intentos y
no-store), el QR vigente sólo para la sesión que vinculó, y «WhatsApp messages» sin
mensaje nuevo, con lo de fuera del roster oculto y responder sólo donde se puede.

Un PaynaniWeb real en un puerto libre con la fuente de demostración
(`whatsapp_source.Demo`); nada sale de la máquina. Si `zbarimg` está instalado, el QR
de la página se decodifica con él.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.sms import qr  # noqa: E402
from paynani_lib.web import app, auth, notify, users, whatsapp_pages, whatsapp_source  # noqa: E402

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
clone = tmp / "clone"
(clone / "state").mkdir(parents=True)
(clone / "roster.md").write_text("| Name | Email |\n|---|---|\n| Julián Flores | julian@example.com |\n",
                                 encoding="utf-8")
wa_env = clone / "whatsapp.env"
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


clock = Clock()
demo = whatsapp_source.Demo(state="unlinked", clock=clock)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "no-accounts.json",
                  state_dir=clone / "state", roster_path=clone / "roster.md",
                  whatsapp_source=demo, whatsapp_root=clone)
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


def login():
    _, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
    return next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


def csrf_of(page):
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def calls(kind):
    return [c for c in demo.calls if c[0] == kind]


def svg_matrix(page):
    """La matriz del primer QR de la página, leída de vuelta del `<path>` del SVG."""
    start = page.find('class="wa-qr-imagen"')
    if start < 0:
        return None
    m = re.search(r'viewBox="0 0 (\d+) (\d+)".*?<path d="([^"]*)"', page[start:])
    if not m:
        return None
    total = int(m.group(1))
    grid = [[False] * total for _ in range(total)]
    for x, y, w in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", m.group(3)):
        for dx in range(int(w)):
            grid[int(y)][int(x) + dx] = True
    quiet = 4
    return [row[quiet:total - quiet] for row in grid[quiet:total - quiet]]


def zbar(matrix):
    """El texto del QR según zbarimg, o None si no está instalado."""
    if not shutil.which("zbarimg"):
        return None
    scale, border = 6, 4
    n = (len(matrix) + 2 * border) * scale
    rows = []
    for y in range(n):
        gy = y // scale - border
        rows.append(" ".join("1" if 0 <= gy < len(matrix) and 0 <= x // scale - border < len(matrix)
                             and matrix[gy][x // scale - border] else "0" for x in range(n)))
    pbm = tmp / "qr.pbm"
    pbm.write_text(f"P1\n{n} {n}\n" + "\n".join(rows) + "\n", encoding="ascii")
    out = subprocess.run(["zbarimg", "-q", "--raw", str(pbm)], capture_output=True, text=True)
    pbm.unlink()
    return out.stdout.rstrip("\n")


th = i18n.th
cookie = login()

# ---- FR-24: sin WhatsApp configurado no aparece nada -------------------------------
status, _, page = req("GET", "/messages?lang=es-MX", cookie=cookie)
check("sin whatsapp.env: el menú no tiene «WhatsApp messages»", (200, False),
      (status, 'href="/whatsapp/messages"' in page))
for path in ("/whatsapp", "/whatsapp/messages", "/whatsapp/link/current", "/whatsapp/messages/ver?n=%2B15550100001"):
    status, _, page = req("GET", path + ("&" if "?" in path else "?") + "lang=es-MX", cookie=cookie)
    check(f"sin whatsapp.env: {path} responde 404 y lo explica", (404, True),
          (status, th("web.wa.not_configured") in page))
csrf = csrf_of(req("GET", "/messages", cookie=cookie)[2])
status, _, _ = req("POST", "/whatsapp/link", form={"csrf": csrf, "password": PASSWORD, "mode": "qr"}, cookie=cookie)
check("sin whatsapp.env: POST /whatsapp/link responde 404 y no le pide nada al servicio", (404, []),
      (status, calls("whatsapp.link")))
for content, label in (("WHATSAPP_ENABLED=0\n", "WHATSAPP_ENABLED=0"), ("WHATSAPP_ENABLED=1\nesto no\n", "una línea rota"),
                       ("", "vacío")):
    wa_env.write_text(content, encoding="utf-8")
    status, _, page = req("GET", "/messages", cookie=cookie)
    check(f"whatsapp.env con {label}: no configurado, sin menú", False, 'href="/whatsapp/messages"' in page)
wa_env.unlink()
real = clone / "real-whatsapp.env"
real.write_text("WHATSAPP_ENABLED=1\n", encoding="utf-8")
os.symlink(real, wa_env)
status, _, page = req("GET", "/messages", cookie=cookie)
check("whatsapp.env como enlace simbólico: no configurado", False, 'href="/whatsapp/messages"' in page)
wa_env.unlink()
wa_env.write_text("# activado por la instalación\nWHATSAPP_ENABLED=1\n", encoding="utf-8")

# ---- Configurado: el menú y la pantalla ----------------------------------------------
status, _, page = req("GET", "/messages?lang=es-MX", cookie=cookie)
check("FR-24: con WhatsApp configurado, «Mensajes de WhatsApp» en el menú", (True, True),
      ('href="/whatsapp/messages"' in page, th("web.wa.nav") in page))
check("«Mensajes» sigue en /messages", True, 'href="/messages"' in page)
status, hdrs, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie)
check("FR-7: /whatsapp abre, sin vincular", (200, True), (status, th("web.wa.state.unlinked") in page))
check("FR-7: advierte del bloqueo de Meta antes de vincular", True, th("web.wa.risk") in page)
check("FR-7: vincular con QR y con código, con la contraseña", (True, True, True),
      ('value="qr"' in page, 'value="code"' in page, 'name="password"' in page))
check("FR-6a: la respuesta lleva Cache-Control: no-store", True, "no-store" in hdrs.get("cache-control", ""))
check("sin atributos style (la CSP los bloquea)", [], re.findall(r'\sstyle="', page))
csp = hdrs.get("content-security-policy", "")
check("la CSP deja que whatsapp.js pregunte a este mismo origen, y a nada más", (True, True, True),
      ("connect-src 'self'" in csp, "default-src 'none'" in csp, "script-src 'self'" in csp))
check("la página marca «WhatsApp messages» como la sección activa del menú", True,
      re.search(r'<a href="/whatsapp/messages" class="activo" aria-current="page">', page) is not None)
csrf = csrf_of(page)

# ---- FR-6a: contraseña, CSRF y Origin antes de pedirle nada al servicio ---------------
status, _, page = req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "qr"}, cookie=cookie)
check("FR-6a: vincular sin contraseña no llega al servicio", (400, True, []),
      (status, th("web.wa.err.password") in page, calls("whatsapp.link")))
status, _, page = req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "qr", "password": "mala"}, cookie=cookie)
check("FR-6a: con la contraseña equivocada tampoco", (403, []), (status, calls("whatsapp.link")))
status, _, _ = req("POST", "/whatsapp/link", form={"csrf": "malo", "mode": "qr", "password": PASSWORD}, cookie=cookie)
check("FR-6a: sin el token CSRF, 403", (403, []), (status, calls("whatsapp.link")))
status, _, _ = req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "qr", "password": PASSWORD}, cookie=cookie,
                   origin=False)
check("FR-6a: sin Origin, 403", (403, []), (status, calls("whatsapp.link")))

# ---- FR-7: vincular con QR -------------------------------------------------------------
status, hdrs, _ = req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "qr", "password": PASSWORD},
                      cookie=cookie)
check("vincular con QR redirige a /whatsapp (recargar no vuelve a mandar el formulario)", (303, "/whatsapp"),
      (status, hdrs.get("location")))
status, hdrs, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie)
first_qr = demo.link["qr"]
link_id = demo.link["id"]
check("FR-7: con la contraseña, la página del QR", (200, True, True),
      (status, th("web.wa.qr_h") in page, "<svg" in page))
check("FR-6a: la página del QR lleva no-store", True, "no-store" in hdrs.get("cache-control", ""))
check("§11: el link_id nunca llega al navegador", (False, False),
      (link_id in page, any(link_id in c for c in hdrs["set-cookie-all"])))
matrix = svg_matrix(page)
check("el SVG de la página es el QR del texto vigente (sms/qr.py)", qr.encode(first_qr), matrix)
decoded = zbar(matrix)
if decoded is None:
    print("ok   (zbarimg no está instalado: el QR no se decodifica con él)")
else:
    check(f"zbarimg lee el QR de la página ({len(first_qr)} bytes)", first_qr, decoded)
check("la página carga whatsapp.js para cambiar el QR", True, 'src="/assets/whatsapp.js"' in page)
check("y ofrece cancelar, con la contraseña", True, 'action="/whatsapp/link/cancel"' in page)

status, hdrs, body = req("GET", "/whatsapp/link/current", cookie=cookie)
data = json.loads(body)
check("GET /whatsapp/link/current: el QR vigente como HTML, con no-store", (200, "waiting", True, True),
      (status, data["state"], "<svg" in data.get("html", ""), "no-store" in hdrs.get("cache-control", "")))
check("§11: la web le pasa al servicio el link_id de esta sesión", link_id,
      calls("whatsapp.link_current")[-1][1].get("link_id"))
clock.now += 21
status, _, body = req("GET", "/whatsapp/link/current", cookie=cookie)
data = json.loads(body)
rotated = demo.link["qr"]
check("WhatsApp rota el QR: la siguiente pregunta trae el nuevo", (True, qr.encode(rotated)),
      (rotated != first_qr, svg_matrix(data["html"])))

# Otra sesión del mismo dueño no recibe el QR de esta.
IP[0] = "198.51.100.8"
cookie2 = login()
status, _, body = req("GET", "/whatsapp/link/current", cookie=cookie2)
check("FR-6a: otra sesión no recibe el QR (no tiene el link_id)", ("ended", False),
      (json.loads(body)["state"], "<svg" in body))
status, _, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie2)
check("FR-6a: en otra sesión, /whatsapp dice que hay una vinculación en curso, sin QR", (True, True, False, False),
      (th("web.wa.linking_by", by="PaynaniWeb", s=0).split(" PaynaniWeb")[0] in page,
       'action="/whatsapp/link/cancel"' in page, "wa-qr-imagen" in page, rotated in page))
IP[0] = "203.0.113.5"

# Sin sesión, nada.
status, _, _ = req("GET", "/whatsapp/link/current")
check("sin sesión, /whatsapp/link/current lleva a la entrada", 303, status)

# Termina: linked.
demo.finish_link("linked")
status, _, body = req("GET", "/whatsapp/link/current", cookie=cookie)
check("al vincular, /whatsapp/link/current dice ended (whatsapp.js recarga)", "ended", json.loads(body)["state"])
status, _, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie)
check("y la página recargada dice que quedó vinculado, una vez", (True, True),
      (th("web.wa.ended.linked") in page, th("web.wa.state.connected") in page))
status, _, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie)
check("el aviso no se repite", False, th("web.wa.ended.linked") in page)
check("conectado: se ve el número vinculado y «Desvincular»", (True, True),
      ("+15550100000" in page, 'action="/whatsapp/unlink"' in page))

# Vincular con una cuenta ya conectada (por ejemplo, desde una página vieja).
status, _, page = req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "qr", "password": PASSWORD}, cookie=cookie)
check("con una cuenta conectada, vincular dice already_linked", (409, True),
      (status, th("web.wa.err.already_linked") in page))

# ---- FR-7: desvincular -----------------------------------------------------------------
status, _, page = req("POST", "/whatsapp/unlink", form={"csrf": csrf, "password": PASSWORD}, cookie=cookie)
check("desvincular sin la casilla de confirmación no llega al servicio", (400, True, []),
      (status, th("web.wa.err.confirm") in page, calls("whatsapp.unlink")))
status, _, _ = req("POST", "/whatsapp/unlink", form={"csrf": csrf, "confirm": "1"}, cookie=cookie)
check("FR-6a: desvincular sin contraseña tampoco", (400, []), (status, calls("whatsapp.unlink")))
demo.unlink_remote = False
status, hdrs, _ = req("POST", "/whatsapp/unlink", form={"csrf": csrf, "confirm": "1", "password": PASSWORD},
                      cookie=cookie)
check("FR-9: desvincular sin respuesta de WhatsApp lo dice", (303, "/whatsapp?ok=unlinked_local"),
      (status, hdrs.get("location")))
status, _, page = req("GET", "/whatsapp?ok=unlinked_local&lang=es-MX", cookie=cookie)
check("y explica que hay que quitar el dispositivo desde WhatsApp", (True, True),
      (th("web.wa.ok_unlinked_local") in page, th("web.wa.state.unlinked") in page))
demo.unlink_remote = True

# ---- FR-6a, FR-7: vincular con código ----------------------------------------------------
status, _, page = req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "code", "number": "55 1234",
                                                      "password": PASSWORD}, cookie=cookie)
check("vincular con código y un número inválido no llega al servicio", (400, True),
      (status, th("web.wa.err.invalid_number") in page))
before = len(calls("whatsapp.link"))
status, hdrs, page = req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "code", "number": "+1 555 010 0000",
                                                         "password": PASSWORD}, cookie=cookie)
code = demo.link["code"]
check("FR-7: con código, la página lo muestra una vez, con no-store", (200, True, True),
      (status, code in page, "no-store" in hdrs.get("cache-control", "")))
check("el número se manda en E.164", {"mode": "code", "number": "+15550100000"}, calls("whatsapp.link")[before][1])
status, _, body = req("GET", "/whatsapp/link/current", cookie=cookie)
check("FR-6a: /whatsapp/link/current no repite el código", ("waiting", False),
      (json.loads(body)["state"], code in body))
status, _, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie)
check("FR-6a: al recargar, el código ya no se ve; sólo que hay una vinculación en curso", (False, True),
      (code in page, 'action="/whatsapp/link/cancel"' in page))
clock.now += 120
status, _, body = req("GET", "/whatsapp/link/current", cookie=cookie)
check("§11: el código no se cancela a los 60 s sin preguntar (vive 180 s)", "waiting", json.loads(body)["state"])

# ---- Cancelar -------------------------------------------------------------------------------
status, _, _ = req("POST", "/whatsapp/link/cancel", form={"csrf": csrf}, cookie=cookie)
check("FR-6a: cancelar sin contraseña no llega al servicio", (400, []), (status, calls("whatsapp.link_cancel")))
status, hdrs, _ = req("POST", "/whatsapp/link/cancel", form={"csrf": csrf, "password": PASSWORD}, cookie=cookie)
check("cancelar con la contraseña", (303, "/whatsapp?ok=canceled", "unlinked"),
      (status, hdrs.get("location"), demo.state))

# ---- §11: el QR se cancela si nadie pregunta en 60 s ---------------------------------------
req("POST", "/whatsapp/link", form={"csrf": csrf, "mode": "qr", "password": PASSWORD}, cookie=cookie)
clock.now += 61
status, _, body = req("GET", "/whatsapp/link/current", cookie=cookie)
check("§11: con la página cerrada 60 s, el servicio cancela el QR", "ended", json.loads(body)["state"])
status, _, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie)
check("y la página lo dice", True, th("web.wa.ended.canceled") in page)

# ---- FR-4: el bloqueo de intentos de la entrada vale aquí --------------------------------------
IP[0] = "198.51.100.77"
cookie3 = login()
csrf3 = csrf_of(req("GET", "/whatsapp", cookie=cookie3)[2])
for _ in range(7):
    req("POST", "/whatsapp/link", form={"csrf": csrf3, "mode": "qr", "password": "mala"}, cookie=cookie3)
before = len(calls("whatsapp.link"))
status, _, _ = req("POST", "/whatsapp/link", form={"csrf": csrf3, "mode": "qr", "password": PASSWORD}, cookie=cookie3)
check("tras varios fallos, ni la buena contraseña vincula (bloqueo de la entrada)", (403, before),
      (status, len(calls("whatsapp.link"))))
IP[0] = "203.0.113.5"

# ---- El servicio caído --------------------------------------------------------------------------
demo.state = "service_down"
status, _, page = req("GET", "/whatsapp?lang=es-MX", cookie=cookie)
check("servicio caído: /whatsapp dice service_down y el menú sigue", (200, True, True),
      (status, th("web.wa.state.service_down") in page, 'href="/whatsapp/messages"' in page))
status, _, page = req("GET", "/whatsapp/messages?lang=es-MX", cookie=cookie)
check("servicio caído: «WhatsApp messages» lo dice", (503, True), (status, th("web.wa.err.unavailable") in page))
demo.finish_link("linked")   # vuelve a conectado
demo.state = "connected"

# ---- FR-24: la lista, sin mensaje nuevo ------------------------------------------------------------
status, _, page = req("GET", "/whatsapp/messages?lang=es-MX", cookie=cookie)
check("FR-24: la lista de conversaciones", (200, 3), (status, page.count('href="/whatsapp/messages/ver?n=')))
check("FR-24, Q189=A: sin botón ni formulario de mensaje nuevo", (False, False),
      ("/whatsapp/messages/nuevo" in page, "<form" in page.split('<main', 1)[1].split("</main>")[0]))
main = page.split("<main", 1)[1]
check("los nombres salen del roster; la más reciente primero", True,
      main.index("Ana López") < main.index("+15550100099") < main.index("Julián Flores"))
check("FR-16a: fuera del roster sólo el número, sin el texto", (True, False, True),
      ("+15550100099" in page, "123456" in page, th("web.wa.hidden_short") in page))
check("un archivo se muestra por su tipo", True, th("web.wa.kind.image") in page or "Gracias" in page)
check("«Mensajes» (SMS) no muestra los hilos de WhatsApp", False,
      "Ana López" in req("GET", "/messages", cookie=cookie)[2])

# ---- FR-24: un hilo y responder ------------------------------------------------------------------
status, _, page = req("GET", "/whatsapp/messages/ver?n=%2B15550100001&lang=es-MX", cookie=cookie)
check("un hilo del roster, en orden de hora, con el cuadro de responder", (200, True, True),
      (status, page.index("¿tienen mesa") < page.index("A nombre de Ana"), 'action="/whatsapp/messages/enviar"' in page))
check("lo que mandó el agente lleva su estado", True, th("web.wa.by_agent") in page and th("web.wa.status.read") in page)
check("la foto se muestra por su tipo, sin ruta ni contenido", True, th("web.wa.kind.image") in page)
status, hdrs, _ = req("POST", "/whatsapp/messages/enviar", form={"csrf": csrf, "n": "+15550100001",
                                                                 "text": "Con gusto, <b>los esperamos</b>."},
                      cookie=cookie)
check("FR-24: contestar en el hilo", (303, "/whatsapp/messages/ver?n=%2B15550100001&ok=sent#responder"),
      (status, hdrs.get("location")))
check("se le pide al servicio whatsapp.send con el número y el texto, sin archivo",
      {"number": "+15550100001", "text": "Con gusto, <b>los esperamos</b>."}, calls("whatsapp.send")[-1][1])
status, _, page = req("GET", "/whatsapp/messages/ver?n=%2B15550100001&ok=sent&lang=es-MX", cookie=cookie)
check("el mensaje aparece como «Tú», escapado, con su estado", (True, True, True),
      (th("web.wa.sent_ok") in page, "Con gusto, &lt;b&gt;los esperamos&lt;/b&gt;." in page,
       th("web.wa.status.sending") in page))
status, _, page = req("POST", "/whatsapp/messages/enviar", form={"csrf": csrf, "n": "+15550100001", "text": "x" * 4001},
                      cookie=cookie)
check("más de 4,000 caracteres no llega al servicio", (400, 1), (status, len(calls("whatsapp.send"))))

# FR-20: un contacto del roster que no ha escrito.
demo.threads[1]["can_reply"] = False
status, _, page = req("GET", "/whatsapp/messages/ver?n=%2B15550100002&lang=es-MX", cookie=cookie)
check("FR-20: sin can_reply no hay cuadro de responder, y dice por qué", (False, True),
      ('action="/whatsapp/messages/enviar"' in page, th("web.wa.no_reply_started") in page))
status, _, page = req("POST", "/whatsapp/messages/enviar", form={"csrf": csrf, "n": "+15550100002", "text": "Hola"},
                      cookie=cookie)
check("FR-20: aunque se mande a mano, el servicio dice not_started", (400, True),
      (status, th("web.wa.err.not_started") in page))

# FR-16a: fuera del roster.
status, _, page = req("GET", "/whatsapp/messages/ver?n=%2B15550100099&lang=es-MX", cookie=cookie)
check("FR-16a: el hilo de fuera del roster no muestra ningún texto", (200, False, False, True),
      (status, "123456" in page, "No lo compartas" in page, th("web.wa.hidden") in page))
check("FR-19: y no tiene cuadro de responder", (False, True),
      ('action="/whatsapp/messages/enviar"' in page, th("web.wa.no_reply_roster") in page))
status, _, page = req("POST", "/whatsapp/messages/enviar", form={"csrf": csrf, "n": "+15550100099", "text": "Hola"},
                      cookie=cookie)
check("FR-19: mandarle a mano dice not_allowed", (400, True), (status, th("web.wa.err.not_allowed") in page))

# Defensa en profundidad: aunque el servicio mandara el texto de un hilo fuera del roster.
leaky = {"number": "+15550100098", "name": "<script>x</script>", "in_roster": False, "can_reply": False,
         "messages": [{"id": "wa:1", "dir": "in", "at": "2026-10-28T19:00:00Z", "kind": "text", "text": "secreto"}]}
i18n.set_current("es-MX")
html_out = whatsapp_pages.thread_body(leaky, "")
check("FR-16a: fuera del roster no se dibuja el texto ni el nombre, aunque llegaran", (False, False),
      ("secreto" in html_out, "<script>" in html_out))

# Desconectado: no se puede contestar.
demo.state = "disconnected"
status, _, page = req("GET", "/whatsapp/messages/ver?n=%2B15550100001&lang=es-MX", cookie=cookie)
check("desconectado: el cuadro de responder lo dice en lugar del formulario", (False, True),
      ('action="/whatsapp/messages/enviar"' in page, th("web.wa.no_reply_connected") in page))
status, _, page = req("POST", "/whatsapp/messages/enviar", form={"csrf": csrf, "n": "+15550100001", "text": "Hola"},
                      cookie=cookie)
check("desconectado: mandar a mano dice not_connected", (409, True), (status, th("web.wa.err.not_connected") in page))
demo.state = "connected"
status, _, page = req("GET", "/whatsapp/messages/ver?n=%2B15550109999&lang=es-MX", cookie=cookie)
check("un número sin hilo: 404", 404, status)
status, _, _ = req("POST", "/whatsapp/messages/enviar", form={"csrf": "malo", "n": "+15550100001", "text": "Hola"},
                   cookie=cookie)
check("responder sin el token CSRF, 403", 403, status)

# ---- Cinco idiomas --------------------------------------------------------------------------------
keys = [k for k in i18n.CATALOGUES["es-MX"] if k.startswith("web.wa.")]
missing = {lang: [k for k in keys if k not in i18n.CATALOGUES[lang]]
           for lang in ("en-US", "es-ES", "fr-FR", "pt-BR")}
check("las cadenas web.wa.* en los cinco idiomas", {lang: [] for lang in missing}, missing)
status, _, page = req("GET", "/whatsapp/messages?lang=en-US", cookie=cookie)
check("en-US: «WhatsApp messages» en el menú", True, ">WhatsApp messages<" in page)

httpd.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
