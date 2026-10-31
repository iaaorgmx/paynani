#!/usr/bin/env python3
"""
Servidor falso de la Bot API de Telegram para las pruebas (TELEGRAM.md §9, #612 TG-0).

Habla HTTP en 127.0.0.1 como https://api.telegram.org: `/bot<token>/<método>` con
parámetros en la query, en un formulario, en JSON o en multipart, y
`/file/bot<token>/<ruta>` para bajar archivos. No usa red ni dependencias.

Las pruebas lo manejan desde Python (`private_message`, `fail_next`, `revoke`…) y leen
lo que el servicio mandó en `sent`. Se comporta como Telegram en lo que el servicio
tiene que manejar: un solo `getUpdates` a la vez (el segundo recibe 409), 409 con un
webhook puesto, 401 con el token revocado, 429 con `retry_after`, y la confirmación
de updates por `offset`.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

_PATH = re.compile(r"^/bot(?P<token>[^/]+)/(?P<method>[A-Za-z]+)$")
_FILE = re.compile(r"^/file/bot(?P<token>[^/]+)/(?P<path>[A-Za-z0-9_./-]+)$")


class FakeBotAPI:
    def __init__(self, token="123456:TEST", bot_id=123456, username="PruebaBot", *, drafts=True):
        self.token = token
        self.bot_id = bot_id
        self.username = username
        self.drafts = drafts             # False: sendMessageDraft responde 400, como un chat que no lo acepta
        self.webhook_url = ""
        self.revoked = False
        self.sent = []                   # [{"method": ..., "params": {...}}] en orden
        self.left_chats = []
        self.calls = []                  # nombres de métodos, en orden (para las pruebas de orden)
        self._updates = []               # [{"update_id": n, ...}]
        self._next_update = 1000
        self._next_message = {}          # chat_id -> siguiente message_id
        self._files = {}                 # file_id -> (file_path, bytes)
        self._fail = {}                  # método -> [(status, retry_after), ...]
        self._polling = 0
        self._cond = threading.Condition()
        self._server = None
        self._thread = None

    # --- ciclo de vida ---
    @property
    def base_url(self):
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self, port=0):
        api = self

        class Handler(_Handler):
            fake = api

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server:
            with self._cond:
                self._cond.notify_all()
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # --- lo que hacen las pruebas ---
    def _push(self, update):
        with self._cond:
            update = {"update_id": self._next_update, **update}
            self._next_update += 1
            self._updates.append(update)
            self._cond.notify_all()
            return update["update_id"]

    def _message_id(self, chat_id):
        n = self._next_message.get(chat_id, 1)
        self._next_message[chat_id] = n + 1
        return n

    @staticmethod
    def _user(user_id, first_name, username=None):
        u = {"id": user_id, "is_bot": False, "first_name": first_name}
        if username:
            u["username"] = username
        return u

    def private_message(self, user_id, text=None, first_name="Prueba", username=None, *,
                        photo=None, document=None, message_id=None):
        """Un mensaje privado. `photo`/`document`: bytes; el archivo queda listo para getFile."""
        msg = {"message_id": message_id or self._message_id(user_id), "date": int(time.time()),
               "from": self._user(user_id, first_name, username),
               "chat": {"id": user_id, "type": "private", "first_name": first_name}}
        if text is not None:
            msg["text"] = text
        if photo is not None:
            fid = self.add_file(photo, "photos/file_%d.jpg" % len(self._files))
            msg["photo"] = [{"file_id": fid, "file_unique_id": fid + "u", "width": 90, "height": 90,
                             "file_size": len(photo)}]
        if document is not None:
            data, name, mime = document
            fid = self.add_file(data, "documents/file_%d" % len(self._files))
            msg["document"] = {"file_id": fid, "file_unique_id": fid + "u", "file_name": name,
                               "mime_type": mime, "file_size": len(data)}
        uid = self._push({"message": msg})
        return uid, msg["message_id"]

    def edit_message(self, user_id, message_id, text, first_name="Prueba"):
        msg = {"message_id": message_id, "date": int(time.time()), "edit_date": int(time.time()),
               "from": self._user(user_id, first_name),
               "chat": {"id": user_id, "type": "private", "first_name": first_name}, "text": text}
        return self._push({"edited_message": msg})

    def group_message(self, chat_id, user_id, text, chat_type="group"):
        msg = {"message_id": self._message_id(chat_id), "date": int(time.time()),
               "from": self._user(user_id, "Alguien"),
               "chat": {"id": chat_id, "type": chat_type, "title": "Grupo"}, "text": text}
        return self._push({"message": msg})

    def group_added(self, chat_id, chat_type="group"):
        return self._push({"my_chat_member": {
            "chat": {"id": chat_id, "type": chat_type, "title": "Grupo"},
            "from": self._user(9, "Alguien"), "date": int(time.time()),
            "old_chat_member": {"status": "left", "user": {"id": self.bot_id, "is_bot": True}},
            "new_chat_member": {"status": "member", "user": {"id": self.bot_id, "is_bot": True}}}})

    def add_file(self, data, file_path, declared_size=None):
        fid = "F%04d" % (len(self._files) + 1)
        self._files[fid] = (file_path, bytes(data), declared_size)
        return fid

    def set_webhook(self, url):
        self.webhook_url = url

    def fail_next(self, method, status, retry_after=None):
        self._fail.setdefault(method, []).append((status, retry_after))

    def revoke(self):
        self.revoked = True

    def pending(self):
        with self._cond:
            return [u["update_id"] for u in self._updates]

    def sent_of(self, method):
        return [s["params"] for s in self.sent if s["method"] == method]

    # --- lo que contesta ---
    def handle(self, method, params):
        self.calls.append(method)
        if self.revoked:
            return 401, _err(401, "Unauthorized")
        queued = self._fail.get(method)
        if queued:
            status, retry_after = queued.pop(0)
            if status == 429:
                return 429, _err(429, "Too Many Requests: retry after %d" % (retry_after or 1),
                                 {"retry_after": retry_after or 1})
            return status, _err(status, "Forced error")
        fn = getattr(self, "_m_" + method, None)
        if fn is None:
            return 404, _err(404, "Not Found: method not found")
        return fn(params)

    def _m_getMe(self, p):
        return _ok({"id": self.bot_id, "is_bot": True, "first_name": self.username,
                    "username": self.username, "can_join_groups": True,
                    "can_read_all_group_messages": False, "supports_inline_queries": False})

    def _m_getWebhookInfo(self, p):
        with self._cond:
            pending = len(self._updates)
        return _ok({"url": self.webhook_url, "has_custom_certificate": False,
                    "pending_update_count": pending})

    def _m_deleteWebhook(self, p):
        self.webhook_url = ""
        if _truthy(p.get("drop_pending_updates")):
            with self._cond:
                self._updates.clear()
        return _ok(True)

    def _m_getUpdates(self, p):
        if self.webhook_url:
            return 409, _err(409, "Conflict: can't use getUpdates method while webhook is active; "
                                  "use deleteWebhook to delete the webhook first")
        offset = int(p.get("offset") or 0)
        timeout = min(int(p.get("timeout") or 0), 50)
        limit = max(1, min(int(p.get("limit") or 100), 100))
        allowed = p.get("allowed_updates")
        if isinstance(allowed, str):
            allowed = json.loads(allowed)
        deadline = time.monotonic() + timeout
        with self._cond:
            if self._polling:
                return 409, _err(409, "Conflict: terminated by other getUpdates request; make sure "
                                      "that only one bot instance is running")
            self._polling += 1
            try:
                if offset:
                    # Como Telegram: pedir desde `offset` confirma todo lo anterior.
                    self._updates = [u for u in self._updates if u["update_id"] >= offset]
                while True:
                    ready = [u for u in self._updates
                             if not allowed or any(k in u for k in allowed)][:limit]
                    left = deadline - time.monotonic()
                    if ready or left <= 0 or self._server is None:
                        return _ok(ready)
                    self._cond.wait(left)
            finally:
                self._polling -= 1

    def _record(self, method, p):
        self.sent.append({"method": method, "params": dict(p)})

    def _sent_message(self, method, p, **extra):
        self._record(method, p)
        chat_id = int(p.get("chat_id"))
        msg = {"message_id": self._message_id(chat_id), "date": int(time.time()),
               "chat": {"id": chat_id, "type": "private"},
               "from": {"id": self.bot_id, "is_bot": True, "first_name": self.username}}
        msg.update(extra)
        return _ok(msg)

    def _m_sendMessage(self, p):
        text = str(p.get("text") or "")
        if not text:
            return 400, _err(400, "Bad Request: message text is empty")
        if len(text) > 4096:
            return 400, _err(400, "Bad Request: message is too long")
        return self._sent_message("sendMessage", p, text=text)

    def _m_sendPhoto(self, p):
        return self._sent_message("sendPhoto", p, photo=[{"file_id": "OUT", "width": 1, "height": 1}])

    def _m_sendDocument(self, p):
        return self._sent_message("sendDocument", p, document={"file_id": "OUT"})

    def _m_sendChatAction(self, p):
        self._record("sendChatAction", p)
        return _ok(True)

    def _m_sendMessageDraft(self, p):
        if not self.drafts:
            return 400, _err(400, "Bad Request: method is unavailable for this chat")
        if not int(p.get("draft_id") or 0):
            return 400, _err(400, "Bad Request: draft_id must be non-zero")
        self._record("sendMessageDraft", p)
        return _ok(True)

    def _m_editMessageText(self, p):
        self._record("editMessageText", p)
        return _ok({"message_id": int(p.get("message_id") or 0), "text": p.get("text"),
                    "chat": {"id": int(p.get("chat_id")), "type": "private"}})

    def _m_leaveChat(self, p):
        self._record("leaveChat", p)
        self.left_chats.append(int(p.get("chat_id")))
        return _ok(True)

    def _m_getFile(self, p):
        fid = p.get("file_id")
        if fid not in self._files:
            return 400, _err(400, "Bad Request: invalid file_id")
        path, data, declared = self._files[fid]
        return _ok({"file_id": fid, "file_unique_id": fid + "u",
                    "file_size": declared if declared is not None else len(data), "file_path": path})

    def file_bytes(self, path):
        for p, data, _ in self._files.values():
            if p == path:
                return data
        return None


def _ok(result):
    return 200, {"ok": True, "result": result}


def _err(code, description, parameters=None):
    body = {"ok": False, "error_code": code, "description": description}
    if parameters:
        body["parameters"] = parameters
    return body


def _truthy(v):
    return str(v).lower() in ("1", "true", "yes")


def _multipart(body, ctype):
    """Sólo los campos de texto; un archivo se registra por su nombre y tamaño."""
    m = re.search(r"boundary=([^;]+)", ctype)
    if not m:
        return {}
    out = {}
    for part in body.split(b"--" + m.group(1).strip('"').encode()):
        head, _, data = part.partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head)
        if not name:
            continue
        data = data[:-2] if data.endswith(b"\r\n") else data
        key = name.group(1).decode()
        if b"filename=" in head:
            out[key] = {"file_bytes": len(data)}
        else:
            out[key] = data.decode("utf-8", "replace")
    return out


class _Handler(BaseHTTPRequestHandler):
    fake: FakeBotAPI = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):     # sin ruido en las pruebas, y nunca la URL con el token
        pass

    def _reply(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _params(self):
        url = urlsplit(self.path)
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = self.rfile.read(length)
            ctype = self.headers.get("Content-Type", "")
            if ctype.startswith("application/json"):
                params.update(json.loads(body or b"{}"))
            elif ctype.startswith("multipart/form-data"):
                params.update(_multipart(body, ctype))
            else:
                params.update({k: v[-1] for k, v in parse_qs(body.decode()).items()})
        return url.path, params

    def _dispatch(self):
        path, params = self._params()
        m = _FILE.match(path)
        if m:
            data = self.fake.file_bytes(m.group("path"))
            if m.group("token") != self.fake.token or data is None or self.fake.revoked:
                return self._reply(404, _err(404, "Not Found"))
            return self._reply(200, data, "application/octet-stream")
        m = _PATH.match(path)
        if not m or m.group("token") != self.fake.token:
            return self._reply(404 if not m else 401, _err(404 if not m else 401,
                               "Not Found" if not m else "Unauthorized"))
        status, body = self.fake.handle(m.group("method"), params)
        self._reply(status, body)

    do_GET = _dispatch
    do_POST = _dispatch


def main(argv=None):
    ap = argparse.ArgumentParser(description="Servidor falso de la Bot API (TELEGRAM.md §9)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--token", default="123456:TEST")
    args = ap.parse_args(argv)
    api = FakeBotAPI(token=args.token).start(args.port)
    print(f"fake Bot API on {api.base_url} (token {args.token!r}); Ctrl-C to stop", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        api.stop()


if __name__ == "__main__":
    main()
