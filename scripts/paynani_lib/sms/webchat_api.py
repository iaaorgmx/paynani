"""
Webchat desde PaynaniApp (PRD #653, SMS_GATEWAY.md §13).

El teléfono emparejado platica con el agente en la misma conversación que PaynaniWeb. Todo
pasa por el almacén del núcleo (`paynani_lib/webchat/store.py`); no hay servicio aparte.

- `webchat.thread` y `webchat.send` llegan por el WebSocket del teléfono (`handle`).
- Los archivos suben por `POST /sms/webchat/upload` (`save_upload`) a
  `state/webchat/uploads/`, fuera de `files/`: un `up_…` pendiente no se puede descargar.
  Se consume sólo cuando el mensaje se guarda.
- `watch` avisa `webchat.changed` cuando cambian los mensajes, «escribiendo…» o el
  borrador.
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

from ..webchat import store

TYPES = ("webchat.thread", "webchat.send")
GRANT = "webchat.owner"
ID_RE = re.compile(r"^q_[0-9a-f]{32}$")
MSG_RE = re.compile(r"^w_[0-9a-f]{32}$")
UPLOAD_RE = re.compile(r"^up_[0-9a-f]{32}$")
MAX_UPLOADS = 10              # por mensaje, como la web
MAX_PENDING = 20              # subidas sin usar por teléfono
UPLOAD_TTL_S = 600
RATE_MAX = 20                 # mensajes por minuto, como la web
RATE_WINDOW_S = 60
REPLAY_MAX = 64
REPLAY_TTL_S = 600
WATCH_S = 0.3                 # cada cuánto se mira el almacén; también el mínimo entre dos `draft`
FULL_EVERY_S = 5.0            # sin cambios, cada cuánto se vuelve a leer «escribiendo…» y el borrador
MESSAGE_FIELDS = ("id", "dir", "by", "at", "text", "files")


class WebchatRelay:
    """
    `owner()` da `{"name", "email"}` del usuario de PaynaniWeb, o None si no hay. Sin él,
    Webchat no se anuncia. `agent_name()` es el nombre para las burbujas, o "".
    """

    def __init__(self, state_dir: Path, *, owner: Callable[[], dict | None] | None = None,
                 agent_name: Callable[[], str] | None = None, log=None,
                 clock: Callable[[], float] = time.time, watch_s: float = WATCH_S):
        self.state_dir = Path(state_dir)
        self._owner = owner or (lambda: None)
        self._agent_name = agent_name or (lambda: "")
        self.log = log or (lambda line: None)
        self.clock = clock
        self.watch_s = watch_s
        self.sent: collections.deque = collections.deque()
        self.replays: collections.OrderedDict = collections.OrderedDict()
        self.lock = threading.Lock()
        self.inflight: dict[str, tuple[str, asyncio.Future]] = {}
        # Un `send` a la vez: dos envíos con el mismo `up_…` y distinto `id` no lo usan dos
        # veces (Iris en #655). Mandar es raro; serializar no cuesta.
        self.send_lock = threading.Lock()

    # --- el welcome --------------------------------------------------------
    def owner(self) -> dict | None:
        try:
            info = self._owner()
        except Exception:  # noqa: BLE001 - un user.json roto es «sin usuario»
            return None
        if not info or not (info.get("email") or info.get("name")):
            return None
        return {"name": str(info.get("name") or ""), "email": str(info.get("email") or "")}

    def available(self) -> bool:
        return self.owner() is not None

    def accepts(self, available: bool) -> list[str]:
        return list(TYPES) if available else []

    def grants(self, available: bool) -> list[str]:
        # La conexión es la del teléfono emparejado (su token es el de device.json).
        return [GRANT] if available else []

    # --- un pedido de la app -----------------------------------------------
    async def handle(self, msg: dict, device_id: str, *, grants: list) -> dict:
        rid = msg.get("id")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            return {"type": "error", "code": "missing_field", "ref": str(rid or "")[:80], "field": "id",
                    "detail": "id es q_ y 32 hex"}
        if GRANT not in (grants or []):
            return _error(rid, "forbidden")
        if msg.get("type") == "webchat.thread":
            return await asyncio.to_thread(self.thread, msg, rid)
        digest = _digest(msg)
        pending = self.inflight.get(rid)
        if pending is not None:
            if pending[0] != digest:
                return _error(rid, "invalid", field="id", reason="id_reused")
            first = await asyncio.shield(pending[1])
            return {**first, "replayed": True} if first.get("type") == "result" else first
        with self.lock:
            self._expire_replays()
            seen = self.replays.get(rid)
        if seen is not None:
            if seen[0] != digest:
                return _error(rid, "invalid", field="id", reason="id_reused")
            return {**seen[1], "replayed": True}
        future = asyncio.get_running_loop().create_future()
        self.inflight[rid] = (digest, future)
        response = _error(rid, "unavailable")
        try:
            response = await asyncio.to_thread(self.send, msg, rid, device_id)
        finally:
            self.inflight.pop(rid, None)
            future.set_result(response)
        if response.get("type") == "result":
            with self.lock:
                self.replays[rid] = (digest, response, time.monotonic())
                while len(self.replays) > REPLAY_MAX:
                    self.replays.popitem(last=False)
        return response

    def _expire_replays(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self.replays.items() if now - v[2] > REPLAY_TTL_S]:
            del self.replays[key]

    # --- webchat.thread ----------------------------------------------------
    def thread(self, msg: dict, rid: str) -> dict:
        if self.owner() is None:
            return _error(rid, "unavailable")
        limit = msg.get("limit", 50)
        if limit is None:
            limit = 50
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            return _error(rid, "invalid", field="limit", reason="1 a 100")
        before, after = msg.get("before"), msg.get("after")
        if before is not None and after is not None:
            return _error(rid, "invalid", field="before", reason="before y after juntos")
        for field, value in (("before", before), ("after", after)):
            if value is not None and (not isinstance(value, str) or not MSG_RE.match(value)):
                return _error(rid, "invalid", field=field, reason="id w_ y 32 hex")
        rows = store.messages(limit=10 ** 9, state_dir=self.state_dir)
        ids = [m["id"] for m in rows]
        anchor = before or after
        if anchor is not None and anchor not in ids:
            return _error(rid, "not_found", field="before" if before else "after")
        if after is not None:
            start = ids.index(after) + 1
            page = rows[start:start + limit]
            next_before = None
        else:
            end = ids.index(before) if before is not None else len(rows)
            start = max(0, end - limit)
            page = rows[start:end]
            next_before = page[0]["id"] if page and start > 0 else None
        return {"type": "result", "ref": rid, "ok": True, "data": {
            "agent": self._agent() or None,
            "messages": [_message(m) for m in page],
            "next_before": next_before,
            "typing": bool(store.is_typing(state_dir=self.state_dir)),
            "draft": store.draft(state_dir=self.state_dir)}}

    def _agent(self) -> str:
        try:
            return str(self._agent_name() or "")[:80]
        except Exception:  # noqa: BLE001 - sólo es para mostrar
            return ""

    # --- webchat.send ------------------------------------------------------
    def send(self, msg: dict, rid: str, device_id: str) -> dict:
        with self.send_lock:
            return self._send_locked(msg, rid, device_id)

    def _send_locked(self, msg: dict, rid: str, device_id: str) -> dict:
        owner = self.owner()
        if owner is None:
            return _error(rid, "unavailable")
        text = msg.get("text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            return _error(rid, "invalid", field="text", reason="texto")
        uploads = msg.get("uploads") or []
        if not isinstance(uploads, list) or len(uploads) > MAX_UPLOADS \
                or not all(isinstance(u, str) for u in uploads) or len(set(uploads)) != len(uploads):
            return _error(rid, "invalid", field="uploads", reason=f"hasta {MAX_UPLOADS} up_ distintos")
        now = self.clock()
        with self.lock:
            while self.sent and now - self.sent[0] >= RATE_WINDOW_S:
                self.sent.popleft()
            if len(self.sent) >= RATE_MAX:
                retry = max(1, int(RATE_WINDOW_S - (now - self.sent[0])) + 1)
                return _error(rid, "rate_limited", retry_after_s=retry)
        files = []
        for up in uploads:
            item = self._pending(up, device_id, now)
            if item is None:
                return _error(rid, "bad_upload", field="uploads")
            files.append(item)
        try:
            message = store.append("owner", text.replace("\r\n", "\n").strip(),
                                   [(meta["name"], data) for meta, data in files],
                                   owner=owner, origin="app", state_dir=self.state_dir)
        except store.Rejected as exc:
            return _error(rid, exc.code)
        with self.lock:
            self.sent.append(now)
        for up in uploads:
            self._drop(up)
        self.log(f"webchat: mensaje del dueño desde PaynaniApp ({device_id}, {len(files)} archivo(s))")
        return {"type": "result", "ref": rid, "ok": True, "data": {"message": _message(message)}}

    # --- las subidas -------------------------------------------------------
    @property
    def uploads_dir(self) -> Path:
        return store.root(self.state_dir) / "uploads"

    def save_upload(self, device_id: str, name: str, data: bytes) -> dict:
        """
        Guarda un archivo para un `webchat.send` posterior. `{"upload", "name", "kind",
        "size"}`, o `{"error": code}` (`too_big`, `bad_type`, `too_many`).
        """
        now = self.clock()
        folder = store.private_dir(self.uploads_dir)
        self.sweep(now)
        mine = 0
        for meta_path in folder.glob("up_*.json"):
            meta = _read_json(meta_path)
            if meta and meta.get("device") == device_id:
                mine += 1
        if mine >= MAX_PENDING:
            return {"error": "too_many"}
        up = "up_" + secrets.token_hex(16)
        path = folder / up
        if len(data) > store.MAX_FILE:
            return {"error": "too_big"}
        store.write_private(path, data)
        try:
            clean, kind = store.check_upload(path, name, data)
        except store.Rejected as exc:
            with contextlib.suppress(OSError):
                path.unlink()
            return {"error": exc.code}
        meta = {"name": clean, "kind": kind, "size": len(data), "device": device_id,
                "expires": now + UPLOAD_TTL_S}
        store.write_private(folder / f"{up}.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        return {"upload": up, "name": clean, "kind": kind, "size": len(data)}

    def _pending(self, up: str, device_id: str, now: float) -> tuple[dict, bytes] | None:
        if not UPLOAD_RE.match(up):
            return None
        meta = _read_json(self.uploads_dir / f"{up}.json")
        if not meta or meta.get("device") != device_id or float(meta.get("expires", 0)) <= now:
            return None
        try:
            data = (self.uploads_dir / up).read_bytes()
        except OSError:
            return None
        return meta, data

    def _drop(self, up: str) -> None:
        for path in (self.uploads_dir / up, self.uploads_dir / f"{up}.json"):
            with contextlib.suppress(OSError):
                path.unlink()

    def sweep(self, now: float | None = None) -> int:
        """Borra las subidas vencidas (y las a medias, sin su .json). Cuántas borró."""
        now = self.clock() if now is None else now
        gone = 0
        try:
            names = os.listdir(self.uploads_dir)
        except OSError:
            return 0
        for name in names:
            if not UPLOAD_RE.match(name):
                continue
            meta = _read_json(self.uploads_dir / f"{name}.json")
            if meta is None:
                # El archivo sin su .json: una subida que se cortó, o un .json que se perdió.
                try:
                    old = now - (self.uploads_dir / name).stat().st_mtime > UPLOAD_TTL_S
                except OSError:
                    old = False
                if not old:
                    continue
            elif float(meta.get("expires", 0)) > now:
                continue
            self._drop(name)
            gone += 1
        return gone

    def file(self, ref: str) -> tuple[Path, str, str] | None:
        """`(ruta, mime, nombre)` de un adjunto ya guardado (`f_…`), o None."""
        return store.file_path(ref, state_dir=self.state_dir)

    # --- los avisos --------------------------------------------------------
    def marks(self) -> tuple:
        """`mtime` y tamaño de lo que puede cambiar, sin abrir nada (como la web, #650)."""
        r = store.root(self.state_dir)
        out = []
        for path in (r / "messages.jsonl", r / "typing.json", r / "draft.json",
                     self.state_dir / "lifecycle.jsonl"):
            try:
                st = path.stat()
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def snapshot(self) -> tuple:
        """Lo que se compara para avisar: (mensajes, escribiendo, borrador)."""
        return (self.marks()[0], bool(store.is_typing(state_dir=self.state_dir)),
                store.draft(state_dir=self.state_dir))

    async def watch(self, on_change: Callable[[str, dict], Awaitable[None]]) -> None:
        """
        Para siempre: `on_change(what, extra)` con `messages`, `typing` o `draft`. Cada
        `watch_s` sólo mira `mtime` y tamaño; lee el almacén cuando algo cambió o cada
        `FULL_EVERY_S` (el «escribiendo…» supuesto y el borrador vencen con el reloj). Dos
        `draft` seguidos nunca salen más juntos que `watch_s`.
        """
        last = await asyncio.to_thread(self.snapshot)
        marks = await asyncio.to_thread(self.marks)
        checked = time.monotonic()
        while True:
            await asyncio.sleep(self.watch_s)
            try:
                now_marks = await asyncio.to_thread(self.marks)
                if now_marks == marks and time.monotonic() - checked < FULL_EVERY_S:
                    continue
                marks, checked = now_marks, time.monotonic()
                now = await asyncio.to_thread(self.snapshot)
            except Exception as exc:  # noqa: BLE001 - un archivo a medias no tumba la vigilancia
                self.log(f"webchat: no se pudo leer el almacén ({type(exc).__name__})")
                continue
            if now[0] != last[0]:
                await on_change("messages", {})
            if now[1] != last[1]:
                await on_change("typing", {"typing": now[1]})
            if now[2] != last[2]:
                await on_change("draft", {"draft": now[2]})
            last = now


def _message(m: dict) -> dict:
    out = {k: m[k] for k in MESSAGE_FIELDS if k in m}
    out["files"] = [{k: f[k] for k in ("n", "name", "kind", "size", "ref") if k in f} for f in m.get("files", [])]
    return out


def _error(rid: str, code: str, **fields) -> dict:
    return {"type": "error", "ref": rid, "code": code, **fields}


def _digest(msg: dict) -> str:
    body = {k: v for k, v in msg.items() if k != "id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
