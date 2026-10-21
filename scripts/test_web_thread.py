#!/usr/bin/env python3
"""
Tests for Email Accounts as a webmail in PaynaniWeb (PRD #434 FR-13 and FR-14;
#435, Julian's Q44 = No): one list per account with what it received and what it
sent, and, when one is opened, only its conversation. An assertion script, like
the rest of this suite.

Lo enviado sale de `state/sent.log`. La conversación es el mismo asunto sin
`Re:`/`Fw:` y la misma otra persona, dentro de la cuenta. El texto de un enviado
se pide a Enviados por Message-ID con un IMAP de prueba; sin copia, la web lo dice.
"""
from __future__ import annotations

import http.client
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

import ledger  # noqa: E402
from paynani_lib.web import app, auth, mail, notify, thread, users  # noqa: E402

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
state.mkdir()
sent_log = state / "sent.log"
sent_log.write_text("\n".join([
    "2026-10-20T10:05:00Z\tto=ana@example.com\tcc=\tbcc=\tsubject=Re: Cotización\tsent-copy=saved\tmessage-id=<r1@agente.example>",
    "2026-10-20T10:20:00Z\tto=ana@example.com\tcc=jefe@example.com\tbcc=archivo@example.com\tsubject=RE: cotización\tsent-copy=skipped\tmessage-id=<r2@agente.example>",
    "2026-10-20T11:30:00Z\tto=beto@example.com\tcc=\tbcc=\tsubject=Re: Cotización\tmessage-id=<otro-destino@agente.example>",
    "2026-10-20T11:40:00Z\tto=jefe@example.com\tcc=Ana <ana@example.com>\tbcc=\tsubject=Fw: Cotización\tmessage-id=<por-cc@agente.example>",
    "2026-10-20T12:00:00Z\tto=ana@example.com\tcc=\tbcc=\tsubject=Re: Cotización\tmessage-id=<de-ventas@ventas.example>\taccount=ventas",
    "2026-10-20T12:30:00Z\tto=ana@example.com\tcc=\tbcc=\tsubject=Otra cosa <b>\tmessage-id=<otro-hilo@agente.example>",
    "2026-10-20T12:40:00Z\tto=ana@example.com\tcc=\tbcc=\tsubject=\tmessage-id=<sin-asunto@agente.example>",
    "2026-10-20T12:30:00Z\tto=ana@example.com\tcc=\tbcc=\tsubject=Otra cosa <b>\tmessage-id=<otro-hilo@agente.example>",
    "línea rota sin campos",
]) + "\n", encoding="utf-8")

# --- el registro, la lista y la conversación ------------------------------------------------
recs = thread.parse_sent_log(sent_log)
check("parse_sent_log: las 8 líneas con message-id, sin la rota", 8, len(recs))
check("con sus campos (sent-copy no estorba)", ("<r1@agente.example>", "archivo@example.com", "ventas"),
      (recs[0]["message-id"], recs[1]["bcc"], recs[4]["account"]))
check("sin sent.log no hay envíos", [], thread.parse_sent_log(tmp / "no-existe.log"))
main_sent = thread.sent_rows(recs, "main")
check("sent_rows de main: sin el de ventas y sin repetir un Message-ID", 6, len(main_sent))
check("sent_rows de ventas: solo el suyo", ["<de-ventas@ventas.example>"],
      [r["message_id"] for r in thread.sent_rows(recs, "ventas")])

received = [
    {"event_id": "imap:INBOX:7:1", "sender_name": "Ana", "sender_address": "ana@example.com", "subject": "Cotización",
     "observed_at": "2026-10-20T10:00:00Z", "roster": True, "state": "replied"},
    {"event_id": "imap:INBOX:7:2", "sender_name": "Ana", "sender_address": "ANA@example.com", "subject": "Re: Cotización",
     "observed_at": "2026-10-20T11:00:00Z", "roster": True, "state": "handled"},
    {"event_id": "imap:INBOX:7:3", "sender_name": "Beto", "sender_address": "beto@example.com", "subject": "Cotización",
     "observed_at": "2026-10-20T11:10:00Z", "roster": False, "state": "observed"},
]
rows = thread.mailbox(received, main_sent)
check("mailbox: recibidos y enviados mezclados, el más reciente primero",
      ["out", "out", "out", "out", "in", "in", "out", "out", "in"], [r["kind"] for r in rows])
check("... por hora", sorted((r["at"] for r in rows), reverse=True), [r["at"] for r in rows])

