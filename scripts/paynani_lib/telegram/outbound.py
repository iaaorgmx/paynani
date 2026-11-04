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
from . import reactions as tg_reactions
from . import uploads as tg_uploads
from .store import private_dir, read_json, write_atomic, write_json

MAX_MESSAGE = 4096                 # lo que acepta Telegram por mensaje
MAX_CAPTION = 1024
MAX_TOTAL = 8 * MAX_MESSAGE        # un send más largo se rechaza (`too_long`)
MAX_UPLOAD = 50 * 1024 * 1024      # lo que deja subir la Bot API
MAX_PHOTO = 10 * 1024 * 1024
# #676: un documento recibido que PaynaniWeb deja descargar. En base64 por control.sock son
# ~27 MB en una línea; la web pone el mismo tope (telegram_source.FILE_MAX_BYTES).
FILE_MAX_BYTES = 20 * 1024 * 1024
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


def _today() -> str:
    """El día UTC del cupo (FR-26). Una función aparte para que las pruebas crucen la medianoche."""
    return time.strftime("%Y-%m-%d", time.gmtime())


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
        self._uploads_busy: set[str] = set()   # #662: los up_ de un envío en curso
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
        # El correo es único; un nombre puede repetirse (Ximena, #619): un nombre de más
        # de una fila no manda a nadie y pide el correo.
        by_mail = [e for e in rows if want and (e.get("address") or "").lower() == want]
        by_name = {contacts.row_key(e): e for e in rows if want and (e.get("name") or "").strip().lower() == want}
        if by_mail:
            entry = by_mail[0]
        elif len(by_name) > 1:
            raise _refused("conflict", "hay más de un contacto con ese nombre: usa su correo", field="contact")
        elif by_name:
            entry = next(iter(by_name.values()))
        else:
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
        return int(data.get("count", 0)) if data.get("day") == _today() else 0

    async def _reserve(self, n: int) -> str:
        """
        Toma `n` de los mensajes del día; si no alcanzan, `rate_limited` y no toma nada.
        Devuelve el día de la reserva, para que `_release` sólo devuelva a ese día.
        """
        async with self._rate_lock:
            day = _today()
            used = self._sent_today()
            limit = config.setting("TELEGRAM_SEND_PER_DAY", self.settings)
            if used + n > limit:
                raise _refused("rate_limited", f"{limit} mensajes al día", retry_after_s=_seconds_to_utc_midnight())
            write_json(self._rate_path(), {"day": day, "count": used + n})
            self.counters["sent_today"] = used + n
            return day

    async def _release(self, n: int, day: str) -> None:
        """
        Devuelve `n` de lo reservado que no quedó en el chat (Ximena, #619), sólo al día
        de la reserva: una reserva de ayer que falla hoy no resta del cupo de hoy.
        """
        if n <= 0:
            return
        async with self._rate_lock:
            if day != _today():
                return                             # ese día ya pasó: su cupo ya no cuenta
            used = max(0, self._sent_today() - n)
            write_json(self._rate_path(), {"day": day, "count": used})
            self.counters["sent_today"] = used

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
        ups = msg.get("uploads")
        if not isinstance(text, str):
            raise _refused("invalid", "text", field="text")
        if file is not None and author(by) != "agent":
            raise _refused("invalid", "sólo la terminal y el agente mandan archivos", field="file")
        if ups is not None and (author(by) != "owner" or file is not None):
            raise _refused("invalid", "sólo el dueño manda archivos subidos (#662)", field="uploads")
        if not text.strip() and not file and not ups:
            raise _refused("invalid", "texto vacío", field="text", reason="empty")
        if len(text) > MAX_TOTAL:
            raise _refused("invalid", f"más de {MAX_TOTAL} caracteres", field="text", reason="too_long")
        reply_to = msg.get("reply_to")
        if reply_to is not None and not isinstance(reply_to, str):
            raise _refused("invalid", "reply_to", field="reply_to")
        thread, chat, _ = self._target(msg)
        quote = self._reply_target(thread, reply_to) if reply_to is not None else None
        if ups is not None:
            try:
                files = tg_uploads.take(self.root, ups)
            except tg_uploads.Rejected as exc:
                raise _refused(exc.code, exc.detail, field="uploads") from None
        elif file:
            path = self.check_file(file)
            files = [{"name": path.name, "path": path}]
        else:
            files = []
        busy = [f["upload"] for f in files if f.get("upload")]
        if self._uploads_busy.intersection(busy):
            raise _refused("bad_upload", "otro envío ya los está mandando", field="uploads")
        self._uploads_busy.update(busy)       # antes del primer await: un up_ no sale dos veces
        try:
            return await self._send(by, text, thread, chat, files, ups is not None, quote)
        finally:
            self._uploads_busy.difference_update(busy)

    def _reply_target(self, thread: str, ref: str) -> dict:
        """
        PRD #685 F2 (contrato de FR-14): el mensaje que se cita, de este mismo hilo, que entró
        (`tg:`) o que salió (`tgo:`). `{"ref", "excerpt", "message_id"}`; `message_id` es el de
        Telegram y nunca sale del servicio (FR-17). Si no, `invalid` con `field: reply_to`.
        """
        data = None
        if ref.startswith("tg:"):
            try:
                data = self.store.inbox(ref)
            except ValueError:
                data = None
            if data and data.get("type") != "telegram.received":
                data = None
        elif ref.startswith("tgo:"):
            data = next((s for s in self.store.sent() if s.get("ref") == ref), None)
        if not data:
            raise _refused("invalid", "ese mensaje no existe", field="reply_to", reason="not_found")
        if data.get("thread") != thread:
            raise _refused("invalid", "ese mensaje es de otro hilo", field="reply_to", reason="other_thread")
        return {"ref": ref, "excerpt": quote_excerpt(data), "message_id": _int_or_none(data.get("message_id"))}

    def _message_data(self, ref: str) -> dict | None:
        """Lo guardado de un mensaje del hilo, que entró (`tg:`) o que salió (`tgo:`), o None."""
        if ref.startswith("tg:"):
            try:
                data = self.store.inbox(ref)
            except ValueError:
                return None
            return data if data and data.get("type") == "telegram.received" else None
        if ref.startswith("tgo:"):
            return next((s for s in self.store.sent() if s.get("ref") == ref), None)
        return None

    async def react(self, msg: dict) -> dict:
        """
        PRD #685 F3 (contrato de FR-14): pone (`emoji`) o quita (`""`) la reacción del bot en
        un mensaje del hilo. Una por mensaje; otra la reemplaza. Sólo las de `BOT_REACTIONS`
        (`invalid`, `reason: bad_emoji`). Fuera del roster es `not_allowed` (FR-17). No cuenta
        para el tope de envíos. Devuelve `{"ref", "reactions"}`.
        """
        if self.store is None:
            raise _refused("unavailable", "el servicio todavía no identifica al bot")
        ref, emoji = msg.get("ref"), msg.get("emoji", "")
        if not isinstance(ref, str) or not ref:
            raise _refused("missing_field", "ref", field="ref")
        if not isinstance(emoji, str):
            raise _refused("invalid", "emoji", field="emoji")
        emoji = emoji.strip()
        api = tg_reactions.api_form(emoji) if emoji else ""
        if api is None:
            raise _refused("invalid", "un bot no puede usar esa reacción", field="emoji", reason="bad_emoji")
        data = self._message_data(ref)
        if not data:
            raise _refused("not_found", "ese mensaje no existe")
        thread, chat, _ = self._target({"thread": data.get("thread")})
        mid = _int_or_none(data.get("message_id"))
        if mid is None:
            raise _refused("not_found", "Telegram no dio el id de ese mensaje")
        current = self.store.reactions().get(ref, {})
        if tg_reactions.key(current.get("ours") or "") != tg_reactions.key(api):
            reaction = json.dumps([{"type": "emoji", "emoji": api}] if api else [], ensure_ascii=False)
            await self._api("setMessageReaction", {"chat_id": chat, "message_id": mid, "reaction": reaction})
            current = self.store.set_reaction(ref, "ours", api)
            self.log(f"telegram.react {ref} en {thread}" + ("" if api else " (quitada)"))
            self._notify("reaction", ref=ref)
        return {"ref": ref, "reactions": tg_reactions.view(current)}

    async def _send(self, by: str, text: str, thread: str, chat: int, files: list[dict],
                    from_web: bool, quote: dict | None = None) -> dict:
        caption = text if files and len(text) <= MAX_CAPTION else ""
        chunks = split_text(text) if text and not caption else []
        reserved = len(chunks) + len(files)
        day = await self._reserve(reserved)        # atómico: dos envíos a la vez no pasan el límite
        delivered = 0
        self._stop_typing(thread)
        ref = "tgo:" + secrets.token_hex(16)
        record = {"ref": ref, "thread": thread, "dir": "out", "by": author(by), "at": _now(),
                  "kind": "file" if files else "text", "text": text,
                  "file": files[0]["name"] if files else None, "status": "sending"}
        if from_web:
            record["files"] = [self._keep_photo(ref, i, f) for i, f in enumerate(files)]
        if quote is not None:
            record["reply_to"] = {"ref": quote["ref"], "excerpt": quote["excerpt"], "missing": False}
        self.store.record_sent(record)
        # PRD #685 F2: sólo la primera parte cita. Sin el message_id del original (un envío
        # viejo), sale sin cita: `dropped`.
        reply_params = None
        if quote is not None and quote.get("message_id"):
            reply_params = {"message_id": quote["message_id"], "allow_sending_without_reply": True}
        first = None
        try:
            for i, f in enumerate(files):
                got = await self._send_file(chat, f, caption if i == 0 else "",
                                            reply_params if i == 0 else None)
                first = got if first is None else first
                delivered += 1
            draft = self._drafts.pop(thread, None)
            for i, chunk in enumerate(chunks):
                await self._pace(chat)
                quoting = reply_params if i == 0 and not files else None
                if i == 0 and draft and draft.get("mode") == "edit" and quoting is None:
                    got = await self._api("editMessageText", {"chat_id": chat, "message_id": draft["message_id"],
                                                              "text": chunk})
                else:
                    if i == 0 and draft and draft.get("mode") == "edit":
                        # Una edición no puede citar: el borrador se borra y la respuesta sale nueva.
                        with contextlib.suppress(Exception):
                            await self._api("deleteMessage", {"chat_id": chat, "message_id": draft["message_id"]})
                    got = await self._api("sendMessage", {"chat_id": chat, "text": chunk,
                                                          "reply_parameters": quoting})
                first = got if first is None else first
                delivered += 1
        except Exception as exc:
            await self._release(reserved - delivered, day)
            gone = [f["upload"] for f in files[:delivered] if f.get("upload")]
            for up in gone:
                tg_uploads.drop(self.root, up)    # lo que ya salió no se repite al reintentar
            if gone and isinstance(exc, _Refused):
                exc.extra["sent_uploads"] = gone  # Andy en #665: la web sabe cuáles quitar de la lista
            self.store.record_sent({"ref": ref, "status": "failed" if not delivered else "partial",
                                    "delivered": delivered, "parts": reserved})
            self._notify("threads")
            raise
        for f in files:
            if f.get("upload"):
                tg_uploads.drop(self.root, f["upload"])    # un solo uso: sólo cuando salió
        done = {"ref": ref, "status": "sent"}
        mid = _int_or_none((first or {}).get("message_id")) if isinstance(first, dict) else None
        if mid is not None:
            done["message_id"] = mid          # privado: para citar este mensaje después (F2)
        reply = None
        if quote is not None:
            quoted = isinstance(first, dict) and isinstance(first.get("reply_to_message"), dict)
            reply = "native" if quoted else "dropped"
            if not quoted:
                done["reply_to"] = dict(record["reply_to"], missing=True)
        self.store.record_sent(done)
        self.log(f"telegram.send {ref} a {thread}" + (f" ({reply})" if reply else ""))
        self._notify("threads")
        out = {"ref": ref, "status": "sent", "at": record["at"]}
        if reply:
            out["reply"] = reply
        return out

    def _keep_photo(self, ref: str, i: int, f: dict) -> dict:
        """Lo que queda en outbox.jsonl de un archivo de la web; una foto, con su copia en media/."""
        item = {"name": f["name"], "kind": f.get("kind"), "size": f["size"]}
        if f.get("kind") == "image" and f["mime"] in PHOTO_MIMES + ("image/gif",):
            ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else "bin"
            path = private_dir(self.root / "media") / f"out-{ref[4:]}-{i}.{ext}"
            with contextlib.suppress(OSError):
                write_atomic(path, f["data"])
                item["media"] = {"path": str(path), "mime": f["mime"], "bytes": f["size"]}
        return item

    async def _send_file(self, chat: int, f: dict, caption: str, reply_params: dict | None = None):
        if f.get("path") is not None:
            data = f["path"].read_bytes()
            mime = mimetypes.guess_type(f["name"])[0] or "application/octet-stream"
        else:
            data, mime = f["data"], f["mime"]
        method, field = ("sendPhoto", "photo") if mime in PHOTO_MIMES and len(data) <= MAX_PHOTO \
            else ("sendDocument", "document")
        await self._pace(chat)
        params = {"chat_id": chat, "caption": caption or None,
                  # multipart: un objeto va como texto JSON (Bot API).
                  "reply_parameters": json.dumps(reply_params) if reply_params else None}
        return await self._api(method, params, upload=(field, f["name"], data, mime))

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
        day = await self._reserve(1)
        state = s["state"]
        try:
            await self._pace(chat, CHAT_EDIT_EVERY_S)
            if state.get("mode") == "edit" and state.get("message_id"):
                await self._api("editMessageText", {"chat_id": chat, "message_id": state["message_id"],
                                                    "text": segment})
            else:
                await self._api("sendMessage", {"chat_id": chat, "text": segment})
        except Exception:
            await self._release(1, day)
            raise
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
            if m.get("filename"):
                item["filename"] = m["filename"]      # #676: el nombre de un documento
            if isinstance(m.get("reply_to"), dict):
                item["reply_to"] = m["reply_to"]      # PRD #685 F2; el nombre va abajo
            out[t]["messages"].append(item)
        for s in self.store.sent():
            t = s.get("thread")
            if t in out:
                item = {"ref": s["ref"], "dir": "out", "at": s.get("at"), "kind": s.get("kind"),
                        "text": s.get("text"), "by": s.get("by"), "status": s.get("status")}
                if s.get("files"):
                    item["files"] = [_public_file(f) for f in s["files"]]
                elif s.get("file"):
                    item["files"] = [{"name": s["file"]}]
                if isinstance(s.get("reply_to"), dict):
                    item["reply_to"] = s["reply_to"]
                if not _int_or_none(s.get("message_id")):
                    # #707: lo que salió sin el message_id de Telegram (antes de #700, o que
                    # no llegó a salir) no se puede citar ni reaccionar; sólo viene si es false.
                    item["actions"] = False
                out[t]["messages"].append(item)
        agent_name = self._agent_name()
        reactions = self.store.reactions()
        for v in out.values():
            for m in v["messages"]:
                if "reply_to" in m:
                    m["reply_to"] = _public_quote(m["reply_to"], v["name"], agent_name)
                found = tg_reactions.view(reactions.get(m["ref"]))
                if found:
                    m["reactions"] = found            # PRD #685 F3; sin reacciones no viene
            v["messages"].sort(key=lambda m: m.get("at") or "", reverse=True)
            v["visible"] = [m for m in v["messages"]
                            if v["entry"] is not None or (m["dir"] == "in" and m["_catch"] and catch_active)]
        return out

    def _agent_name(self) -> str:
        """El nombre del agente en una cita a lo que mandamos: AGENT_EMAIL_FROM_NAME, o el
        @usuario del bot."""
        with contextlib.suppress(Exception):
            from paynani_lib import envfile  # noqa: PLC0415
            name = str(envfile.read_env().get("AGENT_EMAIL_FROM_NAME") or "")
            if name:
                return name
        return f"@{self.bot_username}" if getattr(self, "bot_username", None) else ""

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
        if ref.startswith("tgo:"):
            return self._sent_image(ref, msg.get("index", 0))
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

    def file(self, msg: dict) -> dict:
        """
        #676: un documento recibido, para que PaynaniWeb lo deje descargar. Las reglas de
        `image`: sólo de un mensaje que el hilo muestra hoy. Además, como `whatsapp.file`:
        el archivo directamente dentro de media/, abierto sin seguir enlaces, regular y de
        hasta FILE_MAX_BYTES. Todo lo que no se sirve da el mismo not_found.
        """
        ref = str(msg.get("ref") or "")
        try:
            data = self.store.inbox(ref) if self.store and ref.startswith("tg:") else None
        except ValueError:
            data = None
        media = (data or {}).get("media") or {}
        if not data or data.get("kind") != "document" or not media.get("path"):
            raise _refused("not_found")
        known, links = self._known()
        visible = contacts.recognized_now(known, links, data.get("user", 0)) is not None or \
            (data.get("catch_all") and self._catch_active())
        if not visible:
            raise _refused("not_found")
        root = os.path.abspath(self.root / "media")
        path = os.path.abspath(str(media["path"]))
        if os.path.dirname(path) != root:
            raise _refused("not_found")
        try:
            if stat.S_ISLNK(os.lstat(root).st_mode):
                raise _refused("not_found")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        except OSError:
            raise _refused("not_found") from None
        with os.fdopen(fd, "rb") as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_MAX_BYTES:
                raise _refused("not_found")
            body = fh.read(FILE_MAX_BYTES + 1)
        if len(body) > FILE_MAX_BYTES:
            raise _refused("not_found")
        return {"name": str(data.get("filename") or ""), "mime": str(media.get("mime") or ""),
                "bytes": len(body), "data": base64.b64encode(body).decode("ascii")}

    def _sent_image(self, ref: str, index) -> dict:
        """La copia de una foto que el dueño mandó desde la web (#662), si su hilo se ve hoy."""
        if self.store is None or not isinstance(index, int) or isinstance(index, bool):
            raise _refused("not_found")
        rec = next((s for s in self.store.sent() if s.get("ref") == ref), None)
        files = (rec or {}).get("files") or []
        if not 0 <= index < len(files):
            raise _refused("not_found")
        media = files[index].get("media") or {}
        info = self.store.threads().get(rec.get("thread"))
        known, links = self._known()
        if not media.get("path") or not info or contacts.recognized_now(known, links, info["user"]) is None:
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
    def _notify(self, what: str, **extra) -> None:
        line = (json.dumps({"type": "telegram.changed", "what": what, **extra}) + "\n").encode()
        for w in list(self.watchers):
            try:
                w.write(line)
            except (ConnectionError, RuntimeError):
                self.watchers.discard(w)


