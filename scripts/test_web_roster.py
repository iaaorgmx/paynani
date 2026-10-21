#!/usr/bin/env python3
"""
Tests for PaynaniWeb's Roster (PRD #434 FR-20 and FR-9; T8 of #435).
An assertion script, like the rest of this suite.

La web usa el mismo servicio que la pantalla «Roster» de PaynaniApp
(sms/roster_api.RosterService): las mismas validaciones, el `etag`, la copia en
`state/history/`, el log de cambios y el correo al dueño, que dice que el cambio
vino de PaynaniWeb y de qué dirección. Todo en una carpeta temporal.
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

from paynani_lib.web import app, auth, notify, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | +525511112222 |
| Iris | iris@example.com | AI Agent | irisclaudetob |  |
"""
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
clone.mkdir()
roster = clone / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
(clone / "rosters").mkdir()
(clone / "rosters" / "ventas.md").write_text(ROSTER.replace("Iris | iris@example.com", "Ventas | v@example.com"),
                                             encoding="utf-8")
accounts_file = clone / "accounts.json"
accounts_file.write_text(json.dumps({"schema_version": 1, "accounts": [
    {"id": "ventas", "email": "ventas@example.com", "imap": {"host": "mail.example.com", "port": 993},
     "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD", "roster": "rosters/ventas.md", "mailboxes": ["INBOX"]}]}),
    encoding="utf-8")
state = clone / "state"
state.mkdir()
sent = []
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", "una-contraseña-larga", user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=accounts_file, state_dir=state, roster_path=roster,
                  roster_notifier=lambda to, subject, body: sent.append((to, subject, body)))
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"
IP = "203.0.113.5"


def req(method, path, *, form=None, cookie="", origin=True):
    h = {"Host": HOST, "X-Forwarded-For": IP}
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


_, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": "una-contraseña-larga"})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


def get(path):
    return req("GET", path, cookie=cookie)


def post(path, **form):
    return req("POST", path, form=form, cookie=cookie)


def hidden(page, name):
    m = re.search(rf'name="{name}" value="([^"]*)"', page)
    return m.group(1) if m else ""


def wait_notices():
    for t in list(ctx.roster_service().notify_threads):
        t.join(5)


# --- la lista -----------------------------------------------------------------------------
status, _, page = get("/roster")
check("/roster: 200, marcado en el menú", (200, True), (status, 'href="/roster" class="activo"' in page))
check("las dos cuentas para elegir: la del agente y ventas", True,
      'href="/roster?cuenta=main"' in page and 'href="/roster?cuenta=ventas"' in page)
check("los dos contactos, con sus datos", True, "Julián Flores" in page and "iris@example.com" in page and "+525511112222" in page)
check("el dueño marcado y sin «Quitar»", (True, False, True),
      ('class="marca-roster">dueño' in page, "/roster/quitar?cuenta=main&amp;fila=1" in page,
       "/roster/quitar?cuenta=main&amp;fila=2" in page))
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)

# --- agregar ----------------------------------------------------------------------------------
status, _, page = get("/roster/editar?cuenta=main")
etag = hidden(page, "etag")
check("el formulario de alta trae el etag del roster", 64, len(etag))
status, hdrs, _ = post("/roster/guardar", csrf=csrf, cuenta="main", fila="", etag=etag, name="Ana <Ruiz>",
                       email="ana@example.org", type="Human", github="", phones="55 3333 4444")
check("alta -> 303 a la lista con ok", (303, "/roster?cuenta=main&ok=saved"), (status, hdrs.get("location")))
text = roster.read_text(encoding="utf-8")
check("la fila nueva en roster.md, con el teléfono normalizado", True, "ana@example.org" in text and "+525533334444" in text)
check("con una copia anterior en state/history/", True, any((state / "history").rglob("*")))
changes = [json.loads(l) for l in (state / "roster_changes.jsonl").read_text(encoding="utf-8").splitlines()]
check("el log de cambios dice que vino de la web y de qué dirección", f"web:{IP}", changes[0]["device_id"])
wait_notices()
check("y el correo al dueño (el primer Human del roster)", "julian@example.com", sent[-1][0])
check("dice que vino de PaynaniWeb, con la dirección", True,
      "desde PaynaniWeb" in sent[-1][1] and f"PaynaniWeb (dirección {IP})" in sent[-1][2])
