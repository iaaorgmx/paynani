#!/usr/bin/env python3
"""
Tests for `paynani roster add --telegram` and `paynani roster edit` (#628, Q269 = A,
Q271 = A). An assertion script, like the rest of this suite.

The roster is a temporary file and the regression run is replaced, as in
test_roster_add_phone.py: nothing here touches the real roster.md.
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

from paynani_lib import roster_cli, roster_edit  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


NO_TELEGRAM = """# roster

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human | analopez | +525511112222 |
| Iris | iris@example.com | AI Agent |  |  |
"""

tmp = Path(tempfile.mkdtemp())
path = tmp / "roster.md"
path.write_text(NO_TELEGRAM, encoding="utf-8")
roster_cli.roster_file = lambda: path
roster_cli._run_regression_tests = lambda: (True, "")


def run(fn, **kw):
    args = SimpleNamespace(yes=True, roster=None, **kw)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(args)
    return code, out.getvalue(), err.getvalue()


def row(email):
    return next(m for m in roster_edit.members(path.read_text(encoding="utf-8"))[1] if m["email"] == email)


# --- add --telegram ------------------------------------------------------------------
code, _, err = run(roster_cli.run_add, name="Beto", address="beto@example.com", type="Human", github=None,
                   phone=None, telegram="no vale")
check("add --telegram con un valor inválido: 1 y el roster no cambia", (1, NO_TELEGRAM),
      (code, path.read_text(encoding="utf-8")))
code, _, _ = run(roster_cli.run_add, name="Beto", address="beto@example.com", type="Human", github=None,
                 phone=None, telegram="@Beto_Tienda")
cols = roster_edit.members(path.read_text(encoding="utf-8"))[0]
check("add --telegram en un roster sin la columna: la crea y guarda el @usuario", (0, True, "@beto_tienda"),
      (code, "Telegram" in cols, row("beto@example.com")["telegram"]))
check("las filas de antes quedan con la celda vacía", ("", ""),
      (row("ana@example.com")["telegram"], row("iris@example.com")["telegram"]))
code, _, err = run(roster_cli.run_add, name="Otro", address="otro@example.com", type="Human", github=None,
                   phone=None, telegram="@beto_tienda")
check("add --telegram con un Telegram de otra fila: 1, sin repetir el valor", (1, True, False),
      (code, "telegram" in err, "beto_tienda" in err))
code, _, _ = run(roster_cli.run_add, name="Sin Tg", address="sintg@example.com", type="Human", github=None,
                 phone=None, telegram=None)
check("add sin --telegram sigue igual", (0, ""), (code, row("sintg@example.com")["telegram"]))

# --- edit ------------------------------------------------------------------------------
base = path.read_text(encoding="utf-8")
code, _, err = run(roster_cli.run_edit, address="ana@example.com", name=None, type=None, github=None,
                   phone=None, telegram=None)
check("edit sin opciones: 1 y no escribe", (1, True, base), (code, "nothing to change" in err,
                                                           path.read_text(encoding="utf-8")))
code, _, err = run(roster_cli.run_edit, address="nadie@example.com", name=None, type=None, github=None,
                   phone=None, telegram="700000001")
check("edit de un correo que no está: 1", (1, True), (code, "not on the roster" in err))
code, _, _ = run(roster_cli.run_edit, address="ANA@example.com", name=None, type=None, github=None,
                 phone=None, telegram="0700000001")
check("edit --telegram con un id: lo normaliza, busca el correo sin importar mayúsculas", (0, "700000001"),
      (code, row("ana@example.com")["telegram"]))
check("y las demás celdas de esa fila no cambian", ("Ana López", "analopez", ["+525511112222"]),
      (row("ana@example.com")["name"], row("ana@example.com")["github"], row("ana@example.com")["phones"]))
code, _, _ = run(roster_cli.run_edit, address="ana@example.com", name="Ana L.", type=None, github=None,
                 phone=None, telegram=None)
check("edit --name sin --telegram conserva el Telegram", (0, "Ana L.", "700000001"),
      (code, row("ana@example.com")["name"], row("ana@example.com")["telegram"]))
code, out, _ = run(roster_cli.run_edit, address="ana@example.com", name="Ana L.", type=None, github=None,
                   phone=None, telegram=None)
check("edit con los mismos valores: 0 y lo dice, sin escribir", (0, True), (code, "Nothing to change" in out))
code, _, _ = run(roster_cli.run_edit, address="ana@example.com", name=None, type=None, github=None,
                 phone=None, telegram="")
check('edit --telegram "" lo borra', (0, ""), (code, row("ana@example.com")["telegram"]))
code, _, _ = run(roster_cli.run_edit, address="iris@example.com", name=None, type=None, github="",
                 phone="+15550001111", telegram=None)
check("edit --phone y --github sobre otra fila", (0, ["+15550001111"], ""),
      (code, row("iris@example.com")["phones"], row("iris@example.com")["github"]))
code, _, err = run(roster_cli.run_edit, address="iris@example.com", name=None, type=None, github=None,
                   phone=None, telegram="@beto_tienda")
check("edit con un Telegram de otra fila: 1", (1, True), (code, "telegram" in err))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
