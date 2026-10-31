"""
Telegram desde PaynaniApp (TELEGRAM.md §6, PRD #609 FR-29a; TG-5 de #612).

Como `whatsapp_api.py`: la pasarela le pasa cada pedido `telegram.*` del teléfono
emparejado al servicio `paynani-telegram` por `state/telegram/control.sock`
(TELEGRAM.md §4), con `by: phone:<device_id>`. Sólo cuatro tipos: `status`, `threads`,
`thread` y `send`. No hay `grants`: la app no cambia el token, no ve ids y no tiene
«Agregar al roster». `send` lleva sólo `thread` y `text`, nunca `contact` ni `file`.
"""
from __future__ import annotations

import asyncio
import collections
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

from paynani_lib.telegram import config as tg_config

from .whatsapp_api import ID_RE, ServiceDown, _digest

TYPES = ("telegram.status", "telegram.threads", "telegram.thread", "telegram.send")
REPLAYED = ("telegram.send",)   # el único que cambia algo: el reenvío no lo repite
REPLAY_MAX = 64
REPLAY_TTL_S = 600
TIMEOUT_S = 15
# Un `send` largo sale en varias partes, una por segundo, y un 429 espera y reintenta
# (§4): puede tardar más que una lectura. La app reenvía con el mismo id a los 15 s y
# ese reenvío espera esta misma respuesta.
SEND_TIMEOUT_S = 90
PASS_CODES = {"forbidden", "conflict", "unavailable", "not_allowed", "not_started", "rate_limited",
              "not_found", "invalid"}
STATUS_FIELDS = ("state", "bot_username", "since", "last_poll_at", "counters", "reason")


