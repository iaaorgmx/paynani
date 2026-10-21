#!/usr/bin/env python3
"""
Tests for PaynaniWeb's access (PRD #434 FR-5 to FR-9; T3 of #435).
An assertion script, like the rest of this suite.

La entrada con PDSL-100, el bloqueo tras 5 fallos, la sesión (cookie, 8 horas,
cambio de contraseña), cerrar sesión, el aviso por una dirección nueva, la IP
detrás del túnel, el origen de los formularios y que `next` no lleve a otro sitio.
Con un reloj y un «send.sh» de prueba; todo en 127.0.0.1.
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


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


# --- piezas sueltas ----------------------------------------------------------------
check("IP: el último X-Forwarded-For, el que pone el túnel", "198.51.100.9",
      auth.client_ip({"X-Forwarded-For": "1.2.3.4, 198.51.100.9"}, "127.0.0.1"))
check("IP: un último valor que no es dirección no vale", "127.0.0.1",
      auth.client_ip({"X-Forwarded-For": "1.2.3.4, basura"}, "127.0.0.1"))
check("IP: sin encabezado, la del socket", "127.0.0.1", auth.client_ip({}, "127.0.0.1"))
check("IP: IPv6 normalizada", "2001:db8::1", auth.client_ip({"X-Forwarded-For": "2001:DB8:0::1"}, "127.0.0.1"))

clock = Clock()
lock = auth.Lockout(clock)
for i in range(4):
    check(f"fallo {i + 1} no bloquea", False, lock.fail("a"))
check("el quinto bloquea", True, lock.fail("a"))
check("bloqueada 15 minutos", True, 899 <= lock.remaining("a") <= 901)
check("otra dirección no", 0, lock.remaining("b"))
clock.now += 15 * 60 + 1
check("a los 15 minutos se desbloquea", 0, lock.remaining("a"))
for _ in range(4):
    lock.fail("c")
clock.now += 15 * 60 + 1
check("4 fallos viejos (fuera de la ventana) no cuentan con el siguiente", False, lock.fail("c"))
for _ in range(3):
    lock.fail("d")
lock.success("d")
check("una entrada buena borra los fallos", False, any(lock.fail("d") for _ in range(4)))

user = {"password_changed_at": "t1", "name": "Ana"}
sessions = auth.Sessions(clock)
sid = sessions.create("1.1.1.1", user)
check("id de sesión largo y al azar", True, len(sid) >= 40 and sid != sessions.create("1.1.1.1", user))
check("la sesión sirve", True, sessions.get(sid, user) is not None)
clock.now += 8 * 3600 - 5
check("usada antes de 8 horas sigue (y se renueva)", True, sessions.get(sid, user) is not None)
clock.now += 8 * 3600 + 1
check("8 horas sin uso: vence", None, sessions.get(sid, user))
sid = sessions.create("1.1.1.1", user)
check("otra contraseña (password_changed_at) cierra la sesión", None, sessions.get(sid, dict(user, password_changed_at="t2")))
check("check_csrf sin sesión es False", False, auth.check_csrf(None, "x"))

tmp = Path(tempfile.mkdtemp())
user_file = tmp / "web" / "user.json"
check("remember_ip: nueva", True, auth.remember_ip(user_file, "1.1.1.1"))
check("remember_ip: ya vista", False, auth.remember_ip(user_file, "1.1.1.1"))
auth.known_ips_path(user_file).unlink()

GOOD = "una-contraseña-larga"
users.create("ana@example.com", "Ana Ruiz", GOOD, user_file)
check("verify_login: bien (correo sin importar mayúsculas)", True, auth.verify_login(users.load(user_file), "ANA@example.com ", GOOD))
check("verify_login: otro correo", False, auth.verify_login(users.load(user_file), "otro@example.com", GOOD))
check("verify_login: otra contraseña", False, auth.verify_login(users.load(user_file), "ana@example.com", GOOD + "x"))
check("verify_login: sin usuario", False, auth.verify_login(None, "ana@example.com", GOOD))

# --- el servidor ----------------------------------------------------------------------
sent = []
notifier = notify.Notifier(send=lambda to, subject, body: sent.append((to, subject, body)), log=lambda line: None)
ctx = app.Context(user_file, notifier=notifier, clock=clock)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, cookie="", ip="203.0.113.5", origin=True, headers=None):
    h = {"Host": HOST, "X-Forwarded-For": ip, "X-Forwarded-Proto": "https"}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        if origin is True:
            h["Origin"] = f"https://{HOST}"
        elif origin:
            h["Origin"] = origin
    h.update(headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


def session_cookie(hdrs):
    for c in hdrs["set-cookie-all"]:
        if c.startswith(auth.SESSION_COOKIE + "="):
            return c
    return ""


def login(email="ana@example.com", password=GOOD, ip="203.0.113.5", next_path="/"):
    return req("POST", "/login", form={"email": email, "password": password, "next": next_path}, ip=ip)


status, hdrs, page = req("GET", "/")
check("sin sesión, / -> /login", (303, "/login"), (status, hdrs.get("location")))
status, hdrs, page = req("GET", "/roster?id=ventas")
check("sin sesión, otra ruta -> /login con next", (303, "/login?next=/roster%3Fid%3Dventas"), (status, hdrs.get("location")))
status, hdrs, page = req("GET", "/login")
check("la página de entrar responde", 200, status)
check("sin «Sign up», Google ni teléfono (FR-5)", (False, False, False),
      ("sign up" in page.lower(), "google" in page.lower(), 'type="tel"' in page))
check("con correo y contraseña", True, 'name="email"' in page and 'type="password"' in page)
check("el lema y la marca de agua de PDSL-100", True, 'class="lema"' in page and 'class="marca-agua"' in page)
check("la página no carga nada de fuera", [], re.findall(r'(?:src|href)="(?:https?:)?//[^"]+"', page))

# --- entrar mal -------------------------------------------------------------------------
status, hdrs, page = login(password="mala-contraseña-x")
check("contraseña mala -> 401", 401, status)
bad_text = re.search(r'class="error"[^>]*>([^<]+)<', page).group(1)
status, hdrs, page = login(email="otro@example.com")
check("correo malo -> 401 con el mismo mensaje (no dice cuál falló)", (401, bad_text),
      (status, re.search(r'class="error"[^>]*>([^<]+)<', page).group(1)))
check("el formulario conserva el correo, nunca la contraseña", (True, False),
      ('value="otro@example.com"' in page, GOOD in page))
check("sin cookie de sesión al fallar", "", session_cookie(hdrs))

# --- el bloqueo ---------------------------------------------------------------------------
ip_x = "198.51.100.20"
codes = [login(password=f"mala-{i}-xxxxxxx", ip=ip_x)[0] for i in range(5)]
check("5 fallos: los primeros 401, el quinto 429", [401, 401, 401, 401, 429], codes)
status, hdrs, page = login(ip=ip_x)
check("bloqueada, ni la contraseña buena entra (429)", (429, ""), (status, session_cookie(hdrs)))
check("y dice cuántos minutos", True, "15" in page)
status, hdrs, _ = login(ip="198.51.100.21")
check("otra dirección sí entra", (303, True), (status, bool(session_cookie(hdrs))))
status, hdrs, _ = login(ip=f"{ip_x}, 198.51.100.22".split(", ")[0])
status, hdrs, _ = req("POST", "/login", form={"email": "ana@example.com", "password": GOOD},
                      ip=f"{ip_x}, 198.51.100.23")
check("un X-Forwarded-For falsificado al principio no salta el bloqueo de quien sí está bloqueado", True,
      ctx.lockout.remaining(ip_x) > 0)
clock.now += 15 * 60 + 1
status, hdrs, _ = login(ip=ip_x)
check("a los 15 minutos vuelve a entrar", (303, True), (status, bool(session_cookie(hdrs))))

# --- entrar bien ---------------------------------------------------------------------------
sent.clear()
auth.known_ips_path(user_file).unlink(missing_ok=True)
status, hdrs, _ = login(ip="203.0.113.77", next_path="/roster?id=ventas")
cookie = session_cookie(hdrs)
check("entrar -> 303 a next", (303, "/roster?id=ventas"), (status, hdrs.get("location")))
check("cookie de sesión HttpOnly, Secure y SameSite=Strict, sin Max-Age (de navegador)",
      (True, True, True, False), ("HttpOnly" in cookie, "Secure" in cookie, "SameSite=Strict" in cookie, "Max-Age" in cookie))
sid_cookie = cookie.split(";", 1)[0]
notifier.wait()
check("dirección nueva: un correo al dueño (FR-9)", 1, len(sent))
to, subject, body = sent[0]
check("al correo del usuario", "ana@example.com", to)
check("con la dirección, sin la contraseña", (True, False), ("203.0.113.77" in body, GOOD in body))
check("y dice cómo cambiar la contraseña", True, "scripts/paynani web passwd" in body)
status, hdrs, _ = login(ip="203.0.113.77")
notifier.wait()
check("la misma dirección otra vez: no hay segundo correo", 1, len(sent))
status, hdrs, page = req("GET", "/", cookie=sid_cookie)
check("con sesión, / responde la página de inicio", (200, True), (status, "Ana Ruiz" in page))
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
status, hdrs, _ = req("GET", "/login", cookie=sid_cookie)
check("con sesión, /login lleva a /", (303, "/"), (status, hdrs.get("location")))

# --- next no lleva a otro sitio ------------------------------------------------------------------
for evil in ("//evil.example/x", "https://evil.example", "/\\evil.example", "javascript:alert(1)", "/login?x", "/a\r\nSet-Cookie: x=1"):
    check(f"next={evil!r} -> /", "/", app.safe_next(evil))
check("next de una ruta propia se respeta", "/email/accounts?id=1", app.safe_next("/email/accounts?id=1"))
status, hdrs, _ = login(ip="203.0.113.77", next_path="//evil.example/")
check("y en la petición, un next de otro sitio va a /", "/", hdrs.get("location"))

# --- el origen de los formularios -------------------------------------------------------------------
status, _, _ = req("POST", "/login", form={"email": "ana@example.com", "password": GOOD}, origin=None)
check("POST sin Origin ni Referer -> 403", 403, status)
status, _, _ = req("POST", "/login", form={"email": "ana@example.com", "password": GOOD}, origin="https://evil.example")
check("POST desde otro origen -> 403", 403, status)
status, _, _ = req("POST", "/login", form={"email": "ana@example.com", "password": GOOD}, origin=None,
                   headers={"Referer": f"https://{HOST}/login"})
check("sin Origin pero con Referer de aquí, pasa", 303, status)

# --- cerrar sesión ---------------------------------------------------------------------------------
status, _, _ = req("POST", "/logout", form={"csrf": "otro"}, cookie=sid_cookie)
check("logout con token malo -> 403", 403, status)
status, _, _ = req("GET", "/", cookie=sid_cookie)
check("y la sesión sigue", 200, status)
status, hdrs, _ = req("POST", "/logout", form={"csrf": csrf}, cookie=sid_cookie)
check("logout -> 303 a /login?msg=out", (303, "/login?msg=out"), (status, hdrs.get("location")))
check("y borra la cookie", True, any(c.startswith(auth.SESSION_COOKIE + "=;") or "Max-Age=0" in c
                                     for c in hdrs["set-cookie-all"]))
status, hdrs, _ = req("GET", "/", cookie=sid_cookie)
check("la sesión cerrada ya no sirve: /login?msg=expired", (303, "/login?msg=expired"), (status, hdrs.get("location")))
status, _, page = req("GET", "/login?msg=out")
check("/login?msg=out dice que cerraste la sesión", True, 'class="aviso"' in page)

# --- cambiar la contraseña cierra las sesiones ----------------------------------------------------------
status, hdrs, _ = login()
sid_cookie = session_cookie(hdrs).split(";", 1)[0]
check("otra sesión", 200, req("GET", "/", cookie=sid_cookie)[0])
clock.now += 1
users.set_password("otra-contraseña-larga", user_file)
status, hdrs, _ = req("GET", "/", cookie=sid_cookie)
check("después de paynani web passwd, la sesión vieja ya no sirve", (303, "/login?msg=expired"), (status, hdrs.get("location")))

# --- 8 horas sin uso ---------------------------------------------------------------------------------------
status, hdrs, _ = login(password="otra-contraseña-larga")
sid_cookie = session_cookie(hdrs).split(";", 1)[0]
clock.now += 8 * 3600 + 5
status, hdrs, _ = req("GET", "/", cookie=sid_cookie)
check("8 horas sin uso: /login?msg=expired", (303, "/login?msg=expired"), (status, hdrs.get("location")))

# --- un cuerpo demasiado grande ------------------------------------------------------------------------------
status, _, _ = req("POST", "/login", form={"email": "a", "password": "x" * 70000})
check("un cuerpo de más de 64 KB -> 413", 413, status)

# --- un aviso que no sale no rompe la entrada ------------------------------------------------------------------
def broken(to, subject, body):
    raise RuntimeError("send.sh falló")


logged = []
ctx.notifier = notify.Notifier(send=broken, log=logged.append)
auth.known_ips_path(user_file).unlink(missing_ok=True)
status, hdrs, _ = login(password="otra-contraseña-larga", ip="203.0.113.99")
ctx.notifier.wait()
check("si el aviso no sale, se entra igual", (303, True), (status, bool(session_cookie(hdrs))))
check("y queda una línea en el log, sin el cuerpo", True,
      len(logged) == 1 and "no salió" in logged[0] and "203.0.113.99" not in logged[0])

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
