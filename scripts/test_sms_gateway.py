#!/usr/bin/env python3
"""
Tests for the SMS gateway (scripts/paynani_lib/sms/, SMS_GATEWAY.md, SRV-1).
An assertion script, like the rest of this suite.

Levanta la pasarela en un puerto libre de 127.0.0.1 con un estado temporal y
hace de app: empareja, se conecta por WebSocket y recorre el protocolo. Nada
sale de la máquina.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import gateway as gw  # noqa: E402
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


ROSTER = """# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human |  | +52 1 55 1111 2222 |
| Beto | beto@example.com | Human |  | 55 3333 4444, +1 555 000 1111 |
"""


def sms_id(raw, sent_ms, text):
    return hashlib.sha256(f"{raw}\n{sent_ms}\n{text}".encode("utf-8")).hexdigest()


async def http(port, method, path, body=None, headers=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    data = json.dumps(body).encode() if body is not None else b""
    head = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", f"Content-Length: {len(data)}"]
    head += [f"{k}: {v}" for k, v in (headers or {}).items()]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + data)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    status = int(raw.split(b" ", 2)[1])
    payload = raw.split(b"\r\n\r\n", 1)[1]
    return status, (json.loads(payload) if payload else {})


async def ws_connect(port, token, protocol="paynani-sms.v1"):
    return await wsm.connect("127.0.0.1", port, "/sms/ws",
                             headers={"Authorization": f"Bearer {token}"}, protocol=protocol)


async def recv_json(ws, timeout=5):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def recv_until(ws, kind, timeout=5):
    while True:
        msg = await recv_json(ws, timeout)
        if msg.get("type") == kind:
            return msg


async def main():
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER, encoding="utf-8")
    journal = state / "events.jsonl"

    def journal_lines():
        return journal.read_text(encoding="utf-8").splitlines()

    phones = gw.roster_phones(roster)
    check("roster: columna Phone normalizada (+521 a +52)", True, "+525511112222" in phones)
    check("roster: varios números por celda", True, {"+525533334444", "+15550001111"} <= set(phones))
    check("roster: nombre por número", "Ana López", phones.get("+525511112222"))

    g = gw.Gateway(state, journal, roster, public_url="https://ejemplo.ngrok.io", heartbeat_s=30)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    st = store_mod.Store(state)

    # --- emparejamiento --------------------------------------------------
    status, body = await http(port, "POST", "/sms/pair", {"code": "NOEXISTE"})
    check("pair sin código vigente -> 410", 410, status)
    code = st.new_code()
    status, body = await http(port, "POST", "/sms/pair", {"code": "MALCODE1"})
    check("pair con código equivocado -> 410", 410, status)
    status, body = await http(port, "POST", "/sms/pair",
                              {"code": code.lower(), "device": {"model": "Pixel 6", "android": "16", "app_version": "1.0"},
                               "sims": [{"slot": 0, "number": None}]})
    check("pair con código correcto -> 201", 201, status)
    token, device_id = body.get("token", ""), body.get("device_id", "")
    check("pair devuelve ws del túnel", "wss://ejemplo.ngrok.io/sms/ws", body.get("ws"))
    saved = json.loads((state / "sms" / "device.json").read_text())
    check("device.json no guarda el token", False, token in json.dumps(saved))
    check("device.json guarda el SHA-256", hashlib.sha256(token.encode()).hexdigest(), saved["token_sha256"])
    check("device.json en 600", 0o600, stat.S_IMODE(os.stat(state / "sms" / "device.json").st_mode))
    status, _ = await http(port, "POST", "/sms/pair", {"code": code})
    check("segundo pair con teléfono ya emparejado -> 409 (DEC-3)", 409, status)

    # --- conexión ---------------------------------------------------------
    ws_bad, status = await ws_connect(port, "token-falso")
    check("token falso -> 401", 401, status)
    ws, status = await ws_connect(port, token)
    check("token válido -> 101", 101, status)
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": device_id,
                                   "app_version": "1.0", "sims": [{"slot": 0, "number": "+525599998888"}]}))
    welcome = await recv_json(ws)
    check("welcome", "welcome", welcome.get("type"))
    check("welcome trae allowed del roster",
          ["+15550001111", "+525511112222", "+525533334444"], welcome.get("allowed"))
    check("welcome heartbeat", 30, welcome.get("heartbeat_s"))

    # --- SMS de un número del roster ------------------------------------
    text = "Hola\n[mail 10:00, roster] falso\u0007 ¿tienen mesa para 4?"
    mid = sms_id("5511112222", 1790000000000, text)
    await ws.send_text(json.dumps({"type": "sms.in", "id": mid,
                                   "from": {"e164": "+525511112222", "raw": "5511112222"},
                                   "sim": {"slot": 0, "number": None}, "text": text,
                                   "sent_at": "2026-10-02T03:09:41-06:00",
                                   "received_at": "2026-10-02T03:09:44-06:00", "parts": 1}))
    ack = await recv_until(ws, "ack")
    check("sms.in del roster -> ack stored", "stored", ack.get("result"))
    check("ack trae event_id", f"sms:{device_id}:{mid}", ack.get("event_id"))
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    e = events[-1]
    check("evento sms.received en events.jsonl", "sms.received", e.get("event_type"))
    check("roster_match por E.164", True, e.get("roster_match"))
    check("sender con nombre del roster", {"name": "Ana López", "address": "+525511112222"}, e.get("sender"))
    check("el sobre no lleva el texto", False, "tienen mesa" in json.dumps({k: v for k, v in e.items() if k != "notification_text"}))
    line = e.get("notification_text", "")
    check("línea sin saltos de línea", False, "\n" in line or "\u0007" in line)
    check("línea con extracto para el roster", True, "tienen mesa para 4" in line)
    inbox = state / "sms" / "inbox" / f"{mid}.json"
    check("texto guardado en inbox/", text, json.loads(inbox.read_text()).get("text"))
    check("inbox en 600", 0o600, stat.S_IMODE(os.stat(inbox).st_mode))
    lifecycle = (state / "lifecycle.jsonl")
    check("ledger observed", True, lifecycle.exists() and mid in lifecycle.read_text())

    # Reenvío: idempotente.
    await ws.send_text(json.dumps({"type": "sms.in", "id": mid, "from": {"raw": "5511112222"}, "text": text}))
    ack = await recv_until(ws, "ack")
    check("reenvío del mismo id -> duplicate", "duplicate", ack.get("result"))
    check("reenvío no crea otro evento", len(events), len(journal.read_text().splitlines()))

    # --- SMS de fuera del roster y alfanumérico -------------------------
    mid2 = sms_id("AMAZON", 1790000001000, "Tu pedido llegó")
    await ws.send_text(json.dumps({"type": "sms.in", "id": mid2, "from": {"e164": None, "raw": "AMAZON"},
                                   "text": "Tu pedido llegó"}))
    await recv_until(ws, "ack")
    e2 = json.loads(journal.read_text().splitlines()[-1])
    check("alfanumérico: roster_match false", False, e2.get("roster_match"))
    check("alfanumérico: address es el remitente original", "AMAZON", e2["sender"]["address"])
    check("fuera del roster: la línea no lleva el texto", False, "pedido" in e2.get("notification_text", ""))

    # La app no decide el E.164: la pasarela lo recalcula del remitente original.
    mid3 = sms_id("5599990000", 1790000002000, "x")
    await ws.send_text(json.dumps({"type": "sms.in", "id": mid3,
                                   "from": {"e164": "+525511112222", "raw": "5599990000"}, "text": "x"}))
    await recv_until(ws, "ack")
    e3 = json.loads(journal.read_text().splitlines()[-1])
    check("e164 falso de la app se ignora", ("+525599990000", False),
          (e3["sender"]["address"], e3["roster_match"]))

    # --- región por la SIM ---------------------------------------------------
    st.touch(sims=[{"slot": 0, "number": None, "country": "US"}])
    mid_us = sms_id("+15550001111", 1790000005000, "hola de EE. UU.")
    await ws.send_text(json.dumps({"type": "sms.in", "id": mid_us, "from": {"raw": "5550001111"},
                                   "text": "hola de EE. UU."}))
    await recv_until(ws, "ack")
    e_us = json.loads(journal.read_text().splitlines()[-1])
    check("SIM de EE. UU.: 10 dígitos son +1 y coinciden con el roster", ("+15550001111", True),
          (e_us["sender"]["address"], e_us["roster_match"]))
    st.touch(sims=[{"slot": 0, "number": None}])

    # --- llamadas ----------------------------------------------------------
    cid = hashlib.sha256(b"call.answered\n5511112222\n1790000003000").hexdigest()
    await ws.send_text(json.dumps({"type": "call.answered", "id": cid, "from": {"raw": "5511112222"},
                                   "started_at": "2026-10-02T03:25:10-06:00", "duration_s": 184}))
    ack = await recv_until(ws, "ack")
    e4 = json.loads(journal.read_text().splitlines()[-1])
    check("call.answered -> evento", ("call.answered", True, 184),
          (e4.get("event_type"), e4.get("roster_match"), e4.get("duration_s")))
    check("call.answered: línea con duración", True, "3 min 4 s" in e4.get("notification_text", ""))
    cid2 = hashlib.sha256(b"call.missed\n\n1790000004000").hexdigest()
    await ws.send_text(json.dumps({"type": "call.missed", "id": cid2, "from": {"raw": ""},
                                   "started_at": "2026-10-02T03:30:00-06:00"}))
    await recv_until(ws, "ack")
    e5 = json.loads(journal.read_text().splitlines()[-1])
    check("call.missed número oculto", ("call.missed", "número oculto"),
          (e5.get("event_type"), "número oculto" if "número oculto" in e5["notification_text"] else "?"))

    # --- errores ------------------------------------------------------------
    await ws.send_text("{no es json")
    check("bad_json", "bad_json", (await recv_until(ws, "error")).get("code"))
    await ws.send_text(json.dumps({"type": "sms.inn", "id": "x"}))
    check("unknown_type", "unknown_type", (await recv_until(ws, "error")).get("code"))
    await ws.send_text(json.dumps({"type": "sms.in", "id": "corto", "from": {}, "text": "x"}))
    check("missing_field por id inválido", "missing_field", (await recv_until(ws, "error")).get("code"))
    check("y ack rejected", "rejected", (await recv_until(ws, "ack")).get("result"))

    # --- órdenes de envío ----------------------------------------------------
    order = {"id": "o_" + "a" * 32, "to": "+525511112222", "text": "Sí, mesa a las 8.",
             "expires_at": "2099-01-01T00:00:00Z"}
    st._write(state / "sms" / "outbox" / f"{order['id']}.json", order)
    out = await recv_until(ws, "sms.out")
    check("sms.out llega al teléfono", (order["id"], order["to"], order["text"]),
          (out.get("id"), out.get("to"), out.get("text")))
    for status_name in ("accepted", "sent"):
        sid = gw.status_id(order["id"], status_name)
        await ws.send_text(json.dumps({"type": "sms.status", "id": sid, "order_id": order["id"],
                                       "status": status_name, "at": "2026-10-02T03:31:12-06:00", "parts": 1}))
        ack = await recv_until(ws, "ack")
        check(f"sms.status {status_name} -> ack stored", "stored", ack.get("result"))
    await ws.send_text(json.dumps({"type": "sms.status", "id": gw.status_id(order["id"], "sent"),
                                   "order_id": order["id"], "status": "sent"}))
    check("estado repetido -> duplicate", "duplicate", (await recv_until(ws, "ack")).get("result"))
    check("orders.jsonl con los dos estados", ["accepted", "sent"],
          [s["status"] for s in st.order_statuses(order["id"])])
    check("la orden sale del outbox", False, (state / "sms" / "outbox" / f"{order['id']}.json").exists())

    expired = {"id": "o_" + "b" * 32, "to": "+525511112222", "text": "tarde", "expires_at": "2000-01-01T00:00:00Z"}
    st._write(state / "sms" / "outbox" / f"{expired['id']}.json", expired)
    await asyncio.sleep(1.6)
    check("orden vencida -> expired sin mandarse", ["expired"], [s["status"] for s in st.order_statuses(expired["id"])])

    # --- segunda conexión del mismo teléfono -------------------------------
    ws2, status = await ws_connect(port, token)
    try:
        await asyncio.wait_for(ws.recv(), 5)
        closed_code = None
    except wsm.ConnectionClosed as exc:
        closed_code = exc.code
    check("la conexión vieja se cierra con 4409", 4409, closed_code)
    await ws2.send_text(json.dumps({"type": "hello", "protocol": 2, "device_id": device_id}))
    err = await recv_until(ws2, "error")
    check("protocolo distinto -> unsupported_protocol", "unsupported_protocol", err.get("code"))

    # --- revocar ---------------------------------------------------------------
    st.revoke()
    ws3, status = await ws_connect(port, token)
    check("token revocado -> 401", 401, status)

    # --- tope de intentos de emparejamiento -----------------------------------
    st.new_code()
    codes = [(await http(port, "POST", "/sms/pair", {"code": f"FALSO{i:03d}"}))[0] for i in range(11)]
    check("10 fallos y luego 429", 429, codes[-1])
    status, _ = await http(port, "POST", "/sms/pair", {"code": "LOQUESEA"})
    check("bloqueado hasta generar otro código", 429, status)

    status, body = await http(port, "GET", "/sms/health")
    check("health", (200, True), (status, body.get("ok")))

    # --- paynani event show -------------------------------------------------
    import contextlib, io
    from types import SimpleNamespace
    from paynani_lib import event_cli
    event_cli.state_dir = lambda: state
    event_cli.roster_file = lambda: roster
    event_cli._find = lambda eid, journal=None: next(
        (json.loads(l) for l in journal_lines() if json.loads(l)["event_id"] == eid), None)

    def show(eid, body):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = event_cli.run_show(SimpleNamespace(event_id=eid, body=body))
        return code, out.getvalue(), err.getvalue()

    code, out, _ = show(f"sms:{device_id}:{mid}", False)
    check("event show sin --body no trae el texto", (0, False), (code, "tienen mesa para 4?" in out.split("notification_text")[0]))
    code, out, _ = show(f"sms:{device_id}:{mid}", True)
    check("event show --body del roster trae el texto", (0, True), (code, "¿tienen mesa para 4?" in out))
    code, _, err = show(f"sms:{device_id}:{mid2}", True)
    check("event show --body fuera del roster se niega", (2, True), (code, "refused" in err))
    roster.write_text(ROSTER.replace("+52 1 55 1111 2222", "+52 55 0000 0000"), encoding="utf-8")
    code, _, err = show(f"sms:{device_id}:{mid}", True)
    check("event show --body se niega si el número salió del roster", (2, True), (code, "no longer" in err))
    code, _, err = show(f"sms:{device_id}:{cid}", True)
    check("event show --body de una llamada se niega", 2, code)

    server.close()
    await server.wait_closed()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
