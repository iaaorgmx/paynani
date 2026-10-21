#!/usr/bin/env python3
"""
Tests for PaynaniWeb's Messages (PRD #434 FR-17 to FR-19; T7 of #435).
An assertion script, like the rest of this suite.

Las conversaciones SMS salen del diario y del store de la pasarela, con el mismo
código que `paynani sms thread` (sms/thread.py): lo recibido, lo del agente con su
estado y lo del dueño desde PaynaniApp, en orden de hora real, más las llamadas
perdidas y contestadas. La lista va por conversación, de 50 en 50. Sólo muestra.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import store as sms_store  # noqa: E402
from paynani_lib.sms import thread as sms_thread  # noqa: E402
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


ANA, BETO = "+525511112222", "+525533334444"
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
st = sms_store.Store(state)
roster = tmp / "roster.md"
roster.write_text("| Name | Email | Type | GitHub | Phone |\n|---|---|---|---|---|\n"
                  "| Ana López | ana@example.com | Human |  | +52 1 55 1111 2222 |\n", encoding="utf-8")
journal = state / "events.jsonl"
lines = []


def mid(n):
    return hashlib.sha256(f"m{n}".encode()).hexdigest()


def sms_in(n, number, text, sent_at, name=""):
    st.save_inbox(mid(n), {"text": text})
    lines.append({"event_type": "sms.received", "event_id": f"sms:d:{n}", "sender": {"address": number, "name": name},
                  "provider_id": f"sms:{mid(n)}", "sent_at": sent_at, "observed_at": sent_at})


sms_in(1, ANA, "¿Tienen mesa mañana? <b>4 personas</b>", "2026-10-20T19:00:00-05:00")
lines.append({"event_type": "call.missed", "event_id": "sms:d:c1", "sender": {"address": ANA},
              "started_at": "2026-10-21T00:30:00Z", "observed_at": "2026-10-21T00:30:05Z"})
lines.append({"event_type": "call.answered", "event_id": "sms:d:c2", "sender": {"address": ANA},
              "started_at": "2026-10-21T00:40:00Z", "duration_s": 125})
sms_in(2, BETO, "Hola, soy Beto", "2026-10-21T02:00:00Z", name="Beto (teléfono)")
journal.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines), encoding="utf-8")

order = {"id": "o_" + "a" * 32, "to": ANA, "text": "Sí, Ana: a las 8 tenemos mesa."}
(st.root / "sent" / f"{order['id']}.json").write_text(json.dumps(order), encoding="utf-8")
(st.root / "orders.jsonl").write_text(
    json.dumps({"order_id": order["id"], "status": "queued", "at": "2026-10-21T00:10:00Z"}) + "\n"
    + json.dumps({"order_id": order["id"], "status": "delivered", "at": "2026-10-21T00:11:00Z"}) + "\n", encoding="utf-8")
human_id = "h_" + "b" * 32
st.save_inbox(mid(9), {"text": "Ana, te confirmo yo."})
(st.root / "human.jsonl").write_text(
    json.dumps({"local_id": human_id, "id": mid(9), "to": ANA, "status": "sent", "at": "2026-10-21T00:50:00Z",
                "event_id": "sms-human:x", "pause_until": "2999-01-01T00:00:00Z"}) + "\n"
    + json.dumps({"local_id": human_id, "to": ANA, "status": "delivered", "at": "2026-10-21T00:51:00Z"}) + "\n",
    encoding="utf-8")

# --- el módulo -------------------------------------------------------------------------
all_items = sms_thread.items(st, journal, calls=True)
ana = [i for i in all_items if i["number"] == ANA]
check("Ana: recibido, agente, llamada perdida, contestada y dueño, en orden de hora real",
      ["received", "agent", "call_missed", "call_answered", "human"], [i["kind"] for i in ana])
check("el recibido con zona -05:00 va por su hora real (00:00 UTC), antes del agente", True,
      ana[0]["epoch"] < ana[1]["epoch"])
check("el agente con su último estado", "delivered", ana[1]["status"])
check("el dueño con su último estado", "delivered", ana[4]["status"])
check("la contestada trae la duración", 125, ana[3]["duration_s"])
check("sin calls=True no hay llamadas (como sms thread)", ["received", "agent", "human"],
      [i["kind"] for i in sms_thread.items(st, journal, number=ANA)])
convs = sms_thread.conversations(all_items)
check("conversaciones: la más reciente primero (Beto 02:00 > Ana 00:50)", [BETO, ANA], [c["number"] for c in convs])
check("Ana: 5 elementos y una perdida", (5, 1), (convs[1]["count"], convs[1]["missed"]))

# --- el servidor ---------------------------------------------------------------------------
user_file = tmp / "web" / "user.json"
users.create("dueno@example.com", "Dueño", "una-contraseña-larga", user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "no-accounts.json",
                  state_dir=state, roster_path=roster)
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


_, hdrs, _ = req("POST", "/login", form={"email": "dueno@example.com", "password": "una-contraseña-larga"})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
before = {p.name: p.read_bytes() for p in (st.root).rglob("*") if p.is_file()}
before_journal = journal.read_bytes()

status, _, page = req("GET", "/messages", cookie=cookie)
check("/messages: 200, marcado en el menú", (200, True), (status, 'href="/messages" class="activo"' in page))
check("dos conversaciones, Beto primero", [BETO, ANA],
      [n.replace("%2B", "+") for n in re.findall(r'href="/messages/ver\?n=([^"]+)"', page)])
check("Ana con su nombre del roster y la marca", True, "Ana López" in page and 'class="marca-roster"' in page)
check("Beto, fuera del roster, con el nombre del teléfono", True, "Beto (teléfono)" in page)
check("lo último de Ana es lo del dueño, como vista previa", True, "Tú, desde PaynaniApp: Ana, te confirmo yo." in page)
check("y que tuvo una llamada perdida", True, "1 perdidas" in page)

status, _, page = req("GET", "/messages/ver?n=" + quote(ANA, safe=""), cookie=cookie)
check("la conversación de Ana: 200", 200, status)
order_in_page = [m for m in re.findall(r'class="(sms sms-\w+|llamada)"', page)]
check("en orden: recibido, agente, perdida, contestada, dueño",
      ["sms sms-received", "sms sms-agent", "llamada", "llamada", "sms sms-human"], order_in_page)
check("el texto escapado", (True, False), ("&lt;b&gt;4 personas&lt;/b&gt;" in page, "<b>4 personas</b>" in page))
check("la llamada perdida dice de quién (FR-18)", True, "Llamada perdida de Ana López" in page)
check("la contestada, con su duración", True, "Llamada contestada de Ana López · 2 min 5 s" in page)
check("el estado del agente y del dueño", True, page.count("entregado") >= 2)
check("la pausa del agente después de que contestó el dueño", True, "el agente no le escribe a este número" in page)
check("solo muestra (FR-19): sin formularios salvo cerrar sesión", 0,
      len([f for f in re.findall(r'<form method="post" action="([^"]+)"', page) if f != "/logout"]))

status, _, page = req("GET", "/messages/ver?n=" + quote(BETO, safe=""), cookie=cookie)
check("Beto, fuera del roster, también se lee (como Q-T5-2)", (200, True), (status, "Hola, soy Beto" in page))
status, _, page = req("GET", "/messages/ver?n=%2B520000000000", cookie=cookie)
check("un número sin mensajes: 404", 404, status)
check("ver la web no escribió nada en el store ni en el diario", (before, before_journal),
      ({p.name: p.read_bytes() for p in (st.root).rglob("*") if p.is_file()}, journal.read_bytes()))

# 60 conversaciones: 50 y «Ver más».
extra = []
for n in range(60):
    number = f"+5255000{n:05d}"
    st.save_inbox(mid(100 + n), {"text": f"hola {n}"})
    extra.append({"event_type": "sms.received", "event_id": f"sms:d:x{n}", "sender": {"address": number},
                  "provider_id": f"sms:{mid(100 + n)}", "sent_at": f"2026-10-19T{n // 60:02d}:{n % 60:02d}:00Z"})
with open(journal, "a", encoding="utf-8") as fh:
    fh.write("".join(json.dumps(l) + "\n" for l in extra))
status, _, page = req("GET", "/messages", cookie=cookie)
check("62 conversaciones: 50 en la primera página y «Ver más»", (50, True),
      (len(re.findall(r'href="/messages/ver', page)), 'href="/messages?desde=50"' in page))
status, _, page = req("GET", "/messages?desde=50", cookie=cookie)
check("la segunda página: 12 y sin «Ver más»", (12, False),
      (len(re.findall(r'href="/messages/ver', page)), "desde=100" in page))

# Una conversación de 60 mensajes: los 50 más recientes y «Ver anteriores».
for n in range(60):
    st.save_inbox(mid(300 + n), {"text": f"mensaje {n}"})
with open(journal, "a", encoding="utf-8") as fh:
    for n in range(60):
        fh.write(json.dumps({"event_type": "sms.received", "event_id": f"sms:d:y{n}", "sender": {"address": "+15550001111"},
                             "provider_id": f"sms:{mid(300 + n)}", "sent_at": f"2026-10-18T10:{n:02d}:00Z"}) + "\n")
status, _, page = req("GET", "/messages/ver?n=%2B15550001111", cookie=cookie)
check("60 mensajes: se ven los 50 más recientes (10 a 59) y «Ver anteriores»", (50, True, False, True),
      (page.count('class="sms sms-received"'), "mensaje 59" in page, "mensaje 9<" in page, "desde=50" in page))
status, _, page = req("GET", "/messages/ver?n=%2B15550001111&desde=50", cookie=cookie)
check("«Ver anteriores»: los 10 primeros", (10, True), (page.count('class="sms sms-received"'), "mensaje 0<" in page))

httpd.shutdown()
httpd.server_close()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
