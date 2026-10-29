#!/usr/bin/env python3
"""
Tests for WhatsApp from PaynaniApp through the SMS gateway (SMS_GATEWAY.md §12, PRD #550).
An assertion script, like the rest of this suite.

Levanta el servicio paynani-whatsapp con el puente falso y una pasarela en un puerto
libre, empareja un teléfono y hace de app por WebSocket. Nada sale de la máquina.
"""
from __future__ import annotations

import asyncio
import json
import secrets
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
from paynani_lib.sms import whatsapp_api  # noqa: E402
from paynani_lib.whatsapp.service import WhatsAppService  # noqa: E402

FAKE = [sys.executable, str(ROOT / "scripts" / "whatsapp_bridge" / "fake_bridge.py")]
NUM = "+15550001111"     # en el roster
SIM = "+15550009999"     # la SIM del teléfono emparejado
ROSTER = f"""# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | {NUM} |
"""
FAST = dict(backoff_s=(0.05, 0.1, 0.2), stable_s=60, health_down_s=0.6, ping_every_s=0.3,
            reply_timeout_s=3.0)
WA_TYPES = ["whatsapp.status", "whatsapp.threads", "whatsapp.thread", "whatsapp.send",
            "whatsapp.link", "whatsapp.link_cancel", "whatsapp.unlink"]

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def qid() -> str:
    return "q_" + secrets.token_hex(16)


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


class App:
    """La app: una conexión WebSocket que separa respuestas (por `ref`) de avisos."""

    def __init__(self, ws):
        self.ws = ws
        self.notices: list[dict] = []
        self.answers: dict[str, dict] = {}
        self.closed_code = None
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            while True:
                msg = json.loads(await self.ws.recv())
                if msg.get("ref"):
                    self.answers[msg["ref"]] = msg
                else:
                    self.notices.append(msg)
        except wsm.ConnectionClosed as exc:
            self.closed_code = exc.code

    async def send(self, obj):
        await self.ws.send_text(json.dumps(obj))

    async def ask(self, type_, rid=None, timeout=10.0, **fields) -> dict:
        rid = rid or qid()
        self.answers.pop(rid, None)
        await self.send({"type": type_, "id": rid, **fields})
        end = time.monotonic() + timeout
        while rid not in self.answers:
            if time.monotonic() > end:
                return {"timeout": True}
            await asyncio.sleep(0.02)
        return self.answers.pop(rid)

    async def notice(self, type_, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for i, n in enumerate(self.notices):
                if n.get("type") == type_:
                    return self.notices.pop(i)
            await asyncio.sleep(0.02)
        return None


async def until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.03)
    return False


