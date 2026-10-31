#!/usr/bin/env python3
"""Pruebas del servicio paynani-telegram contra el servidor falso (#612 TG-1, PRD #609)."""

import asyncio
import json
import os
import pathlib
import stat
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.telegram import config, service as svc_mod  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import StartError, TelegramService  # noqa: E402

passed = failed = 0
# Falso a propósito y sin la forma de un token real (AA… de 35), para que el escaneo
# de secretos de GitHub no lo tome por uno (alerta del 2026-10-31).
TOKEN = "123456:fake_token_only_for_tests_x"
BOT_ID = 987654321
ANA = 7771234501          # en el roster por id
BETO = 7771234502         # en el roster por @usuario
PEDRO = 7771234503        # fuera del roster


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"ok    {name}")
    else:
        failed += 1
        print(f"FAIL  {name} {detail}")


ROSTER = """\
| Name | Email | Telegram | Type |
|---|---|---|---|
| Ana López | ana@example.com | %d | Human |
| Beto Ruiz | beto@example.com | @Beto_Ruiz | Human |
""" % ANA


def events(state):
    try:
        lines = (state / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [json.loads(x) for x in lines if x.strip()]


def tg_events(state, kind=None):
    return [e for e in events(state) if e.get("channel") == "telegram"
            and (kind is None or e["event_type"] == kind)]


async def until(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


def make(state, api, logs=None, **kw):
    opts = dict(poll_timeout=1, backoff=(0.05, 0.2))
    opts.update(kw)
    return TelegramService(state, roster_path=state / "roster.md", token=TOKEN, api_base=api.base_url,
                           log=(logs.append if logs is not None else (lambda _l: None)), **opts)


def fresh():
    state = pathlib.Path(tempfile.mkdtemp())
    (state / "roster.md").write_text(ROSTER, encoding="utf-8")
    api = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot").start()
    return state, api


async def socket_call(path, obj):
    reader, writer = await asyncio.open_unix_connection(str(path))
    writer.write((json.dumps(obj) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


async def main():
    # --- recibir, hilos, roster, grupos, ediciones ----------------------------------
    state, api = fresh()
    logs = []
    s = make(state, api, logs)
    await s.start()
    check("arranca y queda running", await until(lambda: s.state == "running"), s.state)
    check("status trae el @usuario del bot", s.status()["bot_username"] == "NegocioBot")

    _, ana_mid = api.private_message(ANA, "¿Tienen mesa a las 8?", first_name="Ana")
    api.private_message(BETO, "hola", first_name="Beto", username="beto_ruiz")
    api.private_message(PEDRO, "texto secreto de Pedro", first_name="Pedro")
    api.group_message(-100500, PEDRO, "en el grupo")
    api.group_added(-100600, "supergroup")
    ok = await until(lambda: len(tg_events(state, "telegram.received")) == 3 and not api.pending()
                     and s.store.offset() > 0)
    check("tres mensajes privados, tres eventos", ok, str(len(tg_events(state))))
    rec = tg_events(state, "telegram.received")
    by_line = {e["notification_text"].split("]")[1].split(":")[0].strip(): e for e in rec}
    check("Ana por id del roster", by_line.get("Ana López", {}).get("roster_match") is True, str(list(by_line)))
    check("Beto por @usuario del roster", by_line.get("Beto Ruiz", {}).get("roster_match") is True)
    pedro = by_line.get("Pedro (no verificado)", {})
    check("Pedro fuera del roster, no verificado", pedro.get("roster_match") is False, str(list(by_line)))
    check("el texto de alguien fuera del roster no sale en el aviso",
          "secreto" not in json.dumps(pedro, ensure_ascii=False))
    check("el aviso del roster lleva el extracto", "¿Tienen mesa" in by_line["Ana López"]["notification_text"])
    check("los grupos no dan eventos y el bot sale de los dos",
          sorted(api.left_chats) == [-100600, -100500] and s.counters["groups_left"] == 2, str(api.left_chats))
    check("ningún evento trae address", all(e["sender"]["address"] == "" for e in rec))

    # FR-3a / Ximena #613: ni el bot_id, ni su hash o prefijo, ni ids de personas, ni el token.
    folder = config.bot_dir_name(BOT_ID)
    secrets_ = [str(BOT_ID), folder, folder[:8], str(ANA), str(BETO), str(PEDRO), TOKEN, TOKEN.split(":")[1]]
    outputs = {"events.jsonl": (state / "events.jsonl").read_text(encoding="utf-8"),
               "lifecycle.jsonl": (state / "lifecycle.jsonl").read_text(encoding="utf-8"),
               "log": "\n".join(logs),
               "status": json.dumps(s.status()),
               "status.json": (state / "telegram" / "status.json").read_text(encoding="utf-8")}
    resp = await socket_call(s.socket_path, {"type": "telegram.status", "id": "q_" + "a" * 32, "by": "web"})
    outputs["control.sock"] = json.dumps(resp)
    leaks = [(name, x) for name, text in outputs.items() for x in secrets_ if x in text]
    check("ni bot_id, ni su hash, ni ids, ni token en eventos, log, status ni socket", leaks == [], str(leaks))
    accounts = {e["account"] for e in tg_events(state)}
    check("account es tg:<alias aleatorio> y es uno solo",
          len(accounts) == 1 and next(iter(accounts)).startswith("tg:") and len(next(iter(accounts))) == 19,
          str(accounts))
    check("el alias está en account.json del bot",
          json.loads((state / "telegram/bots" / folder / "account.json").read_text())["alias"]
          == next(iter(accounts))[3:])
    check("event_id es tg: + 32 hex", all(len(e["event_id"]) == 35 for e in rec))

    # permisos
    bot_dir = state / "telegram" / "bots" / folder
    modes = {p.name: stat.S_IMODE(os.lstat(p).st_mode) for p in
             (state / "telegram", bot_dir, bot_dir / "inbox", bot_dir / "journal.jsonl",
              bot_dir / "offset.json", state / "telegram" / "status.json", s.socket_path)}
    check("carpetas 0700 y archivos 0600",
          all(m == (0o700 if n in ("telegram", folder, "inbox") else 0o600) for n, m in modes.items()),
          str({k: oct(v) for k, v in modes.items()}))

    # control.sock
    check("telegram.status por el socket", resp.get("ok") and resp["data"]["state"] == "running", str(resp))
    bad = await socket_call(s.socket_path, {"type": "telegram.nada", "id": "q_" + "b" * 32, "by": "web"})
    check("un tipo desconocido: unknown_type", bad.get("code") == "unknown_type", str(bad))
    noid = await socket_call(s.socket_path, {"type": "telegram.status", "by": "web"})
    check("sin id: missing_field", noid.get("code") == "missing_field")

    # ediciones (FR-16a)
    api.edit_message(ANA, ana_mid, "¿Tienen mesa a las 9?", first_name="Ana")
    api.edit_message(ANA, 999, "edición de algo que no vimos", first_name="Ana")
    ok = await until(lambda: len(tg_events(state, "telegram.edited")) == 1 and s.counters["edits_ignored"] == 1)
    check("una edición da telegram.edited; la de un mensaje desconocido sólo cuenta", ok,
          f"{len(tg_events(state, 'telegram.edited'))} {s.counters}")
    edited = tg_events(state, "telegram.edited")[0]
    original_ref = by_line["Ana López"]["event_id"]
    check("telegram.edited apunta al original", edited.get("edits") == original_ref)
    check("el inbox del original queda con el texto nuevo y edited",
          s.store.inbox(original_ref).get("text") == "¿Tienen mesa a las 9?" and s.store.inbox(original_ref).get("edited"))

    # candado (FR-3)
    other = make(state, api)
    try:
        await other.start()
        check("un segundo servicio con el mismo estado no arranca", False)
        await other.stop()
    except StartError as exc:
        check("un segundo servicio con el mismo estado no arranca", "lock" in str(exc))

    count = len(tg_events(state))
    await s.stop()
    check("al parar: stopped en status.json",
          json.loads((state / "telegram/status.json").read_text())["state"] == "stopped")

    # reinicio: el mismo offset, nada se repite
    s2 = make(state, api)
    await s2.start()
    await until(lambda: s2.state == "running")
    api.private_message(ANA, "otra", first_name="Ana")
    await until(lambda: len(tg_events(state)) == count + 1)
    await asyncio.sleep(0.3)
    check("al reiniciar no se repite nada y llega lo nuevo", len(tg_events(state)) == count + 1,
          f"{len(tg_events(state))} vs {count + 1}")
    ids = [e["event_id"] for e in tg_events(state)]
    check("ningún event_id repetido", len(ids) == len(set(ids)))
    await s2.stop()
    api.stop()

    # --- caídas entre los pasos de FR-5 --------------------------------------------
    async def crash_at(target, attr, label):
        state, api = fresh()
        s = make(state, api)
        await s.start()
        await until(lambda: s.state == "running")
        real = getattr(target(s), attr)
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("caída simulada")
            return real(*a, **k)

        setattr(target(s), attr, boom)
        api.private_message(ANA, "mensaje " + label, first_name="Ana")
        await until(lambda: s.state == "stopped")
        await s.stop()
        s2 = make(state, api)
        await s2.start()
        ok = await until(lambda: len(tg_events(state, "telegram.received")) >= 1 and not api.pending())
        await asyncio.sleep(0.4)
        evs = tg_events(state, "telegram.received")
        j = s2.store.journal()
        check(f"caída {label}: un solo evento, diario escrito, nada pendiente",
              ok and len(evs) == 1 and all(e["written"] for e in j.values()) and not api.pending(),
              f"eventos={len(evs)} diario={j} pendientes={api.pending()}")
        await s2.stop()
        api.stop()
        return evs

    await crash_at(lambda s: s.store if s.store else s, "save_inbox", "antes del inbox (paso 2→3)")
    await crash_at(lambda s: svc_mod.ev, "append", "antes del evento (inbox escrito)")
    await crash_at(lambda s: s.store, "journal_written", "después del evento (paso 3→4)")

    # mismo update_id, hash distinto: journal_mismatch, nada se marca
    state, api = fresh()
    s = make(state, api)
    await s.start()
    await until(lambda: s.state == "running")
    await s.stop()
    api.private_message(ANA, "original", first_name="Ana")
    uid = api.pending()[0]
    s.store.journal_begin(uid, "tg:" + "c" * 32, "0" * 64)
    s3 = make(state, api)
    await s3.start()
    check("hash distinto para el mismo update: journal_mismatch",
          await until(lambda: s3.state == "journal_mismatch"), s3.state)
    check("journal_mismatch no escribe el evento ni avanza el offset",
          tg_events(state, "telegram.received") == [] and s3.store.offset() == 0)
    check("journal_mismatch da un telegram.health",
          [e["notification_text"] for e in tg_events(state, "telegram.health")] != [])
    await s3.stop()
    api.stop()

    # --- webhook, 409, 401, red -----------------------------------------------------
    state, api = fresh()
    api.set_webhook("https://otra-instalacion.invalid/hook")
    s = make(state, api)
    await s.start()
    check("con webhook: conflict (webhook)", await until(lambda: s.state == "conflict"), s.state)
    check("el webhook no se toca y no hay getUpdates",
          api.webhook_url and "deleteWebhook" not in api.calls and "getUpdates" not in api.calls)
    check("conflict trae reason webhook", s.status().get("reason") == "webhook")
    await s.stop()
    api.stop()

    state, api = fresh()
    s = make(state, api)
    api.fail_next("getUpdates", 409)
    await s.start()
    check("409 en getUpdates: conflict (409) sin reintentar",
          await until(lambda: s.state == "conflict") and s.status().get("reason") == "409")
    n = api.calls.count("getUpdates")
    await asyncio.sleep(0.5)
    check("tras 409 no hay más getUpdates", api.calls.count("getUpdates") == n)
    await s.stop()
    api.stop()

    state, api = fresh()
    s = make(state, api, token_retry_s=0.2)
    api.revoke()
    await s.start()
    check("401: token_invalid", await until(lambda: s.state == "token_invalid"), s.state)
    await asyncio.sleep(0.6)
    health = [e for e in tg_events(state, "telegram.health")]
    check("token_invalid avisa una sola vez", len(health) == 1, str(len(health)))
    await s.stop()
    api.stop()

    state, api = fresh()
    s = make(state, api, offline_alert_s=0.1)
    await s.start()
    await until(lambda: s.state == "running")
    for _ in range(4):
        api.fail_next("getUpdates", 502)
    check("red caída: offline", await until(lambda: s.state == "offline"), s.state)
    check("y se recupera", await until(lambda: s.state == "running"), s.state)
    states = [e["notification_text"] for e in tg_events(state, "telegram.health")]
    check("offline y recovered, una vez cada uno", len(states) == 2, str(states))
    api.private_message(ANA, "después de la caída", first_name="Ana")
    check("después de recuperarse sigue recibiendo",
          await until(lambda: len(tg_events(state, "telegram.received")) == 1))
    await s.stop()
    api.stop()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
