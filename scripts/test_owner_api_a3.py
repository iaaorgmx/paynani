#!/usr/bin/env python3
"""
A3 #721 (PaynaniWebMT#2 FR-A7, FR-A10): las acciones de la API del dueño para correo, roster,
Dashboard, API Tokens y Agente.

Todo corre contra un clon falso en un directorio temporal: el mailer, el updater de la cuenta
principal, el Dashboard y las cuentas son los de prueba (`mail_compose.Fake`,
`account_config.Fake`, `dashboard.Fake` y un `account_ops` que sólo anota). Nada lee ni
escribe la configuración real; al final se revisa con sha256.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import accounts_cli  # noqa: E402
from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.web import (account_config, api_actions, api_tokens, app, dashboard, mail, mail_compose, notify,  # noqa: E402
                             owner_clients, users)

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


REAL = [ROOT / ".env", Path.home() / ".config/himalaya/config.toml", Path.home() / ".claude/workspace/.env"]
BEFORE = [sha(p) for p in REAL]

MAILBOX_SECRET = "buzon-" + "x" * 12
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
(state / "sms").mkdir(parents=True)
roster = tmp / "roster.md"
roster.write_text("| Name | Email | Type | GitHub | Phone |\n|---|---|---|---|---|\n| Ana | ana@example.com | Human |  |  |\n",
                  encoding="utf-8")
accounts_file = tmp / "accounts.json"
accounts_file.write_text(json.dumps({"accounts": [{
    "id": "ventas", "email": "ventas@example.com", "imap": {"host": "imap.example.com", "port": 993},
    "smtp": {"host": "smtp.example.com", "port": 465}, "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD"}]}),
    encoding="utf-8")
env_path = tmp / ".env"
env_path.write_text(
    "AGENT_EMAIL_ACCOUNT=agente@example.com\n"
    f"AGENT_EMAIL_PASSWORD={MAILBOX_SECRET}\n"
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com\nAGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993\n"
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=smtp.example.com\nAGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465\n"
    "AGENT_EMAIL_FROM_NAME=Agente\n", encoding="utf-8")
user_file = tmp / "web" / "user.json"
users.create("owner@example.com", "Owner", "una-contraseña-larga", user_file)
store = owner_clients.clients_path(user_file)
_, (token, client) = owner_clients.pair(owner_clients.new_code(path=store), "MT de Julian", app_name="PaynaniWebMT",
                                        app_version="0.1.0", path=store)
agent_token, _ = api_tokens.create("agente", permissions=["read"], path=api_tokens.path_for(user_file))


class FakeOps:
    """accounts_cli de prueba: sólo anota (como en test_web_api_a3.py)."""

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


owner_mail = []
mailer = mail_compose.Fake(book={"main": ["ana@example.com"]})
updater = account_config.Fake()
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda to, s, b: owner_mail.append((to, s, b)),
                                                      log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=accounts_file, ledger_path=state / "events.jsonl",
                  env_path=env_path, state_dir=state, roster_path=roster, mailer=mailer, updater=updater,
                  dashboard_source=dashboard.Fake(), roster_notifier=lambda *a: None)
ops = FakeOps()
ctx.account_ops = ops
ctx.probe_imap = lambda host, port, user, pw: {"ok": True, "steps": [{"ok": True, "text": "imap"}]}
ctx.probe_smtp = lambda host, port, user, pw: {"ok": True, "steps": [{"ok": True, "text": "smtp"}]}
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def api(action, tok=None, path="/api/owner", **params):
    headers = {"Host": "agente.ngrok.app", "X-Forwarded-For": "198.51.100.7", "Content-Type": "application/json",
               "Authorization": "Bearer " + (tok or token)}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", path, body=json.dumps({"action": action, **params}).encode(), headers=headers)
    r = conn.getresponse()
    data = json.loads(r.read())
    conn.close()
    return r.status, data


def sensitive_count() -> int:
    """Cuántas llamadas quedaron como owner_sensitive (la bitácora no guarda el nombre de la acción)."""
    return sum(1 for line in (state / "api_security.jsonl").read_text(encoding="utf-8").splitlines()
               if json.loads(line).get("kind") == "owner_sensitive")


# --- Correo -----------------------------------------------------------------------------------
status, body = api("ListAccounts")
check("ListAccounts: la del agente y la adicional", (200, ["main", "ventas"]), (status, [a["id"] for a in body["accounts"]]))
check("…con el nombre con que escribe cada una y si tiene firma (las pantallas de correo)",
      [("Agente", False), ("", False)], [(a.get("from_name"), a.get("signed")) for a in body["accounts"]])
signature = tmp / "firma.txt"
signature.write_text("Agente\n", encoding="utf-8")
env_before = env_path.read_text(encoding="utf-8")
env_path.write_text(env_before + f"PAYNANI_SIGNATURE_FILE={signature}\n", encoding="utf-8")
check("…una cuenta con firma dice signed", True, api("ListAccounts")[1]["accounts"][0]["signed"])
env_path.write_text(env_before, encoding="utf-8")
status, body = api("ListMail", account="main")
check("ListMail: 200 con la lista paginada", (200, "main", 0), (status, body["account"], body["offset"]))
status, body = api("ListMail", account="nada")
check("ListMail con una cuenta que no existe: 404", (404, "not_found"), (status, body["code"]))
status, body = api("GetMailThread", account="main")
check("GetMailThread sin event_id ni message_id: 400", (400, "missing_parameter"), (status, body["code"]))


def unreadable_thread():
    """GetMailThread de un recibido cuyo buzón no abre: el registro y el buzón, de mentira."""
    row = {"kind": "in", "event_id": "imap:INBOX:1:5", "at": "2026-10-21T18:25:00Z", "sender_name": "Ana",
           "sender_address": "ana@example.com", "subject": "Hola", "observed_at": "2026-10-21T18:25:00Z",
           "message_id": "<m5@example.com>", "in_reply_to": "", "references": ""}
    real_rows, real_env = api_actions._mail_rows, mail.env_for

    def no_mailbox(*args, **kwargs):
        raise mail.MailError("connect", "imap.example.com: timed out")
    api_actions._mail_rows, mail.env_for = (lambda call, account_id: [row]), no_mailbox
    try:
        return api("GetMailThread", account="main", event_id="imap:INBOX:1:5")
    finally:
        api_actions._mail_rows, mail.env_for = real_rows, real_env


status, body = unreadable_thread()
check("GetMailThread de un correo que no se pudo leer: el código y el detalle sin secretos",
      (200, "connect", "imap.example.com: timed out", True),
      (status, body["messages"][0].get("error"), body["messages"][0].get("error_detail"), body["messages"][0]["selected"]))

before_sensitive = sensitive_count()
status, body = api("SendOwnerMail", account="main", to="ana@example.com", subject="Hola", text="Qué tal")
check("SendOwnerMail a alguien del roster: sale", (200, True, []), (status, body["sent"], body["outside_roster"]))
check("…con un permiso de N1 ligado a la cuenta, por el cliente web, sin «fuera del roster»",
      ("main", True, False), (mailer.sent[-1]["account_id"], mailer.sent[-1]["by"].startswith("owner:" + client["client_id"]),
                              mailer.sent[-1]["allow_outside"]))
sent_before = len(mailer.sent)
status, body = api("SendOwnerMail", account="main", to="ana@example.com, beto@example.com", subject="Hola", text="x")
check("SendOwnerMail con alguien fuera del roster y sin confirmar: 409 outside_roster con la lista, sin mandar",
      (409, "outside_roster", ["beto@example.com"], sent_before), (status, body["code"], body["outside"], len(mailer.sent)))
status, body = api("SendOwnerMail", account="main", to="ana@example.com, beto@example.com", subject="Hola", text="x",
                   confirm_outside=True)
check("…con confirm_outside: sale, y el permiso dice allow_outside", (200, ["beto@example.com"], True),
      (status, body["outside_roster"], mailer.sent[-1]["allow_outside"]))
status, body = api("SendOwnerMail", account="main", to="no-es-correo", subject="Hola", text="x")
check("SendOwnerMail con una dirección inválida: 400 con el código de mail_compose y su detalle aparte", (400, True, True),
      (status, body["code"] != "internal_error", "detail" in body))
status, body = api("SendOwnerMail", account="main", to="ana@example.com", subject="x", text="x", confirm_outside="sí")
check("confirm_outside que no es booleano: invalid_parameter", (400, "confirm_outside"), (status, body.get("field")))
check("cada SendOwnerMail queda en la bitácora como owner_sensitive", 5, sensitive_count() - before_sensitive)

status, body = api("AddAccount", id="soporte", email="soporte@example.com", imap_host="mail.example.com",
                   smtp_host="mail.example.com", password="secreta")
check("AddAccount: probó, guardó y prendió el listener", (200, [("add", "soporte", "secreta"), ("enable", "soporte")]),
      (status, ops.calls[:2]))
check("…el aviso al dueño dice «desde PaynaniWebMT (MT de Julian)», no un API Token", (True, False),
      (any("desde PaynaniWebMT (MT de Julian)" in b for _, _, b in owner_mail), any("API token" in b for _, _, b in owner_mail)))
check("…y la contraseña no vuelve en la respuesta", False, "secreta" in json.dumps(body))
status, body = api("RemoveAccount", account="main")
check("RemoveAccount de la cuenta del agente: 403 agent_account", (403, "agent_account"), (status, body["code"]))
status, body = api("RemoveAccount", account="ventas")
check("RemoveAccount de una adicional: sale", (200, "ventas", ("remove", "ventas")), (status, body["removed"], ops.calls[-1]))

# --- Configuración de la cuenta principal ---------------------------------------------------
status, body = api("GetMainAccountConfig")
check("GetMainAccountConfig: los datos y su rev, sin la contraseña del buzón", (200, "agente@example.com", False, True),
      (status, body["config"].get("AGENT_EMAIL_ACCOUNT"), MAILBOX_SECRET in json.dumps(body), bool(body["rev"])))
rev = body["rev"]
status, body = api("SaveMainAccountConfig", rev="viejo", AGENT_EMAIL_FROM_NAME="Otro")
check("SaveMainAccountConfig con un rev viejo: 409 stale, sin llamar al núcleo", (409, "stale", 0),
      (status, body["code"], len(updater.calls)))
status, body = api("SaveMainAccountConfig", rev=rev)
check("SaveMainAccountConfig sin cambios: nada que guardar", (200, [], 0), (status, body["changed"], len(updater.calls)))
owner_mail.clear()
status, body = api("SaveMainAccountConfig", rev=rev, AGENT_EMAIL_FROM_NAME="Agente Nuevo")
check("SaveMainAccountConfig: el núcleo recibe sólo el cambio, por el cliente web", (200, {"AGENT_EMAIL_FROM_NAME": "Agente Nuevo"}, True),
      (status, updater.calls[-1][0], updater.calls[-1][1].startswith("owner:" + client["client_id"])))
check("…y el correo al dueño dice de qué app vino", True, any("desde PaynaniWebMT" in b for _, _, b in owner_mail))
check("el .env de la prueba no cambió (lo cambia el núcleo, que aquí es falso)", True,
      "AGENT_EMAIL_FROM_NAME=Agente\n" in env_path.read_text(encoding="utf-8"))

# --- Roster, reglas y Catch-All ----------------------------------------------------------------
status, body = api("ListRoster")
check("ListRoster: los contactos", (200, ["Ana"]), (status, [m["name"] for m in body["members"]]))
etag = body.get("etag", "")
status, body = api("SaveRosterContact", name="Beto", email="beto@example.com", type="Human", etag=etag)
check("SaveRosterContact: alta, sin permiso roster.write (el dueño puede todo)", (200, "success"), (status, body["result"]))
status, body = api("ListRoster")
beto = next(m for m in body["members"] if m["name"] == "Beto")
etag = body.get("etag", "")
status, body = api("GetRules", row=beto["row"], roster_etag=etag)
check("GetRules de Beto: 200", 200, status)
status, body = api("PreviewRules", general=True, text="---\nversion: 1\nenabled: true\n---\n\n## General\n\nSé breve.\n")
check("PreviewRules de las generales: el texto efectivo", (200, True), (status, "Sé breve." in body.get("effective", "")))
status, body = api("PreviewRules", general=True, text="---\nversion: 1\nenabled: quizá\n---\n")
check("PreviewRules con un encabezado inválido: 400, no 500", (400, True), (status, body["code"] != "internal_error"))
status, body = api("PreviewRules", row=beto["row"], roster_etag=etag,
                   text="---\nversion: 1\nenabled: true\n---\n\n## General\n\nSólo Beto.\n")
check("PreviewRules de un contacto: 200 con su texto", (200, True), (status, "Sólo Beto." in body.get("effective", "")))


def beto_now():
    listing = api("ListRoster")[1]
    return next(m for m in listing["members"] if m["name"] == "Beto"), listing.get("etag", "")


# La columna Telegram del formulario (PRD #609 FR-13), como en PaynaniWeb.
contact = dict(name="Beto", email="beto@example.com", type="Human")
status, body = api("SaveRosterContact", row=beto["row"], telegram="@beto_tg", etag=etag, **contact)
row, etag = beto_now()
check("SaveRosterContact con telegram: guarda el @usuario", (200, "@beto_tg"), (status, row.get("telegram")))
status, body = api("SaveRosterContact", row=row["row"], etag=etag, **contact)
row, etag = beto_now()
check("…sin telegram en el pedido, la fila conserva el suyo", (200, "@beto_tg"), (status, row.get("telegram")))
# Iris[Q54] = A: una app del dueño ve y escribe el id numérico, como PaynaniWeb (FR-15).
status, body = api("SaveRosterContact", row=row["row"], telegram="123456789", etag=etag, **contact)
row, etag = beto_now()
check("…un id numérico se guarda, como desde PaynaniWeb", (200, "123456789"), (status, row.get("telegram")))
check("…y ListRoster trae la columna tal cual, no has_telegram", (False, False), ("has_telegram" in row, "telegram_username" in row))
status, body = api("SaveRosterContact", row=row["row"], telegram="no es un telegram", etag=etag, **contact)
check("…un valor que no es @usuario ni id: 400 con el campo", (400, "telegram"), (status, body.get("field")))
check("…y la fila no cambió", "123456789", beto_now()[0].get("telegram"))
status, body = api("SaveRosterContact", row=row["row"], telegram=["x"], etag=etag, **contact)
check("…telegram que no es texto: invalid_parameter", (400, "telegram"), (status, body.get("field")))
status, body = api("SaveRosterContact", row=row["row"], telegram="", etag=beto_now()[1], **contact)
check("…vacío lo borra, también un id", (200, ""), (status, beto_now()[0].get("telegram")))
changes = [json.loads(line) for line in (state / roster_api.CHANGES_LOG).read_text(encoding="utf-8").splitlines() if line.strip()]
devices = {c["device_id"].split(":")[0] for c in changes if c.get("device_id")}
check("el registro de cambios del roster dice que fue una app del dueño, no un token de agente", {"owner"}, devices)
check("…con el id de la app emparejada", True, all(c["device_id"].split(":")[1].startswith("w_") for c in changes if c.get("device_id")))
check("who_changed de una app del dueño", "owner app w_abc123", roster_api.who_changed("owner:w_abc123:203.0.113.9"))
check("sees_telegram_id: PaynaniWeb y la app del dueño sí; la API de agentes y el teléfono no", (True, True, False, False),
      tuple(roster_api.sees_telegram_id(d) for d in ("web:1.2.3.4", "owner:w_1:1.2.3.4", "api:pn_abc:1.2.3.4", "dev_123")))
status, body = api("GetCatchAll", channel="whatsapp")
check("GetCatchAll de WhatsApp: 200", 200, status)
status, body = api("SaveCatchAll", channel="whatsapp", enabled=False, text="Avísame.", etag=body.get("etag", ""))
check("SaveCatchAll de WhatsApp sin el permiso por canal del token de agente", (200, "success"), (status, body["result"]))
status, body = api("SaveCatchAll", channel="fax", enabled=False, text="x")
check("SaveCatchAll con un canal que no existe: invalid_parameter", (400, "channel"), (status, body.get("field")))

# --- Dashboard y Agente ----------------------------------------------------------------------
status, body = api("GetDashboard")
check("GetDashboard: el modelo y los números de dashboard.json", (200, True, True),
      (status, isinstance(body["dashboard"], dict), isinstance(body["numbers"], dict)))
status, body = api("GetAgent")
check("GetAgent: la página del agente", (200, True), (status, isinstance(body["agent"], dict) and bool(body["agent"])))

# --- API Tokens ------------------------------------------------------------------------------
tokens_sensitive = sensitive_count()
status, body = api("CreateApiToken", name="Plantako", expiry="7d", permissions=["read", "sms.send"],
                   sms_per_hour="10", sms_per_day="50", agent_replies=True)
check("CreateApiToken: el secreto sale una vez, con un id de 64 hex", (200, True, True),
      (status, body.get("secret", "").startswith("pn_"), bool(re.fullmatch(r"[a-f0-9]{64}", body["token"]["id"]))))
secret, tid = body["secret"], body["token"]["id"]
check("…y la respuesta no trae el campo sha256 suelto", False, "sha256" in body["token"])
check("…con estado activo", "active", body["token"]["status"])
status, body = api("CreateApiToken", name="Malo", expiry="7d", permissions=["root"], sms_per_hour="10", sms_per_day="50")
check("CreateApiToken con un permiso que no existe: 400", (400, "invalid_token_values"), (status, body["code"]))
status, body = api("CreateApiToken", name="Malo", expiry="7d", permissions="read", sms_per_hour="10", sms_per_day="50")
check("CreateApiToken con permissions que no es lista: invalid_parameter", (400, "permissions"), (status, body.get("field")))
status, body = api("ListApiTokens")
check("ListApiTokens: sin secretos ni hashes sueltos", (200, False, False, True),
      (status, secret in json.dumps(body), any("sha256" in t for t in body["tokens"]), any(t["id"] == tid for t in body["tokens"])))
status, body = api("GetApiToken", id=tid)
check("GetApiToken: con los SMS de hoy", (200, 0), (status, body["token"]["sms_today"]))
status, body = api("GetApiToken", id="nope")
check("GetApiToken con un id mal formado: invalid_parameter", (400, "id"), (status, body.get("field")))
status, body = api("SetApiTokenAgentReplies", id=tid, agent_replies=False)
check("SetApiTokenAgentReplies: cambia", (200, False), (status, body["token"]["agent_replies"]))
status, body = api("RevokeApiToken", id=tid)
check("RevokeApiToken: revocado", (200, "revoked"), (status, body["token"]["status"]))
status, body = api("RevokeApiToken", id=tid)
check("revocar otra vez: 404 (ya no está activo)", (404, "not_found"), (status, body["code"]))
check("CreateApiToken y RevokeApiToken quedan como owner_sensitive (5 llamadas)", 5, sensitive_count() - tokens_sensitive)
check("la bitácora no trae el secreto del token creado", False, secret in (state / "api_security.jsonl").read_text())

# --- Los tokens no se cruzan ---------------------------------------------------------------------
status, body = api("ListApiTokens", tok=agent_token)
check("un token de agente pn_ no llama acciones del dueño", (401, "invalid_token"), (status, body["code"]))
status, body = api("ListRoster", tok=token, path="/api/agent")
check("el token del dueño no entra a /api/agent", 401, status)

httpd.shutdown()
check("la configuración real no cambió (.env, Himalaya)", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
