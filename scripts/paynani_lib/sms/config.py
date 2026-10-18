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
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness"))

import paths  # noqa: E402

KEYS = ("PAYNANI_SMS_PORT", "PAYNANI_SMS_PUBLIC_URL", "PAYNANI_SMS_DEFAULT_REGION",
        "PAYNANI_SMS_BATTERY_WARN_PCT", "PAYNANI_SMS_BATTERY_CRITICAL_PCT")
# Los avisos de batería del teléfono (PaynaniApp#109, Q88): aviso y crítico.
BATTERY_WARN_PCT = 25
BATTERY_CRITICAL_PCT = 10
FILE_NAME = "sms.env"


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


def battery_thresholds(environ=None) -> tuple[int, int]:
    """
    (aviso, crítico) en porcentaje, de `PAYNANI_SMS_BATTERY_WARN_PCT` y
    `PAYNANI_SMS_BATTERY_CRITICAL_PCT`. Un valor que no es un entero de 1 a 99, o
    un crítico que no queda por debajo del aviso, vuelve a los de omisión (25 y 10):
    un `sms.env` con un error de dedo nunca apaga los avisos.
    """
    environ = os.environ if environ is None else environ

    def pct(name, default):
        try:
            value = int(str(environ.get(name, default)).strip())
        except ValueError:
            return default
        return value if 1 <= value <= 99 else default

    warn = pct("PAYNANI_SMS_BATTERY_WARN_PCT", BATTERY_WARN_PCT)
    critical = pct("PAYNANI_SMS_BATTERY_CRITICAL_PCT", BATTERY_CRITICAL_PCT)
    if critical >= warn:
        return BATTERY_WARN_PCT, BATTERY_CRITICAL_PCT
    return warn, critical
