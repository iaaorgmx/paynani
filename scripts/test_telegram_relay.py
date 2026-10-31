#!/usr/bin/env python3
"""
Tests for Telegram from PaynaniApp through the SMS gateway (TELEGRAM.md §6, PRD #609
FR-29a; TG-5 of #612). An assertion script, like the rest of this suite.

Levanta el servicio paynani-telegram contra el servidor falso de la Bot API y una
pasarela en un puerto libre, empareja un teléfono y hace de app por WebSocket. Nada sale
de la máquina.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import telegram_api  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402
from test_whatsapp_relay import SIM, connect, http, qid, until  # noqa: E402

TOKEN = "123456:fake_token_only_for_tests_x"
BOT_ID = 987654321
ANA = 7771234501
PEDRO = 7771234503
SECRETS = [TOKEN, str(BOT_ID), str(ANA), str(PEDRO)]
TG_TYPES = ["telegram.status", "telegram.threads", "telegram.thread", "telegram.send"]
ROSTER = """\
| Name | Email | Telegram | Type |
|---|---|---|---|
| Ana López | ana@example.com | %d | Human |
""" % ANA

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def sends(api) -> list[dict]:
    return [x["params"] for x in api.sent if x["method"] == "sendMessage"]


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER, encoding="utf-8")

    logged: list[str] = []
    gw.log = logged.append
    api = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot").start()
    svc = TelegramService(state, roster_path=roster, token=TOKEN, api_base=api.base_url, log=lambda line: None,
                          poll_timeout=1, backoff=(0.05, 0.2), rules_root=tmp,
                          settings={"TELEGRAM_SEND_PER_DAY": "50"})
    await svc.start()
    await until(lambda: svc.state == "running")
    enabled = [True]
    relay = telegram_api.TelegramRelay(state, log=gw.log, configured=lambda: enabled[0], timeout_s=5)

    g = gw.Gateway(state, state / "events.jsonl", roster, public_url="https://ejemplo.ngrok.io",
                   heartbeat_s=30, whatsapp_check_s=0.2, telegram=relay)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    code = store_mod.Store(state).new_code()
    status, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel"},
                                                          "sims": [{"slot": 0, "number": SIM}]})
    check("pair -> 201", 201, status)
    token, device_id = body["token"], body["device_id"]
    seen: list[str] = []   # todo lo que le llegó a la app, para buscar secretos al final
    try:
        app, welcome = await connect(port, token, device_id)
        seen.append(json.dumps(welcome))
        accepts = welcome.get("accepts") or []
        check("welcome: los 4 tipos telegram.* con Telegram configurado", True, all(t in accepts for t in TG_TYPES))
        check("welcome: ni image, ni watch, ni token, ni roster_candidate", [],
              [t for t in accepts if t.startswith("telegram.") and t not in TG_TYPES])
        check("welcome: sin grants para Telegram (sin WhatsApp, grants vacío)", [], welcome.get("grants"))
        check("welcome: sms.in sigue", True, "sms.in" in accepts)

        # --- status -------------------------------------------------------------------
        r = await app.ask("telegram.status")
        seen.append(json.dumps(r))
        data = r.get("data") or {}
        check("status: running y el @ del bot", ("running", "NegocioBot"), (data.get("state"), data.get("bot_username")))
        check("status: con contadores", True, isinstance(data.get("counters"), dict))

        # --- llega un mensaje: aviso, hilos, hilo --------------------------------------
        app.notices.clear()
        api.private_message(user_id=ANA, first_name="Ana", text="¿Tienen mesa a las 8?")
        n = await app.notice("telegram.changed")
        check("aviso telegram.changed threads, sin datos", {"type": "telegram.changed", "what": "threads"}, n)
        r = await app.ask("telegram.threads")
        seen.append(json.dumps(r))
        threads = (r.get("data") or {}).get("threads") or []
        ana = threads[0] if threads else {}
        check("threads: el hilo de Ana con su nombre del roster", ("Ana López", True, True),
              (ana.get("name"), ana.get("in_roster"), ana.get("can_reply")))
        check("threads: el extracto", "¿Tienen mesa a las 8?", ana.get("last_excerpt"))
        r = await app.ask("telegram.thread", thread=ana.get("thread"))
        seen.append(json.dumps(r))
        msgs = (r.get("data") or {}).get("messages") or []
        check("thread: el mensaje y su kind", ("¿Tienen mesa a las 8?", "text"),
              (msgs[0].get("text"), msgs[0].get("kind")) if msgs else None)
        r = await app.ask("telegram.thread", thread="t_" + "0" * 32)
        check("thread que no existe: not_found", "not_found", r.get("code"))

        # --- contestar -------------------------------------------------------------------
        send_id = qid()
        r = await app.ask("telegram.send", rid=send_id, thread=ana["thread"], text="Sí, a las 8 hay lugar.")
        seen.append(json.dumps(r))
        check("send: result", "result", r.get("type"))
        check("send: salió un mensaje", 1, len(sends(api)))
        r2 = await app.ask("telegram.send", rid=send_id, thread=ana["thread"], text="Sí, a las 8 hay lugar.")
        check("send: el reenvío con el mismo id es el mismo result, replayed", ("result", True),
              (r2.get("type"), r2.get("replayed")))
        check("send: el reenvío no manda otro", 1, len(sends(api)))
        r3 = await app.ask("telegram.send", rid=send_id, thread=ana["thread"], text="otro texto")
        check("send: mismo id con otro cuerpo: invalid id_reused", ("invalid", "id_reused"),
              (r3.get("code"), r3.get("reason")))
        r = await app.ask("telegram.thread", thread=ana["thread"])
        out = [m for m in (r.get("data") or {}).get("messages") or [] if m.get("dir") == "out"]
        check("send: queda by owner (phone:… es el dueño, §4)", ["owner"], [m.get("by") for m in out])
        outbox = [json.loads(line) for p in (state / "telegram").rglob("outbox.jsonl")
                  for line in p.read_text().splitlines() if line.strip()]
        check("outbox.jsonl: by owner", ["owner"], sorted({r["by"] for r in outbox if "by" in r}))

        r = await app.ask("telegram.send", thread=ana["thread"], text="   ")
        check("send vacío: invalid text", ("invalid", "text"), (r.get("code"), r.get("field")))
        r = await app.ask("telegram.send", thread=ana["thread"], text="hola", contact="ana@example.com")
        check("send con contact: invalid contact (sólo thread)", ("invalid", "contact"), (r.get("code"), r.get("field")))
        r = await app.ask("telegram.send", thread=ana["thread"], text="hola", file="/etc/passwd")
        check("send con file: invalid file", ("invalid", "file"), (r.get("code"), r.get("field")))
        r = await app.ask("telegram.send", text="hola")
        check("send sin thread: invalid thread", ("invalid", "thread"), (r.get("code"), r.get("field")))
        check("ninguno de esos salió", 1, len(sends(api)))

        # Dos envíos con el mismo id a la vez: el segundo espera al primero.
        both = {"type": "telegram.send", "id": qid(), "thread": ana["thread"], "text": "uno"}
        a, b = await asyncio.gather(*(relay.handle(dict(both), device_id, configured=True) for _ in range(2)))
        check("send concurrente: los dos result, el segundo replayed", ("result", "result", True),
              (a.get("type"), b.get("type"), b.get("replayed")))
        check("send concurrente: salió una sola vez", 2, len(sends(api)))

        # --- alguien fuera del roster -------------------------------------------------
        app.notices.clear()
        api.private_message(user_id=PEDRO, first_name="Pedro", text="Hola, ¿hacen envíos?")
        await app.notice("telegram.changed")
        r = await app.ask("telegram.threads")
        seen.append(json.dumps(r))
        pedro = next((t for t in (r.get("data") or {}).get("threads") or [] if not t.get("in_roster")), {})
        check("fuera del roster: hidden, sin extracto, sin responder", (True, None, False),
              (pedro.get("hidden"), pedro.get("last_excerpt"), pedro.get("can_reply")))
        r = await app.ask("telegram.thread", thread=pedro.get("thread"))
        seen.append(json.dumps(r))
        check("fuera del roster: hilo sin mensajes", (True, []),
              ((r.get("data") or {}).get("hidden"), (r.get("data") or {}).get("messages")))
        r = await app.ask("telegram.send", thread=pedro.get("thread"), text="hola")
        check("fuera del roster: send not_allowed", "not_allowed", r.get("code"))
        check("Pedro: el texto no llegó a la app", False, "hacen envíos" in "".join(seen))

        # --- lo que la pasarela no reenvía ----------------------------------------------
        codes = []
        for kind in ("telegram.image", "telegram.roster_candidate", "telegram.token_check", "telegram.watch",
                     "telegram.draft", "telegram.stream_open"):
            r = await app.ask(kind, thread=ana["thread"], timeout=3)
            codes.append(r.get("code"))
        check("image, roster_candidate, token_check, watch, draft, stream: unknown_type", ["unknown_type"] * 6, codes)

        # --- ni token ni ids --------------------------------------------------------------
        everything = "".join(seen) + json.dumps(app.notices) + "\n".join(logged)
        check("ni el token ni ids de Telegram en lo que vio la app ni en el log", [],
              [s for s in SECRETS if s in everything])
        check("log: sin el texto de los mensajes", False, "mesa" in "\n".join(logged) or "a las 8" in "\n".join(logged))

        # --- se desactiva Telegram con la app conectada: 1012 y welcome sin Telegram ----
        enabled[0] = False
        await until(lambda: app.closed_code is not None, 3)
        check("configuración cambia: cierre 1012", 1012, app.closed_code)
        app, welcome = await connect(port, token, device_id)
        check("welcome sin Telegram: sin tipos telegram.*", False,
              any(t.startswith("telegram.") for t in welcome.get("accepts") or []))
        r = await app.ask("telegram.status")
        check("sin Telegram configurado: unavailable", "unavailable", r.get("code"))
        enabled[0] = True
        await until(lambda: app.closed_code is not None, 3)
        check("se activa: cierre 1012", 1012, app.closed_code)
        app, welcome = await connect(port, token, device_id)
        check("welcome de nuevo con Telegram", True, "telegram.send" in (welcome.get("accepts") or []))

        # --- el servicio no corre --------------------------------------------------------
        await svc.stop()
        r = await app.ask("telegram.status")
        check("servicio caído: status service_down", "service_down", (r.get("data") or {}).get("state"))
        r = await app.ask("telegram.threads")
        check("servicio caído: threads unavailable", "unavailable", r.get("code"))
        r = await app.ask("telegram.send", thread=ana["thread"], text="hola")
        check("servicio caído: send unavailable", "unavailable", r.get("code"))
        check("la conexión sigue abierta después de los errores", None, app.closed_code)
        r = await relay.handle({"type": "telegram.status", "id": "q_corto"}, device_id, configured=True)
        check("id malo: missing_field id", ("missing_field", "id"), (r.get("code"), r.get("field")))
        await app.ws.close()
    finally:
        await g.shutdown()
        server.close()
        await svc.stop()
        api.stop()


def run() -> int:
    asyncio.run(main())
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
