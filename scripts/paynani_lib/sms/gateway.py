"""
La pasarela SMS: HTTP para emparejar y WebSocket para el teléfono
(SMS_GATEWAY.md). Un proceso de larga vida, como idle_listener.py para IMAP.

Escucha sólo en 127.0.0.1: el teléfono llega por el túnel (DEC-2), que pone el
TLS. Escribe cada SMS y llamada en el diario de eventos (events.jsonl) con el
mismo sobre que el correo, y manda `ack` sólo después de escribir.

Sólo biblioteca estándar (asyncio).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import sys
import time
from pathlib import Path

from . import store as store_mod
from .websocket import ConnectionClosed, WebSocket, accept_key

_HARNESS = Path(__file__).resolve().parents[3] / "harness"
_SCRIPTS = Path(__file__).resolve().parents[2]
for _p in (str(_HARNESS), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import event as ev  # noqa: E402
import ledger  # noqa: E402
import phone  # noqa: E402
import roster as roster_mod  # noqa: E402

PROTOCOL = 1
SUBPROTOCOL = "paynani-sms.v1"
HEARTBEAT_S = 30
HELLO_TIMEOUT_S = 10
MAX_OUT_PER_HOUR = 60
MAX_HEAD = 8192
MAX_PAIR_BODY = 8192
HEX64 = re.compile(r"^[0-9a-f]{64}$")
STATUSES = {"accepted", "sent", "delivered", "failed", "rejected", "expired"}


def log(line: str) -> None:
    """Para el operador. Nunca texto de SMS, tokens ni códigos."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} sms-gateway: {line}", flush=True)


def status_id(order_id: str, status: str) -> str:
    return hashlib.sha256(f"{order_id}\n{status}".encode("utf-8")).hexdigest()


def roster_phones(path: Path) -> dict[str, str]:
    """{e164: nombre}. Usa roster.roster_phones (SRV-2) si existe."""
    func = getattr(roster_mod, "roster_phones", None)
    if func is not None:
        return dict(func(path))
    # Respaldo hasta SRV-2: la columna Phone de las filas que roster_entries lee.
    out: dict[str, str] = {}
    try:
        entries = roster_mod.roster_entries(path)
    except OSError:
        return out
    for entry in entries:
        cols = {k.lower(): v for k, v in (entry.get("columns") or {}).items()}
        for raw in phone.split_cell(cols.get("phone", "")):
            e164 = phone.to_e164(raw)
            if e164:
                out.setdefault(e164, entry.get("name", ""))
    return out


