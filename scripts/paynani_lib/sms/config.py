"""
Los ajustes del usuario para la pasarela SMS: `sms.env`, junto a `runtime.env`.

`runtime.env` es del instalador (un cambio a mano detiene el siguiente
`install.sh --upgrade`), así que lo que el usuario sí decide, el puerto y la
dirección del túnel, vive en un archivo que el instalador nunca crea, edita,
anota en el manifiesto ni quita. Lo lee el propio Python, no systemd ni launchd,
para que valga igual en la pasarela, en `paynani sms pair` y en `paynani sms send`,
en Linux y en macOS.

    PAYNANI_SMS_PORT=8770
    PAYNANI_SMS_PUBLIC_URL=https://<tu túnel>
    PAYNANI_SMS_BATTERY_WARN_PCT=25
    PAYNANI_SMS_BATTERY_CRITICAL_PCT=10
    PAYNANI_WEB_PORT=8771

`PAYNANI_WEB_PORT` es el de PaynaniWeb (PRD #434): la pasarela le reenvía lo que
no es de /sms/, y PaynaniWeb escucha ahí.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness"))

import paths  # noqa: E402

KEYS = ("PAYNANI_SMS_PORT", "PAYNANI_SMS_PUBLIC_URL", "PAYNANI_SMS_DEFAULT_REGION",
        "PAYNANI_SMS_BATTERY_WARN_PCT", "PAYNANI_SMS_BATTERY_CRITICAL_PCT", "PAYNANI_WEB_PORT")
# Los avisos de batería del teléfono (PaynaniApp#109, Q88): aviso y crítico.
BATTERY_WARN_PCT = 25
BATTERY_CRITICAL_PCT = 10
FILE_NAME = "sms.env"
WEB_PORT = 8771


def sms_env_path() -> Path:
    return paths.config_dir() / FILE_NAME


def load_sms_env(path=None, environ=None) -> dict:
    """
    Pone en el entorno las claves de `sms.env` que todavía no estén definidas.

    El entorno del proceso gana al archivo. Sólo las claves de `KEYS`; todo
    lo demás se ignora, igual que las líneas vacías y las que empiezan con `#`.
    Sin archivo (o ilegible) no hace nada. Devuelve lo que puso, para quien quiera
    saberlo.
    """
    environ = os.environ if environ is None else environ
    path = sms_env_path() if path is None else Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    applied = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name in KEYS and name not in environ:
            environ[name] = value
            applied[name] = value
    return applied


def battery_thresholds(environ=None, problems=None) -> tuple[int, int]:
    """
    (aviso, crítico) en porcentaje, de `PAYNANI_SMS_BATTERY_WARN_PCT` y
    `PAYNANI_SMS_BATTERY_CRITICAL_PCT`. Un valor que no es un entero de 1 a 99, o
    un crítico que no queda por debajo del aviso, vuelve a los de omisión (25 y 10):
    un `sms.env` con un error de dedo nunca apaga los avisos. Lo que se corrigió se
    agrega a `problems` (una lista), para que quien arranca lo diga en el log.
    """
    environ = os.environ if environ is None else environ
    problems = [] if problems is None else problems

    def pct(name, default):
        raw = environ.get(name)
        if raw is None:
            return default
        try:
            value = int(str(raw).strip())
        except ValueError:
            problems.append(f"{name}={raw!r} no es un número; se usa {default}")
            return default
        if not 1 <= value <= 99:
            problems.append(f"{name}={value} está fuera de 1 a 99; se usa {default}")
            return default
        return value

    warn = pct("PAYNANI_SMS_BATTERY_WARN_PCT", BATTERY_WARN_PCT)
    critical = pct("PAYNANI_SMS_BATTERY_CRITICAL_PCT", BATTERY_CRITICAL_PCT)
    if critical >= warn:
        problems.append(f"el crítico ({critical}) no queda debajo del aviso ({warn}); se usan "
                        f"{BATTERY_WARN_PCT} y {BATTERY_CRITICAL_PCT}")
        return BATTERY_WARN_PCT, BATTERY_CRITICAL_PCT
    return warn, critical


def web_port(arg=None, gateway_port=None, environ=None) -> tuple[int, str]:
    """
    (puerto, problema) de PaynaniWeb: `arg` (--web-port) si viene, si no
    `PAYNANI_WEB_PORT`, si no 8771. 0 apaga el reenvío. Un valor que no es un
    puerto vuelve a 8771, y uno igual al de la pasarela apaga el reenvío: la
    pasarela se estaría reenviando a sí misma. `problema` es la línea para el log,
    o "".
    """
    environ = os.environ if environ is None else environ
    raw = arg if arg is not None else environ.get("PAYNANI_WEB_PORT")
    if raw is None or str(raw).strip() == "":
        port, problem = WEB_PORT, ""
    else:
        try:
            port, problem = int(str(raw).strip()), ""
        except ValueError:
            port, problem = WEB_PORT, f"PAYNANI_WEB_PORT={raw!r} no es un número; se usa {WEB_PORT}"
        if not problem and not 0 <= port <= 65535:
            port, problem = WEB_PORT, f"PAYNANI_WEB_PORT={port} no es un puerto; se usa {WEB_PORT}"
    if port and gateway_port is not None and port == int(gateway_port):
        return 0, (f"PaynaniWeb y la pasarela tienen el mismo puerto ({port}); se apaga el reenvío "
                   "para no reenviarse a sí misma")
    return port, problem
