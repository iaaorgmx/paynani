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
import calendar
import hashlib
import json
import math
import re
import secrets
import sys
import time
from pathlib import Path

from . import roster_api
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
# Lo que la pasarela acepta del teléfono, anunciado en `welcome` (SMS_GATEWAY.md
# §2). Un tipo nuevo entra aquí y no sube PROTOCOL: la app sólo manda lo que ve en
# la lista, así que una pasarela vieja nunca recibe un tipo que rechazaría.
ACCEPTS = ("sms.in", "call.missed", "call.answered", "sms.status", "sms.unseen", "device.status", "sms.human") \
    + roster_api.TYPES  # la pantalla «Roster» (§11)
SUBPROTOCOL = "paynani-sms.v1"
HEARTBEAT_S = 30
HELLO_TIMEOUT_S = 10
MAX_OUT_PER_HOUR = 60
OFFLINE_AFTER_S = 90       # 3 x HEARTBEAT_S: SMS_GATEWAY.md §7
HEALTH_EVERY_S = 5
MAX_HEAD = 8192
MAX_PAIR_BODY = 8192
HEX64 = re.compile(r"^[0-9a-f]{64}$")
STATUSES = {"accepted", "sent", "delivered", "failed", "rejected", "expired"}
# La batería del teléfono (PaynaniApp#109, SMS_GATEWAY.md §3 y §7).
PLUGGED = {"ac", "usb", "wireless", "none"}
BATTERY_STALE_S = 20 * 60   # un dato más viejo no dispara avisos: DuraSpeed puede congelar la app (#92)
BATTERY_HYSTERESIS = 5      # battery_ok al volver a superar el aviso por estos puntos
BATTERY_SETTLE_S = 5 * 60   # sin cargar tanto tiempo antes de avisar: un cable flojo no repite avisos
BATTERY_FUTURE_S = 5 * 60   # una lectura más adelante que esto viene de un reloj mal puesto
BATTERY_PAST_S = 30 * 86400  # y una de hace más de 30 días, también

# SMS del dueño desde PaynaniApp (PaynaniApp#111, SMS_GATEWAY.md §3).
HUMAN_STATUSES = ("sent", "failed", "delivered")
HUMAN_MAX_TEXT = 1000
PAUSE_DEFAULT_MIN = 30
PAUSE_MAX_MIN = 1440


