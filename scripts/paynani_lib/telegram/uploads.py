"""
Archivos que el dueño manda por Telegram desde PaynaniWeb (#662; TELEGRAM.md §4).

PaynaniWeb no elige rutas: llama a `save(root, name, data)` en su propio proceso y recibe
un `up_…`. Se lo pasa a `telegram.send` en `uploads`, y el servicio lo lee con `take`.
Igual que las subidas de Webchat de la pasarela (#655, SMS_GATEWAY.md §13):

- `state/telegram/uploads/up_<hex>` y su `.json` (`name`, `kind`, `size`, `mime`,
  `expires`), carpeta 0700 y archivos 0600;
- el tipo se revisa por los bytes, con las reglas de Webchat (`webchat.store.check_upload`);
- cada `up_…` vale 10 minutos y una sola vez: `drop` lo borra cuando el envío salió, y si
  el envío falla queda para reintentar hasta que venza;
- hasta 20 pendientes por instalación (`too_many`).
"""
from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

from ..webchat import store as wc_store
from .store import private_dir, read_json, write_json

DIR = "uploads"
TTL_S = 600
MAX_PENDING = 20
MAX_FILES = 10                       # por mensaje
MAX_FILE = wc_store.MAX_FILE         # 20 MB por archivo, como Webchat
MAX_TOTAL = wc_store.MAX_FILE        # y 20 MB entre todos los de un mensaje
_REF = re.compile(r"^up_[0-9a-f]{32}$")
_MIME = {real: mime.split(";")[0] for real, (_, mime, _) in wc_store.TYPES.items()}


class Rejected(Exception):
    """`code`: too_big, bad_type, too_many, bad_upload."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _dir(root: Path) -> Path:
    return private_dir(Path(root) / DIR)


def _pending(d: Path, now: float) -> list[str]:
    """Los `up_` vigentes; de paso borra los vencidos y los que quedaron a medias."""
    alive = []
    for meta in d.glob("up_*.json"):
        ref = meta.name[:-5]
        info = read_json(meta)
        if not isinstance(info, dict) or float(info.get("expires", 0)) <= now or not (d / ref).is_file():
            drop(d.parent, ref)
            continue
        alive.append(ref)
    return alive


def save(root: Path, name: str, data: bytes, *, clock=time.time) -> dict:
    """Guarda un archivo de la web y da `{upload, name, kind, size}`; si no, Rejected."""
    d = _dir(root)
    now = clock()
    if len(data) > MAX_FILE:
        raise Rejected("too_big", str(name))
    if len(_pending(d, now)) >= MAX_PENDING:
        raise Rejected("too_many")
    ref = "up_" + secrets.token_hex(16)
    path = d / ref
    wc_store.write_private(path, data)
    try:
        clean, kind = wc_store.check_upload(path, name, data)
    except wc_store.Rejected as exc:
        drop(root, ref)
        raise Rejected(exc.code, str(name)) from None
    ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
    real = wc_store._EXT.get(ext, "")
    info = {"name": clean, "kind": kind, "size": len(data), "mime": _MIME.get(real, "application/octet-stream"),
            "expires": now + TTL_S}
    write_json(d / (ref + ".json"), info)
    return {"upload": ref, "name": clean, "kind": kind, "size": len(data)}


def take(root: Path, refs, *, clock=time.time) -> list[dict]:
    """
    Para `telegram.send`: los archivos de `refs`, en orden, como
    `[{upload, name, kind, mime, size, data}]`. No borra nada (eso es `drop`, cuando el
    envío salió). Rejected: `bad_upload` (no es lista, repetido, no existe o venció),
    `too_many` (más de 10) o `too_big` (más de 20 MB entre todos).
    """
    if not isinstance(refs, list) or not refs:
        raise Rejected("bad_upload", "uploads")
    if len(refs) > MAX_FILES:
        raise Rejected("too_many", f"más de {MAX_FILES}")
    if len(set(map(str, refs))) != len(refs):
        raise Rejected("bad_upload", "repetido")
    d = Path(root) / DIR
    now = clock()
    out, total = [], 0
    for ref in refs:
        if not isinstance(ref, str) or not _REF.match(ref):
            raise Rejected("bad_upload", str(ref)[:40])
        info = read_json(d / (ref + ".json"))
        if not isinstance(info, dict) or float(info.get("expires", 0)) <= now:
            raise Rejected("bad_upload", ref)
        try:
            fd = os.open(d / ref, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            raise Rejected("bad_upload", ref) from None
        with os.fdopen(fd, "rb") as fh:
            data = fh.read()
        total += len(data)
        if total > MAX_TOTAL:
            raise Rejected("too_big", "más de 20 MB entre todos")
        out.append({"upload": ref, "name": str(info.get("name") or "archivo"), "kind": info.get("kind"),
                    "mime": str(info.get("mime") or "application/octet-stream"), "size": len(data),
                    "data": data})
    return out


def drop(root: Path, ref: str) -> None:
    """Borra un `up_` y su `.json`, si existen."""
    if not _REF.match(str(ref)):
        return
    d = Path(root) / DIR
    for p in (d / ref, d / (ref + ".json")):
        try:
            os.unlink(p)
        except OSError:
            pass