def _public_quote(q: dict, contact_name: str, agent_name: str) -> dict:
    """La cita de un mensaje para `telegram.thread` (contrato de FR-14): `{ref, name, excerpt,
    missing}`. `ref` es null si el original es de antes de paynani; el nombre se pone aquí."""
    ref = q.get("ref") if isinstance(q.get("ref"), str) else None
    ours = (ref or "").startswith("tgo:") or (ref is None and q.get("from_bot"))
    return {"ref": ref, "name": agent_name if ours else contact_name,
            "excerpt": str(q.get("excerpt") or "")[:100], "missing": bool(q.get("missing"))}


def _int_or_none(value) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def quote_excerpt(data: dict) -> str:
    """El extracto de una cita (contrato de FR-14): una línea, hasta 100. Sin texto, una foto es
    «📷» y un documento «📄 nombre»."""
    text = " ".join(str(data.get("text") or data.get("caption") or "").split())
    if text:
        return text[:100]
    kind = data.get("kind")
    if kind in ("photo", "image") or data.get("photo"):
        return "📷"
    name = data.get("filename") or data.get("file") or (data.get("document") or {}).get("file_name") or ""
    if kind in ("document", "file") or name or data.get("document"):
        return f"📄 {name}".strip()[:100]
    return ""


class _Refused(Exception):
    """Lo mismo que service.Refused; aquí para no importar service (lo importa a éste)."""

    def __init__(self, code: str, detail: str = "", **extra):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.extra = extra


def _public_file(f: dict) -> dict:
    """Un archivo enviado, para `telegram.thread`: sin la ruta en disco."""
    out = {k: f.get(k) for k in ("name", "kind", "size") if f.get(k) is not None}
    media = f.get("media") or {}
    if media.get("path"):
        out["media"] = {"mime": media.get("mime"), "bytes": media.get("bytes")}
    return out


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