class TelegramRelay:
    """`state_dir` es el state/ de la instalación (ahí está telegram/control.sock)."""

    def __init__(self, state_dir: Path, *, log=None, configured: Callable[[], bool] | None = None,
                 timeout_s: float = TIMEOUT_S, send_timeout_s: float = SEND_TIMEOUT_S):
        self.state_dir = Path(state_dir)
        self.log = log or (lambda line: None)
        self._configured = configured or tg_config.configured
        self.timeout_s = timeout_s
        self.send_timeout_s = send_timeout_s
        self.replays: collections.OrderedDict = collections.OrderedDict()
        self.lock = threading.Lock()
        self.inflight: dict[str, tuple[str, asyncio.Future]] = {}

    @property
    def socket_path(self) -> Path:
        return self.state_dir / "telegram" / "control.sock"

    # --- el welcome --------------------------------------------------------
    def configured(self) -> bool:
        try:
            return bool(self._configured())
        except Exception:  # noqa: BLE001 - un telegram.env roto es «no configurado»
            return False

    def accepts(self, configured: bool) -> list[str]:
        return list(TYPES) if configured else []

    # --- el servicio -------------------------------------------------------
    async def ask(self, type_: str, device_id: str, *, timeout_s: float | None = None, **fields) -> dict:
        """Un pedido al servicio por control.sock; la respuesta tal cual, o ServiceDown."""
        wait = timeout_s or self.timeout_s
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self.socket_path)), self.timeout_s)
        except (OSError, asyncio.TimeoutError) as exc:
            raise ServiceDown(type(exc).__name__) from None
        try:
            msg = {"type": type_, "id": "q_" + secrets.token_hex(16), "by": f"phone:{device_id}", **fields}
            writer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), wait)
            if not line:
                raise ServiceDown("cerró la conexión")
            return json.loads(line)
        except (OSError, asyncio.TimeoutError, ValueError) as exc:
            raise ServiceDown(type(exc).__name__) from None
        finally:
            writer.close()

    async def watch(self, device_id: str, on_change: Callable[[str], Awaitable[None]],
                    retry_s: float = 5.0) -> None:
        """
        `telegram.watch` del servicio; cada `telegram.changed` llama a on_change(what). Para
        siempre. Además, `status` cuando se pierde la conexión con el servicio y cuando
        vuelve, para que la app no se entere sólo al pedir algo (Andy en #612). Al arrancar
        con el servicio caído no avisa: la app ya lo ve en `telegram.status`.
        """
        up: bool | None = None

        async def changed(now_up: bool) -> None:
            nonlocal up
            if up is not None and up != now_up:
                await on_change("status")
            up = now_up

        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
            except OSError:
                await changed(False)
                await asyncio.sleep(retry_s)
                continue
            try:
                msg = {"type": "telegram.watch", "id": "q_" + secrets.token_hex(16), "by": f"phone:{device_id}"}
                writer.write((json.dumps(msg) + "\n").encode())
                await writer.drain()
                first = await reader.readline()
                if not first or json.loads(first).get("type") != "result":
                    raise ConnectionError("watch rechazado")
                await changed(True)
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        notice = json.loads(line)
                    except ValueError:
                        continue
                    if notice.get("type") == "telegram.changed" and notice.get("what") in ("threads", "status"):
                        await on_change(notice["what"])
            except (OSError, ConnectionError, ValueError):
                pass
            finally:
                writer.close()
            await changed(False)
            await asyncio.sleep(retry_s)

    # --- un pedido de la app -----------------------------------------------
    async def handle(self, msg: dict, device_id: str, *, configured: bool) -> dict:
        rid = msg.get("id")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            return {"type": "error", "code": "missing_field", "ref": str(rid or "")[:80], "field": "id",
                    "detail": "id es q_ y 32 hex"}
        kind = msg.get("type")
        if not configured:
            return {"type": "error", "ref": rid, "code": "unavailable", "detail": "Telegram no está configurado"}
        if kind not in REPLAYED:
            return await self._answer(kind, msg, rid, device_id)
        digest = _digest(msg)
        pending = self.inflight.get(rid)
        if pending is not None:
            if pending[0] != digest:
                return {"type": "error", "ref": rid, "code": "invalid", "field": "id", "reason": "id_reused"}
            first = await asyncio.shield(pending[1])
            return {**first, "replayed": True} if first.get("type") == "result" else first
        with self.lock:
            self._expire()
            seen = self.replays.get(rid)
        if seen is not None:
            if seen[0] != digest:
                return {"type": "error", "ref": rid, "code": "invalid", "field": "id", "reason": "id_reused"}
            return {**seen[1], "replayed": True}
        future = asyncio.get_running_loop().create_future()
        self.inflight[rid] = (digest, future)
        response = {"type": "error", "ref": rid, "code": "unavailable"}
        try:
            response = await self._answer(kind, msg, rid, device_id)
        finally:
            # También si este pedido se cancela: el reenvío que espera no se queda colgado.
            self.inflight.pop(rid, None)
            future.set_result(response)
        if response.get("type") == "result":
            with self.lock:
                self.replays[rid] = (digest, response, time.monotonic())
                while len(self.replays) > REPLAY_MAX:
                    self.replays.popitem(last=False)
        return response

    async def _answer(self, kind: str, msg: dict, rid: str, device_id: str) -> dict:
        try:
            return await self._forward(kind, msg, rid, device_id)
        except ServiceDown:
            if kind == "telegram.status":
                return {"type": "result", "ref": rid, "ok": True, "data": {"state": "service_down"}}
            return {"type": "error", "ref": rid, "code": "unavailable",
                    "detail": "el servicio paynani-telegram no corre"}

    async def _forward(self, kind: str, msg: dict, rid: str, device_id: str) -> dict:
        if kind == "telegram.status":
            reply = await self.ask(kind, device_id)
            if reply.get("type") == "result":
                data = reply.get("data") or {}
                return {"type": "result", "ref": rid, "ok": True,
                        "data": {k: data[k] for k in STATUS_FIELDS if k in data}}
            return self._error(rid, reply)
        if kind == "telegram.threads":
            reply = await self.ask(kind, device_id, limit=msg.get("limit", 50), before=msg.get("before"))
        elif kind == "telegram.thread":
            reply = await self.ask(kind, device_id, thread=msg.get("thread"), limit=msg.get("limit", 50),
                                   before=msg.get("before"))
        else:  # telegram.send: sólo `thread` y `text` (§6)
            for field in ("contact", "file"):
                if field in msg:
                    return {"type": "error", "ref": rid, "code": "invalid", "field": field,
                            "reason": "not_from_phone"}
            text = msg.get("text")
            if not isinstance(text, str) or not text.strip():
                return {"type": "error", "ref": rid, "code": "invalid", "field": "text", "reason": "empty"}
            if not isinstance(msg.get("thread"), str) or not msg["thread"]:
                return {"type": "error", "ref": rid, "code": "invalid", "field": "thread", "reason": "missing"}
            reply = await self.ask(kind, device_id, timeout_s=self.send_timeout_s, thread=msg["thread"], text=text)
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
