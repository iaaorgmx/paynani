#!/usr/bin/env python3
"""
Tests for PaynaniWeb's Email Accounts (PRD #434 FR-13 to FR-15; T5 of #435).
An assertion script, like the rest of this suite.

La lista sale del ledger (50 por página, el más reciente primero, con su estado y
la marca del roster), y abrir un correo lo pide a un IMAP de prueba con el login de
su cuenta, verificando UID, UIDVALIDITY, From y Message-ID. El HTML se muestra
como texto. Nada sale de la máquina y no se escribe nada en el ledger.
"""
from __future__ import annotations

import http.client
import json
import re
import sys
import tempfile
import threading
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import event as ev  # noqa: E402
import ledger  # noqa: E402
from paynani_lib.web import app, auth, mail, notify, users  # noqa: E402

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
lifecycle = tmp / "state" / "lifecycle.jsonl"
lifecycle.parent.mkdir(parents=True)
env_path = tmp / ".env"
env_path.write_text("AGENT_EMAIL_ACCOUNT=agente@example.com\nAGENT_EMAIL_PASSWORD=x\n"
                    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com\n"
                    "PAYNANI_ACCOUNT_VENTAS_PASSWORD=y\n", encoding="utf-8")
accounts_file = tmp / "accounts.json"
accounts_file.write_text(json.dumps({"accounts": [
    {"id": "ventas", "email": "ventas@example.com", "imap": {"host": "imap.ventas.example", "port": 993},
     "roster": "rosters/ventas.md", "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD", "mailboxes": ["INBOX"]}]}),
    encoding="utf-8")


def envelope(event_id, account, uid, sender, subject, when, roster, account_id=None):
    out = {"schema_version": 1, "event_type": "email.received", "event_id": event_id, "source": "imap",
           "account": account, "mailbox": "INBOX", "uidvalidity": "77", "uid": str(uid), "observed_at": when,
           "sent_at": when, "sender": {"name": sender[0], "address": sender[1]}, "subject": subject,
           "roster_match": roster, "message_id": f"<m{uid}@example.com>"}
    if account_id:
        out["account_id"] = account_id
    return out


for i in range(120):
    eid = f"imap:INBOX:77:{i + 1}"
    when = f"2026-10-{1 + i // 10:02d}T{i % 10:02d}:00:00Z"
    ledger.observed(lifecycle, envelope(eid, "agente@example.com", i + 1, ("Ana", "ana@example.com"),
                                        f"Asunto {i + 1}", when, i % 2 == 0))
ledger.transition(lifecycle, "imap:INBOX:77:120", "replied")
ledger.transition(lifecycle, "imap:INBOX:77:119", "handled")
ledger.observed(lifecycle, envelope("imap:ventas:INBOX:77:5", "ventas@example.com", 5,
                                    ("Cliente <script>", "cliente@example.org"), "<b>Cotización</b>",
                                    "2026-10-20T10:00:00Z", False, account_id="ventas"))
# Un SMS en el ledger no es correo.
ev.append(lifecycle, {"schema_version": 1, "event_id": "sms:abc", "state": "observed", "at": "2026-10-20T00:00:00Z",
                      "envelope": {"event_type": "sms.received", "event_id": "sms:abc"}})
before = lifecycle.read_bytes()

# --- mail_events y page_of ---------------------------------------------------------------
rows = mail.mail_events(lifecycle, "main", {"ventas"})
check("la cuenta del agente: 120 correos", 120, len(rows))
check("el más reciente primero", "imap:INBOX:77:120", rows[0]["event_id"])
check("con su último estado", ("replied", "handled", "observed"), (rows[0]["state"], rows[1]["state"], rows[2]["state"]))
check("y la marca del roster del sobre", (False, True), (rows[0]["roster"], rows[1]["roster"]))
ventas = mail.mail_events(lifecycle, "ventas", {"ventas"})
check("ventas: solo el suyo", ["imap:ventas:INBOX:77:5"], [r["event_id"] for r in ventas])
check("el SMS no aparece en ninguna", False, any(r["event_id"].startswith("sms") for r in rows + ventas))
chunk, nxt = mail.page_of(rows, 0)
check("página 1: 50 y sigue en 50", (50, 50), (len(chunk), nxt))
chunk, nxt = mail.page_of(rows, 100)
check("página 3: 20 y no hay más", (20, None), (len(chunk), nxt))

