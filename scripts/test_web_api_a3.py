#!/usr/bin/env python3
"""
Tests for the API's read, roster, rules and account actions (A3 #495 of PRD #491).
An assertion script, like the rest of this suite.

Un PaynaniWeb real en un puerto libre, con estado, roster y cuentas temporales.
El roster pasa por el mismo RosterService que la web y PaynaniApp; las pruebas de
IMAP/SMTP y accounts_cli se cambian por unas de prueba. Nada sale de la máquina.
"""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import accounts_cli  # noqa: E402
from paynani_lib.sms import outgoing  # noqa: E402
from paynani_lib.sms import store as sms_store  # noqa: E402
from paynani_lib.web import api_actions, api_tokens, app, notify, users  # noqa: E402

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
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
clone.mkdir()
roster = clone / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
(clone / "rosters").mkdir()
(clone / "rosters" / "ventas.md").write_text(ROSTER, encoding="utf-8")
accounts_file = clone / "accounts.json"
accounts_file.write_text(json.dumps({"schema_version": 1, "accounts": [
    {"id": "ventas", "email": "ventas@example.com", "imap": {"host": "mail.example.com", "port": 993},
     "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD", "roster": "rosters/ventas.md", "mailboxes": ["INBOX"]}]}),
    encoding="utf-8")
state = clone / "state"
state.mkdir()
ledger = state / "lifecycle.jsonl"
ledger.write_text("".join(json.dumps(r) + "\n" for r in [
    {"event_id": "imap:INBOX:1:7", "state": "observed", "at": "2026-10-24T12:00:00Z",
     "envelope": {"event_type": "email.received", "sender": {"name": "Ana", "address": "ana@example.com"},
                  "subject": "Pedido", "observed_at": "2026-10-24T12:00:00Z", "roster_match": True}},
    {"event_id": "imap:INBOX:1:7", "state": "handled", "at": "2026-10-24T12:05:00Z"},
]), encoding="utf-8")

owner_mail = []
roster_mail = []
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", "una-contraseña-larga", user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda to, s, b: owner_mail.append((to, s, b)),
                                                      log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=accounts_file, ledger_path=ledger,
                  env_path=clone / "no.env", state_dir=state, roster_path=roster,
                  roster_notifier=lambda to, subject, body: roster_mail.append((to, subject, body)))


class FakeOps:
    """accounts_cli de prueba: sólo anota."""

    def __init__(self):
        self.calls = []

    def prepare_add(self, account_id, email, imap_host, imap_port, smtp_host, smtp_port, from_name, mailboxes):
        if not account_id:
            raise accounts_cli.AccountOpError("id is required")
        entry = {"id": account_id, "email": email, "imap": {"host": imap_host, "port": int(imap_port)}}
        if smtp_host:
            entry["smtp"] = {"host": smtp_host, "port": int(smtp_port)}
        return {"entry": entry}

    def commit_add(self, prep, password):
        self.calls.append(("add", prep["entry"]["id"], password))

    def _service(self, action, account_id):
        self.calls.append((action, account_id))
        return True

    def remove_account(self, account_id):
        self.calls.append(("remove", account_id))


ops = FakeOps()
ctx.account_ops = ops
probe_ok = {"imap": True, "smtp": True}
ctx.probe_imap = lambda host, port, user, pw: {"ok": probe_ok["imap"], "steps": [{"ok": probe_ok["imap"], "text": "imap"}]}
ctx.probe_smtp = lambda host, port, user, pw: {"ok": probe_ok["smtp"], "steps": [{"ok": probe_ok["smtp"], "text": "smtp"}]}

store_path = api_tokens.path_for(user_file)
reader, _ = api_tokens.create("lector", permissions=["read"], path=store_path)
writer, _ = api_tokens.create("roster", permissions=["read", "roster.write"], path=store_path)
admin, _ = api_tokens.create("cuentas", permissions=["accounts.write"], path=store_path)
nothing, _ = api_tokens.create("nada", permissions=[], path=store_path)

httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def api(token, action, **params):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", "/api/agent", body=json.dumps({"action": action, **params}),
                 headers={"Host": "agente.ngrok.app", "X-Forwarded-For": "203.0.113.9",
                          "Authorization": "Bearer " + token, "Content-Type": "application/json"})
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


