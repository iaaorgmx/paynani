"""
El servicio paynani-whatsapp (PRD #550, WHATSAPP_BRIDGE.md §11).

`WhatsAppService` lleva el puente (bridge.BridgeSupervisor), escribe en el diario lo que
llega (FR-11 a FR-18), aplica las reglas de envío (FR-19 a FR-22) y contesta en el socket
local `state/whatsapp/control.sock` a la terminal, la pasarela SMS y PaynaniWeb.

El QR y el código de vinculación sólo viven en memoria (FR-6a): el código sale una vez,
en el `result` de `whatsapp.link`; el QR sólo con su `link_id`.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import secrets
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT / "scripts"), str(_ROOT / "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import event as ev  # noqa: E402
import ledger  # noqa: E402
import phone  # noqa: E402
import roster as roster_mod  # noqa: E402

from .. import emoji as emoji_mod  # noqa: E402
from .. import web_uploads  # noqa: E402
from . import bridge, config  # noqa: E402
from .media import IMAGE_MAX_BYTES, image_mime  # noqa: E402
from .store import Store, now_utc  # noqa: E402

REQUEST_ID = re.compile(r"^q_[0-9a-f]{32}$")
LINK_ID = re.compile(r"^l_[0-9a-f]{32}$")
BY_RE = re.compile(r"^(terminal|agent|web|api|phone:[A-Za-z0-9_-]{1,40})$")
MAX_TEXT = 4000
MAX_LINE = 256 * 1024
QR_IDLE_S = 60          # §11: un QR sin nadie que pregunte se cancela
ENDED_KEEP_S = 300      # §11: un link_id terminado responde `ended` 5 minutos
LINK_WAIT_S = 20        # cuánto espera `whatsapp.link` el primer QR o código
CODE_TTL_S = 180
QR_TTL_S = 20
FILE_SEND_KINDS = ("agent", "terminal")
WEB_SEND_TIMEOUT_S = 150  # #670: la web espera 180 s; con 1 envío cada 3 s, 10 archivos son ~30 s,
                          # más lo que tarde el puente en subir cada uno


MAX_SOCKET_PATH = 103   # sun_path: 104 en macOS, 108 en Linux, con el NUL al final


class StartError(Exception):
    """El servicio no puede arrancar (por ejemplo, control.sock no se puede abrir)."""


class Refused(Exception):
    def __init__(self, code: str, detail: str = "", **extra: Any):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.extra = extra


def _iso_in(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def roster_phones(path: Path) -> dict[str, str]:
    """{e164: nombre} de la columna Phone de roster.md, la misma del SMS (FR-12)."""
    out: dict[str, str] = {}
    try:
        for entry in roster_mod.roster_phone_entries(path):
            out.setdefault(entry["phone"], entry.get("name", ""))
    except OSError:
        return {}
    return out


@dataclass
class Link:
    link_id: str
    mode: str
    by: str
    number: str | None
    started: float
    state: str = "waiting"          # waiting | ended
    reason: str | None = None
    qr: str | None = None
    code: str | None = None         # sólo hasta entregarlo en el result
    expires: float = 0.0
    last_poll: float = 0.0
    ended_at: float = 0.0
    first: asyncio.Event = field(default_factory=asyncio.Event)


class WhatsAppService:
    def __init__(self, state_dir: Path, *, journal: Path | None = None, roster_path: Path,
                 rules_root: Path | None = None, command: list[str] | None = None,
                 settings: dict[str, str] | None = None, log: Callable[[str], None] = print,
                 supervisor_opts: dict | None = None, qr_idle_s: float = QR_IDLE_S,
                 ended_keep_s: float = ENDED_KEEP_S, link_wait_s: float = LINK_WAIT_S):
        self.state_dir = Path(state_dir)
        self.layout = bridge.Layout(self.state_dir / "whatsapp")
        self.store = Store(self.layout.root)
        self.journal = journal or (self.state_dir / "events.jsonl")
        self.ledger_path = self.state_dir / "lifecycle.jsonl"
        self.roster_path = Path(roster_path)
        self.rules_root = Path(rules_root) if rules_root else None  # None: PAYNANI_RULES o el clon, como el SMS
        self.settings = settings or {}
        self.log = log
        self.qr_idle_s = qr_idle_s
        self.ended_keep_s = ended_keep_s
        self.link_wait_s = link_wait_s
        self.link: Link | None = None
        self._ended: dict[str, tuple[str | None, float]] = {}  # link_id -> (motivo, cuándo)
        self.watchers: set[asyncio.StreamWriter] = set()
        self.clients: set[asyncio.StreamWriter] = set()   # todas las conexiones abiertas a control.sock
        self._roster_mtime: float | None = None
        opts = dict(supervisor_opts or {})
        if command:
            opts["command"] = command
        self.sup = bridge.BridgeSupervisor(
            layout=self.layout, on_event=self._on_bridge, on_health=self._on_health,
            log=self.log, read_receipts=self.settings.get("WHATSAPP_READ_RECEIPTS") == "1",
            max_media_mb=config.setting("WHATSAPP_MAX_MEDIA_MB", self.settings), **opts)
        self._server: asyncio.AbstractServer | None = None
        self._tasks: list[asyncio.Task] = []
        self._bg: set[asyncio.Task] = set()
        self._sock_id: tuple[int, int] | None = None
        self._uploads_busy: set[str] = set()   # #670: los up_ de un envío en curso
        self._send_lock = asyncio.Lock()        # #670: los archivos de un envío salen seguidos

    # --- ciclo de vida ------------------------------------------------------------
    async def start(self) -> None:
        """
        Abre control.sock antes de lanzar el puente: si el socket no se puede abrir
        (StartError, UnsafePath), no queda un puente huérfano y quien llama sale limpio.
        """
        self.layout.prepare()  # UnsafePath antes de abrir nada
        if len(os.fsencode(str(self.socket_path))) > MAX_SOCKET_PATH:
            raise StartError(f"la ruta de control.sock mide más de {MAX_SOCKET_PATH} bytes "
                             f"(límite de los sockets Unix): usa un --state más corto")
        try:
            await self._serve()
        except OSError as exc:
            raise StartError(f"no se pudo abrir control.sock ({type(exc).__name__}: {exc})") from None
        self.sup.allowed = self._allowed()
        self._tasks.append(asyncio.create_task(self.sup.run()))
        self._tasks.append(asyncio.create_task(self._loops()))

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            # Primero se cierran las conexiones: desde Python 3.12, wait_closed() espera a
            # que terminen todas, y la de whatsapp.watch de la pasarela no termina sola.
            for w in list(self.clients):
                with contextlib.suppress(Exception):
                    w.transport.abort()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 5)
        await self.sup.stop()
        for t in self._tasks:
            if not t.done():
                if t is self._tasks[0]:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(t, 15)
                else:
                    t.cancel()
        if self._sock_id:
            with contextlib.suppress(FileNotFoundError):
                st = os.lstat(self.socket_path)
                if (st.st_dev, st.st_ino) == self._sock_id:  # sólo el socket que abrió este servicio
                    os.unlink(self.socket_path)

    @property
    def socket_path(self) -> Path:
        return self.layout.root / "control.sock"

    async def _serve(self) -> None:
        path = self.socket_path
        try:
            st = os.lstat(path)
            if not stat.S_ISSOCK(st.st_mode):
                raise bridge.UnsafePath(f"{path} existe y no es un socket")
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

    async def _loops(self) -> None:
        while True:
            await asyncio.sleep(1)
            try:
                await self._link_tick()
                await self._roster_tick()
            except Exception as exc:  # noqa: BLE001 - un error suelto no detiene el servicio
                self.log(f"whatsapp: revisión periódica falló ({type(exc).__name__})")

    # --- roster y allowed (FR-12, FR-20) -------------------------------------------
    def _phones(self) -> dict[str, str]:
        return roster_phones(self.roster_path)

    def _allowed(self) -> list[str]:
        """La segunda barrera del puente: del roster y que ya escribieron (FR-20)."""
        phones = self._phones()
        return sorted(n for n in self.store.wrote_since_link() if n in phones)

    async def _push_allowed(self) -> None:
        with contextlib.suppress(bridge.BridgeError):
            await self.sup.set_allowed(self._allowed())

    def _push_allowed_soon(self) -> None:
        """Desde un aviso del puente: el lector de stdout no puede esperar su propia respuesta."""
        task = asyncio.create_task(self._push_allowed())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _roster_tick(self) -> None:
        try:
            mtime = self.roster_path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self._roster_mtime:
            self._roster_mtime = mtime
            await self._push_allowed()
            self._notify("threads")

    def _rules_note(self, e164: str) -> dict | None:
        from paynani_lib import roster_edit, rules as rules_mod

        try:
            _, members = roster_edit.members(self.roster_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return None
        member = next((m for m in members if e164 in m["phones"]), None)
        return rules_mod.notice(member["rules"] if member else None, self.rules_root)

    def _catch_all(self) -> dict | None:
        from paynani_lib import rules as rules_mod

        try:
            return rules_mod.catch_all_notice("whatsapp", self.rules_root)  # sólo el de WhatsApp (PRD #576 FR-6)
        except Exception:  # noqa: BLE001 - sin Catch-All, el mensaje igual entra
            return None

    def _catch_all_active(self) -> bool:
        note = self._catch_all()
        return bool(note) and note.get("status") == "active"

    # --- lo que avisa el puente -------------------------------------------------------
    async def _on_bridge(self, msg: dict) -> None:
        kind = msg.get("type")
        try:
            if kind == "message":
                await self._message(msg)
            elif kind == "reaction":
                self._reaction(msg)
            elif kind == "call":
                self._call(msg)
            elif kind == "receipt":
                self.store.record_sent({"receipt": True, "key_id": msg.get("key_id"),
                                        "status": msg.get("status"), "at": msg.get("at") or now_utc()})
                self._notify("threads")
            elif kind == "status":
                if msg.get("state") == "unlinked":
                    self.store.mark_unlinked()
                self._notify("status")
            elif kind in ("link.qr", "link.code", "link.ended"):
                await self._link_event(msg)
        except (OSError, ValueError) as exc:
            self.log(f"whatsapp: no se pudo guardar {kind} ({type(exc).__name__}: {exc})")

    def _me(self) -> str | None:
        return self.sup.state.get("me") or self.store.link_info().get("me")

    async def _message(self, msg: dict) -> None:
        me = self._me()
        account = ev.whatsapp_account(me)
        chat = str(msg.get("chat") or "")
        key_id = str(msg.get("key_id") or "")
        if not chat or not key_id:
            return
        mhash = ev.whatsapp_message_hash(account, chat, key_id)
        existing = self.store.inbox(mhash)
        if existing and existing.get("journaled"):
            return  # FR-11a: WhatsApp lo volvió a entregar
        sender = msg.get("from") or {}
        e164 = phone.to_e164(sender.get("e164")) if sender.get("e164") else None
        lid = sender.get("lid")
        phones = self._phones()
        in_roster = bool(e164 and e164 in phones)
        name = phones.get(e164, "") if in_roster else ""
        rules_note = self._rules_note(e164) if in_roster else None
        catch = self._catch_all() if not in_roster else None
        visible = in_roster or (catch or {}).get("status") == "active"
        media = msg.get("media") if isinstance(msg.get("media"), dict) else None
        kind = str(msg.get("kind") or "other")
        label = ev.whatsapp_kind_label(kind, seconds=(media or {}).get("seconds"),
                                       voice_note=bool((media or {}).get("voice_note")),
                                       filename=(media or {}).get("filename"), show_name=visible)
        text = msg.get("text") if isinstance(msg.get("text"), str) else ""
        reply = self._reply_of(msg.get("quote"), account, chat, e164)
        envelope = ev.whatsapp_event(
            account=account, message_hash=mhash, e164=e164, lid=lid, sender_name=name, kind=kind,
            text=text if visible else "", media_label=label if visible else "", sent_at=str(msg.get("sent_at") or ""),
            roster_match=in_roster, local_time=time.strftime("%H:%M:%S"), rules=rules_note, catch_all=catch,
            reply_excerpt=(reply or {}).get("excerpt") if visible else None)
        data = {"type": "whatsapp.received", "account_me": me, "chat": chat, "key_id": key_id,
                "from_e164": e164, "lid": lid, "push_name": msg.get("push_name"), "kind": kind,
                "text": text, "media": media, "sent_at": msg.get("sent_at"), "received_at": now_utc(),
                "catch_all": (catch or {}).get("status") == "active",
                "event_id": envelope["event_id"], "journaled": False}
        if reply is not None:
            data["reply_to"] = reply
        self.store.save_inbox(mhash, data)
        ev.append(self.journal, envelope)
        ledger.observed(self.ledger_path, envelope)
        data["journaled"] = True
        self.store.save_inbox(mhash, data)
        if not visible:
            self.store.forget_media(mhash)  # FR-16a: el archivo no se queda
        self.log(envelope["notification_text"])
        if in_roster:
            self._push_allowed_soon()
        self._notify("threads")

    def _reaction(self, msg: dict) -> None:
        """
        PRD #685 FR-13, FR-16a: la reacción de un contacto a un mensaje que paynani tiene. Guarda
        la suya (`theirs`) y escribe un evento `kind: "reaction"`. Una reacción a un mensaje que
        no está, o una que no cambia nada, no deja nada.
        """
        me = self._me()
        account = ev.whatsapp_account(me)
        chat = str(msg.get("chat") or "")
        key_id = str(msg.get("key_id") or "")
        target = str((msg.get("target") or {}).get("key_id") or "")
        if not chat or not key_id or not target:
            return
        mhash = ev.whatsapp_message_hash(account, chat, key_id)
        pending = self.store.inbox(mhash)
        if (pending or {}).get("journaled"):
            return  # FR-11a: WhatsApp la volvió a entregar
        sender = msg.get("from") or {}
        e164 = phone.to_e164(sender.get("e164")) if sender.get("e164") else None
        original = self.store.inbox(ev.whatsapp_message_hash(account, chat, target))
        if original and original.get("journaled") and original.get("type", "whatsapp.received") == "whatsapp.received":
            ref = original.get("event_id")
        else:
            original = next((m for m in self.store.sent()
                             if m.get("key_id") == target and (e164 is None or m.get("to") == e164)), None)
            ref = (original or {}).get("id")
        if not ref:
            return
        new = str(msg.get("emoji") or "")
        before = (pending or {}).get("old") if pending else self.store.reactions().get(ref, {}).get("theirs") or ""
        before = before or ""
        if not pending and emoji_mod.emoji_key(before) == emoji_mod.emoji_key(new):
            return                  # nada cambió; con `pending`, una caída dejó el aviso sin escribir
        phones = self._phones()
        in_roster = bool(e164 and e164 in phones)
        catch = self._catch_all() if not in_roster else None
        visible = in_roster or (catch or {}).get("status") == "active"
        envelope = ev.whatsapp_reaction_event(
            account=account, message_hash=mhash, e164=e164, lid=sender.get("lid"),
            sender_name=phones.get(e164, "") if in_roster else "", roster_match=in_roster,
            emoji=new or before, removed=not new, excerpt=quote_excerpt(original) if visible else "",
            sent_at=str(msg.get("sent_at") or ""), local_time=time.strftime("%H:%M:%S"),
            rules=self._rules_note(e164) if in_roster else None, catch_all=catch)
        data = {"type": "whatsapp.reaction", "account_me": me, "chat": chat, "key_id": key_id,
                "from_e164": e164, "lid": sender.get("lid"), "target": ref, "emoji": new, "old": before,
                "sent_at": msg.get("sent_at"), "received_at": now_utc(),
                "catch_all": (catch or {}).get("status") == "active",
                "event_id": envelope["event_id"], "journaled": False}
        self.store.save_inbox(mhash, data)
        self.store.set_reaction(ref, "theirs", new)
        ev.append(self.journal, envelope)
        ledger.observed(self.ledger_path, envelope)
        data["journaled"] = True
        self.store.save_inbox(mhash, data)
        self.log(envelope["notification_text"])
        self._notify("reaction", ref=ref)

    def _reply_of(self, quote, account: str, chat: str, e164: str | None) -> dict | None:
        """
        PRD #685 F2 (FR-9): la cita de un mensaje que entra, de `quote` del puente. `{ref,
        excerpt, from_me}`: `ref` es el `wa:` o `wo_` del original si paynani lo tiene, o null
        si es de antes (entonces el extracto es el que mandó WhatsApp). Ningún key_id sale.
        """
        if not isinstance(quote, dict) or not quote.get("key_id"):
            return None
        key_id = str(quote["key_id"])
        from_me = bool(quote.get("from_me"))
        original = None
        if from_me:
            original = next((m for m in self.store.sent()
                             if m.get("key_id") == key_id and (e164 is None or m.get("to") == e164)), None)
            ref = (original or {}).get("id")
        else:
            original = self.store.inbox(ev.whatsapp_message_hash(account, chat, key_id))
            ref = (original or {}).get("event_id") if original and original.get("journaled") else None
            original = original if ref else None
        excerpt = quote_excerpt(original) if original else quote_excerpt(
            {"text": quote.get("text"), "kind": quote.get("kind"), "media": {"filename": quote.get("filename")}})
        return {"ref": ref, "excerpt": excerpt, "from_me": from_me}

    def _call(self, msg: dict) -> None:
        status = msg.get("status")
        kind = ev.CALL_MISSED if status == "missed" else ev.CALL_ANSWERED if status == "answered" else None
        if not kind or not msg.get("call_id"):
            return
        sender = msg.get("from") or {}
        e164 = phone.to_e164(sender.get("e164")) if sender.get("e164") else None
        phones = self._phones()
        in_roster = bool(e164 and e164 in phones)
        envelope = ev.whatsapp_call_event(
            kind=kind, account=ev.whatsapp_account(self._me()), call_id=str(msg["call_id"]), e164=e164,
            caller_name=phones.get(e164, "") if in_roster else "", started_at=str(msg.get("at") or ""),
            roster_match=in_roster, local_time=time.strftime("%H:%M:%S"), video=bool(msg.get("video")))
        ev.append(self.journal, envelope)
        ledger.observed(self.ledger_path, envelope)
        self.log(envelope["notification_text"])

    def _on_health(self, kind: str, reason: str | None) -> None:
        envelope = ev.whatsapp_health_event(state=kind, account=ev.whatsapp_account(self._me()),
                                            local_time=time.strftime("%H:%M:%S"), reason=reason)
        try:
            ev.append(self.journal, envelope)
            ledger.observed(self.ledger_path, envelope)
        except (OSError, ValueError) as exc:
            self.log(f"whatsapp: no se pudo escribir whatsapp.health ({exc})")
            return
        self.log(envelope["notification_text"])

    # --- vincular (FR-6, FR-6a, §11) ------------------------------------------------
    async def _link_event(self, msg: dict) -> None:
        link = self.link
        kind = msg["type"]
        if kind == "link.ended":
            reason = msg.get("reason")
            if reason == "linked":
                self.store.mark_linked(msg.get("me") or self.sup.state.get("me"))
                self._push_allowed_soon()
            if link and link.state == "waiting" and reason != "replaced":
                self._end_link(link, reason)
            self._notify("status")
            return
        if not link or link.state != "waiting":
            return
        if kind == "link.qr" and link.mode == "qr":
            link.qr = msg.get("qr")
            link.expires = time.time() + QR_TTL_S
        elif kind == "link.code" and link.mode == "code" and not link.first.is_set():
            link.code = msg.get("code")
            link.expires = time.time() + CODE_TTL_S
        link.first.set()

    def _end_link(self, link: Link, reason: str | None) -> None:
        link.state = "ended"
        link.reason = reason
        link.qr = None
        link.code = None
        link.ended_at = time.time()
        link.first.set()
        self._ended[link.link_id] = (reason, link.ended_at)

    async def _link_tick(self) -> None:
        now = time.time()
        for lid, (_, at) in list(self._ended.items()):
            if now - at > self.ended_keep_s:
                del self._ended[lid]
        link = self.link
        if not link:
            return
        if link.state == "waiting" and link.mode == "qr" and now - link.last_poll > self.qr_idle_s:
            self.log("whatsapp: nadie pregunta por el QR; se cancela la vinculación")
            self._end_link(link, "canceled")
            with contextlib.suppress(bridge.BridgeError):
                await self.sup.request("link.cancel")
            self._notify("status")
        elif link.state == "ended" and now - link.ended_at > self.ended_keep_s:
            self.link = None

    def _linking(self) -> dict | None:
        link = self.link
        if not link or link.state != "waiting":
            return None
        return {"by": link.by, "mode": link.mode, "expires_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(link.expires or link.started + CODE_TTL_S)),
            "expires_in_s": max(0, int((link.expires or link.started + CODE_TTL_S) - time.time()))}

    async def link_start(self, mode: str, number: str | None, by: str) -> dict:
        if mode not in ("qr", "code"):
            raise Refused("invalid", field="mode", reason="mode")
        if mode == "code":
            number = phone.to_e164(number) if number else None
            if not number:
                raise Refused("invalid", "el código necesita el número del teléfono", field="number",
                              reason="number")
        if self.sup.state.get("state") == "connected":
            raise Refused("already_linked")
        if self.link and self.link.state == "waiting":
            self._end_link(self.link, "replaced")
        link = Link(link_id="l_" + secrets.token_hex(16), mode=mode, by=by, number=number,
                    started=time.time(), last_poll=time.time())
        self.link = link
        fields = {"mode": mode, **({"number": number} if number else {})}
        try:
            await self.sup.request("link", **fields)
        except bridge.BridgeError as exc:
            self._end_link(link, "failed")
            raise Refused(_bridge_code(exc.code), exc.detail or "") from None
        try:
            await asyncio.wait_for(link.first.wait(), self.link_wait_s)
        except asyncio.TimeoutError:
            pass
        got = link.qr if mode == "qr" else link.code
        if link.state != "waiting" or not got:
            # Sin la primera credencial no hay éxito vacío: se cancela y se dice (§11).
            reason = link.reason if link.state != "waiting" else "timeout"
            if link.state == "waiting":
                self._end_link(link, "failed")
                with contextlib.suppress(bridge.BridgeError):
                    await self.sup.request("link.cancel")
            self._notify("status")
            raise Refused("unavailable", f"WhatsApp no entregó el {'QR' if mode == 'qr' else 'código'} ({reason})")
        self.log(f"whatsapp: vinculación por {mode} pedida desde {by}")
        self._notify("status")
        out = {"link_id": link.link_id, "mode": mode,
               "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(link.expires)),
               "expires_in_s": max(0, int(link.expires - time.time()))}
        if mode == "qr":
            out["qr"] = link.qr
        else:
            out["code"] = link.code
            link.code = None  # FR-6a: una sola vez
        return out

    def link_current(self, link_id: str) -> dict:
        link = self.link
        if not LINK_ID.match(str(link_id or "")):
            raise Refused("not_found")
        if not link or not secrets.compare_digest(link.link_id, link_id) or link.state == "ended":
            ended = self._ended.get(link_id)
            if ended:
                return {"state": "ended", "reason": ended[0]}
            raise Refused("not_found")
        link.last_poll = time.time()
        out = {"state": "waiting", "mode": link.mode,
               "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(link.expires)),
               "expires_in_s": max(0, int(link.expires - time.time()))}
        if link.mode == "qr":
            out["qr"] = link.qr
        return out

    async def link_cancel(self) -> dict:
        if self.link and self.link.state == "waiting":
            self._end_link(self.link, "canceled")
        with contextlib.suppress(bridge.BridgeError):
            await self.sup.request("link.cancel")
        self._notify("status")
        return {}

    async def unlink(self) -> dict:
        try:
            data = await self.sup.request("logout", _timeout=20)
        except bridge.BridgeError as exc:
            raise Refused(_bridge_code(exc.code), exc.detail or "") from None
        self.store.mark_unlinked()
        # El puente ya cerró la sesión. `status` no espera a que el puente mande su
        # siguiente mensaje de estado para decir `unlinked` (#604).
        if self.sup.state.get("state") != "unlinked":
            self.sup._set_state({"type": "status", "state": "unlinked", "me": None,
                                 "since": now_utc(), "reason": "unlink"})
        await self._push_allowed()
        self._notify("status")
        return {"remote": bool(data.get("remote"))}

    def status(self) -> dict:
        st = self.sup.state
        state = st.get("state")
        if state in (None, "unknown", "bridge_down"):
            state = "connecting" if self.store.link_info() else "unlinked"
        return {"state": state, "me": st.get("me") or self.store.link_info().get("me"),
                "since": st.get("since"), "linking": self._linking(), "link_number": None,
                "web_files": True,          # #670 FR-8: whatsapp.send acepta `uploads` de PaynaniWeb
                "replies": True,            # PRD #685 F2: whatsapp.send acepta `reply_to`
                "reactions": "any"}         # PRD #685 F3: whatsapp.react acepta cualquier emoji

    # --- enviar (FR-19 a FR-23) ----------------------------------------------------------
    def attach_dirs(self) -> list[Path]:
        dirs = [self.layout.outbox]
        for raw in (self.settings.get("WHATSAPP_ATTACH_DIRS") or "").split(":"):
            raw = raw.strip()
            if raw and os.path.isabs(raw):
                dirs.append(Path(raw))
        return dirs

    def check_file(self, raw: str) -> Path:
        """FR-22: un archivo regular, sin enlaces, dentro de outbox/ o WHATSAPP_ATTACH_DIRS."""
        if not isinstance(raw, str) or not os.path.isabs(raw):
            raise Refused("not_allowed", "la ruta debe ser absoluta", reason="file_path")
        path = Path(raw)
        try:
            st = os.lstat(path)
        except OSError:
            raise Refused("not_allowed", "el archivo no existe", reason="file_missing") from None
        if not stat.S_ISREG(st.st_mode):
            raise Refused("not_allowed", "no es un archivo regular", reason="file_type")
        real_parent = os.path.realpath(path.parent)
        for d in self.attach_dirs():
            try:
                allowed = os.path.realpath(d)
            except OSError:
                continue
            if real_parent == allowed or real_parent.startswith(allowed + os.sep):
                return Path(real_parent) / path.name
        raise Refused("not_allowed", "fuera de outbox/ y de WHATSAPP_ATTACH_DIRS", reason="file_dir")

    async def send(self, number: str, text: str, by: str, file: str | None = None,
                   uploads: list | None = None, reply_to=None) -> dict:
        e164 = phone.to_e164(number) if number else None
        if not e164:
            raise Refused("invalid", "el número no es E.164", field="number", reason="number")
        text = text if isinstance(text, str) else ""
        if len(text) > MAX_TEXT:
            raise Refused("invalid", "más de 4,000 caracteres", field="text", reason="too_long")
        if uploads is not None and (author(by) != "owner" or file):
            raise Refused("invalid", "sólo el dueño manda archivos subidos, y sin `file` (#670)", field="uploads")
        if not text.strip() and not file and not uploads:
            raise Refused("invalid", "texto vacío", field="text", reason="empty")
        phones = self._phones()
        if e164 not in phones:
            raise Refused("not_allowed", "el número no está en roster.md (Phone)", reason="roster")
        # `by` es sólo una etiqueta (§11): la regla vale igual para todos los que llaman.
        from paynani_lib import reply_policy
        never, _ = reply_policy.check(self.roster_path, "sms", [e164], rules_root=self.rules_root)
        if never:
            raise Refused("not_allowed", "las reglas del contacto dicen reply.sms: never", reason="reply_never")
        if e164 not in self.store.wrote_since_link():
            raise Refused("not_started", "el contacto no ha escrito por WhatsApp desde que se vinculó")
        if reply_to is not None and not isinstance(reply_to, str):
            raise Refused("invalid", "reply_to", field="reply_to")
        quote = self._reply_target(e164, reply_to) if reply_to is not None else None
        if uploads is not None:
            return await self._send_uploads(e164, text, by, uploads, quote)
        path = self.check_file(file) if file else None
        wait = self._rate_wait(1)
        if wait:
            raise Refused("rate_limited", f"espera {wait} s", retry_after_s=wait)
        sid = self.store.new_sent_id()
        record = {"id": sid, "to": e164, "text": text, "by": author(by), "at": now_utc(),
                  "status": "sending", "file": path.name if path else None}
        if quote is not None:
            record["reply_to"] = _quote_record(quote)
        self.store.record_sent(record)
        self.store.rate_take()
        fields: dict[str, Any] = {"to": e164, "text": text}
        if quote is not None and quote.get("bridge"):
            fields["quote"] = quote["bridge"]
        if path:
            import mimetypes
            fields["file"] = {"path": str(path), "mime": mimetypes.guess_type(path.name)[0]
                              or "application/octet-stream", "filename": path.name}
        try:
            data = await self.sup.request("send", **fields)
        except bridge.BridgeError as exc:
            self.store.record_sent({"id": sid, "status": "failed", "error": exc.code})
            self._notify("threads")
            raise Refused(_bridge_code(exc.code), exc.detail or "") from None
        self.store.record_sent({"id": sid, "status": "sent", "key_id": data.get("key_id")})
        self._notify("threads")
        out = {"message": {"id": sid, "dir": "out", "by": record["by"], "at": record["at"], "kind": "file"
                           if path else "text", "text": text, "status": "sent"}}
        if quote is not None:
            out["reply"] = "native" if quote.get("bridge") else "dropped"
        return out

    def _reply_target(self, e164: str, ref: str) -> dict:
        """
        PRD #685 F2 (contrato de FR-14): el mensaje que se cita, de la conversación con este
        número, que entró (`wa:`) o que salió (`wo_`). `{"ref", "excerpt", "bridge"}`; `bridge`
        es lo que el puente necesita (`key_id`, `from_me`, `text`), o None si el original no
        tiene `key_id` (no salió): entonces se manda sin cita (`dropped`).
        """
        if ref.startswith("wa:"):
            original = next((m for m in self.store.received() if m.get("event_id") == ref), None)
            party = (original or {}).get("from_e164")
            from_me = False
        elif ref.startswith("wo_"):
            original = next((m for m in self.store.sent() if m.get("id") == ref), None)
            party = (original or {}).get("to")
            from_me = True
        else:
            original, party, from_me = None, None, False
        if not original:
            raise Refused("invalid", "ese mensaje no existe", field="reply_to", reason="not_found")
        if party != e164:
            raise Refused("invalid", "ese mensaje es de otra conversación", field="reply_to", reason="other_thread")
        excerpt = quote_excerpt(original)
        key_id = original.get("key_id")
        bridge_quote = ({"key_id": str(key_id), "from_me": from_me, "text": str(original.get("text") or "")[:1000]}
                        if key_id else None)
        return {"ref": ref, "excerpt": excerpt, "bridge": bridge_quote}

    async def react(self, ref: str, emoji: str, by: str) -> dict:
        """
        PRD #685 F3 (contrato de FR-14): pone (`emoji`) o quita (`""`) la reacción de la cuenta
        en un mensaje (`wa:` o `wo_`). Una por mensaje; otra la reemplaza. Cualquier emoji, pero
        uno solo (`invalid`, `reason: bad_emoji`). Fuera del roster es `not_allowed` (FR-17). No
        cuenta para el tope de envíos. Devuelve `{"ref", "reactions"}`.
        """
        if not isinstance(ref, str) or not ref:
            raise Refused("missing_field", "ref", field="ref")
        if not isinstance(emoji, str):
            raise Refused("invalid", "emoji", field="emoji")
        emoji = emoji.strip()
        if emoji and not emoji_mod.valid_emoji(emoji):
            raise Refused("invalid", "un solo emoji", field="emoji", reason="bad_emoji")
        if ref.startswith("wa:"):
            original = next((m for m in self.store.received() if m.get("event_id") == ref), None)
            party, from_me = (original or {}).get("from_e164"), False
        elif ref.startswith("wo_"):
            original = next((m for m in self.store.sent() if m.get("id") == ref), None)
            party, from_me = (original or {}).get("to"), True
        else:
            original, party, from_me = None, None, False
        if not original or not original.get("key_id"):
            raise Refused("not_found", "ese mensaje no existe")
        if not party or party not in self._phones():
            raise Refused("not_allowed", "el número no está en roster.md (Phone)", reason="roster")
        current = self.store.reactions().get(ref, {})
        if emoji_mod.emoji_key(current.get("ours") or "") != emoji_mod.emoji_key(emoji):
            target = {"key_id": str(original["key_id"]), "from_me": from_me}
            if not from_me and original.get("chat"):
                target["chat"] = original["chat"]
            try:
                await self.sup.request("react", to=party, target=target, emoji=emoji)
            except bridge.BridgeError as exc:
                raise Refused(_bridge_code(exc.code), exc.detail or "") from None
            current = self.store.set_reaction(ref, "ours", emoji)
            self.log(f"whatsapp.react {ref}" + ("" if emoji else " (quitada)"))
            self._notify("reaction", ref=ref)
        return {"ref": ref, "reactions": _reactions_view(current)}

    def _rate_wait(self, count: int) -> int | None:
        """FR-21 para `count` envíos seguidos: None si el primero sale ya y caben todos hoy."""
        interval = config.setting("WHATSAPP_SEND_INTERVAL_S", self.settings)
        per_day = config.setting("WHATSAPP_SEND_PER_DAY", self.settings)
        wait = self.store.rate_check(interval, per_day)
        if wait or count <= 1:
            return wait
        # No caben todos hoy: mejor no mandar ninguno que dejar el mensaje a medias.
        room = per_day - (count - 1)
        if room <= 0:
            return 86400
        return self.store.rate_check(0, room)

    async def _send_uploads(self, e164: str, text: str, by: str, ups, quote: dict | None = None) -> dict:
        """
        #670 FR-6: los archivos que el dueño subió desde PaynaniWeb (`web_uploads`), un
        `send` del puente por archivo, con el texto como pie del primero. Cada uno cuenta
        para FR-21: entre uno y otro se espera el intervalo, en vez de rechazarlo. Un `up_`
        sale una sola vez: mientras se manda nadie más lo toma, y se borra en cuanto sale.
        """
        try:
            files = web_uploads.take(self.layout.root, ups)
        except web_uploads.Rejected as exc:
            raise Refused(exc.code, exc.detail, field="uploads") from None
        refs = [f["upload"] for f in files]
        if self._uploads_busy.intersection(refs):
            raise Refused("bad_upload", "otro envío ya los está mandando", field="uploads")
        self._uploads_busy.update(refs)       # antes del primer await
        try:
            async with self._send_lock:
                wait = self._rate_wait(len(files))
                if wait:
                    raise Refused("rate_limited", f"espera {wait} s", retry_after_s=wait)
                return await self._send_files(e164, text, by, files, quote)
        finally:
            self._uploads_busy.difference_update(refs)

    async def _send_files(self, e164: str, text: str, by: str, files: list[dict], quote: dict | None = None) -> dict:
        sid = self.store.new_sent_id()
        record = {"id": sid, "to": e164, "text": text, "by": author(by), "at": now_utc(), "status": "sending",
                  "file": files[0]["name"], "files": [self._keep_photo(f) for f in files], "parts": len(files)}
        if quote is not None:
            record["reply_to"] = _quote_record(quote)
        self.store.record_sent(record)
        interval = config.setting("WHATSAPP_SEND_INTERVAL_S", self.settings)
        deadline = time.monotonic() + WEB_SEND_TIMEOUT_S
        delivered = 0
        try:
            for i, f in enumerate(files):
                if i:
                    pause = self.store.rate_check(interval, 1 << 30) or 0
                    if time.monotonic() + pause > deadline:
                        raise Refused("timeout", "no alcanzó el tiempo para mandar todos")
                    await asyncio.sleep(pause)
                self.store.rate_take()
                extra = {"quote": quote["bridge"]} if i == 0 and quote and quote.get("bridge") else {}
                try:
                    data = await self.sup.request(
                        "send", to=e164, text=text if i == 0 else "",
                        file={"path": str(self.layout.root / web_uploads.DIR / f["upload"]), "mime": f["mime"],
                              "filename": f["name"]}, **extra)
                except bridge.BridgeError as exc:
                    raise Refused(_bridge_code(exc.code), exc.detail or "") from None
                web_uploads.drop(self.layout.root, f["upload"])   # un solo uso: ya salió
                delivered += 1
                self.store.record_sent({"id": sid, "key_id": data.get("key_id"), "delivered": delivered})
        except Refused as exc:
            # Lo que ya salió no se repite al reintentar; lo demás queda para otro intento.
            self.store.record_sent({"id": sid, "status": "partial" if delivered else "failed",
                                    "delivered": delivered, "error": exc.code})
            self._notify("threads")
            if delivered:
                exc.extra["sent_uploads"] = [f["upload"] for f in files[:delivered]]
            raise
        self.store.record_sent({"id": sid, "status": "sent"})
        self._notify("threads")
        out = {"message": {"id": sid, "dir": "out", "by": record["by"], "at": record["at"], "kind": "file",
                           "text": text, "status": "sent", "files": [_public_file(x) for x in record["files"]]}}
        if quote is not None:
            out["reply"] = "native" if quote.get("bridge") else "dropped"
        return out

    def _keep_photo(self, f: dict) -> dict:
        """Lo que queda en sent.jsonl de un archivo de la web; una foto, con su copia en media/ (FR-7)."""
        item = {"name": f["name"], "kind": f.get("kind"), "size": f["size"]}
        data = f.get("data") or b""
        mime = image_mime(data[:16]) if f.get("kind") == "image" else None
        if mime and len(data) <= IMAGE_MAX_BYTES:
            import hashlib
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime, "bin")
            path = self.layout.media / f"{hashlib.sha256(data).hexdigest()}.{ext}"
            with contextlib.suppress(OSError):
                if not path.exists():
                    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
                    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp, path)
                item["media"] = {"path": str(path), "mime": mime, "bytes": len(data)}
        return item

    # --- hilos (FR-16a, FR-24, FR-25) -------------------------------------------------
    def _messages(self) -> dict[str, list[dict]]:
        """{número o lid: [mensajes]} con todo lo recibido y enviado."""
        out: dict[str, list[dict]] = {}
        for m in self.store.received():
            party = m.get("from_e164") or m.get("lid") or "?"
            media = m.get("media") or None
            out.setdefault(party, []).append({
                "id": m.get("event_id"), "dir": "in", "at": m.get("received_at"), "kind": m.get("kind"),
                "text": m.get("text"), "catch_all": bool(m.get("catch_all")),
                "media": {k: media.get(k) for k in ("mime", "bytes", "filename", "seconds")} | {"kind": m.get("kind")}
                if media else None})
            if isinstance(m.get("reply_to"), dict):
                out[party][-1]["_reply"] = m["reply_to"]      # PRD #685 F2; se publica en thread()
        for s in self.store.sent():
            item = {"id": s.get("id"), "dir": "out", "by": s.get("by"), "at": s.get("at"),
                    "kind": "file" if s.get("file") else "text", "text": s.get("text"), "status": s.get("status")}
            if s.get("files"):          # #670 FR-7: lo que el dueño mandó desde la web, sin rutas
                item["files"] = [_public_file(f) for f in s["files"]]
            elif s.get("file"):
                item["files"] = [{"name": s["file"]}]
            if isinstance(s.get("reply_to"), dict):
                item["_reply"] = s["reply_to"]
            if not s.get("key_id"):
                item["_noid"] = True    # #707: sin key_id no se puede citar ni reaccionar
            out.setdefault(s.get("to") or "?", []).append(item)
        for msgs in out.values():
            msgs.sort(key=lambda m: m.get("at") or "", reverse=True)
        return out

    def _visible(self, msg: dict, in_roster: bool, catch_active: bool) -> bool:
        return in_roster or (msg.get("dir") == "in" and msg.get("catch_all") and catch_active)

    def _public(self, msg: dict, visible: bool) -> dict:
        if not visible:
            return {"id": msg.get("id"), "dir": msg.get("dir"), "at": msg.get("at"), "hidden": True}
        return {k: v for k, v in msg.items() if k != "catch_all" and not k.startswith("_")}

    def _agent_name(self) -> str:
        """El nombre del agente en una cita a lo que mandamos: AGENT_EMAIL_FROM_NAME."""
        with contextlib.suppress(Exception):
            from paynani_lib import envfile  # noqa: PLC0415
            return str(envfile.read_env().get("AGENT_EMAIL_FROM_NAME") or "")
        return ""

    def _public_quote(self, q: dict, contact_name: str, msgs: list[dict], visible) -> dict:
        """
        La cita de `whatsapp.thread` (contrato de FR-14): `{ref, name, excerpt, missing}`. Un
        original que la conversación oculta hoy no deja ver su texto: `name` y `excerpt` null.
        """
        ref = q.get("ref") if isinstance(q.get("ref"), str) else None
        if ref:
            original = next((m for m in msgs if m.get("id") == ref), None)
            if original is not None and not visible(original):
                return {"ref": ref, "name": None, "excerpt": None, "missing": bool(q.get("missing"))}
        ours = (ref or "").startswith("wo_") or (ref is None and q.get("from_me"))
        return {"ref": ref, "name": self._agent_name() if ours else contact_name,
                "excerpt": str(q.get("excerpt") or "")[:100], "missing": bool(q.get("missing"))}

    def threads(self, limit: int = 50, before: str | None = None) -> dict:
        limit = _limit(limit)
        phones = self._phones()
        wrote = self.store.wrote_since_link()
        catch_active = self._catch_all_active()
        rows = []
        for party, msgs in self._messages().items():
            if not msgs:
                continue
            last = msgs[0]
            in_roster = party in phones
            visible = self._visible(last, in_roster, catch_active)
            row = {"number": party, "name": phones.get(party) if in_roster else None, "in_roster": in_roster,
                   "last_at": last.get("at"), "last_dir": last.get("dir"),
                   "can_reply": in_roster and party in wrote}
            if visible:
                media_label = ev.whatsapp_kind_label(last.get("kind") or "text") if last.get("kind") not in (
                    None, "text", "file") else ""
                row["last_excerpt"] = " ".join(p for p in (media_label, ev.safe_excerpt(last.get("text") or ""))
                                               if p) or None
                row["last_kind"] = last.get("kind")
            else:
                row.update(last_excerpt=None, last_kind=None, hidden=True)
            rows.append(row)
        rows.sort(key=lambda r: r.get("last_at") or "", reverse=True)
        if before:
            rows = [r for r in rows if (r.get("last_at") or "") < before]
        page = rows[:limit]
        return {"threads": page, "next_before": page[-1]["last_at"] if len(rows) > limit else None}

    def thread(self, number: str, limit: int = 50, before: str | None = None) -> dict:
        limit = _limit(limit)
        party = phone.to_e164(number) or str(number or "")
        msgs = self._messages().get(party)
        if not msgs:
            raise Refused("not_found")
        phones = self._phones()
        in_roster = party in phones
        catch_active = self._catch_all_active()
        if before:
            msgs = [m for m in msgs if (m.get("at") or "") < before]
        all_msgs = msgs
        page = msgs[:limit]
        contact = phones.get(party) if in_roster else (next((m.get("push_name") for m in all_msgs
                                                            if m.get("push_name")), None) or party)

        def visible(m):
            return self._visible(m, in_roster, catch_active)

        rows = []
        reactions = self.store.reactions()
        for m in page:
            row = self._public(m, visible(m))
            if "_reply" in m and not row.get("hidden"):
                row["reply_to"] = self._public_quote(m["_reply"], contact, all_msgs, visible)
            found = _reactions_view(reactions.get(m.get("id"))) if not row.get("hidden") else []
            if found:
                row["reactions"] = found        # PRD #685 F3; sin reacciones no viene
            if m.get("_noid") and not row.get("hidden"):
                row["actions"] = False          # #707: sólo viene si es false
            rows.append(row)
        return {"number": party, "name": phones.get(party) if in_roster else None, "in_roster": in_roster,
                "can_reply": in_roster and party in self.store.wrote_since_link(),
                "messages": rows,
                "next_before": page[-1].get("at") if len(msgs) > limit else None}

    def image(self, message_id: str, index=0) -> dict:
        """
        #573: la foto de un mensaje recibido, para PaynaniWeb. Sólo si su texto también
        se mostraría (FR-16a), recalculado en cada pedido: apagar el Catch-All o sacar al
        contacto del roster la deja de servir, también a una URL ya abierta. Un id que no
        existe, que no es una foto, que no se puede mostrar o cuyo archivo falta da el
        mismo not_found.
        """
        mid = str(message_id or "")
        if mid.startswith("wo_"):
            return self._sent_image(mid, index)
        data = self.store.inbox(mid.rsplit(":", 1)[-1]) if mid.startswith("wa:") else None
        if not data or data.get("event_id") != mid or data.get("kind") != "image":
            raise Refused("not_found")
        party = data.get("from_e164") or data.get("lid") or "?"
        view = {"dir": "in", "catch_all": bool(data.get("catch_all"))}
        if not self._visible(view, party in self._phones(), self._catch_all_active()):
            raise Refused("not_found")
        try:
            body, mime = self.store.read_image(data)
        except LookupError:
            raise Refused("not_found") from None
        return {"mime": mime, "bytes": len(body), "data": base64.b64encode(body).decode("ascii")}

    def file(self, message_id: str) -> dict:
        """
        #676: un documento recibido, para que PaynaniWeb lo deje descargar. Las mismas
        reglas que `image` (#573): sólo de un mensaje que el hilo mostraría (FR-16a),
        recalculado en cada pedido, y el archivo dentro de media/ (`Store.read_file`).
        Todo lo que no se sirve da el mismo not_found.
        """
        mid = str(message_id or "")
        data = self.store.inbox(mid.rsplit(":", 1)[-1]) if mid.startswith("wa:") else None
        if not data or data.get("event_id") != mid or data.get("kind") != "document":
            raise Refused("not_found")
        party = data.get("from_e164") or data.get("lid") or "?"
        view = {"dir": "in", "catch_all": bool(data.get("catch_all"))}
        if not self._visible(view, party in self._phones(), self._catch_all_active()):
            raise Refused("not_found")
        try:
            body = self.store.read_file(data)
        except LookupError:
            raise Refused("not_found") from None
        media = data.get("media") or {}
        return {"name": str(media.get("filename") or ""), "mime": str(media.get("mime") or ""),
                "bytes": len(body), "data": base64.b64encode(body).decode("ascii")}

    def _sent_image(self, sid: str, index) -> dict:
        """#670 FR-7: la copia de una foto que el dueño mandó desde la web, si el hilo se ve hoy."""
        if not isinstance(index, int) or isinstance(index, bool):
            raise Refused("not_found")
        rec = next((s for s in self.store.sent() if s.get("id") == sid), None)
        files = (rec or {}).get("files") or []
        if not 0 <= index < len(files) or rec.get("to") not in self._phones():
            raise Refused("not_found")
        try:
            body, mime = self.store.read_image(files[index])
        except LookupError:
            raise Refused("not_found") from None
        return {"mime": mime, "bytes": len(body), "data": base64.b64encode(body).decode("ascii")}

    # --- el socket (§11) -------------------------------------------------------------------
    def _notify(self, what: str, **extra) -> None:
        line = (json.dumps({"type": "whatsapp.changed", "what": what, **extra}) + "\n").encode()
        for w in list(self.watchers):
            try:
                w.write(line)
            except (ConnectionError, RuntimeError):
                self.watchers.discard(w)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        try:
            while True:
                try:
                    raw = await reader.readline()
                except (asyncio.LimitOverrunError, ValueError):
                    await _write(writer, {"type": "error", "ref": None, "code": "bad_json", "detail": "línea larga"})
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
                await _write(writer, await self.handle(msg, writer))
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.watchers.discard(writer)
            self.clients.discard(writer)
            writer.close()

    async def handle(self, msg: dict, writer: asyncio.StreamWriter | None = None) -> dict:
        rid = msg.get("id")
        if not isinstance(rid, str) or not REQUEST_ID.match(rid):
            return {"type": "error", "ref": None, "code": "missing_field", "field": "id"}
        by = msg.get("by")
        if not isinstance(by, str) or not BY_RE.match(by):
            return {"type": "error", "ref": rid, "code": "missing_field", "field": "by"}
        kind = msg.get("type")
        try:
            if kind == "whatsapp.status":
                data = self.status()
            elif kind == "whatsapp.link":
                data = await self.link_start(str(msg.get("mode") or ""), msg.get("number"), by)
            elif kind == "whatsapp.link_current":
                data = self.link_current(str(msg.get("link_id") or ""))
            elif kind == "whatsapp.link_cancel":
                data = await self.link_cancel()
            elif kind == "whatsapp.unlink":
                data = await self.unlink()
            elif kind == "whatsapp.threads":
                data = self.threads(msg.get("limit", 50), msg.get("before"))
            elif kind == "whatsapp.thread":
                data = self.thread(str(msg.get("number") or ""), msg.get("limit", 50), msg.get("before"))
            elif kind == "whatsapp.send":
                data = await self.send(str(msg.get("number") or ""), msg.get("text") or "", by, msg.get("file"),
                                       msg.get("uploads"), msg.get("reply_to"))
            elif kind == "whatsapp.react":
                data = await self.react(msg.get("ref"), msg.get("emoji", ""), by)
            elif kind == "whatsapp.image":
                data = self.image(str(msg.get("message_id") or ""), msg.get("index", 0))
            elif kind == "whatsapp.file":
                data = self.file(str(msg.get("message_id") or ""))
            elif kind == "whatsapp.watch":
                if writer is not None:
                    self.watchers.add(writer)
                data = {"watching": writer is not None, "status": self.status()}
            else:
                return {"type": "error", "ref": rid, "code": "unknown_type"}
        except Refused as exc:
            out = {"type": "error", "ref": rid, "code": exc.code}
            if exc.detail:
                out["detail"] = exc.detail
            out.update(exc.extra)
            return out
        return {"type": "result", "ref": rid, "ok": True, "data": data}


def author(by: str) -> str:
    """
    Quién escribió, para el hilo (SMS_GATEWAY.md §12): `agent` (el agente o la terminal),
    `owner` (PaynaniWeb o PaynaniApp) o `api`. `by` es la etiqueta de quién llama (§11).
    """
    if by == "api":
        return "api"
    if by == "web" or by.startswith("phone:"):
        return "owner"
    return "agent"


def _reactions_view(current: dict | None) -> list[dict]:
    """`[{emoji, count, mine}]` (FR-14): `ours` es la de la cuenta (la ponga el dueño o el
    agente), `theirs` la del contacto. Primero la nuestra, luego por `count`."""
    groups: dict[str, dict] = {}
    for side in ("ours", "theirs"):
        emoji = (current or {}).get(side) or ""
        if not emoji:
            continue
        g = groups.setdefault(emoji_mod.emoji_key(emoji), {"emoji": emoji, "count": 0, "mine": False})
        g["count"] += 1
        if side == "ours":
            g["mine"] = True
            g["emoji"] = emoji
    return sorted(groups.values(), key=lambda g: (not g["mine"], -g["count"]))


def _quote_record(quote: dict) -> dict:
    """Lo que queda en sent.jsonl de una cita: sin el key_id del original."""
    return {"ref": quote["ref"], "excerpt": quote["excerpt"], "missing": not quote.get("bridge")}


def quote_excerpt(data: dict) -> str:
    """El extracto de una cita (contrato de FR-14): una línea, hasta 100. Sin texto, una foto es
    «📷» y un documento «📄 nombre»."""
    text = " ".join(str(data.get("text") or "").split())
    if text:
        return text[:100]
    kind = data.get("kind")
    if kind == "image":
        return "📷"
    media = data.get("media") or {}
    name = media.get("filename") or data.get("file") or ""
    if kind in ("document", "file") or name:
        return f"📄 {name}".strip()[:100]
    return ""


def _public_file(f: dict) -> dict:
    """Un archivo enviado, para `whatsapp.thread`: sin la ruta en disco (#670 FR-7)."""
    out = {k: f.get(k) for k in ("name", "kind", "size") if f.get(k) is not None}
    media = f.get("media") or {}
    if media.get("path"):
        out["media"] = {"mime": media.get("mime"), "bytes": media.get("bytes")}
    return out


def _limit(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise Refused("invalid", field="limit", reason="limit") from None
    if not 1 <= n <= 100:
        raise Refused("invalid", field="limit", reason="limit")
    return n


def _bridge_code(code: str) -> str:
    return {"bridge_down": "unavailable", "timeout": "unavailable", "not_started": "unavailable",
            "too_large": "invalid", "missing_field": "invalid"}.get(code, code)


async def _write(writer: asyncio.StreamWriter, obj: dict) -> None:
    writer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()
