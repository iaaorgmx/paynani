#!/usr/bin/env python3
"""
The optional Telegram LaunchAgent of the macOS installer (TG-6 of #612, PRD #609
FR-1). An assertion script, like the rest of this suite.

Like test_install_macos_whatsapp.py, it drives install_macos.py with launchctl and
the home directory stubbed, so it runs on any host.
"""
from __future__ import annotations

import contextlib
import io
import os
import plistlib
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import install_macos as m  # noqa: E402

passed = failed = 0
TOKEN = "123456789:fake_token_only_for_tests_x"


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


tmp = Path(tempfile.mkdtemp()).resolve()
agents = tmp / "LaunchAgents"
state = tmp / "state"
config = tmp / "config"
config.mkdir()
env_file = tmp / "mail.env"
env_file.write_text("x=1\n")
env_file.chmod(0o600)
calls: list = []


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(m, "launch_agent_dir", lambda: agents), \
         mock.patch.object(m, "state_dir", lambda: state), \
         mock.patch.object(m, "config_dir", lambda: config), \
         mock.patch.object(m, "env_file", lambda: env_file), \
         mock.patch.object(m, "runtime_env", lambda: tmp / "runtime.env"), \
         mock.patch.object(m, "manifest", lambda: tmp / "install.manifest"), \
         mock.patch.object(m, "run_launchctl", lambda *a, **k: calls.append(a) or mock.Mock(returncode=0)), \
         mock.patch.object(m, "bootstrap", lambda path, label: calls.append(("bootstrap", label)) or True), \
         mock.patch.object(m, "service_state", lambda label: "loaded"), \
         mock.patch.object(m.shutil, "which", lambda name, *a, **k: "/usr/bin/" + name), \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        args = m.parse(argv)
        try:
            code = m.uninstall(args) if args.uninstall else m.install(args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


tg = agents / "com.paynani.telegram.plist"
tg_env = config / "telegram.env"


def write_env(enabled: str) -> None:
    fd = os.open(tg_env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"TELEGRAM_ENABLED={enabled}\nTELEGRAM_TOKEN={TOKEN}\n")


try:
    with contextlib.redirect_stderr(io.StringIO()):
        m.parse(["--runtime", "codex", "--uninstall", "--with-telegram"])
    check("--with-telegram con --uninstall", "SystemExit", "sin error")
except SystemExit as exc:
    check("--with-telegram con --uninstall se rechaza con 64", 64, exc.code)

code, out, _ = run(["--runtime", "codex"])
check("sin --with-telegram: ni LaunchAgent ni nada de Telegram", (False, False, False),
      (tg.exists(), tg_env.exists(), "com.paynani.telegram" in out))

code, out, _ = run(["--runtime", "codex", "--dry-run", "--with-telegram"])
check("dry-run con --with-telegram: lo planea sin escribir", (True, False),
      ("planned-launchagent=" + str(tg) in out, tg.exists()))

code, out, _ = run(["--runtime", "codex", "--with-telegram"])
check("--with-telegram sin telegram.env: instala, carga y dice que falta setup", (True, True, True, False),
      (tg.exists(), ("bootstrap", "com.paynani.telegram") in calls,
       'telegram=waiting-setup next="paynani telegram setup"' in out, tg_env.exists()))
plist = plistlib.loads(tg.read_bytes())
check("plist: telegram_service.py de este clon, sólo se reinicia si falla, umask 077, con sus registros",
      (str(ROOT / "scripts" / "telegram_service.py"), {"SuccessfulExit": False}, 0o077, str(state / "telegram.log")),
      (plist["ProgramArguments"][-1], plist["KeepAlive"], plist["Umask"], plist["StandardOutPath"]))
check("plist: sin el token", False, TOKEN in tg.read_text(errors="replace"))
manifest_text = (tmp / "install.manifest").read_text()
check("el manifiesto registra el LaunchAgent y no telegram.env", (True, False),
      (str(tg) in manifest_text, "telegram.env" in manifest_text))

write_env("1")
code, out, _ = run(["--runtime", "codex", "--upgrade"])
check("con telegram.env: el upgrade lo atiende y ya no pide setup", (True, False, False),
      (("bootstrap", "com.paynani.telegram") in calls, "waiting-setup" in out, TOKEN in out))
write_env("0")
code, out, _ = run(["--runtime", "codex", "--upgrade"])
check("desactivado en telegram.env: vuelve a decir que espera", True, "telegram=waiting-setup" in out)

calls.clear()
code, out, _ = run(["--runtime", "codex", "--uninstall"])
check("uninstall quita y detiene el LaunchAgent de Telegram y deja telegram.env", (False, True, True),
      (tg.exists(), any(c[:1] == ("bootout",) and "com.paynani.telegram" in str(c) for c in calls), tg_env.exists()))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