# --- Permisos (FR-5) --------------------------------------------------------------
status, body = api(nothing, "ListAccounts")
check("sin read: 403 forbidden con el permiso que falta", (403, "forbidden", "read"),
      (status, body["code"], body.get("permission")))
status, body = api(reader, "SaveRosterContact", name="X")
check("sin roster.write: forbidden", (403, "forbidden", "roster.write"), (status, body["code"], body.get("permission")))
status, body = api(reader, "AddAccount", id="x")
check("sin accounts.write: forbidden", (403, "accounts.write"), (status, body.get("permission")))
status, body = api(admin, "ListMail")
check("accounts.write no incluye read", (403, "read"), (status, body.get("permission")))
status, body = api(reader, "UpdateProfile")
check("perfil y contraseña no están en la API (FR-4): invalid_action", (400, "invalid_action"),
      (status, body["code"]))
check("toda respuesta lleva request_id", True, len(body.get("request_id", "")) == 16)

# --- Cuentas, correo y SMS --------------------------------------------------------
status, body = api(reader, "ListAccounts")
check("ListAccounts: success", (200, "success"), (status, body["result"]))
check("ListAccounts: la del agente y ventas", ["main", "ventas"], [a["id"] for a in body["accounts"]])

status, body = api(reader, "ListMail")
check("ListMail: un correo de la cuenta del agente", (200, 1), (status, body["total"]))
row = body["mail"][0]
check("ListMail: remitente, asunto y último estado", ("ana@example.com", "Pedido", "handled"),
      (row["sender_address"], row["subject"], row["state"]))
check("ListMail: sin el sobre interno", False, "envelope" in row)
check("ListMail: next_offset None", None, body["next_offset"])
status, body = api(reader, "ListMail", account="ventas")
check("ListMail de ventas: vacío", (200, 0), (status, body["total"]))
status, body = api(reader, "ListMail", account="nadie")
check("ListMail de una cuenta que no existe: 404", (404, "not_found"), (status, body["code"]))
status, body = api(reader, "ListMail", offset="-1")
check("offset negativo: invalid_parameter", (400, "invalid_parameter", "offset"), (status, body["code"], body["field"]))

status, body = api(reader, "GetMailThread")
check("GetMailThread sin id: missing_parameter", (400, "missing_parameter"), (status, body["code"]))
status, body = api(reader, "GetMailThread", event_id="imap:INBOX:1:999")
check("GetMailThread de otro id: 404", 404, status)
status, body = api(reader, "GetMailThread", event_id="imap:INBOX:1:7")
check("GetMailThread sin login de IMAP: 200 con el error por mensaje", (200, 1), (status, len(body["messages"])))
check("GetMailThread: marca el pedido y dice por qué no se leyó", (True, True),
      (body["messages"][0]["selected"], bool(body["messages"][0].get("error"))))

st = sms_store.Store(state)
outgoing.queue(st, to="+525511112222", text="Hola Julián")
status, body = api(reader, "ListSmsConversations")
check("ListSmsConversations: una conversación con su nombre del roster", (200, "+525511112222", "Julián Flores"),
      (status, body["conversations"][0]["number"], body["conversations"][0]["name"]))
status, body = api(reader, "GetSmsThread", number="+525511112222")
check("GetSmsThread: el SMS en cola", (200, "Hola Julián"), (status, body["items"][-1]["text"]))
check("GetSmsThread: sin pausa", None, body["agent_paused_until"])
status, body = api(reader, "GetSmsThread", number="+15550009999")
check("GetSmsThread de un número sin mensajes: 404", (404, "not_found"), (status, body["code"]))
status, body = api(reader, "GetSmsThread")
check("GetSmsThread sin número: missing_parameter", (400, "number"), (status, body.get("field")))

# --- Roster y reglas --------------------------------------------------------------
status, body = api(reader, "ListRoster")
check("ListRoster: los dos contactos y las cuentas", (200, 2, True),
      (status, len(body["members"]), bool(body["accounts"])))
etag = body["etag"]
status, body = api(writer, "SaveRosterContact", name="Beto", email="beto@example.com", type="Human",
                   phones="55 3333 4444", etag=etag)