check("y que cambie la contraseña de la web si no fue él", True, "scripts/paynani web passwd" in sent[-1][2])
status, _, page = get("/roster?cuenta=main&ok=saved")
check("la lista dice que se guardó, con el nombre escapado", (True, True, False),
      ('class="aviso-ok"' in page, "Ana &lt;Ruiz&gt;" in page, "Ana <Ruiz>" in page))

# --- validación y conflicto ----------------------------------------------------------------------
before = roster.read_bytes()
etag = hidden(get("/roster/editar?cuenta=main")[2], "etag")
status, _, page = post("/roster/guardar", csrf=csrf, cuenta="main", fila="", etag=etag, name="Malo",
                       email="no-es-correo", type="Human", github="", phones="")
check("correo inválido: 400, el error y el formulario con lo escrito", (400, True, True),
      (status, 'class="error-caja"' in page, 'value="no-es-correo"' in page))
status, _, page = post("/roster/guardar", csrf=csrf, cuenta="main", fila="", etag=etag, name="Sin datos",
                       email="", type="Human", github="", phones="")
check("sin correo ni teléfono: 400", 400, status)
status, _, page = post("/roster/guardar", csrf=csrf, cuenta="main", fila="", etag="0" * 64, name="Tarde",
                       email="tarde@example.org", type="Human", github="", phones="")
check("con un etag viejo: 409 y dice que alguien lo cambió", (409, True), (status, "cambió este roster" in page))
check("ninguno de los tres escribió", before, roster.read_bytes())
status, _, _ = req("POST", "/roster/guardar", form={"cuenta": "main", "name": "X", "email": "x@example.org"}, cookie=cookie)
check("sin el token de la sesión: 403", 403, status)

# --- editar ----------------------------------------------------------------------------------------
status, _, page = get("/roster/editar?cuenta=main&fila=2")
check("editar trae los datos de la fila", True, 'value="Iris"' in page and 'value="iris@example.com"' in page)
status, hdrs, _ = post("/roster/guardar", csrf=csrf, cuenta="main", fila="2", etag=hidden(page, "etag"), name="Iris Claude",
                       email="iris@example.com", type="AI Agent", github="irisclaudetob", phones="")
check("editar -> 303", 303, status)
check("el nombre cambió en el archivo", True, "Iris Claude" in roster.read_text(encoding="utf-8"))
wait_notices()
check("el correo dice qué cambió", True, "edición" in sent[-1][1] and "Cambió: name" in sent[-1][2])

# --- quitar -----------------------------------------------------------------------------------------
status, _, _ = get("/roster/quitar?cuenta=main&fila=1")
check("quitar al dueño ni siquiera se ofrece: 403", 403, status)
status, _, page = get("/roster/quitar?cuenta=main&fila=1".replace("fila=1", "fila=2"))
etag = hidden(page, "etag")
status, _, page = post("/roster/quitar", csrf=csrf, cuenta="main", fila="1", etag=etag)
check("y por POST tampoco: 400 con owner_row", (400, True), (status, "dueño" in page))
status, _, page = get("/roster/quitar?cuenta=main&fila=2")
check("la confirmación nombra al contacto", True, "¿Quitar a Iris Claude?" in page)
status, hdrs, _ = post("/roster/quitar", csrf=csrf, cuenta="main", fila="2", etag=hidden(page, "etag"))
check("quitar -> 303 con ok", (303, "/roster?cuenta=main&ok=removed"), (status, hdrs.get("location")))
check("ya no está en el archivo", False, "iris@example.com" in roster.read_text(encoding="utf-8"))