class Gateway:
    def __init__(self, state_dir: Path, journal: Path, roster_path: Path, *,
                 public_url: str = "", heartbeat_s: int = HEARTBEAT_S,
                 max_out_per_hour: int = MAX_OUT_PER_HOUR):
        self.store = store_mod.Store(state_dir)
        self.journal = Path(journal)
        self.ledger_path = ledger.path_for(self.journal)
        self.roster_path = Path(roster_path)
        self.public_url = public_url.rstrip("/")
        self.heartbeat_s = heartbeat_s
        self.max_out_per_hour = max_out_per_hour
        self.conn: WebSocket | None = None
        self.last_frame = 0.0

    # --- HTTP -------------------------------------------------------------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            writer.close()
            return
        if len(head) > MAX_HEAD:
            await self._respond(writer, 431, {"error": "headers_too_large"})
            return
        try:
            request_line, *lines = head.decode("latin-1").split("\r\n")
            method, target, _ = request_line.split(" ", 2)
        except ValueError:
            await self._respond(writer, 400, {"error": "bad_request"})
            return
        headers = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        path = target.split("?", 1)[0]
        if method == "POST" and path == "/sms/pair":
            await self._pair(reader, writer, headers)
        elif method == "GET" and path == "/sms/ws":
            await self._websocket(reader, writer, headers)
        elif method == "GET" and path == "/sms/health":
            await self._respond(writer, 200, {"ok": True, "phone_connected": self.conn is not None})
        else:
            await self._respond(writer, 404, {"error": "not_found"})

    async def _respond(self, writer, status: int, body: dict) -> None:
        reason = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized",
                  404: "Not Found", 409: "Conflict", 410: "Gone", 413: "Payload Too Large",
                  426: "Upgrade Required", 429: "Too Many Requests",
                  431: "Request Header Fields Too Large"}.get(status, "Error")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json; charset=utf-8\r\n"
                     f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode("latin-1") + data)
        try:
            await writer.drain()
        finally:
            writer.close()

    def _ws_url(self, headers: dict) -> str:
        if self.public_url:
            base = self.public_url
        else:
            proto = "https" if headers.get("x-forwarded-proto") == "https" else "http"
            base = f"{proto}://{headers.get('host', '127.0.0.1')}"
        return base.replace("https://", "wss://").replace("http://", "ws://") + "/sms/ws"

    async def _pair(self, reader, writer, headers) -> None:
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_PAIR_BODY:
            await self._respond(writer, 413 if length > MAX_PAIR_BODY else 400, {"error": "bad_request"})
            return
        try:
            body = json.loads((await asyncio.wait_for(reader.readexactly(length), 10)).decode("utf-8"))
            code = str(body["code"])
        except Exception:
            await self._respond(writer, 400, {"error": "bad_request"})
            return
        if self.store.device():
            # DEC-3: un teléfono. Emparejar otro pide revocar antes el actual.
            await self._respond(writer, 409, {"error": "device_exists"})
            return
        result = self.store.redeem(code)
        if result == "blocked":
            log("emparejamiento bloqueado por demasiados códigos equivocados; genera uno nuevo")
            await self._respond(writer, 429, {"error": "too_many_attempts"})
            return
        if result != "ok":
            await self._respond(writer, 410, {"error": "code_expired"})
            return
        device_id = "d_" + secrets.token_hex(3)
        token = secrets.token_urlsafe(32)
        dev = body.get("device") or {}
        self.store.save_device({
            "device_id": device_id,
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "paired_at": store_mod.now_utc(),
            "model": str(dev.get("model", ""))[:80],
            "android": str(dev.get("android", ""))[:20],
            "app_version": str(dev.get("app_version", ""))[:40],
            "sims": body.get("sims") if isinstance(body.get("sims"), list) else [],
            "last_seen": None,
            "connected": False,
        })
        log(f"teléfono emparejado: {device_id}")
        await self._respond(writer, 201, {"device_id": device_id, "token": token, "ws": self._ws_url(headers)})

    # --- WebSocket ----------------------------------------------------------
    async def _websocket(self, reader, writer, headers) -> None:
        if headers.get("upgrade", "").lower() != "websocket" or "sec-websocket-key" not in headers:
            await self._respond(writer, 426, {"error": "upgrade_required"})
            return
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        device = self.store.device_for_token(token)
        if not device:
            await self._respond(writer, 401, {"error": "unauthorized"})
            return
        offered = [p.strip() for p in headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        lines = ["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Accept: {accept_key(headers['sec-websocket-key'])}"]
        if SUBPROTOCOL in offered:
            lines.append(f"Sec-WebSocket-Protocol: {SUBPROTOCOL}")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        await writer.drain()
        ws = WebSocket(reader, writer, on_frame=lambda _op: self._saw_frame())
        if self.conn is not None:
            old, self.conn = self.conn, None
            await old.close(4409, "reemplazada por otra conexión del mismo teléfono")
        await self._session(ws, device)

    def _saw_frame(self) -> None:
        self.last_frame = time.monotonic()

    async def _send(self, ws: WebSocket, obj: dict) -> None:
        await ws.send_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

    async def _error(self, ws, code: str, ref: str = "", detail: str = "") -> None:
        msg = {"type": "error", "code": code}
        if ref:
            msg["ref"] = ref
        if detail:
            msg["detail"] = detail
        await self._send(ws, msg)

    async def _session(self, ws: WebSocket, device: dict) -> None:
        device_id = device["device_id"]
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S))
        except (asyncio.TimeoutError, ConnectionClosed, ValueError):
            await ws.close(4400, "se esperaba hello")
            return
        if hello.get("type") != "hello" or hello.get("protocol") != PROTOCOL:
            await self._error(ws, "unsupported_protocol", detail=f"esta pasarela habla el protocolo {PROTOCOL}")
            await ws.close(4400, "protocolo")
            return
        if hello.get("device_id") not in (None, device_id):
            await ws.close(4401, "device_id no corresponde al token")
            return
        self.conn = ws
        self._saw_frame()
        self.store.touch(connected=True, last_seen=store_mod.now_utc(),
                         app_version=str(hello.get("app_version", ""))[:40],
                         sims=hello.get("sims") if isinstance(hello.get("sims"), list) else device.get("sims", []))
        log(f"teléfono conectado: {device_id}")
        allowed = sorted(roster_phones(self.roster_path))
        await self._send(ws, {"type": "welcome", "protocol": PROTOCOL, "server_time": store_mod.now_utc(),
                              "heartbeat_s": self.heartbeat_s, "allowed": allowed,
                              "max_out_per_hour": self.max_out_per_hour})
        tasks = [asyncio.create_task(self._pump_outbox(ws)),
                 asyncio.create_task(self._watch_roster(ws, allowed)),
                 asyncio.create_task(self._watchdog(ws))]
        try:
            while True:
                raw = await ws.recv()
                await self._dispatch(ws, device_id, raw)
        except ConnectionClosed as exc:
            log(f"teléfono desconectado: {device_id} ({exc.code})")
        finally:
            for t in tasks:
                t.cancel()
            if self.conn is ws:
                self.conn = None
                self.store.touch(connected=False, last_seen=store_mod.now_utc())

    async def _watchdog(self, ws: WebSocket) -> None:
        """Sin ningún frame en 3 × heartbeat, la conexión se da por muerta."""
        while not ws.closed:
            await asyncio.sleep(max(1, self.heartbeat_s // 3))
            if time.monotonic() - self.last_frame > 3 * self.heartbeat_s:
                log("sin latido del teléfono; se cierra la conexión")
                await ws.close(1001, "sin latido")
                return
            self.store.touch(last_seen=store_mod.now_utc())

    async def _watch_roster(self, ws: WebSocket, allowed: list) -> None:
        while not ws.closed:
            await asyncio.sleep(10)
            current = sorted(roster_phones(self.roster_path))
            if current != allowed:
                allowed = current
                await self._send(ws, {"type": "allowed", "allowed": allowed})

    async def _pump_outbox(self, ws: WebSocket) -> None:
        pushed: set[str] = set()
        while not ws.closed:
            for order in self.store.pending_orders():
                oid = order.get("id", "")
                if not oid or oid in pushed:
                    continue
                if order.get("expires_at", "") and order["expires_at"] < store_mod.now_utc():
                    self.store.append_status({"id": status_id(oid, "expired"), "order_id": oid,
                                              "status": "expired", "at": store_mod.now_utc()})
                    self.store.finish_order(oid)
                    log(f"orden {oid} vencida sin enviarse")
                    continue
                msg = {"type": "sms.out", "id": oid, "to": order["to"], "text": order["text"],
                       "expires_at": order.get("expires_at", "")}
                if order.get("sim_slot") is not None:
                    msg["sim_slot"] = order["sim_slot"]
                await self._send(ws, msg)
                pushed.add(oid)
            await asyncio.sleep(1)

    # --- mensajes del teléfono ---------------------------------------------
    async def _dispatch(self, ws: WebSocket, device_id: str, raw: str) -> None:
        try:
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                raise ValueError
        except ValueError:
            await self._error(ws, "bad_json")
            return
        kind = msg.get("type")
        if kind == "sms.in":
            await self._sms_in(ws, device_id, msg)
        elif kind in (ev.CALL_MISSED, ev.CALL_ANSWERED):
            await self._call(ws, device_id, msg)
        elif kind == "sms.status":
            await self._sms_status(ws, msg)
        elif kind == "hello":
            await self._error(ws, "unknown_type", detail="hello sólo al conectar")
        else:
            await self._error(ws, "unknown_type", ref=str(msg.get("id", ""))[:80],
                              detail=f"type {str(kind)[:40]!r} no existe")

    def _region(self) -> str | None:
        """El país de la SIM del teléfono emparejado (SMS_GATEWAY.md), o None."""
        device = self.store.device() or {}
        for sim in device.get("sims") or []:
            country = str((sim or {}).get("country") or "").strip().upper()
            if re.fullmatch(r"[A-Z]{2}", country):
                return country
        return None

    def _who(self, raw_from) -> tuple[str, str | None, str, bool]:
        raw = str((raw_from or {}).get("raw", "")) if isinstance(raw_from, dict) else ""
        e164 = phone.to_e164(raw, self._region())
        phones = roster_phones(self.roster_path)
        name = phones.get(e164, "") if e164 else ""
        return raw, e164, name, bool(e164 and e164 in phones)

    def _journal(self, message_id: str, envelope: dict, extra: dict) -> str:
        """
        Escribe el evento una sola vez, aunque el teléfono reenvíe.

        Primero se guarda el registro con journaled=False, luego el evento, y
        al final se marca journaled=True. Si se cae en medio, el reenvío vuelve
        a escribir el evento; si ya estaba marcado, es duplicado.
        """
        existing = self.store.inbox(message_id)
        if existing and existing.get("journaled"):
            return "duplicate"
        data = dict(extra, event_id=envelope["event_id"], journaled=False)
        self.store.save_inbox(message_id, data)
        ev.append(self.journal, envelope)
        ledger.observed(self.ledger_path, envelope)
        data["journaled"] = True
        self.store.save_inbox(message_id, data)
        print(envelope["notification_text"], flush=True)
        return "stored"

    async def _sms_in(self, ws, device_id, msg) -> None:
        mid = str(msg.get("id", ""))
        text = msg.get("text")
        if not HEX64.match(mid) or not isinstance(text, str) or not isinstance(msg.get("from"), dict):
            await self._error(ws, "missing_field", ref=mid[:80], detail="sms.in necesita id, from y text")
            await self._send(ws, {"type": "ack", "id": mid, "result": "rejected"})
            return
        raw, e164, name, in_roster = self._who(msg["from"])
        envelope = ev.sms_event(device_id=device_id, message_id=mid, e164=e164, raw_sender=raw,
                                sender_name=name, text=text, sent_at=str(msg.get("sent_at", "")),
                                roster_match=in_roster, local_time=time.strftime("%H:%M:%S"))
        try:
            result = self._journal(mid, envelope, {
                "type": "sms.in", "from_raw": raw, "from_e164": e164, "text": text,
                "sent_at": msg.get("sent_at", ""), "received_at": msg.get("received_at", ""),
                "sim": msg.get("sim"), "parts": msg.get("parts", 1)})
        except (OSError, ValueError) as exc:
            log(f"no se pudo escribir el evento ({exc}); no se manda ack, el teléfono reintentará")
            return
        await self._send(ws, {"type": "ack", "id": mid, "result": result,
                              "event_id": envelope["event_id"]})

    async def _call(self, ws, device_id, msg) -> None:
        cid = str(msg.get("id", ""))
        kind = msg["type"]
        if not HEX64.match(cid) or not isinstance(msg.get("from"), dict):
            await self._error(ws, "missing_field", ref=cid[:80], detail=f"{kind} necesita id y from")
            await self._send(ws, {"type": "ack", "id": cid, "result": "rejected"})
            return
        raw, e164, name, in_roster = self._who(msg["from"])
        duration = msg.get("duration_s") if kind == ev.CALL_ANSWERED else None
        if duration is not None and not isinstance(duration, int):
            duration = None
        envelope = ev.call_event(kind=kind, device_id=device_id, call_id=cid, e164=e164,
                                 raw_caller=raw, caller_name=name,
                                 started_at=str(msg.get("started_at", "")),
                                 roster_match=in_roster, local_time=time.strftime("%H:%M:%S"),
                                 duration_s=duration)
        try:
            result = self._journal(cid, envelope, {"type": kind, "from_raw": raw, "from_e164": e164,
                                                   "started_at": msg.get("started_at", ""),
                                                   "duration_s": duration})
        except (OSError, ValueError) as exc:
            log(f"no se pudo escribir el evento ({exc}); no se manda ack, el teléfono reintentará")
            return
        await self._send(ws, {"type": "ack", "id": cid, "result": result, "event_id": envelope["event_id"]})

    async def _sms_status(self, ws, msg) -> None:
        sid, oid, status = str(msg.get("id", "")), str(msg.get("order_id", "")), msg.get("status")
        if not HEX64.match(sid) or not oid or status not in STATUSES:
            await self._error(ws, "missing_field", ref=sid[:80], detail="sms.status necesita id, order_id y status")
            await self._send(ws, {"type": "ack", "id": sid, "result": "rejected"})
            return
        record = {"id": sid, "order_id": oid, "status": status, "at": str(msg.get("at", "")) or store_mod.now_utc()}
        for key in ("error", "parts"):
            if key in msg:
                record[key] = msg[key]
        try:
            fresh = self.store.append_status(record)
        except OSError as exc:
            log(f"no se pudo guardar el estado de la orden ({exc}); sin ack")
            return
        # Cualquier estado dice que la orden ya está en manos del teléfono: sale
        # del outbox para no reenviarse. Los siguientes estados llegan igual.
        self.store.finish_order(oid)
        if fresh:
            log(f"orden {oid}: {status}")
        await self._send(ws, {"type": "ack", "id": sid, "result": "stored" if fresh else "duplicate"})


async def serve(gateway: Gateway, host: str, port: int):
    server = await asyncio.start_server(gateway.handle, host, port, limit=MAX_HEAD)
    log(f"escuchando en {host}:{port}")
    return server
