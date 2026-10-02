"""
WebSocket (RFC 6455) sobre asyncio, sólo con la biblioteca estándar.

Lo justo para la pasarela SMS: frames de texto, ping/pong, cierre con código y
mensajes fragmentados. Sin extensiones (permessage-deflate) ni binarios: el
protocolo de SMS_GATEWAY.md es JSON en frames de texto.

Incluye un cliente mínimo, que usan las pruebas y la simulación de la app.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA

MAX_MESSAGE = 256 * 1024  # un SMS cabe de sobra; esto sólo protege la memoria


class ConnectionClosed(Exception):
    def __init__(self, code=1006, reason=""):
        super().__init__(f"{code} {reason}".strip())
        self.code = code
        self.reason = reason


class ProtocolError(Exception):
    pass


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")


class WebSocket:
    """Una conexión ya negociada. `client=True` enmascara lo que envía."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *,
                 client: bool = False, on_frame=None):
        self.reader = reader
        self.writer = writer
        self.client = client
        self.closed = False
        self.close_code = None
        self._send_lock = asyncio.Lock()
        # Se llama con cada frame recibido (incluidos ping y pong): la pasarela lo
        # usa para saber cuándo vio al teléfono por última vez.
        self.on_frame = on_frame

    async def _send_frame(self, opcode: int, payload: bytes = b"") -> None:
        if self.closed and opcode != OP_CLOSE:
            raise ConnectionClosed(self.close_code or 1006)
        header = bytes([0x80 | opcode])
        mask_bit = 0x80 if self.client else 0
        n = len(payload)
        if n < 126:
            header += bytes([mask_bit | n])
        elif n < 65536:
            header += bytes([mask_bit | 126]) + struct.pack("!H", n)
        else:
            header += bytes([mask_bit | 127]) + struct.pack("!Q", n)
        if self.client:
            mask = os.urandom(4)
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            header += mask
        async with self._send_lock:
            self.writer.write(header + payload)
            await self.writer.drain()

    async def send_text(self, text: str) -> None:
        await self._send_frame(OP_TEXT, text.encode("utf-8"))

    async def ping(self, data: bytes = b"") -> None:
        await self._send_frame(OP_PING, data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        self.close_code = code
        try:
            await self._send_frame(OP_CLOSE, struct.pack("!H", code) + reason.encode("utf-8")[:120])
        except (ConnectionError, RuntimeError, ConnectionClosed):
            pass
        try:
            self.writer.close()
        except Exception:
            pass

    async def _read_frame(self):
        head = await self.reader.readexactly(2)
        fin = bool(head[0] & 0x80)
        if head[0] & 0x70:
            raise ProtocolError("bits RSV sin extensión negociada")
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack("!H", await self.reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", await self.reader.readexactly(8))[0]
        if n > MAX_MESSAGE:
            raise ProtocolError("frame demasiado grande")
        if not self.client and not masked:
            raise ProtocolError("el cliente debe enmascarar sus frames")
        mask = await self.reader.readexactly(4) if masked else b""
        payload = await self.reader.readexactly(n) if n else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if self.on_frame:
            self.on_frame(opcode)
        return fin, opcode, payload

    async def recv(self) -> str:
        """El siguiente mensaje de texto. Contesta ping y cierre por su cuenta."""
        parts: list[bytes] = []
        total = 0
        while True:
            try:
                fin, opcode, payload = await self._read_frame()
            except (asyncio.IncompleteReadError, ConnectionError) as exc:
                self.closed = True
                raise ConnectionClosed(1006, "conexión cortada") from exc
            except ProtocolError as exc:
                await self.close(1002, str(exc))
                raise ConnectionClosed(1002, str(exc)) from exc
            if opcode == OP_PING:
                await self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                reason = payload[2:].decode("utf-8", "replace")
                if not self.closed:
                    await self.close(code if code not in (1005, 1006) else 1000)
                self.closed = True
                raise ConnectionClosed(code, reason)
            if opcode == OP_BINARY:
                await self.close(1003, "sólo texto")
                raise ConnectionClosed(1003, "sólo texto")
            if opcode in (OP_TEXT, OP_CONT):
                if opcode == OP_TEXT and parts:
                    await self.close(1002, "frame de texto dentro de un mensaje fragmentado")
                    raise ConnectionClosed(1002)
                parts.append(payload)
                total += len(payload)
                if total > MAX_MESSAGE:
                    await self.close(1009, "mensaje demasiado grande")
                    raise ConnectionClosed(1009)
                if fin:
                    try:
                        return b"".join(parts).decode("utf-8")
                    except UnicodeDecodeError as exc:
                        await self.close(1007, "texto que no es UTF-8")
                        raise ConnectionClosed(1007) from exc
                continue
            await self.close(1002, "opcode desconocido")
            raise ConnectionClosed(1002, "opcode desconocido")


async def connect(host: str, port: int, path: str, *, headers: dict | None = None,
                  protocol: str | None = None, ssl=None):
    """Cliente mínimo. Devuelve (WebSocket, código HTTP) o lanza si no hubo 101."""
    reader, writer = await asyncio.open_connection(host, port, ssl=ssl)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}", "Upgrade: websocket",
             "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    if protocol:
        lines.append(f"Sec-WebSocket-Protocol: {protocol}")
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {value}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
    await writer.drain()
    raw = await reader.readuntil(b"\r\n\r\n")
    status_line, *header_lines = raw.decode("latin-1").split("\r\n")
    status = int(status_line.split()[1])
    got = {}
    for line in header_lines:
        if ":" in line:
            k, v = line.split(":", 1)
            got[k.strip().lower()] = v.strip()
    if status != 101:
        writer.close()
        return None, status
    if got.get("sec-websocket-accept") != accept_key(key):
        writer.close()
        raise ProtocolError("Sec-WebSocket-Accept no coincide")
    return WebSocket(reader, writer, client=True), status
