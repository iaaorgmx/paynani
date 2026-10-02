#!/usr/bin/env python3
"""
The optional SMS gateway LaunchAgent of the macOS installer (SRV-7).
An assertion script, like the rest of this suite.

test_install_macos.py only runs on a Mac. This one drives the same functions with
launchctl and the home directory stubbed, so the logic is covered on any host.
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


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


tmp = Path(tempfile.mkdtemp())
agents = tmp / "LaunchAgents"
state = tmp / "state"
env_file = tmp / "mail.env"
env_file.write_text("x=1\n")
env_file.chmod(0o600)
calls = []


def fake_launchctl(*args, check=False):
    calls.append(args)
    return mock.Mock(returncode=0, stdout="", stderr="")


def run(argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(m, "launch_agent_dir", lambda: agents), \
         mock.patch.object(m, "state_dir", lambda: state), \
         mock.patch.object(m, "env_file", lambda: env_file), \
         mock.patch.object(m, "runtime_env", lambda: tmp / "runtime.env"), \
         mock.patch.object(m, "run_launchctl", fake_launchctl), \
         mock.patch.object(m, "bootstrap", lambda path, label: calls.append(("bootstrap", label)) or True), \
         mock.patch.object(m, "service_state", lambda label: "active"), \
         mock.patch.object(m.shutil, "which", lambda name: "/usr/bin/" + name), \
         mock.patch.dict(os.environ, env or {}, clear=False), \
         contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        args = m.parse(argv)
        try:
            code = m.uninstall(args) if args.uninstall else m.install(args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


sms = agents / "com.paynani.sms.plist"

# --- parse ---------------------------------------------------------------------------
try:
    with contextlib.redirect_stderr(io.StringIO()):
        m.parse(["--runtime", "codex", "--uninstall", "--with-sms"])
    check("--with-sms con --uninstall", "SystemExit", "sin error")
except SystemExit as exc:
    check("--with-sms con --uninstall se rechaza con 64", 64, exc.code)

# --- el plist ---------------------------------------------------------------------------
with mock.patch.object(m, "state_dir", lambda: state), mock.patch.object(m, "env_file", lambda: env_file), \
     mock.patch.dict(os.environ, {"PAYNANI_SMS_PORT": "8771", "PAYNANI_SMS_PUBLIC_URL": "https://x.ngrok.io"}):
    plist = m.plist_for("sms", "/usr/bin/python3", "codex")
check("plist: sms_gateway.py de este clon, siempre vivo", (True, True, True),
      (plist["ProgramArguments"] == ["/usr/bin/python3", str(ROOT / "scripts" / "sms_gateway.py")],
       plist["KeepAlive"], plist["RunAtLoad"]))
check("plist: registros sms.log y sms.err.log en state/", (str(state / "sms.log"), str(state / "sms.err.log")),
      (plist["StandardOutPath"], plist["StandardErrorPath"]))
check("plist: el puerto y la URL no se escriben en el LaunchAgent (los lee sms.env)", (False, False),
      ("PAYNANI_SMS_PORT" in plist["EnvironmentVariables"], "PAYNANI_SMS_PUBLIC_URL" in plist["EnvironmentVariables"]))
with mock.patch.object(m, "state_dir", lambda: state), mock.patch.object(m, "env_file", lambda: env_file), \
     mock.patch.dict(os.environ, {}, clear=False):
    os.environ.pop("PAYNANI_SMS_PORT", None)
    os.environ.pop("PAYNANI_SMS_PUBLIC_URL", None)
    bare = m.plist_for("sms", "/usr/bin/python3", "codex")
check("plist: sin variables, no inventa ninguna", False, "PAYNANI_SMS_PORT" in bare["EnvironmentVariables"])

# --- instalar -------------------------------------------------------------------------------
code, out, _ = run(["--runtime", "codex"])
check("sin --with-sms: se instalan los tres de siempre y ninguno de SMS", (True, False, False),
      (all((agents / f"com.paynani.{n}.plist").exists() for n in ("idle", "dispatch", "logrotate")),
       sms.exists(), "com.paynani.sms" in out))
code, out, _ = run(["--runtime", "codex", "--dry-run"])
check("el dry-run sin --with-sms no menciona la pasarela", False, "com.paynani.sms" in out)
code, out, _ = run(["--runtime", "codex", "--dry-run", "--with-sms"])
check("el dry-run con --with-sms la planea y no la escribe", (True, False),
      ("planned-launchagent=" + str(sms) in out, sms.exists()))
code, out, _ = run(["--runtime", "codex", "--with-sms"])
check("--with-sms instala y arranca el LaunchAgent de la pasarela", (True, True, True),
      (sms.exists(), ("bootstrap", "com.paynani.sms") in calls, f"launchagent={sms} label=com.paynani.sms" in out))
check("el plist escrito es el de plist_for", "com.paynani.sms", plistlib.loads(sms.read_bytes())["Label"])
calls.clear()
code, out, _ = run(["--runtime", "codex", "--upgrade"])
check("un upgrade sin la bandera sigue atendiendo la pasarela instalada", (True, True),
      (sms.exists(), ("bootstrap", "com.paynani.sms") in calls))

# --- una pasarela ajena no se pisa ---------------------------------------------------------------
sms.write_bytes(plistlib.dumps({"Label": "com.paynani.sms", "ProgramArguments": ["/otro/lugar/sms_gateway.py"]}))
code, _, err = run(["--runtime", "codex", "--with-sms"])
check("un LaunchAgent que no es de este clon se rechaza", (m.EX_CONFIG, True), (code, "unowned" in err))
sms.unlink()

# --- desinstalar --------------------------------------------------------------------------------------
run(["--runtime", "codex", "--with-sms"])
calls.clear()
code, out, _ = run(["--runtime", "codex", "--uninstall"])
check("uninstall quita también la pasarela instalada", (False, True), (sms.exists(), "removed_launchagent=" + str(sms) in out))
check("uninstall la detiene con bootout", True, any(c[:1] == ("bootout",) and "com.paynani.sms" in str(c) for c in calls))
calls.clear()
code, out, _ = run(["--runtime", "codex", "--uninstall"])
check("uninstall sin pasarela no la menciona ni la toca", (False, False),
      ("com.paynani.sms" in out, any("com.paynani.sms" in str(c) for c in calls)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
