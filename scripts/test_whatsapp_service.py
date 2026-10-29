#!/usr/bin/env python3
"""
Tests for the paynani-whatsapp service (WA-2 #554, PRD #550 FR-6 to FR-23;
WHATSAPP_BRIDGE.md §11) with the fake bridge, through control.sock.
An assertion script, like the rest of this suite.

Nada se conecta a WhatsApp: el puente falso sigue el contrato y las órdenes `fake.*`
simulan lo que llega.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import stat
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.whatsapp.service import WhatsAppService  # noqa: E402

FAKE = [sys.executable, str(ROOT / "scripts" / "whatsapp_bridge" / "fake_bridge.py")]
NUM = "+15550001111"     # en el roster
OTHER = "+15550002222"   # fuera del roster
ROSTER = f"""# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | {NUM} |
| Iris | iris@example.com | AI Agent | irisclaudetob |  |
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


def qid() -> str:
    return "q_" + secrets.token_hex(16)


class Client:
    def __init__(self, path: Path):
        self.path = path

    async def __aenter__(self):
        self.r, self.w = await asyncio.open_unix_connection(str(self.path))
        return self

    async def __aexit__(self, *exc):
        self.w.close()

    async def raw(self, obj) -> dict:
        self.w.write((json.dumps(obj) + "\n").encode())
        await self.w.drain()
        return json.loads(await asyncio.wait_for(self.r.readline(), 30))

    async def ask(self, type_, by="terminal", **fields) -> dict:
        return await self.raw({"type": type_, "id": qid(), "by": by, **fields})

    async def notice(self, timeout=3.0):
        return json.loads(await asyncio.wait_for(self.r.readline(), timeout))


def journal(tmp: Path) -> list[dict]:
    p = tmp / "state" / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


async def until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.03)
    return False


def make(tmp: Path, **kw) -> WhatsAppService:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "roster.md").write_text(ROSTER)
    (tmp / "rules").mkdir(exist_ok=True)
    opts = dict(roster_path=tmp / "roster.md", rules_root=tmp, command=FAKE,
                settings={"WHATSAPP_SEND_INTERVAL_S": "3"}, log=lambda line: None,
                supervisor_opts=FAST)
    opts.update(kw)
    return WhatsAppService(tmp / "state", **opts)


async def started(svc: WhatsAppService) -> None:
    await svc.start()
    await asyncio.wait_for(svc.sup.ready.wait(), 5)