first = next(r for r in rows if r.get("event_id") == "imap:INBOX:7:1")
convo = thread.conversation(rows, first, own="agente@example.com")
check("la conversación del primero: mismo asunto y Ana, recibidos y enviados, en orden",
      ["imap:INBOX:7:1", "<r1@agente.example>", "<r2@agente.example>", "imap:INBOX:7:2", "<por-cc@agente.example>"],
      [r.get("event_id") or r["message_id"] for r in convo])
check("no entran Beto (otra persona), ventas (otra cuenta) ni «Otra cosa»", True,
      not {r.get("event_id") or r["message_id"] for r in convo}
      & {"imap:INBOX:7:3", "<otro-destino@agente.example>", "<de-ventas@ventas.example>", "<otro-hilo@agente.example>"})
r2 = next(r for r in rows if r.get("message_id") == "<r2@agente.example>")
check("abrir un enviado da la misma conversación, más lo de jefe@ (estaba en su Cc)",
      True, {r.get("event_id") or r["message_id"] for r in convo} <= {r.get("event_id") or r["message_id"]
                                                                       for r in thread.conversation(rows, r2)})
lonely = next(r for r in rows if r.get("message_id") == "<sin-asunto@agente.example>")
check("un correo sin asunto es una conversación de uno", [lonely], thread.conversation(rows, lonely))
check("la dirección de la cuenta no cuenta como la otra persona", set(),
      thread.people({"kind": "out", "to": "agente@example.com", "cc": ""}, own="agente@example.com"))
check("norm_subject", ("cotización", "cotización", ""),
      (thread.norm_subject("RE: Fw:  Cotización"), thread.norm_subject("rv: res: cotización"), thread.norm_subject("")))


# --- Enviados -----------------------------------------------------------------------------------
def message(mid, text):
    m = EmailMessage()
    m["From"] = "agente@example.com"
    m["To"] = "ana@example.com"
    m["Subject"] = "Re: Cotización"
    m["Message-ID"] = mid
    m.set_content(text)
    return m.as_bytes()


def inbox_message(uid):
    m = EmailMessage()
    m["From"] = "Ana <ana@example.com>"
    m["To"] = "agente@example.com"
    m["Subject"] = "Cotización" if uid == "1" else "Re: Cotización"
    m["Message-ID"] = "<orig@example.com>" if uid == "1" else "<segundo@example.com>"
    m["Date"] = "Tue, 20 Oct 2026 10:00:00 +0000" if uid == "1" else "Tue, 20 Oct 2026 11:00:00 +0000"
    m.set_content("¿Me cotizan 40 mesas?" if uid == "1" else
                  "Gracias, ¿y 50?\n\n-- \nAna\n\nOn Tue, Oct 20, 2026 at 10:05 AM Agente <agente@example.com>\nwrote:\n\n"
                  "> Sí, Ana: 40 mesas a 3000.\n")
    return m.as_bytes()


class FakeIMAP:
    """INBOX con los dos correos de Ana, y Enviados (marcado \\Sent) con copia de r1 solamente."""
    selected = None
    sent_folder = b'(\\HasNoChildren \\Sent) "/" "Enviados"'
    connections = 0
    queries: list = []

    def __init__(self, env):
        FakeIMAP.connections += 1

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', FakeIMAP.sent_folder]

    def select(self, mailbox, readonly=False):
        FakeIMAP.selected = mailbox
        return ("OK", [b"1"]) if readonly else ("NO", [b""])

    def uid(self, command, *args):
        if command == "search":
            mid = args[-1]
            return "OK", [b"9" if mid == "<r1@agente.example>" and FakeIMAP.selected == '"Enviados"' else b""]
        uids, query = args
        FakeIMAP.queries.append(query)
        out = []
        for uid in uids.split(","):
            if FakeIMAP.selected == "INBOX":
                data = inbox_message(uid)
            else:
                data = message("<r1@agente.example>", "Sí, Ana: 40 mesas a <b>3000</b>.")
            out += [(f"{len(out) + 1} (UID {uid} BODY[]".encode(), data), b")"]
        return "OK", out

    def logout(self):
        pass


texts = thread.fetch_texts({}, ["<r1@agente.example>", "<r2@agente.example>", "no-es-id"], connect=FakeIMAP)
check("fetch_texts: el texto de la copia que existe, nada de la que no", (["<r1@agente.example>"], True),
      (list(texts), "40 mesas" in texts.get("<r1@agente.example>", "")))
