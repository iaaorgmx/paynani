#!/usr/bin/env python3
"""
Tests for the API's WhatsApp read actions (WA-6 #558, PRD #550 FR-26, FR-16a).
An assertion script, like the rest of this suite.

Un PaynaniWeb real en un puerto libre y el servicio paynani-whatsapp con el puente
falso, hablando por control.sock como en la instalación. Nada se conecta a WhatsApp
ni sale de la máquina.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import api_tokens, app, notify, users, whatsapp_source  # noqa: E402
from paynani_lib.whatsapp.service import WhatsAppService  # noqa: E402

FAKE = [sys.executable, str(ROOT / "scripts" / "whatsapp_bridge" / "fake_bridge.py")]
NUM = "+15550001111"     # en el roster
OTHER = "+15550002222"   # fuera del roster
ROSTER = f"""# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | {NUM} |
"""
FAST = dict(backoff_s=(0.05, 0.1, 0.2), stable_s=60, health_down_s=0.6, ping_every_s=0.3,
            reply_timeout_s=3.0)

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
wa_root = tmp / "config"
wa_root.mkdir()
wa_env = wa_root / "whatsapp.env"
wa_env.write_text("WHATSAPP_ENABLED=1\n")

user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", "una-contraseña-larga", user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "accounts.json",
                  ledger_path=state / "lifecycle.jsonl", env_path=clone / "no.env", state_dir=state,
                  roster_path=roster, roster_notifier=lambda *a: None,
                  whatsapp_source=whatsapp_source.ControlSocket(state / "whatsapp" / "control.sock", timeout=5),
                  whatsapp_root=wa_root)
store_path = api_tokens.path_for(user_file)
reader, _ = api_tokens.create("lector", permissions=["read"], path=store_path)
sender, _ = api_tokens.create("sms", permissions=["sms.send"], path=store_path)

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


async def main() -> None:
    svc = WhatsAppService(state, roster_path=roster, rules_root=clone, command=FAKE,
                          settings={"WHATSAPP_SEND_INTERVAL_S": "1"}, log=lambda line: None,
                          supervisor_opts=FAST)
    await svc.start()
    await asyncio.wait_for(svc.sup.ready.wait(), 5)
    call = lambda *a, **k: asyncio.to_thread(api, *a, **k)  # noqa: E731
    try:
        await svc.sup.request("link", mode="qr")
        await svc.sup.request("fake.link_done", me="+15550009999")
        await svc.sup.request("fake.message", from_e164=NUM, text="hola desde WhatsApp", key_id="3EB0AAAA")
        await svc.sup.request("fake.message", from_e164=OTHER, text="compra ya, código 123456", key_id="3EB0BBBB")
        for _ in range(100):
            if len((svc.threads().get("threads") or [])) == 2:
                break
            await asyncio.sleep(0.05)

        # --- permisos ----------------------------------------------------------------
        status, body = await call(sender, "ListWhatsAppConversations")
        check("sin read: 403 forbidden con el permiso que falta", (403, "forbidden", "read"),
              (status, body.get("code"), body.get("permission")))
        status, body = await call(sender, "GetWhatsAppThread", number=NUM)
        check("GetWhatsAppThread también pide read", (403, "read"), (status, body.get("permission")))

        # --- la lista -------------------------------------------------------------------
        status, body = await call(reader, "ListWhatsAppConversations")
        threads = {t["number"]: t for t in body.get("threads") or []}
        check("ListWhatsAppConversations: 200 con los dos hilos", (200, {NUM, OTHER}), (status, set(threads)))
        mine = threads.get(NUM, {})
        check("el hilo del roster: nombre del roster, extracto y can_reply",
              ("Julián Flores", "hola desde WhatsApp", True),
              (mine.get("name"), mine.get("last_excerpt"), mine.get("can_reply")))
        other = threads.get(OTHER, {})
        check("fuera del roster (FR-16a): hidden, sin extracto ni tipo ni nombre",
              (True, None, None, None), (other.get("hidden"), other.get("last_excerpt"), other.get("last_kind"),
                                         other.get("name")))
        check("el texto de fuera del roster no sale en ninguna parte de la respuesta", False,
              "123456" in json.dumps(body))
        check("next_before null: no hay más", None, body.get("next_before"))
        status, body = await call(reader, "ListWhatsAppConversations", limit=1)
        check("limit=1: un hilo y next_before para la página siguiente", (1, True),
              (len(body.get("threads") or []), isinstance(body.get("next_before"), str)))
        status, body2 = await call(reader, "ListWhatsAppConversations", limit=1, before=body.get("next_before"))
        check("before=next_before: el otro hilo", True,
              (body2.get("threads") or [{}])[0].get("number") not in {t["number"] for t in body["threads"]})
        for bad in (0, 101, "x"):
            status, body = await call(reader, "ListWhatsAppConversations", limit=bad)
            check(f"limit={bad!r}: 400 invalid_parameter limit", (400, "invalid_parameter", "limit"),
                  (status, body.get("code"), body.get("field")))
        status, body = await call(reader, "ListWhatsAppConversations", before="ayer")
        check("before que no es una fecha: 400 invalid_parameter before", (400, "before"),
              (status, body.get("field")))

        # --- un hilo ----------------------------------------------------------------------
        status, body = await call(reader, "GetWhatsAppThread", number=NUM)
        msgs = body.get("messages") or []
        check("GetWhatsAppThread del roster: el texto", (200, "hola desde WhatsApp"),
              (status, msgs[0].get("text") if msgs else None))
        status, body = await call(reader, "GetWhatsAppThread", number=OTHER)
        msgs = body.get("messages") or []
        check("GetWhatsAppThread fuera del roster: hora y dirección, hidden, sin texto ni archivo",
              (200, 1, True, False, False, False),
              (status, len(msgs), msgs[0].get("hidden") if msgs else None,
               bool(msgs and msgs[0].get("text")), bool(msgs and msgs[0].get("media")), "123456" in json.dumps(body)))
        status, body = await call(reader, "GetWhatsAppThread", number="+1 555 000 1111")
        check("el número se normaliza a E.164", (200, NUM), (status, body.get("number")))
        status, body = await call(reader, "GetWhatsAppThread", number="+15550003333")
        check("un número sin hilo: 404 not_found", (404, "not_found"), (status, body.get("code")))
        status, body = await call(reader, "GetWhatsAppThread")
        check("sin number: 400 missing_parameter", (400, "missing_parameter", "number"),
              (status, body.get("code"), body.get("field")))

        # --- sin WhatsApp o sin servicio ---------------------------------------------------
        wa_env.write_text("WHATSAPP_ENABLED=0\n")
        status, body = await call(reader, "ListWhatsAppConversations")
        check("WhatsApp apagado: 503 whatsapp_unavailable", (503, "whatsapp_unavailable"),
              (status, body.get("code")))
        wa_env.write_text("WHATSAPP_ENABLED=1\n")
        await svc.stop()
        status, body = await call(reader, "GetWhatsAppThread", number=NUM)
        check("servicio caído: 503 whatsapp_unavailable, sin rutas en el mensaje",
              (503, "whatsapp_unavailable", False), (status, body.get("code"), "/" in str(body.get("message"))))
    finally:
        await svc.stop()


asyncio.run(main())
httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
