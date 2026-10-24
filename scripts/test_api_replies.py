#!/usr/bin/env python3
"""
Tests for replies to API conversations and opt-outs (A5 #497 of PRD #491: FR-11 to
FR-13). An assertion script, like the rest of this suite.

Una pasarela real con un teléfono de prueba por WebSocket, y un PaynaniWeb sobre el
mismo estado. Las órdenes sólo quedan en outbox/: nada sale de la máquina.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import api_replies  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import outgoing  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import websocket as wsm  # noqa: E402
from paynani_lib.web import api_tokens, app, auth, notify, strings, users  # noqa: E402
from paynani_lib import i18n  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


# --- Las palabras (FR-13) -------------------------------------------------------------
for text, expected in (("STOP", ("stop", "stop")), (" baja ", ("stop", "baja")), ("Bájá.", ("stop", "baja")),
                       ("ALTO!", ("stop", "alto")), ("Cancelar", ("stop", "cancelar")), ("start", ("start", "start")),
                       ("ALTA", ("start", "alta")), ("stop por favor", None), ("STOPP", None), ("", None), (None, None)):
    check(f"keyword({text!r})", expected, api_replies.keyword(text))
check("confirmación en español para BAJA", True, "ALTA" in api_replies.confirmation("stop", "baja"))
check("confirmación en inglés para STOP", True, "START" in api_replies.confirmation("stop", "stop"))

ROSTER = """# roster

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human |  | +525511112222 |
"""
ANA = "+525511112222"
CLIENT = "+525588887777"
OTHER = "+525533334444"
LATE = "+525566665555"

tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
roster = tmp / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
journal = state / "events.jsonl"
st = store_mod.Store(state)
user_file = tmp / "web" / "user.json"
PASSWORD = "una-contraseña-larga"
users.create("dueno@example.com", "Dueño", PASSWORD, user_file)
tokens_path = api_tokens.path_for(user_file)
citas, citas_rec = api_tokens.create("citas", permissions=["read", "sms.send"], path=tokens_path)
ventas, ventas_rec = api_tokens.create("ventas", permissions=["read", "sms.send"], path=tokens_path)
# FR-12: «el agente local contesta» en ventas.
records = json.loads(tokens_path.read_text())
for r in records:
    if r["prefix"] == ventas_rec["prefix"]:
        r["agent_replies"] = True
tokens_path.write_text(json.dumps(records))


def events(kind=None):
    lines = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
    return [e for e in (json.loads(x) for x in lines) if kind is None or e.get("event_type") == kind]


def mark(st, order_id, status, when=None):
    """El estado que mandaría el teléfono para una orden (sent, failed, …)."""
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if when is None else when))
    st.append_status({"id": f"{order_id}:{status}", "order_id": order_id, "status": status, "at": at})


def sms_id(seed):
    return hashlib.sha256(seed.encode()).hexdigest()


async def recv_until(ws, kind, timeout=5):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg.get("type") == kind:
            return msg


async def gateway_part():
    g = gw.Gateway(state, journal, roster, public_url="https://ejemplo.ngrok.io", api_tokens_path=tokens_path)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    code = st.new_code()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    data = json.dumps({"code": code, "device": {"model": "Pixel"}, "sims": [{"slot": 0, "number": None, "country": "MX"}]}).encode()
    writer.write(f"POST /sms/pair HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data)
    raw = await reader.read()
    writer.close()
    body = json.loads(raw.split(b"\r\n\r\n", 1)[1])
    ws, _ = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {body['token']}"},
                              protocol="paynani-sms.v1")
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": body["device_id"], "app_version": "0.9.0",
                                   "sims": [{"slot": 0, "number": None}], "accepts_owner_out": True,
                                   "accepts_api_out": True}))
    await recv_until(ws, "welcome")

    # Conversaciones de la API: citas con CLIENT, ventas con ANA (del roster).
    a1 = outgoing.queue(st, to=CLIENT, text="Su cita es mañana", origin="api", token="citas",
                        token_id=citas_rec["prefix"], idempotency_key="c1", source="203.0.113.9")
    a2 = outgoing.queue(st, to=ANA, text="Oferta", origin="api", token="ventas", token_id=ventas_rec["prefix"],
                        idempotency_key="v1", source="203.0.113.9")
    # Revisión de #523: sólo una orden que el teléfono envió hace conversación.
    check("una orden sólo en cola no hace conversación", None, api_replies.conversation(st, CLIENT))
    mark(st, a1["id"], "sent")
    mark(st, a2["id"], "sent")
    mark(st, a2["id"], "delivered")

    async def sms_in(number, text, seed):
        await ws.send_text(json.dumps({"type": "sms.in", "id": sms_id(seed), "from": {"e164": number, "raw": number},
                                       "text": text, "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        ack = await recv_until(ws, "ack")
        return ack, events("sms.received")[-1]

    # FR-11: respuesta de CLIENT a citas (fuera del roster).
    ack, ev = await sms_in(CLIENT, "Sí confirmo", "r1")
    check("FR-11: la respuesta queda marcada para citas", (citas_rec["prefix"], "citas", a1["id"], False),
          (ev.get("api_reply", {}).get("token_id"), ev["api_reply"].get("token"), ev["api_reply"].get("order_id"),
           ev["api_reply"].get("agent_replies")))
    check("FR-11/12: la línea del agente dice respuesta a la API y que no contesta", True,
          "respuesta a la API: citas, el agente no contesta]" in ev["notification_text"])
    # FR-12: ventas deja contestar; ANA está en el roster.
    ack, ev = await sms_in(ANA, "Me interesa", "r2")
    check("FR-12: con agent_replies, la línea no dice que no conteste, y conserva , roster]", (True, False, True),
          ("respuesta a la API: ventas" in ev["notification_text"], "no contesta" in ev["notification_text"],
           ", roster]" in ev["notification_text"]))
    # Sin conversación de la API.
    ack, ev = await sms_in(OTHER, "Hola", "r3")
    check("sin conversación de la API: sin marca", (False, False), ("api_reply" in ev, "API" in ev["notification_text"]))
    # Hace más de 7 días no cuenta.
    old = outgoing.queue(st, to=OTHER, text="viejo", origin="api", token="citas", token_id=citas_rec["prefix"],
                         idempotency_key="old", source="t", now=time.time() - 8 * 86400)
    mark(st, old["id"], "sent", time.time() - 8 * 86400)
    check("una orden enviada hace 8 días no hace conversación", None, api_replies.conversation(st, OTHER))
    # Revisión de #523: fallida, rechazada o vencida no le habló a nadie.
    for n, status in enumerate(("failed", "rejected", "expired")):
        bad = outgoing.queue(st, to=OTHER, text="no salió", origin="api", token="citas",
                             token_id=citas_rec["prefix"], idempotency_key=f"bad{n}", source="t")
        mark(st, bad["id"], "accepted")
        mark(st, bad["id"], status)
        check(f"una orden {status} no hace conversación", None, api_replies.conversation(st, OTHER))
    ack, ev = await sms_in(OTHER, "Hola otra vez", "r4")
    check("un SMS después de una orden fallida no se marca para el token", False, "api_reply" in ev)
    # La ventana corre desde el envío, no desde la cola.
    late = outgoing.queue(st, to=LATE, text="tarde", origin="api", token="citas", token_id=citas_rec["prefix"],
                          idempotency_key="late", source="t", now=time.time() - 8 * 86400)
    mark(st, late["id"], "sent", time.time() - 6 * 86400)
    check("en cola hace 8 días y enviada hace 6: sí hace conversación", late["id"],
          (api_replies.conversation(st, LATE) or {}).get("order_id"))
    mark(st, late["id"], "delivered", time.time() - 6 * 86400 + 30)
    check("la ventana corre desde el primer envío", time.strftime("%Y-%m-%dT", time.gmtime(time.time() - 6 * 86400)),
          (api_replies.conversation(st, LATE) or {}).get("at", "")[:11])

    # FR-13: STOP de CLIENT: baja, una confirmación por la API (orden a_ de citas).
    before = {p.name for p in (st.root / "outbox").glob("a_*.json")}
    ack, ev = await sms_in(CLIENT, "STOP", "s1")
    check("FR-13: STOP da de baja el número", True, st.opted_out(CLIENT) is not None)
    check("FR-13: el evento lo marca y la línea lo dice", ("stop", True), (ev.get("api_optout"), "baja de la API" in ev["notification_text"]))
    new = [json.loads((st.root / "outbox" / n).read_text()) for n in
           {p.name for p in (st.root / "outbox").glob("a_*.json")} - before]
    check("FR-13: una confirmación en inglés, como orden a_ del token citas", (1, "citas", True),
          (len(new), new[0].get("token") if new else None, "START" in (new[0]["text"] if new else "")))
    # Reenvío del mismo SMS y un segundo STOP: nada nuevo.
    await ws.send_text(json.dumps({"type": "sms.in", "id": sms_id("s1"), "from": {"e164": CLIENT, "raw": CLIENT},
                                   "text": "STOP"}))
    await recv_until(ws, "ack")
    ack, ev = await sms_in(CLIENT, "baja", "s2")
    after = {p.name for p in (st.root / "outbox").glob("a_*.json")} - before
    check("FR-13: la confirmación sale una sola vez", 1, len(after))
    # SendSms ya no puede escribirle (A4): lo prueba la parte web de abajo.
    # START: alta y confirmación.
    ack, ev = await sms_in(CLIENT, "Alta", "s3")
    after2 = {p.name for p in (st.root / "outbox").glob("a_*.json")} - before
    check("FR-13: ALTA lo da de alta y confirma en español", (None, 2),
          (st.opted_out(CLIENT), len(after2)))
    # STOP de un número sin conversación de la API: baja sin confirmación.
    before3 = {p.name for p in (st.root / "outbox").glob("a_*.json")}
    ack, ev = await sms_in(OTHER, "STOP", "s4")
    check("STOP sin conversación de la API: baja, sin confirmación", (True, set()),
          (st.opted_out(OTHER) is not None, {p.name for p in (st.root / "outbox").glob("a_*.json")} - before3))
    ws.close() if hasattr(ws, "close") and not asyncio.iscoroutinefunction(ws.close) else await ws.close()
    server.close()
    await g.shutdown()
    return a1


a1 = asyncio.run(gateway_part())

# --- La web y la API sobre el mismo estado ----------------------------------------------
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "no-accounts.json",
                  state_dir=state, roster_path=roster)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def api(secret, action, **params):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", "/api/agent", body=json.dumps({"action": action, **params}),
                 headers={"Host": HOST, "X-Forwarded-For": "203.0.113.9", "Authorization": "Bearer " + secret,
                          "Content-Type": "application/json"})
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


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


since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
status, body = api(citas, "ListSmsReplies", since=since)
froms = [(r["from"], r["text"]) for r in body.get("replies", [])]
check("ListSmsReplies (citas): sólo las respuestas a citas, con su texto", (200, True, False),
      (status, (CLIENT, "Sí confirmo") in froms, any(f == ANA for f, _ in froms)))
check("ListSmsReplies marca las bajas y altas", True,
      any(r.get("opt_out") == "stop" for r in body["replies"]) and any(r.get("opt_out") == "start" for r in body["replies"]))
check("ListSmsReplies: in_reply_to es la orden de la API", True,
      any(r["in_reply_to"] == a1["id"] for r in body["replies"]))
status, body = api(ventas, "ListSmsReplies", since=since)
check("ListSmsReplies (ventas): sólo la de Ana", [ANA], [r["from"] for r in body["replies"]])
for bad in ("ayer", "2026-10-24T10:00:00", "2099-01-01T00:00:00Z", "2020-01-01T00:00:00Z"):
    status, body = api(citas, "ListSmsReplies", since=bad)
    check(f"since inválido {bad!r}: invalid_parameter", (400, "invalid_parameter"), (status, body.get("code")))
status, body = api(citas, "ListSmsReplies")
check("sin since: missing_parameter", (400, "missing_parameter"), (status, body.get("code")))

# A4 + A5: OTHER se dio de baja; SendSms responde opted_out.
status, body = api(citas, "SendSms", to=OTHER, text="hola", idempotency_key="after-stop")
check("SendSms a un número que mandó STOP: opted_out", (403, "opted_out"), (status, body.get("code")))

# --- La pantalla de bajas -------------------------------------------------------------
_, hdrs, _ = req("POST", "/login", form={"email": "dueno@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
th = i18n.th
status, _, page = req("GET", "/messages", cookie=cookie)
check("Mensajes enlaza a la lista de bajas", True, 'href="/messages/bajas"' in page)
status, _, page = req("GET", "/messages/bajas", cookie=cookie)
check("la lista muestra a OTHER con «Respondió STOP»", (200, True, True),
      (status, OTHER in page, th("web.sms.optout.by_sms", word="STOP") in page))
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
status, hdrs, _ = req("POST", "/messages/bajas", form={"csrf": csrf, "accion": "agregar", "n": "55 9999 0000"}, cookie=cookie)
check("agregar un número (formato local): 303 y queda en la lista en E.164", (303, True),
      (status, st.opted_out("+525599990000") is not None))
check("…y dice que fue desde la web", "web:203.0.113.5", st.opted_out("+525599990000").get("by"))
status, hdrs, _ = req("POST", "/messages/bajas", form={"csrf": csrf, "accion": "quitar", "n": OTHER}, cookie=cookie)
check("quitar de la lista", (303, None), (status, st.opted_out(OTHER)))
status, _, page = req("GET", "/messages/bajas?ok=removed", cookie=cookie)
check("el aviso de quitado", True, th("web.sms.optout.ok_removed") in page)
status, _, page = req("POST", "/messages/bajas", form={"csrf": csrf, "accion": "agregar", "n": "hola"}, cookie=cookie)
check("un número ilegible: 400 con su razón", (400, True), (status, th("web.sms.err.invalid_number") in page))
status, _, _ = req("POST", "/messages/bajas", form={"csrf": "malo", "accion": "agregar", "n": OTHER}, cookie=cookie)
check("sin el CSRF: 403 y no cambia nada", (403, None), (status, st.opted_out(OTHER)))
status, _, _ = req("GET", "/messages/bajas")
check("sin sesión: no muestra la lista", True, status in (302, 303))
missing = [(lang, k) for lang in strings.STRINGS for k in strings.STRINGS["es-MX"]
           if k.startswith("web.sms.optout.") and k not in strings.STRINGS[lang]]
check("las cadenas de la pantalla en los cinco idiomas", [], missing)

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
