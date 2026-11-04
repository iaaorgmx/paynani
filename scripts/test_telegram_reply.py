#!/usr/bin/env python3
"""
Tests for replies in Telegram (PRD #685 F2, the FR-14 contract on #685), against the fake
Bot API: `reply_to` in `telegram.send` (native, dropped, not_found, other_thread), the
quote in `telegram.thread` for sent and received messages, `reply_to_message` on the way
in (a known original, one of ours, one from before paynani), the notice to the agent
(FR-16), `replies` in `telegram.status`, the CLI `--reply-to`, `telegram thread` and
`event show tg:… --body`. The agent's name comes from a patched `envfile.read_env`.
"""

import asyncio
import json
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import envfile  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402

passed = failed = 0
TOKEN = "123456:fake_token_only_for_tests_x"
BOT_ID = 987654321
ANA = 7771234501
BETO = 7771234502
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
ROSTER = """\
| Name | Email | Telegram | Type |
|---|---|---|---|
| Ana López | ana@example.com | %d | Human |
| Beto Ruiz | beto@example.com | %d | Human |
""" % (ANA, BETO)
envfile.read_env = lambda: {"AGENT_EMAIL_FROM_NAME": "Agente Prueba"}


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"ok    {name}")
    else:
        failed += 1
        print(f"FAIL  {name} {detail}")


