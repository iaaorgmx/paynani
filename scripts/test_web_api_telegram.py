#!/usr/bin/env python3
"""
Tests for the API's Telegram read actions and the Telegram Catch-All permission
(TG-5 of #612, PRD #609 FR-30). An assertion script, like the rest of this suite.

Un PaynaniWeb real en un puerto libre y el servicio paynani-telegram contra el servidor
falso de la Bot API, hablando por control.sock como en la instalación. Nada sale de la
máquina.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402
from paynani_lib.web import api_tokens, app, notify, telegram_source, token_pages, users  # noqa: E402

TOKEN = "123456:fake_token_only_for_tests_xxxxxxxxxxxx"
BOT_ID = 987654321
ANA = 7771234501
PEDRO = 7771234503
SECRETS = [TOKEN, str(BOT_ID), str(ANA), str(PEDRO)]
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


tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
clone.mkdir()
roster = clone / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
(clone / "rules").mkdir()
state = clone / "state"
state.mkdir()
tg_root = tmp / "config"
tg_root.mkdir()
tg_env = tg_root / "telegram.env"


def enable(on: bool) -> None:
    if on:
        fd = os.open(tg_env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(f"TELEGRAM_ENABLED=1\nTELEGRAM_TOKEN={TOKEN}\n")
    elif tg_env.exists():
        tg_env.unlink()


enable(True)
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", "una-contraseña-larga", user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "accounts.json",
                  ledger_path=state / "lifecycle.jsonl", env_path=clone / "no.env", state_dir=state,
                  roster_path=roster, roster_notifier=lambda *a: None,
                  telegram_source=telegram_source.ControlSocket(state / "telegram" / "control.sock", timeout=5),
                  telegram_root=tg_root)
store_path = api_tokens.path_for(user_file)
reader, _ = api_tokens.create("lector", permissions=["read"], path=store_path)
tg_reader, _ = api_tokens.create("telegram", permissions=["telegram.read"], path=store_path)
wa_catch, _ = api_tokens.create("wa", permissions=["catchall.whatsapp.write"], path=store_path)
tg_catch, _ = api_tokens.create("tg", permissions=["catchall.telegram.write", "read"], path=store_path)

httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def api(token, action, **params):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", "/api/agent", body=json.dumps({"action": action, **params}),
                 headers={"Host": "agente.ngrok.app", "X-Forwarded-For": "203.0.113.9",
                          "Authorization": "Bearer " + token, "Content-Type": "application/json"})
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


async def until(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


async def main() -> None:
    fake = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot").start()
    svc = TelegramService(state, roster_path=roster, token=TOKEN, api_base=fake.base_url, log=lambda line: None,
                          poll_timeout=1, backoff=(0.05, 0.2), rules_root=clone,
                          settings={"TELEGRAM_SEND_PER_DAY": "50"})
    await svc.start()
    await until(lambda: svc.state == "running")
    call = lambda *a, **k: asyncio.to_thread(api, *a, **k)  # noqa: E731
    seen: list[str] = []
    try:
        fake.private_message(user_id=ANA, first_name="Ana", text="¿Tienen mesa a las 8?")
        fake.private_message(user_id=PEDRO, first_name="Pedro", text="compra ya, código 123456")
        await until(lambda: len(svc.threads({}).get("threads") or []) == 2)

        # --- permisos ----------------------------------------------------------------
        status, body = await call(reader, "ListTelegramConversations")
        check("con read pero sin telegram.read: 403 con el permiso que falta", (403, "forbidden", "telegram.read"),
              (status, body.get("code"), body.get("permission")))
        status, body = await call(reader, "GetTelegramThread", thread="t_" + "0" * 32)
        check("GetTelegramThread también pide telegram.read", (403, "telegram.read"), (status, body.get("permission")))
        status, body = await call(tg_reader, "ListWhatsAppConversations")
        check("telegram.read no da read", (403, "read"), (status, body.get("permission")))
        check("la página de tokens ofrece telegram.read y catchall.telegram.write", (True, True),
              ("telegram.read" in token_pages.PERMISSIONS, "catchall.telegram.write" in token_pages.PERMISSIONS))

        # --- la lista -------------------------------------------------------------------
        status, body = await call(tg_reader, "ListTelegramConversations")
        seen.append(json.dumps(body))
        threads = body.get("threads") or []
        ana = next((t for t in threads if t.get("in_roster")), {})
        pedro = next((t for t in threads if not t.get("in_roster")), {})
        check("ListTelegramConversations: 200 con los dos hilos", (200, 2), (status, len(threads)))
        check("el hilo del roster: nombre del roster, extracto y can_reply", ("Ana López", "¿Tienen mesa a las 8?", True),
              (ana.get("name"), ana.get("last_excerpt"), ana.get("can_reply")))
        check("fuera del roster: hidden, sin extracto", (True, None, False),
              (pedro.get("hidden"), pedro.get("last_excerpt"), pedro.get("can_reply")))
        check("el texto de fuera del roster no sale", False, "123456" in json.dumps(body))
        status, page = await call(tg_reader, "ListTelegramConversations", limit=1)
        check("limit=1: un hilo y next_before", (1, True),
              (len(page.get("threads") or []), isinstance(page.get("next_before"), str)))
        status, page2 = await call(tg_reader, "ListTelegramConversations", limit=1, before=page.get("next_before"))
        check("before=next_before: el otro hilo", True,
              (page2.get("threads") or [{}])[0].get("thread") != page["threads"][0]["thread"])
        for bad in (0, 101, "x"):
            status, body = await call(tg_reader, "ListTelegramConversations", limit=bad)
            check(f"limit={bad!r}: invalid_parameter", (400, "limit"), (status, body.get("field")))

        # --- un hilo ---------------------------------------------------------------------
        status, body = await call(tg_reader, "GetTelegramThread", thread=ana["thread"])
        seen.append(json.dumps(body))
        msgs = body.get("messages") or []
        check("GetTelegramThread del roster: el texto", (200, "¿Tienen mesa a las 8?"),
              (status, msgs[0].get("text") if msgs else None))
        status, body = await call(tg_reader, "GetTelegramThread", thread=pedro["thread"])
        seen.append(json.dumps(body))
        check("GetTelegramThread fuera del roster: hidden, sin mensajes", (200, True, []),
              (status, body.get("hidden"), body.get("messages")))
        status, body = await call(tg_reader, "GetTelegramThread", thread="t_" + "0" * 32)
        check("hilo que no existe: 404 not_found", (404, "not_found"), (status, body.get("code")))
        status, body = await call(tg_reader, "GetTelegramThread", thread=str(ANA))
        check("un id de Telegram en lugar de thread: invalid_parameter", (400, "thread"), (status, body.get("field")))
        status, body = await call(tg_reader, "GetTelegramThread")
        check("sin thread: missing_parameter", (400, "missing_parameter"), (status, body.get("code")))
        check("nada de lo que pidió la API se escribió como mandado", 0,
              sum(1 for x in fake.sent if x["method"] == "sendMessage"))

        # --- Catch-All de Telegram -----------------------------------------------------
        status, body = await call(wa_catch, "SaveCatchAll", channel="telegram", enabled=True,
                                  text="Contesta con amabilidad.", etag="")
        check("SaveCatchAll telegram sin catchall.telegram.write: 403", (403, "catchall.telegram.write"),
              (status, body.get("permission")))
        status, body = await call(tg_catch, "GetCatchAll", channel="telegram")
        check("GetCatchAll telegram con read: off", (200, "telegram", False),
              (status, body.get("channel"), body.get("enabled")))
        status, body = await call(tg_catch, "SaveCatchAll", channel="telegram", enabled=True,
                                  text="Contesta con amabilidad.", etag=body.get("etag", ""))
        check("SaveCatchAll telegram con su permiso: activo", (200, "telegram", True),
              (status, body.get("channel"), body.get("enabled")))
        check("guardó rules/catch-all-telegram.md", True, (clone / "rules" / "catch-all-telegram.md").exists())
        status, body = await call(tg_catch, "SaveCatchAll", channel="telegrama", enabled=False, text="", etag="")
        check("canal que no existe: invalid_parameter channel", (400, "channel"), (status, body.get("field")))
        fake.private_message(user_id=PEDRO, first_name="Pedro", text="¿hacen envíos?")
        await until(lambda: any(not t.get("hidden") for t in svc.threads({}).get("threads") or []
                                if not t.get("in_roster")))
        status, body = await call(tg_reader, "GetTelegramThread", thread=pedro["thread"])
        seen.append(json.dumps(body))
        texts = [m.get("text") for m in body.get("messages") or []]
        check("con el Catch-All: se ve lo que llegó con él, no lo de antes", (["¿hacen envíos?"], False),
              (texts, "123456" in json.dumps(body)))

        # --- ni token ni ids ------------------------------------------------------------
        check("ni el token ni ids de Telegram en las respuestas", [], [s for s in SECRETS if s in "".join(seen)])

        # --- sin Telegram, o con el servicio caído --------------------------------------
        enable(False)
        status, body = await call(tg_reader, "ListTelegramConversations")
        check("sin Telegram configurado: 503 telegram_unavailable", (503, "telegram_unavailable"),
              (status, body.get("code")))
        enable(True)
        await svc.stop()
        status, body = await call(tg_reader, "GetTelegramThread", thread=ana["thread"])
        check("servicio caído: 503 telegram_unavailable", (503, "telegram_unavailable"), (status, body.get("code")))
    finally:
        await svc.stop()
        fake.stop()
        httpd.shutdown()


def run() -> int:
    asyncio.run(main())
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
