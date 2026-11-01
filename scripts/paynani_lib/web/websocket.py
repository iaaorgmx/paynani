"""
WebSocket (RFC 6455) con la biblioteca estándar, para Webchat (#648, Q309 = A): sólo lo que
hace falta para texto. El handshake, los frames de texto, ping, pong y close, y los
mensajes partidos en frames de continuación. Un frame del navegador siempre viene
enmascarado; uno sin máscara cierra la conexión (§5.1).

`Conn` lee y escribe sobre el socket ya actualizado: `recv(timeout)` devuelve
`(opcode, bytes)`, None si no llegó nada a tiempo, o levanta `Closed`.
"""
from __future__ import annotations

import base64
import hashlib
import socket
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TEXT, BINARY, CLOSE, PING, PONG, CONT = 0x1, 0x2, 0x8, 0x9, 0xA, 0x0
MAX_MESSAGE = 64 * 1024            # un mensaje de texto de Webchat cabe de sobra


class Closed(Exception):
    pass


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")


def valid_key(key: str) -> bool:
    try:
        return len(base64.b64decode(key, validate=True)) == 16
    except (ValueError, TypeError):
        return False


def frame(opcode: int, payload: bytes = b"") -> bytes:
    """Un frame del servidor (sin máscara, FIN)."""
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack("!H", n)
    else:
        head += bytes([127]) + struct.pack("!Q", n)
    return head + payload


class Conn:
    def __init__(self, sock: socket.socket, max_message: int = MAX_MESSAGE):
        self.sock = sock
        self.max_message = max_message
        self.lock = threading.Lock()
        self.buf = b""
        self.closed = False

    def send(self, opcode: int, payload: bytes = b"") -> None:
        with self.lock:
            if self.closed:
                raise Closed()
            try:
                self.sock.sendall(frame(opcode, payload))
            except OSError as exc:
                self.closed = True
                raise Closed() from exc

    def send_text(self, text: str) -> None:
        self.send(TEXT, text.encode("utf-8"))

    def close(self, code: int = 1000) -> None:
        try:
            self.send(CLOSE, struct.pack("!H", code))
        except Closed:
            pass
        self.closed = True

    def _need(self, n: int, timeout: float | None, started: bool = False) -> bytes | None:
        """`n` bytes, o None si no llegó nada en `timeout`. Con `started` (ya empezó un frame
        o un mensaje partido), quedarse sin bytes es `Closed`: devolver None dejaría el
        frame a medias y lo que siga en `buf` desalineado (revisión de Metis en #650)."""
        while len(self.buf) < n:
            self.sock.settimeout(timeout)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                if started:
                    raise Closed() from None
                return None
            except OSError as exc:
                raise Closed() from exc
            if not chunk:
                raise Closed()
            self.buf += chunk
            if self.buf:
                started, timeout = True, 10.0    # empezado un frame, el resto tiene que llegar
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, timeout: float | None, started: bool = False):
        head = self._need(2, timeout, started)
        if head is None:
            return None
        fin, opcode = head[0] & 0x80, head[0] & 0x0F
        masked, n = head[1] & 0x80, head[1] & 0x7F
        if head[0] & 0x70 or not masked:
            raise Closed()            # extensiones sin negociar, o un frame sin máscara
        if n == 126:
            n = struct.unpack("!H", self._need(2, 10.0, True))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._need(8, 10.0, True))[0]
        if n > self.max_message:
            raise Closed()
        mask = self._need(4, 10.0, True)
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(self._need(n, 10.0, True))) if n else b""
        return bool(fin), opcode, data

    def recv(self, timeout: float | None):
        """Un mensaje completo `(opcode, bytes)`, None si no llegó nada en `timeout`. Contesta
        los ping y el close; un pong se devuelve para que quien llama sepa que hay vida."""
        parts, kind = [], None
        while True:
            got = self._frame(timeout if not parts else 10.0, started=bool(parts))
            if got is None:
                return None
            fin, opcode, data = got
            if opcode == CLOSE:
                self.close()
                raise Closed()
            if opcode == PING:
                self.send(PONG, data[:125])
                continue
            if opcode == PONG:
                return PONG, data
            if opcode in (TEXT, BINARY):
                kind, parts = opcode, [data]
            elif opcode == CONT and kind is not None:
                parts.append(data)
            else:
                raise Closed()
            if sum(len(p) for p in parts) > self.max_message:
                raise Closed()
            if fin:
                return kind, b"".join(parts)
