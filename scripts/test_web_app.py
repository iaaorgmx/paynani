#!/usr/bin/env python3
"""
Tests for PaynaniWeb's skeleton (PRD #434 FR-3, FR-4, FR-5, FR-11; T2 of #435).
An assertion script, like the rest of this suite.

El usuario (scrypt, modo 600, uno solo), `paynani web user add` / `passwd` /
`user show`, y el servidor: sin usuario toda ruta es «crea tu usuario», los
recursos estáticos, los encabezados de seguridad, el idioma y que nada se cargue
de fuera. Todo en una carpeta temporal y en 127.0.0.1.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, strings, users  # noqa: E402

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
user_file = tmp / "cfg" / "web" / "user.json"
GOOD = "una-contraseña-larga"

# --- el usuario ---------------------------------------------------------------
check("sin archivo no hay usuario", False, users.exists(user_file))
h = users.hash_password(GOOD)
check("el hash es scrypt con sus parámetros", True, h.startswith("scrypt$16384$8$1$"))
check("la contraseña buena verifica", True, users.verify_password(GOOD, h))
check("una mala no", False, users.verify_password(GOOD + "x", h))
check("dos hashes de la misma contraseña difieren (sal)", False, h == users.hash_password(GOOD))
check("un hash mal formado nunca deja pasar", (False, False, False),
      (users.verify_password(GOOD, "scrypt$x"), users.verify_password(GOOD, ""),
       users.verify_password(GOOD, "bcrypt$1$2$3$aa$bb")))
check("parámetros viejos en la cadena siguen verificando", True,
      users.verify_password(GOOD, users.hash_password(GOOD, n=2 ** 12)))

for bad, why in (("corta", "at least"), (" " + GOOD, "space"), ("x" * 2000, "at most")):
    check(f"contraseña rechazada ({why})", True, why in users.password_problem(bad))
check("una de 12 caracteres sirve", "", users.password_problem("x" * 12))

for email, name, label in (("no-es-correo", "Ana", "correo"), ("ana@example.com", " ", "nombre")):
    try:
        users.create(email, name, GOOD, user_file)
        check(f"create sin {label} válido se niega", "UserError", "nada")
    except users.UserError:
        check(f"create sin {label} válido se niega", True)
check("y no deja archivo", False, user_file.exists())

data = users.create("ana@example.com", "Ana Ruiz", GOOD, user_file)
check("create guarda nombre y correo", ("Ana Ruiz", "ana@example.com"), (data["name"], data["email"]))
saved = user_file.read_text(encoding="utf-8")
check("el archivo no trae la contraseña en claro", False, GOOD in saved)
check("archivo en modo 600", 0o600, stat.S_IMODE(user_file.stat().st_mode))
check("carpeta en modo 700", 0o700, stat.S_IMODE(user_file.parent.stat().st_mode))
check("no quedan temporales", [], [p.name for p in user_file.parent.iterdir() if p.name != "user.json"])
try:
    users.create("otro@example.com", "Otro", GOOD, user_file)
    check("un segundo usuario se niega (FR-6)", "UserError", "nada")
except users.UserError as exc:
    check("un segundo usuario se niega (FR-6)", True, "passwd" in str(exc))
check("public() no trae el hash", False, "password" in users.public(users.load(user_file)))

old = users.load(user_file)["password"]
users.set_password("otra-contraseña-larga", user_file)
check("set_password cambia el hash", False, old == users.load(user_file)["password"])
check("y la nueva verifica", True, users.verify_password("otra-contraseña-larga", users.load(user_file)["password"]))
user_file.write_text("{roto", encoding="utf-8")
check("un archivo roto cuenta como sin usuario (vuelve «crea tu usuario»)", False, users.exists(user_file))
user_file.write_text(json.dumps({"email": "a@b.co", "password": "plano"}), encoding="utf-8")
check("un archivo sin hash scrypt cuenta como sin usuario", False, users.exists(user_file))
user_file.unlink()

check("PAYNANI_WEB_USER cambia el archivo", Path("/tmp/x/user.json"),
      users.user_path({"PAYNANI_WEB_USER": "/tmp/x/user.json"}))
check("sin él, <config>/web/user.json", True, str(users.user_path({})).endswith("/web/user.json"))
check("/web/ está en .gitignore", 0, subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "web/user.json"]).returncode)

# --- paynani web ... ------------------------------------------------------------
env = dict(os.environ, PAYNANI_WEB_USER=str(user_file))


def cli(*args, stdin=""):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "paynani"), "web", *args], input=stdin,
                         capture_output=True, text=True, env=env, timeout=60)
    return out.returncode, out.stdout + out.stderr


code, out = cli("user", "show")
check("user show sin usuario: 1 y lo dice", (1, True), (code, "no user yet" in out))
code, out = cli("passwd", "--password-stdin", stdin="nueva-contraseña-1\n")
check("passwd sin usuario: 1", (1, True), (code, "user add" in out))
code, out = cli("user", "add", "--email", "ana@example.com", "--name", "Ana")
check("user add sin terminal ni --password-stdin: 1, sin archivo", (1, False), (code, user_file.exists()))
code, out = cli("user", "add", "--email", "ana@example.com", "--name", "Ana", "--password-stdin", stdin="corta\n")
check("user add con contraseña corta: 2, sin archivo", (2, False), (code, user_file.exists()))
code, out = cli("user", "add", "--email", "ana@example.com", "--name", "Ana Ruiz", "--password-stdin",
                stdin=GOOD + "\n")
check("user add: 0 y lo crea", (0, True), (code, user_file.exists()))
check("la salida no trae la contraseña", False, GOOD in out)
check("y dice dónde lo guardó", True, str(user_file) in out)
code, out = cli("user", "add", "--email", "b@example.com", "--name", "B", "--password-stdin", stdin=GOOD + "\n")
check("un segundo user add: 1 (uno solo)", (1, True), (code, "already has a user" in out))
code, out = cli("user", "show")
check("user show: nombre y correo, sin hash", (0, True, False), (code, "Ana Ruiz <ana@example.com>" in out, "scrypt" in out))
code, out = cli("passwd", "--password-stdin", stdin="nueva-contraseña-1\n")
check("passwd cambia", (0, True), (code, users.verify_password("nueva-contraseña-1", users.load(user_file)["password"])))
user_file.unlink()

# Un user.json roto no deja al dueño sin salida (Metis en #437).
user_file.write_text("{roto", encoding="utf-8")
try:
    users.create("ana@example.com", "Ana", GOOD, user_file)
    check("create con un user.json roto se niega", "UserError", "nada")
except users.UserError as exc:
    check("create con un user.json roto dice que lo apartes con mv", True, "mv " in str(exc) and ".broken" in str(exc))
code, out = cli("user", "add", "--email", "ana@example.com", "--name", "Ana", "--password-stdin", stdin=GOOD + "\n")
check("user add con un user.json roto: 1 y dice cómo salir", (1, True, True),
      (code, "not a valid PaynaniWeb user file" in out, f"mv {user_file} {user_file}.broken" in out))
user_file.rename(str(user_file) + ".broken")
code, out = cli("user", "add", "--email", "ana@example.com", "--name", "Ana", "--password-stdin", stdin=GOOD + "\n")
check("después de apartarlo, user add funciona", (0, True), (code, users.exists(user_file)))
user_file.unlink()
Path(str(user_file) + ".broken").unlink()

# --- textos -----------------------------------------------------------------------
keys = set(strings.STRINGS["es-MX"])
for lang in i18n.LANGUAGES:
    check(f"{lang}: tiene todas las claves web.*", set(), keys - set(strings.STRINGS.get(lang, {})))
check("las claves web.* llegan a los catálogos de i18n", "Language",
      __import__("paynani_lib.i18n_data", fromlist=["CATALOGUES"]).CATALOGUES["en-US"]["web.lang.label"])

# --- idioma -------------------------------------------------------------------------
check("?lang= gana y se recuerda", ("fr-FR", True), app.negotiate_lang({"lang": ["fr-FR"]}, "paynani_web_lang=en-US", "es"))
check("si no, la cookie", ("en-US", False), app.negotiate_lang({}, "paynani_web_lang=en-US", "fr"))
check("si no, Accept-Language por su idioma (pt -> pt-BR)", ("pt-BR", False), app.negotiate_lang({}, "", "pt;q=0.9, en"))
check("Accept-Language exacto", ("es-ES", False), app.negotiate_lang({}, "", "es-ES,es;q=0.8"))
check("nada conocido -> es-MX", ("es-MX", False), app.negotiate_lang({"lang": ["xx"]}, "paynani_web_lang=zz", "de"))
check("una cookie mal formada no truena", ("es-MX", False), app.negotiate_lang({}, '"""; =', ""))

