"""
El estado privado de cada bot (PRD #609 FR-3a, FR-4, FR-5; TELEGRAM.md §1).

    state/telegram/bots/<bot>/
        offset.json      siguiente offset de getUpdates
        journal.jsonl    una línea por paso: {"u": update_id, "ref", "hash"} y {"u", "written": true}
        inbox/<ref>.json el mensaje recibido (texto, tipo, hilo) con su hash
        chats.json       hilo opaco t_… <-> chat privado; y el último mensaje por chat
        links.json       @usuario -> id fijado (FR-13, TG-3)

Todo es 0600 en carpetas 0700, se escribe completo o no se escribe (archivo temporal,
fsync, os.replace) y el diario se agrega con fsync. Los ids de Telegram sólo viven aquí.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path

REF_RE = re.compile(r"^tg:[0-9a-f]{32}$")
THREAD_RE = re.compile(r"^t_[0-9a-f]{32}$")


def new_ref() -> str:
    return "tg:" + secrets.token_hex(16)


def new_thread() -> str:
    return "t_" + secrets.token_hex(16)


def canonical_hash(update: dict) -> str:
    """SHA-256 del update en forma canónica (FR-5): claves ordenadas, sin espacios."""
    data = json.dumps(update, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def private_dir(path: Path) -> Path:
    """Crea la carpeta 0700 si falta; se niega a usar un enlace o algo que no sea carpeta."""
    path = Path(path)
    if path.is_symlink():
        raise OSError(f"{path.name}: es un enlace simbólico")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise OSError(f"{path.name}: no es una carpeta")
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.chmod(path, 0o700)
    return path


def write_atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def write_json(path: Path, obj) -> None:
    write_atomic(path, json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def read_json(path: Path, default=None):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return default
    try:
        with os.fdopen(fd, "rb") as fh:
            return json.loads(fh.read() or b"null")
    except (OSError, ValueError):
        return default


def append_line(path: Path, obj) -> None:
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
        os.fsync(fd)
    finally:
        os.close(fd)


class BotStore:
    def __init__(self, root: Path):
        self.root = private_dir(root)
        self.inbox_dir = private_dir(self.root / "inbox")

    # --- offset (FR-4) ---
    def offset(self) -> int:
        data = read_json(self.root / "offset.json", {})
        try:
            return int((data or {}).get("offset", 0))
        except (TypeError, ValueError):
            return 0

    def save_offset(self, offset: int) -> None:
        write_json(self.root / "offset.json", {"offset": int(offset)})

    # --- diario (FR-5) ---
    def journal(self) -> dict[int, dict]:
        """{update_id: {"ref", "hash", "written"}} según el diario."""
        out: dict[int, dict] = {}
        try:
            fd = os.open(self.root / "journal.jsonl", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            return out
        with os.fdopen(fd, "rb") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                    u = int(rec["u"])
                except (ValueError, KeyError, TypeError):
                    continue                     # una línea cortada por una caída: se ignora
                if "ref" in rec:
                    out[u] = {"ref": rec["ref"], "hash": rec.get("hash", ""), "written": False}
                elif rec.get("written") and u in out:
                    out[u]["written"] = True
        return out

    def journal_begin(self, update_id: int, ref: str, digest: str) -> None:
        append_line(self.root / "journal.jsonl", {"u": int(update_id), "ref": ref, "hash": digest})

    def journal_written(self, update_id: int) -> None:
        append_line(self.root / "journal.jsonl", {"u": int(update_id), "written": True})

    # --- inbox ---
    def _inbox_path(self, ref: str) -> Path:
        if not REF_RE.match(ref):
            raise ValueError("referencia inválida")
        return self.inbox_dir / (ref[3:] + ".json")

    def inbox(self, ref: str) -> dict | None:
        return read_json(self._inbox_path(ref))

    def save_inbox(self, ref: str, data: dict) -> None:
        write_json(self._inbox_path(ref), data)

    def inbox_refs(self):
        for p in self.inbox_dir.glob("*.json"):
            yield "tg:" + p.stem

    # --- hilos ---
    def _chats(self) -> dict:
        return read_json(self.root / "chats.json", {}) or {}

    def thread_for(self, chat_id: int, user_id: int) -> str:
        """El hilo opaco de un chat privado; lo crea la primera vez."""
        data = self._chats()
        key = str(int(chat_id))
        entry = data.get("by_chat", {}).get(key)
        if entry:
            return entry["thread"]
        thread = new_thread()
        data.setdefault("by_chat", {})[key] = {"thread": thread, "user": int(user_id)}
        data.setdefault("by_thread", {})[thread] = key
        write_json(self.root / "chats.json", data)
        return thread

    def chat_of(self, thread: str) -> tuple[int, int] | None:
        """(chat_id, user_id) de un hilo, o None."""
        if not THREAD_RE.match(thread or ""):
            return None
        data = self._chats()
        key = data.get("by_thread", {}).get(thread)
        if key is None:
            return None
        entry = data.get("by_chat", {}).get(key) or {}
        return int(key), int(entry.get("user", key))

    def threads(self) -> dict[str, dict]:
        data = self._chats()
        return {e["thread"]: {"chat": int(k), "user": int(e.get("user", k))}
                for k, e in data.get("by_chat", {}).items()}

    def find_message(self, chat_id: int, message_id: int) -> str | None:
        """La referencia de un mensaje ya recibido, para una edición (FR-16a)."""
        for ref in self.inbox_refs():
            data = self.inbox(ref) or {}
            if data.get("chat") == int(chat_id) and data.get("message_id") == int(message_id) \
                    and data.get("type") == "telegram.received":
                return ref
        return None
