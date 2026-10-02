#!/usr/bin/env python3
"""
Revocar corta la conexión viva y apagar la pasarela no deja nada colgado
(hallazgos 1 y 2 de QA-4, iaaorgmx/PaynaniApp#28). An assertion script.
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


ROSTER = "# r\n\n# 1. Approved contacts\n\n| Name | Email | Phone |\n|---|---|---|\n| Ana | ana@example.com | +15550001111 |\n"
MID = "a" * 64


async def pair(port, g):
    code = g.store.new_code()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    body = json.dumps({"code": code, "device": {"model": "Pixel", "android": "16", "app_version": "1"}})
    writer.write((f"POST /sms/pair HTTP/1.1\r\nHost: x\r\nContent-Length: {len(body)}\r\n\r\n{body}").encode())
    raw = await reader.read()
    writer.close()
    return json.loads(raw.split(b"\r\n\r\n", 1)[1])["token"]


async def connect(port, token):
    ws, _status = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {token}"}, protocol="paynani-sms.v1")
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "app_version": "1", "sims": [{"slot": 0, "country": "US"}]}))
    while json.loads(await asyncio.wait_for(ws.recv(), 5)).get("type") != "welcome":
        pass
    return ws


def events(journal):
    try:
        return [json.loads(x) for x in Path(journal).read_text().splitlines() if x.strip()]
    except OSError:
        return []


async def main():
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    roster = tmp / "roster.md"
    roster.write_text(ROSTER)
    journal = state / "events.jsonl"
    g = gw.Gateway(state, journal, roster, offline_after_s=3600)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    # --- revocar corta la conexión viva ---------------------------------------------------
    token = await pair(port, g)
    ws = await connect(port, token)
    check("conectado", True, g.conn is not None)
    t0 = time.monotonic()
    g.store.revoke()
    closed = None
    try:
        while True:
            await asyncio.wait_for(ws.recv(), 4)
    except wsm.ConnectionClosed as exc:
        closed = exc.code
    except asyncio.TimeoutError:
        closed = "sin cierre"
    check("revocar cierra el WebSocket con 4401", 4401, closed)
    check("y lo hace en pocos segundos", True, time.monotonic() - t0 < 3.5)
    await asyncio.sleep(0.2)
    check("la pasarela ya no tiene conexión", None, g.conn)

    # --- nada de un revocado entra a events.jsonl -------------------------------------------
    token = await pair(port, g)
    ws = await connect(port, token)
    g.store.revoke()
    text = "no debe entrar"
    await ws.send_text(json.dumps({"type": "sms.in", "id": MID, "from": {"raw": "5550001111"}, "text": text,
                                   "sent_at": "2026-10-02T01:00:00-05:00"}))
    try:
        while True:
            await asyncio.wait_for(ws.recv(), 4)
    except Exception:  # noqa: BLE001
        pass
    check("un SMS que manda el teléfono ya revocado no se escribe", [], [e for e in events(journal) if e.get("event_type") == "sms.received"])

    # --- un teléfono nuevo no hereda el apagado del revocado --------------------------------------
    token = await pair(port, g)
    ws = await connect(port, token)
    check("el teléfono nuevo queda conectado", True, bool(g.store.device().get("connected")))
    await asyncio.sleep(1.5)
    check("y sigue conectado cuando se cierra la conexión del revocado", (True, True), (g.conn is not None, bool(g.store.device().get("connected"))))

    # --- apagar con una conexión colgada ----------------------------------------------------------------
    idle_reader, idle_writer = await asyncio.open_connection("127.0.0.1", port)  # no manda nada
    await asyncio.sleep(0.2)
    check("la pasarela conoce la conexión colgada", True, len(g._writers) >= 2)
    server.close()
    t0 = time.monotonic()
    await g.shutdown()
    try:
        await asyncio.wait_for(server.wait_closed(), 5)
        done = True
    except asyncio.TimeoutError:
        done = False
    check("wait_closed() termina aunque haya una conexión abierta", True, done)
    check("y en poco tiempo", True, time.monotonic() - t0 < 3)
    check("la vigilancia de salud se canceló", True, g.health_task.cancelled() or g.health_task.done())
    idle_writer.close()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
