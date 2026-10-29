"""
WhatsApp desde PaynaniApp (SMS_GATEWAY.md §12, PRD #550).

La pasarela no habla con el puente de Baileys: le pasa cada pedido `whatsapp.*` del
teléfono emparejado al servicio `paynani-whatsapp` por `state/whatsapp/control.sock`
(WHATSAPP_BRIDGE.md §11), con `by: phone:<device_id>`, y le devuelve a la app sólo lo
que §12 dice. El código de vinculación va sólo en el `result` de su pedido: nunca se
guarda, ni en el log, ni en la caché de reenvíos.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

from paynani_lib.whatsapp import config as wa_config

TYPES = ("whatsapp.status", "whatsapp.threads", "whatsapp.thread", "whatsapp.send",
         "whatsapp.link", "whatsapp.link_cancel", "whatsapp.unlink")
ADMIN = ("whatsapp.link", "whatsapp.link_cancel", "whatsapp.unlink")
REPLAYED = ADMIN + ("whatsapp.send",)  # los que cambian algo: el reenvío seguro no los repite
GRANT = "whatsapp.admin"
ID_RE = re.compile(r"^q_[0-9a-f]{32}$")
REPLAY_MAX = 64
REPLAY_TTL_S = 600
CHANGES_LOG = "whatsapp_changes.jsonl"
TIMEOUT_S = 15
# Lo que el servicio puede contestar y la app conoce (§12, «Errores de esta sección»).
PASS_CODES = {"forbidden", "conflict", "unavailable", "already_linked", "not_connected", "not_allowed",
              "not_started", "rate_limited", "not_found", "invalid"}


class ServiceDown(Exception):
    pass


def _digest(msg: dict) -> str:
    body = {k: v for k, v in msg.items() if k != "id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WhatsAppRelay:
    """
    `state_dir` es el state/ de la instalación (ahí está whatsapp/control.sock).
    `changes_dir` es donde va el log de cambios, junto al del roster. `notifier(to,
    subject, body)` y `owner_email()` mandan el aviso al dueño, como en §11.
    """

    def __init__(self, state_dir: Path, *, changes_dir: Path | None = None, notifier=None,
                 owner_email: Callable[[], str] | None = None, log=None,
                 configured: Callable[[], bool] | None = None, timeout_s: float = TIMEOUT_S):
        self.state_dir = Path(state_dir)
        self.changes_dir = Path(changes_dir) if changes_dir else self.state_dir
        self.notifier = notifier
        self.owner_email = owner_email or (lambda: "")
        self.log = log or (lambda line: None)
        self._configured = configured or wa_config.configured
        self.timeout_s = timeout_s
        self.replays: collections.OrderedDict = collections.OrderedDict()
        self.lock = threading.Lock()
        self.notify_threads: list[threading.Thread] = []
        # Un reenvío que llega mientras el primero sigue en curso espera su respuesta:
        # así un `whatsapp.send` lento no sale dos veces.
        self.inflight: dict[str, tuple[str, asyncio.Future]] = {}

    @property
    def socket_path(self) -> Path:
        return self.state_dir / "whatsapp" / "control.sock"

    # --- el welcome --------------------------------------------------------
    def configured(self) -> bool:
        try:
            return bool(self._configured())
        except Exception:  # noqa: BLE001 - un whatsapp.env roto es «no configurado»
            return False

    def accepts(self, configured: bool) -> list[str]:
        return list(TYPES) if configured else []

    def grants(self, configured: bool) -> list[str]:
        """La pasarela sólo habla con el teléfono emparejado: con WhatsApp, es el administrador."""
        return [GRANT] if configured else []

    # --- el servicio -------------------------------------------------------
    async def ask(self, type_: str, device_id: str, **fields) -> dict:
        """Un pedido al servicio por control.sock; la respuesta tal cual, o ServiceDown."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self.socket_path)), self.timeout_s)
        except (OSError, asyncio.TimeoutError) as exc:
            raise ServiceDown(type(exc).__name__) from None
        try:
            msg = {"type": type_, "id": "q_" + secrets.token_hex(16), "by": f"phone:{device_id}", **fields}
            writer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), self.timeout_s)
            if not line:
                raise ServiceDown("cerró la conexión")
            return json.loads(line)
        except (OSError, asyncio.TimeoutError, ValueError) as exc:
            raise ServiceDown(type(exc).__name__) from None
        finally:
            writer.close()

    async def watch(self, device_id: str, on_change: Callable[[str], Awaitable[None]],
                    retry_s: float = 5.0) -> None:
        """`whatsapp.watch` del servicio; cada `whatsapp.changed` llama a on_change(what). Para siempre."""
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
            except OSError:
                await asyncio.sleep(retry_s)
                continue
            try:
                msg = {"type": "whatsapp.watch", "id": "q_" + secrets.token_hex(16), "by": f"phone:{device_id}"}
                writer.write((json.dumps(msg) + "\n").encode())
                await writer.drain()
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        notice = json.loads(line)
                    except ValueError:
                        continue
                    if notice.get("type") == "whatsapp.changed" and notice.get("what") in ("threads", "status"):
                        await on_change(notice["what"])
            except (OSError, ConnectionError):
                pass
            finally:
                writer.close()
            await asyncio.sleep(retry_s)

    # --- un pedido de la app -----------------------------------------------
    async def handle(self, msg: dict, device_id: str, *, grants: list[str], configured: bool,
                     link_number: str | None) -> dict:
        rid = msg.get("id")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            return {"type": "error", "code": "missing_field", "ref": str(rid or "")[:80], "field": "id",
                    "detail": "id es q_ y 32 hex"}
        kind = msg.get("type")
        if not configured:
            return {"type": "error", "ref": rid, "code": "unavailable", "detail": "WhatsApp no está configurado"}
        if kind in ADMIN and GRANT not in grants:
            return {"type": "error", "ref": rid, "code": "forbidden"}
        digest = _digest(msg)
        if kind in REPLAYED:
            pending = self.inflight.get(rid)
            if pending is not None:
                if pending[0] != digest:
                    return {"type": "error", "ref": rid, "code": "invalid", "field": "id", "reason": "id_reused"}
                first = await asyncio.shield(pending[1])
                if kind == "whatsapp.link" and first.get("type") == "result":
                    return {"type": "error", "ref": rid, "code": "conflict",
                            "detail": "ese código ya se entregó; pide uno nuevo"}
                return {**first, "replayed": True} if first.get("type") == "result" else first
            with self.lock:
                self._expire()
                seen = self.replays.get(rid)
            if seen is not None:
                if seen[0] != digest:
                    return {"type": "error", "ref": rid, "code": "invalid", "field": "id", "reason": "id_reused"}
                if kind == "whatsapp.link":
                    # El código es de un solo uso: el reenvío nunca lo repite (§12).
                    return {"type": "error", "ref": rid, "code": "conflict",
                            "detail": "ese código ya se entregó; pide uno nuevo"}
                return {**seen[1], "replayed": True}
        future = asyncio.get_running_loop().create_future() if kind in REPLAYED else None
        if future is not None:
            self.inflight[rid] = (digest, future)
        response = {"type": "error", "ref": rid, "code": "unavailable"}
        try:
            response = await self._answer(kind, msg, rid, device_id, link_number)
        finally:
            if future is not None:
                # También si este pedido se cancela: el reenvío que espera no se queda colgado.
                self.inflight.pop(rid, None)
                future.set_result(response)
        if kind in REPLAYED and response.get("type") == "result":
            stored = response if kind != "whatsapp.link" else {"type": "result", "ref": rid}  # sin el código
            with self.lock:
                self.replays[rid] = (digest, stored, time.monotonic())
                while len(self.replays) > REPLAY_MAX:
                    self.replays.popitem(last=False)
            if kind in ADMIN:
                self._changed(device_id, kind)
        return response

    async def _answer(self, kind: str, msg: dict, rid: str, device_id: str, link_number: str | None) -> dict:
        try:
            return await self._forward(kind, msg, rid, device_id, link_number)
        except ServiceDown:
            if kind == "whatsapp.status":
                return {"type": "result", "ref": rid, "ok": True, "data": {
                    "state": "service_down", "me": None, "since": None, "linking": None,
                    "link_number": link_number}}
            return {"type": "error", "ref": rid, "code": "unavailable",
                    "detail": "el servicio paynani-whatsapp no corre"}

    async def _forward(self, kind: str, msg: dict, rid: str, device_id: str, link_number: str | None) -> dict:
        if kind == "whatsapp.status":
            reply = await self.ask(kind, device_id)
            if reply.get("type") == "result":
                data = dict(reply.get("data") or {})
                linking = data.get("linking")
                if isinstance(linking, dict):
                    by = str(linking.get("by") or "")
                    linking = dict(linking, by="phone" if by.startswith("phone:") else
                                   by if by in ("web", "terminal") else "terminal")
                return {"type": "result", "ref": rid, "ok": True, "data": {
                    "state": data.get("state"), "me": data.get("me"), "since": data.get("since"),
                    "linking": linking, "link_number": link_number}}
            return self._error(rid, reply)
        if kind == "whatsapp.link":
            number = msg.get("number") or link_number
            if not isinstance(number, str) or not number:
                return {"type": "error", "ref": rid, "code": "invalid", "field": "number", "reason": "missing"}
            reply = await self.ask(kind, device_id, mode="code", number=number)
            if reply.get("type") == "result":
                data = reply.get("data") or {}
                return {"type": "result", "ref": rid, "ok": True, "data": {
                    "code": data.get("code"), "expires_at": data.get("expires_at"),
                    "expires_in_s": max(0, min(180, int(data.get("expires_in_s") or 0)))}}
            return self._error(rid, reply)
        if kind in ("whatsapp.link_cancel", "whatsapp.unlink"):
            reply = await self.ask(kind, device_id)
            if reply.get("type") == "result":
                data = reply.get("data") or {}
                out = {"remote": bool(data.get("remote"))} if kind == "whatsapp.unlink" else {}
                return {"type": "result", "ref": rid, "ok": True, "data": out}
            return self._error(rid, reply)
        if kind == "whatsapp.threads":
            reply = await self.ask(kind, device_id, limit=msg.get("limit", 50), before=msg.get("before"))
        elif kind == "whatsapp.thread":
            reply = await self.ask(kind, device_id, number=msg.get("number"), limit=msg.get("limit", 50),
                                   before=msg.get("before"))
        else:  # whatsapp.send: sólo texto en esta versión (§12)
            text = msg.get("text")
            if not isinstance(text, str) or not text.strip():
                return {"type": "error", "ref": rid, "code": "invalid", "field": "text", "reason": "empty"}
            reply = await self.ask(kind, device_id, number=msg.get("number"), text=text)
        if reply.get("type") == "result":
            return {"type": "result", "ref": rid, "ok": True, "data": reply.get("data") or {}}
        return self._error(rid, reply)

    @staticmethod
    def _error(rid: str, reply: dict) -> dict:
        code = reply.get("code")
        out = {"type": "error", "ref": rid, "code": code if code in PASS_CODES else "unavailable"}
        for key in ("field", "reason", "retry_after_s", "detail"):
            if key in reply:
                out[key] = reply[key]
        return out

    def _expire(self) -> None:
        cutoff = time.monotonic() - REPLAY_TTL_S
        for rid in [r for r, (_, _, at) in self.replays.items() if at < cutoff]:
            del self.replays[rid]

    # --- log y aviso al dueño (§12, «Lo que se registra») -------------------
    def _append(self, entry: dict) -> None:
        path = self.changes_dir / CHANGES_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _changed(self, device_id: str, kind: str) -> None:
        action = kind.split(".", 1)[1]
        entry = {"at": _now_iso(), "change": "w_" + secrets.token_hex(8), "device_id": device_id,
                 "type": kind, "action": action}
        self._append(entry)
        self.log(f"whatsapp: {action} desde {device_id}")
        if self.notifier is None:
            return
        to = self.owner_email()
        if not to:
            self._append({"at": _now_iso(), "type": "notify", "for": entry["change"], "notified": False,
                          "error": "no_owner_email"})
            return
        subject, body = notice(entry)
        notifier = self.notifier

        def run():
            try:
                notifier(to, subject, body)
            except Exception as exc:  # noqa: BLE001 - el cambio ya está hecho y en el log
                self._append({"at": _now_iso(), "type": "notify", "for": entry["change"], "notified": False,
                              "error": type(exc).__name__})
            else:
                self._append({"at": _now_iso(), "type": "notify", "for": entry["change"], "notified": True})

        thread = threading.Thread(target=run, daemon=True)
        self.notify_threads.append(thread)
        thread.start()


def notice(entry: dict) -> tuple[str, str]:
    """El correo al dueño: qué se hizo con WhatsApp desde PaynaniApp. Nunca el código."""
    what = {"link": "se pidió un código para vincular WhatsApp",
            "link_cancel": "se canceló la vinculación de WhatsApp en curso",
            "unlink": "se desvinculó WhatsApp (se borraron las llaves del host)"}[entry["action"]]
    subject = {"link": "paynani: código de vinculación de WhatsApp pedido desde PaynaniApp",
               "link_cancel": "paynani: vinculación de WhatsApp cancelada desde PaynaniApp",
               "unlink": "paynani: WhatsApp desvinculado desde PaynaniApp"}[entry["action"]]
    lines = [f"Desde el teléfono {entry['device_id']}, a las {entry['at']}: {what}.", "",
             "El código no va en este correo: sólo lo vio la app.", "",
             "Si no fuiste tú, revisa WhatsApp → Dispositivos vinculados en tu teléfono, quita lo que no "
             "reconozcas, y revoca el teléfono emparejado con `paynani sms revoke`."]
    return subject, "\n".join(lines) + "\n"
