#!/usr/bin/env python3
"""
Tests for PaynaniWeb as a whole (PRD #434 §5 and NFR-1 to NFR-3; T10 of #435).
An assertion script, like the rest of this suite.

Recorre todas las pantallas con sesión y sin ella y comprueba en cada una lo que
el PRD pide de seguridad:

- los encabezados (CSP sin nada de fuera, `X-Frame-Options`, `nosniff`,
  `no-store`) en toda respuesta HTML;
- que ninguna página cargue algo de fuera, lleve `style=` o script en línea;
- que todo formulario POST lleve el token de la sesión;
- que el log no traiga contraseñas, consultas ni cuerpos de correo o SMS.

Y NFR-3: una lista de 50 correos o de conversaciones SMS, sobre un ledger y un
diario grandes, sale en menos de 2 segundos. Todo en una carpeta temporal y en
127.0.0.1.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import re
import sys
import tempfile
import threading
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import ledger  # noqa: E402
from paynani_lib.sms import store as sms_store  # noqa: E402
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


SECRET_PW = "secreto-de-la-web-123"
SECRET_BODY = "CUERPO-SECRETO-DEL-CORREO"
SECRET_SMS = "TEXTO-SECRETO-DEL-SMS"
SECRET_QUERY = "consulta-secreta-xyz"

tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
roster = tmp / "roster.md"
roster.write_text("| Name | Email | Type | GitHub | Phone |\n|---|---|---|---|---|\n"
                  "| Dueño | dueno@example.com | Human |  | +525511112222 |\n", encoding="utf-8")
env_path = tmp / ".env"
env_path.write_text("AGENT_EMAIL_ACCOUNT=agente@example.com\nAGENT_EMAIL_PASSWORD=x\n"
                    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com\n", encoding="utf-8")

# NFR-3: un ledger de 6 000 correos (con sus cambios de estado) y un diario de 3 000 SMS.
lifecycle = state / "lifecycle.jsonl"
with open(lifecycle, "w", encoding="utf-8") as fh:
    for i in range(6000):
        eid = f"imap:INBOX:7:{i + 1}"
        env = {"event_type": "email.received", "event_id": eid, "account": "agente@example.com", "mailbox": "INBOX",
               "uidvalidity": "7", "uid": str(i + 1), "observed_at": f"2026-10-{1 + i % 20:02d}T{i % 24:02d}:{i % 60:02d}:00Z",
               "sender": {"name": f"Persona {i}", "address": f"p{i}@example.org"}, "subject": f"Asunto {i}",
               "roster_match": i % 3 == 0, "message_id": f"<m{i + 1}@example.org>"}
        fh.write(json.dumps({"schema_version": 1, "event_id": eid, "state": "observed", "at": env["observed_at"],
                             "envelope": env}) + "\n")
        fh.write(json.dumps({"schema_version": 1, "event_id": eid, "state": "handled", "at": env["observed_at"]}) + "\n")
(state / "sent.log").write_text("2026-10-20T10:05:00Z\tto=p0@example.org\tcc=\tbcc=\tsubject=Re: Asunto 0"
                                 "\tsent-copy=skipped\tmessage-id=<s1@agente.example>\n", encoding="utf-8")
st = sms_store.Store(state)
with open(state / "events.jsonl", "w", encoding="utf-8") as fh:
    for i in range(3000):
        mid = hashlib.sha256(f"s{i}".encode()).hexdigest()
        st.save_inbox(mid, {"text": SECRET_SMS if i == 0 else f"hola {i}"})
        fh.write(json.dumps({"event_type": "sms.received", "event_id": f"sms:d:{i}",
                             "sender": {"address": f"+52550{i % 400:07d}"}, "provider_id": f"sms:{mid}",
                             "sent_at": f"2026-10-{1 + i % 20:02d}T{i % 24:02d}:00:00Z"}) + "\n")


class FakeIMAP:
    def __init__(self, env):
        pass

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def uid(self, command, uid, query):
        m = EmailMessage()
        m["From"] = f"Persona {int(uid) - 1} <p{int(uid) - 1}@example.org>"
        m["To"] = "agente@example.com"
        m["Subject"] = "Asunto"
        m["Message-ID"] = f"<m{uid}@example.org>"
        m.set_content(SECRET_BODY)
        data = m.as_bytes()
        return "OK", [(f"1 (UID {uid} BODY[]".encode(), data), b")"]

    def logout(self):
        pass


user_file = tmp / "web" / "user.json"
users.create("dueno@example.com", "Dueño", SECRET_PW, user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", ledger_path=lifecycle,
                  env_path=env_path, imap_connect=FakeIMAP, imap_uidvalidity=lambda c, m: "7",
                  state_dir=state, roster_path=roster, roster_notifier=lambda *a: None)
log_out, log_err = io.StringIO(), io.StringIO()


class CapturedSys:
    """El `sys` que ve app.py: su stdout y stderr van aquí, sin tocar los de la prueba."""
    stdout, stderr = log_out, log_err

    def __getattr__(self, name):
        return getattr(sys, name)


app.sys = CapturedSys()
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, cookie=""):
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.5"}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = f"https://{HOST}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    t0 = time.monotonic()
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    took = time.monotonic() - t0
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    out["took"] = took
    conn.close()
    return r.status, out, data


_, hdrs, _ = req("POST", "/login?" + SECRET_QUERY, form={"email": "dueno@example.com", "password": SECRET_PW})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]

pages = {
    "/login (sin sesión)": ("/login", ""),
    "/": ("/", cookie),
    "/email/main": ("/email/main?" + SECRET_QUERY, cookie),
    "un correo abierto": ("/email/main/ver?e=" + quote("imap:INBOX:7:1", safe=""), cookie),
    "un enviado abierto": ("/email/main/ver?s=" + quote("<s1@agente.example>", safe=""), cookie),
    "/messages": ("/messages", cookie),
    "una conversación": ("/messages/ver?n=" + quote("+525500000000", safe=""), cookie),
    "/roster": ("/roster", cookie),
    "/roster/editar": ("/roster/editar?cuenta=main&fila=1", cookie),
    "/roster/reglas": ("/roster/reglas?cuenta=main&fila=1", cookie),
    "/roster/reglas general": ("/roster/reglas?general=1", cookie),
    "/profile": ("/profile", cookie),
    "/profile/info": ("/profile/info", cookie),
    "/profile/password": ("/profile/password", cookie),
    "/cuentas/nueva": ("/cuentas/nueva", cookie),
    "una ruta que no existe": ("/no-existe", cookie),
}
CSP = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'"
for label, (path, ck) in pages.items():
    status, h, page = req("GET", path, cookie=ck)
    problems = []
    if h.get("content-security-policy") != CSP:
        problems.append("CSP")
    if h.get("x-frame-options") != "DENY" or h.get("x-content-type-options") != "nosniff":
        problems.append("frame/nosniff")
    if "no-store" not in h.get("cache-control", ""):
        problems.append("cache")
    if re.findall(r'(?:src|href|action)="(?:https?:)?//[^"]+"', page):
        problems.append("recurso de fuera")
    if re.search(r'\sstyle="', page):
        problems.append("style=")
    if re.search(r"<script(?![^>]*\ssrc=\"/assets/)", page):
        problems.append("script en línea")
    if re.search(r"\son[a-z]+=", page):
        problems.append("manejador on*=")
    for form in re.findall(r'<form method="post"[^>]*>(.*?)</form>', page, re.S):
        if ck and 'name="csrf"' not in form:
            problems.append("POST sin token")
    check(f"{label}: {status}, encabezados, nada de fuera, sin style ni script en línea, POST con token", [], problems)

# --- lo que nunca va al log ------------------------------------------------------------------
_, _, page = req("GET", "/email/main/ver?e=" + quote("imap:INBOX:7:1", safe=""), cookie=cookie)
check("el correo abierto sí muestra su cuerpo", True, SECRET_BODY in page)
req("POST", "/profile/password", form={"csrf": re.search(r'name="csrf" value="([^"]+)"', page).group(1),
                                       "current": SECRET_PW, "new": SECRET_PW + "x", "again": SECRET_PW + "y"},
    cookie=cookie)
req("GET", "/messages/ver?n=" + quote("+525500000000", safe=""), cookie=cookie)
logs = log_out.getvalue() + log_err.getvalue()
check("el log tiene una línea por petición", True, "GET /email/main" in logs and "POST /login" in logs)
for secret, what in ((SECRET_PW, "la contraseña"), (SECRET_QUERY, "la consulta"), (SECRET_BODY, "el cuerpo del correo"),
                     (SECRET_SMS, "el texto del SMS"), ("e=imap", "el id del correo de la consulta")):
    check(f"el log no trae {what}", False, secret in logs)

# --- NFR-3 ---------------------------------------------------------------------------------------
for label, path in (("50 correos de un ledger de 6 000", "/email/main"),
                    ("la página 60 de esos correos", "/email/main?desde=3000"),
                    ("50 conversaciones de un diario de 3 000 SMS", "/messages")):
    status, h, page = req("GET", path, cookie=cookie)
    check(f"NFR-3: {label} en menos de 2 s ({h['took']:.2f} s)", (200, True), (status, h["took"] < 2.0))

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
