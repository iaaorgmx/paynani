#!/usr/bin/env python3
"""
Tests for the agent's instructions per contact on the gateway side (R3 de #410,
SMS_GATEWAY.md §11): `rules.get`, `rules.preview`, `rules.save`,
`rules.get_default` and `rules.save_default` over the paired phone's WebSocket,
the `Rules` column, the dated copy, the effective rule, the flags in
`roster.list` and what happens to a removed contact's rules. An assertion script,
like the rest of this suite.

Levanta la pasarela en un puerto libre de 127.0.0.1 con un estado temporal y hace
de app, como test_sms_roster.py. Nada sale de la máquina.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import roster_edit  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import websocket as wsm  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """# roster de prueba

# 1. Approved contacts

| Name | Email | Type | Phone |
|---|---|---|---|
| Julián Flores | julian@example.com | Human | +525511112222 |
| Ana Ruiz | ana@example.com | Human | +525511113333 |
"""

ANA_RULES = """---
version: 1
enabled: true
reply:
  sms: never
updated_by: alguien que no es la pasarela
---

## General
Sus correos son pedidos: créale la orden y no le contestes.

## SMS
Un SMS suyo es sólo un aviso.
"""

DEFAULT = """---
version: 1
enabled: true
---

## General
Contesta en el idioma del mensaje.