async def scenario_main(tmp: Path) -> None:
    svc = make(tmp)
    await started(svc)
    sock = svc.socket_path
    try:
        check("control.sock existe en 0600 (§11)", 0o600, stat.S_IMODE(os.lstat(sock).st_mode))
        check("state/whatsapp en 0700", 0o700, stat.S_IMODE(os.stat(svc.layout.root).st_mode))
        async with Client(sock) as c:
            # protocolo
            r = await c.raw({"type": "whatsapp.status", "by": "terminal"})
            check("sin id: missing_field id", ("missing_field", "id"), (r.get("code"), r.get("field")))
            r = await c.raw({"type": "whatsapp.status", "id": qid(), "by": "root"})
            check("by desconocido: missing_field by", ("missing_field", "by"), (r.get("code"), r.get("field")))
            r = await c.ask("whatsapp.nope")
            check("tipo desconocido: unknown_type", "unknown_type", r.get("code"))
            c.w.write(b"{no json\n")
            await c.w.drain()
            check("línea rota: bad_json", "bad_json", (await c.notice()).get("code"))

            r = await c.ask("whatsapp.status")
            check("status sin vincular: unlinked", "unlinked", r["data"]["state"])
            check("status: linking null", None, r["data"]["linking"])

            # vincular por QR, luego por código (reemplaza)
            r = await c.ask("whatsapp.link", mode="qr")
            qr_id = r["data"]["link_id"]
            check("link qr: link_id l_ + 32 hex", True, qr_id.startswith("l_") and len(qr_id) == 34)
            check("link qr: trae el QR", True, str(r["data"].get("qr", "")).startswith("2@"))
            r = await c.ask("whatsapp.link_current", link_id=qr_id)
            check("link_current: waiting con el QR", ("waiting", True),
                  (r["data"]["state"], bool(r["data"].get("qr"))))
            r = await c.ask("whatsapp.status")
            check("status: linking dice quién y el modo", ("terminal", "qr"),
                  (r["data"]["linking"]["by"], r["data"]["linking"]["mode"]))
            r = await c.ask("whatsapp.link_current", link_id="l_" + "0" * 32)
            check("link_current con otro id: not_found", "not_found", r.get("code"))
            r = await c.ask("whatsapp.link", mode="code")
            check("link code sin número: invalid", "invalid", r.get("code"))
            r = await c.ask("whatsapp.link", by="phone:abc", mode="code", number=NUM)
            code_id = r["data"]["link_id"]
            check("link code: el código sale una vez en el result", True,
                  len(r["data"].get("code") or "") == 9)
            check("link code: expires_in_s hasta 180", True, 0 < r["data"]["expires_in_s"] <= 180)
            r = await c.ask("whatsapp.link_current", link_id=code_id)
            check("link_current de código: sin el código (FR-6a)", (True, None),
                  ("code" not in r["data"], r["data"].get("qr")))
            r = await c.ask("whatsapp.link_current", link_id=qr_id)
            check("el QR anterior: ended replaced", ("ended", "replaced"),
                  (r["data"]["state"], r["data"]["reason"]))

            await svc.sup.request("fake.link_done")
            check("vinculado: status connected", True,
                  await until(lambda: svc.sup.state.get("state") == "connected"))
            r = await c.ask("whatsapp.link_current", link_id=code_id)
            check("link_current tras vincular: ended linked", ("ended", "linked"),
                  (r["data"]["state"], r["data"]["reason"]))
            check("link.json guarda el número, no secretos", NUM, svc.store.link_info().get("me"))
            r = await c.ask("whatsapp.link", mode="qr")
            check("link estando vinculado: already_linked", "already_linked", r.get("code"))

            # FR-20: no se escribe primero
            r = await c.ask("whatsapp.send", number=NUM, text="hola")
            check("send antes de que escriba: not_started", "not_started", r.get("code"))
            r = await c.ask("whatsapp.send", number=OTHER, text="hola")
            check("send fuera del roster: not_allowed", "not_allowed", r.get("code"))

            # llega un mensaje del roster
            await svc.sup.request("fake.message", from_e164=NUM, text="hola Metis", key_id="3EB0AAAA")
            check("mensaje del roster: al diario", True,
                  await until(lambda: any(e["event_type"] == "whatsapp.received" for e in journal(tmp))))
            ev = [e for e in journal(tmp) if e["event_type"] == "whatsapp.received"][0]
            check("evento: id wa:<dígitos>:<hash>", True, ev["event_id"].startswith("wa:15550001111:"))
            check("evento: roster_match y nombre", (True, "Julián Flores"),
                  (ev["roster_match"], ev["sender"]["name"]))
            check("evento: el aviso trae el extracto", True, "hola Metis" in ev["notification_text"])
            check("evento: el texto no va en el sobre", True, "text" not in ev)
            await svc.sup.request("fake.message", from_e164=NUM, text="hola Metis", key_id="3EB0AAAA")
            await asyncio.sleep(0.3)
            check("el mismo key_id otra vez: un solo evento (FR-11a)", 1,
                  sum(1 for e in journal(tmp) if e["event_type"] == "whatsapp.received"))
            check("allowed del puente: el contacto que escribió", True,
                  await until(lambda: svc.sup.allowed == [NUM]))
            ledger = (tmp / "state" / "lifecycle.jsonl").read_text()
            check("el ledger lo ve como observed", True, ev["event_id"] in ledger)

            # contestar
            r = await c.ask("whatsapp.send", by="agent", number=NUM, text="hola Julián")
            check("send después de que escribió: ok", (True, "sent"),
                  (r.get("ok"), (r.get("data") or {}).get("message", {}).get("status")))
            r = await c.ask("whatsapp.send", by="agent", number=NUM, text="otra")
            check("segundo envío enseguida: rate_limited con retry_after_s", ("rate_limited", True),
                  (r.get("code"), 1 <= (r.get("retry_after_s") or 0) <= 3))
            r = await c.ask("whatsapp.send", number=NUM, text="")
            check("texto vacío: invalid", "invalid", r.get("code"))
            r = await c.ask("whatsapp.send", number=NUM, text="x" * 4001)
            check("más de 4000: invalid", "invalid", r.get("code"))

            # archivos (FR-22)
            outside = tmp / "secreto.txt"
            outside.write_text("no")
            r = await c.ask("whatsapp.send", number=NUM, text="", file=str(outside))
            check("archivo fuera de outbox/: not_allowed", ("not_allowed", "file_dir"),
                  (r.get("code"), r.get("reason")))
            link = svc.layout.outbox / "enlace.txt"
            link.symlink_to(outside)
            r = await c.ask("whatsapp.send", number=NUM, text="", file=str(link))
            check("enlace dentro de outbox/: not_allowed", ("not_allowed", "file_type"),
                  (r.get("code"), r.get("reason")))
            r = await c.ask("whatsapp.send", number=NUM, text="", file="outbox/x.txt")
            check("ruta relativa: not_allowed", "not_allowed", r.get("code"))
            check("check_file acepta un archivo de outbox/", True,
                  _ok(lambda: svc.check_file(str(_touch(svc.layout.outbox / "factura.pdf")))))

            # alguien fuera del roster, sin Catch-All
            await svc.sup.request("fake.message", from_e164=OTHER, text="compra ya", key_id="3EB0BBBB")
            await until(lambda: sum(1 for e in journal(tmp) if e["event_type"] == "whatsapp.received") == 2)
            ev2 = [e for e in journal(tmp) if e["event_type"] == "whatsapp.received"][-1]
            check("fuera del roster: roster_match false", False, ev2["roster_match"])
            check("fuera del roster: el aviso no trae el texto (FR-13)", False,
                  "compra ya" in ev2["notification_text"])
            check("fuera del roster: allowed no cambia", [NUM], svc.sup.allowed)

            # hilos (FR-24, FR-25)
            r = await c.ask("whatsapp.threads", by="web")
            rows = {t["number"]: t for t in r["data"]["threads"]}
            check("threads: los dos números", {NUM, OTHER}, set(rows))
            check("threads: el del roster, con nombre y can_reply", ("Julián Flores", True),
                  (rows[NUM]["name"], rows[NUM]["can_reply"]))
            check("threads: el de fuera, oculto (FR-16a)", (True, None, False),
                  (rows[OTHER].get("hidden"), rows[OTHER]["last_excerpt"], rows[OTHER]["can_reply"]))
            r = await c.ask("whatsapp.thread", by="web", number=NUM)
            dirs = [m["dir"] for m in r["data"]["messages"]]
            check("thread: el recibido y el enviado", ["in", "out"], sorted(dirs))
            out = [m for m in r["data"]["messages"] if m["dir"] == "out"][0]
            check("thread: el enviado con su estado y quién", ("agent", True),
                  (out["by"], out["status"] in ("sent", "server")))
            r = await c.ask("whatsapp.thread", by="web", number=OTHER)
            check("thread de fuera: mensajes ocultos, sin texto", (True, None),
                  (r["data"]["messages"][0].get("hidden"), r["data"]["messages"][0].get("text")))
            r = await c.ask("whatsapp.thread", by="web", number="+15559999999")
            check("thread sin mensajes: not_found", "not_found", r.get("code"))
            r = await c.ask("whatsapp.threads", by="web", limit=0)
            check("threads limit 0: invalid", "invalid", r.get("code"))

            # llamadas (FR-18)
            await svc.sup.request("fake.call", from_e164=NUM, status="missed")
            check("llamada perdida: call.missed con channel whatsapp", True, await until(
                lambda: any(e["event_type"] == "call.missed" and e.get("channel") == "whatsapp"
                            for e in journal(tmp))))

            # watch
            async with Client(sock) as w:
                r = await w.ask("whatsapp.watch", by="web")
                check("watch: watching y el status", (True, "connected"),
                      (r["data"]["watching"], r["data"]["status"]["state"]))
                await svc.sup.request("fake.message", from_e164=NUM, text="otro", key_id="3EB0CCCC")
                n = await w.notice()
                check("watch: whatsapp.changed threads", ("whatsapp.changed", "threads"),
                      (n.get("type"), n.get("what")))

            # salud (FR-5)
            await svc.sup.request("fake.disconnect")
            check("más de health_down_s sin conexión: whatsapp.health down", True, await until(
                lambda: any(e["event_type"] == "whatsapp.health" and "down" in e["event_id"]
                            for e in journal(tmp)), 4))

            # el roster cambia: allowed se recalcula
            await svc.sup.request("fake.reconnect")
            (tmp / "roster.md").write_text(ROSTER.replace(NUM, "+15550003333"))
            os.utime(tmp / "roster.md", (time.time() + 5, time.time() + 5))
            check("quitar al contacto del roster lo quita de allowed", True,
                  await until(lambda: svc.sup.allowed == [], 4))
            (tmp / "roster.md").write_text(ROSTER)
            os.utime(tmp / "roster.md", (time.time() + 10, time.time() + 10))
            await until(lambda: svc.sup.allowed == [NUM], 4)

            # desvincular
            r = await c.ask("whatsapp.unlink")
            check("unlink: ok", True, r.get("ok"))
            check("unlink: sin link.json ni auth/creds.json", (False, False),
                  ((svc.layout.root / "link.json").exists(), (svc.layout.auth / "creds.json").exists()))
            r = await c.ask("whatsapp.status")
            check("status tras unlink: unlinked", "unlinked", r["data"]["state"])
    finally:
        await svc.stop()
    check("stop: el socket se borra", False, os.path.lexists(sock))


