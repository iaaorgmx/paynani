#!/usr/bin/env python3
"""
Tests for roster_edit.py (R2 de #410, SMS_GATEWAY.md §11): leer la tabla de
contactos, validar un contacto, el alta, la edición y la baja, y el paso único de
bloqueo, `etag`, copia fechada, escritura y relectura, también contra
`paynani roster` (roster_cli). Una secuencia de aserciones, como el resto.

Todo en un directorio temporal: nunca toca el roster.md de la instalación.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import roster_cli  # noqa: E402
from paynani_lib import roster_edit as re_  # noqa: E402
from paynani_lib.roster_edit import EditError  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def error_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except EditError as exc:
        return (exc.code, exc.field, exc.reason)
    return None


ROSTER = """# roster de prueba
# | Comentado | no@cuenta.com | Human |

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone | Notes |
|---|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | +52 1 55 1111 2222, +15550001111 | dueño |
| Iris | iris@example.com | AI Agent | irisclaudetob |  | agente |
| Solo Tel |  | Human |  | +525533334444 |  |

## Notifiers

| Address | Header | Column |
|---|---|---|
| notifications@github.com | X-GitHub-Sender | GitHub |
"""

# --- leer ---------------------------------------------------------------------
cols, rows = re_.members(ROSTER)
check("columns: las que conoce la app, en orden; Notes no", ["Name", "Email", "Type", "GitHub", "Phone"], cols)
check("tres filas; ni el comentario ni los notificadores", ["Julián Flores", "Iris", "Solo Tel"],
      [m["name"] for m in rows])
check("phones en E.164, varios por celda", ["+525511112222", "+15550001111"], rows[0]["phones"])
check("el dueño es el primer Human", [True, False, False], [m["owner"] for m in rows])
check("una fila sólo con teléfono", ("", ["+525533334444"]), (rows[2]["email"], rows[2]["phones"]))
check("sin columna Rules, rules es None", None, rows[0]["rules"])
check("columna vieja `address` se ve como Email", ["Name", "Email"],
      re_.members("| Name | address |\n|---|---|\n| A | a@b.co |\n")[0])
check("etag de un archivo que no existe es vacío", "", re_.etag_of(None))
check("etag es el SHA-256 en hex", 64, len(re_.etag_of(b"x")))

# --- validar ---------------------------------------------------------------------
others = rows[1:]
good = {"name": "Ana Ruiz", "email": "ana@example.com", "type": "human", "github": "", "phones": ["+525511113333"]}
clean = re_.validate(good, cols, others, owner=False)
check("validate limpia y normaliza el tipo", ("Ana Ruiz", "Human", ["+525511113333"]),
      (clean["name"], clean["type"], clean["phones"]))
cases = [
    ("nombre vacío", {**good, "name": "  "}, ("invalid", "name", "required")),
    ("nombre con |", {**good, "name": "A | B"}, ("invalid", "name", "required")),
    ("correo inválido", {**good, "email": "ana@"}, ("invalid", "email", "email_format")),
    ("teléfono fuera de E.164", {**good, "phones": ["55 1111 3333"]}, ("invalid", "phones", "phone_e164")),
    ("sin correo ni teléfono", {**good, "email": "", "phones": []}, ("invalid", "email", "no_channel")),
    ("correo de otra fila, sin distinguir mayúsculas", {**good, "email": "IRIS@example.com"},
     ("invalid", "email", "duplicate_email")),
    ("teléfono de otra fila", {**good, "phones": ["+525533334444"]}, ("invalid", "phones", "duplicate_phone")),
    ("tipo desconocido", {**good, "type": "Robot"}, ("invalid", "type", "type")),
    ("GitHub inválido", {**good, "github": "-mal-"}, ("invalid", "github", "github")),
]
for label, member, expected in cases:
    check(f"validate: {label}", expected, error_of(re_.validate, member, cols, others, owner=False))
check("validate: el dueño no deja de ser Human", ("invalid", "type", "owner_type"),
      error_of(re_.validate, {**good, "type": "AI Agent"}, cols, others, owner=True))
check("validate: teléfono sin columna Phone", ("invalid", "phones", "no_phone_column"),
      error_of(re_.validate, good, ["Name", "Email", "Type"], [], owner=False))
check("validate: GitHub sin columna GitHub", ("invalid", "github", "no_github_column"),
      error_of(re_.validate, {**good, "phones": [], "github": "ana"}, ["Name", "Email", "Type"], [], owner=False))

# --- alta, edición, baja (texto) -------------------------------------------------
new_text, row, _ = re_.save_text(ROSTER, None, good)
cols2, rows2 = re_.members(new_text)
check("alta: va al final de la tabla, fila 4", (4, "Ana Ruiz"), (row, rows2[3]["name"]))
check("alta: los notificadores siguen igual", True, "| notifications@github.com | X-GitHub-Sender | GitHub |" in new_text)
check("alta: la columna desconocida queda vacía", True, "| Ana Ruiz | ana@example.com | Human |  | +525511113333 |  |" in new_text)
edited, row, _ = re_.save_text(ROSTER, 2, {"name": "Iris C.", "email": "iris@example.com", "type": "AI Agent",
                                           "github": "irisclaudetob", "phones": []})
check("edición: cambia la fila 2", "Iris C.", re_.members(edited)[1][1]["name"])
check("edición: conserva la columna que la app no ve", True, "| Iris C. | iris@example.com | AI Agent | irisclaudetob |  | agente |" in edited)
check("edición: la fila puede conservar su propio correo", 3, len(re_.members(edited)[1]))
check("edición: fila fuera de la tabla", ("not_found", "row", ""), error_of(re_.save_text, ROSTER, 9, good))
gone_text, gone = re_.delete_text(ROSTER, 3)
check("baja: quita la fila 3", (["Julián Flores", "Iris"], "Solo Tel"),
      ([m["name"] for m in re_.members(gone_text)[1]], gone["name"]))
check("baja: la fila del dueño no", ("owner_row", "row", ""), error_of(re_.delete_text, ROSTER, 1))
check("sin tabla de contactos", ("unreadable", "", ""), error_of(re_.save_text, "# nada\n", None, good))

# --- apply: bloqueo, etag, copia, relectura -------------------------------------
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
path = tmp / "roster.md"
path.write_text(ROSTER, encoding="utf-8")
etag = re_.etag_of(path.read_bytes())

done = re_.apply(path, etag, lambda t: (re_.save_text(t, None, good)[0], {}), state_dir=state, label="roster")
check("apply: escribe el alta", True, "Ana Ruiz" in path.read_text(encoding="utf-8"))
check("apply: etag nuevo es el del archivo", re_.etag_of(path.read_bytes()), done["etag"])
check("apply: etag_before es el que se leyó", etag, done["etag_before"])
backup = Path(done["backup"])
check("apply: copia fechada con el contenido de antes", (True, ROSTER),
      (backup.parent == state / "history", backup.read_text(encoding="utf-8")))
check("apply: la copia es 600", 0o600, backup.stat().st_mode & 0o777)

before = path.read_bytes()
err = None
try:
    re_.apply(path, etag, lambda t: (t, {}), state_dir=state, label="roster")
except EditError as exc:
    err = exc
check("apply: etag viejo -> conflict con el actual, sin escribir",
      ("conflict", re_.etag_of(before), before), (err.code, err.etag, path.read_bytes()))
check("apply: etag que no es texto -> missing_field", ("missing_field", "etag", ""),
      error_of(re_.apply, path, None, lambda t: (t, {}), state_dir=state, label="roster"))

# Una relectura que no cuadra se restaura byte por byte.
real = re_._signature
re_._signature = lambda text, _n=[0]: (_n.__setitem__(0, _n[0] + 1), real(text) if _n[0] == 1 else ["otra"])[1]
err = None
try:
    re_.apply(path, re_.etag_of(before), lambda t: (re_.delete_text(t, 2)[0], {}), state_dir=state, label="roster")
except EditError as exc:
    err = exc
re_._signature = real
check("apply: relectura distinta -> write_failed y restaurado", ("write_failed", before),
      (err.code if err else None, path.read_bytes()))

# Un archivo que no existe empieza desde la plantilla.
fresh = tmp / "rosters" / "ventas.md"
fresh.parent.mkdir()
no_phone = {**good, "phones": []}  # la plantilla no trae columna Phone
check("la plantilla no trae Phone: un teléfono ahí es no_phone_column", ("invalid", "phones", "no_phone_column"),
      error_of(re_.apply, fresh, "", lambda t: (re_.save_text(t, None, good)[0], {}), state_dir=state,
               label="rosters__ventas"))
check("y no se creó el archivo", False, fresh.exists())
done = re_.apply(fresh, "", lambda t: (re_.save_text(t, None, no_phone)[0], {}), state_dir=state,
                 label="rosters__ventas")
check("apply: crea desde roster.md.example, sin copia", (True, ""),
      ("Ana Ruiz" in fresh.read_text(encoding="utf-8"), done["backup"]))
check("apply: el archivo creado se lee con la plantilla", ["Ana Ruiz"],
      [m["name"] for m in re_.members(fresh.read_text(encoding="utf-8"))[1]])

# El bloqueo: un segundo escritor espera al primero.
order = []
release = threading.Event()


def holder():
    with re_.locked(path, state):
        order.append("primero")
        release.wait(2)
        order.append("suelta")


t = threading.Thread(target=holder)
t.start()
time.sleep(0.1)
threading.Timer(0.3, release.set).start()
with re_.locked(path, state):
    order.append("segundo")
t.join()
check("locked: el segundo entra cuando el primero suelta", ["primero", "suelta", "segundo"], order)
check("locked: el archivo de bloqueo está en state/locks y no junto al roster",
      (True, False), (re_.lock_path(path, state).parent == state / "locks", (tmp / ".roster.md.lock").exists()))
err = None
with re_.locked(path, state):
    def late():
        global err
        try:
            with re_.locked(path, state, timeout_s=0.2):
                pass
        except TimeoutError as exc:
            err = exc
    t = threading.Thread(target=late)
    t.start()
    t.join()
check("locked: sin el bloqueo a tiempo, TimeoutError", True, isinstance(err, TimeoutError))

# --- roster_cli usa el mismo bloqueo y no pisa un cambio de la app ---------------
os.environ["PAYNANI_STATE"] = str(state)
cli_path = tmp / "cli-roster.md"
cli_path.write_text(ROSTER, encoding="utf-8")
base = cli_path.read_text(encoding="utf-8")
ok, computed = roster_cli.roster_mod.add_contact(base, "Beto", "beto@example.com", type_="Human")
# La app escribe entre la lectura de `paynani roster add` y su escritura.
re_.apply(cli_path, re_.etag_of(cli_path.read_bytes()), lambda t: (re_.save_text(t, None, good)[0], {}),
          state_dir=state, label="cli")
expected = roster_cli.roster_mod._addresses_from_text(computed)
status, _ = roster_cli._apply_change_core(cli_path, computed, expected, run_tests=False, base=base)
check("roster_cli: el roster cambió desde la app -> conflict, y el cambio de la app se queda",
      ("conflict", True, False), (status, "Ana Ruiz" in cli_path.read_text(encoding="utf-8"),
                                  "Beto" in cli_path.read_text(encoding="utf-8")))
base = cli_path.read_text(encoding="utf-8")
ok, computed = roster_cli.roster_mod.add_contact(base, "Beto", "beto@example.com", type_="Human")
status, _ = roster_cli._apply_change_core(cli_path, computed, roster_cli.roster_mod._addresses_from_text(computed),
                                          run_tests=False, base=base)
check("roster_cli: sin cambio en medio, escribe", ("ok", True), (status, "Beto" in cli_path.read_text(encoding="utf-8")))
held = []
with re_.locked(cli_path, state):
    def cli_write():
        b = cli_path.read_text(encoding="utf-8")
        _, c = roster_cli.roster_mod.add_contact(b, "Caro", "caro@example.com", type_="Human")
        held.append(roster_cli._apply_change_core(cli_path, c, roster_cli.roster_mod._addresses_from_text(c),
                                                  run_tests=False, base=b)[0])
    t = threading.Thread(target=cli_write)
    t.start()
    time.sleep(0.3)
    check("roster_cli: espera mientras la app tiene el bloqueo", [], held)
t.join()
check("roster_cli: escribe cuando la app suelta", ["ok"], held)
check("roster_cli: sin `base`, como antes (no compara)", "ok",
      roster_cli._apply_change_core(cli_path, cli_path.read_text(encoding="utf-8"),
                                    roster_cli.roster_mod.roster_addresses(cli_path), run_tests=False)[0])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