async def connect(port, token, device_id) -> tuple[App, dict]:
    ws, status = await wsm.connect("127.0.0.1", port, "/sms/ws",
                                   headers={"Authorization": f"Bearer {token}"}, protocol="paynani-sms.v1")
    assert status == 101, status
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": device_id, "app_version": "1.0",
                                   "sims": [{"slot": 0, "number": SIM, "country": "US"}]}))
    welcome = json.loads(await asyncio.wait_for(ws.recv(), 5))
    return App(ws), welcome


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER)
    (tmp / "rules").mkdir()

    logged: list[str] = []
    gw.log = logged.append  # la pasarela escribe su log con esta función del módulo
    mails: list[tuple[str, str, str]] = []
    enabled = [True]
    relay = whatsapp_api.WhatsAppRelay(state, notifier=lambda *m: mails.append(m),
                                       owner_email=lambda: "julian@example.com", log=gw.log,
                                       configured=lambda: enabled[0], timeout_s=5)
    svc = WhatsAppService(state, roster_path=roster, rules_root=tmp, command=FAKE,
                          settings={"WHATSAPP_SEND_INTERVAL_S": "1"}, log=lambda line: None,
                          supervisor_opts=FAST)
    await svc.start()
    await asyncio.wait_for(svc.sup.ready.wait(), 5)

    g = gw.Gateway(state, state / "events.jsonl", roster, public_url="https://ejemplo.ngrok.io",
                   heartbeat_s=30, whatsapp=relay, whatsapp_check_s=0.2)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    code = store_mod.Store(state).new_code()
    status, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel"},
                                                          "sims": [{"slot": 0, "number": SIM}]})
    check("pair -> 201", 201, status)
    token, device_id = body["token"], body["device_id"]
    try:
        app, welcome = await connect(port, token, device_id)
        accepts = welcome.get("accepts") or []
        check("welcome: los tipos whatsapp.* con WhatsApp configurado", True, all(t in accepts for t in WA_TYPES))
        check("welcome: sms.in sigue", True, "sms.in" in accepts)
        check("welcome: grants whatsapp.admin al teléfono emparejado", ["whatsapp.admin"], welcome.get("grants"))

        # --- status ------------------------------------------------------------------
        r = await app.ask("whatsapp.status")
        check("status: unlinked", "unlinked", r.get("data", {}).get("state"))
        check("status: link_number de la SIM", SIM, r["data"].get("link_number"))
        check("status: linking null", None, r["data"].get("linking"))

        # --- vincular por código -------------------------------------------------------
        link_id = qid()
        r = await app.ask("whatsapp.link", rid=link_id)
        got = r.get("data", {}).get("code") or ""
        check("link: devuelve el código", True, len(got) == 9 and got[4] == "-")
        check("link: expires_in_s entero de 0 a 180", True,
              isinstance(r["data"].get("expires_in_s"), int) and 0 <= r["data"]["expires_in_s"] <= 180)
        check("link: sin link_id ni QR para la app", (False, False), ("link_id" in r["data"], "qr" in r["data"]))
        check("link: el servicio usó el número de la SIM", SIM, svc.link.number if svc.link else None)
        r2 = await app.ask("whatsapp.link", rid=link_id)
        check("link: el reenvío con el mismo id es conflict, sin código", ("conflict", False),
              (r2.get("code"), got in json.dumps(r2)))
        r = await app.ask("whatsapp.status")
        linking = r["data"].get("linking") or {}
        check("status: linking.by phone", "phone", linking.get("by"))
        check("status: linking sin el código", False, got in json.dumps(r))
        changes = (state / "whatsapp_changes.jsonl").read_text()
        check("log de cambios: link con device_id", True,
              '"action": "link"' in changes and device_id in changes)
        check("log de cambios: sin el código", False, got in changes)
        await until(lambda: len(mails) >= 1)
        check("correo al dueño por el link", "julian@example.com", mails[0][0] if mails else None)
        check("correo sin el código", False, got in "".join(mails[0]) if mails else True)

        r = await app.ask("whatsapp.link_cancel")
        check("link_cancel: result", "result", r.get("type"))
        r = await app.ask("whatsapp.status")
        check("status: sin vinculación en curso", None, r["data"].get("linking"))

        r = await app.ask("whatsapp.link", number="no-es-numero")
        check("link con número malo: invalid number", ("invalid", "number"), (r.get("code"), r.get("field")))

        # --- vinculado: mensajes, avisos, contestar ----------------------------------
        await app.ask("whatsapp.link")
        await svc.sup.request("fake.link_done")
        n = await app.notice("whatsapp.changed")
        check("aviso whatsapp.changed (status) a la conexión que pidió status", "status", (n or {}).get("what"))
        r = await app.ask("whatsapp.link")
        check("link con cuenta conectada: already_linked", "already_linked", r.get("code"))
        await asyncio.sleep(0.3)
        app.notices.clear()
        await svc.sup.request("fake.message", from_e164=NUM, text="hola desde WhatsApp", key_id="3EB0AAAA")
        n = await app.notice("whatsapp.changed")
        check("aviso whatsapp.changed threads, sin nada del mensaje", {"type": "whatsapp.changed", "what": "threads"}, n)
        r = await app.ask("whatsapp.threads")
        threads = r.get("data", {}).get("threads") or []
        check("threads: el hilo del roster", (NUM, True), (threads[0].get("number"), threads[0].get("can_reply"))
              if threads else None)
        r = await app.ask("whatsapp.thread", number=NUM)
        check("thread: el mensaje", "hola desde WhatsApp", (r.get("data", {}).get("messages") or [{}])[0].get("text"))
        r = await app.ask("whatsapp.thread", number="+15550002222")
        check("thread sin hilo: not_found", "not_found", r.get("code"))

        send_id = qid()
        r = await app.ask("whatsapp.send", rid=send_id, number=NUM, text="Con gusto, lo esperamos.")
        message = r.get("data", {}).get("message") or {}
        check("send: result by owner", ("result", "owner"), (r.get("type"), message.get("by")))
        r2 = await app.ask("whatsapp.send", rid=send_id, number=NUM, text="Con gusto, lo esperamos.")
        check("send: el reenvío es el mismo result con replayed", (True, message.get("id")),
              (r2.get("replayed"), (r2.get("data", {}).get("message") or {}).get("id")))
        r3 = await app.ask("whatsapp.send", rid=send_id, number=NUM, text="otro texto")
        check("send: mismo id con otro cuerpo: invalid id_reused", ("invalid", "id_reused"),
              (r3.get("code"), r3.get("reason")))
        r = await app.ask("whatsapp.thread", number=NUM)
        outs = [m for m in r.get("data", {}).get("messages") or [] if m.get("dir") == "out"]
        check("send: salió una sola vez", 1, len(outs))
        r = await app.ask("whatsapp.send", number=NUM, text="   ")
        check("send vacío: invalid text", ("invalid", "text"), (r.get("code"), r.get("field")))

        # Dos envíos con el mismo id a la vez (el reenvío llega antes que la respuesta):
        # el segundo espera al primero y no sale otro mensaje.
        await asyncio.sleep(1.1)  # WHATSAPP_SEND_INTERVAL_S
        both = {"type": "whatsapp.send", "id": qid(), "number": NUM, "text": "uno"}
        a, b = await asyncio.gather(*(relay.handle(dict(both), device_id, grants=[], configured=True,
                                                   link_number=None) for _ in range(2)))
        check("send concurrente: los dos result, el segundo replayed", ("result", "result", True),
              (a.get("type"), b.get("type"), b.get("replayed")))
        r = await app.ask("whatsapp.thread", number=NUM)
        outs = [m for m in r.get("data", {}).get("messages") or [] if m.get("dir") == "out"]
        check("send concurrente: salió una sola vez", 2, len(outs))

        r = await app.ask("whatsapp.unlink")
        check("unlink: remote true", (True, True), (r.get("type") == "result", r.get("data", {}).get("remote")))
        await until(lambda: len(mails) >= 4)
        actions = [json.loads(line).get("action") for line in
                   (state / "whatsapp_changes.jsonl").read_text().splitlines() if '"action"' in line]
        check("log de cambios: link, link_cancel, link, unlink", ["link", "link_cancel", "link", "unlink"], actions)

        # --- sin whatsapp.admin -----------------------------------------------------
        r = await relay.handle({"type": "whatsapp.unlink", "id": qid()}, device_id, grants=[], configured=True,
                               link_number=None)
        check("sin whatsapp.admin: forbidden", "forbidden", r.get("code"))
        r = await relay.handle({"type": "whatsapp.link", "id": "q_corto"}, device_id, grants=["whatsapp.admin"],
                               configured=True, link_number=None)
        check("id malo: missing_field id", ("missing_field", "id"), (r.get("code"), r.get("field")))

        # --- el log de la pasarela ------------------------------------------------------
        text = "\n".join(logged)
        check("log: sin el código", False, got in text)
        check("log: sin el texto de los mensajes", False, "Con gusto" in text or "hola desde" in text)
        check("log: sin el número completo", False, NUM in text or SIM in text)

        # --- se desactiva WhatsApp con la app conectada: 1012 y welcome sin WhatsApp --
        enabled[0] = False
        await until(lambda: app.closed_code is not None, 3)
        check("configuración cambia: cierre 1012", 1012, app.closed_code)
        app, welcome = await connect(port, token, device_id)
        check("welcome sin WhatsApp: ni tipos ni grants", (False, []),
              (any(t.startswith("whatsapp.") for t in welcome.get("accepts") or []), welcome.get("grants")))
        r = await app.ask("whatsapp.status")
        check("sin WhatsApp configurado: unavailable", "unavailable", r.get("code"))
        enabled[0] = True
        await until(lambda: app.closed_code is not None, 3)
        check("se activa: cierre 1012", 1012, app.closed_code)
        app, welcome = await connect(port, token, device_id)
        check("welcome de nuevo con WhatsApp", True, "whatsapp.status" in (welcome.get("accepts") or []))

        # --- el servicio no corre --------------------------------------------------------
        await svc.stop()
        r = await app.ask("whatsapp.status")
        check("servicio caído: status service_down", ("service_down", SIM),
              (r.get("data", {}).get("state"), r.get("data", {}).get("link_number")))
        r = await app.ask("whatsapp.threads")
        check("servicio caído: threads unavailable", "unavailable", r.get("code"))
        r = await app.ask("whatsapp.link")
        check("servicio caído: link unavailable", "unavailable", r.get("code"))
        check("la conexión sigue abierta después de los errores", None, app.closed_code)
        await app.ws.close()
    finally:
        await g.shutdown()
        server.close()
        await svc.stop()


def run() -> int:
    asyncio.run(main())
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
