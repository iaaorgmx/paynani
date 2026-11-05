#!/usr/bin/env python3
"""
A1 #719 (PaynaniWebMT#2): emparejar clientes web del dueño.

El código (bueno, vencido, usado, equivocado, bloqueado), el token pw_ que sólo
guarda su SHA-256, revocar, el endpoint POST /api/owner/pair (201/410/429/415/400),
el CLI `web pair` / `web clients` y la página «Apps conectadas».
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
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import api_tokens, app, auth, notify, owner_clients, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


# --- el módulo ------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
user_file = tmp / "web" / "user.json"
GOOD = "una-contraseña-larga"
users.create("owner@example.com", "Owner", GOOD, user_file)
store = owner_clients.clients_path(user_file)
check("el archivo vive junto a user.json", user_file.parent / "owner_clients.json", store)

T0 = 1_800_000_000.0
code = owner_clients.new_code(path=store, now=T0)
check("código de 8 caracteres sin letras confusas", True,
      len(code) == 8 and all(c in owner_clients.CODE_ALPHABET for c in code))
pairing = (store.parent / "owner_pairing.json").read_text()
check("el código no se guarda en claro", False, code in pairing)
outcome, (token, record) = owner_clients.pair(code.lower(), "Mi MT", app_name="PaynaniWebMT", app_version="0.1.0",
                                             ip="198.51.100.1", path=store, now=T0 + 5)
check("emparejar con el código bueno (sin importar mayúsculas)", "ok", outcome)
check("token pw_ y client_id w_", True, token.startswith("pw_") and re.fullmatch(r"w_[0-9a-f]{8}", record["client_id"]) is not None)
check("sólo se guarda el SHA-256", (False, True), (token in store.read_text(), record["sha256"] in store.read_text()))
check("modos 600 y 700", (0o600, 0o600, 0o700),
      (stat.S_IMODE(store.stat().st_mode), stat.S_IMODE((store.parent / "owner_pairing.json").stat().st_mode),
       stat.S_IMODE(store.parent.stat().st_mode)))
check("el código ya usado no sirve", ("expired", ""), owner_clients.pair(code, "x", path=store, now=T0 + 6))
code = owner_clients.new_code(path=store, now=T0)
check("el código vencido no sirve", "expired",
      owner_clients.pair(code, "x", path=store, now=T0 + owner_clients.CODE_TTL_S + 1)[0])
check("sin código vigente", "expired", owner_clients.pair("ABCDEFGH", "x", path=tmp / "otro" / "c.json")[0])

code = owner_clients.new_code(path=store, now=T0)
for _ in range(owner_clients.FAIL_LIMIT - 1):
    owner_clients.pair("WRONGXXX", "x", path=store, now=T0 + 1)
check("el décimo código equivocado bloquea", "blocked", owner_clients.pair("WRONGXXX", "x", path=store, now=T0 + 1)[0])
check("bloqueado, ni el código bueno entra", "blocked", owner_clients.pair(code, "x", path=store, now=T0 + 2)[0])
code = owner_clients.new_code(path=store, now=T0 + 3)
check("un código nuevo levanta el bloqueo", "ok", owner_clients.pair(code, "Segunda", path=store, now=T0 + 4)[0])

check("lookup del token bueno", "ok", owner_clients.lookup(token, path=store)[0])
check("lookup rechaza un token de agente pn_", "invalid_token",
      owner_clients.lookup(api_tokens.TOKEN_PREFIX + "x" * 40 if hasattr(api_tokens, "TOKEN_PREFIX") else "pn_" + "x" * 40,
                           path=store)[0])
check("lookup rechaza basura", "invalid_token", owner_clients.lookup("pw_\ud800", path=store)[0])
check("public() quita el hash", False, "sha256" in owner_clients.public(record))
check("revocar por id", record["client_id"], (owner_clients.revoke(record["client_id"], path=store) or {}).get("client_id"))
check("revocado no abre", "token_revoked", owner_clients.lookup(token, path=store)[0])
check("revocar dos veces da None", None, owner_clients.revoke(record["client_id"], path=store))
check("revocar un id malformado da None", None, owner_clients.revoke("../x", path=store))
check("varios clientes a la vez (Q3)", 2, len(owner_clients.list_clients(path=store)))

# --- el endpoint y la página ------------------------------------------------------------------
sent = []
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: sent.append(a), log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "none.json", state_dir=tmp / "state",
                  roster_path=tmp / "roster.md")
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, json_body=None, raw=None, ctype=None, cookie="", ip="203.0.113.5"):
    h = {"Host": HOST, "X-Forwarded-For": ip}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = f"https://{HOST}"
    elif json_body is not None:
        body = json.dumps(json_body)
        h["Content-Type"] = "application/json"
    elif raw is not None:
        body = raw
        h["Content-Type"] = ctype or "text/plain"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


code = owner_clients.new_code(path=store)
status, hdrs, body = req("POST", "/api/owner/pair",
                         json_body={"code": code, "name": "MT de prueba", "app_name": "PaynaniWebMT", "app_version": "0.1.0"})
data = json.loads(body)
check("POST /api/owner/pair: 201 con token y client_id", (201, True, True),
      (status, data.get("token", "").startswith("pw_"), data.get("client_id", "").startswith("w_")))
check("request_id en cuerpo y encabezado", data.get("request_id"), hdrs.get("x-request-id"))
check("el dueño recibe un correo", True, any("nueva app conectada" in str(a) for a in sent))
check("el correo dice la app y su versión", True, any("PaynaniWebMT 0.1.0" in str(a) for a in sent))
saved = next(r for r in json.loads(store.read_text()) if r["client_id"] == data["client_id"])
check("app_name y app_version de primer nivel llegan al registro", ("MT de prueba", "PaynaniWebMT", "0.1.0"),
      (saved["name"], saved["app_name"], saved["app_version"]))
check("el correo no lleva el token", False, any(data["token"] in str(a) for a in sent))
status, _, body = req("POST", "/api/owner/pair", json_body={"code": code, "name": "otra vez"})
check("el mismo código otra vez: 410 code_expired", (410, "code_expired"), (status, json.loads(body).get("code")))
check("sin JSON: 415", 415, req("POST", "/api/owner/pair", raw="code=x", ctype="application/x-www-form-urlencoded")[0])
check("JSON roto: 400", 400, req("POST", "/api/owner/pair", raw="{", ctype="application/json")[0])
for _ in range(owner_clients.FAIL_LIMIT):
    status, _, body = req("POST", "/api/owner/pair", json_body={"code": "WRONGXXX"}, ip="198.51.100.9")
check("10 códigos equivocados: 429 too_many_attempts", (429, "too_many_attempts"), (status, json.loads(body).get("code")))
security = (tmp / "state").rglob("api_security.jsonl")
log = "".join(p.read_text() for p in security)
check("bitácora: owner_paired y owner_pair_blocked, sin token", (True, True, False),
      ("owner_paired" in log, "owner_pair_blocked" in log, data["token"] in log))
check("la bitácora guarda el prefijo pw_", True, data["token"][:11] in log)

check("/apps sin sesión manda a login", 303, req("GET", "/apps")[0])
_, hdrs, _ = req("POST", "/login", form={"email": "owner@example.com", "password": GOOD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
status, _, page = req("GET", "/apps?lang=es-MX", cookie=cookie)
check("/apps: 200 con «Apps conectadas» y la entrada activa", (200, True, True),
      (status, "<h1>Apps conectadas</h1>" in page, 'href="/apps" class="activo"' in page))
check("lista los clientes, sin hashes", (True, False),
      ("MT de prueba" in page, any(r["sha256"] in page for r in json.loads(store.read_text()))))
nav = page.split('<aside class="lateral"', 1)[1].split("</aside>", 1)[0]
check("en el menú, antes de API Tokens", True, nav.index('href="/apps"') < nav.index('href="/api-tokens"'))
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)

status, _, page = req("POST", "/apps/code", form={"csrf": csrf, "password": "mala"}, cookie=cookie)
check("generar código con contraseña mala: 400 sin código", (400, False), (status, "apps-code" in page))
os.environ.pop("PAYNANI_SMS_PUBLIC_URL", None)
status, _, page = req("POST", "/apps/code", form={"csrf": csrf, "password": GOOD}, cookie=cookie)
check("sin dirección pública: 400 con el aviso", (400, True), (status, "PAYNANI_SMS_PUBLIC_URL" in page))
os.environ["PAYNANI_SMS_PUBLIC_URL"] = "https://agente.ngrok.app/"
status, _, page = req("POST", "/apps/code", form={"csrf": csrf, "password": GOOD}, cookie=cookie)
shown = re.search(r'<code class="apps-code">([A-Z0-9]{8})</code>', page)
check("generar código: 200 con la dirección y el código", (200, True, True),
      (status, "https://agente.ngrok.app</code>" in page, shown is not None))
check("ese código empareja", "ok", owner_clients.pair(shown.group(1), "Desde la página", path=store)[0])
check("CSRF malo: 403", 403, req("POST", "/apps/code", form={"csrf": "x", "password": GOOD}, cookie=cookie)[0])

target = data["client_id"]
sent.clear()
status, _, page = req("POST", "/apps/revoke", form={"csrf": csrf, "password": GOOD, "id": target}, cookie=cookie)
check("revocar desde la página: 200 con el aviso", (200, True), (status, "App revocada" in page))
check("y el token ya no abre", "token_revoked", owner_clients.lookup(data["token"], path=store)[0])
check("correo al dueño al revocar", True, any("app revocada" in str(a) for a in sent))
status, _, _ = req("POST", "/apps/revoke", form={"csrf": csrf, "password": GOOD, "id": target}, cookie=cookie)
check("revocar otra vez: 404", 404, status)

# --- el CLI -----------------------------------------------------------------------------------
env = {**os.environ, "PAYNANI_WEB_USER": str(user_file)}
cli = [sys.executable, str(ROOT / "scripts" / "paynani"), "web"]
run = subprocess.run(cli + ["pair", "--url", "https://agente.ngrok.app"], capture_output=True, text=True, env=env)
check("`web pair --url` imprime la dirección y un código", (0, True, True),
      (run.returncode, "https://agente.ngrok.app" in run.stdout, re.search(r"\b[A-Z2-9]{8}\b", run.stdout) is not None))
run = subprocess.run(cli + ["clients"], capture_output=True, text=True, env=env)
check("`web clients` lista los clientes", (0, True), (run.returncode, "Desde la página" in run.stdout))

httpd.shutdown()
print(f"\n{passed} ok, {failed} fail")
sys.exit(1 if failed else 0)
