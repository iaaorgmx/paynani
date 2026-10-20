#!/usr/bin/env python3
"""
Tests for the «Roster» screen on the gateway side (R2 de #410, SMS_GATEWAY.md
§11): `roster.accounts`, `roster.list`, `roster.save` and `roster.delete` over the
paired phone's WebSocket, with the safe resend, `etag` conflicts, the owner's row,
the change log, the email to the human and the new `allowed`. An assertion
script, like the rest of this suite.

Levanta la pasarela en un puerto libre de 127.0.0.1 con un estado temporal y hace
de app, como test_sms_human.py. El correo al humano es una función de prueba: nada
sale de la máquina.
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

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | +525511112222 |
| Iris | iris@example.com | AI Agent | irisclaudetob |  |
"""

ACCOUNTS = {"schema_version": 1, "accounts": [
    {"id": "ventas", "email": "ventas@example.com", "imap": {"host": "mail.example.com", "port": 993},
     "smtp": {"host": "mail.example.com", "port": 465}, "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD",
     "roster": "rosters/ventas.md", "mailboxes": ["INBOX"], "enabled": True}]}


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


async def recv_until(ws, kinds, timeout=5):
    kinds = (kinds,) if isinstance(kinds, str) else kinds
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg.get("type") in kinds:
            return msg


