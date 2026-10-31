#!/usr/bin/env python3
"""
Tests for `paynani telegram disable` and `enable` (TG-6 of #612, PRD #609 FR-1;
TELEGRAM.md §5). An assertion script, like the rest of this suite.

In process, with telegram.env in a temporary folder and the service control replaced:
nothing here touches the host's paynani-telegram.
"""
from __future__ import annotations

import contextlib
import io
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.telegram import cli, config  # noqa: E402

TOKEN = "123456789:fake_token_only_for_tests_x"
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
env = tmp / "telegram.env"
actions: list[str] = []
answer = {"value": "stopped"}


def control(action):
    actions.append(action)
    return answer["value"] if action == "stop" else answer.get("start", "started")


def run(fn):
    out = io.StringIO()
    real_env, real_control = config.env_path, cli.service_control
    config.env_path = lambda environ=None: env
    cli.service_control = control
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = fn(None)
    finally:
        config.env_path, cli.service_control = real_env, real_control
    return rc, out.getvalue()


rc, out = run(cli.run_disable)
check("disable sin telegram.env: 0, nada que hacer, no toca el servicio", (0, False, []),
      (rc, env.exists(), actions))
rc, out = run(cli.run_enable)
check("enable sin token: 2 y pide setup", (2, True), (rc, "telegram setup" in out))

config.write(config.with_token({"TELEGRAM_SEND_PER_DAY": "80"}, TOKEN), env)
rc, out = run(cli.run_disable)
values = config.read(env)
check("disable: TELEGRAM_ENABLED=0, el token y los ajustes se quedan", ("0", TOKEN, "80"),
      (values.get("TELEGRAM_ENABLED"), values.get("TELEGRAM_TOKEN"), values.get("TELEGRAM_SEND_PER_DAY")))
check("disable: ya no cuenta como configurado (la pasarela y la web lo dejan de mostrar)", False,
      config.configured(env))
check("disable: detiene el servicio y dice cómo volver", (0, ["stop"], True),
      (rc, actions, "telegram enable" in out))
check("telegram.env sigue 0600", 0o600, stat.S_IMODE(os.stat(env).st_mode))
check("el token no sale en la salida", False, TOKEN in out)

actions.clear()
rc, out = run(cli.run_disable)
check("disable dos veces: lo dice y vuelve a detenerlo", (0, True, ["stop"]),
      (rc, "ya estaba desactivado" in out, actions))

answer["value"] = "failed"
rc, out = run(cli.run_disable)
check("si no se puede detener: 1 y lo dice", (1, True), (rc, "detenlo a mano" in out))
answer["value"] = "stopped"

actions.clear()
rc, out = run(cli.run_enable)
check("enable: TELEGRAM_ENABLED=1 con el mismo token, configurado, y arranca el servicio", (0, True, ["start"], True),
      (rc, config.configured(env), actions, "arrancó" in out))
check("enable: el token no sale en la salida", False, TOKEN in out)

answer["start"] = "failed"
config.write(dict(config.read(env), TELEGRAM_ENABLED="0"), env)
rc, out = run(cli.run_enable)
check("enable si el servicio no arranca: 1, lo dice, y telegram.env sí queda en 1 (Ximena en #623)",
      (1, True, True), (rc, "no pude arrancar" in out, config.configured(env)))

answer["start"] = "not-installed"
actions.clear()
rc, out = run(cli.run_enable)
check("enable sin el servicio instalado: dice cómo instalarlo", (0, True, True),
      (rc, "ya estaba activado" in out, "--with-telegram" in out))

# --- service_control en macOS: detener algo que launchd ya tiene detenido es 0 (Ximena en #623) ---
from unittest import mock  # noqa: E402

home = tmp / "home"
(home / "Library" / "LaunchAgents").mkdir(parents=True)
(home / "Library" / "LaunchAgents" / "com.paynani.telegram.plist").write_text("x")


def fake_launchctl(running):
    def run_(argv, *a, **k):
        if argv[:2] == ["launchctl", "kill"]:
            return mock.Mock(returncode=0 if running else 3, stdout="", stderr="")
        if argv[:2] == ["launchctl", "print"]:
            return mock.Mock(returncode=0, stdout="state = running" if running else "state = not running", stderr="")
        return mock.Mock(returncode=1, stdout="", stderr="")
    return run_


import subprocess  # noqa: E402

for running, want in ((False, "stopped"), (True, "stopped")):
    with mock.patch.object(cli.sys, "platform", "darwin"), mock.patch.object(Path, "home", lambda: home), \
         mock.patch.object(subprocess, "run", fake_launchctl(running)):
        got = cli.service_control("stop")
    check(f"macOS stop con el servicio {'corriendo' if running else 'ya detenido'}: stopped", want, got)


def kill_fails_still_running(argv, *a, **k):
    if argv[:2] == ["launchctl", "print"]:
        return mock.Mock(returncode=0, stdout="state = running", stderr="")
    return mock.Mock(returncode=3, stdout="", stderr="")


with mock.patch.object(cli.sys, "platform", "darwin"), mock.patch.object(Path, "home", lambda: home), \
     mock.patch.object(subprocess, "run", kill_fails_still_running):
    got = cli.service_control("stop")
check("macOS stop que falla y sigue corriendo: failed", "failed", got)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
