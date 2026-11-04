#!/usr/bin/env python3
"""
Tests for reactions in WhatsApp (PRD #685 F3, the FR-14 contract on #685) with the fake
bridge: `whatsapp.react` (what the bridge gets, put, replace, remove, bad_emoji, not_found,
not_allowed), `reactions` in `whatsapp.status` and per message in `whatsapp.thread`, a
contact's reaction on the way in (FR-13) with its notice (FR-16a), one from outside the
roster, that a reaction does not count as writing (FR-20) nor shows as a message, the CLI
`whatsapp react` and `event show wa:… --body` of a reaction.
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
    svc._rate_wait = lambda count: None
    await svc.start()
    await asyncio.wait_for(svc.sup.ready.wait(), 5)
    react_event = removed_event = None
    try:
        await svc.sup.request("link", mode="qr")
        await svc.sup.request("fake.link_done", me="+15550009999")
        await until(lambda: svc.sup.state.get("state") == "connected")
        async with Client(svc.socket_path) as c:
            r = await c.ask("whatsapp.status")
            check("whatsapp.status dice reactions: any", "any", r["data"].get("reactions"))

            await svc.sup.request("fake.message", from_e164=NUM, text="¿Tienen mesa a las 8?", key_id="3EB0A001")
            await svc.sup.request("fake.message", from_e164=OTHER, text="promo", key_id="3EB0B001")
            await until(lambda: len(journal(tmp)) >= 2 and NUM in svc.store.wrote_since_link())
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            mine_in = thread["messages"][0]
            other_in = next(e["event_id"] for e in journal(tmp) if not e.get("roster_match"))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="Sí, a las 8")
            out_id = r["data"]["message"]["id"]
            our_key = next(s for s in svc.store.sent() if s["id"] == out_id)["key_id"]
            n = len(journal(tmp))
            sent_before = len((await svc.sup.request("fake.sends"))["sends"])

            # --- la cuenta reacciona ------------------------------------------------------
            r = await c.ask("whatsapp.react", by="web", ref=mine_in["id"], emoji="👍")
            check("whatsapp.react: ok, con el ref y las reacciones", {
                "ref": mine_in["id"], "reactions": [{"emoji": "👍", "count": 1, "mine": True}]}, r.get("data"))
            reacts = (await svc.sup.request("fake.reacts"))["reacts"]
            check("el puente recibe el key_id del mensaje de ellos y su chat", {
                "to": NUM, "target": {"key_id": "3EB0A001", "from_me": False, "chat": NUM[1:] + "@s.whatsapp.net"},
                "emoji": "👍"}, reacts[-1])
            check("una reacción no es un envío (no cuenta para FR-21)", sent_before,
                  len((await svc.sup.request("fake.sends"))["sends"]))
            check("la nuestra no avisa (FR-16a)", n, len(journal(tmp)))
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            got = next(m for m in thread["messages"] if m["id"] == mine_in["id"])
            check("el hilo trae reactions en ese mensaje", [{"emoji": "👍", "count": 1, "mine": True}], got.get("reactions"))
            check("sin reacciones, el campo no viene", False,
                  "reactions" in next(m for m in thread["messages"] if m["id"] == out_id))
            check("el key_id no sale en el hilo", False, "3EB0A001" in json.dumps(thread))
            check("lo que se puede citar y reaccionar no trae actions (#707)", False,
                  any("actions" in m for m in thread["messages"]))

            # --- #707: un envío sin key_id (no salió) --------------------------------------
            svc.store.record_sent({"id": "wo_" + "0" * 32, "to": NUM, "by": "web", "text": "Recibí la foto",
                                   "at": "2026-11-03T18:42:00Z", "status": "failed"})
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            legacy = next(m for m in thread["messages"] if m["id"] == "wo_" + "0" * 32)
            check("#707: sin key_id el hilo trae actions: false", False, legacy.get("actions"))
            check("#707: el envío que salió sigue sin actions", False,
                  "actions" in next(m for m in thread["messages"] if m["id"] == out_id))
            r = await c.ask("whatsapp.react", by="web", ref="wo_" + "0" * 32, emoji="👍")
            check("#707: y react de ese mensaje da not_found", "not_found", r.get("code"))

            await c.ask("whatsapp.react", by="web", ref=mine_in["id"], emoji="👍")
            check("la misma otra vez no vuelve al puente", len(reacts),
                  len((await svc.sup.request("fake.reacts"))["reacts"]))
            r = await c.ask("whatsapp.react", by="web", ref=mine_in["id"], emoji="🥳")
            check("otra la reemplaza (FR-11), cualquier emoji", [{"emoji": "🥳", "count": 1, "mine": True}],
                  r["data"]["reactions"])
            r = await c.ask("whatsapp.react", by="web", ref=mine_in["id"], emoji="")
            check("vacío la quita", [], r["data"]["reactions"])
            check("y al puente le llega vacío", "", (await svc.sup.request("fake.reacts"))["reacts"][-1]["emoji"])
            r = await c.ask("whatsapp.react", by="agent", ref=out_id, emoji="🔥")
            check("en lo que mandamos, from_me", ([{"emoji": "🔥", "count": 1, "mine": True}], True),
                  (r["data"]["reactions"], (await svc.sup.request("fake.reacts"))["reacts"][-1]["target"]["from_me"]))

            # --- errores --------------------------------------------------------------------
            r = await c.ask("whatsapp.react", by="web", ref=mine_in["id"], emoji="👍👍")
            check("dos emojis: invalid bad_emoji", ("invalid", "emoji", "bad_emoji"),
                  (r.get("code"), r.get("field"), r.get("reason")))
            r = await c.ask("whatsapp.react", by="web", ref=mine_in["id"], emoji="hola")
            check("texto: bad_emoji", "bad_emoji", r.get("reason"))
            r = await c.ask("whatsapp.react", by="web", ref="wa:nada", emoji="👍")
            check("un ref que no existe: not_found", "not_found", r.get("code"))
            r = await c.ask("whatsapp.react", by="web", ref=other_in, emoji="👍")
            check("fuera del roster: not_allowed (FR-17)", "not_allowed", r.get("code"))
            await svc.sup.request("fake.fail_after", n=0)
            r = await c.ask("whatsapp.react", by="web", ref=mine_in["id"], emoji="👀")
            await svc.sup.request("fake.fail_after", n=None)
            check("el puente falla: el error llega y no se guarda", (True, False),
                  (r.get("type") == "error", "ours" in (svc.store.reactions().get(mine_in["id"]) or {})))

            # --- Julián reacciona (FR-13, FR-16a) -----------------------------------------
            n = len(journal(tmp))
            await svc.sup.request("fake.reaction", from_e164=NUM, target_key_id=our_key, emoji="❤", key_id="3EB0R001")
            await until(lambda: len(journal(tmp)) > n)
            new = journal(tmp)[n:]
            check("la reacción de Julián avisa una vez", 1, len(new))
            ev_ = new[0]
            check("con kind reaction y un event_id propio", (True, True),
                  (ev_["kind"] == "reaction", ev_["event_id"] not in (mine_in["id"], out_id)))
            check("el aviso dice el emoji y el extracto", True,
                  f", roster] Julián Flores {NUM} reaccionó ❤ a «Sí, a las 8»" in ev_["notification_text"])
            react_event = ev_["event_id"]
            thread = (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]
            got = next(m for m in thread["messages"] if m["id"] == out_id)
            check("el hilo junta la nuestra y la de Julián", [
                {"emoji": "🔥", "count": 1, "mine": True}, {"emoji": "❤", "count": 1, "mine": False}], got.get("reactions"))
            check("la reacción no aparece como mensaje", False, any(m["id"] == react_event for m in thread["messages"]))
            await svc.sup.request("fake.reaction", from_e164=NUM, target_key_id=our_key, emoji="❤", key_id="3EB0R001")
            await asyncio.sleep(0.3)
            check("WhatsApp la entrega otra vez: no avisa dos veces (FR-11a)", n + 1, len(journal(tmp)))

            n = len(journal(tmp))
            await svc.sup.request("fake.reaction", from_e164=NUM, target_key_id=our_key, emoji="🔥", key_id="3EB0R002")
            await until(lambda: len(journal(tmp)) > n)
            got = next(m for m in (await c.ask("whatsapp.thread", by="web", number=NUM))["data"]["messages"]
                       if m["id"] == out_id)
            check("cambiar a la misma que la nuestra: count 2", [{"emoji": "🔥", "count": 2, "mine": True}],
                  got.get("reactions"))
            n = len(journal(tmp))
            await svc.sup.request("fake.reaction", from_e164=NUM, target_key_id=our_key, emoji="", key_id="3EB0R003")
            await until(lambda: len(journal(tmp)) > n)
            check("quitar también avisa", True,
                  f"Julián Flores {NUM} quitó su reacción 🔥 de «Sí, a las 8»" in journal(tmp)[-1]["notification_text"])
            removed_event = journal(tmp)[-1]["event_id"]

            n = len(journal(tmp))
            await svc.sup.request("fake.reaction", from_e164=NUM, target_key_id="NOESTA", emoji="👍", key_id="3EB0R004")
            await asyncio.sleep(0.3)
            check("una reacción a un mensaje que no está no deja nada", n, len(journal(tmp)))

            # --- fuera del roster -------------------------------------------------------------
            n = len(journal(tmp))
            await svc.sup.request("fake.reaction", from_e164=OTHER, target_key_id="3EB0B001", emoji="👍", key_id="3EB0R005")
            await until(lambda: len(journal(tmp)) > n)
            text = journal(tmp)[-1]["notification_text"]
            check("fuera del roster: sólo «reacción de un número fuera del roster»", (True, False, False),
                  ("reacción de un número fuera del roster" in text, "👍" in text, "promo" in text))

            # --- una reacción no abre la conversación (FR-20) -------------------------------
            NEW = "+15550003333"
            (tmp / "roster.md").write_text(ROSTER + f"| Ana | ana@example.com | Human | ana | {NEW} |\n")
            svc.store.record_sent({"id": "wo_" + "2" * 32, "to": NEW, "text": "hola Ana", "by": "agent",
                                   "at": "2026-01-01T00:00:00Z", "status": "sent", "key_id": "3EB0C001"})
            n = len(journal(tmp))
            await svc.sup.request("fake.reaction", from_e164=NEW, target_key_id="3EB0C001", emoji="👍", key_id="3EB0R006")
            await until(lambda: len(journal(tmp)) > n)
            check("una reacción no cuenta como escribir desde la vinculación", False, NEW in svc.store.wrote_since_link())

        # --- la CLI ---------------------------------------------------------------------------
        rc, outp, err = await cli(tmp, "react", mine_in["id"], "👀")
        check("CLI: react sale bien y lo dice", (0, True), (rc, outp.startswith(f"{mine_in['id']}\treacted 👀\t[👀 nuestra]")))
        rc, outp, err = await cli(tmp, "thread", NUM)
        check("CLI: thread muestra las reacciones", (0, True), (rc, "[👀 nuestra]" in outp))
        rc, outp, err = await cli(tmp, "react", mine_in["id"], "--remove")
        check("CLI: --remove la quita", (0, True), (rc, "\tremoved\t[]" in outp))
        rc, outp, err = await cli(tmp, "react", "tg:1", "👍")
        check("CLI: un ref sin forma da 2", 2, rc)
        rc, outp, err = await cli(tmp, "react", mine_in["id"])
        check("CLI: sin emoji ni --remove da 2", 2, rc)
        rc, outp, err = await cli(tmp, "react", mine_in["id"], "👍👍")
        check("CLI: dos emojis da 2", (2, True), (rc, "bad_emoji" in err or "emoji" in err))
    finally:
        await svc.stop()

    from paynani_lib import event_cli
    event_cli.state_dir = lambda: tmp / "state"
    event_cli.roster_file = lambda: tmp / "roster.md"
    event_cli._find = lambda eid, journal_=None: next((e for e in journal(tmp) if e["event_id"] == eid), None)
    for eid, want in ((react_event, f"--- reaction: ❤ on the agent's message ({out_id}) ---\nSí, a las 8"),
                      (removed_event, f"--- reaction: removed 🔥 on the agent's message ({out_id}) ---")):
        buf, errbuf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(errbuf):
            rc = event_cli.run_show(SimpleNamespace(event_id=eid, body=True))
        check(f"event show --body: {want.splitlines()[0]}", (0, True), (rc, want in buf.getvalue()))
    check("y dice cómo reaccionar", True, f"whatsapp react {out_id} <emoji>" in buf.getvalue())


asyncio.run(main(Path(tempfile.mkdtemp())))
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