async def ask(ws, msg):
    """Manda un pedido y espera la respuesta con su `ref`, dejando pasar lo demás."""
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
    accounts_file = tmp / "accounts.json"
    accounts_file.write_text(json.dumps(ACCOUNTS), encoding="utf-8")
    journal = state / "events.jsonl"
    mails = []
    service = roster_api.RosterService(roster, state, accounts_file=accounts_file, agent_email="agente@example.com",
                                       notifier=lambda to, subject, body: mails.append((to, subject, body)))
    g = gw.Gateway(state, journal, roster, roster_service=service)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    st = store_mod.Store(state)
    code = st.new_code()
    _, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel 6"},
                                                     "sims": [{"slot": 0, "number": None, "country": "MX"}]})
    token, device_id = body["token"], body["device_id"]
    ws, _ = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {token}"},
                              protocol="paynani-sms.v1")
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": device_id, "app_version": "1.0",
                                   "sims": [{"slot": 0, "number": None}]}))
    welcome = await recv_until(ws, "welcome")
    check("welcome anuncia los cuatro roster.*", True,
          all(t in welcome["accepts"] for t in ("roster.accounts", "roster.list", "roster.save", "roster.delete")))
    check("welcome todavía no anuncia rules.* (R3)", False, any(t.startswith("rules.") for t in welcome["accepts"]))

    # --- cuentas y lista ---
    r = await ask(ws, {"type": "roster.accounts", "id": qid()})
    accts = r["data"]["accounts"]
    check("roster.accounts: la del agente primero, con null", (None, "agente@example.com", "roster.md", 2, "ok"),
          (accts[0]["account"], accts[0]["email"], accts[0]["roster"], accts[0]["members"], accts[0]["status"]))
    check("roster.accounts: la adicional, sin archivo todavía", ("ventas", "rosters/ventas.md", "missing"),
          (accts[1]["account"], accts[1]["roster"], accts[1]["status"]))
    check("roster.accounts: nada de contraseñas", False, "password" in json.dumps(r).lower())

    r = await ask(ws, {"type": "roster.list", "id": qid(), "account": None})
    data = r["data"]
    check("roster.list: ok con columns", (True, ["Name", "Email", "Type", "GitHub", "Phone"]),
          (r["ok"], data["columns"]))
    check("roster.list: filas, dueño y has_rules", [(1, "Julián Flores", True, False), (2, "Iris", False, False)],
          [(m["row"], m["name"], m["owner"], m["has_rules"]) for m in data["members"]])
    check("roster.list: etag del archivo", roster_api.roster_edit.etag_of(roster.read_bytes()), data["etag"])
    etag = data["etag"]
    lines_before = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []

    # --- alta ---
    ana = {"name": "Ana Ruiz", "email": "ana@example.com", "type": "Human", "github": "", "phones": ["+525511113333"]}
    save = {"type": "roster.save", "id": qid(), "account": None, "etag": etag, "row": None, "member": ana}
    await ws.send_text(json.dumps(save))
    first = await recv_until(ws, ("result", "error"))
    allowed = await recv_until(ws, "allowed")
    check("roster.save alta: result con la fila 3", (True, 3), (first.get("ok"), first["data"]["row"]))
    check("roster.save alta: la lista nueva trae a Ana", "Ana Ruiz", first["data"]["members"][2]["name"])
    check("roster.save alta: etag nuevo", roster_api.roster_edit.etag_of(roster.read_bytes()), first["data"]["etag"])
    check("roster.save alta: allowed nuevo enseguida, con el número de Ana", ["+525511112222", "+525511113333"],
          allowed["allowed"])
    check("roster.md tiene la fila", True, "| Ana Ruiz | ana@example.com | Human |  | +525511113333 |" in
          roster.read_text(encoding="utf-8"))
    history = list((state / "history").glob("roster.*.md"))
    check("copia fechada del roster de antes", (1, ROSTER), (len(history), history[0].read_text(encoding="utf-8")))
    log = [json.loads(line) for line in (state / roster_api.CHANGES_LOG).read_text(encoding="utf-8").splitlines()]
    check("log de cambios: una línea con lo que pasó", ("add", device_id, None, 3, "Ana Ruiz", etag),
          (log[0]["action"], log[0]["device_id"], log[0]["account"], log[0]["row"], log[0]["name"],
           log[0]["etag_before"]))
    check("log de cambios: sin los datos del contacto", False, "ana@example.com" in json.dumps(log[0]))
    for thread in service.notify_threads:
        thread.join(5)
    check("correo al dueño (el primer Human)", "julian@example.com", mails[0][0] if mails else None)
    check("el correo dice qué cambió y desde qué teléfono", (True, True),
          (("alta" in mails[0][1]) if mails else False, (device_id in mails[0][2]) if mails else False))
    log = [json.loads(line) for line in (state / roster_api.CHANGES_LOG).read_text(encoding="utf-8").splitlines()]
    check("el aviso que salió queda en el log", ("notify", True, log[0]["change"]),
          (log[1].get("type"), log[1].get("notified"), log[1].get("for")))
    check("unnotified: nada pendiente", {"count": 0, "errors": []}, roster_api.unnotified(state))

    # --- reenvío seguro ---
    again = await ask(ws, save)
    check("mismo id y mismo pedido -> la misma respuesta, replayed", (True, 3, True),
          (again.get("ok"), again["data"]["row"], again.get("replayed")))
    check("y no se agregó otra fila", 1, roster.read_text(encoding="utf-8").count("Ana Ruiz"))
    reused = await ask(ws, {**save, "member": {**ana, "name": "Otra"}})
    check("mismo id con otro pedido -> invalid id_reused", ("invalid", "id", "id_reused"),
          (reused.get("code"), reused.get("field"), reused.get("reason")))

    # --- conflicto y validación ---
    stale = await ask(ws, {**save, "id": qid(), "member": {**ana, "email": "otra@example.com", "phones": []}})
    check("etag viejo -> conflict con el etag actual", ("conflict", roster_api.roster_edit.etag_of(roster.read_bytes())),
          (stale.get("code"), stale.get("etag")))
    etag = stale["etag"]
    bad = await ask(ws, {"type": "roster.save", "id": qid(), "account": None, "etag": etag, "row": 2,
                         "member": {"name": "Iris", "email": "iris@", "type": "AI Agent", "github": "", "phones": []}})
    check("correo inválido -> invalid email email_format", ("invalid", "email", "email_format"),
          (bad.get("code"), bad.get("field"), bad.get("reason")))
    check("y no cambió nada", etag, roster_api.roster_edit.etag_of(roster.read_bytes()))
    owner = await ask(ws, {"type": "roster.save", "id": qid(), "account": None, "etag": etag, "row": 1,
                           "member": {"name": "Julián Flores", "email": "julian@example.com", "type": "AI Agent",
                                      "github": "julianflores", "phones": ["+525511112222"]}})
    check("el dueño no deja de ser Human", ("invalid", "owner_type"), (owner.get("code"), owner.get("reason")))

    # --- edición ---
    edit = await ask(ws, {"type": "roster.save", "id": qid(), "account": None, "etag": etag, "row": 2,
                          "member": {"name": "Iris C.", "email": "iris@example.com", "type": "AI Agent",
                                     "github": "irisclaudetob", "phones": []}})
    check("edición de la fila 2", (True, 2, "Iris C."),
          (edit.get("ok"), edit["data"]["row"], edit["data"]["members"][1]["name"]))
    for thread in service.notify_threads:
        thread.join(5)
    check("el correo de la edición dice qué campo cambió", True, "Cambió: name." in mails[-1][2])
    etag = edit["data"]["etag"]

    # --- baja ---
    nope = await ask(ws, {"type": "roster.delete", "id": qid(), "account": None, "etag": etag, "row": 1})
    check("baja del dueño -> owner_row", "owner_row", nope.get("code"))
    msg = {"type": "roster.delete", "id": qid(), "account": None, "etag": etag, "row": 3}
    await ws.send_text(json.dumps(msg))
    gone = await recv_until(ws, ("result", "error"))
    allowed = await recv_until(ws, "allowed")
    check("baja de Ana", (True, ["Julián Flores", "Iris C."]),
          (gone.get("ok"), [m["name"] for m in gone["data"]["members"]]))
    check("allowed sin el número de Ana", ["+525511112222"], allowed["allowed"])
    out = await ask(ws, {"type": "roster.delete", "id": qid(), "account": None, "etag": gone["data"]["etag"], "row": 9})
    check("fila que no existe -> not_found", ("not_found", "row"), (out.get("code"), out.get("field")))

    # --- un error pasajero no se guarda para el reenvío ---
    real_locked = roster_api.roster_edit.locked
    calls = []

    def busy(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("ocupado")
        return real_locked(*args, **kwargs)

    roster_api.roster_edit.locked = busy
    cara = {"name": "Cara", "email": "cara@example.com", "type": "Human", "github": "", "phones": []}
    retry = {"type": "roster.save", "id": qid(), "account": None, "etag": gone["data"]["etag"], "row": None,
             "member": cara}
    first = await ask(ws, retry)
    second = await ask(ws, retry)
    roster_api.roster_edit.locked = real_locked
    check("bloqueo ocupado -> write_failed", "write_failed", first.get("code"))
    check("el reenvío del mismo id se vuelve a intentar y entra", (True, None), (second.get("ok"), second.get("replayed")))
    for thread in service.notify_threads:
        thread.join(5)

    # --- un aviso que no sale no queda en silencio ---
    def broken(to, subject, body):
        raise RuntimeError("send.sh no pudo")

    service.notifier = broken
    etag = second["data"]["etag"]
    r = await ask(ws, {"type": "roster.delete", "id": qid(), "account": None, "etag": etag, "row": 3})
    for thread in service.notify_threads:
        thread.join(5)
    log = [json.loads(line) for line in (state / roster_api.CHANGES_LOG).read_text(encoding="utf-8").splitlines()]
    check("el cambio se hizo aunque el correo falle", True, r.get("ok"))
    check("el aviso fallido queda en el log con la clase del error", (False, "RuntimeError"),
          (log[-1].get("notified"), log[-1].get("error")))
    pending = roster_api.unnotified(state)
    check("unnotified lo cuenta", (1, ["RuntimeError"]), (pending["count"], pending["errors"]))
    import healthcheck
    warning = healthcheck.roster_notice_warnings(pending)
    check("healthcheck lo advierte", (1, True), (len(warning), "not emailed to your human" in warning[0]))
    check("sin cambios sin aviso, healthcheck no dice nada", [],
          healthcheck.roster_notice_warnings({"count": 0, "errors": []}))
    service.notifier = lambda to, subject, body: mails.append((to, subject, body))

    # --- otra cuenta ---
    r = await ask(ws, {"type": "roster.list", "id": qid(), "account": "ventas"})
    check("lista de una cuenta sin archivo: vacía, etag vacío", ([], ""), (r["data"]["members"], r["data"]["etag"]))
    beto = {"name": "Beto", "email": "beto@example.com", "type": "Human", "github": "", "phones": []}
    r = await ask(ws, {"type": "roster.save", "id": qid(), "account": "ventas", "etag": "", "row": None,
                       "member": beto})
    ventas = tmp / "rosters" / "ventas.md"
    check("alta en la cuenta adicional crea su roster", (True, True),
          (r.get("ok"), "Beto" in ventas.read_text(encoding="utf-8") if ventas.exists() else False))
    check("y no tocó roster.md", False, "Beto" in roster.read_text(encoding="utf-8"))
    r = await ask(ws, {"type": "roster.list", "id": qid(), "account": "nadie"})
    check("cuenta que no existe -> not_found account", ("not_found", "account"), (r.get("code"), r.get("field")))

    # --- forma del pedido ---
    await ws.send_text(json.dumps({"type": "roster.list", "id": "mal"}))
    r = await recv_until(ws, "error")
    check("id que no es q_ + 32 hex -> missing_field id", ("missing_field", "id"), (r.get("code"), r.get("field")))
    lines_after = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
    check("nada de esto entra a events.jsonl", lines_before, lines_after)
    r = await ask(ws, {"type": "roster.list", "id": qid(), "account": None})
    check("la conexión sigue viva después de los errores", True, r.get("ok"))

    await ws.close()
    server.close()
    await g.shutdown()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
