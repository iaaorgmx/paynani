"""
De dónde lee y a dónde escribe la página de Webchat (#648). El almacén es del núcleo
(`paynani_lib/webchat/store.py`, de Metis), con el contrato acordado en #648:

- `append(by, text, files, *, owner=None)` guarda un mensaje. Con `by="owner"` exige
  `owner={"name", "email"}` y escribe el evento `webchat.received`. `files` es
  `[(nombre, bytes)]`. Si no se puede, `Rejected(code)` con `empty`, `too_long`, `too_big`
  o `bad_type`.
- `messages(after=None, limit=50, before=None)`, los mensajes en orden: `{id: "w_…", at,
  by, text, files: [{name, kind: "image"|"document", size, ref: "f_…"}], event_id}`.
- `file_path(ref)` → `(ruta, mime, nombre)` de un adjunto, o None.
- `is_typing(now=None)` → True mientras el agente escribe.

`load()` da el del núcleo, o None si esta instalación todavía no lo trae: la página lo dice
y no ofrece escribir. `Fake` es el de las pruebas y las capturas, en una carpeta temporal.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
import tempfile
from pathlib import Path

MAX_FILE = 20 * 1024 * 1024
MAX_MESSAGE = 25 * 1024 * 1024       # el POST no puede ser más grande que esto (y poco más)
MAX_TEXT = 4000
REF_RE = re.compile(r"^f_[0-9a-f]{32}$")
ID_RE = re.compile(r"^w_[0-9a-f]{32}$")


def load():
    """El almacén del núcleo, o None si esta instalación no lo trae todavía."""
    try:
        from ..webchat import store  # noqa: PLC0415 -- de Metis (#648, W-1)
    except ImportError:
        return None
    return store


def rejected_code(exc: Exception) -> str | None:
    """El código de un `Rejected` del almacén (el del núcleo o el falso)."""
    return getattr(exc, "code", None) if type(exc).__name__ == "Rejected" else None


class Rejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sniff(data: bytes) -> tuple[str, str] | None:
    """(mime, kind) por los bytes, como pide el contrato; None si el tipo no se acepta."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "image"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "image"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "image"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "image"
    if data.startswith(b"%PDF-"):
        return "application/pdf", "document"
    if data.startswith(b"PK\x03\x04"):
        return "application/zip", "document"
    try:
        data.decode("utf-8")
        return "text/plain", "document"
    except UnicodeDecodeError:
        return None


class Fake:
    """En memoria y en una carpeta temporal, con las mismas firmas que el del núcleo."""

    Rejected = Rejected

    def __init__(self, root: Path | None = None, now=None):
        self.root = Path(root or tempfile.mkdtemp())
        self.items: list[dict] = []
        self.blobs: dict[str, tuple[Path, str, str]] = {}
        self.typing_until: dt.datetime | None = None
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        self.events: list[dict] = []

    def append(self, by: str, text: str, files: list[tuple[str, bytes]], *, owner: dict | None = None) -> dict:
        if by == "owner" and not owner:
            raise ValueError("owner required")
        if not (text or "").strip() and not files:
            raise Rejected("empty")
        if len(text or "") > MAX_TEXT:
            raise Rejected("too_long")
        if any(len(data) > MAX_FILE for _, data in files) or sum(len(d) for _, d in files) > MAX_MESSAGE:
            raise Rejected("too_big")
        stored = []
        for name, data in files:
            sniffed = _sniff(data)
            if sniffed is None:
                raise Rejected("bad_type")
            mime, kind = sniffed
            ref = "f_" + secrets.token_hex(16)
            path = self.root / ref
            path.write_bytes(data)
            self.blobs[ref] = (path, mime, name)
            stored.append({"name": name, "kind": kind, "size": len(data), "ref": ref})
        hexid = secrets.token_hex(16)
        msg = {"id": "w_" + hexid, "at": self.now().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "by": by, "text": text or "", "files": stored}
        if by == "owner":
            msg["event_id"] = "wc:" + hexid
            self.events.append({"event_id": msg["event_id"], "owner": owner})
        else:
            self.typing_until = None
        self.items.append(msg)
        return msg

    def messages(self, after: str | None = None, limit: int = 50, before: str | None = None) -> list[dict]:
        ids = [m["id"] for m in self.items]
        items = self.items
        if after:
            items = items[ids.index(after) + 1:] if after in ids else []
        elif before:
            items = items[:ids.index(before)] if before in ids else []
        return items[-limit:] if not after else items[:limit]

    def file_path(self, ref: str):
        return self.blobs.get(ref) if REF_RE.match(ref or "") else None

    def typing(self, seconds: int = 60) -> None:
        self.typing_until = self.now() + dt.timedelta(seconds=seconds)

    def typing_off(self) -> None:
        self.typing_until = None

    def is_typing(self, now=None) -> bool:
        now = now or self.now()
        return self.typing_until is not None and now < self.typing_until
