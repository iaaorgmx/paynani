#!/usr/bin/env python3
"""
Tests for owner and API orders in the gateway (PRD #489 FR-11, FR-14, FR-15;
PRD #491 FR-19; T2 #505). An assertion script, like the rest of this suite.

Levanta la pasarela en un puerto libre de 127.0.0.1 con un estado temporal y
hace de app, como test_sms_human.py. Nada sale de la máquina.
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

from paynani_lib.sms import cli  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import outgoing  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import thread as thread_mod  # noqa: E402
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
CLIENT = "+525588887777"  # fuera del roster
WEB = "203.0.113.7"


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


async def collect(ws, kind, seconds):
    """Todos los mensajes `kind` que llegan en `seconds`."""
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


async def recv_until(ws, kind, timeout=5):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg.get("type") == kind:
            return msg


def status(order_id, st, **extra):
    msg = {"type": "sms.status", "id": gw.status_id(order_id, st), "order_id": order_id, "status": st,
           "at": time.strftime("%Y-%m-%dT%H:%M:%S-06:00", time.gmtime(time.time() - 6 * 3600)), "parts": 1}
    msg.update(extra)
    return msg


async def connect(port, token, device_id, **caps):
    ws, _ = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {token}"},
                              protocol="paynani-sms.v1")
    hello = {"type": "hello", "protocol": 1, "device_id": device_id, "app_version": "0.9.0",
             "sims": [{"slot": 0, "number": None}]}
    hello.update(caps)
    await ws.send_text(json.dumps(hello))
    await recv_until(ws, "welcome")
    return ws


async def main():
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER, encoding="utf-8")
    journal = state / "events.jsonl"

    def events(kind=None):
        lines = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
        out = [json.loads(line) for line in lines]
        return [e for e in out if kind is None or e.get("event_type") == kind]

    g = gw.Gateway(state, journal, roster, public_url="https://ejemplo.ngrok.io")
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    st = store_mod.Store(state)
    code = st.new_code()
    _, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel 6"},
                                                     "sims": [{"slot": 0, "number": None, "country": "MX"}]})
    token, device_id = body["token"], body["device_id"]

    # --- 1. Una app que no anuncia las capacidades: sólo recibe las del agente ------
    agent = outgoing.queue(st, to=ANA, text="Del agente")
    owner = outgoing.queue(st, to=ANA, text="Del dueño", origin="owner", source=WEB, agent_pause_min=30)
    api = outgoing.queue(st, to=CLIENT, text="Recordatorio", origin="api", token="citas")
    ws = await connect(port, token, device_id)
    outs = await collect(ws, "sms.out", 2.5)
    check("app vieja: recibe la del agente", [agent["id"]], [m["id"] for m in outs])
    check("app vieja: la orden del agente no lleva origin", False, "origin" in outs[0])
    check("app vieja: device.json dice que no acepta las del dueño", (False, False),
          (st.accepts("owner"), st.accepts("api")))
    check("app vieja: las del dueño y la API siguen en outbox", sorted([owner["id"], api["id"]]),
          sorted(o["id"] for o in st.pending_orders(origins=("owner", "api"))))

    # Una orden del dueño que vence mientras la app no la acepta: se marca vencida.
    stale = outgoing.queue(st, to=ANA, text="Vieja", origin="owner", source=WEB)
    order = st.order(stale["id"])
    order["expires_at"] = "2000-01-01T00:00:00Z"
    st.queue_order(order)
    await asyncio.sleep(1.5)
    check("app vieja: la del dueño vencida queda expired", "expired", st.order_statuses(stale["id"])[-1]["status"])
    check("app vieja: y sale de outbox", False, stale["id"] in [o["id"] for o in st.pending_orders(origins=("owner",))])
    check("app vieja: human.jsonl la registra vencida, sin evento",
          [("expired", None)], [(r["status"], r.get("event_id")) for r in st.human_records() if r["local_id"] == stale["id"]])
    await ws.close()
    await asyncio.sleep(0.3)

    # --- 2. Una app que acepta las del dueño y las de la API --------------------
    ws = await connect(port, token, device_id, accepts_owner_out=True, accepts_api_out=True)
    check("app nueva: device.json lo dice", (True, True), (st.accepts("owner"), st.accepts("api")))
    outs = {m["id"]: m for m in await collect(ws, "sms.out", 2.5)}
    check("app nueva: recibe la del dueño con origin owner", "owner", outs.get(owner["id"], {}).get("origin"))
    check("app nueva: recibe la de la API con origin y token", ("api", "citas"),
          (outs.get(api["id"], {}).get("origin"), outs.get(api["id"], {}).get("token")))

    # El teléfono la envía: sent pausa al agente y escribe sms.human_sent con origin web.
    await ws.send_text(json.dumps(status(owner["id"], "accepted")))
    await recv_until(ws, "ack")
    await ws.send_text(json.dumps(status(owner["id"], "sent")))
    await recv_until(ws, "ack")
    human_events = events("sms.human_sent")
    check("sent: un evento sms.human_sent", 1, len(human_events))
    e = human_events[-1]
    check("sent: origin web", "web", e.get("origin"))
    check("sent: la línea dice Tú (PaynaniWeb) → Ana", True, "Tú (PaynaniWeb) → Ana López" in e["notification_text"])
    check("sent: pausa de 30 minutos", (30, True), (e.get("agent_pause_min"), bool(e.get("pause_until"))))
    check("sent: el agente queda en pausa con Ana", True, bool(cli.human_pause(st, ANA)))
    await ws.send_text(json.dumps(status(owner["id"], "delivered")))
    await recv_until(ws, "ack")
    check("delivered: no escribe otro evento", 1, len(events("sms.human_sent")))
    statuses = [r["status"] for r in st.human_records() if r["local_id"] == owner["id"]]
    check("human.jsonl: accepted, sent y delivered", ["accepted", "sent", "delivered"], statuses)
    await ws.send_text(json.dumps(status(owner["id"], "sent")))
    await recv_until(ws, "ack")
    check("sent repetido: sin evento nuevo", 1, len(events("sms.human_sent")))

    # Sin la casilla (pausa 0) no pausa; un failed escribe el evento sin pausa.
    nopause = outgoing.queue(st, to=CLIENT, text="Sin pausa", origin="owner", source=WEB)
    await recv_until(ws, "sms.out")
    await ws.send_text(json.dumps(status(nopause["id"], "failed", error="RESULT_ERROR_NO_SERVICE")))
    await recv_until(ws, "ack")
    e = events("sms.human_sent")[-1]
    check("failed: evento con status failed y sin pausa", ("failed", None, 0),
          (e.get("status"), e.get("pause_until"), e.get("agent_pause_min")))
    check("failed: número fuera del roster, la línea no trae el texto", True,
          "fuera del roster" in e["notification_text"] and "Sin pausa" not in e["notification_text"])
    check("sin casilla: el agente no queda en pausa con el cliente", None, cli.human_pause(st, CLIENT))

    # La de la API no se registra como SMS del dueño.
    await ws.send_text(json.dumps(status(api["id"], "sent")))
    await recv_until(ws, "ack")
    check("api: no va a human.jsonl", [], [r for r in st.human_records() if r["local_id"] == api["id"]])

    # La conversación (paynani sms thread y la web) la muestra como del dueño, vía web.
    items = thread_mod.items(st, journal, number=ANA)
    mine = [(i["kind"], i["via"], i["status"], i["text"]) for i in items if i["text"] in ("Del dueño", "Vieja")]
    check("thread: la enviada, del dueño vía web con su último estado", True,
          ("human", "web", "delivered", "Del dueño") in mine)
    check("thread: la vencida también", True, ("human", "web", "expired", "Vieja") in mine)
    check("thread: la del agente sigue como agente", True,
          any(i["kind"] == "agent" and i["text"] == "Del agente" for i in items))
    pending = outgoing.queue(st, to=ANA, text="En camino", origin="owner", source=WEB)
    held = [i for i in thread_mod.items(st, journal, number=ANA) if i["text"] == "En camino"]
    check("thread: una en cola sale como queued", [("human", "web", "queued")],
          [(i["kind"], i["via"], i["status"]) for i in held] or [(None, None, None)])
    del pending

    # Una trama con hora del futuro lejano no deja al agente pausado décadas (revisión #514).
    future = outgoing.queue(st, to=ANA, text="Del futuro", origin="owner", source=WEB, agent_pause_min=30)
    await recv_until(ws, "sms.out")
    far = status(future["id"], "sent")
    far["at"] = "2099-01-01T00:00:00Z"
    await ws.send_text(json.dumps(far))
    await recv_until(ws, "ack")
    e = events("sms.human_sent")[-1]
    until = gw._iso_epoch(e.get("pause_until"))
    check("at=2099: la pausa empieza con la hora de la pasarela", True,
          until is not None and until <= time.time() + 30 * 60 + 5)
    check("at=2099: el evento no lleva el año 2099", False, "2099" in json.dumps(e))
    await ws.close()
    await asyncio.sleep(0.3)

    # --- 3. Capacidades: sólo true booleano; el origin debe coincidir con el prefijo ---
    for bogus in ("false", 1, "true", None):
        st.touch(accepts_owner_out=bogus, accepts_api_out=bogus)
        check(f"device.json con {bogus!r}: no acepta", (False, False), (st.accepts("owner"), st.accepts("api")))

    disguised = outgoing.queue(st, to=CLIENT, text="Disfrazada", origin="owner", source=WEB)
    order = st.order(disguised["id"])
    order["origin"] = "api"
    st.queue_order(order)
    check("w_ con origin api: pending_orders no la da como del dueño", False,
          disguised["id"] in [o["id"] for o in st.pending_orders(origins=("owner", "api"))])
    ws = await connect(port, token, device_id, accepts_owner_out=True)
    outs = await collect(ws, "sms.out", 2.5)
    check("w_ con origin api: la app que sólo acepta las del dueño no la recibe", False,
          disguised["id"] in [m["id"] for m in outs])
    check("w_ con origin api: nada sale con origin api", False, any(m.get("origin") == "api" for m in outs))

    await ws.close()
    server.close()
    await g.shutdown()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
