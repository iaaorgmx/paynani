"""
Lo que el servicio de WhatsApp guarda en state/whatsapp/ (PRD #550 FR-11, FR-20, FR-21, FR-23).

    inbox/<hash>.json   un mensaje recibido, con su texto y su archivo (como state/sms/inbox/)
    sent.jsonl          una línea por envío y por cada cambio de estado (FR-23)
    link.json           cuándo se vinculó la cuenta (FR-20 cuenta desde ahí); sin secretos
    rate.json           los envíos recientes, para el tope de FR-21

Todo con 0600 en carpetas 0700 (Layout.prepare()). Nada de esto lleva el QR, el código
de vinculación ni nada de auth/.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import secrets
import time
from pathlib import Path

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SENT_ID_RE = re.compile(r"^wo_[0-9a-f]{32}$")


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _epoch(stamp: str) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)

    # --- archivos -------------------------------------------------------------
    def _write(self, path: Path, data) -> None:
        """Atómico y durable: temporal 0600, fsync, rename."""
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def _read(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, UnicodeDecodeError):
            return default

    def _append(self, path: Path, record: dict) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # --- la vinculación ---------------------------------------------------------
    def link_info(self) -> dict:
        return self._read(self.root / "link.json", {})

    def mark_linked(self, me: str | None) -> None:
        """FR-20 cuenta los mensajes desde aquí: lo de una vinculación anterior no abre hilos."""
        self._write(self.root / "link.json", {"me": me, "linked_at": now_utc()})

    def mark_unlinked(self) -> None:
        try:
            (self.root / "link.json").unlink()
        except FileNotFoundError:
            pass

    # --- recibidos (FR-11, FR-11a) ---------------------------------------------
    def inbox_path(self, message_hash: str) -> Path:
        if not HASH_RE.match(str(message_hash or "")):
            raise ValueError("hash de mensaje inválido")
        return self.root / "inbox" / f"{message_hash}.json"

    def inbox(self, message_hash: str) -> dict | None:
        if not HASH_RE.match(str(message_hash or "")):
            return None
        return self._read(self.inbox_path(message_hash), None)

    def save_inbox(self, message_hash: str, data: dict) -> None:
        self._write(self.inbox_path(message_hash), data)

    def received(self):
        """Cada mensaje recibido guardado, sin orden."""
        for path in (self.root / "inbox").glob("*.json"):
            data = self._read(path, None)
            if isinstance(data, dict) and data.get("journaled"):
                yield data

    def wrote_since_link(self) -> set[str]:
        """
        FR-20 (Q8=B): los números que ya escribieron por WhatsApp desde que se vinculó
        esta cuenta. Sólo a ellos se les puede contestar.
        """
        info = self.link_info()
        since = _epoch(info.get("linked_at", ""))
        me = info.get("me")
        out = set()
        for msg in self.received():
            e164 = msg.get("from_e164")
            if not e164:
                continue
            if me and msg.get("account_me") and msg["account_me"] != me:
                continue
            got = _epoch(msg.get("received_at", ""))
            if since is not None and (got is None or got < since):
                continue
            out.add(e164)
        return out

    def forget_media(self, message_hash: str) -> None:
        """FR-16a: el archivo de un mensaje que no se puede mostrar se borra y se olvida."""
        data = self.inbox(message_hash)
        if not data or not (data.get("media") or {}).get("path"):
            return
        path = Path(data["media"]["path"])
        media_root = (self.root / "media").resolve()
        try:
            if path.resolve().parent == media_root and not path.is_symlink():
                path.unlink()
        except FileNotFoundError:
            pass
        data["media"] = dict(data["media"], path=None, sha256=None, skipped="hidden")
        self.save_inbox(message_hash, data)

    # --- enviados (FR-23) ---------------------------------------------------------
    def new_sent_id(self) -> str:
        return "wo_" + secrets.token_hex(16)

    def record_sent(self, record: dict) -> None:
        self._append(self.root / "sent.jsonl", record)

    def sent(self) -> list[dict]:
        """Cada envío con su último estado (el archivo es de líneas que se agregan)."""
        out: dict[str, dict] = {}
        by_key: dict[str, str] = {}
        try:
            lines = (self.root / "sent.jsonl").read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("receipt"):
                sid = by_key.get(rec.get("key_id", ""))
                if sid and sid in out:
                    out[sid]["status"] = rec["status"]
                    out[sid]["status_at"] = rec.get("at")
                continue
            sid = rec.get("id")
            if not sid:
                continue
            out[sid] = dict(out.get(sid, {}), **rec)
            if rec.get("key_id"):
                by_key[rec["key_id"]] = sid
        return list(out.values())

    # --- el tope de envío (FR-21) ----------------------------------------------------
    def rate_check(self, interval_s: int, per_day: int, now: float | None = None) -> int | None:
        """None si se puede mandar ahora; si no, los segundos que faltan."""
        now = time.time() if now is None else now
        stamps = [t for t in self._read(self.root / "rate.json", []) if isinstance(t, (int, float))
                  and now - t < 86400]
        if stamps and now - max(stamps) < interval_s:
            return max(1, int(interval_s - (now - max(stamps)) + 0.999))
        if len(stamps) >= per_day:
            return max(1, int(86400 - (now - min(stamps))))
        return None

    def rate_take(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        stamps = [t for t in self._read(self.root / "rate.json", []) if isinstance(t, (int, float))
                  and now - t < 86400]
        stamps.append(now)
        self._write(self.root / "rate.json", stamps)