# --- otra cuenta -------------------------------------------------------------------------------------
status, _, page = get("/roster?cuenta=ventas")
check("el roster de ventas", (200, True), (status, "v@example.com" in page))
status, _, page = get("/roster/editar?cuenta=ventas")
status, hdrs, _ = post("/roster/guardar", csrf=csrf, cuenta="ventas", fila="", etag=hidden(page, "etag"), name="Cliente",
                       email="cliente@example.org", type="Human", github="", phones="")
check("un alta en ventas va a rosters/ventas.md, no a roster.md", (303, True, False),
      (status, "cliente@example.org" in (clone / "rosters" / "ventas.md").read_text(encoding="utf-8"),
       "cliente@example.org" in roster.read_text(encoding="utf-8")))
status, _, _ = get("/roster?cuenta=nadie")
check("una cuenta que no existe: 404", 404, status)

# --- instrucciones de un contacto ------------------------------------------------------------------------
status, _, page = get("/roster/reglas?cuenta=main&fila=1")
check("el editor de instrucciones, con la plantilla para quien no tiene", (200, True, True),
      (status, "version: 1" in page, "todavía no tiene instrucciones propias" in page))
roster_etag = hidden(page, "roster_etag")
status, _, page = post("/roster/reglas", csrf=csrf, cuenta="main", fila="1", general="", etag="", roster_etag=roster_etag,
                       accion="vista", text="---\nversion: 2\nenabled: true\n---\n")
check("vista previa con una cabecera mala: 400 y el campo", (400, True), (status, "header.version" in page))
rules_text = "---\nversion: 1\nenabled: true\nreply:\n  email: never\n---\n\n## General\nNo contestar <nunca>.\n"
status, _, page = post("/roster/reglas", csrf=csrf, cuenta="main", fila="1", general="", etag="", roster_etag=roster_etag,
                       accion="vista", text=rules_text)
check("vista previa buena: la regla efectiva, escapada", (200, True), (status, "No contestar &lt;nunca&gt;." in page))
check("la vista previa no escribe", False, (clone / "rules").exists() and any((clone / "rules").glob("*.md")))
status, hdrs, _ = post("/roster/reglas", csrf=csrf, cuenta="main", fila="1", general="", etag="", roster_etag=roster_etag,
                       accion="guardar", text=rules_text)
check("guardar -> 303 al editor con ok", 303, status)
files = list((clone / "rules").glob("*.md"))
check("queda rules/<id>.md", 1, len(files))
saved_rules = files[0].read_text(encoding="utf-8")
check("con updated_by de PaynaniWeb y su dirección", True, f"updated_by: PaynaniWeb {IP}" in saved_rules)
check("y el id en la columna Rules del roster", True, files[0].stem in roster.read_text(encoding="utf-8"))
wait_notices()
check("el correo del cambio de reglas, sin el texto", (True, False),
      ("cambio de reglas" in sent[-1][1], "No contestar" in sent[-1][2]))
status, _, page = get("/roster?cuenta=main")
check("la lista marca que tiene instrucciones", True, "con instrucciones" in page)

# --- reglas generales ---------------------------------------------------------------------------------
status, _, page = get("/roster/reglas?general=1")
check("reglas generales: el editor", (200, True), (status, "Todavía no hay reglas generales" in page))
status, hdrs, _ = post("/roster/reglas", csrf=csrf, general="1", cuenta="", fila="", etag=hidden(page, "etag"),
                       roster_etag="", accion="guardar",
                       text="---\nversion: 1\nenabled: true\n---\n\n## General\nSaluda.\n\n## SMS\nSé breve.\n")
check("guardar las generales -> rules/default.md", (303, True), (status, (clone / "rules" / "default.md").exists()))
status, _, page = get("/roster/reglas?cuenta=main&fila=1")
check("la regla efectiva: la General del contacto sustituye a la general, y ## SMS de las generales sigue",
      (True, True, False), ("Sé breve." in page, "No contestar" in page, "Saluda." in page))

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
