#!/usr/bin/env python3
"""
Tests for a phone paired for Webchat only (PaynaniApp-Agentic#175, Q343 = A).
An assertion script, like the rest of this suite.

La PaynaniApp pública no hace SMS ni llamadas: su saludo trae `"sms": false`. La
pasarela no le manda `sms.out`, no crea órdenes nuevas, no avisa apagones ni batería,
y `status`, `healthcheck` y `sms check` lo dicen. Un saludo sin el campo sigue igual
que siempre. Levanta la pasarela en 127.0.0.1 con un estado temporal y hace de app,
como test_sms_owner_out.py. Nada sale de la máquina.
"""
from __future__ import annotations

import asyncio
import calendar
import io
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import healthcheck  # noqa: E402
from paynani_lib.sms import check as check_mod  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import health  # noqa: E402
from paynani_lib.sms import outgoing  # noqa: E402
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
"""

ANA = "+525511112222"
WEB = "203.0.113.7"


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


async def http(port, method, path, body=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    data = json.dumps(body).encode() if body is not None else b""
    head = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", f"Content-Length: {len(data)}"]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + data)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    payload = raw.split(b"\r\n\r\n", 1)[1]
    return int(raw.split(b" ", 2)[1]), (json.loads(payload) if payload else {})


async def recv_until(ws, kind, timeout=5):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg.get("type") == kind:
            return msg


async def collect(ws, kind, seconds):
    got = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.05, end - time.monotonic())))
        except asyncio.TimeoutError:
            break
        if msg.get("type") == kind:
            got.append(msg)
    return got


async def connect(port, token, device_id, **fields):
    ws, _ = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {token}"},
                              protocol="paynani-sms.v1")
    hello = {"type": "hello", "protocol": 1, "device_id": device_id, "app_version": "1.0.0", "sims": []}
    hello.update(fields)
    await ws.send_text(json.dumps(hello))
    welcome = await recv_until(ws, "welcome")
    return ws, welcome


def refused(st, **kw):
    try:
        outgoing.queue(st, to=ANA, text="Hola", **kw)
    except outgoing.Refused as exc:
        return exc.code
    return None


async def main():
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER, encoding="utf-8")
    journal = state / "events.jsonl"

    g = gw.Gateway(state, journal, roster, public_url="https://ejemplo.ngrok.io")
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    st = store_mod.Store(state)
    code = st.new_code()
    _, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel 6"}, "sims": []})
    token, device_id = body["token"], body["device_id"]
    check("recién emparejado, sin saludo: hace SMS", True, st.sms_enabled())

    # --- 1. La app de siempre: sin el campo, nada cambia -----------------------------
    agent = outgoing.queue(st, to=ANA, text="Del agente")
    ws, welcome_sms = await connect(port, token, device_id)
    check("sin el campo: device.json dice sms true", True, st.device().get("sms"))
    outs = await collect(ws, "sms.out", 2.5)
    check("sin el campo: recibe la orden del agente", [agent["id"]], [m["id"] for m in outs])
    await ws.close()
    await asyncio.sleep(0.3)

    # Sólo el false booleano apaga los SMS.
    for value in ("false", 0, None, "no"):
        ws, _ = await connect(port, token, device_id, sms=value)
        check(f"sms={value!r}: sigue haciendo SMS", True, st.sms_enabled())
        await ws.close()
        await asyncio.sleep(0.3)

    # --- 2. Sólo Webchat ---------------------------------------------------------------
    before = outgoing.queue(st, to=ANA, text="De antes")      # quedó en outbox antes del saludo
    stale = outgoing.queue(st, to=ANA, text="Vencida", origin="owner", source=WEB)
    order = st.order(stale["id"])
    order["expires_at"] = "2000-01-01T00:00:00Z"
    st.queue_order(order)
    # Una de la API pendiente: aunque el saludo anuncie accepts_api_out, no se manda (Metis en #671).
    api = outgoing.queue(st, to=ANA, text="De la API", origin="api", token="citas")
    ws, welcome_wc = await connect(port, token, device_id, sms=False, accepts_owner_out=True, accepts_api_out=True)
    check("sms false: device.json lo guarda", False, st.device().get("sms"))
    check("sms false: sms_enabled es False", False, st.sms_enabled())
    check("Webchat no cambia: el welcome anuncia los mismos tipos y grants",
          (welcome_sms["accepts"], welcome_sms["grants"]), (welcome_wc["accepts"], welcome_wc["grants"]))
    outs = await collect(ws, "sms.out", 2.5)
    check("sms false: no le llega ningún sms.out, ni la que estaba en cola", [], [m["id"] for m in outs])
    check("sms false: la orden vencida queda expired", "expired", st.order_statuses(stale["id"])[-1]["status"])
    check("sms false: la del agente sigue en outbox hasta su hora", True,
          before["id"] in [o["id"] for o in st.pending_orders(origins=("agent",))])
    check("sms false con accepts_api_out: la de la API sigue en outbox, sin enviarse", True,
          api["id"] in [o["id"] for o in st.pending_orders(origins=("api",))])
    order = st.order(api["id"])
    order["expires_at"] = "2000-01-01T00:00:00Z"
    st.queue_order(order)
    await asyncio.sleep(1.5)
    check("sms false con accepts_api_out: la de la API vence a su hora", "expired",
          st.order_statuses(api["id"])[-1]["status"])
    check("sms false con accepts_api_out: nunca llegó como sms.out", [], [m["id"] for m in await collect(ws, "sms.out", 1.2)])
    queued = sorted(o["id"] for o in st.pending_orders(origins=("agent", "owner", "api")))
    for origin, extra in (("agent", {}), ("owner", {"source": WEB}), ("api", {"token": "citas"})):
        check(f"sms false: una orden nueva de {origin} se rechaza con no_sms_phone", "no_sms_phone",
              refused(st, origin=origin, **extra))
    check("sms false: el rechazo no deja nada nuevo en outbox", queued,
          sorted(o["id"] for o in st.pending_orders(origins=("agent", "owner", "api"))))

    # Batería: con el teléfono conectado, aunque traiga una lectura baja, no hay aviso.
    now = time.time()
    st.touch(battery_pct=5, charging=False, battery_measured_at=stamp(now - 10),
             battery_received_at=stamp(now - 10), battery_unplugged_at=stamp(now - 3600))
    check("sms false: sin aviso de batería", None, g.battery_tick(now))
    st.touch(sms=True)
    check("control: con SMS, la misma lectura sí avisa", "critical", g.battery_tick(now))
    st.touch(sms=False, battery_alert_level="")
    await ws.close()
    await asyncio.sleep(0.3)

    # Apagón: con la app cerrada no sale sms.gateway.offline.
    g.started_at = now - 3600
    st.touch(connected=False, last_seen=stamp(now - 600), offline_notified=False)
    check("sms false: cerrar la app no es un apagón", None, g.health_tick(now))
    offline = [e for e in (json.loads(x) for x in journal.read_text().splitlines()) if e.get("event_type") == "sms.gateway.offline"] \
        if journal.exists() else []
    check("sms false: no hay sms.gateway.offline en events.jsonl", [], offline)

    # --- 3. status, healthcheck y sms check ---------------------------------------------
    facts = health.phone_facts(state)
    check("phone_facts: sms False", False, facts["sms"])
    check("status: la línea dice Webchat only", True, "Webchat only" in health.describe(facts)[0])
    check("status: sin la sugerencia de abrir Paynani", False, "open Paynani" in health.describe(facts)[0])
    check("healthcheck: sin advertencia por estar desconectado", [], healthcheck.sms_phone_warnings(facts))
    report = check_mod.Report(out=io.StringIO())
    check("sms check: no puede mandar un texto de prueba", False, check_mod.check_phone(report, facts))
    check("sms check: no es FAIL", (False, True), (report.failed, "Webchat only" in report.out.getvalue()))
    st.touch(sms=True)
    facts = health.phone_facts(state)
    check("control: con SMS, desconectado sí advierte", 1, len(healthcheck.sms_phone_warnings(facts)))

    server.close()
    await g.shutdown()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
