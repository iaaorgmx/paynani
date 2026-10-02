#!/usr/bin/env python3
"""
Tests for harness/phone.py: la tabla de casos de SMS_GATEWAY.md («Números de
teléfono»), más los bordes. An assertion script, like the rest of this suite.

La tabla es compartida: el roster (SRV-2), la pasarela (SRV-1) y la app Android
tienen que dar exactamente estas salidas. Si cambias una fila aquí, cámbiala en
SMS_GATEWAY.md y en las pruebas de la app en el mismo PR.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))

import phone  # noqa: E402

passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


# La tabla de SMS_GATEWAY.md, fila por fila.
TABLE = [
    ("55 1111 2222", "MX", "+525511112222"),
    ("+52 1 55 1111 2222", "MX", "+525511112222"),
    ("0052 55 1111-2222", "MX", "+525511112222"),
    ("(555) 000-1111", "US", "+15550001111"),
    ("1 555 000 1111", "US", "+15550001111"),
    ("+15550001111", "MX", "+15550001111"),
    ("26262", "MX", None),
    ("AMAZON", "MX", None),
]
for raw, region, expected in TABLE:
    check(f"tabla: {raw!r} {region}", expected, phone.to_e164(raw, region))

# Bordes.
check("alfanumérico con apóstrofo", None, phone.to_e164("O'Shop", "MX"))
check("vacío", None, phone.to_e164("", "MX"))
check("None", None, phone.to_e164(None, "MX"))
check("código corto de 3 dígitos", None, phone.to_e164("911", "MX"))
check("+521 sin espacios", "+525511112222", phone.to_e164("+5215511112222", "MX"))
check("00521", "+525511112222", phone.to_e164("00521 55 1111 2222", "MX"))
check("12 dígitos 52 sin +", "+525511112222", phone.to_e164("525511112222", "MX"))
check("10 dígitos sin regla de la región", None, phone.to_e164("5511112222", "ES"))
check("+ con letras", None, phone.to_e164("+52AB", "MX"))
check("demasiado largo", None, phone.to_e164("+1234567890123456", "MX"))
check("espacio no separable", "+525511112222", phone.to_e164("55 1111 2222", "MX"))
check("puntos", "+525511112222", phone.to_e164("55.1111.2222", "MX"))
check("región en minúsculas", "+15550001111", phone.to_e164("5550001111", "us"))
check("canadá", "+14165550000", phone.to_e164("416 555 0000", "CA"))
check("idempotente", "+525511112222", phone.to_e164(phone.to_e164("55 1111 2222", "MX"), "MX"))

# Región por omisión.
check("región por omisión sin variable", "MX", phone.default_region({}))
check("región de runtime.env", "US", phone.default_region({"PAYNANI_SMS_DEFAULT_REGION": " us "}))
check("región vacía cae en MX", "MX", phone.default_region({"PAYNANI_SMS_DEFAULT_REGION": ""}))

# Celdas del roster.
check("celda con varios números", ["+525511112222", "55 3333 4444"],
      phone.split_cell("+525511112222, 55 3333 4444"))
check("celda vacía", [], phone.split_cell(""))
check("celda None", [], phone.split_cell(None))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