# --- HTML a texto ---------------------------------------------------------------------------
text = mail.html_to_text('<html><head><style>x{}</style><title>t</title></head><body><p>Hola <b>Ana</b></p>'
                         '<script>alert(1)</script><img src="https://x/y.png"><p>Ver <a href="https://ex.com/a">'
                         'aquí</a> y <a href="javascript:x()">esto</a></p><ul><li>uno</li><li>dos</li></ul></body></html>')
check("HTML: sin script, estilo, título ni imágenes", (False, False, False, False),
      ("alert" in text, "x{}" in text, "\nt\n" in text, "y.png" in text))
check("HTML: el texto y la dirección del enlace, sin enlace activo", True,
      "Hola Ana" in text and "aquí (https://ex.com/a)" in text and "javascript" not in text)
check("HTML: las listas con viñeta", True, "• uno" in text and "• dos" in text)


# --- un IMAP de prueba ----------------------------------------------------------------------
def raw_message(uid, sender, subject, *, html=False, mid=None, attach=False):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "agente@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = mid or f"<m{uid}@example.com>"
    msg["Date"] = "Tue, 20 Oct 2026 10:00:00 +0000"
    if html:
        msg.set_content("<p>Hola <b>desde HTML</b></p><script>x()</script>", subtype="html")
    else:
        msg.set_content(f"Texto del correo {uid}\n<script>no se ejecuta</script>")
    if attach:
        msg.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="cotizacion.pdf")
    return msg.as_bytes()


class FakeIMAP:
    messages = {}
    logins = []
    validity = "77"

    def __init__(self, env):
        FakeIMAP.logins.append((env.get("PAYNANI_EMAIL") or env.get("AGENT_EMAIL_ACCOUNT"),
                                env.get("PAYNANI_IMAP_HOST") or env.get("AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST")))

    def select(self, mailbox, readonly=False):
        return ("OK", [b"1"]) if readonly else ("NO", [b""])

    def uid(self, command, uid, query):
        assert command == "fetch" and query == "(BODY.PEEK[])", (command, query)
        data = FakeIMAP.messages.get(uid)
        if data is None:
            return "OK", [None]
        return "OK", [(f"1 (UID {uid} BODY[] {{{len(data)}}}".encode(), data), b")"]

    def logout(self):
        pass


FakeIMAP.messages = {
    "120": raw_message(120, "Ana <ana@example.com>", "Asunto 120"),
    "119": raw_message(119, "Ana <ana@example.com>", "Asunto 119", html=True, attach=True),
    "118": raw_message(118, "Otro <otro@example.com>", "Asunto 118"),
    "117": raw_message(117, "Ana <ana@example.com>", "Asunto 117", mid="<distinto@example.com>"),
    "5": raw_message(5, "cliente@example.org", "Cotización"),
}

user_file = tmp / "web" / "user.json"
users.create("dueno@example.com", "Dueño", "una-contraseña-larga", user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=accounts_file, ledger_path=lifecycle,
                  env_path=env_path, imap_connect=FakeIMAP, imap_uidvalidity=lambda conn, mb: FakeIMAP.validity,
                  state_dir=tmp / "state")
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
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


status, hdrs, _ = req("POST", "/login", form={"email": "dueno@example.com", "password": "una-contraseña-larga"})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


def get(path):
    return req("GET", path, cookie=cookie)


status, _, page = get("/email/main")
check("la lista: 200", 200, status)
items = re.findall(r'<li class="correo-in"><a href="(/email/main/ver\?e=[^"]+)"', page)
check("50 correos en la primera página", 50, len(items))
check("el primero es el más reciente", "/email/main/ver?e=" + quote("imap:INBOX:77:120", safe=""), items[0])
check("dice cuántos son", True, "120 correos" in page)
check("el estado respondido y la marca del roster", True,
      'estado-replied">respondido' in page and 'class="marca-roster"' in page)
check("«Ver más» a la siguiente página", True, 'href="/email/main?desde=50"' in page)
status, _, page = get("/email/main?desde=100")
check("la última página: 20 y sin «Ver más»", (20, False),
      (len(re.findall(r'<li class="correo-in"><a href="/email/main/ver', page)), "desde=" in page))
