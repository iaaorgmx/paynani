#!/usr/bin/env python3
"""
Tests for reactions in Telegram (PRD #685 F3, the FR-14 contract on #685), against the fake
Bot API: `telegram.react` (put, replace, remove, bad_emoji, not_found, not_allowed),
`reactions` in `telegram.status` and per message in `telegram.thread`, `message_reaction` in
`allowed_updates`, a contact's reaction on the way in (FR-13) with its notice (FR-16a), one
from outside the roster, the CLI `telegram react`, `telegram thread` and `event show`.
"""

import argparse
import asyncio
import contextlib
import io
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
from paynani_lib.telegram import reactions as tg_reactions  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import ALLOWED_UPDATES, TelegramService  # noqa: E402

passed = failed = 0
TOKEN = "123456:fake_token_only_for_tests_x"
BOT_ID = 987654321
ANA = 7771234501
EXTRA = 7771234599            # no está en el roster
ROSTER = """\
| Name | Email | Telegram | Type |
|---|---|---|---|
| Ana López | ana@example.com | %d | Human |
""" % ANA
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
    t = next(x["thread"] for x in rows if x["name"].startswith(name))
    return (await call(s, "telegram.thread", by="web", thread=t))["data"]


def show(state, event_id):
    from paynani_lib import event_cli
    event_cli.roster_file = lambda: state / "roster.md"
    event_cli.state_dir = lambda: state
    record = next(e for e in events(state) if e["event_id"] == event_id)
    buf, errbuf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(errbuf):
        rc = event_cli._show_telegram(record, argparse.Namespace(event_id=event_id, body=True))
    return rc, buf.getvalue(), errbuf.getvalue()