## Correo
Firma como el agente.
"""


def qid() -> str:
    return "q_" + secrets.token_hex(16)


async def http(port, method, path, body=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    data = json.dumps(body).encode() if body is not None else b""
    head = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", f"Content-Length: {len(data)}"]
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + data)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    payload = raw.split(b"\r\n\r\n", 1)[1]
    return int(raw.split(b" ", 2)[1]), (json.loads(payload) if payload else {})


async def recv_until(ws, kind, timeout=5):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg.get("type") == kind:
            return msg


async def ask(ws, msg):
    await ws.send_text(json.dumps(msg))
    while True:
        reply = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if reply.get("type") in ("result", "error") and reply.get("ref") == msg.get("id"):
            return reply


async def main():
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER, encoding="utf-8")
    journal = state / "events.jsonl"
    mails = []
    service = roster_api.RosterService(roster, state, agent_email="agente@example.com", rules_root=tmp,
                                       notifier=lambda to, subject, body: mails.append((to, subject, body)))
    g = gw.Gateway(state, journal, roster, roster_service=service)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    st = store_mod.Store(state)
    _, body = await http(port, "POST", "/sms/pair", {"code": st.new_code(), "device": {"model": "Pixel 6"},
                                                     "sims": [{"slot": 0, "number": None, "country": "MX"}]})
    token, device_id = body["token"], body["device_id"]
    ws, _ = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {token}"},
                              protocol="paynani-sms.v1")
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": device_id, "app_version": "1.0",
                                   "sims": [{"slot": 0, "number": None}]}))
    welcome = await recv_until(ws, "welcome")
    check("welcome anuncia los cinco rules.*", True,
          all(t in welcome["accepts"] for t in ("rules.get", "rules.preview", "rules.save", "rules.get_default",
                                                "rules.save_default")))
    rules_dir = tmp / "rules"

    listing = (await ask(ws, {"type": "roster.list", "id": qid(), "account": None}))["data"]
    retag = listing["etag"]
    check("sin reglas: has_rules false y default_rules false", ([False, False], False),
          ([m["has_rules"] for m in listing["members"]], listing["default_rules"]))

    # --- leer sin archivo ---
    r = await ask(ws, {"type": "rules.get", "id": qid(), "account": None, "row": 2, "roster_etag": retag})
    check("rules.get sin archivo: exists false, text y etag vacíos, con la fila", (False, "", "", 2, "Ana Ruiz"),
          (r["data"]["exists"], r["data"]["text"], r["data"]["etag"], r["data"]["row"], r["data"]["name"]))
    check("rules.get sin archivo ni default: effective vacío", "", r["data"]["effective"])
    r = await ask(ws, {"type": "rules.get", "id": qid(), "account": None, "row": 2, "roster_etag": "0" * 64})
    check("rules.get con roster_etag viejo -> conflict con el actual", ("conflict", retag), (r.get("code"), r.get("etag")))
    r = await ask(ws, {"type": "rules.get", "id": qid(), "account": None, "row": 9, "roster_etag": retag})
    check("rules.get de una fila que no existe -> not_found", ("not_found", "row"), (r.get("code"), r.get("field")))

    # --- vista previa ---
    r = await ask(ws, {"type": "rules.preview", "id": qid(), "account": None, "row": 2, "roster_etag": retag,
                       "text": ANA_RULES})
    check("rules.preview: effective sin guardar nada", (True, False),
          ("créale la orden" in r["data"]["effective"], rules_dir.exists()))
    r = await ask(ws, {"type": "rules.preview", "id": qid(), "account": None, "row": 2, "roster_etag": retag,
                       "text": "## sin cabecera\n"})
    check("rules.preview inválido -> el mismo invalid que rules.save", ("invalid", "header", "header_missing"),
          (r.get("code"), r.get("field"), r.get("reason")))

    # --- guardar por primera vez ---
    save = {"type": "rules.save", "id": qid(), "account": None, "row": 2, "etag": "", "roster_etag": retag,
            "text": ANA_RULES}
    r = await ask(ws, save)
    data = r.get("data") or {}
    rid = data.get("rules", "")
    rfile = rules_dir / f"{rid}.md"
    check("rules.save: id nuevo con el nombre", True, rid.startswith("ana-ruiz-") and rfile.exists())
    check("rules.save: la columna Rules en roster.md, con el id en la fila de Ana", (True, rid),
          ("| Rules |" in roster.read_text(encoding="utf-8"),
           roster_edit.members(roster.read_text(encoding="utf-8"))[1][1]["rules"]))
    check("rules.save: roster_etag nuevo", roster_edit.etag_of(roster.read_bytes()), data.get("roster_etag"))
    written = rfile.read_text(encoding="utf-8")
    check("rules.save: updated_by es el teléfono, no lo que mandó la app", (True, False),
          (f"updated_by: phone {device_id}" in written, "alguien" in written))
    check("rules.save: etag es el del archivo", roster_edit.etag_of(rfile.read_bytes()), data.get("etag"))
    check("rules.save: el archivo es 600 y la carpeta 700", (0o600, 0o700),
          (rfile.stat().st_mode & 0o777, rules_dir.stat().st_mode & 0o777))
    check("rules.save: effective en la respuesta", True, "Un SMS suyo es sólo un aviso." in data.get("effective", ""))
    log = [json.loads(line) for line in (state / roster_api.CHANGES_LOG).read_text(encoding="utf-8").splitlines()
           if '"action"' in line]
    check("log: el cambio de reglas, con el resumen y sin el texto", ("rules", f"rules/{rid}.md", {"sms": "never"}, False),
          (log[-1]["action"], log[-1]["rules"]["file"], log[-1]["rules"]["reply"], "créale" in json.dumps(log)))
    for thread in service.notify_threads:
        thread.join(5)
    check("correo al dueño: qué archivo y su política, sin el texto", (True, True, False),
          (rid in mails[-1][2], "sms: never" in mails[-1][2], "créale" in mails[-1][2]))

    # --- otra vez ---
    retag = data["roster_etag"]
    stale = await ask(ws, {**save, "id": qid(), "roster_etag": retag, "etag": ""})
    check("rules.save con el etag viejo del archivo -> conflict", ("conflict", data["etag"]),
          (stale.get("code"), stale.get("etag")))
    edited = ANA_RULES.replace("enabled: true", "enabled: false")
    r = await ask(ws, {**save, "id": qid(), "roster_etag": retag, "etag": data["etag"], "text": edited})
    history = sorted((state / "history").glob(f"rules__{rid}.*.md"))
    check("la segunda vez: mismo id, sin otra columna, y copia fechada de la anterior", (rid, 1, 1, written),
          (r["data"]["rules"], roster.read_text(encoding="utf-8").count("Rules"), len(history),
           history[0].read_text(encoding="utf-8") if history else None))
    listing = (await ask(ws, {"type": "roster.list", "id": qid(), "account": None}))["data"]
    check("roster.list: has_rules true y rules_enabled false (enabled: false)", (True, False, rid),
          (listing["members"][1]["has_rules"], listing["members"][1]["rules_enabled"], listing["members"][1]["rules"]))
    big = await ask(ws, {**save, "id": qid(), "roster_etag": retag, "etag": r["data"]["etag"],
                         "text": ANA_RULES + "x" * (32 * 1024)})
    check("más de 32 KB -> invalid too_large", ("invalid", "text", "too_large"),
          (big.get("code"), big.get("field"), big.get("reason")))

    # --- reglas generales ---
    r = await ask(ws, {"type": "rules.get_default", "id": qid()})
    check("rules.get_default sin archivo", (False, "", "default"), (r["data"]["exists"], r["data"]["etag"], r["data"]["rules"]))
    r = await ask(ws, {"type": "rules.save_default", "id": qid(), "etag": "", "text": DEFAULT})
    check("rules.save_default crea rules/default.md", (True, True), (r.get("ok"), (rules_dir / "default.md").exists()))
    listing = (await ask(ws, {"type": "roster.list", "id": qid(), "account": None}))["data"]
    check("roster.list: default_rules true", True, listing["default_rules"])
    r = await ask(ws, {"type": "rules.get", "id": qid(), "account": None, "row": 2, "roster_etag": listing["etag"]})
    check("Ana apagada: effective es default.md solo", (True, False),
          ("idioma del mensaje" in r["data"]["effective"], "créale" in r["data"]["effective"]))
    r = await ask(ws, {"type": "rules.preview", "id": qid(), "account": None, "row": 2, "roster_etag": listing["etag"],
                       "text": ANA_RULES})
    eff = r["data"]["effective"]
    check("preview con Ana activa: su General sustituye, la Correo general sigue, su SMS al final", (True, False, True, True),
          ("créale" in eff, "idioma del mensaje" in eff, "Firma como el agente." in eff,
           eff.rstrip().endswith("Un SMS suyo es sólo un aviso.")))

    # --- baja de un contacto con reglas ---
    r = await ask(ws, {"type": "roster.delete", "id": qid(), "account": None, "etag": listing["etag"], "row": 2})
    removed = list(rules_dir.glob(f"{rid}.removed-*.md"))
    check("la baja renombra sus reglas, no las borra", (True, False, 1), (r.get("ok"), rfile.exists(), len(removed)))
    check("default.md sigue", True, (rules_dir / "default.md").exists())

    # --- dos filas con el mismo Rules (edición a mano) ---
    text = roster.read_text(encoding="utf-8")
    text = text.rstrip("\n") + f"\n| Beto | beto@example.com | Human |  | compartido-0000 |\n" \
                               f"| Caro | caro@example.com | Human |  | compartido-0000 |\n"
    roster.write_text(text, encoding="utf-8")
    shared = rules_dir / "compartido-0000.md"
    shared.write_text(DEFAULT, encoding="utf-8")
    listing = (await ask(ws, {"type": "roster.list", "id": qid(), "account": None}))["data"]
    r = await ask(ws, {"type": "roster.delete", "id": qid(), "account": None, "etag": listing["etag"], "row": 2})
    check("si otra fila tiene el mismo Rules, el archivo se queda", (True, True), (r.get("ok"), shared.exists()))

    lines = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
    check("nada de esto entra a events.jsonl", [], lines)

    await ws.close()
    server.close()
    await g.shutdown()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
