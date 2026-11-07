#!/usr/bin/env python3
"""
Citas y reacciones de Webchat desde PaynaniApp, por la pasarela (paynani #745,
SMS_GATEWAY.md §13): `webchat.react`, `reply_to` en `webchat.send`, `reply_to` y `reactions`
en `webchat.thread`, y `webchat.changed` con `what: "reactions"`.

    python3 scripts/test_sms_webchat_react.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import webchat_api  # noqa: E402
from paynani_lib.webchat import store  # noqa: E402
from test_whatsapp_relay import SIM, connect, http, qid  # noqa: E402

OWNER = {"name": "Dueña Prueba", "email": "duena@example.com"}
MISSING = "w_" + "0" * 32

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


async def changed(app, what, timeout=5.0):
    """El siguiente `webchat.changed` con ese `what`; descarta los demás. None si no llega."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        n = await app.notice("webchat.changed", timeout=max(0.05, end - time.monotonic()))
        if n is None:
            return None
        if n.get("what") == what:
            return n
    return None


def last_event(state: Path) -> dict:
    lines = (state / "events.jsonl").read_text().splitlines()
    return json.loads(lines[-1]) if lines else {}


def count_events(state: Path) -> int:
    path = state / "events.jsonl"
    return len(path.read_text().splitlines()) if path.exists() else 0


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text("# roster\n", encoding="utf-8")
    logged: list[str] = []
    gw.log = logged.append

    clock = [1_000_000.0]
    relay = webchat_api.WebchatRelay(state, owner=lambda: OWNER, agent_name=lambda: "Metis",
                                     log=gw.log, clock=lambda: clock[0], watch_s=0.05)
    g = gw.Gateway(state, state / "events.jsonl", roster, public_url="https://ejemplo.ngrok.io",
                   heartbeat_s=30, whatsapp_check_s=0.1, webchat=relay)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    code = store_mod.Store(state).new_code()
    status, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel"},
                                                          "sims": [{"slot": 0, "number": SIM}]})
    check("pair -> 201", 201, status)
    token, device_id = body["token"], body["device_id"]
    try:
        # --- FR-1: el anuncio ---------------------------------------------------------------
        app, welcome = await connect(port, token, device_id)
        check("welcome: webchat.react en accepts", True, "webchat.react" in welcome.get("accepts", []))

        # Un mensaje del agente para citar y reaccionar.
        agent_msg = store.append("agent", "Sí, te lo mandé al correo", state_dir=state)
        await changed(app, "messages")

        r = await app.ask("webchat.thread")
        data = r.get("data") or {}
        check("thread: replies y reactions en true", (True, True), (data.get("replies"), data.get("reactions")))
        first = (data.get("messages") or [{}])[-1]
        check("thread: sin reacciones ni cita, los campos no vienen", (False, False),
              ("reactions" in first, "reply_to" in first))

        # --- FR-3: citar ---------------------------------------------------------------------
        r = await app.ask("webchat.send", text="Gracias", reply_to=agent_msg["id"])
        msg = (r.get("data") or {}).get("message") or {}
        quote = msg.get("reply_to") or {}
        check("send con reply_to: la cita en el mensaje", ("result", agent_msg["id"], False),
              (r.get("type"), quote.get("ref"), quote.get("missing")))
        check("la cita trae el extracto", True, "te lo mandé" in (quote.get("excerpt") or ""))
        envelope = last_event(state)
        check("el aviso de la respuesta dice (PaynaniApp) y cita", (True, True),
              ("(PaynaniApp)" in envelope.get("notification_text", ""),
               "respondiendo a" in envelope.get("notification_text", "")))

        r = await app.ask("webchat.send", text="¿Y este?", reply_to=MISSING)
        quote = ((r.get("data") or {}).get("message") or {}).get("reply_to") or {}
        check("reply_to que ya no está: se guarda con missing", ("result", True, None),
              (r.get("type"), quote.get("missing"), quote.get("ref")))
        r = await app.ask("webchat.send", text="x", reply_to="w_mal")
        check("reply_to sin forma de w_: bad_reply", "bad_reply", r.get("code"))
        r = await app.ask("webchat.send", text="x", reply_to=5)
        check("reply_to que no es texto: invalid", ("invalid", "reply_to"), (r.get("code"), r.get("field")))

        r = await app.ask("webchat.thread")
        cited = [m for m in (r.get("data") or {}).get("messages", []) if m.get("text") == "Gracias"]
        check("thread: el mensaje citado trae reply_to", agent_msg["id"],
              ((cited or [{}])[0].get("reply_to") or {}).get("ref"))

        # --- FR-4 y FR-6: reaccionar ------------------------------------------------------------
        before = count_events(state)
        rid = qid()
        r = await app.ask("webchat.react", rid=rid, ref=agent_msg["id"], emoji="👍")
        check("react: result con las reacciones", ("result", agent_msg["id"], [{"emoji": "👍", "count": 1, "mine": True}]),
              (r.get("type"), (r.get("data") or {}).get("ref"), (r.get("data") or {}).get("reactions")))
        envelope = last_event(state)
        check("react: un evento de reacción", (before + 1, "reaction"), (count_events(state), envelope.get("kind")))
        check("el aviso dice (PaynaniApp) reaccionó 👍", True,
              "Dueña Prueba (PaynaniApp) reaccionó 👍" in envelope.get("notification_text", ""))
        n = await changed(app, "reactions")
        check("webchat.changed reactions, sin contenido", {"type": "webchat.changed", "what": "reactions"}, n)

        r2 = await app.ask("webchat.react", rid=rid, ref=agent_msg["id"], emoji="👍")
        check("reenvío con el mismo id: replayed, sin otro evento", (True, before + 1),
              (r2.get("replayed"), count_events(state)))
        r = await app.ask("webchat.react", rid=rid, ref=agent_msg["id"], emoji="❤️")
        check("el mismo id con otro emoji: invalid id_reused", ("invalid", "id_reused"), (r.get("code"), r.get("reason")))

        r = await app.ask("webchat.thread")
        reacted = [m for m in (r.get("data") or {}).get("messages", []) if m.get("id") == agent_msg["id"]]
        check("thread: el mensaje trae reactions", [{"emoji": "👍", "count": 1, "mine": True}],
              (reacted or [{}])[0].get("reactions"))

        # La del agente se ve como de la otra parte y también avisa al teléfono.
        store.react(agent_msg["id"], "❤️", by="agent", state_dir=state)
        n = await changed(app, "reactions")
        check("la reacción del agente avisa reactions", "reactions", (n or {}).get("what"))

        # La del teléfono es la misma del dueño en la web: otra la reemplaza y "" la quita.
        r = await app.ask("webchat.react", ref=agent_msg["id"], emoji="🔥")
        mine = [x for x in (r.get("data") or {}).get("reactions", []) if x.get("mine")]
        check("otra reemplaza la del dueño", [{"emoji": "🔥", "count": 1, "mine": True}], mine)
        r = await app.ask("webchat.react", ref=agent_msg["id"], emoji="")
        check("emoji vacío la quita; queda la del agente", [{"emoji": "❤️", "count": 1, "mine": False}],
              (r.get("data") or {}).get("reactions"))
        check("quitarla avisa al agente", True, "quitó su reacción 🔥" in last_event(state).get("notification_text", ""))

        # --- errores --------------------------------------------------------------------------
        r = await app.ask("webchat.react", ref=MISSING, emoji="👍")
        check("react a un mensaje que no está: not_found", "not_found", r.get("code"))
        r = await app.ask("webchat.react", ref="w_mal", emoji="👍")
        check("react con ref sin forma: invalid ref", ("invalid", "ref"), (r.get("code"), r.get("field")))
        r = await app.ask("webchat.react", ref=agent_msg["id"], emoji="hola")
        check("react con texto que no es un emoji: bad_emoji", "bad_emoji", r.get("code"))
        r = await app.ask("webchat.react", ref=agent_msg["id"], emoji=7)
        check("react con emoji que no es texto: invalid", ("invalid", "emoji"), (r.get("code"), r.get("field")))

        # --- el tope es uno solo para mensajes y reacciones ---------------------------------------
        clock[0] += 120
        for i in range(webchat_api.RATE_MAX - 1):
            await app.ask("webchat.send", text=f"r{i}")
        r = await app.ask("webchat.react", ref=agent_msg["id"], emoji="👀")
        check("la reacción 20 del minuto entra", "result", r.get("type"))
        r = await app.ask("webchat.react", ref=agent_msg["id"], emoji="👌")
        check("la 21 (mensajes y reacciones juntos): rate_limited", "rate_limited", r.get("code"))

        joined = "\n".join(logged)
        check("el log no trae emojis ni textos", (False, False), ("👍" in joined, "Gracias" in joined))
    finally:
        await g.shutdown()
        server.close()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