def server_version() -> str | None:
    try:
        version = (Path(__file__).resolve().parents[3] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return version or None


SERVER_VERSION = server_version()


def log(line: str) -> None:
    """Para el operador. Nunca texto de SMS, tokens ni códigos."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} sms-gateway: {line}", flush=True)


def _epoch(stamp) -> float | None:
    """Un `YYYY-MM-DDTHH:MM:SSZ` de store.now_utc() como segundos, o None."""
    try:
        return float(calendar.timegm(time.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def _when_local(epoch: float, now: float) -> str:
    """«HH:MM» si fue hoy (hora local), y «DD/MM HH:MM» si fue otro día."""
    same_day = time.localtime(epoch)[:3] == time.localtime(now)[:3]
    return time.strftime("%H:%M" if same_day else "%d/%m %H:%M", time.localtime(epoch))


def ws_device_id(ws) -> str:
    return getattr(ws, "device_id", "")


def status_id(order_id: str, status: str) -> str:
    return hashlib.sha256(f"{order_id}\n{status}".encode("utf-8")).hexdigest()


def human_status_id(local_id: str, status: str) -> str:
    return hashlib.sha256(f"{local_id}\n{status}".encode("utf-8")).hexdigest()


def iso_utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def roster_phones(path: Path) -> dict[str, str]:
    """{e164: nombre} de la columna Phone de roster.md (SRV-2, roster.py)."""
    out: dict[str, str] = {}
    try:
        for entry in roster_mod.roster_phone_entries(path):
            out.setdefault(entry["phone"], entry.get("name", ""))
    except OSError:
        return {}
    return out


class Gateway:
    def __init__(self, state_dir: Path, journal: Path, roster_path: Path, *,
                 public_url: str = "", heartbeat_s: int = HEARTBEAT_S,
                 max_out_per_hour: int = MAX_OUT_PER_HOUR,
                 offline_after_s: int = OFFLINE_AFTER_S, health_every_s: float = HEALTH_EVERY_S,
                 battery_warn_pct: int = 25, battery_critical_pct: int = 10,
                 battery_stale_s: int = BATTERY_STALE_S, roster_service=None):
        self.store = store_mod.Store(state_dir)
        self.journal = Path(journal)
        self.ledger_path = ledger.path_for(self.journal)
        self.roster_path = Path(roster_path)
        # §11: sin uno dado, sólo la cuenta del agente y sin correo al humano. sms_gateway.py
        # pasa el de la instalación, con accounts.json y send.sh.
        self.roster_service = roster_service or roster_api.RosterService(self.roster_path, state_dir, log=log)
        self.public_url = public_url.rstrip("/")
        self.heartbeat_s = heartbeat_s
        self.max_out_per_hour = max_out_per_hour
        self.offline_after_s = offline_after_s
        self.health_every_s = health_every_s
        self.battery_warn_pct = battery_warn_pct
        self.battery_critical_pct = battery_critical_pct
        self.battery_stale_s = battery_stale_s
        self.clock = time.time  # las pruebas lo cambian; lo viejo del dato se mide con este reloj
        self.conn: WebSocket | None = None
        self.last_frame = 0.0
        # La misma hora en reloj de pared, para `last_seen` (#385).
        self.last_frame_at = 0.0
        # Un proceso nuevo no tiene a nadie conectado, diga lo que diga device.json
        # de la vida anterior; y el teléfono tiene `offline_after_s` para volver
        # antes de que se diga que no está.
        self.started_at = time.time()
        self.store.touch(connected=False)
        self.clients: set = set()   # todos los writers abiertos, para cerrarlos al apagar
        self.health_task = None

    # --- HTTP -------------------------------------------------------------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        try:
            await self._handle(reader, writer)
        finally:
            self.clients.discard(writer)

    async def shutdown(self, timeout: float = 5.0) -> None:
        """
        Apagado ordenado: la vigilancia de salud se detiene primero (un proceso que se
        está apagando no debe escribir eventos), el teléfono recibe 1001 y cualquier
        otra conexión se corta. Desde Python 3.12, Server.wait_closed() espera a que se
        cierren todas las conexiones; sin esto, una conexión colgada del túnel deja
        vivo el proceso después de SIGTERM.
        """
        if self.health_task is not None:
            self.health_task.cancel()
        if self.conn is not None:
            try:
                await asyncio.wait_for(self.conn.close(1001, "la pasarela se apaga"), timeout)
            except (asyncio.TimeoutError, ConnectionError, OSError):
                pass
        for writer in list(self.clients):
            try:
                writer.transport.abort()
            except Exception:  # noqa: BLE001 -- ya cerrado
                pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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

    # --- salud del teléfono (SRV-5) ------------------------------------------
    def health_tick(self, now: float | None = None) -> str | None:
        """
        Una revisión: escribe `sms.gateway.offline` cuando el teléfono lleva
        `offline_after_s` sin conexión, y `sms.gateway.online` cuando vuelve.
        Cada uno una sola vez por apagón: la marca vive en device.json, así que
        reiniciar la pasarela no repite el aviso. Si el evento no se pudo
        escribir, la marca no se pone y se reintenta en la siguiente revisión.
        Devuelve "offline", "online" o None.
        """
        now = time.time() if now is None else now
        device = self.store.device()
        if not device:
            return None
        device_id = device.get("device_id", "")
        local = time.strftime("%H:%M:%S", time.localtime(now))
        if self.conn is not None:
            if not device.get("offline_notified"):
                return None
            began = _epoch(device.get("offline_at")) or now
            envelope = ev.gateway_health_event(kind=ev.GATEWAY_ONLINE, device_id=device_id, local_time=local,
                                               offline_for_s=max(0, now - began))
            if self._publish(envelope):
                self.store.touch(offline_notified=False, offline_at=None)
                return "online"
            return None
        if device.get("offline_notified"):
            return None
        seen = _epoch(device.get("last_seen")) or _epoch(device.get("paired_at")) or 0.0
        since = max(seen, self.started_at)
        if now - since < self.offline_after_s:
            return None
        last = time.strftime("%H:%M:%S", time.localtime(seen)) if _epoch(device.get("last_seen")) else ""
        measured = _epoch(device.get("battery_measured_at"))
        envelope = ev.gateway_health_event(kind=ev.GATEWAY_OFFLINE, device_id=device_id, local_time=local,
                                           offline_for_s=now - since, last_seen_local=last,
                                           last_battery_pct=device.get("battery_pct"),
                                           last_battery_local=_when_local(measured, now) if measured else "")
        if self._publish(envelope):
            self.store.touch(offline_notified=True, offline_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since)))
            return "offline"
        return None

    def battery_tick(self, now: float | None = None) -> str | None:
        """
        Los avisos de batería (PaynaniApp#109): con el teléfono conectado y sin
        cargar, `sms.gateway.battery_low` al bajar del aviso (`warn`) y del crítico
        (`critical`), una sola vez por nivel y por descarga; `sms.gateway.battery_ok`
        una vez, al cargar o al volver a superar el aviso por BATTERY_HYSTERESIS. La
        marca (`battery_alert_level` en device.json) sobrevive a un reinicio, como
        `offline_notified`.

        Sin dato, o con uno recibido hace más de `battery_stale_s`, no se dice nada:
        podría ser viejo. Lo viejo se mide con la hora en que llegó (reloj de la
        pasarela), no con `measured_at`, que es del teléfono. battery_low sólo sale
        si el teléfono lleva BATTERY_SETTLE_S sin cargar: un cable flojo que conecta
        y desconecta no repite warn, ok, warn… Devuelve "warn", "critical", "ok" o None.
        """
        now = self.clock() if now is None else now
        device = self.store.device()
        if not device or self.conn is None:
            return None
        pct = device.get("battery_pct")
        received = _epoch(device.get("battery_received_at"))
        if not isinstance(pct, int) or received is None or now - received > self.battery_stale_s:
            return None
        device_id = device.get("device_id", "")
        level = device.get("battery_alert_level") or ""
        charging = bool(device.get("charging"))
        local = time.strftime("%H:%M:%S", time.localtime(now))
        if level and (charging or pct >= self.battery_warn_pct + BATTERY_HYSTERESIS):
            envelope = ev.gateway_battery_event(kind=ev.GATEWAY_BATTERY_OK, device_id=device_id, local_time=local,
                                                battery_pct=pct, charging=charging)
            if self._publish(envelope):
                self.store.touch(battery_alert_level="")
                return "ok"
            return None
        if charging:
            return None
        unplugged = _epoch(device.get("battery_unplugged_at"))
        if unplugged is None or now - unplugged < BATTERY_SETTLE_S:
            return None
        if pct < self.battery_critical_pct and level != "critical":
            new = "critical"
        elif pct < self.battery_warn_pct and not level:
            new = "warn"
        else:
            return None
        envelope = ev.gateway_battery_event(kind=ev.GATEWAY_BATTERY_LOW, device_id=device_id, local_time=local,
                                            battery_pct=pct, charging=False, level=new)
        if self._publish(envelope):
            self.store.touch(battery_alert_level=new)
            return new
        return None

    def _publish(self, envelope: dict) -> bool:
        try:
            ev.append(self.journal, envelope)
            ledger.observed(self.ledger_path, envelope)
        except (OSError, ValueError) as exc:
            log(f"no se pudo escribir el evento de salud ({exc}); se reintenta")
            return False
        print(envelope["notification_text"], flush=True)
        return True

    async def health_loop(self) -> None:
        while True:
            await asyncio.sleep(self.health_every_s)
            try:
                self.health_tick()
            except Exception as exc:  # noqa: BLE001 -- la vigilancia no debe morir por un error suelto
                log(f"revisión de salud falló: {exc}")
            try:
                self.battery_tick()
            except Exception as exc:  # noqa: BLE001 -- un error de la batería no frena la de conexión
                log(f"revisión de batería falló: {exc}")

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
        self.last_frame_at = time.time()

    def _mark_seen(self, **fields) -> None:
        """
        `last_seen` es la hora del último frame del teléfono, no la de ahora: el
        watchdog y el cierre corren aunque el teléfono ya no hable, y health_tick
        cuenta `offline_after_s` desde aquí (#385).
        """
        seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_frame_at)) if self.last_frame_at \
            else store_mod.now_utc()
        self.store.touch(last_seen=seen, **fields)

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
        ws.token_sha256 = device.get("token_sha256", "")
        ws.device_id = device_id
        self._saw_frame()
        self.store.touch(connected=True, last_seen=store_mod.now_utc(),
                         app_version=str(hello.get("app_version", ""))[:40],
                         sims=hello.get("sims") if isinstance(hello.get("sims"), list) else device.get("sims", []))
        if isinstance(hello.get("device_status"), dict):
            # La última lectura de batería viene en el saludo (PaynaniApp#109). Una
            # lectura mala nunca impide el welcome.
            try:
                if self._device_status_problem(hello["device_status"]) is None:
                    self._store_device_status(hello["device_status"])
            except Exception as exc:  # noqa: BLE001
                log(f"hello.device_status no se guardó: {exc}")
        log(f"teléfono conectado: {device_id}")
        allowed = sorted(roster_phones(self.roster_path))
        welcome = {"type": "welcome", "protocol": PROTOCOL, "server_time": store_mod.now_utc(),
                   "heartbeat_s": self.heartbeat_s, "allowed": allowed,
                   "max_out_per_hour": self.max_out_per_hour, "accepts": list(ACCEPTS)}
        if SERVER_VERSION:
            welcome["server_version"] = SERVER_VERSION
        await self._send(ws, welcome)
        tasks = [asyncio.create_task(self._pump_outbox(ws)),
                 asyncio.create_task(self._watch_roster(ws, allowed)),
                 asyncio.create_task(self._watchdog(ws))]
        try:
            while True:
                raw = await ws.recv()
                if not self._still_paired(ws, device_id):
                    await self._revoked(ws, device_id)
                    break
                await self._dispatch(ws, device_id, raw)
        except ConnectionClosed as exc:
            log(f"teléfono desconectado: {device_id} ({exc.code})")
        finally:
            for t in tasks:
                t.cancel()
            if self.conn is ws:
                self.conn = None
                if self._still_paired(ws, device_id):
                    self._mark_seen(connected=False)

    def _still_paired(self, ws: WebSocket, device_id: str) -> bool:
        """
        ¿El teléfono de esta conexión sigue emparejado con el mismo token? `sms revoke`
        (o el botón de la página) borra device.json desde otro proceso, y un
        emparejamiento nuevo lo reemplaza: en los dos casos esta conexión ya no vale.
        """
        device = self.store.device()
        return bool(device) and device.get("device_id") == device_id \
            and device.get("token_sha256", "") == getattr(ws, "token_sha256", None)

    async def _revoked(self, ws: WebSocket, device_id: str) -> None:
        log(f"teléfono revocado: {device_id}; se cierra su conexión (4401)")
        await ws.close(4401, "token revocado")

    async def _watchdog(self, ws: WebSocket) -> None:
        """Sin ningún frame en 3 × heartbeat, la conexión se da por muerta."""
        while not ws.closed:
            await asyncio.sleep(max(1, self.heartbeat_s // 3))
            if not self._still_paired(ws, ws_device_id(ws)):
                await self._revoked(ws, ws_device_id(ws))
                return
            if time.monotonic() - self.last_frame > 3 * self.heartbeat_s:
                log("sin latido del teléfono; se cierra la conexión")
                await ws.close(1001, "sin latido")
                return
            self._mark_seen()

    async def _watch_roster(self, ws: WebSocket, allowed: list) -> None:
        # Lo último que se le mandó al teléfono, en la conexión: `_roster` también lo
        # manda después de un cambio desde la app, y así no sale dos veces.
        ws.allowed_sent = allowed
        while not ws.closed:
            await asyncio.sleep(10)
            current = sorted(roster_phones(self.roster_path))
            if current != getattr(ws, "allowed_sent", None):
                ws.allowed_sent = current
                await self._send(ws, {"type": "allowed", "allowed": current})

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
        elif kind == ev.SMS_UNSEEN:
            await self._sms_unseen(ws, device_id, msg)
        elif kind == "device.status":
            await self._device_status(ws, msg)
        elif kind == "sms.human":
            await self._sms_human(ws, device_id, msg)
        elif kind in roster_api.TYPES:
            await self._roster(ws, device_id, msg)
        elif kind == "hello":
            await self._error(ws, "unknown_type", detail="hello sólo al conectar")
        else:
            await self._error(ws, "unknown_type", ref=str(msg.get("id", ""))[:80],
                              detail=f"type {str(kind)[:40]!r} no existe")

    async def _roster(self, ws: WebSocket, device_id: str, msg: dict) -> None:
        """
        Un pedido de la pantalla «Roster» (§11). Corre en un hilo: espera el bloqueo
        del roster, y un `paynani roster add` en la terminal no detiene la conexión.
        Si cambió un teléfono del roster del agente, el `allowed` nuevo sale enseguida,
        sin esperar al vigilante del roster.
        """
        response = await asyncio.to_thread(self.roster_service.handle, msg, device_id)
        await self._send(ws, response)
        if response.get("type") == "result" and msg.get("type") in roster_api.WRITES \
                and msg.get("account") is None:
            current = sorted(roster_phones(self.roster_path))
            if current != getattr(ws, "allowed_sent", None):
                ws.allowed_sent = current
                await self._send(ws, {"type": "allowed", "allowed": current})

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

    async def _sms_unseen(self, ws, device_id, msg) -> None:
        uid, app, posted = str(msg.get("id", "")), msg.get("app"), msg.get("posted_at")
        if not HEX64.match(uid) or not isinstance(app, str) or not app or not isinstance(posted, str) or not posted:
            await self._error(ws, "missing_field", ref=uid[:80], detail="sms.unseen necesita id, app y posted_at")
            await self._send(ws, {"type": "ack", "id": uid, "result": "rejected"})
            return
        title = msg.get("title") if isinstance(msg.get("title"), str) else ""
        envelope = ev.unseen_event(device_id=device_id, message_id=uid, app=app, posted_at=posted,
                                   title=title, local_time=time.strftime("%H:%M:%S"))
        try:
            result = self._journal(uid, envelope, {"type": ev.SMS_UNSEEN, "app": envelope["app"],
                                                   "posted_at": posted, "title": envelope["title"],
                                                   "sim": msg.get("sim")})
        except (OSError, ValueError) as exc:
            log(f"no se pudo escribir el evento ({exc}); no se manda ack, el teléfono reintentará")
            return
        await self._send(ws, {"type": "ack", "id": uid, "result": result, "event_id": envelope["event_id"]})

    def _device_status_problem(self, msg: dict) -> str | None:
        """
        Por qué la lectura no sirve, o None si sirve. Además de la forma, `measured_at`
        tiene que caer entre hace 30 días y dentro de 5 minutos: una lectura del
        futuro dejaría todas las reales como `duplicate` (y sin avisos), y una enorme
        rompe `gmtime`.
        """
        pct, charging, measured = msg.get("battery_pct"), msg.get("charging"), msg.get("measured_at")
        if not (isinstance(pct, int) and not isinstance(pct, bool) and 0 <= pct <= 100
                and isinstance(charging, bool)
                and isinstance(measured, int) and not isinstance(measured, bool) and measured > 0):
            return "device.status necesita id, battery_pct, charging y measured_at"
        skew = measured / 1000 - self.clock()
        if skew > BATTERY_FUTURE_S or skew < -BATTERY_PAST_S:
            return f"measured_at fuera de rango: {int(skew)} s respecto a la pasarela (¿reloj del teléfono?)"
        return None

    def _store_device_status(self, msg: dict) -> bool:
        """
        Guarda la lectura en device.json si es más nueva que la guardada: la cola
        del teléfono puede entregar una lectura vieja después de una nueva. Quien
        llama ya la validó con _device_status_problem. Devuelve si la guardó.
        """
        device = self.store.device() or {}
        now = self.clock()
        measured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(msg["measured_at"] / 1000))
        previous = device.get("battery_measured_at")
        if previous and previous >= measured_at:
            return False
        plugged = msg.get("plugged") if msg.get("plugged") in PLUGGED else "none"
        temp = msg.get("battery_temp_c")
        if not (isinstance(temp, (int, float)) and not isinstance(temp, bool)
                and math.isfinite(temp) and -40 <= temp <= 100):
            temp = None
        received_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        # Desde cuándo no carga, con el reloj de la pasarela (BATTERY_SETTLE_S).
        if msg["charging"]:
            unplugged_at = None
        elif device.get("charging") is False and device.get("battery_unplugged_at"):
            unplugged_at = device["battery_unplugged_at"]
        else:
            unplugged_at = received_at
        self.store.touch(battery_pct=msg["battery_pct"], charging=msg["charging"], plugged=plugged,
                         battery_temp_c=float(temp) if temp is not None else None,
                         battery_measured_at=measured_at, battery_received_at=received_at,
                         battery_unplugged_at=unplugged_at)
        return True

    async def _device_status(self, ws, msg) -> None:
        sid = str(msg.get("id", ""))
        problem = "device.status necesita un id de 64 hex" if not HEX64.match(sid) else self._device_status_problem(msg)
        if problem:
            if "measured_at fuera de rango" in problem:
                log(f"device.status rechazado: {problem}")
            await self._error(ws, "missing_field", ref=sid[:80], detail=problem)
            await self._send(ws, {"type": "ack", "id": sid, "result": "rejected"})
            return
        try:
            fresh = self._store_device_status(msg)
        except OSError as exc:
            log(f"no se pudo guardar la batería ({exc}); sin ack")
            return
        await self._send(ws, {"type": "ack", "id": sid, "result": "stored" if fresh else "duplicate"})

    def _sms_human_problem(self, msg: dict) -> str | None:
        """Por qué el sms.human no sirve, o None (SMS_GATEWAY.md §3)."""
        hid, local_id, status = str(msg.get("id", "")), msg.get("local_id"), msg.get("status")
        to, text, at = msg.get("to"), msg.get("text"), msg.get("at")
        pause = msg.get("agent_pause_min", PAUSE_DEFAULT_MIN)
        if not (HEX64.match(hid) and store_mod.valid_human_id(local_id) and status in HUMAN_STATUSES
                and isinstance(to, dict) and isinstance(to.get("raw"), str) and to["raw"].strip()
                and isinstance(text, str) and text.strip()
                and isinstance(at, int) and not isinstance(at, bool) and at > 0
                and isinstance(pause, int) and not isinstance(pause, bool) and 0 <= pause <= PAUSE_MAX_MIN):
            return "sms.human necesita id, local_id, to.raw, text, status, at y agent_pause_min de 0 a 1440"
        if hid != human_status_id(local_id, status):
            return "sms.human: id no es sha256(local_id + \"\\n\" + status)"
        if len(text) > HUMAN_MAX_TEXT:
            return f"sms.human: text de más de {HUMAN_MAX_TEXT} caracteres"
        skew = at / 1000 - self.clock()
        if skew > BATTERY_FUTURE_S or skew < -BATTERY_PAST_S:
            return f"sms.human: at fuera de rango, {int(skew)} s respecto a la pasarela (¿reloj del teléfono?)"
        return None

    async def _sms_human(self, ws, device_id, msg) -> None:
        """
        Un SMS que el dueño mandó desde PaynaniApp (PaynaniApp#111). El evento
        sms.human_sent se escribe una vez por envío, con el primer `sent` o
        `failed`; `delivered` y cualquier estado repetido sólo van a human.jsonl.
        """
        hid = str(msg.get("id", ""))
        problem = self._sms_human_problem(msg)
        if problem:
            if "fuera de rango" in problem:
                log(problem)
            await self._error(ws, "missing_field", ref=hid[:80], detail=problem)
            await self._send(ws, {"type": "ack", "id": hid, "result": "rejected"})
            return
        local_id, status, text = msg["local_id"], msg["status"], msg["text"]
        raw, e164, name, in_roster = self._who(msg["to"])
        at_s = msg["at"] / 1000
        pause = msg.get("agent_pause_min", PAUSE_DEFAULT_MIN)
        pause_until = iso_utc(at_s + pause * 60) if status == "sent" and pause > 0 and e164 else None
        reply = msg.get("in_reply_to")
        replied = self.store.inbox(reply) if isinstance(reply, str) and HEX64.match(reply) else None
        in_reply_to = replied.get("event_id") if replied and replied.get("type") == "sms.in" else None
        record = {"id": hid, "local_id": local_id, "to": e164 or raw, "status": status, "at": iso_utc(at_s),
                  "agent_pause_min": pause}
        for key in ("parts", "error"):
            if key in msg:
                record[key] = msg[key]
        if in_reply_to:
            record["in_reply_to"] = in_reply_to
        if pause_until:
            record["pause_until"] = pause_until
        journaled = any(r.get("local_id") == local_id and r.get("event_id")
                        for r in self.store.human_records())
        result = "duplicate"
        try:
            if status in ("sent", "failed") and (not journaled or self.store.inbox(hid)):
                envelope = ev.human_sent_event(
                    device_id=device_id, message_id=hid, e164=e164, raw_to=raw, recipient_name=name,
                    text=text, status=status, parts=msg.get("parts", 1), at=iso_utc(at_s),
                    roster_match=in_roster, local_time=time.strftime("%H:%M:%S"),
                    in_reply_to=in_reply_to, agent_pause_min=pause, pause_until=pause_until,
                    error=msg.get("error"))
                result = self._journal(hid, envelope, {
                    "type": "sms.human", "local_id": local_id, "to_raw": raw, "to_e164": e164,
                    "text": text, "status": status, "at": iso_utc(at_s), "sim": msg.get("sim")})
                record["event_id"] = envelope["event_id"]
            if self.store.append_human(record):
                result = "stored"
        except (OSError, ValueError) as exc:
            log(f"no se pudo guardar el sms.human ({exc}); sin ack, el teléfono reintentará")
            return
        ack = {"type": "ack", "id": hid, "result": result}
        if record.get("event_id"):
            ack["event_id"] = record["event_id"]
        await self._send(ws, ack)

    async def _sms_status(self, ws, msg) -> None:
        sid, oid, status = str(msg.get("id", "")), str(msg.get("order_id", "")), msg.get("status")
        if not HEX64.match(sid) or not store_mod.valid_order_id(oid) or status not in STATUSES:
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
    gateway.health_task = asyncio.ensure_future(gateway.health_loop())
    log(f"escuchando en {host}:{port}")
    return server
