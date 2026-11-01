"""
`/webchat/ws` (#648, Q309 = A): la conversación de Webchat en vivo, sobre `websocket.Conn`.
El protocolo sigue el de NiceBot (un JSON por frame de texto):

Del navegador:
- `{"type": "connect", "csrf": "…", "after": "w_…", "day": "YYYY-MM-DD"}`: el primero, en
  10 s. El CSRF de la página, el último mensaje que ya tiene y el día de su último
  separador.
- `{"type": "message.create", "request_id": "…", "content": "…"}`: un mensaje de texto (los
  adjuntos van por el POST). Un `request_id` repetido no se guarda dos veces.
- `{"type": "ping"}`.

Del servidor:
- `{"type": "connected"}`.
- `{"type": "message.accepted", "request_id", "message_id"}`.
- `{"type": "messages", "html", "after"}`: los mensajes nuevos, ya dibujados.
- `{"type": "typing", "on": bool}`.
- `{"type": "message.delta", "text"}`: el borrador que el agente va escribiendo
  (`store.draft()`, con `webchat send --stream`); `{"type": "message.delta", "text": null}`
  cuando ya no hay.
- `{"type": "error", "request_id", "code", "message", "retryable"}`.
- `{"type": "pong"}`.

El servidor mira el almacén cada segundo y manda un ping cada 30 s, para que el proxy del
gateway no corte la conexión por inactividad (revisión de Metis en #648).
"""
from __future__ import annotations

import json
import time

from . import websocket as ws

POLL_S = 1.0
PING_S = 30.0
CONNECT_S = 10.0
RATE_PER_MIN = 20
MAX_TEXT = 4000
ERRORS = {"empty": "EMPTY", "too_long": "MESSAGE_TOO_LARGE", "too_big": "MESSAGE_TOO_LARGE", "bad_type": "INVALID_FIELD"}


def _send(conn: ws.Conn, **data) -> None:
    conn.send_text(json.dumps(data, ensure_ascii=False))


def _error(conn, code: str, message: str, request_id=None, retryable: bool = False) -> None:
    _send(conn, type="error", request_id=request_id, code=code, message=message, retryable=retryable)


def serve(conn: ws.Conn, store, *, csrf_ok, owner: dict, render, texts: dict, clock=time.monotonic) -> None:
    """
    Atiende una conexión hasta que se cierra. `csrf_ok(token)` valida el CSRF de la
    sesión; `render(messages, day)` → `(html, day)` dibuja los mensajes nuevos; `texts`
    trae los mensajes de error ya traducidos.
    """
    try:
        got = conn.recv(CONNECT_S)
        hello = json.loads(got[1]) if got and got[0] == ws.TEXT else None
    except (ValueError, ws.Closed):
        hello = None
    if not isinstance(hello, dict) or hello.get("type") != "connect" or not csrf_ok(str(hello.get("csrf") or "")):
        conn.close(1008)
        return
    after = str(hello.get("after") or "") or None
    day = str(hello.get("day") or "")[:10]
    _send(conn, type="connected", protocol_version=1)
    seen: dict[str, str] = {}
    sent_times: list[float] = []
    typing = None
    draft = None
    next_poll = next_ping = 0.0
    try:
        while True:
            now = clock()
            if now >= next_poll:
                next_poll = now + POLL_S
                # Sin `after`, la página no tenía mensajes: todo lo que haya es nuevo para ella.
                new = store.messages(after=after, limit=50) if after else store.messages(limit=50)
                if new:
                    html, day = render(new, day)
                    after = new[-1]["id"]
                    _send(conn, type="messages", html=html, after=after)
                on = bool(store.is_typing())
                if on != typing:
                    typing = on
                    _send(conn, type="typing", on=on)
                current = store.draft() if hasattr(store, "draft") else None
                text = (current or {}).get("text") if current else None
                if text != draft:
                    draft = text
                    _send(conn, type="message.delta", text=text)
            if now >= next_ping:
                next_ping = now + PING_S
                conn.send(ws.PING, b"")
            got = conn.recv(max(0.05, min(next_poll, next_ping) - clock()))
            if got is None or got[0] != ws.TEXT:
                continue
            try:
                packet = json.loads(got[1])
            except ValueError:
                _error(conn, "INVALID_JSON", texts["malformed"])
                continue
            kind = packet.get("type") if isinstance(packet, dict) else None
            if kind == "ping":
                _send(conn, type="pong")
                continue
            if kind != "message.create":
                _error(conn, "UNSUPPORTED_MESSAGE", texts["malformed"])
                continue
            request_id = str(packet.get("request_id") or "")[:64]
            if request_id in seen:
                _send(conn, type="message.accepted", request_id=request_id, message_id=seen[request_id])
                continue
            content = packet.get("content")
            if not isinstance(content, str):
                _error(conn, "INVALID_FIELD", texts["malformed"], request_id)
                continue
            sent_times = [t for t in sent_times if now - t < 60]
            if len(sent_times) >= RATE_PER_MIN:
                _error(conn, "RATE_LIMITED", texts["rate"], request_id, retryable=True)
                continue
            try:
                message = store.append("owner", content.strip(), [], owner=owner)
            except Exception as exc:  # noqa: BLE001 -- el Rejected del almacén, o un fallo al guardar
                code = getattr(exc, "code", None) if type(exc).__name__ == "Rejected" else None
                _error(conn, ERRORS.get(code, "INTERNAL_ERROR"), texts.get(code or "failed", texts["failed"]),
                       request_id, retryable=code is None)
                continue
            sent_times.append(now)
            if request_id:
                seen[request_id] = message["id"]
            _send(conn, type="message.accepted", request_id=request_id, message_id=message["id"])
            next_poll = 0.0                  # que el mensaje aparezca de inmediato
    except ws.Closed:
        return