check("buscó en la carpeta marcada \\Sent", '"Enviados"', FakeIMAP.selected)
FakeIMAP.sent_folder = b'(\\HasNoChildren) "/" "Sent Items"'
thread.fetch_texts({}, ["<r1@agente.example>"], connect=FakeIMAP)
check("sin marca \\Sent, por su nombre conocido", '"Sent Items"', FakeIMAP.selected)
FakeIMAP.sent_folder = b'(\\HasNoChildren \\Sent) "/" "Enviados"'


def broken(env):
    raise OSError("sin red")


check("si el servidor no responde, sin textos y sin caerse", {}, thread.fetch_texts({}, ["<r1@agente.example>"], connect=broken))

# --- en la página ---------------------------------------------------------------------------------
lifecycle = state / "lifecycle.jsonl"
for uid, subject, at, mid in (("1", "Cotización", "2026-10-20T10:00:00Z", "<orig@example.com>"),
                              ("2", "Re: Cotización", "2026-10-20T11:00:00Z", "<segundo@example.com>")):
    ledger.observed(lifecycle, {"event_type": "email.received", "event_id": f"imap:INBOX:7:{uid}",
                                "account": "agente@example.com", "mailbox": "INBOX", "uidvalidity": "7", "uid": uid,
                                "observed_at": at, "sender": {"name": "Ana", "address": "ana@example.com"},
                                "subject": subject, "roster_match": True, "message_id": mid})
env_path = tmp / ".env"
env_path.write_text("AGENT_EMAIL_ACCOUNT=agente@example.com\nAGENT_EMAIL_PASSWORD=x\n"
                    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com\nPAYNANI_FROM_NAME=Agente Paynani\n",
                    encoding="utf-8")
user_file = tmp / "web" / "user.json"
users.create("dueno@example.com", "Dueño", "una-contraseña-larga", user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", ledger_path=lifecycle,
                  env_path=env_path, imap_connect=FakeIMAP, imap_uidvalidity=lambda c, m: "7", state_dir=state,
                  roster_path=tmp / "roster.md")
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def req(method, path, *, form=None, cookie=""):
    h = {"Host": "agente.ngrok.app", "X-Forwarded-For": "203.0.113.5"}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = "https://agente.ngrok.app"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


_, hdrs, _ = req("POST", "/login", form={"email": "dueno@example.com", "password": "una-contraseña-larga"})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]

status, _, page = req("GET", "/email/main", cookie=cookie)
kinds = re.findall(r'<li class="correo-(in|out)">', page)
check("la lista: 200, 2 recibidos y 6 enviados, mezclados", (200, 2, 6), (status, kinds.count("in"), kinds.count("out")))
check("dice cuántos son, contando los enviados", True, "8 correos" in page)
check("un enviado: la flecha de salida, «Para:» y «Enviado»", True,
      'class="dir dir-out"' in page and "Para: ana@example.com" in page and 'class="estado estado-sent">Enviado' in page)
check("un recibido: la flecha de entrada, «De:», su estado y la marca del roster", True,
      'class="dir dir-in"' in page and "De: Ana" in page and 'estado-observed' in page and 'class="marca-roster"' in page)
check("el enlace de un enviado va por su Message-ID", True,
      'href="/email/main/ver?s=' + quote("<r1@agente.example>", safe="") + '#m-' in page)
check("el asunto de un enviado va escapado", (True, False), ("Otra cosa &lt;b&gt;" in page, "Otra cosa <b>" in page))
check("a todo lo ancho, con la cabecera De / Para, Asunto, Fecha y Estado (como Orders del /dash)", True,
      '<main class="panel panel-ancho">' in page and '<li class="correos-cabecera" aria-hidden="true"><span>De / Para</span>'
      '<span>Asunto</span><span>Fecha</span><span>Estado</span>' in page)
css = (ROOT / "scripts" / "paynani_lib" / "assets" / "web.css").read_text(encoding="utf-8")
webmail_css = css[css.index("/* Email Accounts como webmail (T5)"):]
check("el CSS del webmail no toca .hilo, que es la conversación de SMS de Messages", False, ".hilo" in webmail_css)
status, _, page = req("GET", "/email/ventas", cookie=cookie)
check("una cuenta que no existe sigue siendo 404", 404, status)

# --- abrir un recibido: todo el hilo como en Gmail (PRD #455) ------------------------------
from paynani_lib.web import mail_pages  # noqa: E402