check("SaveRosterContact: alta", (200, "success"), (status, body["result"]))
status, body = api(reader, "ListRoster")
beto = next((m for m in body["members"] if m["name"] == "Beto"), None)
check("el número se guardó en E.164, como en la web", True, beto is not None and "+525533334444" in beto["phones"])
check("el dueño recibió el aviso del cambio, como desde la web", True, len(roster_mail) >= 1)
status, body = api(writer, "SaveRosterContact", name="Otro", email="otro@example.com", type="Human", etag=etag)
check("SaveRosterContact con etag viejo: 409 conflict", (409, "conflict"), (status, body["code"]))
status, body = api(writer, "SaveRosterContact", name="Malo", email="malo@example.com", type="Human",
                   phones=[True], etag=body.get("etag", ""))
check("phones con un valor que no es texto se ignora, no truena", True, status in (200, 400, 409))

status, body = api(reader, "ListRoster")
etag, beto = body["etag"], next(m for m in body["members"] if m["name"] == "Beto")
status, body = api(writer, "GetRules", row=beto["row"], roster_etag=etag)
check("GetRules: success", (200, "success"), (status, body["result"]))
status, body = api(writer, "SaveRules", row=beto["row"], roster_etag=etag, etag=body.get("etag", ""),
                   text="---\nversion: 1\nenabled: true\n---\n\n## General\n\nResponde corto.\n")
check("SaveRules: success", (200, "success"), (status, body["result"]))
status, body = api(reader, "GetDefaultRules")
check("GetDefaultRules: success", (200, "success"), (status, body["result"]))
status, body = api(reader, "SaveDefaultRules", text="x")
check("SaveDefaultRules sin roster.write: forbidden", 403, status)

status, body = api(reader, "ListRoster")
etag, beto = body["etag"], next(m for m in body["members"] if m["name"] == "Beto")
status, body = api(writer, "DeleteRosterContact")
check("DeleteRosterContact sin fila: missing_parameter", (400, "row"), (status, body.get("field")))
status, body = api(writer, "DeleteRosterContact", row=beto["row"], etag=etag)
check("DeleteRosterContact: baja", (200, "success"), (status, body["result"]))
status, body = api(reader, "ListRoster")
check("Beto ya no está", False, any(m["name"] == "Beto" for m in body["members"]))

# --- Agregar y quitar cuentas -----------------------------------------------------
probe_ok["imap"] = False
status, body = api(admin, "AddAccount", id="soporte", email="soporte@example.com", imap_host="mail.example.com",
                   smtp_host="mail.example.com", password="secreta")
check("AddAccount con IMAP rechazado: probe_failed con los pasos", (400, "probe_failed", "imap"),
      (status, body["code"], body["checks"][0]["step"]))
check("no se escribió nada", [], [c for c in ops.calls if c[0] == "add"])
check("la contraseña no vuelve en la respuesta", False, "secreta" in json.dumps(body))
probe_ok["imap"] = True
status, body = api(admin, "AddAccount", id="soporte", email="soporte@example.com", imap_host="mail.example.com",
                   smtp_host="mail.example.com")
check("AddAccount sin contraseña: missing_parameter", (400, "password"), (status, body.get("field")))
status, body = api(admin, "AddAccount", id="soporte", email="soporte@example.com", imap_host="mail.example.com",
                   smtp_host="mail.example.com", password="secreta")
check("AddAccount: success, probó IMAP y SMTP y prendió el listener", (200, ["imap", "smtp"], True),
      (status, [c["step"] for c in body["checks"]], body["listener_started"]))
check("AddAccount: guardó y activó", [("add", "soporte", "secreta"), ("enable", "soporte")], ops.calls[:2])
check("AddAccount: aviso al dueño que dice que fue por la API", True,
      any("API token cuentas" in b for _, _, b in owner_mail))
status, body = api(admin, "RemoveAccount", account="main")
check("RemoveAccount de la cuenta del agente: 403 agent_account", (403, "agent_account"), (status, body["code"]))
status, body = api(admin, "RemoveAccount", account="ventas")
check("RemoveAccount: success", (200, "ventas"), (status, body["removed"]))
check("RemoveAccount: llamó a remove_account", ("remove", "ventas"), ops.calls[-1])

# --- Un error interno responde JSON -------------------------------------------------
original = api_actions.ACTIONS["ListAccounts"]
api_actions.ACTIONS["ListAccounts"] = ("read", lambda call: 1 / 0)
status, body = api(reader, "ListAccounts")
check("una excepción en la acción: 500 internal_error, sin detalles", (500, "internal_error"), (status, body["code"]))
api_actions.ACTIONS["ListAccounts"] = original

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
