#!/usr/bin/env python3
"""Pruebas del servidor falso de la Bot API (TELEGRAM.md §9, #612 TG-0)."""

import json
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from paynani_lib.telegram.fake_api import FakeBotAPI

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"ok    {name}")
    else:
        failed += 1
        print(f"FAIL  {name} {detail}")


def call(api, method, token=None, **params):
    data = urllib.parse.urlencode({k: json.dumps(v) if isinstance(v, (list, dict)) else v
                                   for k, v in params.items()}).encode()
    req = urllib.request.Request(f"{api.base_url}/bot{token or api.token}/{method}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


api = FakeBotAPI(token="123456:TEST", bot_id=123456, username="PruebaBot").start()
try:
    s, b = call(api, "getMe")
    check("getMe devuelve el bot", s == 200 and b["result"]["username"] == "PruebaBot", str(b))
    s, b = call(api, "getMe", token="999:OTRO")
    check("otro token: 401", s == 401 and b["ok"] is False)

    s, b = call(api, "getUpdates", timeout=0)
    check("sin updates: lista vacía", s == 200 and b["result"] == [])

    uid, mid = api.private_message(1001, "hola", first_name="Ana")
    s, b = call(api, "getUpdates", timeout=0)
    check("un mensaje privado llega", s == 200 and len(b["result"]) == 1
          and b["result"][0]["message"]["text"] == "hola"
          and b["result"][0]["message"]["chat"]["type"] == "private", str(b))
    s, b = call(api, "getUpdates", timeout=0)
    check("sin offset, el mismo update se vuelve a entregar", len(b["result"]) == 1)
    s, b = call(api, "getUpdates", timeout=0, offset=uid + 1)
    check("offset confirma y no lo repite", b["result"] == [] and api.pending() == [])

    # espera larga: el update que llega durante la espera la despierta
    t0 = time.monotonic()
    threading.Timer(0.3, lambda: api.private_message(1001, "despierta")).start()
    s, b = call(api, "getUpdates", timeout=5, offset=uid + 1)
    check("la espera larga regresa en cuanto llega algo",
          len(b["result"]) == 1 and time.monotonic() - t0 < 3, f"{time.monotonic() - t0:.2f}s")
    last = b["result"][0]["update_id"]

    # dos lectores: el segundo recibe 409
    results = {}

    def poll():
        results["first"] = call(api, "getUpdates", timeout=2, offset=last + 1)

    th = threading.Thread(target=poll)
    th.start()
    time.sleep(0.3)
    s, b = call(api, "getUpdates", timeout=0, offset=last + 1)
    th.join()
    check("un segundo getUpdates a la vez: 409", s == 409 and "only one bot instance" in b["description"], str(b))
    check("el primero sigue bien", results["first"][0] == 200)

    api.set_webhook("https://ejemplo.invalid/hook")
    s, b = call(api, "getWebhookInfo")
    check("getWebhookInfo dice el webhook", b["result"]["url"] == "https://ejemplo.invalid/hook")
    s, b = call(api, "getUpdates", timeout=0)
    check("con webhook, getUpdates da 409", s == 409 and "webhook is active" in b["description"])
    s, b = call(api, "deleteWebhook")
    s, b = call(api, "getWebhookInfo")
    check("deleteWebhook lo quita", b["result"]["url"] == "")

    api.edit_message(1001, mid, "hola editado")
    api.group_added(-500)
    s, b = call(api, "getUpdates", timeout=0, offset=last + 1,
                allowed_updates=["message", "edited_message", "my_chat_member"])
    kinds = [next(k for k in u if k != "update_id") for u in b["result"]]
    check("edición y grupo llegan con allowed_updates", kinds == ["edited_message", "my_chat_member"], str(kinds))
    s, b = call(api, "getUpdates", timeout=0, offset=last + 1, allowed_updates=["message"])
    check("allowed_updates filtra", b["result"] == [])

    s, b = call(api, "sendMessage", chat_id=1001, text="respuesta")
    check("sendMessage se registra", s == 200 and api.sent_of("sendMessage")[-1]["text"] == "respuesta")
    s, b = call(api, "sendMessage", chat_id=1001, text="x" * 4097)
    check("más de 4096 caracteres: 400", s == 400)
    s, b = call(api, "sendChatAction", chat_id=1001, action="typing")
    check("sendChatAction se registra", api.sent_of("sendChatAction")[-1]["action"] == "typing")
    s, b = call(api, "sendMessageDraft", chat_id=1001, draft_id=7, text="borr")
    check("sendMessageDraft se registra", s == 200 and api.sent_of("sendMessageDraft")[-1]["draft_id"] == "7")
    s, b = call(api, "sendMessageDraft", chat_id=1001, draft_id=0, text="x")
    check("draft_id 0: 400", s == 400)
    api.drafts = False
    s, b = call(api, "sendMessageDraft", chat_id=1001, draft_id=8, text="x")
    check("chat sin borradores: 400", s == 400 and "unavailable" in b["description"])
    s, b = call(api, "editMessageText", chat_id=1001, message_id=5, text="editado")
    check("editMessageText se registra", api.sent_of("editMessageText")[-1]["text"] == "editado")

    api.fail_next("sendMessage", 429, retry_after=3)
    s, b = call(api, "sendMessage", chat_id=1001, text="otra")
    check("fail_next 429 trae retry_after", s == 429 and b["parameters"]["retry_after"] == 3)
    s, b = call(api, "sendMessage", chat_id=1001, text="otra")
    check("después del fallo forzado, normal", s == 200)

    uid2, _ = api.private_message(1001, None, photo=b"\xff\xd8\xff\xe0JPEGDATA")
    s, b = call(api, "getUpdates", timeout=0, offset=uid2)
    fid = b["result"][-1]["message"]["photo"][0]["file_id"]
    s, b = call(api, "getFile", file_id=fid)
    path = b["result"]["file_path"]
    with urllib.request.urlopen(f"{api.base_url}/file/bot{api.token}/{path}", timeout=5) as r:
        data = r.read()
    check("getFile y la descarga dan los bytes", data.startswith(b"\xff\xd8\xff"), repr(data[:8]))
    try:
        urllib.request.urlopen(f"{api.base_url}/file/bot999:OTRO/{path}", timeout=5)
        check("la descarga con otro token falla", False)
    except urllib.error.HTTPError as e:
        check("la descarga con otro token falla", e.code == 404)
    fid2 = api.add_file(b"%PDF-1.7 grande", "documents/mentira.pdf", declared_size=10)
    s, b = call(api, "getFile", file_id=fid2)
    check("tamaño declarado distinto del real, para FR-18", b["result"]["file_size"] == 10)

    s, b = call(api, "leaveChat", chat_id=-500)
    check("leaveChat se registra", api.left_chats == [-500])

    api.revoke()
    s, b = call(api, "getMe")
    check("token revocado: 401", s == 401)
finally:
    api.stop()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