FakeIMAP.connections = 0
FakeIMAP.queries = []
status, _, page = req("GET", "/email/main/ver?e=" + quote("imap:INBOX:7:1", safe=""), cookie=cookie)
check("el recibido abierto: 200", 200, status)
check("una sola conexión para todo el hilo (4.3)", 1, FakeIMAP.connections)
check("... y solo BODY.PEEK[]: nada queda leído", True, bool(FakeIMAP.queries) and set(FakeIMAP.queries) == {"(BODY.PEEK[])"})
check("los 5 mensajes, una vez cada uno (4.1)", 5, page.count('<li id="m-'))
order = [page.index(t) for t in ("¿Me cotizan 40 mesas?", "Sí, Ana: 40 mesas a", "Gracias, ¿y 50?")]
check("... del más viejo al más nuevo", sorted(order), order)
check("el otro recibido trae su cuerpo completo, no un enlace", (True, False), ("Gracias, ¿y 50?" in page, ">Abrir<" in page))
opened = mail_pages.anchor({"kind": "in", "event_id": "imap:INBOX:7:1"})
check("el abierto va con borde y su id es el ancla (#m-…)", (1, True),
      (page.count('class="mensaje abierto"'), f'<li id="{opened}" class="mensaje abierto">' in page))
check("el asunto una sola vez, sin Re:", (1, True, False),
      (page.count('<h2 class="asunto-correo">'), '<h2 class="asunto-correo">Cotización</h2>' in page, "Re: Cotización</h2>" in page))
check("todos con el mismo formato: avatar, nombre y «para …» (4.2)", (5, 3, 2, 5),
      (page.count('class="avatar-mensaje'), page.count("avatar-agente"), page.count("avatar-contacto"), page.count('class="para"')))
check("a un recibido: «para mí»", True, '<div class="para">para mí</div>' in page)
check("un enviado sin copia: Para y Cc del registro", True, "para ana@example.com · cc jefe@example.com" in page)
check("... y el nombre con el que firma send.sh (PAYNANI_FROM_NAME), no la dirección (revisión de #459)", (True, True),
      ("<b>Agente Paynani</b> <span class=\"direccion\">&lt;agente@example.com&gt;</span>" in page,
       'avatar-agente" aria-hidden="true">AP<' in page))
check("la hora va en <time datetime> con la fecha completa en title (T4)", True,
      '<time datetime="2026-10-20T10:00:00Z" title="' in page)
check("cada recibido conserva su estado y la marca del roster junto a la hora (4.7)", True,
      'class="estado estado-observed"' in page and 'class="marca-roster"' in page)
check("el enviado con copia trae su texto, escapado", (True, False),
      ("40 mesas a &lt;b&gt;3000&lt;/b&gt;." in page, "<b>3000</b>" in page))
check("el enviado sin copia dice por qué, dentro de su mensaje", True,
      '<p class="quiet nota sin-copia">El servidor no guardó copia de este envío en Enviados.</p>' in page)
check("el texto citado plegado detrás de «•••», con <details> (4.5)", True,
      '<details class="cita"><summary' in page and ">•••</summary>" in page and "&gt; Sí, Ana: 40 mesas a 3000." in page)
check("... y la firma a la vista, fuera de la cita", True, page.index("-- \nAna") < page.index('<details class="cita">'))
for gone in ("Conversación", "correos de esta cuenta con el mismo asunto", "Solo se muestra", "este correo", 'class="sobre"'):
    check(f"sin «{gone}» (4.6)", False, gone in page)
check("ni Beto ni «Otra cosa» en el hilo", (False, False), ("beto@" in page, "Otra cosa" in page))
check("un correo abierto no va a todo lo ancho", False, "panel-ancho" in page)
status, _, listing = req("GET", "/email/main", cookie=cookie)
check("la lista enlaza cada correo con su ancla, para que la página baje a él", True,
      f'href="/email/main/ver?e={quote("imap:INBOX:7:1", safe="")}#{opened}"' in listing)

# --- abrir otro del mismo hilo, y un enviado -----------------------------------------------
status, _, page = req("GET", "/email/main/ver?e=" + quote("imap:INBOX:7:2", safe=""), cookie=cookie)
check("abrir el segundo: el mismo hilo, ahora marcado él", (200, 5, True),
      (status, page.count('<li id="m-'), f'<li id="{mail_pages.anchor({"kind": "in", "event_id": "imap:INBOX:7:2"})}" class="mensaje abierto">' in page))
status, _, page = req("GET", "/email/main/ver?s=" + quote("<r1@agente.example>", safe=""), cookie=cookie)
check("un enviado abierto: el mismo hilo, él marcado, con su texto", (200, 5, True, True),
      (status, page.count('<li id="m-'), "mensaje abierto" in page, "40 mesas a &lt;b&gt;3000" in page))