status, _, page = get("/email/main?desde=abc")
check("un desde que no es número es 0", 50, len(re.findall(r'<li class="correo-in"><a href="/email/main/ver', page)))
status, _, page = get("/email/ventas")
check("ventas: su correo, con el asunto y el nombre escapados", (1, True, False),
      (len(re.findall(r'<li class="correo-in"><a href="/email/ventas/ver', page)), "&lt;b&gt;Cotización&lt;/b&gt;" in page,
       "<script>" in page))
status, _, _ = get("/email/nadie")
check("una cuenta que no existe: 404", 404, status)

# --- abrir un correo -----------------------------------------------------------------------------
FakeIMAP.logins.clear()
status, _, page = get("/email/main/ver?e=" + quote("imap:INBOX:77:120", safe=""))
check("abrir uno: 200 con su texto", (200, True), (status, "Texto del correo 120" in page))
check("el texto escapado: un <script> del cuerpo no es marcado", (True, False),
      ("&lt;script&gt;no se ejecuta" in page, "<script>no se ejecuta" in page))
check("con el login de la cuenta del agente", [("agente@example.com", "imap.example.com")], FakeIMAP.logins)
check("De, Para y el asunto", True, "ana@example.com" in page and "agente@example.com" in page and "Asunto 120" in page)
check("dice que solo se muestra (FR-15)", True, "Solo se muestra" in page)
check("y su conversación, sola: no hay otro correo con ese asunto y esa persona", True, "No hay más correos en esta conversación" in page)
status, _, page = get("/email/main/ver?e=" + quote("imap:INBOX:77:119", safe=""))
check("un correo en HTML: el texto, el aviso y el adjunto nombrado", (200, True, True, True, False),
      (status, "Hola desde HTML" in page, "venía en HTML" in page, "cotizacion.pdf" in page, "x()" in page))
FakeIMAP.logins.clear()
status, _, page = get("/email/ventas/ver?e=" + quote("imap:ventas:INBOX:77:5", safe=""))
check("un correo de ventas, de alguien fuera del roster, se lee (Q-T5-2)", (200, True),
      (status, "Texto del correo 5" in page))
check("con el login de ventas, nunca el del agente", [("ventas@example.com", "imap.ventas.example")], FakeIMAP.logins)

for uid, code, label in (("118", "remitente", "From distinto"), ("117", "Message-ID", "Message-ID distinto"),
                         ("116", "ya no está", "el UID ya no está")):
    status, _, page = get("/email/main/ver?e=" + quote(f"imap:INBOX:77:{uid}", safe=""))
    check(f"{label}: 502 y lo dice, sin cuerpo", (502, True, False),
          (status, code in page, f"Texto del correo {uid}" in page))
FakeIMAP.validity = "78"
status, _, page = get("/email/main/ver?e=" + quote("imap:INBOX:77:120", safe=""))
check("UIDVALIDITY cambió: no se abre", (502, True, False), (status, "UIDVALIDITY" in page, "Texto del correo" in page))
FakeIMAP.validity = "77"
status, _, page = get("/email/ventas/ver?e=" + quote("imap:INBOX:77:120", safe=""))
check("un correo de otra cuenta por la ruta de ventas: 404", (404, True), (status, "no es de esta cuenta" in page))


def refuse(env):
    raise SystemExit(1)


ctx.imap_connect = refuse
status, _, page = get("/email/main/ver?e=" + quote("imap:INBOX:77:120", safe=""))
check("login rechazado: 502 y lo dice", (502, True), (status, "rechazó el acceso" in page))


def unreachable(env):
    raise OSError("sin red")


ctx.imap_connect = unreachable
status, _, page = get("/email/main/ver?e=" + quote("imap:INBOX:77:120", safe=""))
check("sin red: 502 con el tipo de error y nada más", (502, True, False), (status, "OSError" in page, "sin red" in page))
ctx.imap_connect = FakeIMAP
accounts_file.write_text('{"accounts": []}', encoding="utf-8")
status, _, page = get("/email/ventas")
check("una cuenta que se quitó de accounts.json ya no se lista", 404, status)

check("abrir correos no escribió nada en el ledger (FR-15)", before, lifecycle.read_bytes())
httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