# --- el servidor ---------------------------------------------------------------------
try:
    app.serve("0.0.0.0", 0, user_file)
    check("serve fuera de loopback se niega", "ValueError", "nada")
except ValueError:
    check("serve fuera de loopback se niega", True)

httpd = app.serve("127.0.0.1", 0, user_file)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def get(path, method="GET", headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data.decode("utf-8", "replace")


for path in ("/", "/email/accounts", "/roster?id=ventas", "/login"):
    status, hdrs, page = get(path)
    check(f"sin usuario, {path} -> «crea tu usuario»", (200, True),
          (status, "scripts/paynani web user add" in page))
status, hdrs, page = get("/", headers={"Accept-Language": "en-US"})
check("en inglés con Accept-Language", True, "The user has not been created yet" in page)
check("lang en <html>", True, '<html lang="en-US">' in page)
status, hdrs, page = get("/?lang=pt-BR")
check("?lang=pt-BR en portugués", True, "O usuário ainda não foi criado" in page)
check("y deja la cookie de idioma, HttpOnly y SameSite=Strict", True,
      all(x in hdrs.get("set-cookie", "") for x in ("paynani_web_lang=pt-BR", "HttpOnly", "SameSite=Strict")))
status, hdrs, page = get("/?lang=en-US", headers={"X-Forwarded-Proto": "https"})
check("detrás del túnel https, la cookie es Secure", True, "Secure" in hdrs.get("set-cookie", ""))
check("CSP sin nada de fuera", True, "default-src 'none'" in hdrs.get("content-security-policy", ""))
check("X-Frame-Options DENY y nosniff", ("DENY", "nosniff"), (hdrs.get("x-frame-options"), hdrs.get("x-content-type-options")))
check("Cache-Control no-store", True, "no-store" in hdrs.get("cache-control", ""))
check("Server sin versión de Python", "paynani-web", hdrs.get("server"))
check("la página no carga nada de fuera", [], re.findall(r'(?:src|href)="(?:https?:)?//[^"]+"', page))
check("trae la marca en línea (la voluta)", True, 'class="voluta"' in page)
status, hdrs, page = get("/", method="POST", headers={"Content-Length": "3"}, body="a=b")
check("POST sin usuario -> «crea tu usuario»", (200, True), (status, "web user add" in page))

for path, kind in (("/assets/app.css", "text/css"), ("/assets/web.css", "text/css"), ("/assets/lang.js", "application/javascript")):
    status, hdrs, _ = get(path)
    check(f"{path} se sirve", (200, True), (status, hdrs.get("content-type", "").startswith(kind)))
for path in ("/assets/../web/users.py", "/assets/app.css/../../web/users.py", "/assets/x.css"):
    status, _, body = get(path)
    check(f"{path}: no sirve ningún archivo fuera de la lista", False, "def verify_password" in body or "scrypt" in body)
status, hdrs, body = get("/_health")
check("/_health sin usuario", (200, {"ok": True, "configured": False}), (status, json.loads(body)))

users.create("ana@example.com", "Ana Ruiz", GOOD, user_file)
status, _, body = get("/_health")
check("/_health con usuario", {"ok": True, "configured": True}, json.loads(body))
status, hdrs, page = get("/")
check("con usuario y sin sesión, / lleva a /login (T3)", (303, "/login"), (status, hdrs.get("location")))
status, _, page = get("/login")
check("y /login ya no es «crea tu usuario»", (200, False), (status, "web user add" in page))
status, hdrs, page = get("/no-existe")
check("sin sesión, una ruta desconocida también lleva a /login", (303, True),
      (status, hdrs.get("location", "").startswith("/login")))
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
conn.request("HEAD", "/login")
head = conn.getresponse()
head_body = head.read()
conn.close()
check("HEAD responde 200 con Content-Length y sin cuerpo", (200, True, b""),
      (head.status, int(head.getheader("Content-Length", "0")) > 0, head_body))
import socket
raw = socket.create_connection(("127.0.0.1", port), timeout=10)
raw.sendall(b"HEAD /login HTTP/1.1\r\nHost: x\r\n\r\n")
chunks = b""
while True:
    piece = raw.recv(65536)
    if not piece:
        break
    chunks += piece
raw.close()
check("en el socket, después de los encabezados no viene nada", b"", chunks.split(b"\r\n\r\n", 1)[1])

# --- varios a la vez, cada uno en su idioma ----------------------------------------------
results = {}


def worker(lang):
    _, _, page = get(f"/login?lang={lang}")
    results[lang] = re.search(r'<html lang="([^"]+)"', page).group(1)


threads = [threading.Thread(target=worker, args=(lang,)) for lang in list(i18n.LANGUAGES) * 3]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("peticiones a la vez en idiomas distintos no se mezclan", {lang: lang for lang in i18n.LANGUAGES}, results)
httpd.shutdown()
httpd.server_close()

# --- el proceso real ---------------------------------------------------------------------
user_file.unlink()
probe = app.serve("127.0.0.1", 0, user_file)
free = probe.server_address[1]
probe.server_close()
proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "paynani_web.py"), "--port", str(free)],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    line = proc.stdout.readline()
    check("paynani_web.py arranca y dice que espera el usuario", True,
          "listening on 127.0.0.1" in line and "web user add" in line)
    port = free
    status, _, page = get("/x?secreto=1")
    check("y sirve «crea tu usuario»", (200, True), (status, "web user add" in page))
    proc.terminate()
    out, _ = proc.communicate(timeout=10)
    check("SIGTERM lo detiene", 0, proc.returncode)
    check("el log trae el método y la ruta, no la consulta", (True, False), ("GET /x" in out, "secreto" in out))
finally:
    if proc.poll() is None:
        proc.kill()
code = subprocess.run([sys.executable, str(ROOT / "scripts" / "paynani_web.py"), "--host", "0.0.0.0"],
                      env=env, capture_output=True, text=True, timeout=30).returncode
check("paynani_web.py fuera de loopback sale con 2", 2, code)
code = subprocess.run([sys.executable, str(ROOT / "scripts" / "paynani_web.py"), "--port", "8770"],
                      env=dict(env, PAYNANI_SMS_PORT="8770"), capture_output=True, text=True, timeout=30).returncode
check("paynani_web.py en el puerto de la pasarela sale con 2", 2, code)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
