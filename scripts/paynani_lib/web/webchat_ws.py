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

El servidor mira cada segundo si el almacén cambió (por `mtime`) y manda un ping cada 30 s, para que el proxy del
gateway no corte la conexión por inactividad (revisión de Metis en #648).
"""
from __future__ import annotations

import json
import re
import time

from . import websocket as ws

POLL_S = 1.0
REFRESH_S = 5.0                     # aunque nada cambie: typing y el borrador vencen con el tiempo
PING_S = 30.0
CONNECT_S = 10.0
RATE_PER_MIN = 20
REPLY_ID = re.compile(r"^w_[0-9a-f]{32}$")   # PRD #685 F2: el mensaje que se cita
MAX_TEXT = 4000
ERRORS = {"empty": "EMPTY", "too_long": "MESSAGE_TOO_LARGE", "too_big": "MESSAGE_TOO_LARGE", "bad_type": "INVALID_FIELD"}


def signature(store):
    """`mtime` y tamaño de lo que puede cambiar (revisión de Metis en #650): la conversación,
    typing, el borrador, las reacciones (PRD #685 F3) y el ledger. Con el almacén del núcleo
    (`root()`); con otro, None, y entonces se relee en cada vuelta."""
    if not hasattr(store, "root"):
        return None
    try:
        r = store.root()
    except Exception:  # noqa: BLE001 -- sin firma, se relee
        return None
    out = []
    for path in (r / "messages.jsonl", r / "typing.json", r / "draft.json", r / "reactions.jsonl",
                 r.parent / "lifecycle.jsonl"):
        try:
            st = path.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


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
    # PRD #685 F2: el almacén guarda `reply_to` (lo agrega el núcleo); un solo lugar lo decide.
    from .webchat_pages import replies as store_replies
    replies = store_replies(store)
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
    seen_sig, refreshed = object(), 0.0
    # PRD #685 F3: las reacciones de los últimos mensajes, para mandar sólo las que cambian (una
    # del agente a un mensaje viejo se ve sin recargar). La primera vuelta sólo las anota.
    reactions_seen: dict | None = None
    try:
        while True:
            now = clock()
            refresh = False
            if now >= next_poll:
                next_poll = now + POLL_S
                # Releer sólo si algo cambió en disco, o cada REFRESH_S por los plazos.
                sig = signature(store)
                if sig is None or sig != seen_sig or now - refreshed >= REFRESH_S:
                    seen_sig, refreshed, refresh = sig, now, True
            if refresh:
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
                if callable(getattr(store, "react", None)):
                    now_reacts = {m["id"]: m.get("reactions") or [] for m in store.messages(limit=50) if m.get("id")}
                    if reactions_seen is not None:
                        changed = {k: v for k, v in now_reacts.items() if reactions_seen.get(k, []) != v}
                        if changed:
                            _send(conn, type="reactions", items=changed)
                    reactions_seen = now_reacts
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
            # PRD #685 F2: la cita, si el almacén ya la guarda (un `w_…` de esta conversación).
            reply_to = packet.get("reply_to")
            extra = ({"reply_to": reply_to} if isinstance(reply_to, str) and REPLY_ID.match(reply_to)
                     and replies else {})
            try:
                message = store.append("owner", content.strip(), [], owner=owner, **extra)
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
