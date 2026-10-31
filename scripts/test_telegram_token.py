#!/usr/bin/env python3
"""Pruebas de TG-2 (#612, PRD #609 FR-8 a FR-10): telegram.env, setup y cambio de token."""

import asyncio
import io
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

from paynani_lib.telegram import cli, config  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402

passed = failed = 0
# Falsos a propósito, sin la forma de un token real (ver test_telegram_service.py).
OLD = "111111:fake_old_token_for_tests_x"
NEW = "222222:fake_new_token_for_tests_x"
OLD_ID, NEW_ID = 900000001, 900000002


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


def events(state):
    try:
        return [json.loads(x) for x in (state / "events.jsonl").read_text().splitlines() if x.strip()]
    except OSError:
        return []


class Args:
    def __init__(self, **kw):
        self.__dict__.update(dict(dedicated=False, delete_webhook=False, replace=False, json=False, state=None))
        self.__dict__.update(kw)


CONTROL = {"start": "not-installed"}


def run_cli(fn, args, stdin_text, env_path, base):
    """Corre una orden de la CLI con stdin, env_path y la Bot API falsa; (código, salida)."""
    saved = (sys.stdin, sys.stdout, sys.stderr, config.env_path, os.environ.get(config.API_ENV))
    sys.stdin, out = io.StringIO(stdin_text), io.StringIO()
    sys.stdout = sys.stderr = out
    config.env_path = lambda environ=None: env_path
    os.environ[config.API_ENV] = base
    real_control = cli.service_control
    cli.service_control = lambda action: CONTROL["start"]   # nunca el servicio real del host
    try:
        rc = fn(args)
    finally:
        cli.service_control = real_control
        sys.stdin, sys.stdout, sys.stderr, config.env_path = saved[:4]
        if saved[4] is None:
            os.environ.pop(config.API_ENV, None)
        else:
            os.environ[config.API_ENV] = saved[4]
    return rc, out.getvalue()


# --- telegram.env (FR-8) ----------------------------------------------------------------
d = pathlib.Path(tempfile.mkdtemp())
env = d / "telegram.env"
config.write(config.with_token({"TELEGRAM_SEND_PER_DAY": "50"}, OLD), env)
check("telegram.env se escribe 0600", stat.S_IMODE(os.stat(env).st_mode) == 0o600)
check("configured() con ENABLED=1 y token", config.configured(env))
check("los otros ajustes se conservan", config.read(env)["TELEGRAM_SEND_PER_DAY"] == "50")
config.save_backup(env)
check("el respaldo también es 0600 y trae el token anterior",
      stat.S_IMODE(os.stat(d / "telegram.env.bak").st_mode) == 0o600
      and config.token(config.read(d / "telegram.env.bak")) == OLD)
try:
    config.with_token({}, "no es un token")
    check("with_token rechaza algo sin forma de token", False)
except ValueError as exc:
    check("with_token rechaza algo sin forma de token", "no es un token" not in str(exc))
os.chmod(env, 0o644)
check("telegram.env legible por otros: no cuenta como configurado", not config.configured(env))
os.chmod(env, 0o600)

# --- setup (FR-9) -------------------------------------------------------------------------
api = FakeBotAPI(token=NEW, bot_id=NEW_ID, username="NuevoBot").start()
d = pathlib.Path(tempfile.mkdtemp())
env = d / "telegram.env"
rc, out = run_cli(cli.run_setup, Args(), NEW + "\n", env, api.base_url)
check("setup sin --dedicated (y sin terminal) no escribe nada", rc == 2 and not env.exists(), out)
rc, out = run_cli(cli.run_setup, Args(dedicated=True), "123:corto\n", env, api.base_url)
check("setup con algo que no es token: 2 y nada escrito", rc == 2 and not env.exists())
rc, out = run_cli(cli.run_setup, Args(dedicated=True), "999999:otro_token_que_no_existe_x\n", env, api.base_url)
check("setup con un token que Telegram rechaza: 2 y nada escrito", rc == 2 and not env.exists(), out)
api.set_webhook("https://otra.invalid/hook")
rc, out = run_cli(cli.run_setup, Args(dedicated=True), NEW + "\n", env, api.base_url)
check("setup con webhook sin --delete-webhook: no lo borra y no escribe",
      rc == 2 and api.webhook_url and not env.exists(), out)
