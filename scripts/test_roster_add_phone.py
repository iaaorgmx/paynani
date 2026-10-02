#!/usr/bin/env python3
"""
Tests for `paynani roster add --phone` (SRV-4 follow-up; roster.md Phone column, SRV-2).
An assertion script, like the rest of this suite.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import roster as roster_mod  # noqa: E402
from paynani_lib import roster_cli  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


WITH_PHONE = """# roster

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human |  | +52 1 55 1111 2222 |
"""
NO_PHONE = """# roster

# 1. Approved contacts

| Name | Email | Type | GitHub |
|---|---|---|---|
| Ana López | ana@example.com | Human |  |
"""

# --- add_contact -------------------------------------------------------------
ok, text = roster_mod.add_contact(WITH_PHONE, "Beto", "beto@example.com", type_="Human", phone_cell="55 3333 4444, +1 555 000 1111")
check("add_contact con teléfonos: se guardan en E.164, separados por coma", (True, True),
      (ok, "| Beto | beto@example.com | Human |  | +525533334444, +15550001111 |" in text))
check("el roster los lee de vuelta", {"+525511112222", "+525533334444", "+15550001111"}, {e["phone"] for e in roster_mod._phone_entries_from_text(text)})
ok, text2 = roster_mod.add_contact(WITH_PHONE, "Beto", "beto@example.com")
check("sin --phone la celda queda vacía", (True, True), (ok, "| Beto | beto@example.com |  |  |  |" in text2))
ok, why = roster_mod.add_contact(WITH_PHONE, "Beto", "beto@example.com", phone_cell="AMAZON")
check("un valor que no es teléfono se rechaza con el ejemplo en E.164", (False, True), (ok, "not a phone number" in why and "+525511112222" in why))
ok, why = roster_mod.add_contact(WITH_PHONE, "Beto", "beto@example.com", phone_cell="55 3333 4444, hola")
check("un solo valor malo rechaza todo", False, ok)
ok, why = roster_mod.add_contact(WITH_PHONE, "Beto", "beto@example.com", phone_cell="+52 55 1111 2222")
check("el número de otro contacto se rechaza, diciendo de quién es", (False, True), (ok, "already the phone of Ana López" in why))
ok, text3 = roster_mod.add_contact(WITH_PHONE, "Beto", "beto@example.com", phone_cell="55 3333 4444, 5533334444")
check("el mismo número dos veces se guarda una vez", (True, True), (ok, "| +525533334444 |" in text3))
ok, why = roster_mod.add_contact(NO_PHONE, "Beto", "beto@example.com", phone_cell="55 3333 4444")
check("sin columna Phone: se rechaza y dice qué hacer", (False, True), (ok, "no Phone column" in why))
ok, text4 = roster_mod.add_contact(NO_PHONE, "Beto", "beto@example.com")
check("sin columna Phone y sin --phone: sigue igual que antes", (True, True), (ok, "| Beto | beto@example.com |  |  |" in text4))

# --- paynani roster add ---------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
path = tmp / "roster.md"
path.write_text(WITH_PHONE, encoding="utf-8")
roster_cli.roster_file = lambda: path
roster_cli._run_regression_tests = lambda: (True, "")


def run_add(**kw):
    args = SimpleNamespace(name="Beto", address="beto@example.com", type="Human", github=None, phone=None, yes=True, roster=None)
    args.__dict__.update(kw)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = roster_cli.run_add(args)
    return code, out.getvalue(), err.getvalue()


code, _, err = run_add(phone="hola")
check("CLI: teléfono inválido, código 1 y el roster no cambia", (1, True, WITH_PHONE), (code, "not a phone number" in err, path.read_text()))
code, _, _ = run_add(phone="55 3333 4444")
check("CLI: --phone agrega el contacto con su teléfono", (0, True), (code, "| Beto | beto@example.com | Human |  | +525533334444 |" in path.read_text()))
check("CLI: el roster resultante autoriza ese número", True,
      "+525533334444" in roster_mod.roster_phones(path))
code, _, err = run_add(address="otro@example.com", name="Otro", phone="+525533334444")
check("CLI: un número ya usado se rechaza", (1, True), (code, "already the phone of Beto" in err))

status, detail = roster_cli.add_contact_noninteractive("Cata", "cata@example.com", type_="Human", phone="+525599998888")
check("add_contact_noninteractive acepta phone", ("added", True), (status, "+525599998888" in path.read_text()))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