async def until(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


_n = [0]


async def call(s, kind, by="terminal", **fields):
    _n[0] += 1
    msg = {"type": kind, "id": "q_%032x" % _n[0], "by": by, **fields}
    reader, writer = await asyncio.open_unix_connection(str(s.socket_path))
    writer.write((json.dumps(msg) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


async def cli(env, *argv):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "scripts" / "paynani"), *argv, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(b""), 60)
    return proc.returncode, out.decode(), err.decode()


def methods(api, name):
    return [x["params"] for x in api.sent if x["method"] == name]


def events(state):
    path = state / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


async def thread_of(s, name):
    rows = (await call(s, "telegram.threads", by="web"))["data"]["threads"]
    t = next(x["thread"] for x in rows if x["name"] == name)
    return (await call(s, "telegram.thread", by="web", thread=t))["data"]


async def main_tests():
    state = pathlib.Path(tempfile.mkdtemp())
    (state / "roster.md").write_text(ROSTER, encoding="utf-8")
    api = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot").start()
    s = TelegramService(state, roster_path=state / "roster.md", token=TOKEN, api_base=api.base_url,
                        log=lambda *_: None, poll_timeout=1, backoff=(0.05, 0.2), rules_root=state,
                        settings={"TELEGRAM_SEND_PER_DAY": "50"})
    await s.start()
    await until(lambda: s.state == "running")
    env = dict(os.environ, PAYNANI_STATE=str(state))
    try:
        r = await call(s, "telegram.status", by="web")
        check("telegram.status dice replies: true", r["data"].get("replies") is True, str(r))

        # --- Ana escribe; el agente le responde citándola ----------------------------------
        _, ana_mid = api.private_message(ANA, "¿Tienen mesa\na las 8?", first_name="Ana")
        _, beto_mid = api.private_message(BETO, "Hola, soy Beto", first_name="Beto")
        await until(lambda: len(events(state)) >= 2)
        ana = await thread_of(s, "Ana López")
        ana_in = next(m for m in ana["messages"] if m["dir"] == "in")
        beto = await thread_of(s, "Beto Ruiz")
        beto_in = next(m for m in beto["messages"] if m["dir"] == "in")

        before = len(methods(api, "sendMessage"))
        r = await call(s, "telegram.send", by="web", thread=ana["thread"], text="Sí, a las 8", reply_to=ana_in["ref"])
        check("send con reply_to: ok y reply native", r.get("ok") and r["data"].get("reply") == "native", str(r))
        sent = methods(api, "sendMessage")[before:]
        check("sale con reply_parameters del message_id de Ana", len(sent) == 1
              and sent[0].get("reply_parameters", {}).get("message_id") == ana_mid, str(sent))
        check("y con allow_sending_without_reply", sent[0].get("reply_parameters", {}).get("allow_sending_without_reply") is True)
        out_ref = r["data"]["ref"]
        ana = await thread_of(s, "Ana López")
        out = next(m for m in ana["messages"] if m["ref"] == out_ref)
        check("el hilo trae la cita en lo que salió", out.get("reply_to") == {
            "ref": ana_in["ref"], "name": "Ana López", "excerpt": "¿Tienen mesa a las 8?", "missing": False},
            str(out.get("reply_to")))
        check("un mensaje sin cita no trae reply_to", "reply_to" not in ana_in)
        check("el message_id de Telegram no sale en el hilo", "message_id" not in json.dumps(ana))

        # --- errores del contrato --------------------------------------------------------
        r = await call(s, "telegram.send", by="web", thread=ana["thread"], text="x", reply_to=beto_in["ref"])
        check("un mensaje de otro hilo: invalid other_thread", r.get("code") == "invalid"
              and r.get("field") == "reply_to" and r.get("reason") == "other_thread", str(r))
        r = await call(s, "telegram.send", by="web", thread=ana["thread"], text="x", reply_to="tg:nada")
        check("un ref que no existe: invalid not_found", r.get("code") == "invalid" and r.get("reason") == "not_found", str(r))
        r = await call(s, "telegram.send", by="web", thread=ana["thread"], text="x", reply_to="tgo:" + "0" * 32)
        check("un tgo: que no existe: not_found", r.get("reason") == "not_found", str(r))
        r = await call(s, "telegram.send", by="web", thread=ana["thread"], text="x", reply_to=5)
        check("un reply_to que no es texto: invalid", r.get("code") == "invalid" and r.get("field") == "reply_to", str(r))

        # --- el original ya no está en Telegram: sale sin cita (dropped) -----------------
        api.deleted.add(ana_mid)
        r = await call(s, "telegram.send", by="web", thread=ana["thread"], text="¿Sigue en pie?", reply_to=ana_in["ref"])
        check("con el original borrado: ok y reply dropped", r.get("ok") and r["data"].get("reply") == "dropped", str(r))
        ana = await thread_of(s, "Ana López")
        dropped = next(m for m in ana["messages"] if m["ref"] == r["data"]["ref"])
        check("y el hilo lo marca missing", (dropped.get("reply_to") or {}).get("missing") is True, str(dropped))
        api.deleted.discard(ana_mid)

        # --- citar algo que mandamos, con un archivo --------------------------------------
        outbox = state / "telegram" / "outbox"
        outbox.mkdir(mode=0o700, parents=True, exist_ok=True)
        (outbox / "menu.jpg").write_bytes(JPEG)
        r = await call(s, "telegram.send", by="agent", contact="Ana López", text="el menú",
                       file=str(outbox / "menu.jpg"), reply_to=out_ref)
        photos = methods(api, "sendPhoto")
        check("una foto cita en multipart (JSON como texto)", r.get("ok") and r["data"].get("reply") == "native"
              and photos and json.loads(photos[-1].get("reply_parameters") or "{}").get("message_id") is not None,
              str(r) + str(photos[-1:]))

        # --- Ana responde a lo que mandó el agente --------------------------------------
        rec = next(x for x in s.store.sent() if x["ref"] == out_ref)
        our_mid = rec.get("message_id")
        check("el servicio guardó el message_id de lo que mandó", isinstance(our_mid, int), str(rec))
        n = len(events(state))
        api.private_message(ANA, "Perfecto, gracias", first_name="Ana", reply_to=(our_mid, True, "Sí, a las 8"))
        await until(lambda: len(events(state)) > n)
        notice = events(state)[-1]["notification_text"]
        check("el aviso dice a qué responde (FR-16)", "Ana López (respondiendo a «Sí, a las 8»): Perfecto, gracias" in notice, notice)
        ana = await thread_of(s, "Ana López")
        got = next(m for m in ana["messages"] if m.get("text") == "Perfecto, gracias")
        check("lo que entró cita lo que mandamos, con el nombre del agente", got.get("reply_to") == {
            "ref": out_ref, "name": "Agente Prueba", "excerpt": "Sí, a las 8", "missing": False}, str(got.get("reply_to")))
        reply_event = events(state)[-1]["event_id"]

        # --- Ana cita uno de sus mensajes de antes de paynani ----------------------------
        n = len(events(state))
        api.private_message(ANA, "Esto que te dije", first_name="Ana", reply_to=(99999, False, "Mensaje viejo de Ana"))
        await until(lambda: len(events(state)) > n)
        ana = await thread_of(s, "Ana López")
        old = next(m for m in ana["messages"] if m.get("text") == "Esto que te dije")
        check("un original de antes de paynani: ref null y el extracto de Telegram", old.get("reply_to") == {
            "ref": None, "name": "Ana López", "excerpt": "Mensaje viejo de Ana", "missing": False}, str(old.get("reply_to")))

        # --- Ana se cita a sí misma ----------------------------------------------------------
        n = len(events(state))
        api.private_message(ANA, "Lo de arriba", first_name="Ana", reply_to=(ana_mid, False, "¿Tienen mesa a las 8?"))
        await until(lambda: len(events(state)) > n)
        ana = await thread_of(s, "Ana López")
        own = next(m for m in ana["messages"] if m.get("text") == "Lo de arriba")
        check("lo que entró cita un mensaje suyo con su ref", (own.get("reply_to") or {}).get("ref") == ana_in["ref"], str(own))

        # --- la CLI ------------------------------------------------------------------------------
        rc, outp, err = await cli(env, "telegram", "send", "Ana López", "--reply-to", ana_in["ref"], "Listo")
        check("CLI: send --reply-to sale bien y lo dice", rc == 0 and f"reply_to {ana_in['ref']}" in outp, outp + err)
        rc, outp, err = await cli(env, "telegram", "send", "Ana López", "--reply-to", "w_1", "x")
        check("CLI: un --reply-to sin forma de tg: da 2", rc == 2 and "tg:" in err, outp + err)
        rc, outp, err = await cli(env, "telegram", "send", "Ana López", "--reply-to", beto_in["ref"], "x")
        check("CLI: un ref de otro hilo da 2 y lo dice", rc == 2 and "other_thread" in err + outp or "otro hilo" in err, outp + err)
        rc, outp, err = await cli(env, "telegram", "thread", "Ana López")
        check("CLI: thread muestra los refs y las citas", rc == 0 and ana_in["ref"] in outp
              and "(respondiendo a «Sí, a las 8») Perfecto, gracias" in outp, outp + err)
        # event show en el mismo proceso: roster.md siempre es el del clon (paths.roster).
        import argparse
        import contextlib
        import io
        from paynani_lib import event_cli
        event_cli.roster_file = lambda: state / "roster.md"
        event_cli.state_dir = lambda: state
        record = next(e for e in events(state) if e["event_id"] == reply_event)
        buf = io.StringIO()
        errbuf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(errbuf):
            rc = event_cli._show_telegram(record, argparse.Namespace(event_id=reply_event, body=True))
        outp = buf.getvalue()
        check("event show --body imprime la cita antes del cuerpo", rc == 0
              and f"--- in reply to the agent ({out_ref}) ---\nSí, a las 8" in outp
              and outp.index("--- in reply to") < outp.index("--- verified body ---"), f"rc={rc} err={errbuf.getvalue()} tail={outp[-300:]}")
        check("y dice cómo citar este mensaje", f"--reply-to {reply_event}" in outp, outp[-300:])
    finally:
        await s.stop()
        api.stop()


asyncio.run(main_tests())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
