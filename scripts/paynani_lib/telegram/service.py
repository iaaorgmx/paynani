"""
El servicio paynani-telegram (PRD #609 FR-1 a FR-7 y FR-19; TELEGRAM.md).

`TelegramService` toma el candado de instancia, valida el token con `getMe`, revisa
que no haya webhook, reconcilia el diario del bot y recibe con `getUpdates` y espera
larga. Cada mensaje privado se vuelve un evento `telegram.received` (o
`telegram.edited`) en `events.jsonl`; de un grupo, supergrupo o canal sólo sale con
`leaveChat`. Contesta `telegram.status` en `state/telegram/control.sock`.

El orden de FR-5 para cada update:

1. si el diario ya lo tiene escrito, se salta;
2. si no lo tiene, se anota `update_id`, referencia y hash (con fsync);
3. se guarda el mensaje en `inbox/<ref>.json` y se escribe el evento (con fsync);
4. se marca escrito en el diario; el offset se guarda después.

Al arrancar, antes de leer updates, cada entrada sin marca de escrito se resuelve
(`_reconcile`). Nada de lo que sale de aquí (log, eventos, status, respuestas) lleva el
token, una URL de la Bot API ni un id de Telegram.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import os
import random
import re
import secrets
import stat
import sys
import time
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT / "scripts"), str(_ROOT / "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import event as ev  # noqa: E402
import ledger  # noqa: E402
import roster as roster_mod  # noqa: E402

from . import api as tg_api  # noqa: E402
from . import config  # noqa: E402
from .store import BotStore, canonical_hash, new_ref, private_dir, read_json, write_json  # noqa: E402

REQUEST_ID = re.compile(r"^q_[0-9a-f]{32}$")
BY_RE = re.compile(r"^(terminal|agent|web|api|phone:[A-Za-z0-9_-]{1,40})$")
ALIAS_RE = re.compile(r"^[0-9a-f]{16}$")
MAX_LINE = 256 * 1024
MAX_SOCKET_PATH = 103
POLL_TIMEOUT_S = 30
ALLOWED_UPDATES = ["message", "edited_message", "my_chat_member"]
OFFLINE_ALERT_S = 600          # TELEGRAM.md §3: `offline` tras 10 minutos sin Telegram
TOKEN_RETRY_S = 300            # con 401, se vuelve a probar getMe cada 5 minutos
WEBHOOK_RETRY_S = 60           # con webhook, se vuelve a mirar cada minuto, sin tocarlo
GROUP_TYPES = ("group", "supergroup", "channel")
CHECK_TTL_S = 300              # TELEGRAM.md §4: un `check` vale 5 minutos
READY_TIMEOUT_S = 60           # FR-10 paso 5: listo en 60 s o rollback
CHECK_RE = re.compile(r"^c_[0-9a-f]{32}$")

# Tipo de mensaje (TELEGRAM.md §3 `kind`), en el orden en que se reconocen.
KINDS = (("photo", "image"), ("video", "video"), ("video_note", "video"), ("voice", "voice"),
         ("audio", "audio"), ("document", "document"), ("sticker", "sticker"),
         ("location", "location"), ("venue", "location"), ("contact", "contact"))


class StartError(Exception):
    """El servicio no puede arrancar: candado tomado, control.sock, carpeta insegura."""


class Refused(Exception):
    def __init__(self, code: str, detail: str = "", **extra: Any):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.extra = extra


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def message_kind(message: dict) -> str:
    if isinstance(message.get("text"), str):
        return "text"
    for key, kind in KINDS:
        if key in message:
            return kind
    return "other"


class TelegramService:
    def __init__(self, state_dir: Path, *, roster_path: Path, token: str,
                 api_base: str = config.DEFAULT_API, journal: Path | None = None,
                 settings: dict[str, str] | None = None, log: Callable[[str], None] = print,
                 poll_timeout: int = POLL_TIMEOUT_S, backoff: tuple[float, float] = (1.0, 60.0),
                 offline_alert_s: float = OFFLINE_ALERT_S, token_retry_s: float = TOKEN_RETRY_S,
                 webhook_retry_s: float = WEBHOOK_RETRY_S, env_path: Path | None = None,
                 notify_owner: Callable[[str], None] | None = None,
                 ready_timeout_s: float = READY_TIMEOUT_S):
        self.state_dir = Path(state_dir)
        self.root = self.state_dir / "telegram"
        self.journal = journal or (self.state_dir / "events.jsonl")
        self.ledger_path = self.state_dir / "lifecycle.jsonl"
        self.roster_path = Path(roster_path)
        self.settings = settings or {}
        self.log = log
        self.api_base = api_base
        self.api = tg_api.BotAPI(token, api_base)
        self._token = token
        self.env_path = Path(env_path) if env_path else None   # None: config.env_path()
        self.notify_owner = notify_owner
        self.ready_timeout_s = ready_timeout_s
        self._checks: dict[str, dict] = {}
        self._apply_lock = asyncio.Lock()
        self._inflight: asyncio.Future | None = None   # el getUpdates en curso (un hilo no se cancela)
        self.poll_timeout = poll_timeout
        self.backoff = backoff
        self.offline_alert_s = offline_alert_s
        self.token_retry_s = token_retry_s
        self.webhook_retry_s = webhook_retry_s
        self.store: BotStore | None = None
        self.account = ""
        self.bot_username: str | None = None
        self.state = "starting"
        self.reason: str | None = None
        self.since = now_utc()
        self.last_poll_at: str | None = None
        self.counters = {"received_today": 0, "sent_today": 0, "edits_ignored": 0,
                         "media_rejected": 0, "groups_left": 0}
        self._day = time.strftime("%Y-%m-%d")
        self._health_sent: str | None = None    # el último `telegram.health` escrito
        self._lock_fd: int | None = None
        self._server: asyncio.AbstractServer | None = None
        self._sock_id: tuple[int, int] | None = None
        self._task: asyncio.Task | None = None
        self.clients: set[asyncio.StreamWriter] = set()
        self._stopping = asyncio.Event()

    def __repr__(self) -> str:
        return "TelegramService(<token>)"

    def _restart_loop(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _halt_loop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _drain_inflight(self) -> None:
        """
        Espera a que termine el getUpdates que quedó en curso con el token anterior. Volver
        a leer ese token mientras sigue abierto daría 409 contra nosotros mismos (FR-3).
        """
        fut = self._inflight
        if fut is not None and not fut.done():
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(fut), self.poll_timeout * 2 + 5)
        self._inflight = None

    # --- ciclo de vida ------------------------------------------------------------
    @property
    def socket_path(self) -> Path:
        return self.root / "control.sock"

    async def start(self) -> None:
        """Candado, control.sock y el bucle. StartError si algo de eso no se puede."""
        try:
            private_dir(self.root)
        except OSError as exc:
            raise StartError(f"state/telegram no se puede usar ({exc})") from None
        self._take_lock()
        if len(os.fsencode(str(self.socket_path))) > MAX_SOCKET_PATH:
            raise StartError(f"la ruta de control.sock mide más de {MAX_SOCKET_PATH} bytes: usa un --state más corto")
        try:
            await self._serve()
        except OSError as exc:
            raise StartError(f"no se pudo abrir control.sock ({type(exc).__name__})") from None
        self._write_status()
        self._restart_loop()

    async def stop(self) -> None:
        self._stopping.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        if self._server:
            self._server.close()
            for w in list(self.clients):
                with contextlib.suppress(Exception):
                    w.transport.abort()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 5)
        if self._sock_id:
            with contextlib.suppress(FileNotFoundError):
                st = os.lstat(self.socket_path)
                if (st.st_dev, st.st_ino) == self._sock_id:
                    os.unlink(self.socket_path)
        if self.state not in ("conflict", "token_invalid", "journal_mismatch"):
            self._set_state("stopped")
        else:
            self._write_status()
        if self._lock_fd is not None:
            os.close(self._lock_fd)        # suelta el flock
            self._lock_fd = None

    def _take_lock(self) -> None:
        """FR-3: un solo lector por instalación. Sin el candado, no arranca."""
        path = self.root / "lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise StartError("otro paynani-telegram ya corre con este estado (state/telegram/lock)") from None
        self._lock_fd = fd

    async def _serve(self) -> None:
        path = self.socket_path
        try:
            st = os.lstat(path)
            if not stat.S_ISSOCK(st.st_mode):
                raise StartError("state/telegram/control.sock existe y no es un socket")
            os.unlink(path)
        except FileNotFoundError:
            pass
        old = os.umask(0o177)
        try:
            self._server = await asyncio.start_unix_server(self._client, path=str(path), limit=MAX_LINE)
        finally:
            os.umask(old)
        os.chmod(path, 0o600)
        st = os.lstat(path)
        self._sock_id = (st.st_dev, st.st_ino)

    # --- estado ---------------------------------------------------------------------
    def _set_state(self, state: str, reason: str | None = None) -> None:
        if (state, reason) != (self.state, self.reason):
            self.state, self.reason = state, reason
            self.since = now_utc()
            self.log(f"estado: {state}" + (f" ({reason})" if reason else ""))
        self._write_status()

    def status(self) -> dict:
        self._roll_day()
        out = {"state": self.state, "bot_username": self.bot_username, "since": self.since,
               "last_poll_at": self.last_poll_at,
               "counters": dict(self.counters, send_limit_day=config.setting("TELEGRAM_SEND_PER_DAY", self.settings))}
        if self.reason:
            out["reason"] = self.reason
        return out

    def _write_status(self) -> None:
        with contextlib.suppress(OSError):
            write_json(self.root / "status.json", dict(self.status(), written_at=now_utc()))

    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self.counters["received_today"] = 0
            self.counters["sent_today"] = 0

    def _health(self, state: str, reason: str | None = None) -> None:
        """Un `telegram.health` por cambio, nunca uno repetido (FR-7: avisar una vez)."""
        if state == self._health_sent:
            return
        if state == "recovered" and self._health_sent is None:
            return
        envelope = ev.telegram_health_event(state=state, account=self.account or "tg:",
                                            local_time=time.strftime("%H:%M:%S"), reason=reason)
        try:
            ev.append(self.journal, envelope)
            ledger.observed(self.ledger_path, envelope)
        except (OSError, ValueError) as exc:
            self.log(f"no se pudo escribir telegram.health ({type(exc).__name__})")
            return
        self._health_sent = None if state == "recovered" else state
        self.log(envelope["notification_text"])

    # --- el bucle -------------------------------------------------------------------
    async def _call(self, method: str, params: dict | None = None, timeout: float = 15.0):
        return await asyncio.to_thread(self.api.call, method, params, timeout=timeout)

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), seconds)

    async def _run(self) -> None:
        try:
            if not await self._identify():
                return
            if not await self._no_webhook():
                return
            if not self._reconcile():
                return
            await self._poll()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - que se vea en el log, sin URL ni token
            self.log(f"el bucle se detuvo ({type(exc).__name__})")
            self._set_state("stopped", "error")

    async def _identify(self) -> bool:
        """getMe: el bot y su carpeta (FR-3a). 401 → token_invalid (FR-7)."""
        delay = self.backoff[0]
        while not self._stopping.is_set():
            try:
                me = await self._call("getMe")
            except tg_api.Unauthorized:
                self._set_state("token_invalid")
                self._health("token_invalid")
                await self._sleep(self.token_retry_s)
                continue
            except (tg_api.NetworkError, tg_api.RetryAfter, tg_api.ApiError) as exc:
                await self._sleep(getattr(exc, "retry_after", None) or self._jitter(delay))
                delay = min(delay * 2, self.backoff[1])
                continue
            bot_id = int(me["id"])
            self.bot_username = me.get("username")
            self._open_bot(bot_id)
            return True
        return False

    def _open_bot(self, bot_id: int) -> None:
        name = config.bot_dir_name(bot_id)
        self.store = BotStore(private_dir(self.root / "bots") / name)
        data = read_json(self.store.root / "account.json", {}) or {}
        alias = data.get("alias") if isinstance(data, dict) else None
        if not isinstance(alias, str) or not ALIAS_RE.match(alias):
            alias = secrets.token_hex(8)       # TELEGRAM.md §1: aleatorio, nunca del bot_id
            write_json(self.store.root / "account.json", {"alias": alias})
        self.account = f"tg:{alias}"
        write_json(self.root / "active", {"bot": name})

    async def _no_webhook(self) -> bool:
        """FR-3: con webhook no se toca nada; `conflict` hasta que se quite."""
        delay = self.backoff[0]
        while not self._stopping.is_set():
            try:
                info = await self._call("getWebhookInfo")
            except tg_api.Unauthorized:
                self._set_state("token_invalid")
                self._health("token_invalid")
                return False
            except (tg_api.NetworkError, tg_api.ApiError) as exc:
                await self._sleep(getattr(exc, "retry_after", None) or self._jitter(delay))
                delay = min(delay * 2, self.backoff[1])
                continue
            if (info or {}).get("url"):
                self._set_state("conflict", "webhook")
                self._health("conflict", "webhook")
                await self._sleep(self.webhook_retry_s)
                continue
            return True
        return False

    def _jitter(self, delay: float) -> float:
        return delay * (0.5 + random.random() / 2)

    async def _poll(self) -> None:
        """getUpdates con espera larga (FR-2), reconexión (FR-7) y offset durable (FR-4)."""
        delay = self.backoff[0]
        down_since: float | None = None
        self._set_state("running")
        while not self._stopping.is_set():
            params = {"offset": self.store.offset() or None, "timeout": self.poll_timeout,
                      "allowed_updates": ALLOWED_UPDATES}
            try:
                self._inflight = asyncio.ensure_future(
                    self._call("getUpdates", params, timeout=self.poll_timeout * 2))
                updates = await asyncio.shield(self._inflight)
            except tg_api.Unauthorized:
                self._set_state("token_invalid")
                self._health("token_invalid")
                return
            except tg_api.Conflict:
                # Otro lector con el mismo token: sin reintentar en bucle (FR-3).
                self._set_state("conflict", "409")
                self._health("conflict", "409")
                return
            except tg_api.RetryAfter as exc:
                await self._sleep(exc.retry_after or delay)
                continue
            except (tg_api.NetworkError, tg_api.ApiError):
                down_since = down_since or time.monotonic()
                if time.monotonic() - down_since >= self.offline_alert_s:
                    self._set_state("offline")
                    self._health("offline")
                await self._sleep(self._jitter(delay))
                delay = min(delay * 2, self.backoff[1])
                continue
            delay = self.backoff[0]
            if down_since is not None:
                down_since = None
                if self.state == "offline":
                    self._set_state("running")
                    self._health("recovered")
            self.last_poll_at = now_utc()
            for update in updates or []:
                if not await self._handle_update(update):
                    return            # sin confirmar: journal_mismatch, 401 o el servicio se detiene
                self.store.save_offset(int(update["update_id"]) + 1)
            self._write_status()

    # --- reconciliación (FR-5) ------------------------------------------------------
    def _events_with(self, refs: set[str]) -> dict[str, str | None]:
        """{ref: _tg_hash} de los eventos de events.jsonl con esas referencias."""
        found: dict[str, str | None] = {}
        if not refs:
            return found
        try:
            with open(self.journal, "rb") as fh:
                for raw in fh:
                    if b'"tg:' not in raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue
                    if rec.get("event_id") in refs:
                        found[rec["event_id"]] = rec.get("_tg_hash")
        except OSError:
            pass
        return found

    def _in_ledger(self, ref: str) -> bool:
        try:
            return ref in ledger.latest(self.ledger_path)
        except (OSError, ValueError):
            return False

    def _reconcile(self) -> bool:
        """Cada entrada del diario sin marca de escrito, antes de leer updates (FR-5)."""
        pending = {u: e for u, e in self.store.journal().items() if not e["written"]}
        if not pending:
            return True
        events = self._events_with({e["ref"] for e in pending.values()})
        for u, entry in sorted(pending.items()):
            ref = entry["ref"]
            if ref in events:
                if events[ref] != entry["hash"]:
                    self._mismatch()
                    return False
                self._finish(u, ref)
            elif self._in_ledger(ref):
                # events.jsonl ya se compactó, pero el ciclo de vida dice que se escribió.
                self._finish(u, ref)
            else:
                inbox = self.store.inbox(ref)
                if inbox and inbox.get("hash") == entry["hash"] and inbox.get("envelope"):
                    # Caída entre el inbox y el evento: el evento se rehace del inbox.
                    self._write_event(u, ref, inbox, inbox["envelope"])
                # Sin inbox: queda pendiente. El offset no avanzó; Telegram lo vuelve a entregar.
        return True

    def _finish(self, update_id: int, ref: str) -> None:
        inbox = self.store.inbox(ref)
        if inbox and not inbox.get("journaled"):
            inbox["journaled"] = True
            self.store.save_inbox(ref, inbox)
        self.store.journal_written(update_id)

    def _mismatch(self) -> None:
        self._set_state("journal_mismatch")
        self._health("journal_mismatch")

    # --- cada update ----------------------------------------------------------------
    async def _handle_update(self, update: dict) -> bool:
        """False con journal_mismatch, o si no pudo salir de un grupo (FR-19): no se confirma."""
        u = int(update["update_id"])
        digest = canonical_hash(update)
        entry = self.store.journal().get(u)
        if entry and entry["written"]:
            return True                                    # FR-5 paso 1
        if entry and entry["hash"] != digest:
            self._mismatch()
            return False
        message = update.get("message") or update.get("edited_message")
        member = update.get("my_chat_member")
        chat = (message or member or {}).get("chat") or {}
        if chat.get("type") in GROUP_TYPES:
            return await self._leave(chat)                 # FR-19: sin salir, no se confirma
        if not message or chat.get("type") != "private":
            return True                                    # bloqueos y otros: nada que guardar
        if "edited_message" in update:
            original = self.store.find_message(int(chat["id"]), int(message["message_id"]))
            if not original:
                self.counters["edits_ignored"] += 1        # TELEGRAM.md §3
                return True
        else:
            original = None
        ref = entry["ref"] if entry else new_ref()
        if entry:
            if self._events_with({ref}).get(ref) == digest or self._in_ledger(ref):
                self._finish(u, ref)
                return True
        else:
            self.store.journal_begin(u, ref, digest)       # FR-5 paso 2
        inbox, envelope = self._build(ref, digest, message, original)
        self.store.save_inbox(ref, inbox)
        self._write_event(u, ref, inbox, envelope)
        return True

    def _sender(self, user: dict) -> tuple[bool, str]:
        """(en el roster, nombre). Por id o por @usuario; un duplicado no reconoce a nadie."""
        try:
            known = roster_mod.roster_telegram(self.roster_path)
        except OSError:
            return False, ""
        entry = known["ids"].get(str(int(user.get("id", 0))))
        username = (user.get("username") or "").lower()
        if entry is None and username:
            entry = known["usernames"].get(username)
        if entry is not None:
            return True, entry.get("name", "")
        name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p)
        return False, ev.safe_excerpt(name, 60) if name else ""

    def _build(self, ref: str, digest: str, message: dict, original: str | None) -> tuple[dict, dict]:
        user = message.get("from") or {}
        chat_id = int(message["chat"]["id"])
        thread = self.store.thread_for(chat_id, int(user.get("id", chat_id)))
        in_roster, name = self._sender(user)
        kind = message_kind(message)
        text = message.get("text") if kind == "text" else message.get("caption")
        text = text if isinstance(text, str) else ""
        filename = (message.get("document") or {}).get("file_name")
        visible = in_roster                                # Catch-All de Telegram: TG-3
        sent_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(message.get("date") or time.time())))
        envelope = ev.telegram_event(
            account=self.account, ref=ref, digest=digest, sender_name=name, kind=kind,
            text=text if visible else "",
            media_label=ev.telegram_kind_label(kind, filename=filename, show_name=visible),
            sent_at=sent_at, roster_match=in_roster, local_time=time.strftime("%H:%M:%S"),
            edits=original)
        inbox = {"type": envelope["event_type"], "chat": chat_id, "user": int(user.get("id", chat_id)),
                 "message_id": int(message["message_id"]), "thread": thread, "kind": kind, "text": text,
                 "filename": filename, "sent_at": sent_at, "received_at": now_utc(),
                 "in_roster": in_roster, "hash": digest, "edits": original,
                 "envelope": envelope, "journaled": False}
        return inbox, envelope

    def _write_event(self, update_id: int, ref: str, inbox: dict, envelope: dict) -> None:
        ev.append(self.journal, envelope)                  # FR-5 paso 3
        ledger.observed(self.ledger_path, envelope)
        inbox["journaled"] = True
        self.store.save_inbox(ref, inbox)
        if inbox.get("edits"):
            original = self.store.inbox(inbox["edits"])
            if original is not None:
                original.update(text=inbox["text"], edited=True)
                self.store.save_inbox(inbox["edits"], original)
        self.store.journal_written(update_id)             # FR-5 paso 4
        self._roll_day()
        if inbox["type"] == ev.TELEGRAM_RECEIVED:
            self.counters["received_today"] += 1
        self.log(envelope["notification_text"])

    async def _leave(self, chat: dict) -> bool:
        """
        FR-19: sale del grupo y sólo registra que salió, sin nombre ni quién lo agregó.

        True cuando ya no está en el grupo: salió, o Telegram dice que no estaba (400/403).
        Con red, 5xx o 429 reintenta con la misma espera que getUpdates y no regresa hasta
        salir, para que el offset no confirme un update del que nunca salió (Ximena, #616).
        False sólo si el servicio se detiene o el token dejó de valer: el update no se
        confirma y Telegram lo vuelve a entregar.
        """
        delay = self.backoff[0]
        while not self._stopping.is_set():
            try:
                await self._call("leaveChat", {"chat_id": int(chat["id"])})
            except tg_api.Unauthorized:
                self._set_state("token_invalid")
                self._health("token_invalid")
                return False
            except tg_api.RetryAfter as exc:
                await self._sleep(exc.retry_after or delay)
                continue
            except tg_api.NetworkError:
                await self._sleep(self._jitter(delay))
                delay = min(delay * 2, self.backoff[1])
                continue
            except tg_api.ApiError as exc:
                if exc.code in (400, 403):
                    self.log("un grupo o canal en el que el bot ya no está")
                    return True
                await self._sleep(self._jitter(delay))
                delay = min(delay * 2, self.backoff[1])
                continue
            self.counters["groups_left"] += 1
            self.log("salió de un grupo o canal")
            return True
        return False

    # --- cambio de token (FR-10, TELEGRAM.md §4) ------------------------------------
    def _prune_checks(self) -> None:
        now = time.monotonic()
        for cid in [c for c, v in self._checks.items() if v["expires"] < now]:
            del self._checks[cid]

    async def token_check(self, token: str) -> dict:
        """Prueba un token con getMe y getWebhookInfo; lo guarda en memoria 5 minutos."""
        if not isinstance(token, str) or not config.TOKEN_RE.match(token.strip()):
            raise Refused("invalid", field="token", reason="format")
        token = token.strip()
        candidate = tg_api.BotAPI(token, self.api_base)
        try:
            me = await asyncio.to_thread(candidate.call, "getMe", None, timeout=15.0)
            info = await asyncio.to_thread(candidate.call, "getWebhookInfo", None, timeout=15.0)
        except tg_api.Unauthorized:
            raise Refused("invalid", field="token", reason="getMe") from None
        except (tg_api.ApiError, tg_api.NetworkError):
            raise Refused("unavailable", detail="Telegram no contestó") from None
        self._prune_checks()
        cid = "c_" + secrets.token_hex(16)
        webhook = bool((info or {}).get("url"))
        self._checks[cid] = {"token": token, "expires": time.monotonic() + CHECK_TTL_S,
                             "username": me.get("username"), "webhook": webhook}
        return {"bot_username": me.get("username"), "same_token": token == self._token,
                "webhook": webhook, "check": cid}

    async def token_apply(self, check: str, confirm_dedicated, confirm_delete_webhook) -> dict:
        """FR-10 pasos 2 a 5: aplica el token del `check`, o vuelve al anterior."""
        self._prune_checks()
        if not isinstance(check, str) or not CHECK_RE.match(check) or check not in self._checks:
            raise Refused("not_found")
        entry = self._checks[check]
        if confirm_dedicated is not True:
            raise Refused("invalid", field="confirm_dedicated", reason="required")
        if entry["webhook"] and confirm_delete_webhook is not True:
            raise Refused("invalid", field="confirm_delete_webhook", reason="required")
        if self._apply_lock.locked():
            raise Refused("conflict", detail="ya hay un cambio de token en curso")
        async with self._apply_lock:
            del self._checks[check]
            if entry["token"] == self._token:
                return {"result": "unchanged", "bot_username": self.bot_username}
            return await self._switch(entry["token"], entry["webhook"])

    async def _switch(self, new_token: str, delete_webhook: bool) -> dict:
        old_token, old_api = self._token, self.api
        env = self.env_path or config.env_path()
        old_values = config.read(env)
        await self._halt_loop()
        new_api = tg_api.BotAPI(new_token, self.api_base)
        try:
            reason = await self._try_new(new_api, delete_webhook, env, old_values, new_token)
        except (OSError, ValueError) as exc:
            # No se pudo escribir el respaldo, telegram.env o la carpeta del bot (Ximena,
            # #617): igual que un 409, se vuelve al bot anterior y el lector no queda apagado.
            self.log(f"no se pudo guardar el token nuevo ({type(exc).__name__})")
            reason = "write"
        if reason is None:
            self.log(f"token cambiado: ahora @{self.bot_username}")
            if self.notify_owner:
                with contextlib.suppress(Exception):
                    self.notify_owner(self.bot_username or "")
            self._restart_loop()
            return {"result": "applied", "bot_username": self.bot_username}
        # Rollback (FR-10 paso 5): el token anterior y la carpeta de su bot, sin tocar la del nuevo.
        await self._drain_inflight()
        if old_values is not None:
            try:
                if config.token(config.read(env)) != config.token(old_values):
                    config.write(old_values, env)
            except (OSError, ValueError) as exc:
                self.log(f"no se pudo restaurar telegram.env ({type(exc).__name__}); "
                         f"el respaldo está en {config.BACKUP_NAME}")
        self.api, self._token = old_api, old_token
        self.store, self.account = None, ""
        self._health_sent = None
        self.log(f"cambio de token revertido ({reason})")
        self._set_state("starting")
        self._restart_loop()
        return {"result": "rollback", "reason": reason, "bot_username": None}

    async def _try_new(self, api, delete_webhook, env, old_values, new_token) -> str | None:
        """None si el bot nuevo quedó listo; si no, el motivo del rollback."""
        try:
            me = await asyncio.to_thread(api.call, "getMe", None, timeout=15.0)
            if delete_webhook:
                await asyncio.to_thread(api.call, "deleteWebhook", {"drop_pending_updates": False}, timeout=15.0)
        except tg_api.Unauthorized:
            return "getMe"
        except (tg_api.ApiError, tg_api.NetworkError):
            return "not_ready"
        config.save_backup(env)
        config.write(config.with_token(old_values, new_token), env)
        self.api, self._token = api, new_token
        self.bot_username = me.get("username")
        self._health_sent = None
        self._open_bot(int(me["id"]))
        if not self._reconcile():
            return "not_ready"
        deadline = time.monotonic() + self.ready_timeout_s
        delay = self.backoff[0]
        while time.monotonic() < deadline:
            wait = max(1, min(self.poll_timeout, int(deadline - time.monotonic())))
            params = {"offset": self.store.offset() or None, "timeout": wait,
                      "allowed_updates": ALLOWED_UPDATES}
            try:
                updates = await self._call("getUpdates", params, timeout=wait * 2)
            except tg_api.Conflict:
                return "409"
            except tg_api.Unauthorized:
                return "getMe"
            except tg_api.RetryAfter as exc:
                await self._sleep(min(exc.retry_after or delay, max(0.0, deadline - time.monotonic())))
                continue
            except (tg_api.ApiError, tg_api.NetworkError):
                await self._sleep(min(self._jitter(delay), max(0.0, deadline - time.monotonic())))
                delay = min(delay * 2, self.backoff[1])
                continue
            for update in updates or []:
                if not await self._handle_update(update):
                    return "not_ready"
                self.store.save_offset(int(update["update_id"]) + 1)
            self.last_poll_at = now_utc()
            self._set_state("running")
            return None
        return "not_ready"

    # --- control.sock (FR-6) --------------------------------------------------------
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        try:
            while True:
                try:
                    raw = await reader.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    await _write(writer, {"type": "error", "ref": None, "code": "bad_json"})
                    break
                if not raw:
                    break
                try:
                    msg = json.loads(raw)
                    if not isinstance(msg, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    await _write(writer, {"type": "error", "ref": None, "code": "bad_json"})
                    continue
                await _write(writer, await self.handle(msg))
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()

    async def handle(self, msg: dict) -> dict:
        rid = msg.get("id")
        if not isinstance(rid, str) or not REQUEST_ID.match(rid):
            return {"type": "error", "ref": None, "code": "missing_field", "field": "id"}
        by = msg.get("by")
        if not isinstance(by, str) or not BY_RE.match(by):
            return {"type": "error", "ref": rid, "code": "missing_field", "field": "by"}
        kind = msg.get("type")
        try:
            if kind == "telegram.status":
                data = self.status()
            elif kind == "telegram.token_check":
                data = await self.token_check(msg.get("token"))
            elif kind == "telegram.token_apply":
                data = await self.token_apply(msg.get("check"), msg.get("confirm_dedicated"),
                                              msg.get("confirm_delete_webhook"))
            else:
                return {"type": "error", "ref": rid, "code": "unknown_type"}
        except Refused as exc:
            out = {"type": "error", "ref": rid, "code": exc.code}
            if exc.detail:
                out["detail"] = exc.detail
            out.update(exc.extra)
            return out
        except Exception as exc:  # noqa: BLE001 - el cliente siempre recibe respuesta, sin detalles
            self.log(f"{kind} falló ({type(exc).__name__})")
            return {"type": "error", "ref": rid, "code": "unavailable"}
        return {"type": "result", "ref": rid, "ok": True, "data": data}


async def _write(writer: asyncio.StreamWriter, obj: dict) -> None:
    writer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()
