#!/usr/bin/env python3
"""
A4 #722 (PaynaniWebMT#2 FR-A7, A9, A10): the owner API's text messages, WhatsApp, Telegram
and Webchat actions, end to end over HTTP with a `pw_` token. An assertion script, like the
rest of this suite. The channels are the in-memory demos (`whatsapp_source.Demo`,
`telegram_source.Demo`, `webchat_source.Fake`); nothing leaves the machine.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import store as sms_store  # noqa: E402
from paynani_lib.web import app, notify, owner_api, owner_clients, users  # noqa: E402
from paynani_lib.web import telegram_source, webchat_source, whatsapp_source  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


os.environ.pop("PAYNANI_WEB_AGENT_PAUSE_MIN", None)
os.environ["PAYNANI_WEB_SMS_PER_HOUR"] = "5"
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
(state / "sms").mkdir(parents=True)
roster = tmp / "roster.md"
ANA = "+525511112222"
roster.write_text("| Name | Email | Phone |\n|---|---|---|\n"
                  f"| Julián Flores | julian@example.com |  |\n| Ana López | ana@example.com | {ANA} |\n",
                  encoding="utf-8")
user_file = tmp / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", "una-contraseña-larga", user_file)
clients = owner_clients.clients_path(user_file)
_, (token, client) = owner_clients.pair(owner_clients.new_code(path=clients), "MT en iaa.org.mx",
                                        app_name="PaynaniWebMT", app_version="0.1.0", path=clients)
_, (token2, client2) = owner_clients.pair(owner_clients.new_code(path=clients), "Otra",
                                          app_name="PaynaniWebMT", app_version="0.1.0", path=clients)

wa = whatsapp_source.Demo(state="connected")
tg = telegram_source.Demo(state="running")
tg_root = tmp / "tg"
tg_root.mkdir()
(tg_root / "telegram.env").write_text(f"TELEGRAM_ENABLED=1\nTELEGRAM_TOKEN={tg.token}\n", encoding="utf-8")
(tg_root / "telegram.env").chmod(0o600)   # el lector de telegram.env sólo acepta 0600
(tmp / "whatsapp.env").write_text("WHATSAPP_ENABLED=1\n", encoding="utf-8")
wc = webchat_source.Fake()
mails = []
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: mails.append(a), log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "none.json", state_dir=state,
                  roster_path=roster, whatsapp_source=wa, whatsapp_root=tmp, telegram_source=tg,
                  telegram_root=tg_root, webchat_store=wc)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def _post(payload: bytes, ctype: str, tok: str | None, binary: bool):
    headers = {"Host": "agente.ngrok.app", "X-Forwarded-For": "198.51.100.7", "Content-Type": ctype,
               "Authorization": "Bearer " + (tok or token)}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", "/api/owner", body=payload, headers=headers)
    r = conn.getresponse()
    data = r.read()
    hdrs = {k.lower(): v for k, v in r.getheaders()}
    conn.close()
    if binary:
        return r.status, hdrs, data
    return r.status, json.loads(data)


def call(action: str, tok: str | None = None, binary: bool = False, **params):
    return _post(json.dumps({"action": action, **params}).encode(), "application/json", tok, binary)


def upload(action: str, fields: dict, files: list[tuple[str, bytes]]):
    boundary = "b" + uuid.uuid4().hex
    parts = []
    for k, v in {"action": action, **fields}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, data in files:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return _post(b"".join(parts), f"multipart/form-data; boundary={boundary}", None, False)


def code(r):
    return r[0], r[1].get("code") if r[0] >= 400 else r[1].get("result")


# --- registro ------------------------------------------------------------------------------
A4 = {"ListSmsConversations", "GetSmsThread", "SendOwnerSms", "GetSmsStatuses", "ListOptOuts", "SaveOptOut",
      "DeleteOptOut", "GetWhatsAppStatus", "ListWhatsAppConversations", "GetWhatsAppThread", "SendWhatsApp",
      "ReactWhatsApp", "GetWhatsAppMedia", "LinkWhatsApp", "GetWhatsAppLinkCode", "CancelWhatsAppLink",
      "UnlinkWhatsApp", "GetTelegramStatus", "ListTelegramConversations", "GetTelegramThread", "SendTelegram",
      "ReactTelegram", "GetTelegramMedia", "SetupTelegram", "CheckTelegramToken", "ApplyTelegramToken",
      "CancelTelegramToken", "GetWebchatThread", "SendWebchat", "ReactWebchat", "GetWebchatFile",
      "GetAgentTyping"}
check("las 32 acciones de FR-A7 están registradas", set(), A4 - set(owner_api.ACTIONS))
check("FR-A10: vincular, desvincular y el token de Telegram son delicadas",
      {"LinkWhatsApp", "CancelWhatsAppLink", "UnlinkWhatsApp", "SetupTelegram", "CheckTelegramToken",
       "ApplyTelegramToken"}, {n for n in A4 if owner_api.is_sensitive(n)})

# --- SMS -------------------------------------------------------------------------------------
st = sms_store.Store(state)
r = call("ListSmsConversations")
check("SMS sin teléfono: 200, phone.state no_phone", (200, "no_phone"), (r[0], r[1]["phone"]["state"]))
check("SendOwnerSms sin teléfono: 409 phone_not_ready", (409, "phone_not_ready"),
      code(call("SendOwnerSms", number=ANA, text="hola")))
st.save_device({"device_id": "d_1", "sims": [{"slot": 0, "country": "MX"}], "accepts_owner_out": True})
r = call("SendOwnerSms", number="55 1111 2222", text="hola\r\nAna", pause=True)
check("SendOwnerSms: normaliza con la región y encola", (200, ANA, "queued", True),
      (r[0], r[1].get("number"), r[1].get("status"), r[1].get("in_roster")))
check("con pause: los minutos de pausa", True, r[1].get("agent_pause_min", 0) > 0)
check("número que no sirve: invalid_number", (400, "invalid_number"),
      code(call("SendOwnerSms", number="hola", text="x")))
check("texto vacío: empty_text", (400, "empty_text"), code(call("SendOwnerSms", number=ANA, text="  ")))
r = call("GetSmsStatuses", number=ANA)
check("GetSmsStatuses: la orden de la web con su estado", (200, True),
      (r[0], any(i["id"].startswith("w_") and i["status"] for i in r[1].get("items", []))))
r = call("SaveOptOut", number="55 1111 2222")
check("SaveOptOut: baja, cambió", (200, ANA, True), (r[0], r[1].get("number"), r[1].get("changed")))
r = call("ListOptOuts")
check("ListOptOuts la trae, hecha por este cliente", (ANA, "owner:" + client["client_id"]),
      (r[1]["opt_outs"][0]["number"], r[1]["opt_outs"][0].get("by")))
check("DeleteOptOut: alta", True, call("DeleteOptOut", number=ANA)[1].get("changed"))

# --- WhatsApp ------------------------------------------------------------------------------
r = call("GetWhatsAppStatus")
check("GetWhatsAppStatus: configurado y conectado, sin vinculación", (200, True, "connected", None),
      (r[0], r[1]["configured"], r[1]["state"], r[1]["link"]))
r = call("ListWhatsAppConversations")
check("ListWhatsAppConversations: los hilos", (200, True), (r[0], len(r[1]["threads"]) > 0))
check("con by: web, nunca by: api (el dueño ve como en la web)", False,
      any(f.get("by") == "api" for _, f in wa.calls))
r = call("GetWhatsAppThread", number="+15550100001")
check("GetWhatsAppThread: el hilo", (200, "+15550100001"), (r[0], r[1].get("number")))
r = call("SendWhatsApp", number="+15550100001", text="Listo")
check("SendWhatsApp: sale", (200, True), (r[0], r[1].get("sent")))
check("SendWhatsApp sin texto ni archivos: invalid", (400, "invalid"),
      code(call("SendWhatsApp", number="+15550100001", text=" ")))
check("SendWhatsApp a alguien fuera del roster: el código del servicio", (400, "not_allowed"),
      code(call("SendWhatsApp", number="+15550100099", text="hola")))
check("ReactWhatsApp con un canal que no reacciona: 404", (404, "not_found"),
      code(call("ReactWhatsApp", ref="wo_" + "a" * 32, emoji="👍")))
check("ReactWhatsApp con emoji inválido: 400", (400, "invalid_parameter"),
      code(call("ReactWhatsApp", ref="wo_" + "a" * 32, emoji="no")))
check("GetWhatsAppMedia de un ref inventado: 404", (404, "not_found"),
      code(call("GetWhatsAppMedia", ref="wa:demo:0010")))

# vincular: desvincular primero (confirm), luego vincular con código
check("UnlinkWhatsApp sin confirm: 400", (400, "confirm_required"), code(call("UnlinkWhatsApp")))
r = call("UnlinkWhatsApp", confirm=True)
check("UnlinkWhatsApp: desvinculado, remoto", (200, True), (r[0], r[1].get("remote")))
check("LinkWhatsApp con número malo: invalid_number", (400, "invalid_number"),
      code(call("LinkWhatsApp", mode="code", number="123")))
r = call("LinkWhatsApp", mode="code", number="+1 555 010 0000")
check("LinkWhatsApp con código: el código viaja sólo aquí", (200, True), (r[0], str(r[1].get("code", "")).startswith("DEMO-")))
r = call("GetWhatsAppLinkCode")
check("GetWhatsAppLinkCode: la vinculación de este cliente", ("waiting", "code"),
      ((r[1]["link"] or {}).get("state"), (r[1]["link"] or {}).get("mode")))
check("otro cliente no ve la vinculación de éste (estado por client_id)", None,
      call("GetWhatsAppLinkCode", tok=token2)[1]["link"])
check("CancelWhatsAppLink: cancelada", (200, True), (lambda x: (x[0], x[1].get("canceled")))(call("CancelWhatsAppLink")))
check("después de cancelar no queda vinculación", None, call("GetWhatsAppLinkCode")[1]["link"])

# --- Telegram ------------------------------------------------------------------------------
tg.reactions = ["👍", "❤️"]
r = call("GetTelegramStatus")
check("GetTelegramStatus: configurado y corriendo, sin check", (200, True, "running", None),
      (r[0], r[1]["configured"], r[1]["state"], r[1]["check"]))
r = call("ListTelegramConversations")
threads = r[1].get("threads") or []
check("ListTelegramConversations: los hilos", (200, True), (r[0], len(threads) > 0))
thread = threads[0]["thread"] if threads else "t_" + "0" * 32
r = call("GetTelegramThread", thread=thread)
check("GetTelegramThread: el hilo", 200, r[0])
check("GetTelegramThread con un hilo que no es t_: 400", (400, "invalid_parameter"),
      code(call("GetTelegramThread", thread="+5255")))
ref = next((m["ref"] for m in r[1].get("messages", []) if m.get("ref")), "tg:none")
r = call("ReactTelegram", ref=ref, emoji="👍")
check("ReactTelegram: la reacción del dueño", (200, True),
      (r[0], any(x.get("mine") for x in r[1].get("reactions", []))))
check("ReactTelegram con un ref de otro canal: 404", (404, "not_found"),
      code(call("ReactTelegram", ref="wo_" + "a" * 32, emoji="👍")))
check("SendTelegram a un hilo que no es t_: 404", (404, "not_found"), code(call("SendTelegram", thread="x", text="hola")))

check("CheckTelegramToken con forma mala: token_format", (400, "token_format"),
      code(call("CheckTelegramToken", token="nada")))
check("CheckTelegramToken rechazado por getMe: token_rejected", (400, "token_rejected"),
      code(call("CheckTelegramToken", token="999999:" + "B" * 28 + "REVOKED")))
r = call("CheckTelegramToken", token="999999:" + "C" * 35)
check("CheckTelegramToken: el bot nuevo, sin devolver el check", (200, "NuevoPaynaniBot", False),
      (r[0], r[1].get("bot_username"), "check" in r[1]))
check("GetTelegramStatus trae el check pendiente de este cliente", "NuevoPaynaniBot",
      (call("GetTelegramStatus")[1]["check"] or {}).get("bot_username"))
check("ApplyTelegramToken sin confirm_dedicated: missing_field", (400, "missing_field", "confirm_dedicated"),
      (lambda x: (x[0], x[1].get("code"), x[1].get("field")))(call("ApplyTelegramToken")))
check("otro cliente no tiene ese check: check_expired", (409, "check_expired"),
      code(call("ApplyTelegramToken", tok=token2, confirm_dedicated=True)))
mails.clear()
r = call("ApplyTelegramToken", confirm_dedicated=True)
check("ApplyTelegramToken: aplicado", (200, "applied", "NuevoPaynaniBot"),
      (r[0], r[1].get("result"), r[1].get("bot_username")))
check("FR-A10: el correo al dueño dice desde PaynaniWebMT (<nombre>)", True,
      any("desde PaynaniWebMT (MT en iaa.org.mx)" in str(m) for m in mails))
call("CheckTelegramToken", token="999999:" + "D" * 35)
check("CancelTelegramToken: ya no hay check", None,
      (call("CancelTelegramToken"), call("GetTelegramStatus")[1]["check"])[1])
check("SetupTelegram con Telegram ya configurado: 409", (409, "already_configured"),
      code(call("SetupTelegram", token="1:x", bot_username="b", owner_telegram="@j")))

# --- Webchat -------------------------------------------------------------------------------
r = call("GetWebchatThread")
check("GetWebchatThread vacío", (200, [], False), (r[0], r[1]["messages"], r[1]["typing"]))
r = upload("SendWebchat", {"text": "Hola agente"}, [("nota.txt", b"hola")])
check("SendWebchat con un archivo (multipart)", (200, "Hola agente", 1),
      (r[0], r[1].get("message", {}).get("text"), len(r[1].get("message", {}).get("files", []))))
first = r[1]["message"]["id"]
call("SendWebchat", text="Otro")
r = call("GetWebchatThread", since=first)
check("GetWebchatThread con since: sólo lo nuevo", ["Otro"], [m["text"] for m in r[1]["messages"]])
check("since que no es w_: 400", (400, "invalid_parameter"), code(call("GetWebchatThread", since="x")))
fref = next((f.get("ref") for m in call("GetWebchatThread")[1]["messages"] for f in m.get("files", [])), "")
status, hdrs, body = call("GetWebchatFile", binary=True, ref=fref)
check("GetWebchatFile: los bytes como archivo, no JSON", (200, b"hola", True),
      (status, body, "attachment" in hdrs.get("content-disposition", "")))
check("GetWebchatFile de un ref inventado: 404", (404, "not_found"), code(call("GetWebchatFile", ref="f_" + "0" * 32)))
check("SendWebchat vacío: código del almacén", 400, call("SendWebchat", text=" ")[0])
check("ReactWebchat con un almacén que no reacciona: 404", (404, "not_found"),
      code(call("ReactWebchat", ref=first, emoji="👍")))
wc.typing()
r = call("GetAgentTyping")
check("GetAgentTyping: escribiendo", (200, True), (r[0], r[1]["typing"]))

# --- canal no configurado --------------------------------------------------------------------
(tg_root / "telegram.env").unlink()
check("Telegram sin configurar: GetTelegramStatus dice configured false", False,
      call("GetTelegramStatus")[1]["configured"])
check("Telegram sin configurar: las demás 503 telegram_unavailable", (503, "telegram_unavailable"),
      code(call("ListTelegramConversations")))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
