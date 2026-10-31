"""
Lo que sale por Telegram (PRD #609 FR-20 a FR-27; TELEGRAM.md §4).

`Outbound` es una mezcla de `TelegramService`: usa su `store`, `settings`, `_call`,
`api`, `counters`, `log` y `_stopping`. Aquí están:

- a quién se puede mandar (FR-25): un contacto del roster hoy, con un chat privado que
  esa persona abrió (su hilo existe sólo si escribió). Si no, `not_allowed` o
  `not_started`;
- los límites (FR-26): un mensaje por segundo por chat (el servicio espera) y
  `TELEGRAM_SEND_PER_DAY` al día por instalación (`rate_limited` con `retry_after_s`).
  Un 429 espera su `retry_after` y se reintenta una vez;
- «escribiendo…» (FR-21) cada 4 s desde que llega el mensaje de un contacto, hasta que
  sale la respuesta, el agente cierra el evento o pasan 2 minutos;
- `telegram.send` (FR-20), con el texto partido en mensajes de 4096 y archivos sólo de
  `state/telegram/outbox/` o `TELEGRAM_ATTACH_DIRS`;
- `telegram.draft` (FR-24) y `telegram.stream_*` (FR-22), con `sendMessageDraft` y,
  si Telegram no lo acepta, un mensaje que se edita;
- `telegram.threads`, `telegram.thread`, `telegram.image` y `telegram.watch`.

Nada de aquí escribe ids de Telegram en el log ni en las respuestas.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import mimetypes
import os
import secrets
import stat
import time
from pathlib import Path

import ledger
import roster as roster_mod

from . import api as tg_api
from . import config, contacts
from .store import read_json, write_json

MAX_MESSAGE = 4096                 # lo que acepta Telegram por mensaje
MAX_CAPTION = 1024
MAX_TOTAL = 8 * MAX_MESSAGE        # un send más largo se rechaza (`too_long`)
MAX_UPLOAD = 50 * 1024 * 1024      # lo que deja subir la Bot API
MAX_PHOTO = 10 * 1024 * 1024
PHOTO_MIMES = ("image/jpeg", "image/png", "image/webp")
TYPING_EVERY_S = 4.0
TYPING_MAX_S = 120.0
STREAM_IDLE_S = 120.0
STREAM_TICK_S = 0.25
STREAM_MIN_CHARS = 24              # FR-22: como Hermes, desde 24 caracteres nuevos…
STREAM_EVERY_S = 0.8               # …cada 0.8 s…
CHAT_EDIT_EVERY_S = 1.0            # …sin pasar de un cambio por segundo por chat
CLOSED_STATES = {"handled", "replied", "closed"}


def author(by: str) -> str:
    """`by` del mensaje que sale (§4, #615): agent, owner o api."""
    if by == "api":
        return "api"
    if by == "web" or by.startswith("phone:"):
        return "owner"
    return "agent"


def split_text(text: str, size: int = MAX_MESSAGE) -> list[str]:
    """Partes de hasta `size`, cortando de preferencia en un salto de línea o un espacio."""
    parts = []
    rest = text
    while len(rest) > size:
        cut = rest.rfind("\n", 0, size)
        if cut < size // 2:
            cut = rest.rfind(" ", 0, size)
        if cut < size // 2:
            cut = size
        parts.append(rest[:cut])
        rest = rest[cut + 1:] if rest[cut:cut + 1] in ("\n", " ") else rest[cut:]
    if rest:
        parts.append(rest)
    return parts


def _seconds_to_utc_midnight() -> int:
    now = time.time()
    return max(1, int(86400 - (now % 86400)))


class Outbound:
    def _out_init(self) -> None:
        self._typing: dict[str, asyncio.Task] = {}
        self._drafts: dict[str, dict] = {}
        self._draft_ids: dict[str, int] = {}
        self._streams: dict[str, dict] = {}
        self._chat_last: dict[int, float] = {}
        self._rate_lock = asyncio.Lock()
        self.watchers: set = set()

    async def _out_stop(self) -> None:
        for task in list(self._typing.values()):
            task.cancel()
        for s in list(self._streams.values()):
            if s.get("task"):
                s["task"].cancel()
        self._typing.clear()
        self._streams.clear()

    # --- a quién (FR-25) --------------------------------------------------------------
    def _known(self) -> tuple[dict, dict]:
        try:
            known = roster_mod.roster_telegram(self.roster_path)
        except OSError:
            raise _refused("unavailable", "no se pudo leer roster.md") from None
        return known, self.store.links()["usernames"]

    def _target(self, msg: dict) -> tuple[str, int, dict]:
        """(hilo, chat, fila del roster) para mandar; aplica FR-25."""
        if self.store is None:
            raise _refused("unavailable", "el servicio todavía no identifica al bot")
        thread, contact = msg.get("thread"), msg.get("contact")
        if bool(thread) == bool(contact):
            raise _refused("missing_field", "thread o contact", field="thread")
        known, links = self._known()
        if thread:
            found = self.store.chat_of(str(thread))
            if found is None:
                raise _refused("not_allowed", "ese hilo no existe")
            chat, user = found
            entry = contacts.recognized_now(known, links, user)
            if entry is None:
                raise _refused("not_allowed", "no es un contacto del roster (Telegram)")
            return str(thread), chat, entry
        want = str(contact).strip().lower()
        rows = list(known["ids"].values()) + list(known["usernames"].values())
        entry = next((e for e in rows if want and want in ((e.get("name") or "").lower(),
                                                            (e.get("address") or "").lower())), None)
        if entry is None:
            raise _refused("not_allowed", "no está en roster.md con la columna Telegram")
        key = contacts.row_key(entry)
        for t, info in self.store.threads().items():
            now = contacts.recognized_now(known, links, info["user"])
            if now is not None and contacts.row_key(now) == key:
                return t, info["chat"], entry
        raise _refused("not_started", "esa persona no le ha escrito al bot")

    # --- límites (FR-26) --------------------------------------------------------------
    def _rate_path(self) -> Path:
        return self.root / "rate.json"

    def _sent_today(self) -> int:
        data = read_json(self._rate_path(), {}) or {}
        return int(data.get("count", 0)) if data.get("day") == time.strftime("%Y-%m-%d", time.gmtime()) else 0

    async def _reserve(self, n: int) -> None:
        """Toma `n` de los mensajes del día; si no alcanzan, `rate_limited` y no toma nada."""
        async with self._rate_lock:
            day = time.strftime("%Y-%m-%d", time.gmtime())
            used = self._sent_today()
            limit = config.setting("TELEGRAM_SEND_PER_DAY", self.settings)
            if used + n > limit:
                raise _refused("rate_limited", f"{limit} mensajes al día", retry_after_s=_seconds_to_utc_midnight())
            write_json(self._rate_path(), {"day": day, "count": used + n})
            self.counters["sent_today"] = used + n

    async def _pace(self, chat: int, every: float | None = None) -> None:
        """Un cambio por chat cada `TELEGRAM_SEND_INTERVAL_S` (o `every`): aquí se espera."""
        every = every if every is not None else float(config.setting("TELEGRAM_SEND_INTERVAL_S", self.settings))
        wait = self._chat_last.get(chat, -1e9) + every - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._chat_last[chat] = time.monotonic()

    async def _api(self, method: str, params: dict, upload: tuple | None = None):
        """Una llamada que manda algo: un 429 espera y reintenta una vez (FR-26)."""
        for attempt in (0, 1):
            try:
                if upload:
                    return await asyncio.to_thread(self.api.upload, method, params, *upload)
                return await self._call(method, params, timeout=60.0)
            except tg_api.Unauthorized:
                raise _refused("unavailable", "el token no vale") from None
            except tg_api.RetryAfter as exc:
                if attempt:
                    raise _refused("rate_limited", "Telegram pidió esperar",
                                   retry_after_s=int(exc.retry_after or 1)) from None
                await asyncio.sleep(min(float(exc.retry_after or 1), 30.0))
            except tg_api.NetworkError:
                if attempt:
                    raise _refused("unavailable", "no se pudo hablar con Telegram") from None
                await asyncio.sleep(1.0)
            except tg_api.ApiError as exc:
                raise _refused("invalid" if exc.code == 400 else "unavailable", f"{method}: {exc.code}") from None
        raise _refused("unavailable")

    # --- «escribiendo…» (FR-21) ---------------------------------------------------------
    def _start_typing(self, thread: str, chat: int, ref: str) -> None:
        self._stop_typing(thread)
        self._typing[thread] = asyncio.get_running_loop().create_task(self._typing_loop(thread, chat, ref))

    def _stop_typing(self, thread: str) -> None:
        task = self._typing.pop(thread, None)
        if task and task is not asyncio.current_task():
            task.cancel()

    def _event_closed(self, ref: str) -> bool:
        try:
            return any(r.get("state") in CLOSED_STATES for r in ledger.history(self.ledger_path, ref))
        except OSError:
            return False

    async def _typing_loop(self, thread: str, chat: int, ref: str) -> None:
        end = time.monotonic() + TYPING_MAX_S
        try:
            while time.monotonic() < end and not self._stopping.is_set():
                if self._event_closed(ref):
                    return
                with contextlib.suppress(tg_api.ApiError, tg_api.NetworkError):
                    await self._call("sendChatAction", {"chat_id": chat, "action": "typing"})
                await self._sleep(TYPING_EVERY_S)
        finally:
            if self._typing.get(thread) is asyncio.current_task():
                self._typing.pop(thread, None)

    # --- archivos (FR-20) ----------------------------------------------------------------
    def attach_dirs(self) -> list[Path]:
        dirs = [self.root / "outbox"]
        for raw in (self.settings.get("TELEGRAM_ATTACH_DIRS") or "").split(":"):
            raw = raw.strip()
            if raw and os.path.isabs(raw):
                dirs.append(Path(raw))
        return dirs

    def check_file(self, raw) -> Path:
        """Un archivo regular, sin enlaces, dentro de outbox/ o TELEGRAM_ATTACH_DIRS."""
        if not isinstance(raw, str) or not os.path.isabs(raw):
            raise _refused("not_allowed", "la ruta debe ser absoluta", reason="file_path")
        path = Path(raw)
        try:
            st = os.lstat(path)
        except OSError:
            raise _refused("not_allowed", "el archivo no existe", reason="file_missing") from None
        if not stat.S_ISREG(st.st_mode):
            raise _refused("not_allowed", "no es un archivo regular", reason="file_type")
        if st.st_size > MAX_UPLOAD:
            raise _refused("invalid", "más de 50 MB", field="file", reason="too_large")
        real_parent = os.path.realpath(path.parent)
        for d in self.attach_dirs():
            allowed = os.path.realpath(d)
            if real_parent == allowed or real_parent.startswith(allowed + os.sep):
                return Path(real_parent) / path.name
        raise _refused("not_allowed", "fuera de outbox/ y de TELEGRAM_ATTACH_DIRS", reason="file_dir")

    # --- telegram.send (FR-20, FR-25, FR-26) ----------------------------------------------
    async def send(self, msg: dict) -> dict:
        by = msg.get("by", "")
        text = msg.get("text", "")
        file = msg.get("file")
        if not isinstance(text, str):
            raise _refused("invalid", "text", field="text")
        if file is not None and author(by) != "agent":
            raise _refused("invalid", "sólo la terminal y el agente mandan archivos", field="file")
        if not text.strip() and not file:
            raise _refused("invalid", "texto vacío", field="text", reason="empty")
        if len(text) > MAX_TOTAL:
            raise _refused("invalid", f"más de {MAX_TOTAL} caracteres", field="text", reason="too_long")
        thread, chat, _ = self._target(msg)
        path = self.check_file(file) if file else None
        caption = text if path and len(text) <= MAX_CAPTION else ""
        chunks = split_text(text) if text and not caption else []
        await self._reserve(len(chunks) + (1 if path else 0))
        self._stop_typing(thread)
        ref = "tgo:" + secrets.token_hex(16)
        record = {"ref": ref, "thread": thread, "dir": "out", "by": author(by), "at": _now(),
                  "kind": "file" if path else "text", "text": text, "file": path.name if path else None,
                  "status": "sending"}
        self.store.record_sent(record)
        try:
            if path:
                await self._send_file(chat, path, caption)
            draft = self._drafts.pop(thread, None)
            for i, chunk in enumerate(chunks):
                await self._pace(chat)
                if i == 0 and draft and draft.get("mode") == "edit":
                    await self._api("editMessageText", {"chat_id": chat, "message_id": draft["message_id"],
                                                        "text": chunk})
                else:
                    await self._api("sendMessage", {"chat_id": chat, "text": chunk})
        except Exception:
            self.store.record_sent({"ref": ref, "status": "failed"})
            self._notify("threads")
            raise
        self.store.record_sent({"ref": ref, "status": "sent"})
        self.log(f"telegram.send {ref} a {thread}")
        self._notify("threads")
        return {"ref": ref, "status": "sent", "at": record["at"]}

    async def _send_file(self, chat: int, path: Path, caption: str) -> None:
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        method, field = ("sendPhoto", "photo") if mime in PHOTO_MIMES and len(data) <= MAX_PHOTO \
            else ("sendDocument", "document")
        await self._pace(chat)
        params = {"chat_id": chat, "caption": caption or None}
        await self._api(method, params, upload=(field, path.name, data, mime))

    # --- telegram.draft (FR-24) ----------------------------------------------------------
    def _draft_id(self, thread: str) -> int:
        return self._draft_ids.setdefault(thread, secrets.randbelow(2 ** 31 - 2) + 1)

    async def _show(self, chat: int, thread: str, text: str, state: dict) -> None:
        """
        Muestra `text` como borrador: `sendMessageDraft`, o si Telegram no lo acepta, un
        mensaje que se edita (`state["mode"] = "edit"`, `state["message_id"]`).
        """
        if state.get("mode", "draft") == "draft":
            try:
                await self._api("sendMessageDraft", {"chat_id": chat, "draft_id": self._draft_id(thread),
                                                     "text": text})
                state["mode"] = "draft"
                return
            except _Refused as exc:
                if exc.code != "invalid":
                    raise
                state["mode"] = "edit"
        if state.get("message_id"):
            await self._api("editMessageText", {"chat_id": chat, "message_id": state["message_id"], "text": text})
        else:
            sent = await self._api("sendMessage", {"chat_id": chat, "text": text})
            state["message_id"] = int((sent or {}).get("message_id") or 0)

    async def draft(self, msg: dict) -> dict:
        text = msg.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE:
            raise _refused("invalid", "texto de 1 a 4096 caracteres", field="text")
        thread, chat, _ = self._target(msg)
        state = self._drafts.setdefault(thread, {"mode": "draft"})
        await self._pace(chat, CHAT_EDIT_EVERY_S)
        await self._show(chat, thread, text, state)
        return {"status": "shown", "transport": state["mode"]}

    # --- telegram.stream_* (FR-22) ---------------------------------------------------------
    async def stream_open(self, msg: dict) -> dict:
        thread, chat, _ = self._target(msg)
        if self._sent_today() >= config.setting("TELEGRAM_SEND_PER_DAY", self.settings):
            raise _refused("rate_limited", "límite del día", retry_after_s=_seconds_to_utc_midnight())
        self._stop_typing(thread)
        sid = "s_" + secrets.token_hex(16)
        prior = self._drafts.pop(thread, None) or {}
        s = {"id": sid, "thread": thread, "chat": chat, "by": author(msg.get("by", "")), "text": "",
             "start": 0, "shown": 0, "last": 0.0, "touched": time.monotonic(),
             "state": {"mode": prior.get("mode", "draft"), "message_id": prior.get("message_id")},
             "lock": asyncio.Lock(), "segments": 0, "used_edit": prior.get("mode") == "edit"}
        self._streams[sid] = s
        s["task"] = asyncio.get_running_loop().create_task(self._stream_ticker(sid))
        return {"stream": sid}

    def _stream(self, msg: dict) -> dict:
        s = self._streams.get(str(msg.get("stream") or ""))
        if s is None:
            raise _refused("not_found", "ese stream no existe o ya se cerró")
        return s

    async def stream_append(self, msg: dict) -> dict:
        s = self._stream(msg)
        text = msg.get("text")
        if not isinstance(text, str):
            raise _refused("invalid", "text", field="text")
        if len(s["text"]) + len(text) > MAX_TOTAL:
            raise _refused("invalid", f"más de {MAX_TOTAL} caracteres", field="text", reason="too_long")
        s["text"] += text
        s["touched"] = time.monotonic()
        async with s["lock"]:
            await self._stream_push(s, final=False)
        return {"length": len(s["text"])}

    async def _stream_push(self, s: dict, final: bool) -> None:
        """Muestra lo nuevo, o lo deja como mensaje si `final`. Pasando 4096, sigue en otro."""
        chat, thread = s["chat"], s["thread"]
        while len(s["text"]) - s["start"] > MAX_MESSAGE:
            segment = split_text(s["text"][s["start"]:])[0]
            await self._finish_segment(s, segment)
            s["start"] += len(segment)
            s["shown"] = s["start"]
        current = s["text"][s["start"]:]
        if final:
            if current.strip():
                await self._finish_segment(s, current)
            return
        new = len(s["text"]) - s["shown"]
        since = time.monotonic() - s["last"]
        if not current.strip() or new <= 0:
            return
        if not ((new >= STREAM_MIN_CHARS and since >= STREAM_EVERY_S) or since >= CHAT_EDIT_EVERY_S):
            return
        if time.monotonic() - self._chat_last.get(chat, -1e9) < CHAT_EDIT_EVERY_S:
            return                                    # el siguiente tick lo muestra
        self._chat_last[chat] = time.monotonic()
        await self._show(chat, thread, current, s["state"])
        if s["state"].get("mode") == "edit":
            s["used_edit"] = True
        s["shown"] = len(s["text"])
        s["last"] = time.monotonic()

    async def _finish_segment(self, s: dict, segment: str) -> None:
        """Una parte terminada: mensaje normal tras un borrador, o la última edición del mensaje."""
        chat = s["chat"]
        await self._reserve(1)
        await self._pace(chat, CHAT_EDIT_EVERY_S)
        state = s["state"]
        if state.get("mode") == "edit" and state.get("message_id"):
            await self._api("editMessageText", {"chat_id": chat, "message_id": state["message_id"], "text": segment})
        else:
            await self._api("sendMessage", {"chat_id": chat, "text": segment})
        state["message_id"] = None
        s["segments"] += 1

    async def stream_close(self, msg: dict) -> dict:
        s = self._stream(msg)
        return await self._close_stream(s)

    async def _close_stream(self, s: dict) -> dict:
        self._streams.pop(s["id"], None)
        task = s.get("task")
        if task and task is not asyncio.current_task():
            task.cancel()
        if not s["text"].strip():
            raise _refused("invalid", "el stream no trajo texto", field="text", reason="empty")
        ref = "tgo:" + secrets.token_hex(16)
        record = {"ref": ref, "thread": s["thread"], "dir": "out", "by": s["by"], "at": _now(),
                  "kind": "text", "text": s["text"], "status": "sending"}
        self.store.record_sent(record)
        try:
            async with s["lock"]:
                await self._stream_push(s, final=True)
        except Exception:
            self.store.record_sent({"ref": ref, "status": "failed"})
            self._notify("threads")
            raise
        transport = "edit" if s["used_edit"] else "draft"
        self.store.record_sent({"ref": ref, "status": "sent", "transport": transport})
        self.log(f"telegram.stream {ref} a {s['thread']} ({transport})")
        self._notify("threads")
        return {"ref": ref, "status": "sent", "transport": transport}

    async def _stream_ticker(self, sid: str) -> None:
        """Muestra lo que quedó pendiente y cierra un stream sin `append` en 120 s."""
        while not self._stopping.is_set():
            await asyncio.sleep(STREAM_TICK_S)
            s = self._streams.get(sid)
            if s is None:
                return
            if time.monotonic() - s["touched"] > STREAM_IDLE_S:
                with contextlib.suppress(Exception):
                    await self._close_stream(s)
                return
            with contextlib.suppress(Exception):
                async with s["lock"]:
                    await self._stream_push(s, final=False)

    # --- hilos (§4) ------------------------------------------------------------------------
    def _thread_view(self, known: dict, links: dict, catch_active: bool) -> dict[str, dict]:
        """{hilo: {"entry", "name", "messages" (del más reciente al más viejo)}}."""
        threads = self.store.threads()
        out: dict[str, dict] = {}
        for t, info in threads.items():
            entry = contacts.recognized_now(known, links, info["user"])
            name = entry.get("name") if entry else f"{self.store.display_name(t) or 'alguien'} (no verificado)"
            out[t] = {"entry": entry, "name": name, "messages": []}
        for m in self.store.received():
            t = m.get("thread")
            if t not in out or m.get("type") != "telegram.received":
                continue
            item = {"ref": m["ref"], "dir": "in", "at": m.get("sent_at") or m.get("received_at"),
                    "kind": m.get("kind"), "text": m.get("text"), "edited": bool(m.get("edited")),
                    "_catch": bool(m.get("catch_all"))}
            media = m.get("media") or {}
            if media.get("path"):
                item["media"] = {"mime": media.get("mime"), "bytes": media.get("bytes")}
            out[t]["messages"].append(item)
        for s in self.store.sent():
            t = s.get("thread")
            if t in out:
                out[t]["messages"].append({"ref": s["ref"], "dir": "out", "at": s.get("at"), "kind": s.get("kind"),
                                           "text": s.get("text"), "by": s.get("by"), "status": s.get("status")})
        for v in out.values():
            v["messages"].sort(key=lambda m: m.get("at") or "", reverse=True)
            v["visible"] = [m for m in v["messages"]
                            if v["entry"] is not None or (m["dir"] == "in" and m["_catch"] and catch_active)]
        return out

    def _catch_active(self) -> bool:
        note = self._catch_all()
        return bool(note) and note.get("status") == "active"

    def threads(self, msg: dict) -> dict:
        limit, before = _limit(msg.get("limit", 50)), msg.get("before")
        if self.store is None:
            return {"threads": [], "next_before": None}
        known, links = self._known()
        rows = []
        for t, v in self._thread_view(known, links, self._catch_active()).items():
            if not v["messages"]:
                continue
            last = v["messages"][0]
            row = {"thread": t, "name": v["name"], "in_roster": v["entry"] is not None,
                   "last_at": last.get("at"), "last_dir": last["dir"], "can_reply": v["entry"] is not None}
            if v["visible"] and v["visible"][0] is last:
                row["last_excerpt"] = " ".join(str(last.get("text") or "").split())[:160] or None
                row["last_kind"] = last.get("kind")
            else:
                row.update(last_excerpt=None, last_kind=None)
                if not v["visible"]:
                    row["hidden"] = True
            rows.append(row)
        rows.sort(key=lambda r: r.get("last_at") or "", reverse=True)
        if before:
            rows = [r for r in rows if (r.get("last_at") or "") < str(before)]
        page = rows[:limit]
        return {"threads": page, "next_before": page[-1]["last_at"] if len(rows) > limit else None}

    def thread(self, msg: dict) -> dict:
        limit, before = _limit(msg.get("limit", 50)), msg.get("before")
        if self.store is None:
            raise _refused("not_found")
        if msg.get("contact") and not msg.get("thread"):
            if author(msg.get("by", "")) != "agent":
                raise _refused("invalid", "contact sólo desde la terminal o el agente", field="contact")
            t, _, _ = self._target({"contact": msg["contact"]})
        else:
            t = str(msg.get("thread") or "")
        known, links = self._known()
        v = self._thread_view(known, links, self._catch_active()).get(t)
        if v is None:
            raise _refused("not_found")
        base = {"thread": t, "name": v["name"], "in_roster": v["entry"] is not None,
                "can_reply": v["entry"] is not None}
        if not v["visible"]:
            return dict(base, messages=[], hidden=True, next_before=None)
        msgs = v["visible"]
        if before:
            msgs = [m for m in msgs if (m.get("at") or "") < str(before)]
        page = [{k: val for k, val in m.items() if not k.startswith("_")} for m in msgs[:limit]]
        return dict(base, messages=page, next_before=page[-1]["at"] if len(msgs) > limit else None)

    def image(self, msg: dict) -> dict:
        """Como `whatsapp.image` (#573): la foto de un mensaje visible hoy; si no, `not_found`."""
        ref = str(msg.get("ref") or "")
        try:
            data = self.store.inbox(ref) if self.store else None
        except ValueError:
            data = None
        media = (data or {}).get("media") or {}
        if not data or not str(media.get("mime") or "").startswith("image/") or not media.get("path"):
            raise _refused("not_found")
        known, links = self._known()
        visible = contacts.recognized_now(known, links, data.get("user", 0)) is not None or \
            (data.get("catch_all") and self._catch_active())
        if not visible:
            raise _refused("not_found")
        path = Path(media["path"])
        if path.parent != self.root / "media":
            raise _refused("not_found")
        try:
            body = path.read_bytes()
        except OSError:
            raise _refused("not_found") from None
        return {"mime": media["mime"], "bytes": len(body), "data": base64.b64encode(body).decode("ascii")}

    # --- telegram.watch ----------------------------------------------------------------------
    def _notify(self, what: str) -> None:
        line = (json.dumps({"type": "telegram.changed", "what": what}) + "\n").encode()
        for w in list(self.watchers):
            try:
                w.write(line)
            except (ConnectionError, RuntimeError):
                self.watchers.discard(w)


class _Refused(Exception):
    """Lo mismo que service.Refused; aquí para no importar service (lo importa a éste)."""

    def __init__(self, code: str, detail: str = "", **extra):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.extra = extra


def _refused(code: str, detail: str = "", **extra) -> _Refused:
    return _Refused(code, detail, **extra)


def _limit(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise _refused("invalid", "limit", field="limit") from None
    if not 1 <= n <= 100:
        raise _refused("invalid", "limit de 1 a 100", field="limit")
    return n


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