async def scenario_qr_idle(tmp: Path) -> None:
    svc = make(tmp, qr_idle_s=0.4)
    await started(svc)
    try:
        async with Client(svc.socket_path) as c:
            r = await c.ask("whatsapp.link", mode="qr")
            lid = r["data"]["link_id"]
            await asyncio.sleep(2.2)
            r = await c.ask("whatsapp.link_current", link_id=lid)
            check("QR sin nadie que pregunte: ended canceled (§11)", ("ended", "canceled"),
                  (r["data"]["state"], r["data"]["reason"]))
            r = await c.ask("whatsapp.link", mode="code", number=NUM)
            lid = r["data"]["link_id"]
            await asyncio.sleep(2.2)
            r = await c.ask("whatsapp.link_current", link_id=lid)
            check("el código no se cancela por silencio", "waiting", r["data"]["state"])
    finally:
        await svc.stop()


async def scenario_catch_all(tmp: Path) -> None:
    svc = make(tmp)
    (tmp / "rules" / "catch-all.md").write_text(
        "---\nversion: 1\nenabled: true\n---\n\nReenvía a Julián.\n")
    await started(svc)
    try:
        await svc.sup.request("link", mode="qr")
        await svc.sup.request("fake.link_done", me="+15550009999")
        await svc.sup.request("fake.message", from_e164=OTHER, text="promo", key_id="3EB0DDDD")
        await until(lambda: any(e["event_type"] == "whatsapp.received" for e in journal(tmp)))
        ev = [e for e in journal(tmp) if e["event_type"] == "whatsapp.received"][0]
        check("Catch-All activo: el evento dice el archivo", {"file": "rules/catch-all.md", "status": "active"},
              ev.get("catch_all"))
        check("Catch-All activo: el aviso trae el texto", True, "promo" in ev["notification_text"])
        async with Client(svc.socket_path) as c:
            r = await c.ask("whatsapp.thread", by="web", number=OTHER)
            check("Catch-All activo: el hilo muestra el texto", "promo", r["data"]["messages"][0].get("text"))
            check("Catch-All: can_reply sigue en false (fuera del roster)", False, r["data"]["can_reply"])
        (tmp / "rules" / "catch-all.md").unlink()
        async with Client(svc.socket_path) as c:
            r = await c.ask("whatsapp.thread", by="web", number=OTHER)
            check("Catch-All apagado después: el hilo se oculta (FR-16a)", True,
                  r["data"]["messages"][0].get("hidden"))
    finally:
        await svc.stop()


async def scenario_socket_safety(tmp: Path) -> None:
    svc = make(tmp)
    svc.layout.prepare()
    svc.socket_path.write_text("no soy un socket")
    try:
        await svc.start()
        check("un archivo en lugar del socket: no arranca", False, True)
    except Exception as exc:  # noqa: BLE001
        check("un archivo en lugar del socket: UnsafePath", "UnsafePath", type(exc).__name__)
    finally:
        await svc.stop()
    check("el archivo ajeno sigue ahí", "no soy un socket", svc.socket_path.read_text())


def _touch(p: Path) -> Path:
    p.write_text("x")
    return p


def _ok(fn) -> bool:
    try:
        fn()
        return True
    except Exception:  # noqa: BLE001
        return False


async def main_async() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        await scenario_main(tmp / "main")
        await scenario_qr_idle(tmp / "idle")
        await scenario_catch_all(tmp / "catch")
        await scenario_socket_safety(tmp / "sock")


if __name__ == "__main__":
    asyncio.run(main_async())
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
