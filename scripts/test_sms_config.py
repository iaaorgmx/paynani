#!/usr/bin/env python3
"""
sms.env: the user's settings for the SMS gateway (SRV-7, paynani_lib/sms/config.py).
An assertion script, like the rest of this suite.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import config  # noqa: E402

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
f = tmp / "sms.env"

env = {}
check("sin archivo no hace nada", ({}, {}), (config.load_sms_env(f, env), env))

f.write_text("""# mis ajustes
PAYNANI_SMS_PORT=8771

PAYNANI_SMS_PUBLIC_URL = https://x.ngrok.io
  # comentada con sangría
PAYNANI_SMS_DEFAULT_REGION="US"
OTRA_COSA=no
PAYNANI_SMS_PORT_EXTRA=no
""", encoding="utf-8")
env = {}
applied = config.load_sms_env(f, env)
check("un valor del archivo entra cuando la variable no existe",
      {"PAYNANI_SMS_PORT": "8771", "PAYNANI_SMS_PUBLIC_URL": "https://x.ngrok.io", "PAYNANI_SMS_DEFAULT_REGION": "US"}, env)
check("devuelve lo que puso", env, applied)
check("una clave fuera de las tres se ignora", (False, False), ("OTRA_COSA" in env, "PAYNANI_SMS_PORT_EXTRA" in env))

env = {"PAYNANI_SMS_PORT": "9000"}
config.load_sms_env(f, env)
check("la variable del entorno gana al archivo", ("9000", "https://x.ngrok.io"), (env["PAYNANI_SMS_PORT"], env["PAYNANI_SMS_PUBLIC_URL"]))

f.write_text("# PAYNANI_SMS_PORT=1\n#PAYNANI_SMS_PUBLIC_URL=https://no\n", encoding="utf-8")
env = {}
config.load_sms_env(f, env)
check("las líneas # se ignoran", {}, env)

f.write_text("PAYNANI_SMS_PORT=8771\n", encoding="utf-8")
check("un archivo ilegible no rompe nada", {}, config.load_sms_env(tmp, {}))

# --- dónde vive ------------------------------------------------------------------------------
check("sms.env está junto a runtime.env", config.paths.runtime_env().parent / "sms.env", config.sms_env_path())

# --- los dos puntos de entrada lo leen de verdad ---------------------------------------------------
home = tmp / "clone"
home.mkdir()
(home / "sms.env").write_text("PAYNANI_SMS_PORT=8799\nPAYNANI_SMS_PUBLIC_URL=https://desde-sms-env.example\n", encoding="utf-8")
base = {k: v for k, v in os.environ.items() if not k.startswith("PAYNANI_")}
base["PAYNANI_STATE"] = str(tmp / "state")
base["HOME"] = str(tmp)


def run(argv, extra=None):
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, env={**base, **(extra or {})})


# `sms pair` imprime el contenido del QR con la dirección del archivo, sin exportar nada
probe = ("import sys,os; sys.path.insert(0,%r); sys.path.insert(0,%r); "
         "import paths; paths.config_dir = lambda environ=None, home=None: __import__('pathlib').Path(%r); "
         "from paynani_lib.sms import config; config.load_sms_env(); "
         "print(os.environ.get('PAYNANI_SMS_PORT'), os.environ.get('PAYNANI_SMS_PUBLIC_URL'))"
         % (str(ROOT / "harness"), str(ROOT / "scripts"), str(home)))
r = run([sys.executable, "-c", probe])
check("load_sms_env() sin argumentos lee el sms.env de la instalación", ("8799 https://desde-sms-env.example", 0),
      (r.stdout.strip(), r.returncode))

src = (ROOT / "scripts" / "sms_gateway.py").read_text(encoding="utf-8")
check("sms_gateway.py lo carga antes de armar argparse", True,
      src.index("sms_config.load_sms_env()") < src.index("argparse.ArgumentParser("))
src = (ROOT / "scripts" / "paynani").read_text(encoding="utf-8")
check("paynani lo carga antes de despachar cualquier subcomando sms", True,
      src.index("sms_config.load_sms_env()") < src.index("sms_cli.run_pair"))

# --- de punta a punta: el comando real lee el archivo real -----------------------------------------
real = ROOT / "sms.env"
if real.exists():
    print("skip e2e: ya hay un sms.env en este clon, no lo piso")
else:
    try:
        real.write_text("PAYNANI_SMS_PUBLIC_URL=https://desde-sms-env.example\n", encoding="utf-8")
        r = run([str(ROOT / "scripts" / "paynani"), "sms", "pair"])
        check("paynani sms pair saca la dirección del túnel de sms.env, sin exportar nada", (0, True),
              (r.returncode, "https://desde-sms-env.example/sms/pair" in r.stdout))
        r = run([str(ROOT / "scripts" / "paynani"), "sms", "pair"], {"PAYNANI_SMS_PUBLIC_URL": "https://del-entorno.example"})
        check("y el entorno gana al archivo en el comando real", True,
              "https://del-entorno.example/sms/pair" in r.stdout and "desde-sms-env" not in r.stdout)
    finally:
        real.unlink(missing_ok=True)
check("el clon no se queda con un sms.env", False, real.exists())

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
