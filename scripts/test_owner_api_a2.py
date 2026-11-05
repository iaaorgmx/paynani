#!/usr/bin/env python3
"""
A2 #720 (PaynaniWebMT#2 FR-A5, A8, A9): el marco de `POST /api/owner`.

Autenticación sólo con `pw_` en el encabezado, 120 llamadas por minuto, bloqueo,
bitácora, `GetInstance`, `GetChanges` sin huecos ni duplicados, `Disconnect`, y las
subidas y bajadas de archivos con una acción de prueba registrada como lo harán A3 y A4.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import api_tokens, app, notify, owner_api, owner_changes, owner_clients, users  # noqa: E402

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
state = tmp / "state"
(state / "sms").mkdir(parents=True)
(state / "webchat").mkdir()
roster = tmp / "roster.md"
roster.write_text("| Nombre | Correo |\n|---|---|\n")
user_file = tmp / "web" / "user.json"
users.create("owner@example.com", "Owner", "una-contraseña-larga", user_file)
store = owner_clients.clients_path(user_file)
_, (token, client) = owner_clients.pair(owner_clients.new_code(path=store), "MT", app_name="PaynaniWebMT",
                                        app_version="0.1.0", path=store)
agent_token, _ = api_tokens.create("agente", path=api_tokens.path_for(user_file))


# Una acción de prueba, registrada como lo harán A3 y A4.
@owner_api.action("TestEcho")
def _echo(call):
    return {"files": [{"field": f["field"], "name": f["name"], "size": len(f["data"])} for f in call.files],
            "note": call.text("note"), "client_id": call.client["client_id"], "has_hash": "sha256" in call.client}


@owner_api.action("TestFile")
def _file(call):
    return owner_api.FileResult('fo"to/../x.html', b"<script>alert(1)</script>")


@owner_api.action("TestSensitive", sensitive=True)
def _sensitive(call):
    return {"origin": call.origin()}


sent = []
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: sent.append(a), log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "none.json", state_dir=state,
                  roster_path=roster)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def call(body=None, *, tok=None, ip="198.51.100.1", raw=None, ctype="application/json", path="/api/owner",
         binary=False):
    headers = {"Host": "agente.ngrok.app", "X-Forwarded-For": ip, "Content-Type": ctype}
    if tok is not False:
        headers["Authorization"] = "Bearer " + (tok or token)
    payload = raw if raw is not None else json.dumps(body or {}).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", path, body=payload, headers=headers)
    r = conn.getresponse()
    data = r.read()
    out = {k.lower(): v for k, v in r.getheaders()}
    conn.close()
    if binary:
        return r.status, out, data
    return r.status, out, json.loads(data)


# --- autenticación -----------------------------------------------------------------------------
status, hdrs, body = call({"action": "GetInstance"})
check("GetInstance: 200 success con request_id en cuerpo y encabezado", (200, "success", True),
      (status, body["result"], body["request_id"] == hdrs["x-request-id"]))
check("versión, agente, dueño, canales e idiomas", (True, "agente@example.com", "owner@example.com", True, True),
      ("version" in body["paynani"], body["agent"]["email"], body["owner"]["email"],
       body["channels"]["sms"] and body["channels"]["webchat"] and body["channels"]["mail"],
       "es-MX" in body["languages"]))
check("el cliente sale sin el hash del token", (client["client_id"], False),
      (body["client"]["client_id"], "sha256" in body["client"]))
check("un token de agente pn_ no entra aquí", (401, "invalid_token"),
      (lambda r: (r[0], r[2]["code"]))(call({"action": "GetInstance"}, tok=agent_token)))
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
conn.request("POST", "/api/agent", body=json.dumps({"action": "GetTokenInfo"}),
             headers={"Host": "agente.ngrok.app", "Content-Type": "application/json", "Authorization": "Bearer " + token})
r = conn.getresponse()
check("y un pw_ no entra en /api/agent", (401, "invalid_token"), (r.status, json.loads(r.read())["code"]))
conn.close()
check("sin token: 401", 401, call({"action": "GetInstance"}, tok=False)[0])
check("token en la URL: 401", 401, call({"action": "GetInstance"}, path="/api/owner?token=" + token)[0])
check("token en el cuerpo: 400", 400, call({"action": "GetInstance", "api_token": token})[0])
check("acción desconocida: 400 invalid_action", "invalid_action", call({"action": "Nada"})[2]["code"])
check("form-urlencoded: 415", 415, call(raw=b"action=GetInstance", ctype="application/x-www-form-urlencoded")[0])
check("JSON roto: 400", 400, call(raw=b"{", ctype="application/json")[0])
for _ in range(10):
    call({"action": "GetInstance"}, tok="pw_" + "x" * 30, ip="198.51.100.66")
check("10 fallos bloquean la dirección: 429", (429, "too_many_attempts"),
      (lambda r: (r[0], r[2]["code"]))(call({"action": "GetInstance"}, ip="198.51.100.66")))
check("otra dirección sigue", 200, call({"action": "GetInstance"}, ip="198.51.100.67")[0])
check("last_used_at queda guardado", True, owner_clients.lookup(token, path=store)[1]["last_used_at"] is not None)

limits = ctx.api_limits
for _ in range(owner_api.RATE_PER_MINUTE):
    assert limits.admit_call("limit-test", owner_api.RATE_PER_MINUTE) == 0
check("120 por minuto por cliente (FR-A5)", True, limits.admit_call("limit-test", owner_api.RATE_PER_MINUTE) > 0)
check("el agente sigue en 60", True, all(limits.admit_call("agent-test") == 0 for _ in range(60))
      and limits.admit_call("agent-test") > 0)

# --- archivos (FR-A9) ----------------------------------------------------------------------------
boundary = uuid.uuid4().hex
def multipart(fields, files):
    out = b""
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for field, name, data in files:
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
    return out + f"--{boundary}--\r\n".encode()

status, _, body = call(raw=multipart({"action": "TestEcho", "note": "hola"}, [("file", "a.jpg", b"x" * 1000),
                                                                              ("file", "b.pdf", b"y" * 10)]),
                       ctype=f"multipart/form-data; boundary={boundary}")
check("multipart: la acción recibe los campos y los archivos", (200, "hola", [1000, 10]),
      (status, body.get("note"), [f["size"] for f in body.get("files", [])]))
check("call.client sin hash", (client["client_id"], False), (body["client_id"], body["has_hash"]))
big = b"z" * (20 * 1024 * 1024 + 1)
status, _, body = call(raw=multipart({"action": "TestEcho"}, [("file", "big.bin", big)]),
                       ctype=f"multipart/form-data; boundary={boundary}")
check("un archivo de más de 20 MB: 413", (413, "body_too_large"), (status, body["code"]))
status, hdrs, data = call({"action": "TestFile"}, binary=True)
check("bajada: octet-stream, attachment con nombre limpio, sandbox y request id", (200, True, True, True, True),
      (status, hdrs["content-type"] == "application/octet-stream", hdrs["content-disposition"].startswith("attachment"),
       '"' not in hdrs["content-disposition"].split("filename=", 1)[1].strip('"').split('";')[0],
       "sandbox" in hdrs.get("content-security-policy", "") and bool(hdrs.get("x-request-id"))))
check("el cuerpo son los bytes, no JSON", b"<script>alert(1)</script>", data)

# --- acciones delicadas (FR-A10) -----------------------------------------------------------------
status, hdrs, body = call({"action": "TestSensitive"})
check("delicada: sin contraseña de PaynaniWeb, con el nombre del cliente", (200, "desde PaynaniWebMT (MT)"),
      (status, body["origin"]))
log = (state / "api_security.jsonl").read_text()
check("bitácora: owner_sensitive con el prefijo pw_ y sin token", (True, True, False),
      ('"owner_sensitive"' in log, token[:11] in log, token in log))

# --- GetChanges (FR-A8) --------------------------------------------------------------------------
def changes(cursor=""):
    status, _, body = call({"action": "GetChanges", "cursor": cursor})
    assert status == 200, body
    return body

first = changes()
check("sin cursor: todas las áreas y reset", (True, True), (first["reset"], set(owner_changes.AREAS) <= set(first["changed"])))
again = changes(first["cursor"])
check("sin cambios: vacío y rápido", ([], False), (again["changed"], again["reset"]))
check("un cursor que no se entiende: reset", True, changes("c1.no-es-base64!!")["reset"])

events = state / "events.jsonl"
with events.open("a") as f:
    f.write(json.dumps({"event_type": "email.received", "account": "owner@example.com"}) + "\n")
    f.write(json.dumps({"event_type": "sms.received", "account": "sms:d_1"}) + "\n")
    f.write('{"event_type": "email.received", "account": "a medias')       # línea sin terminar
step = changes(again["cursor"])
check("mail por cuenta y sms desde events.jsonl, más el dashboard",
      ["dashboard", "mail:owner@example.com", "sms"], step["changed"])
with events.open("a") as f:
    f.write('"}\n')
step2 = changes(step["cursor"])
check("la línea a medias sale cuando se termina, una sola vez", ["dashboard", "mail:a medias"], step2["changed"])
check("y no se repite", [], changes(step2["cursor"])["changed"])

time.sleep(0.01)
(state / "webchat" / "messages.jsonl").write_text('{"id": 1}\n')
roster.write_text(roster.read_text() + "| Ana | ana@example.com |\n")
step3 = changes(step2["cursor"])
check("webchat y roster por sus archivos", ["dashboard", "roster", "webchat"], step3["changed"])
check("sin duplicados", [], changes(step3["cursor"])["changed"])
(state / "webchat" / "lock").write_text("x")
check("un candado no cuenta como cambio", [], changes(step3["cursor"])["changed"])
(state / "sent.log").write_text("x\n")
check("sent.log cambia todas las cuentas de correo", ["dashboard", "mail:*"], changes(step3["cursor"])["changed"])

events.rename(state / "events.jsonl.1")
events.write_text(json.dumps({"event_type": "email.received", "account": "otra@example.com"}) + "\n")
rot = changes(step3["cursor"])
check("events.jsonl rotó: todas las cuentas y la línea nueva", True,
      {"mail:*", "mail:otra@example.com"} <= set(rot["changed"]))

# --- Disconnect ----------------------------------------------------------------------------------
sent.clear()
status, _, body = call({"action": "Disconnect"})
check("Disconnect: 200 y el cliente queda revocado", (200, "token_revoked"),
      (status, owner_clients.lookup(token, path=store)[0]))
check("correo al dueño", True, any("app desconectada" in str(a) for a in sent))
check("después, el token da 401 token_revoked", (401, "token_revoked"),
      (lambda r: (r[0], r[2]["code"]))(call({"action": "GetInstance"}, ip="198.51.100.90")))

httpd.shutdown()
print(f"\n{passed} ok, {failed} fail")
sys.exit(1 if failed else 0)
