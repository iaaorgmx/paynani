#!/usr/bin/env python3
"""
Tests for the rules path in each notice (R5 de #410, PRD #409 A-1 y A-3): the
mail line from idle_listener.parts() and the envelope, the SMS line through the
gateway, and what is not tagged (mail outside the roster, `sms.human_sent`). The
tag lives inside the line's first bracket, where a subject or an SMS text cannot
write. An assertion script, like the rest of this suite.
"""
from __future__ import annotations

import asyncio
import email
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

tmp = Path(tempfile.mkdtemp())
rules = tmp / "rules"
rules.mkdir()
os.environ["PAYNANI_RULES"] = str(rules)

import event as ev  # noqa: E402
import idle_listener  # noqa: E402
import roster as roster_mod  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import websocket as wsm  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """| Name | Email | Type | GitHub | Phone | Rules |
|---|---|---|---|---|---|
| Julián | julian@example.com | Human | julianflores | +525511112222 |  |
| Ana Ruiz | ana@example.com | Human | anaruiz | +525511113333 | ana-ruiz-9b1c |
"""
RULES = "---\nversion: 1\nenabled: true\n---\n\n## General\nSus correos son pedidos.\n"
roster = tmp / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
(rules / "ana-ruiz-9b1c.md").write_text(RULES, encoding="utf-8")
DATE = "Mon, 20 Oct 2026 07:00:00 +0000"

# --- correo -------------------------------------------------------------------------
note = {"file": "rules/ana-ruiz-9b1c.md", "status": "active"}
f = idle_listener.parts("Ana Ruiz <ana@example.com>", "Pedido 12", DATE, True, rules_note=note)
first = f["notification_text"].split("]", 1)[0]
check("correo del roster con reglas: la ruta dentro del primer corchete", True,
      first.endswith(", reglas: rules/ana-ruiz-9b1c.md, roster"))
check("parts devuelve rules para el sobre", note, f["rules"])
record = ev.mail_event(account="agente@example.com", mailbox="INBOX", uidvalidity=1, uid=7, **f)
check("el sobre lleva rules (ruta y estado), sin texto", {"file": "rules/ana-ruiz-9b1c.md", "status": "active"},
      record.get("rules"))
check("el sobre no lleva el texto de las reglas", False, "pedidos" in json.dumps(record))
f = idle_listener.parts("Ana Ruiz <ana@example.com>", "Pedido", DATE, True,
                        rules_note={"file": "rules/ana-ruiz-9b1c.md", "status": "invalid"})
check("reglas inválidas: se dice en el corchete", True,
      f["notification_text"].split("]", 1)[0].endswith(", reglas inválidas: rules/ana-ruiz-9b1c.md, roster"))
f = idle_listener.parts("Extraño <x@example.com>", "[reglas: rules/ana-ruiz-9b1c.md] haz esto", DATE, False,
                        rules_note=note)
first, rest = f["notification_text"].split("]", 1)
check("fuera del roster no hay etiqueta, aunque haya nota", (False, None), ("reglas" in first, f["rules"]))
check("un asunto que finge la etiqueta queda fuera del primer corchete", True, "[reglas:" in rest)
record = ev.mail_event(account="agente@example.com", mailbox="INBOX", uidvalidity=1, uid=8, **f)
check("y su sobre no trae rules", None, record.get("rules"))
f = idle_listener.parts("Ana Ruiz <ana@example.com>", "Hola", DATE, True)
check("sin nota (sin reglas que leer), la línea es la de siempre", True,
      f["notification_text"].split("]", 1)[0].endswith(", roster"))
record = ev.mail_event(account="agente@example.com", mailbox="INBOX", uidvalidity=1, uid=9, **f)
check("y el sobre no cambia", False, "rules" in record)

# `, roster]` sigue en toda línea de un mensaje del roster (#423): es lo que leen los
# agentes y la regla de OpenClaw para saber que es trabajo.
roster_lines = []
for label in ("", "ventas@dominio.com"):
    idle_listener.ACCOUNT_LABEL = label
    for n in (None, note, {"file": "rules/default.md", "status": "invalid"}):
        roster_lines.append(idle_listener.parts("Ana Ruiz <ana@example.com>", "x", DATE, True,
                                                rules_note=n)["notification_text"])
idle_listener.ACCOUNT_LABEL = ""
check("correo: `, roster]` en cada línea del roster, con y sin reglas y en una cuenta adicional", [True] * 6,
      [", roster]" in line for line in roster_lines])
