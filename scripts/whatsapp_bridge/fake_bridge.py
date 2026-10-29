#!/usr/bin/env python3
"""
Puente falso para las pruebas (WHATSAPP_BRIDGE.md §10).

Habla el mismo protocolo que index.js, por stdin y stdout, sin red ni Baileys. Las
órdenes `fake.*`, que el puente real no tiene, simulan lo que haría WhatsApp:

    fake.link_done      termina la vinculación en curso (escribe auth/creds.json)
    fake.message        un mensaje que llega: from_e164, text, kind, key_id, lid, push_name
    fake.call           una llamada: from_e164, status (missed|answered)
    fake.disconnect     se cae la conexión (status disconnected)
    fake.reconnect      vuelve (status connected)
    fake.logged_out     WhatsApp cerró la sesión: borra auth/ y avisa logged_out
    fake.crash          sale con el código `code` (1 por omisión) sin cerrar
    fake.hang           deja de contestar (para probar los pings)
    fake.silent_link    el próximo link contesta bien pero no manda QR ni código
    fake.stderr         escribe `text` en stderr

Variables de entorno, para las pruebas de arranque:
    FAKE_BRIDGE_EXIT=<n>   sale con n antes de leer nada
    FAKE_BRIDGE_LOG=<ruta> agrega cada orden recibida (sin campos) a ese archivo
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL = 1
ID_RE = re.compile(r"^c_[0-9a-f]{32}$")
E164_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")


def iso(offset_s: float = 0) -> str:
    return datetime.fromtimestamp(time.time() + offset_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result(ref, data=None) -> None:
    out({"type": "result", "ref": ref, "ok": True, "data": data or {}})


def fail(ref, code, detail=None, **extra) -> None:
    msg = {"type": "error", "ref": ref, "code": code}
    if detail:
        msg["detail"] = detail
    msg.update(extra)
    out(msg)


class Fake:
    def __init__(self) -> None:
        self.cfg: dict | None = None
        self.allowed: set[str] = set()
        self.state = {"state": "unlinked", "me": None, "since": iso(), "reason": None}
        self.link: dict | None = None
        self.hung = False
        self.silent_link = False

    # --- estado ---
    def creds(self) -> Path:
        return Path(self.cfg["auth_dir"]) / "creds.json"

    def has_creds(self) -> bool:
        return self.cfg is not None and self.creds().exists()

    def set_status(self, state: str, reason=None, me=None) -> None:
        self.state = {"state": state, "me": me if state != "unlinked" else None,
                      "since": iso(), "reason": reason}
        out({"type": "status", **self.state})

    def wipe(self) -> None:
        auth = Path(self.cfg["auth_dir"])
        if auth.is_symlink():
            sys.exit(4)
        for p in auth.iterdir():
            shutil.rmtree(p) if p.is_dir() else p.unlink()

    # --- órdenes ---
    def handle(self, msg: dict) -> None:
        ref = msg.get("id") if isinstance(msg.get("id"), str) and ID_RE.match(msg["id"]) else None
        if ref is None:
            return fail(None, "missing_field", field="id")
        kind = msg["type"]
        if kind != "start" and self.cfg is None:
            return fail(ref, "not_started")
        handler = getattr(self, "do_" + kind.replace(".", "_"), None)
        if handler is None:
            return fail(ref, "unknown_type", f"type '{kind[:40]}' no existe")
        handler(ref, msg)

    def do_start(self, ref, msg) -> None:
        if msg.get("protocol") != PROTOCOL:
            fail(ref, "unsupported_protocol")
            sys.exit(3)
        auth = Path(msg["auth_dir"])
        st = auth.lstat()
        if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077 or any(
                stat.S_IMODE(p.lstat().st_mode) & 0o077 for p in auth.iterdir()):
            sys.stderr.write("auth_dir con permisos abiertos\n")
            sys.exit(4)
        media = Path(msg["media_dir"])
        media.mkdir(exist_ok=True, mode=0o700)
        if media.is_symlink() or not media.is_dir():
            sys.stderr.write("media_dir es un enlace simbólico\n")
            sys.exit(4)
        self.cfg = msg
        self.allowed = {n for n in msg.get("allowed") or [] if E164_RE.match(n)}
        result(ref, {"protocol": PROTOCOL, "bridge_version": "fake", "baileys_version": None})
        if self.has_creds():
            me = json.loads(self.creds().read_text()).get("me")
            self.set_status("connecting", me=me)
            self.set_status("connected", me=me)
        else:
            out({"type": "status", **self.state})

    def do_status(self, ref, msg) -> None:
        result(ref, dict(self.state))

    def do_ping(self, ref, msg) -> None:
        result(ref, {"state": self.state["state"]})

    def do_allow(self, ref, msg) -> None:
        self.allowed = {n for n in msg.get("allowed") or [] if E164_RE.match(n)}
        result(ref, {"count": len(self.allowed)})

    def do_link(self, ref, msg) -> None:
        mode = msg.get("mode")
        if mode not in ("qr", "code"):
            return fail(ref, "missing_field", field="mode")
        if mode == "code" and not E164_RE.match(msg.get("number") or ""):
            return fail(ref, "missing_field", field="number")
        if self.state["state"] == "connected":
            return fail(ref, "already_linked")
        if self.link:
            out({"type": "link.ended", "reason": "replaced"})
        self.link = {"mode": mode, "number": msg.get("number")}
        self.set_status("linking")
        result(ref)
        if self.silent_link:
            self.silent_link = False
            return
        if mode == "qr":
            out({"type": "link.qr", "qr": "2@" + secrets.token_urlsafe(24), "expires_at": iso(20)})
        else:
            code = secrets.token_hex(4).upper()
            out({"type": "link.code", "code": f"{code[:4]}-{code[4:]}", "expires_at": iso(180)})

    def do_link_cancel(self, ref, msg) -> None:
        if self.link:
            self.link = None
            out({"type": "link.ended", "reason": "canceled"})
            self.set_status("unlinked")
        result(ref)

    def do_send(self, ref, msg) -> None:
        if self.state["state"] != "connected":
            return fail(ref, "not_connected")
        to = msg.get("to") or ""
        if not E164_RE.match(to):
            return fail(ref, "missing_field", field="to")
        if to not in self.allowed:
            return fail(ref, "not_allowed", "el número no está en allowed")
        text = msg.get("text") or ""
        if len(text) > 4000:
            return fail(ref, "too_large")
        f = msg.get("file")
        if f:
            p = Path(f.get("path", ""))
            if p.is_symlink() or not p.is_file():
                return fail(ref, "not_allowed", "no es un archivo regular")
        elif not text:
            return fail(ref, "missing_field", field="text")
        key = "3EB0" + secrets.token_hex(8).upper()
        chat = to[1:] + "@s.whatsapp.net"
        result(ref, {"key_id": key, "chat": chat, "sent_at": iso()})
        out({"type": "receipt", "key_id": key, "chat": chat, "status": "server", "at": iso()})

    def do_read(self, ref, msg) -> None:
        result(ref)

    def do_logout(self, ref, msg) -> None:
        if not self.has_creds():
            return fail(ref, "not_connected")
        self.wipe()
        self.set_status("unlinked")
        result(ref, {"remote": True})

    def do_shutdown(self, ref, msg) -> None:
        result(ref)
        sys.exit(0)

    # --- simulaciones ---
    def do_fake_link_done(self, ref, msg) -> None:
        if not self.link:
            return fail(ref, "missing_field", "no hay vinculación en curso")
        me = self.link.get("number") or msg.get("me") or "+15550000000"
        p = self.creds()
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump({"me": me, "registered": True}, fh)
        self.link = None
        out({"type": "link.ended", "reason": "linked", "me": me})
        self.set_status("connected", me=me)
        result(ref)

    def do_fake_message(self, ref, msg) -> None:
        e164 = msg.get("from_e164")
        lid = msg.get("lid")
        jid = (e164[1:] + "@s.whatsapp.net") if e164 else lid
        out({"type": "message", "key_id": msg.get("key_id") or "3EB0" + secrets.token_hex(8).upper(),
             "chat": jid, "from": {"e164": e164, "jid": jid, "lid": lid},
             "push_name": msg.get("push_name"), "sent_at": msg.get("sent_at") or iso(),
             "kind": msg.get("kind") or "text", "text": msg.get("text"), "media": msg.get("media")})
        result(ref)

    def do_fake_call(self, ref, msg) -> None:
        e164 = msg.get("from_e164")
        out({"type": "call", "call_id": secrets.token_hex(8).upper(),
             "from": {"e164": e164, "jid": e164[1:] + "@s.whatsapp.net" if e164 else None, "lid": None},
             "status": msg.get("status") or "missed", "video": False, "at": iso()})
        result(ref)

    def do_fake_disconnect(self, ref, msg) -> None:
        self.set_status("disconnected", "connection_lost", me=self.state["me"])
        result(ref)

    def do_fake_reconnect(self, ref, msg) -> None:
        self.set_status("connected", me=self.state["me"])
        result(ref)

    def do_fake_logged_out(self, ref, msg) -> None:
        self.wipe()
        self.set_status("logged_out", "logged_out")
        self.set_status("unlinked", "logged_out")
        result(ref)

    def do_fake_crash(self, ref, msg) -> None:
        os._exit(int(msg.get("code", 1)))

    def do_fake_silent_link(self, ref, msg) -> None:
        self.silent_link = True
        result(ref)

    def do_fake_hang(self, ref, msg) -> None:
        self.hung = True

    def do_fake_stderr(self, ref, msg) -> None:
        sys.stderr.write(str(msg.get("text", "")) + "\n")
        sys.stderr.flush()
        result(ref)


def main() -> int:
    if os.environ.get("FAKE_BRIDGE_EXIT"):
        return int(os.environ["FAKE_BRIDGE_EXIT"])
    os.umask(0o077)
    log = os.environ.get("FAKE_BRIDGE_LOG")
    fake = Fake()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            fail(None, "bad_json", "no es JSON")
            continue
        if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
            fail(None, "bad_json", "no es un objeto con type")
            continue
        if log:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(msg["type"] + "\n")
        if fake.hung:
            continue
        fake.handle(msg)
    return 0  # stdin cerrado: cierre normal


if __name__ == "__main__":
    sys.exit(main())