rc, out = run_cli(cli.run_setup, Args(dedicated=True, delete_webhook=True), NEW + "\n", env, api.base_url)
check("setup con las dos confirmaciones: borra el webhook y escribe 0600",
      rc == 0 and not api.webhook_url and config.token(config.read(env)) == NEW
      and stat.S_IMODE(os.stat(env).st_mode) == 0o600, out)
check("setup muestra el @usuario del bot", "@NuevoBot" in out)
check("setup nunca imprime el token", NEW not in out and NEW.split(":")[1] not in out)
rc, out = run_cli(cli.run_setup, Args(dedicated=True), NEW + "\n", env, api.base_url)
check("setup con Telegram ya configurado pide paynani telegram token", rc == 2 and "telegram token" in out)
env2 = d / "otro" / "telegram.env"
env2.parent.mkdir()
CONTROL["start"] = "failed"
rc, out = run_cli(cli.run_setup, Args(dedicated=True), NEW + "\n", env2, api.base_url)
CONTROL["start"] = "not-installed"
check("setup si el servicio no arranca: 1 y lo dice, con telegram.env ya escrito (Ximena en #623)",
      rc == 1 and "no pude arrancar" in out and config.token(config.read(env2)) == NEW, out)
api.stop()


# --- cambio de token en el servicio (FR-10) ---------------------------------------------
async def service_case(label, prepare=None, *, ready_timeout_s=3.0):
    """Arranca con OLD, prueba y aplica NEW; regresa (servicio, resultado, apis, carpeta)."""
    state = pathlib.Path(tempfile.mkdtemp())
    (state / "roster.md").write_text("| Name | Email | Type |\n|---|---|---|\n| Dueña | d@example.com | Human |\n")
    env = state / "telegram.env"
    config.write(config.with_token({}, OLD), env)
    old_api = FakeBotAPI(token=OLD, bot_id=OLD_ID, username="ViejoBot").start()
    new_api = old_api.add_bot(NEW, NEW_ID, "NuevoBot")
    notified, logs = [], []
    s = TelegramService(state, roster_path=state / "roster.md", token=OLD, api_base=old_api.base_url,
                        env_path=env, notify_owner=notified.append, log=logs.append,
                        poll_timeout=1, backoff=(0.05, 0.2), ready_timeout_s=ready_timeout_s)
    await s.start()
    await until(lambda: s.state == "running")
    if prepare:
        prepare(new_api)
    reply = await s.handle({"type": "telegram.token_check", "id": "q_" + "1" * 32, "by": "web", "token": NEW})
    data = reply.get("data") or {}
    result = None
    if reply.get("ok"):
        r2 = await s.handle({"type": "telegram.token_apply", "id": "q_" + "2" * 32, "by": "web",
                             "check": data["check"], "confirm_dedicated": True,
                             "confirm_delete_webhook": data.get("webhook")})
        result = r2.get("data") or r2
    return s, data, result, (old_api, new_api), state, env, notified, logs