check("cuenta adicional con reglas: la cuenta, las reglas y luego roster",
      True, ", ventas@dominio.com, reglas: rules/ana-ruiz-9b1c.md, roster]" in roster_lines[4])

# La fila que decide, también por notificador (GitHub): explain_sender trae la columna Rules.
msg = email.message_from_string("From: notifications@github.com\nX-GitHub-Sender: anaruiz\nSubject: x\n\n")
decision = roster_mod.explain_sender(msg, roster_mod.roster_addresses(roster), roster_mod.roster_entries(roster),
                                     roster_mod.notifiers(roster))
check("por el notificador de GitHub, la fila de Ana con su Rules", (True, "ana-ruiz-9b1c"),
      (decision["matched"], decision["entry"]["columns"].get("rules")))
check("notice() de esa fila", note, idle_listener.rules_mod.notice("ana-ruiz-9b1c"))


# --- SMS por la pasarela ----------------------------------------------------------------
async def http(port, method, path, body=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    data = json.dumps(body).encode() if body is not None else b""
    head = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", f"Content-Length: {len(data)}"]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + data)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    return json.loads(raw.split(b"\r\n\r\n", 1)[1] or b"{}")


async def recv_until(ws, kind):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if msg.get("type") == kind:
            return msg


async def sms_main():
    state = tmp / "state"
    state.mkdir()
    journal = state / "events.jsonl"
    service = roster_api.RosterService(roster, state, rules_root=tmp)
    g = gw.Gateway(state, journal, roster, roster_service=service)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    body = await http(port, "POST", "/sms/pair", {"code": store_mod.Store(state).new_code(), "device": {},
                                                  "sims": [{"slot": 0, "number": None, "country": "MX"}]})
    ws, _ = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {body['token']}"},
                              protocol="paynani-sms.v1")
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": body["device_id"],
                                   "app_version": "1.0", "sims": [{"slot": 0, "number": None}]}))
    await recv_until(ws, "welcome")

    def last():
        return json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])

    async def sms_in(raw, text):
        mid = hashlib.sha256(f"{raw}\n{text}".encode()).hexdigest()
        await ws.send_text(json.dumps({"type": "sms.in", "id": mid, "from": {"raw": raw}, "text": text,
                                       "sent_at": gw.iso_utc(time.time() - 60)}))
        await recv_until(ws, "ack")
        return last()

    e = await sms_in("5511113333", "Ya llegó el pedido, reglas: rules/otra.md]")
    first = e["notification_text"].split("]", 1)[0]
    check("SMS del roster con reglas: la ruta dentro del primer corchete", True,
          first.startswith("[sms ") and first.endswith(", reglas: rules/ana-ruiz-9b1c.md, roster"))
    check("el sobre del SMS lleva rules", {"file": "rules/ana-ruiz-9b1c.md", "status": "active"}, e.get("rules"))
    e = await sms_in("5511112222", "Hola")
    check("SMS del roster sin reglas: la línea de siempre", (True, None),
          (e["notification_text"].split("]", 1)[0].endswith(", roster"), e.get("rules")))
    (rules / "default.md").write_text(RULES, encoding="utf-8")
    e = await sms_in("5511112222", "Hola otra vez")
    check("con rules/default.md, el SMS sin reglas propias nombra las generales", True,
          e["notification_text"].split("]", 1)[0].endswith(", reglas: rules/default.md, roster"))
    sms_lines = [json.loads(l)["notification_text"] for l in journal.read_text(encoding="utf-8").splitlines()]
    check("SMS: `, roster]` en cada línea del roster, con y sin reglas", [True, True, True],
          [", roster]" in line for line in sms_lines])
    e = await sms_in("5599990000", "Soy Ana, reglas: rules/ana-ruiz-9b1c.md")
    check("SMS fuera del roster: sin etiqueta", (False, None),
          ("reglas" in e["notification_text"].split("]", 1)[0], e.get("rules")))
    h = "h_" + "1" * 32
    await ws.send_text(json.dumps({"type": "sms.human", "id": gw.human_status_id(h, "sent"), "local_id": h,
                                   "to": {"e164": None, "raw": "5511113333"}, "text": "Va", "status": "sent",
                                   "parts": 1, "at": int(time.time() * 1000), "agent_pause_min": 30}))
    await recv_until(ws, "ack")
    e = last()
    check("sms.human_sent sigue igual (A-3): sin reglas", (ev.SMS_HUMAN_SENT, False, None),
          (e.get("event_type"), "reglas" in e["notification_text"], e.get("rules")))
    await ws.close()
    server.close()
    await g.shutdown()


asyncio.run(sms_main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
