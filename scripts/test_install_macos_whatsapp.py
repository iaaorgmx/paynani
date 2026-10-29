#!/usr/bin/env python3
"""
The optional WhatsApp LaunchAgent of the macOS installer (WA-3 #555, PRD #550
FR-1, FR-3, FR-3b, FR-10). An assertion script, like the rest of this suite.

Like test_install_macos_sms.py, it drives install_macos.py with launchctl, the
home directory, node and npm stubbed, so it runs on any host.
"""
from __future__ import annotations

import contextlib
import io
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import install_macos as m  # noqa: E402

passed = failed = 0


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
npm_calls: list = []
fake = {"node": "22", "npm_rc": 0, "which_node": "/Users/x/.nvm/versions/node/v22.0.0/bin/node"}
real_run = subprocess.run


def fake_run(argv, *a, **k):
    if argv and argv[0] == fake["which_node"]:
        return mock.Mock(returncode=0, stdout=fake["node"] + "\n", stderr="")
    if argv and argv[0].endswith("/npm"):
        npm_calls.append(list(argv))
        return mock.Mock(returncode=fake["npm_rc"], stdout="", stderr="")
    return real_run(argv, *a, **k)


def which(name, *a, **k):
    if name == "node":
        return fake["which_node"]
    if name == "npm":
        return str(Path(fake["which_node"]).parent / "npm") if fake["which_node"] else None
    return "/usr/bin/" + name


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
         mock.patch.object(m, "service_state", lambda label: "active"), \
         mock.patch.object(m.shutil, "which", which), \
         mock.patch.object(m.subprocess, "run", fake_run), \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        args = m.parse(argv)
        try:
            code = m.uninstall(args) if args.uninstall else m.install(args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


wa = agents / "com.paynani.whatsapp.plist"
wa_env = config / "whatsapp.env"

# --- parse ------------------------------------------------------------------------------
try:
    with contextlib.redirect_stderr(io.StringIO()):
        m.parse(["--runtime", "codex", "--uninstall", "--with-whatsapp"])
    check("--with-whatsapp con --uninstall", "SystemExit", "sin error")
except SystemExit as exc:
    check("--with-whatsapp con --uninstall se rechaza con 64", 64, exc.code)

# --- sin la bandera, nada de WhatsApp ----------------------------------------------------------
code, out, _ = run(["--runtime", "codex"])
check("sin --with-whatsapp: ni LaunchAgent, ni whatsapp.env, ni npm", (False, False, [], False),
      (wa.exists(), wa_env.exists(), npm_calls, "com.paynani.whatsapp" in out))

# --- Node ------------------------------------------------------------------------------------------
fake["which_node"] = None
code, _, err = run(["--runtime", "codex", "--with-whatsapp"])
check("sin Node: no escribe nada y dice cómo instalarlo", (m.EX_CONFIG, False, True),
      (code, wa.exists(), "brew install node" in err))
fake["which_node"] = "/Users/x/.nvm/versions/node/v22.0.0/bin/node"
fake["node"] = "18"
code, _, err = run(["--runtime", "codex", "--with-whatsapp"])
check("con Node 18: no escribe nada", (m.EX_CONFIG, False, True), (code, wa.exists(), "is 18" in err))
fake["node"] = "22"
fake["npm_rc"] = 1
code, _, err = run(["--runtime", "codex", "--with-whatsapp"])
check("npm ci falla: no escribe el LaunchAgent", (m.EX_CONFIG, False), (code, wa.exists()))
fake["npm_rc"] = 0
npm_calls.clear()

# --- instalar ------------------------------------------------------------------------------------------
code, out, _ = run(["--runtime", "codex", "--dry-run", "--with-whatsapp"])
check("dry-run con --with-whatsapp: lo planea sin escribir ni correr npm", (True, False, []),
      ("planned-launchagent=" + str(wa) in out, wa.exists(), npm_calls))
code, out, _ = run(["--runtime", "codex", "--with-whatsapp"])
check("--with-whatsapp instala y arranca el LaunchAgent", (True, True),
      (wa.exists(), ("bootstrap", "com.paynani.whatsapp") in calls))
check("npm ci --ignore-scripts en scripts/whatsapp_bridge",
      [["/Users/x/.nvm/versions/node/v22.0.0/bin/npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix",
        str(ROOT / "scripts" / "whatsapp_bridge")]], npm_calls)
plist = plistlib.loads(wa.read_bytes())
check("plist: whatsapp_service.py de este clon, siempre vivo, umask 077, con sus registros",
      (str(ROOT / "scripts" / "whatsapp_service.py"), True, 0o077, str(state / "whatsapp.log")),
      (plist["ProgramArguments"][-1], plist["KeepAlive"], plist["Umask"], plist["StandardOutPath"]))
check("plist: la carpeta de node (nvm) va primero en el PATH", "/Users/x/.nvm/versions/node/v22.0.0/bin",
      plist["EnvironmentVariables"]["PATH"].split(":")[0])
check("whatsapp.env: 0600 con WHATSAPP_ENABLED=1", (0o600, True),
      (wa_env.stat().st_mode & 0o777, "WHATSAPP_ENABLED=1" in wa_env.read_text()))
manifest_text = (tmp / "install.manifest").read_text()
check("el manifiesto registra el LaunchAgent y no whatsapp.env ni las llaves (FR-10)", (True, False, False),
      (str(wa) in manifest_text, "whatsapp.env" in manifest_text, "whatsapp/auth" in manifest_text))
others = [plistlib.loads((agents / f"com.paynani.{n}.plist").read_bytes())["EnvironmentVariables"]["PATH"]
          for n in ("idle", "dispatch", "logrotate")]
check("los otros LaunchAgents no reciben la carpeta de node", False, any(".nvm" in p for p in others))

# whatsapp.env ya es del dueño: no se reescribe.
wa_env.write_text("WHATSAPP_ENABLED=0\n")
code, _, _ = run(["--runtime", "codex", "--with-whatsapp"])
check("un segundo install no reescribe whatsapp.env", "WHATSAPP_ENABLED=0\n", wa_env.read_text())
calls.clear()
code, _, _ = run(["--runtime", "codex", "--upgrade"])
check("un upgrade sin la bandera sigue atendiendo el LaunchAgent instalado", (True, True),
      (wa.exists(), ("bootstrap", "com.paynani.whatsapp") in calls))

# --- un LaunchAgent ajeno no se pisa ------------------------------------------------------------------
run(["--runtime", "codex", "--uninstall"])
wa.write_bytes(plistlib.dumps({"Label": "com.paynani.whatsapp", "ProgramArguments": ["/otro/whatsapp_service.py"]}))
code, _, err = run(["--runtime", "codex", "--with-whatsapp"])
check("un LaunchAgent de WhatsApp que no es de este clon se rechaza", (m.EX_CONFIG, True), (code, "unowned" in err))
wa.unlink()

# --- desinstalar ------------------------------------------------------------------------------------------
run(["--runtime", "codex", "--with-whatsapp"])
calls.clear()
code, out, _ = run(["--runtime", "codex", "--uninstall"])
check("uninstall quita y detiene el LaunchAgent de WhatsApp", (False, True),
      (wa.exists(), any(c[:1] == ("bootout",) and "com.paynani.whatsapp" in str(c) for c in calls)))
check("uninstall deja whatsapp.env (es del dueño)", True, wa_env.exists())

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
