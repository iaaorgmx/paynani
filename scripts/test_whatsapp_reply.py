#!/usr/bin/env python3
"""
Tests for replies in WhatsApp (PRD #685 F2, the FR-14 contract on #685) with the fake
bridge: `reply_to` in `whatsapp.send` (the quote the bridge gets, native, dropped,
not_found, other_thread), the quote in `whatsapp.thread` for sent and received messages,
`quote` on the way in (one of ours, one from before paynani), a hidden original, the
notice to the agent (FR-16), `replies` in `whatsapp.status`, the CLI `--reply-to` and
`event show wa:… --body`. The agent's name comes from a patched `envfile.read_env`.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import envfile  # noqa: E402
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
envfile.read_env = lambda: {"AGENT_EMAIL_FROM_NAME": "Agente Prueba"}
passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


class Client:
    def __init__(self, path: Path):
        self.path = path

    async def __aenter__(self):
        self.r, self.w = await asyncio.open_unix_connection(str(self.path))
        return self

    async def __aexit__(self, *exc):
        self.w.close()

    async def ask(self, type_, by="terminal", **fields) -> dict:
        self.w.write((json.dumps({"type": type_, "id": "q_" + secrets.token_hex(16), "by": by, **fields}) + "\n").encode())
        await self.w.drain()
        return json.loads(await asyncio.wait_for(self.r.readline(), 30))


def journal(tmp: Path) -> list[dict]:
    p = tmp / "state" / "events.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


async def until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.03)
    return pred()


async def cli(tmp: Path, *argv: str):
    env = dict(os.environ, PAYNANI_STATE=str(tmp / "state"))
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "scripts" / "paynani"), "whatsapp", *argv, env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(), 60)
    return proc.returncode, out.decode(), err.decode()


async def main(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "roster.md").write_text(ROSTER)
    (tmp / "rules").mkdir(exist_ok=True)
    svc = WhatsAppService(tmp / "state", roster_path=tmp / "roster.md", rules_root=tmp, command=FAKE,
                          settings={"WHATSAPP_SEND_INTERVAL_S": "0"}, log=lambda line: None, supervisor_opts=FAST)
    svc._rate_wait = lambda count: None          # FR-21 tiene su propia prueba; aquí se manda seguido
    await svc.start()
    await asyncio.wait_for(svc.sup.ready.wait(), 5)
    try:
        await svc.sup.request("link", mode="qr")
        await svc.sup.request("fake.link_done", me="+15550009999")
        await until(lambda: svc.sup.state.get("state") == "connected")
        async with Client(svc.socket_path) as c:
            r = await c.ask("whatsapp.status")
            check("whatsapp.status dice replies: true", True, r["data"].get("replies"))

            await svc.sup.request("fake.message", from_e164=NUM, text="¿Tienen mesa\na las 8?", key_id="3EB0A001")
            await svc.sup.request("fake.message", from_e164=OTHER, text="promo", key_id="3EB0B001")
            await until(lambda: len(journal(tmp)) >= 2 and NUM in svc.store.wrote_since_link())
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            mine_in = thread["messages"][0]
            other_in = next(e["event_id"] for e in journal(tmp) if not e.get("roster_match"))

            r = await c.ask("whatsapp.send", by="web", number=NUM, text="Sí, a las 8", reply_to=mine_in["id"])
            check("send con reply_to: reply native", "native", r.get("data", {}).get("reply"))
            sends = (await svc.sup.request("fake.sends"))["sends"]
            check("el puente recibe la cita con el key_id, de ellos", {
                "key_id": "3EB0A001", "from_me": False, "text": "¿Tienen mesa\na las 8?"}, sends[-1].get("quote"))
            out_id = r["data"]["message"]["id"]
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            out = next(m for m in thread["messages"] if m["id"] == out_id)
            check("el hilo trae la cita en lo que salió", {
                "ref": mine_in["id"], "name": "Julián Flores", "excerpt": "¿Tienen mesa a las 8?", "missing": False},
                out.get("reply_to"))
            check("un mensaje sin cita no trae reply_to", False, "reply_to" in mine_in)
            check("el key_id no sale en el hilo", False, "3EB0A001" in json.dumps(thread))

            r = await c.ask("whatsapp.send", by="web", number=NUM, text="x", reply_to=other_in)
            check("un mensaje de otra conversación: other_thread", ("invalid", "reply_to", "other_thread"),
                  (r.get("code"), r.get("field"), r.get("reason")))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="x", reply_to="wa:nada")
            check("un wa: que no existe: not_found", "not_found", r.get("reason"))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="x", reply_to="wo_" + "0" * 32)
            check("un wo_ que no existe: not_found", "not_found", r.get("reason"))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="x", reply_to=7)
            check("un reply_to que no es texto: invalid", ("invalid", "reply_to"), (r.get("code"), r.get("field")))

            # Un envío viejo sin key_id: sale sin cita (dropped)
            svc.store.record_sent({"id": "wo_" + "1" * 32, "to": NUM, "text": "viejo", "by": "agent",
                                   "at": "2026-01-01T00:00:00Z", "status": "failed", "file": None})
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="¿Y esto?", reply_to="wo_" + "1" * 32)
            check("sin key_id del original: reply dropped", "dropped", r.get("data", {}).get("reply"))
            sends = (await svc.sup.request("fake.sends"))["sends"]
            check("y el puente no recibe cita", None, sends[-1].get("quote"))
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            dropped = next(m for m in thread["messages"] if m["id"] == r["data"]["message"]["id"])
            check("el hilo lo marca missing", True, (dropped.get("reply_to") or {}).get("missing"))

            # Julián responde a lo que mandamos
            our_key = next(s for s in svc.store.sent() if s["id"] == out_id)["key_id"]
            n = len(journal(tmp))
            await svc.sup.request("fake.message", from_e164=NUM, text="Perfecto", key_id="3EB0A002",
                                  quote={"key_id": our_key, "from_me": True, "text": "Sí, a las 8"})
            await until(lambda: len(journal(tmp)) > n)
            notice = journal(tmp)[-1]["notification_text"]
            check("el aviso dice a qué responde (FR-16)", True,
                  f"Julián Flores {NUM} (respondiendo a «Sí, a las 8»): Perfecto" in notice)
            reply_event = journal(tmp)[-1]["event_id"]
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            got = next(m for m in thread["messages"] if m.get("text") == "Perfecto")
            check("lo que entró cita lo nuestro, con el nombre del agente", {
                "ref": out_id, "name": "Agente Prueba", "excerpt": "Sí, a las 8", "missing": False}, got.get("reply_to"))

            # Julián cita algo de antes de paynani
            n = len(journal(tmp))
            await svc.sup.request("fake.message", from_e164=NUM, text="Esto", key_id="3EB0A003",
                                  quote={"key_id": "VIEJO1", "from_me": False, "text": "Mensaje viejo"})
            await until(lambda: len(journal(tmp)) > n)
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            old = next(m for m in thread["messages"] if m.get("text") == "Esto")
            check("un original de antes de paynani: ref null y el extracto de WhatsApp", {
                "ref": None, "name": "Julián Flores", "excerpt": "Mensaje viejo", "missing": False}, old.get("reply_to"))

            # Julián se cita a sí mismo
            n = len(journal(tmp))
            await svc.sup.request("fake.message", from_e164=NUM, text="Lo de arriba", key_id="3EB0A004",
                                  quote={"key_id": "3EB0A001", "from_me": False, "text": "¿Tienen mesa?"})
            await until(lambda: len(journal(tmp)) > n)
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            own = next(m for m in thread["messages"] if m.get("text") == "Lo de arriba")
            check("lo que entró cita un mensaje suyo con su ref", mine_in["id"], (own.get("reply_to") or {}).get("ref"))

            # Fuera del roster sin Catch-All: el aviso no dice nada de la cita
            n = len(journal(tmp))
            await svc.sup.request("fake.message", from_e164=OTHER, text="otra promo", key_id="3EB0B002",
                                  quote={"key_id": "3EB0B001", "from_me": False, "text": "promo"})
            await until(lambda: len(journal(tmp)) > n)
            check("fuera del roster el aviso no trae la cita", False,
                  "respondiendo" in journal(tmp)[-1]["notification_text"])

        # --- la CLI ---------------------------------------------------------------------------
        rc, outp, err = await cli(tmp, "send", NUM, "--reply-to", mine_in["id"], "Listo")
        check("CLI: send --reply-to sale bien y lo dice", (0, True), (rc, f"reply_to {mine_in['id']}" in outp))
        rc, outp, err = await cli(tmp, "send", NUM, "--reply-to", "tg:1", "x")
        check("CLI: un --reply-to sin forma da 2", (2, True), (rc, "wa:" in err))
        rc, outp, err = await cli(tmp, "thread", NUM)
        check("CLI: thread muestra los ids y las citas", (0, True, True),
              (rc, mine_in["id"] in outp, "(respondiendo a «Sí, a las 8») Perfecto" in outp))
    finally:
        await svc.stop()

    from paynani_lib import event_cli
    event_cli.state_dir = lambda: tmp / "state"
    event_cli.roster_file = lambda: tmp / "roster.md"
    event_cli._find = lambda eid, journal_=None: next((e for e in journal(tmp) if e["event_id"] == eid), None)
    buf, errbuf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(errbuf):
        rc = event_cli.run_show(SimpleNamespace(event_id=reply_event, body=True))
    outp = buf.getvalue()
    check("event show --body imprime la cita antes del cuerpo", (0, True, True),
          (rc, f"--- in reply to the agent ({out_id}) ---\nSí, a las 8" in outp,
           "--- in reply to" in outp and outp.index("--- in reply to") < outp.index("--- verified body ---")))
    check("y dice cómo citar este mensaje", True, f"--reply-to {reply_event}" in outp)


asyncio.run(main(Path(tempfile.mkdtemp())))
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