async def main():
    # applied
    s, data, result, (old_api, new_api), state, env, notified, logs = await service_case("ok")
    check("token_check: @usuario, same_token false, sin webhook, check c_…",
          data.get("bot_username") == "NuevoBot" and data.get("same_token") is False
          and data.get("webhook") is False and data.get("check", "").startswith("c_"), str(data))
    check("token_check nunca devuelve el token", NEW not in json.dumps(data))
    check("applied", result.get("result") == "applied" and result.get("bot_username") == "NuevoBot", str(result))
    check("telegram.env trae el token nuevo y el respaldo el anterior",
          config.token(config.read(env)) == NEW and config.token(config.read(env.with_name("telegram.env.bak"))) == OLD)
    check("el dueño recibe aviso con el @usuario nuevo", notified == ["NuevoBot"], str(notified))
    check("el servicio queda running con el bot nuevo",
          await until(lambda: s.state == "running") and s.status()["bot_username"] == "NuevoBot")
    new_api.private_message(7001, "hola al bot nuevo", first_name="Ana")
    check("y recibe del bot nuevo", await until(lambda: any(e.get("channel") == "telegram" for e in events(state))))
    bots = sorted(p.name for p in (state / "telegram" / "bots").iterdir())
    check("cada bot tiene su carpeta", len(bots) == 2 and config.bot_dir_name(NEW_ID) in bots)
    text = "\n".join(logs) + (state / "telegram" / "status.json").read_text() + json.dumps(events(state))
    leaks = [x for x in (OLD, NEW, OLD.split(":")[1], NEW.split(":")[1], str(OLD_ID), str(NEW_ID)) if x in text]
    check("ni tokens ni bot_id en log, status ni eventos", leaks == [], str(leaks))
    again = await s.handle({"type": "telegram.token_apply", "id": "q_" + "3" * 32, "by": "web",
                            "check": data["check"], "confirm_dedicated": True})
    check("un check ya usado: not_found", again.get("code") == "not_found", str(again))
    await s.stop()
    old_api.stop()
    new_api.stop()

    # unchanged
    state = pathlib.Path(tempfile.mkdtemp())
    (state / "roster.md").write_text("")
    api = FakeBotAPI(token=OLD, bot_id=OLD_ID, username="ViejoBot").start()
    s = TelegramService(state, roster_path=state / "roster.md", token=OLD, api_base=api.base_url,
                        env_path=state / "telegram.env", poll_timeout=1, backoff=(0.05, 0.2))
    await s.start()
    await until(lambda: s.state == "running")
    r = await s.handle({"type": "telegram.token_check", "id": "q_" + "4" * 32, "by": "web", "token": OLD})
    check("el mismo token: same_token true", r["data"]["same_token"] is True)
    r2 = await s.handle({"type": "telegram.token_apply", "id": "q_" + "5" * 32, "by": "web",
                         "check": r["data"]["check"], "confirm_dedicated": True})
    check("el mismo token: unchanged", r2["data"]["result"] == "unchanged", str(r2))
    r3 = await s.handle({"type": "telegram.token_check", "id": "q_" + "6" * 32, "by": "web", "token": "x"})
    check("token sin forma: invalid", r3.get("code") == "invalid" and r3.get("field") == "token")
    r4 = await s.handle({"type": "telegram.token_check", "id": "q_" + "7" * 32, "by": "web",
                         "token": "333333:no_existe_en_el_falso_x"})
    check("token que Telegram rechaza: invalid", r4.get("code") == "invalid", str(r4))
    r5 = await s.handle({"type": "telegram.token_check", "id": "q_" + "8" * 32, "by": "web", "token": OLD})
    r6 = await s.handle({"type": "telegram.token_apply", "id": "q_" + "9" * 32, "by": "web",
                         "check": r5["data"]["check"]})
    check("sin confirm_dedicated: invalid", r6.get("code") == "invalid" and r6.get("field") == "confirm_dedicated")
    r7 = await s.handle({"type": "telegram.token_apply", "id": "q_" + "a" * 32, "by": "web",
                         "check": "c_" + "0" * 32, "confirm_dedicated": True})
    check("check desconocido: not_found", r7.get("code") == "not_found")
    await s.stop()
    api.stop()

    # webhook en el bot nuevo
    s, data, result, (old_api, new_api), state, env, notified, _ = await service_case(
        "webhook", lambda a: a.set_webhook("https://otra.invalid/hook"))
    check("token_check avisa del webhook", data.get("webhook") is True)
    check("con confirm_delete_webhook: se borra y applied",
          result.get("result") == "applied" and not new_api.webhook_url, str(result))
    await s.stop()
    old_api.stop()
    new_api.stop()

    # rollbacks
    for label, prepare, reason, timeout in (
            ("409", lambda a: a.fail_next("getUpdates", 409), "409", 3.0),
            ("not_ready", lambda a: [a.fail_next("getUpdates", 502) for _ in range(200)], "not_ready", 1.0)):
        s, data, result, (old_api, new_api), state, env, notified, _ = await service_case(
            label, prepare, ready_timeout_s=timeout)
        check(f"rollback {label}", result.get("result") == "rollback" and result.get("reason") == reason, str(result))
        check(f"rollback {label}: telegram.env vuelve al token anterior", config.token(config.read(env)) == OLD)
        check(f"rollback {label}: el dueño no recibe aviso", notified == [])
        ok = await until(lambda: s.state == "running" and s.status()["bot_username"] == "ViejoBot")
        check(f"rollback {label}: el servicio vuelve al bot anterior", ok, f"{s.state} {s.status()['bot_username']}")
        old_api.private_message(7002, "sigo en el bot viejo", first_name="Beto")
        check(f"rollback {label}: y sigue recibiendo del anterior",
              await until(lambda: any(e.get("channel") == "telegram" and e["event_type"] == "telegram.received"
                                      for e in events(state))))
        await s.stop()
        old_api.stop()
        new_api.stop()

    # no se puede guardar el respaldo o telegram.env (Ximena, #617)
    for label, target in (("save_backup", "save_backup"), ("write", "write")):
        real = getattr(config, target)
        calls = {"n": 0}

        def boom(*a, _real=real, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("disco lleno (simulado)")
            return _real(*a, **k)

        def prepare(_api, _t=target, _b=boom):
            setattr(config, _t, _b)

        s, data, result, (old_api, new_api), state, env, notified, _ = await service_case(label, prepare)
        setattr(config, target, real)
        check(f"falla {label}: rollback write",
              result.get("result") == "rollback" and result.get("reason") == "write", str(result))
        check(f"falla {label}: telegram.env sigue con el token anterior", config.token(config.read(env)) == OLD)
        ok = await until(lambda: s.state == "running" and s.status()["bot_username"] == "ViejoBot"
                         and s._task is not None and not s._task.done())
        check(f"falla {label}: el lector vuelve al bot anterior y corre", ok, s.state)
        old_api.private_message(7003, f"después de fallar {label}", first_name="Ceci")
        check(f"falla {label}: y sigue recibiendo del anterior",
              await until(lambda: any(e.get("event_type") == "telegram.received" for e in events(state))))
        check(f"falla {label}: el dueño no recibe aviso", notified == [])
        await s.stop()
        old_api.stop()

    # una excepción inesperada en handle(): el cliente igual recibe respuesta
    state = pathlib.Path(tempfile.mkdtemp())
    (state / "roster.md").write_text("")
    api = FakeBotAPI(token=OLD, bot_id=OLD_ID, username="ViejoBot").start()
    s = TelegramService(state, roster_path=state / "roster.md", token=OLD, api_base=api.base_url,
                        env_path=state / "telegram.env", poll_timeout=1, backoff=(0.05, 0.2))
    await s.start()

    async def explode(*a, **k):
        raise RuntimeError("inesperado")

    s.token_check = explode
    r = await s.handle({"type": "telegram.token_check", "id": "q_" + "d" * 32, "by": "web", "token": OLD})
    check("excepción inesperada: error unavailable, sin detalles", r == {"type": "error", "ref": "q_" + "d" * 32,
                                                                        "code": "unavailable"}, str(r))
    await s.stop()
    api.stop()

    # getMe falla entre check y apply (token revocado)
    state = pathlib.Path(tempfile.mkdtemp())
    (state / "roster.md").write_text("")
    env = state / "telegram.env"
    config.write(config.with_token({}, OLD), env)
    old_api = FakeBotAPI(token=OLD, bot_id=OLD_ID, username="ViejoBot").start()
    new_api = old_api.add_bot(NEW, NEW_ID, "NuevoBot")
    s = TelegramService(state, roster_path=state / "roster.md", token=OLD, api_base=old_api.base_url,
                        env_path=env, poll_timeout=1, backoff=(0.05, 0.2), ready_timeout_s=3)
    await s.start()
    await until(lambda: s.state == "running")
    r = await s.handle({"type": "telegram.token_check", "id": "q_" + "b" * 32, "by": "web", "token": NEW})
    new_api.revoke()
    r2 = await s.handle({"type": "telegram.token_apply", "id": "q_" + "c" * 32, "by": "web",
                         "check": r["data"]["check"], "confirm_dedicated": True})
    check("token revocado entre check y apply: rollback getMe",
          r2["data"].get("result") == "rollback" and r2["data"].get("reason") == "getMe", str(r2))
    check("y telegram.env queda con el anterior", config.token(config.read(env)) == OLD)
    await s.stop()
    old_api.stop()
    new_api.stop()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