# --- la lista de un bot ---------------------------------------------------------------------
check("message_reaction está en allowed_updates (FR-13)", "message_reaction" in ALLOWED_UPDATES)
shown = tg_reactions.display_list()
check("la lista trae los 7 de la fila (FR-10)", all(e in shown for e in ("👍", "👌", "❤️", "👀", "🔥", "😭", "👎")))
check("❤ se muestra con U+FE0F y va a la API sin él", tg_reactions.api_form("❤️") == "❤" and "❤️" in shown)
check("un emoji que un bot no puede usar no tiene forma de API", tg_reactions.api_form("🦖") is None)


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
        check("telegram.status trae la lista de reacciones", r["data"].get("reactions") == shown, str(r)[:200])

        _, ana_mid = api.private_message(ANA, "¿Tienen mesa a las 8?", first_name="Ana")
        _, extra_mid = api.private_message(EXTRA, "hola", first_name="Extraño")
        await until(lambda: len(events(state)) >= 2)
        ana = await thread_of(s, "Ana López")
        ana_in = next(m for m in ana["messages"] if m["dir"] == "in")
        r = await call(s, "telegram.send", by="web", thread=ana["thread"], text="Sí, a las 8")
        out_ref = r["data"]["ref"]
        n_events = len(events(state))

        # --- el bot reacciona -----------------------------------------------------------
        r = await call(s, "telegram.react", by="web", ref=ana_in["ref"], emoji="👍")
        check("telegram.react: ok", r.get("ok"), str(r))
        check("devuelve el ref y las reacciones", r["data"] == {
            "ref": ana_in["ref"], "reactions": [{"emoji": "👍", "count": 1, "mine": True}]}, str(r))
        calls = methods(api, "setMessageReaction")
        check("llama a setMessageReaction con el message_id de Ana", len(calls) == 1
              and calls[0]["message_id"] == ana_mid and calls[0]["chat_id"] == ANA, str(calls))
        check("con una reacción emoji", json.loads(calls[0]["reaction"]) == [{"type": "emoji", "emoji": "👍"}])
        check("la nuestra no avisa (FR-16a)", len(events(state)) == n_events)
        ana = await thread_of(s, "Ana López")
        got = next(m for m in ana["messages"] if m["ref"] == ana_in["ref"])
        check("el hilo trae reactions en ese mensaje", got.get("reactions") == [{"emoji": "👍", "count": 1, "mine": True}],
              str(got))
        check("sin reacciones, el campo no viene", "reactions" not in next(m for m in ana["messages"] if m["ref"] == out_ref))
        check("el message_id no sale en el hilo", "message_id" not in json.dumps(ana))
        check("lo que sí se puede citar y reaccionar no trae actions (#707)",
              all("actions" not in m for m in ana["messages"]), str(ana["messages"]))

        # --- #707: un envío de antes de #700, sin message_id ----------------------------
        old = dict(next(r for r in s.store.sent() if r["ref"] == out_ref), ref="tgo:" + "0" * 32,
                   at="2026-11-03T18:42:00Z", text="Recibí la foto")
        old.pop("message_id", None)
        s.store.record_sent(old)
        ana = await thread_of(s, "Ana López")
        legacy = next(m for m in ana["messages"] if m["ref"] == old["ref"])
        check("#707: sin message_id el hilo trae actions: false", legacy.get("actions") is False, str(legacy))
        check("#707: el envío nuevo sigue sin actions", "actions" not in next(
            m for m in ana["messages"] if m["ref"] == out_ref))
        r = await call(s, "telegram.react", by="web", ref=old["ref"], emoji="👍")
        check("#707: y react de ese mensaje da not_found", r.get("code") == "not_found", str(r))

        r = await call(s, "telegram.react", by="web", ref=ana_in["ref"], emoji="👍")
        check("la misma otra vez no vuelve a llamar a Telegram", len(methods(api, "setMessageReaction")) == 1)
        r = await call(s, "telegram.react", by="web", ref=ana_in["ref"], emoji="❤️")
        check("otra la reemplaza (FR-11), con la forma de la API", r["data"]["reactions"] == [
            {"emoji": "❤️", "count": 1, "mine": True}] and api.reactions[(ANA, ana_mid)] == "❤", str(r))
        r = await call(s, "telegram.react", by="web", ref=ana_in["ref"], emoji="")
        check("vacío la quita", r.get("ok") and r["data"]["reactions"] == [] and api.reactions[(ANA, ana_mid)] is None,
              str(r))
        r = await call(s, "telegram.react", by="agent", ref=out_ref, emoji="🔥")
        check("también en lo que salió (tgo:)", r.get("ok") and r["data"]["reactions"][0]["emoji"] == "🔥", str(r))

        # --- errores --------------------------------------------------------------------
        r = await call(s, "telegram.react", by="web", ref=ana_in["ref"], emoji="🦖")
        check("un emoji que no es de bot: invalid bad_emoji", r.get("code") == "invalid"
              and r.get("reason") == "bad_emoji" and r.get("field") == "emoji", str(r))
        r = await call(s, "telegram.react", by="web", ref="tg:" + "0" * 32, emoji="👍")
        check("un ref que no existe: not_found", r.get("code") == "not_found", str(r))
        extra_ref = next(x for x in s.store.received() if x.get("user") == EXTRA)["ref"]
        r = await call(s, "telegram.react", by="web", ref=extra_ref, emoji="👍")
        check("fuera del roster: not_allowed (FR-17)", r.get("code") == "not_allowed", str(r))
        api.fail_next("setMessageReaction", 429, retry_after=1)
        api.fail_next("setMessageReaction", 429, retry_after=1)
        r = await call(s, "telegram.react", by="web", ref=ana_in["ref"], emoji="👌")
        check("Telegram se queja dos veces: rate_limited", r.get("code") == "rate_limited", str(r))

        # --- Ana reacciona (FR-13, FR-16a) ---------------------------------------------
        n_events = len(events(state))
        mid_out = next(x for x in s.store.sent() if x["ref"] == out_ref)["message_id"]
        api.reaction(ANA, mid_out, new="❤", first_name="Ana")
        await until(lambda: len(events(state)) > n_events)
        new = events(state)[n_events:]
        check("la reacción de Ana avisa una vez", len(new) == 1, str(new))
        ev = new[0]
        check("con kind reaction y un tg: propio", ev["kind"] == "reaction" and ev["event_id"].startswith("tg:")
              and ev["event_id"] not in (ana_in["ref"], out_ref), str(ev))
        check("el aviso dice el emoji y el extracto", "[telegram " in ev["notification_text"]
              and ", roster] Ana López reaccionó ❤️ a «Sí, a las 8»" in ev["notification_text"], ev["notification_text"])
        ana = await thread_of(s, "Ana López")
        got = next(m for m in ana["messages"] if m["ref"] == out_ref)
        check("el hilo junta la nuestra y la de Ana", got.get("reactions") == [
            {"emoji": "🔥", "count": 1, "mine": True}, {"emoji": "❤️", "count": 1, "mine": False}], str(got))
        rc, outp, err = show(state, ev["event_id"])
        check("event show --body imprime la reacción y el mensaje", rc == 0
              and f"--- reaction: ❤️ on the agent's message ({out_ref}) ---\nSí, a las 8" in outp, outp[-300:] + err)
        check("y dice cómo reaccionar", f"telegram react {out_ref} <emoji>" in outp)
        check("la reacción no aparece como mensaje en el hilo", all(m["ref"] != ev["event_id"] for m in ana["messages"]))

        n_events = len(events(state))
        api.reaction(ANA, mid_out, new="🔥", old="❤", first_name="Ana")
        await until(lambda: len(events(state)) > n_events)
        got = next(m for m in (await thread_of(s, "Ana López"))["messages"] if m["ref"] == out_ref)
        check("cambiar a la misma que la nuestra: count 2", got.get("reactions") == [
            {"emoji": "🔥", "count": 2, "mine": True}], str(got))
        check("cambiar da un solo aviso, con la nueva", len(events(state)) == n_events + 1
              and "reaccionó 🔥 a" in events(state)[-1]["notification_text"])
        n_events = len(events(state))
        api.reaction(ANA, mid_out, new=None, old="🔥", first_name="Ana")
        await until(lambda: len(events(state)) > n_events)
        check("quitar también avisa", len(events(state)) == n_events + 1
              and "Ana López quitó su reacción 🔥 de «Sí, a las 8»" in events(state)[-1]["notification_text"],
              events(state)[-1]["notification_text"])
        rc, outp, err = show(state, events(state)[-1]["event_id"])
        check("event show dice cuál quitó", rc == 0 and f"--- reaction: removed 🔥 on the agent's message ({out_ref})" in outp,
              outp[-300:] + err)

        # --- alguien fuera del roster -----------------------------------------------------
        n_events = len(events(state))
        api.reaction(EXTRA, extra_mid, new="👍", first_name="Extraño")
        await until(lambda: len(events(state)) > n_events)
        text = events(state)[-1]["notification_text"]
        check("fuera del roster: sólo «reacción de alguien fuera del roster»",
              "reacción de alguien fuera del roster" in text and "👍" not in text and "hola" not in text, text)

        # --- la CLI ---------------------------------------------------------------------
        rc, outp, err = await cli(env, "telegram", "react", ana_in["ref"], "👀")
        check("CLI: telegram react sale bien", rc == 0 and outp.startswith(f"{ana_in['ref']}\treacted 👀\t[👀 bot]"),
              outp + err)
        rc, outp, err = await cli(env, "telegram", "thread", "Ana López")
        check("CLI: thread muestra las reacciones", rc == 0 and "[👀 bot]" in outp, outp + err)
        rc, outp, err = await cli(env, "telegram", "react", ana_in["ref"], "--remove")
        check("CLI: --remove la quita", rc == 0 and "\tremoved\t[]" in outp, outp + err)
        rc, outp, err = await cli(env, "telegram", "react", ana_in["ref"], "🦖")
        check("CLI: un emoji que no es de bot da 2", rc == 2 and "invalid" in err, outp + err)
        rc, outp, err = await cli(env, "telegram", "react", "w_1", "👍")
        check("CLI: un ref sin forma de tg: da 2", rc == 2, outp + err)
        rc, outp, err = await cli(env, "telegram", "react", ana_in["ref"])
        check("CLI: sin emoji ni --remove da 2", rc == 2, outp + err)
    finally:
        await s.stop()
        api.stop()


asyncio.run(main_tests())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
