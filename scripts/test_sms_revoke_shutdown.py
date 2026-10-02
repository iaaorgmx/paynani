#!/usr/bin/env python3
"""
Tests for two gateway findings from QA-4 (iaaorgmx/PaynaniApp#28).
An assertion script, like the rest of this suite.

1. `paynani sms revoke` (o un emparejamiento nuevo) tiene que cortar al teléfono que
   ya estaba conectado con 4401, y lo que mande después no entra al diario.
2. Con una conexión colgada, el apagado no puede quedarse esperando: la vigilancia
   de salud se detiene y el servidor cierra en segundos.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import websocket as wsm  # noqa: E402

passed = failed = 0

ROSTER = """# roster de prueba

# 1. Approved contacts

| Name | Email | Phone |
|---|---|---|
| Ana López | ana@example.com | +52 55 1111 2222 |
"""


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}: expected {expected!r}, got {actual!r}")


async def http_pair(port, code):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    data = json.dumps({"code": code, "device": {"model": "Pixel", "android": "16", "app_version": "1.0"},
                       "sims": [{"slot": 0, "number": None, "country": "MX"}]}).encode()
    writer.write((f"POST /sms/pair HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n\r\n").encode() + data)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    return json.loads(raw.split(b"\r\n\r\n", 1)[1])


async def connect(port, token, device_id):
    ws, status = await wsm.connect("127.0.0.1", port, "/sms/ws",
                                   headers={"Authorization": f"Bearer {token}"}, protocol="paynani-sms.v1")
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": device_id,
                                   "app_version": "1.0", "sims": [{"slot": 0, "number": None, "country": "MX"}]}))
    while json.loads(await asyncio.wait_for(ws.recv(), 5)).get("type") != "welcome":
        pass
    return ws


async def closed_code(ws, timeout):
    try:
        while True:
            await asyncio.wait_for(ws.recv(), timeout)
    except wsm.ConnectionClosed as exc:
        return exc.code
    except asyncio.TimeoutError:
        return None


def sms_in(text):
    return json.dumps({"type": "sms.in", "id": "%064x" % abs(hash(text)),
                       "from": {"e164": "+525511112222", "raw": "5511112222"},
                       "sim": {"slot": 0, "number": None}, "text": text,
                       "sent_at": "2026-10-02T03:09:41-06:00", "received_at": "2026-10-02T03:09:44-06:00",
                       "parts": 1})


async def main():
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER, encoding="utf-8")
    journal = state / "events.jsonl"

    def events():
        return journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []

    # heartbeat_s=3: el watchdog revisa cada segundo.
    g = gw.Gateway(state, journal, roster, heartbeat_s=3)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    st = store_mod.Store(state)

    # --- 1a. revocar con la conexión callada: el watchdog la corta ---------
    body = await http_pair(port, st.new_code())
    ws = await connect(port, body["token"], body["device_id"])
    st.revoke()
    started = time.monotonic()
    code = await closed_code(ws, 5)
    check("revocar con el teléfono conectado -> cierre 4401", 4401, code)
    check("el corte llega antes de un intervalo de latido", True, time.monotonic() - started < 3)

    # --- 1b. revocar y mandar enseguida: el SMS no entra al diario ---------
    body = await http_pair(port, st.new_code())
    ws = await connect(port, body["token"], body["device_id"])
    before = len(events())
    st.revoke()
    await ws.send_text(sms_in("llega después de revocar"))
    code = await closed_code(ws, 5)
    check("un frame después de revocar -> cierre 4401", 4401, code)
    check("ese SMS no entra a events.jsonl", before, len(events()))

    # --- 1c. emparejar otro teléfono corta al anterior y no toca el nuevo ---
    old = await http_pair(port, st.new_code())
    ws = await connect(port, old["token"], old["device_id"])
    st.revoke()
    new = await http_pair(port, st.new_code())
    code = await closed_code(ws, 5)
    check("un emparejamiento nuevo corta la conexión del anterior con 4401", 4401, code)
    await asyncio.sleep(0.3)
    device = st.device() or {}
    check("device.json es del teléfono nuevo", new["device_id"], device.get("device_id"))
    check("la conexión vieja no marca al nuevo como desconectado ni le cambia la hora",
          (False, None), (device.get("connected"), device.get("last_seen")))

    # --- 2. apagado con una conexión colgada --------------------------------
    hanging_reader, hanging_writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.sleep(0.2)
    check("la conexión colgada se registra", True, len(g.clients) >= 1)
    started = time.monotonic()
    server.close()
    await g.shutdown()
    try:
        await asyncio.wait_for(server.wait_closed(), 5)
        closed = True
    except asyncio.TimeoutError:
        closed = False
    check("con una conexión colgada, el servidor cierra", True, closed)
    check("y cierra en menos de 3 s", True, time.monotonic() - started < 3)
    await asyncio.sleep(0.1)
    check("la vigilancia de salud quedó detenida", True,
          g.health_task is not None and (g.health_task.cancelled() or g.health_task.done()))
    hanging_writer.close()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
