#!/usr/bin/env python3
"""
Tests for PaynaniWeb's Profile (PRD #434 FR-21; T9 of #435).
An assertion script, like the rest of this suite.

Como el Profile del /dash: el avatar, el nombre, «Dueño» y el último ingreso, y
sólo Personal Info y Account Password. Cambiar el correo pide la contraseña;
cambiar la contraseña pide la actual, valida la nueva y cierra las otras sesiones
sin cerrar la de quien la cambió. La contraseña actual pasa por el bloqueo de T3.
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


tmp = Path(tempfile.mkdtemp())
user_file = tmp / "web" / "user.json"
GOOD = "una-contraseña-larga"
users.create("john@example.com", "John Doe", GOOD, user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "none.json", state_dir=tmp / "state",
                  roster_path=tmp / "roster.md")
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, cookie="", ip="203.0.113.5"):
    h = {"Host": HOST, "X-Forwarded-For": ip}
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


def login(email="john@example.com", password=GOOD, ip="203.0.113.5"):
    status, hdrs, _ = req("POST", "/login", form={"email": email, "password": password}, ip=ip)
    c = next((c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)), "")
    return status, c.split(";", 1)[0]


_, cookie = login()
_, other = login(ip="198.51.100.7")


def csrf_of(page):
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


status, _, page = req("GET", "/profile", cookie=cookie)
check("/profile: 200 con el avatar y las iniciales", (200, True), (status, '<div class="avatar-grande">JD</div>' in page))
check("el nombre, «Dueño» y el último ingreso", True,
      "John Doe" in page and "Dueño" in page and re.search(r"Último ingreso: 20\d\d-\d\d-\d\d \d\d:\d\d UTC", page) is not None)
check("solo dos opciones: Datos personales y Contraseña (Q25)", (["/profile/info", "/profile/password"], False, False),
      (re.findall(r'<li><a href="(/profile/[^"]+)"', page), "Schedule" in page, "Security" in page))
check("la flecha de regreso", True, 'class="atras" href="/"' in page)
check("el último ingreso quedó en user.json", "198.51.100.7", users.load(user_file).get("last_login_ip"))
csrf = csrf_of(page)

# --- datos personales ---------------------------------------------------------------------
status, hdrs, _ = req("POST", "/profile/info", form={"csrf": csrf, "name": "John Q. Doe", "email": "john@example.com"},
                      cookie=cookie)
check("cambiar solo el nombre no pide contraseña: 303", (303, "/profile?ok=info"), (status, hdrs.get("location")))
check("y queda guardado", "John Q. Doe", users.load(user_file)["name"])
status, _, page = req("POST", "/profile/info", form={"csrf": csrf, "name": "John", "email": "nuevo@example.com"},
                      cookie=cookie)
check("cambiar el correo sin la contraseña: 400", (400, "john@example.com"), (status, users.load(user_file)["email"]))
status, _, page = req("POST", "/profile/info", form={"csrf": csrf, "name": "John", "email": "nuevo@example.com",
                                                      "current": "mala-contraseña-x"}, cookie=cookie)
check("con la contraseña mala: 400 y lo dice", (400, True), (status, "no es correcta" in page))
status, _, page = req("POST", "/profile/info", form={"csrf": csrf, "name": "John", "email": "no-es-correo",
                                                      "current": GOOD}, cookie=cookie)
check("un correo inválido: 400", (400, "john@example.com"), (status, users.load(user_file)["email"]))
status, hdrs, _ = req("POST", "/profile/info", form={"csrf": csrf, "name": "John Doe", "email": "nuevo@example.com",
                                                      "current": GOOD}, cookie=cookie)
check("con la contraseña buena: 303 y cambia", (303, "nuevo@example.com"), (status, users.load(user_file)["email"]))
check("ahora se entra con el correo nuevo", 303, login("nuevo@example.com")[0])
check("y ya no con el viejo", 401, login("john@example.com")[0])
status, _, _ = req("POST", "/profile/info", form={"name": "Sin token", "email": "nuevo@example.com"}, cookie=cookie)
check("sin el token de la sesión: 403", 403, status)

# --- contraseña ---------------------------------------------------------------------------
for form, why in (({"current": "mala-contraseña-x", "new": "otra-contraseña-1", "again": "otra-contraseña-1"}, "no es correcta"),
                  ({"current": GOOD, "new": "otra-contraseña-1", "again": "otra-contraseña-2"}, "no coinciden"),
                  ({"current": GOOD, "new": "corta", "again": "corta"}, "al menos 12"),
                  ({"current": GOOD, "new": GOOD, "again": GOOD}, "igual a la actual")):
    status, _, page = req("POST", "/profile/password", form={"csrf": csrf, **form}, cookie=cookie)
    check(f"contraseña: {why} -> 400", (400, True), (status, why in page))
check("ninguno cambió la contraseña", True, users.verify_password(GOOD, users.load(user_file)["password"]))
check("la otra sesión sigue abierta", 200, req("GET", "/", cookie=other)[0])

status, hdrs, _ = req("POST", "/profile/password", form={"csrf": csrf, "current": GOOD, "new": "otra-contraseña-1",
                                                          "again": "otra-contraseña-1"}, cookie=cookie)
check("cambiarla: 303 con ok", (303, "/profile?ok=password"), (status, hdrs.get("location")))
check("esta sesión sigue (FR-21)", 200, req("GET", "/profile?ok=password", cookie=cookie)[0])
check("y dice que se cerraron las otras", True, "Se cerraron tus otras sesiones" in req("GET", "/profile?ok=password", cookie=cookie)[2])
status, hdrs, _ = req("GET", "/", cookie=other)
check("la otra sesión se cerró: /login?msg=expired", (303, "/login?msg=expired"), (status, hdrs.get("location")))
check("la vieja ya no entra y la nueva sí", (401, 303), (login("nuevo@example.com")[0], login("nuevo@example.com", "otra-contraseña-1")[0]))

# --- el bloqueo vale aquí también ----------------------------------------------------------
ip = "198.51.100.99"
_, attacker = login("nuevo@example.com", "otra-contraseña-1", ip=ip)
page = req("GET", "/profile/password", cookie=attacker, ip=ip)[2]
csrf2 = csrf_of(page)
codes = [req("POST", "/profile/password", form={"csrf": csrf2, "current": f"mala-{i}-xxxxxxxx", "new": "x" * 12,
                                                 "again": "x" * 12}, cookie=attacker, ip=ip)[2] for i in range(6)]
check("5 contraseñas actuales malas y la sexta ya dice que está bloqueada", True,
      all("no es correcta" in c for c in codes[:5]) and "Demasiados intentos" in codes[5])

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
