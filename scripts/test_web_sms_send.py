#!/usr/bin/env python3
"""
Tests for sending SMS from PaynaniWeb (T3 #506 of PRD #489: FR-1 to FR-4b, FR-6,
FR-8 to FR-10). An assertion script, like the rest of this suite.

Un PaynaniWeb real en un puerto libre, con el estado de la pasarela en una carpeta
temporal. El envío sólo deja la orden en outbox/ (la pasarela la manda después):
nada sale de la máquina.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.sms import store as sms_store  # noqa: E402
from paynani_lib.web import app, auth, notify, strings, users  # noqa: E402,F401

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ANA = "+525511112222"       # en el roster
CLIENTE = "+525588887777"   # fuera del roster
ROSTER = f"""# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human |  | {ANA} |
"""
os.environ.pop("PAYNANI_WEB_AGENT_PAUSE_MIN", None)
os.environ["PAYNANI_WEB_SMS_PER_HOUR"] = "3"
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
roster = tmp / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
st = sms_store.Store(state)
PASSWORD = "una-contraseña-larga"
user_file = tmp / "web" / "user.json"
users.create("dueno@example.com", "Dueño", PASSWORD, user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "no-accounts.json",
                  state_dir=state, roster_path=roster)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, cookie="", origin=True):
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.5"}
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


_, hdrs, _ = req("POST", "/login", form={"email": "dueno@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
_, _, page = req("GET", "/messages/nuevo", cookie=cookie)


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    return m.group(1) if m else ""


def send(**form):
    _, _, page = req("GET", "/messages", cookie=cookie)
    token = csrf_of(page) or CSRF
    return req("POST", "/messages/enviar", form={"csrf": token, **form}, cookie=cookie)


def outbox() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((st.root / "outbox").glob("w_*.json"))]


th = i18n.th

# --- FR-6: sin teléfono, y con una app vieja ---------------------------------------
status, _, page = req("GET", "/messages", cookie=cookie)
check("sin teléfono: «Nuevo SMS» deshabilitado con «No hay teléfono emparejado»", True,
      'aria-disabled="true"' in page and th("web.sms.no_phone") in page)
status, _, page = req("GET", "/messages/nuevo", cookie=cookie)
check("sin teléfono: Nuevo SMS no trae formulario", (200, False), (status, 'action="/messages/enviar"' in page))
st.save_device({"device_id": "d_1", "sims": [{"slot": 0, "country": "MX"}]})
status, _, page = req("GET", "/messages/nuevo", cookie=cookie)
check("app vieja: «Actualiza PaynaniApp para enviar desde aquí»", (True, False),
      (th("web.sms.old_app") in page, 'action="/messages/enviar"' in page))
# Un envío forzado con la app vieja no crea nada.
CSRF = ""
_, _, listing = req("GET", "/messages", cookie=cookie)
m = re.search(r'name="csrf" value="([^"]+)"', listing)
st.touch(accepts_owner_out=True)
_, _, page = req("GET", "/messages/nuevo", cookie=cookie)
CSRF = csrf_of(page)
st.touch(accepts_owner_out=False)
status, _, page = req("POST", "/messages/enviar", form={"csrf": CSRF, "n": ANA, "text": "hola"}, cookie=cookie)
check("app vieja: POST forzado responde 409 y no deja orden", (409, []), (status, outbox()))

# --- FR-2: Nuevo SMS ----------------------------------------------------------------
st.touch(accepts_owner_out=True)
status, _, page = req("GET", "/messages", cookie=cookie)
check("con la app nueva: botón «Nuevo SMS» a /messages/nuevo", True, 'href="/messages/nuevo"' in page)
status, _, page = req("GET", "/messages/nuevo", cookie=cookie)
check("Nuevo SMS: formulario con número, texto y CSRF", (200, True, True),
      (status, 'name="n"' in page and 'name="text"' in page, bool(csrf_of(page))))
check("Nuevo SMS: los contactos del roster con teléfono para elegir", True,
      f'<option value="{ANA}">Ana López</option>' in page)
check("FR-4b: la casilla de pausa sin marcar, con 30 minutos por omisión", True,
      th("web.sms.pause", min=30) in page and 'name="pause" value="1">' in page)
check("FR-4: maxlength 1000 y el contador con su script", True,
      'maxlength="1000"' in page and "data-sms-counter" in page and "/assets/sms.js" in page)
status, _, js = req("GET", "/assets/sms.js")
check("el script del contador se sirve", (200, True), (status, "data-sms-counter" in js))

# Un número del roster, escrito a la mexicana, sin contraseña.
status, hdrs, _ = send(n="55 1111 2222", text="Hola Ana, ¿confirmas mañana?")
check("roster: 303 a la conversación con el número en E.164", (303, f"/messages/ver?n={quote(ANA, safe='')}&ok=queued#responder"),
      (status, hdrs.get("location")))
orders = outbox()
check("roster: una orden w_ en outbox con origin owner", (1, "owner", ANA),
      (len(orders), orders[0].get("origin"), orders[0]["to"]))
check("sin la casilla: agent_pause_min 0", 0, orders[0].get("agent_pause_min"))
queued = [json.loads(l) for l in (st.root / "orders.jsonl").read_text().splitlines()]
check("orders.jsonl lleva la dirección de la web (FR-16)", "203.0.113.5", queued[-1].get("source"))
status, _, page = req("GET", f"/messages/ver?n={quote(ANA, safe='')}&ok=queued", cookie=cookie)
check("la conversación dice que quedó en cola y muestra el SMS del dueño vía web", True,
      th("web.sms.queued_ok") in page and th("web.sms.by_owner_web") in page and "Hola Ana" in page)

# --- FR-3: fuera del roster pide la contraseña ----------------------------------------
status, _, page = send(n=CLIENTE, text="Su pedido está listo")
check("fuera del roster sin contraseña: 403 y no envía", (403, 1), (status, len(outbox())))
check("el formulario vuelve con el número y el texto, sin la contraseña", True,
      CLIENTE in page and "Su pedido está listo" in page and PASSWORD not in page)
status, hdrs, _ = send(n=CLIENTE, text="Su pedido está listo", current=PASSWORD, pause="1")
check("fuera del roster con la contraseña: sale", (303, 2), (status, len(outbox())))
new = [o for o in outbox() if o["to"] == CLIENTE][0]
check("con la casilla: agent_pause_min 30", 30, new.get("agent_pause_min"))

# --- FR-1: el cuadro para responder -----------------------------------------------------
status, _, page = req("GET", f"/messages/ver?n={quote(ANA, safe='')}", cookie=cookie)
check("FR-1: la conversación trae el cuadro para responder con «Enviar»", True,
      'id="responder"' in page and th("web.sms.send") in page and f'name="n" value="{ANA}"' in page)
check("del roster: el cuadro no pide contraseña", False, 'name="current"' in page)
status, _, page = req("GET", f"/messages/ver?n={quote(CLIENTE, safe='')}", cookie=cookie)
check("fuera del roster: el cuadro pide la contraseña", True, 'name="current"' in page and "required" in page)

# --- FR-4: texto vacío y largo; número inválido ---------------------------------------
status, _, page = send(n=ANA, text="   ", desde_hilo="1")
check("texto vacío: 400 con su razón, en la conversación", (400, True, True),
      (status, th("web.sms.err.empty_text") in page, 'id="responder"' in page))
status, _, page = send(n=ANA, text="x" * 1001, desde_hilo="1")
check("más de 1000: 400 con su razón", (400, True), (status, th("web.sms.err.text_too_long", n=1000) in page))
status, _, page = send(n="hola", text="x")
check("número inválido: 400 con su razón", (400, True), (status, th("web.sms.err.invalid_number") in page))
check("nada de eso dejó orden", 2, len(outbox()))

# --- FR-8: el tope por hora (3 en esta prueba) -----------------------------------------
status, _, _ = send(n=ANA, text="tercero")
check("el tercero sale", (303, 3), (status, len(outbox())))
status, _, page = send(n=ANA, text="cuarto")
check("el cuarto: 429 y dice cuándo se libera", (429, True, 3),
      (status, th("web.sms.err.rate_limited", n=3, when="")[:30] in page, len(outbox())))

# --- FR-9: CSRF y Origin ---------------------------------------------------------------
status, _, _ = req("POST", "/messages/enviar", form={"csrf": "malo", "n": ANA, "text": "x"}, cookie=cookie)
check("sin el CSRF de la sesión: 403", 403, status)
status, _, _ = req("POST", "/messages/enviar", form={"csrf": CSRF, "n": ANA, "text": "x"}, cookie=cookie, origin=False)
check("sin Origin: 403", 403, status)
status, hdrs, _ = req("POST", "/messages/enviar", form={"csrf": CSRF, "n": ANA, "text": "x"})
check("sin sesión: no envía", True, status in (303, 200, 403) and len(outbox()) == 3)

# --- FR-10: las cadenas nuevas en los cinco idiomas -------------------------------------
keys = [k for k in strings.STRINGS["es-MX"] if k.startswith(("web.sms.new", "web.sms.reply", "web.sms.send",
                                                              "web.sms.pause", "web.sms.password", "web.sms.err.",
                                                              "web.sms.no_phone", "web.sms.old_app",
                                                              "web.sms.queued_ok", "web.sms.by_owner_web",
                                                              "web.sms.counter", "web.sms.to"))]
missing = [(lang, k) for lang in strings.STRINGS for k in keys if k not in strings.STRINGS[lang]]
check("FR-10: cada cadena nueva está en los cinco idiomas", [], missing)

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
