#!/usr/bin/env python3
"""
Tests for `configured()` (WA-2 #554, WHATSAPP_BRIDGE.md §11): the one predicate for
"WhatsApp is on" that the service, the gateway, PaynaniWeb and the installer share.
An assertion script, like the rest of this suite.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.whatsapp import config  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    f = tmp / "whatsapp.env"

    def case(label, text, expected):
        f.write_bytes(text if isinstance(text, bytes) else text.encode())
        check(label, expected, config.configured(f))

    check("sin archivo: no configurado", False, config.configured(f))
    case("WHATSAPP_ENABLED=1: configurado", "WHATSAPP_ENABLED=1\n", True)
    case("con comillas y comentarios: configurado", "# activado por install.sh\nWHATSAPP_ENABLED=\"1\"\n\n", True)
    case("WHATSAPP_ENABLED=0 (desactivado): no", "WHATSAPP_ENABLED=0\n", False)
    case("sin la clave: no", "WHATSAPP_MAX_MEDIA_MB=10\n", False)
    case("vacío: no", "", False)
    case("una línea que no se entiende: no", "WHATSAPP_ENABLED=1\nesto no es una clave\n", False)
    case("minúsculas no cuentan: no", "whatsapp_enabled=1\n", False)
    case("«true» no es 1: no", "WHATSAPP_ENABLED=true\n", False)
    case("no es UTF-8: no", b"WHATSAPP_ENABLED=1\n\xff\xfe\n", False)

    f.write_text("WHATSAPP_ENABLED=1\n")
    os.chmod(f, 0o000)
    if os.geteuid() != 0:
        check("ilegible: no", False, config.configured(f))
    os.chmod(f, 0o600)

    real = tmp / "real.env"
    real.write_text("WHATSAPP_ENABLED=1\n")
    f.unlink()
    os.symlink(real, f)
    check("un enlace simbólico a un archivo válido: no", False, config.configured(f))
    f.unlink()
    f.mkdir()
    check("una carpeta: no", False, config.configured(f))
    f.rmdir()

check("env_path(): whatsapp.env junto a runtime.env (la raíz de la instalación)",
      ROOT / "whatsapp.env", config.env_path())
check("setting: omisión sin valor", 25, config.setting("WHATSAPP_MAX_MEDIA_MB", {}))
check("setting: un valor válido", 10, config.setting("WHATSAPP_MAX_MEDIA_MB", {"WHATSAPP_MAX_MEDIA_MB": "10"}))
check("setting: fuera de rango vuelve a la omisión", 200, config.setting("WHATSAPP_SEND_PER_DAY", {"WHATSAPP_SEND_PER_DAY": "99999"}))
check("setting: no numérico vuelve a la omisión", 3, config.setting("WHATSAPP_SEND_INTERVAL_S", {"WHATSAPP_SEND_INTERVAL_S": "x"}))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
