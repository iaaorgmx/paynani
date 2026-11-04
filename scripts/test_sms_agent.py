#!/usr/bin/env python3
"""
Tests for the agent status for PaynaniApp (#692, SMS_GATEWAY.md §13): `agent.get` and
`agent.changed`. An assertion script, like the rest of this suite.

Levanta una pasarela en un puerto libre con un usuario de PaynaniWeb falso y un modelo de
agente falso, empareja un teléfono y hace de app por WebSocket. Nada sale de la máquina.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import agent_api  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import webchat_api  # noqa: E402
from test_whatsapp_relay import SIM, connect, http, until  # noqa: E402

OWNER = {"name": "Dueña Prueba", "email": "duena@example.com"}
UTC = dt.timezone.utc
CST = dt.timezone(dt.timedelta(hours=-6))

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def fake_model() -> dict:
    """La forma de `web/agent.build()`, con fechas en dos zonas."""
    return {
        "now": dt.datetime(2026, 11, 4, 0, 20, tzinfo=CST),
        "name": "Metis", "email": "metis@example.com", "runtime": "claudecode",
        "runtime_label": "Claude Code", "kind": "watch", "status": status[0],
        "session": {"live": True, "armed_at": dt.datetime(2026, 11, 4, 6, 11, 1, tzinfo=UTC),
                    "expires_at": None},
        "last_accepted": dt.datetime(2026, 11, 4, 0, 18, 48, tzinfo=CST),
        "dispatcher": "active", "listener": "active",
        "handled": {"replied": 2, "closed": 16}, "waiting": 0,
        "last_reply": {"at": dt.datetime(2026, 11, 4, 0, 13, 13, tzinfo=CST), "who": "Dueña", "channel": "webchat"},
        "reply_median_s": 42.0,
        "version": {"installed": "0.21.0", "latest": "0.21.0", "checked_at": ""},
        "roster_count": 3, "phone": None, "whatsapp": None, "telegram": {"state": "running", "bot_username": "x_bot"},
        "activity": [{"at": dt.datetime(2026, 11, 4, 6, 13, tzinfo=UTC), "channel": "mail", "state": "replied",
                      "who": "Andy", "what": "Re: hola", "href": "/mail/ver?id=1"}],
    }


status = ["online"]

# --- payload: el modelo de /agent, listo para JSON ---------------------------------------------
data = agent_api.payload(fake_model())
check("payload: sin `now`", False, "now" in data)
check("payload: activity sin href", ["at", "channel", "state", "what", "who"], sorted(data["activity"][0]))
check("payload: fechas en ISO UTC (de CST y de UTC)",
      ("2026-11-04T06:18:48Z", "2026-11-04T06:11:01Z", "2026-11-04T06:13:13Z", "2026-11-04T06:13:00Z"),
      (data["last_accepted"], data["session"]["armed_at"], data["last_reply"]["at"], data["activity"][0]["at"]))
check("payload: lo que falta sigue como null", (None, None, None), (data["session"]["expires_at"], data["phone"], data["whatsapp"]))
check("payload: se puede mandar como JSON", True, isinstance(json.dumps(data), str))


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text("# roster\n", encoding="utf-8")
    logged: list[str] = []
    gw.log = logged.append

    owner = [None]
    broken = [False]

    def model():
        if broken[0]:
            raise OSError("ledger a medias")
        return fake_model()

    def read_status():
        if broken[0]:
            raise OSError("ledger a medias")
        return status[0]

    wc = webchat_api.WebchatRelay(state, owner=lambda: owner[0], agent_name=lambda: "Metis", log=gw.log, watch_s=0.05)
    agent = agent_api.AgentRelay(model=model, status=read_status, log=gw.log, watch_s=0.05)
    g = gw.Gateway(state, state / "events.jsonl", roster, public_url="https://ejemplo.ngrok.io",
                   heartbeat_s=30, whatsapp_check_s=0.1, webchat=wc, agent=agent)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    code = store_mod.Store(state).new_code()
    st, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel"},
                                                      "sims": [{"slot": 0, "number": SIM}]})
    check("pair -> 201", 201, st)
    token, device_id = body["token"], body["device_id"]
    try:
        # --- sin usuario de PaynaniWeb: no se anuncia y responde forbidden ----------------------
        app, welcome = await connect(port, token, device_id)
        check("sin usuario: agent.get no va en accepts", False, "agent.get" in welcome.get("accepts", []))
        r = await app.ask("agent.get")
        check("sin usuario: agent.get -> forbidden", "forbidden", r.get("code"))

        owner[0] = OWNER
        check("al crear el usuario la pasarela cierra con 1012", True,
              await until(lambda: app.closed_code == 1012, timeout=3))
        app, welcome = await connect(port, token, device_id)
        check("con usuario: agent.get en accepts", True, "agent.get" in welcome.get("accepts", []))

        # --- agent.get --------------------------------------------------------------------------
        r = await app.ask("agent.get")
        d = r.get("data") or {}
        check("agent.get: result con el modelo", ("result", "Metis", "online", "Claude Code", 2),
              (r.get("type"), d.get("name"), d.get("status"), d.get("runtime_label"), (d.get("handled") or {}).get("replied")))
        check("agent.get: fechas en UTC y sin href", ("2026-11-04T06:18:48Z", False),
              (d.get("last_accepted"), "href" in (d.get("activity") or [{}])[0]))
        r = await app.ask("agent.get", rid="mal")
        check("agent.get con id mal formado -> missing_field", ("error", "missing_field"), (r.get("type"), r.get("code")))

        # --- agent.changed: una vez por cambio, ninguna sin cambio ------------------------------
        pushes = lambda: [m for m in app.notices if m.get("type") == "agent.changed"]  # noqa: E731
        await asyncio.sleep(0.3)
        check("sin cambio: ningún agent.changed", [], pushes())
        status[0] = "no_session"
        check("al cambiar: un agent.changed con no_session", True,
              await until(lambda: [m.get("status") for m in pushes()] == ["no_session"], timeout=3))
        await asyncio.sleep(0.3)
        check("sigue igual: no se repite", 1, len(pushes()))

        # --- una lectura que falla no tumba nada ni cuenta como cambio --------------------------
        broken[0] = True
        r = await app.ask("agent.get")
        check("modelo que falla -> unavailable", "unavailable", r.get("code"))
        await asyncio.sleep(0.3)
        check("estado que falla: no avisa", 1, len(pushes()))
        broken[0] = False
        status[0] = "online"
        check("se recupera y avisa online", True,
              await until(lambda: [m.get("status") for m in pushes()] == ["no_session", "online"], timeout=3))
        check("el log no lleva datos del agente", False, any("Metis" in line or "duena" in line for line in logged))
    finally:
        server.close()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