status, _, page = req("GET", "/email/main/ver?s=" + quote("<r2@agente.example>", safe=""), cookie=cookie)
check("uno sin copia: 200 y la razón, no un error de página", (200, True), (status, "no guardó copia de este envío" in page))
status, _, page = req("GET", "/email/main/ver?s=" + quote("<sin-asunto@agente.example>", safe=""), cookie=cookie)
check("uno sin asunto: solo él", (200, True, 1), (status, "(sin asunto)" in page, page.count('<li id="m-')))
for label, mid in (("que no está en sent.log", "<nadie@agente.example>"), ("de otra cuenta", "<de-ventas@ventas.example>")):
    status, _, _ = req("GET", "/email/main/ver?s=" + quote(mid, safe=""), cookie=cookie)
    check(f"un Message-ID {label}: 404", 404, status)
status, _, _ = req("GET", "/email/main/ver?s=" + quote("<r1@agente.example>", safe=""))
check("sin sesión: a /login", 303, status)


# --- el nombre de la cuenta para lo enviado, como lo firma send.sh ------------------------
import json  # noqa: E402

accounts_json = tmp / "accounts-nombre.json"
accounts_json.write_text(json.dumps({"schema_version": 1, "accounts": [
    {"id": "ventas", "email": "ventas@example.com", "from_name": "Ventas Dominio", "imap": {"host": "imap.example.com", "port": 993},
     "smtp": {"host": "smtp.example.com", "port": 465}, "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD",
     "roster": "rosters/ventas.md", "mailboxes": ["INBOX"], "enabled": True}]}), encoding="utf-8")
check("sender_name: PAYNANI_FROM_NAME para la del agente, from_name de accounts.json para las demás",
      ("Agente Paynani", "Ventas Dominio", ""),
      (mail.sender_name("main", accounts_json, env_path), mail.sender_name("ventas", accounts_json, env_path),
       mail.sender_name("nadie", accounts_json, env_path)))

# --- hilos largos: con más de 10, los del medio plegados (4.8) ---------------------------
def fake_in(i):
    return {"kind": "in", "event_id": f"imap:INBOX:7:{100 + i}", "sender_name": "Ana", "sender_address": "ana@example.com",
            "subject": "Re: Largo", "at": f"2026-10-20T{8 + i:02d}:00:00Z", "state": "handled", "roster": True}


long_convo = [fake_in(i) for i in range(12)]
loaded = {r["event_id"]: {"message": {"from": "Ana <ana@example.com>", "to": "agente@example.com", "cc": "",
                                      "date": r["at"], "text": f"cuerpo {i}", "truncated": False, "source": "plain",
                                      "attachments": []}} for i, r in enumerate(long_convo)}
html = mail_pages.thread_page("main", long_convo[-1], long_convo, loaded, own="agente@example.com")
check("12 mensajes, el abierto al final: 2 + 3 a la vista y 7 en «7 mensajes más»", (1, True, 12),
      (html.count('<li class="plegados">'), "7 mensajes más</summary>" in html, html.count('<li id="m-')))
visible = html.split('<li class="plegados">')[0] + html.split("</details></li>")[-1]
check("... los dos primeros y los tres últimos fuera del pliegue", True,
      all(f"cuerpo {i}<" in visible for i in (0, 1, 9, 10, 11)) and "cuerpo 5<" not in visible)
html = mail_pages.thread_page("main", long_convo[6], long_convo, loaded, own="agente@example.com")
check("el abierto en medio siempre se ve: dos pliegues, de 4 y de 2", (2, True, True),
      (html.count('<li class="plegados">'), "4 mensajes más</summary>" in html, "2 mensajes más</summary>" in html))
check("... y el abierto queda fuera de ellos", True,
      'class="mensaje abierto"' in html.split('<li class="plegados">')[1].split("</details></li>")[-1])
check("10 mensajes no se pliegan", 0,
      mail_pages.thread_page("main", long_convo[0], long_convo[:10], loaded, own="agente@example.com").count("plegados"))
loaded[long_convo[3]["event_id"]] = {"error": mail.MailError("gone")}
html = mail_pages.thread_page("main", long_convo[0], long_convo[:5], loaded, own="agente@example.com")
check("uno que no se pudo leer dice por qué y el resto sale (4.3)", (True, 5, True),
      ("aviso-caja" in html, html.count('<li id="m-'), "cuerpo 4<" in html))

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
