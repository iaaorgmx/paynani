#!/usr/bin/env python3
"""
Tests for rules.py (R3 de #410, PRD #409 I-1 a I-6, SMS_GATEWAY.md §11): la
cabecera de un archivo de reglas, su forma canónica, las secciones, la regla
efectiva con `default.md`, la política `reply` por canal, los ids y la columna
`Rules` del roster. Una secuencia de aserciones, como el resto.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import roster_edit  # noqa: E402
from paynani_lib import rules  # noqa: E402
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


def error_of(fn, *args):
    try:
        fn(*args)
    except EditError as exc:
        return (exc.code, exc.field, exc.reason)
    return None


CONTACT = """---
version: 1
enabled: true
reply:
  sms: never
updated_at: 2026-10-20T07:00:00Z
updated_by: phone d_fb89b8
---

## General
Sus correos son pedidos de compras: créale la orden y no le contestes.

## SMS
Un SMS suyo es sólo un aviso. Nunca le escribas por SMS.
"""

DEFAULT = """---
version: 1
enabled: true
reply:
  email: normal
  sms: normal
---

Reglas para todos.

## General
Contesta en el idioma del mensaje.

## Correo
Firma como el agente.
"""

# --- cabecera -----------------------------------------------------------------
p = rules.parse(CONTACT)
check("parse: enabled y reply por canal", (True, {"email": "normal", "sms": "never"}), (p["enabled"], p["reply"]))
check("parse: reply_set dice qué canales escribió el archivo", {"sms"}, p["reply_set"])
check("parse: updated_by", "phone d_fb89b8", p["updated_by"])
head = "---\nversion: 1\nenabled: true\n"
cases = [
    ("sin cabecera", "## General\nhola\n", ("invalid", "header", "header_missing")),
    ("cabecera sin cerrar", "---\nversion: 1\n", ("invalid", "header", "header_missing")),
    ("version 2", "---\nversion: 2\nenabled: true\n---\n", ("invalid", "header.version", "value")),
    ("sin version", "---\nenabled: true\n---\n", ("invalid", "header.version", "value")),
    ("enabled yes", "---\nversion: 1\nenabled: yes\n---\n", ("invalid", "header.enabled", "value")),
    ("reply.sms maybe", head + "reply:\n  sms: maybe\n---\n", ("invalid", "header.reply.sms", "value")),
    ("reply.email quiet", head + "reply:\n  email: quiet\n---\n", ("invalid", "header.reply.email", "value")),
    ("llave desconocida", head + "permisos: todos\n---\n", ("invalid", "header", "unknown_key")),
    ("canal desconocido", head + "reply:\n  whatsapp: never\n---\n", ("invalid", "header", "unknown_key")),
    ("reply con valor en la misma línea", head + "reply: never\n---\n", ("invalid", "header.reply", "value")),
    ("llave repetida", head + "enabled: false\n---\n", ("invalid", "header.enabled", "value")),
    ("más de 32 KB", head + "---\n" + "x" * (32 * 1024), ("invalid", "text", "too_large")),
]
for label, text, expected in cases:
    check(f"parse: {label}", expected, error_of(rules.parse, text))
check("parse: 32 KB exactos caben", None, error_of(rules.parse, head + "---\n" + "x" * (32 * 1024 - len(head) - 4)))
check("parse: comentarios y comillas en la cabecera", True,
      rules.parse("---\n# nota\nversion: '1'\nenabled: \"false\"\n---\n")["enabled"] is False)

# --- forma canónica ---------------------------------------------------------------
out = rules.render(rules.parse(CONTACT.replace("updated_by: phone d_fb89b8", "updated_by: alguien")),
                   updated_at="2026-10-21T00:00:00Z", updated_by="phone d_3f9a1c")
check("render: updated_at y updated_by de la pasarela", (True, True, False),
      ("updated_at: 2026-10-21T00:00:00Z" in out, "updated_by: phone d_3f9a1c" in out, "alguien" in out))
check("render: sólo escribe el canal que el archivo escribió", (True, False), ("  sms: never" in out, "  email:" in out))
check("render: el cuerpo no cambia", rules.parse(CONTACT)["body"], rules.parse(out)["body"])
check("render: se vuelve a leer igual", (True, {"sms"}), (rules.parse(out)["enabled"], rules.parse(out)["reply_set"]))

# --- secciones y regla efectiva -----------------------------------------------------
check("sections: el preámbulo es la sección vacía", ["", "General", "Correo"],
      [name for name, _ in rules.sections(rules.parse(DEFAULT)["body"])])
check("sections: ### no abre sección", ["General"],
      [n for n, _ in rules.sections("## General\n### sub\nx\n")])
eff = rules.effective(DEFAULT, CONTACT)
check("effective: la General del contacto sustituye a la general completa", (True, False),
      ("créale la orden" in eff, "idioma del mensaje" in eff))
check("effective: la Correo de default.md sigue (el contacto no la define)", True, "Firma como el agente." in eff)
check("effective: la SMS del contacto se agrega al final", True, eff.rstrip().endswith("Nunca le escribas por SMS."))
check("effective: el preámbulo de default.md se conserva", True, eff.startswith("Reglas para todos."))
check("effective: la sección del mismo nombre sin distinguir mayúsculas", True,
      "uno" not in rules.effective(DEFAULT.replace("## Correo\nFirma como el agente.", "## correo\nuno"),
                                   CONTACT.replace("## SMS", "## CORREO")))
off = CONTACT.replace("enabled: true", "enabled: false")
check("effective: contacto con enabled: false -> default.md solo", rules.effective(DEFAULT, None),
      rules.effective(DEFAULT, off))
check("effective: default.md apagado o faltante -> sólo lo del contacto", rules.effective(None, CONTACT),
      rules.effective(DEFAULT.replace("enabled: true", "enabled: false"), CONTACT))
check("effective: los dos faltan o están apagados -> vacío", ("", ""),
      (rules.effective(None, None), rules.effective(None, off)))
check("effective: un archivo inválido no cuenta", rules.effective(DEFAULT, None),
      rules.effective(DEFAULT, "## sin cabecera\n"))

# --- reply efectivo (I-3) ------------------------------------------------------------
check("effective_reply: el canal del contacto manda; el que no escribió, el de default.md",
      {"email": "normal", "sms": "never"}, rules.effective_reply(DEFAULT, CONTACT))
check("effective_reply: default.md con email never cuenta donde el contacto no dice",
      {"email": "never", "sms": "never"},
      rules.effective_reply(DEFAULT.replace("email: normal", "email: never"), CONTACT))
check("effective_reply: contacto apagado -> el de default.md", {"email": "normal", "sms": "normal"},
      rules.effective_reply(DEFAULT, off))
check("effective_reply: sin reglas -> normal", {"email": "normal", "sms": "normal"}, rules.effective_reply(None, None))

# --- ids ------------------------------------------------------------------------------
rid = rules.new_id("Ana Ruíz Núñez", set())
check("new_id: nombre sin acentos, con guiones, más 4 hex", True,
      rid.startswith("ana-ruiz-nunez-") and len(rid.rsplit("-", 1)[1]) == 4 and bool(rules.ID_RE.match(rid)))
check("new_id: un nombre sin letras usa «contacto»", True, rules.new_id("☎☎", set()).startswith("contacto-"))
check("new_id: nunca uno ya tomado", True, all(rules.new_id("Ana", {"ana-0000"}) != "ana-0000" for _ in range(20)))
check("path_for: un id raro no sale de rules/", ("invalid", "rules", "rules_id"),
      error_of(rules.path_for, "../roster"))
check("path_for: default es rules/default.md", "default.md", rules.path_for("default", Path("/x")).name)

# --- la columna Rules del roster --------------------------------------------------------
ROSTER = """| Name | Email | Type | Phone |
|---|---|---|---|
| Julián | julian@example.com | Human | +525511112222 |
| Ana | ana@example.com | Human |  |
"""
out = roster_edit.set_rules_text(ROSTER, 2, "ana-9b1c")
cols, rows = roster_edit.members(out)
check("set_rules_text: agrega la columna Rules al final", ["Name", "Email", "Type", "Phone", "Rules"], cols)
check("set_rules_text: pone el id en esa fila y nada en las demás", [None, "ana-9b1c"], [m["rules"] for m in rows])
check("set_rules_text: las demás celdas no cambian", ["+525511112222"], rows[0]["phones"])
again = roster_edit.set_rules_text(out, 1, "julian-1a2b")
check("set_rules_text: con la columna ya puesta no la repite", (1, ["julian-1a2b", "ana-9b1c"]),
      (again.splitlines()[0].count("Rules"), [m["rules"] for m in roster_edit.members(again)[1]]))
check("set_rules_text: fila fuera de la tabla", ("not_found", "row", ""),
      error_of(roster_edit.set_rules_text, ROSTER, 7, "x-0000"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
