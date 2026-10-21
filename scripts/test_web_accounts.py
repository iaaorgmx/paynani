#!/usr/bin/env python3
"""
Tests for adding and removing mail accounts from PaynaniWeb (PRD #434 FR-16,
#435 Q23; T6 of #435). An assertion script, like the rest of this suite.

La web usa lo mismo que `paynani account add/remove` (accounts_cli.prepare_add,
commit_add, remove_account) con un servicio, un IMAP y un SMTP de prueba. Pide la
contraseña de la web antes de agregar o quitar, prueba el acceso antes de
escribir, nunca devuelve la contraseña del correo en la página, no quita la cuenta
del agente, y le avisa al dueño. Todo en una carpeta temporal.
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
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

tmp = Path(tempfile.mkdtemp())
env_file = tmp / ".env"
env_file.write_text("AGENT_EMAIL_ACCOUNT=agente@example.com\nAGENT_EMAIL_PASSWORD=x\n", encoding="utf-8")
os.chmod(env_file, 0o600)
os.environ["PAYNANI_ENV"] = str(env_file)

from paynani_lib import accounts, accounts_cli  # noqa: E402
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


class Service:
    def __init__(self):
        self.calls = []
        self.enable_state = "active"
        self.disable_state = "inactive"

    def enable(self, account_id):
        self.calls.append(("enable", account_id))
        return self.enable_state

    def disable(self, account_id):
        self.calls.append(("disable", account_id))
        return self.disable_state


service = Service()
himalaya = tmp / "himalaya.toml"
accounts_cli.account_service = service
accounts_cli.himalaya_config_path = lambda: himalaya
probes = []
answers = {"imap": True, "smtp": True}


def fake_probe(kind):
    def probe(host, port, user, password):
        probes.append((kind, host, port, user, password))
        ok = answers[kind]
        return {"ok": ok, "steps": [{"ok": ok, "text": f"{kind} {host}:{port}", "detail": "" if ok else "rechazado"}]}
    return probe


sent = []
user_file = tmp / "web" / "user.json"
WEB = "una-contraseña-larga"
users.create("dueno@example.com", "Dueño", WEB, user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda to, s, b: sent.append((to, s, b)), log=lambda l: None),
                  agent_email="agente@example.com", accounts_file=accounts.accounts_path(),
                  state_dir=tmp / "state", roster_path=tmp / "roster.md")
ctx.probe_imap = fake_probe("imap")
ctx.probe_smtp = fake_probe("smtp")
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"
IP = "203.0.113.5"


def req(method, path, *, form=None, cookie="", ip=IP):
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


_, hdrs, _ = req("POST", "/login", form={"email": "dueno@example.com", "password": WEB})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
csrf = re.search(r'name="csrf" value="([^"]+)"', req("GET", "/", cookie=cookie)[2]).group(1)
MAILPW = "clave-del-correo-123"


def add(**over):
    form = {"csrf": csrf, "id": "ventas", "email": "ventas@example.com", "from_name": "Ventas", "imap_host": "imap.example.com",
            "imap_port": "993", "smtp_host": "smtp.example.com", "smtp_port": "465", "mailbox": "INBOX",
            "account_password": MAILPW, "current": WEB}
    form.update(over)
    return req("POST", "/cuentas/nueva", form=form, cookie=cookie)


status, _, page = req("GET", "/", cookie=cookie)
check("el desplegable tiene «+ Agregar cuenta»", True, 'href="/cuentas/nueva"' in page)
status, _, page = req("GET", "/cuentas/nueva", cookie=cookie)
check("el formulario pide la contraseña del correo y la de la web", (200, True, True),
      (status, 'name="account_password"' in page, 'name="current"' in page))

# --- sin la contraseña de la web, nada ------------------------------------------------------
status, _, page = add(current="mala-contraseña-x")
check("contraseña de la web mala: 403, sin probar ni escribir", (403, [], False),
      (status, probes, accounts.accounts_path().exists()))
check("y la página no devuelve la contraseña del correo", False, MAILPW in page)

# --- el servidor rechaza ---------------------------------------------------------------------
answers["imap"] = False
status, _, page = add()
check("IMAP rechaza: 400 con los pasos, sin escribir", (400, True, False),
      (status, "imap imap.example.com:993" in page, accounts.accounts_path().exists()))
check("con el login de la cuenta y su contraseña", ("imap", "imap.example.com", 993, "ventas@example.com", MAILPW), probes[-1])
check("y no devuelve la contraseña del correo", False, MAILPW in page)
answers["imap"], answers["smtp"] = True, False
status, _, page = add()
check("SMTP rechaza: 400, sin escribir (Q23 prueba los dos)", (400, False), (status, accounts.accounts_path().exists()))
answers["smtp"] = True
status, _, page = add(id="main")
check("el id main es de la cuenta del agente: 400 con el mensaje de la CLI", (400, True), (status, "not a usable id" in page))
status, _, page = add(account_password="")
check("sin contraseña del correo: 400", 400, status)
env_before = env_file.read_bytes()
probes.clear()
for bad in ("abc\nAGENT_EMAIL_PASSWORD=xyz", "abc\rdef", "abc\x00def"):
    status, _, page = add(account_password=bad)
    check(f"contraseña con {bad[3]!r} en medio: 400, sin probar ni escribir (revisión de #446)",
          (400, True, [], env_before), (status, "saltos de línea" in page, probes, env_file.read_bytes()))
try:
    accounts_cli._env_edit("PAYNANI_X", "a\nb")
    check("_env_edit con un salto de línea se niega", "AccountOpError", "nada")
except accounts_cli.AccountOpError:
    check("_env_edit con un salto de línea se niega (también la CLI)", env_before, env_file.read_bytes())

# --- agregar -----------------------------------------------------------------------------------
probes.clear()
status, hdrs, _ = add()
check("agregar -> 303 a la cuenta nueva", (303, "/email/ventas?ok=added"), (status, hdrs.get("location")))
check("probó IMAP y SMTP", ["imap", "smtp"], [p[0] for p in probes])
saved = json.loads(accounts.accounts_path().read_text(encoding="utf-8"))
check("accounts.json con la cuenta, sin su contraseña", (["ventas"], False),
      ([a["id"] for a in saved["accounts"]], MAILPW in accounts.accounts_path().read_text(encoding="utf-8")))
check("la contraseña en el .env, en modo 600", (True, 0o600),
      (f"PAYNANI_ACCOUNT_VENTAS_PASSWORD={MAILPW}" in env_file.read_text(encoding="utf-8"),
       __import__("stat").S_IMODE(env_file.stat().st_mode)))
check("su roster y su cuenta de himalaya", (True, True),
      ((tmp / "rosters" / "ventas.md").exists(), "[accounts.paynani-ventas]" in himalaya.read_text(encoding="utf-8")))
check("y arrancó su servicio", ("enable", "ventas"), service.calls[-1])
notify_wait = ctx.notifier.wait()
check("aviso al dueño, sin la contraseña", (True, True, False),
      (sent[-1][0] == "dueno@example.com", "ventas@example.com" in sent[-1][1], MAILPW in sent[-1][2]))
status, _, page = req("GET", "/email/ventas?ok=added", cookie=cookie)
check("la cuenta en el menú y el aviso", (200, True, True), (status, "ventas@example.com" in page, 'class="aviso-ok"' in page))
check("con «Quitar esta cuenta»", True, 'href="/cuentas/ventas/quitar"' in page)
status, _, page = add()
check("agregarla otra vez: 400 (ya existe)", (400, True), (status, "already exists" in page))

# --- quitar ---------------------------------------------------------------------------------------
status, _, page = req("GET", "/email/main", cookie=cookie)
check("la cuenta del agente no tiene «Quitar»", False, "/cuentas/main/quitar" in page)
status, _, _ = req("GET", "/cuentas/main/quitar", cookie=cookie)
check("ni por la ruta: 404", 404, status)
status, _, _ = req("POST", "/cuentas/main/quitar", form={"csrf": csrf, "current": WEB}, cookie=cookie)
check("ni por POST", 404, status)
status, _, page = req("GET", "/cuentas/ventas/quitar", cookie=cookie)
check("la confirmación explica que el buzón no se toca", (200, True), (status, "El buzón no se toca" in page))
status, _, _ = req("POST", "/cuentas/ventas/quitar", form={"csrf": csrf, "current": "mala-contraseña-x"}, cookie=cookie)
check("quitar con la contraseña de la web mala: 403, sigue", (403, ["ventas"]),
      (status, [a["id"] for a in accounts.load(accounts.accounts_path())]))
service.disable_state = "active"
status, _, page = req("POST", "/cuentas/ventas/quitar", form={"csrf": csrf, "current": WEB}, cookie=cookie)
check("si el servicio no se detiene: 400 y nada cambia", (400, ["ventas"]),
      (status, [a["id"] for a in accounts.load(accounts.accounts_path())]))
service.disable_state = "inactive"
status, hdrs, _ = req("POST", "/cuentas/ventas/quitar", form={"csrf": csrf, "current": WEB}, cookie=cookie)
check("quitar -> 303 a la cuenta del agente", (303, "/email/main?ok=removed"), (status, hdrs.get("location")))
check("fuera de accounts.json y su contraseña fuera del .env", ([], False),
      ([a["id"] for a in accounts.load(accounts.accounts_path())], "PAYNANI_ACCOUNT_VENTAS_PASSWORD" in env_file.read_text(encoding="utf-8")))
check("su roster se guardó en rosters/removed/, no se borró", (False, True),
      ((tmp / "rosters" / "ventas.md").exists(), (tmp / "rosters" / "removed" / "ventas.md").exists()))
ctx.notifier.wait()
check("y aviso al dueño", True, "ya no" in sent[-1][1].lower() or "dejó de vigilar" in sent[-1][1])
status, _, _ = req("POST", "/cuentas/nueva", form={"id": "x", "current": WEB}, cookie=cookie)
check("sin el token de la sesión: 403", 403, status)

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
