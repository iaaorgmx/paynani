#!/usr/bin/env python3
"""
Números de teléfono en E.164, con las reglas de SMS_GATEWAY.md («Números de
teléfono»).

Lo usan las dos mitades que tienen que estar de acuerdo: el roster (columna
`Phone`, SRV-2) y la pasarela SMS (SRV-1). Si cada una normalizara por su
cuenta, un número del roster podría no coincidir con el mismo número llegando
por SMS, y el agente le contestaría a quien no debe o no le contestaría a quien
sí. Por eso hay una sola función y una sola tabla de casos
(scripts/test_phone.py), que la app Android también reproduce.

Sólo biblioteca estándar: no hay `phonenumbers`. No es un validador completo
de planes de numeración; hace lo que el roster necesita, que es que el mismo
número escrito de formas distintas termine igual.
"""
import os
import re

DEFAULT_REGION_ENV = "PAYNANI_SMS_DEFAULT_REGION"
DEFAULT_REGION = "MX"

# Lo que se quita antes de mirar dígitos: espacios (incluido el no separable),
# guiones, puntos y paréntesis.
_SEPARATORS = re.compile(r"[\s \-.()]")
# Sólo dígitos ASCII: \d de Python acepta cualquier dígito Unicode, y un número
# en dígitos de ancho completo o arábigo-índicos se parece mucho al de un contacto.
_DIGITS = re.compile(r"[0-9]+")

# Prefijo internacional por región, para números escritos sin "+".
_COUNTRY_CODE = {"MX": "52", "US": "1", "CA": "1"}


def default_region(env=None):
    """La región de runtime.env, o MX."""
    value = (env if env is not None else os.environ).get(DEFAULT_REGION_ENV, "")
    value = value.strip().upper()
    return value or DEFAULT_REGION


def to_e164(raw, region=None):
    """
    `raw` en E.164 (`+` y dígitos), o None si no es un número de teléfono.

    None para remitentes alfanuméricos (`AMAZON`, `O'Shop`) y para códigos
    cortos de 3 a 6 dígitos: ninguno de los dos coincide nunca con el roster.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    compact = _SEPARATORS.sub("", text)
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    plus = compact.startswith("+")
    digits = compact[1:] if plus else compact
    if not _DIGITS.fullmatch(digits or "x"):
        return None  # alfanumérico, o con caracteres que no son de un número
    region = (region or default_region()).upper()

    if plus:
        if digits.startswith("0"):
            return None  # ningún código de país de E.164 empieza con 0
        number = digits
    elif len(digits) <= 6:
        return None  # código corto
    elif region == "MX" and len(digits) == 10:
        number = "52" + digits
    elif region in ("US", "CA") and len(digits) == 10:
        number = "1" + digits
    elif region in ("US", "CA") and len(digits) == 11 and digits.startswith("1"):
        number = digits
    elif region == "MX" and len(digits) == 12 and digits.startswith("52"):
        number = digits
    else:
        # Sin "+" y sin una regla de la región: no se adivina el país.
        return None

    # México: el "1" de los móviles que se dejó de usar en 2019 (+521 y 10
    # dígitos) es el mismo número que +52 y esos 10.
    if number.startswith("521") and len(number) == 13:
        number = "52" + number[3:]

    if not 8 <= len(number) <= 15:
        return None
    return "+" + number


def split_cell(cell):
    """Los números de una celda `Phone` del roster: separados por coma."""
    return [part.strip() for part in str(cell or "").split(",") if part.strip()]
