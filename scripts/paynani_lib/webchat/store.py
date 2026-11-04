"""
El almacén del Webchat (#648, WEBCHAT.md §2 a §4).

No hay servicio ni socket: el dueño escribe desde PaynaniWeb y el agente contesta desde
la terminal, en el mismo host y con el mismo usuario. Las dos partes usan este módulo.

    state/webchat/                 0700
      lock                         0600  flock de las escrituras
      messages.jsonl               0600  un mensaje por línea, sólo se agrega
      files/f_<32 hex>             0600  los adjuntos, con nombre opaco
      outbox/                      0700  de aquí toma archivos `paynani webchat send --file`
      typing.json                  0600  {"until": "…Z"} mientras el agente escribe
      draft.json                   0600  {"text", "at"} el borrador de `webchat send --stream`
      reactions.jsonl              0600  una reacción puesta o quitada por línea (PRD #685 F3)

El nombre original de un archivo sólo vive en `files[].name`; nunca llega a una ruta.
Cada mensaje del dueño escribe además el evento `webchat.received` (harness/event.py)
en `events.jsonl` y su `observed` en el ledger, para que el agente lo reciba.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import secrets
import sys
import time
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT / "scripts"), str(_ROOT / "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import event as ev  # noqa: E402
import ledger  # noqa: E402
import paths  # noqa: E402

from ..emoji import MAX_EMOJI, emoji_key, valid_emoji  # noqa: E402,F401  (PRD #685 F3)
from ..telegram import media as tg_media  # noqa: E402

MAX_TEXT = 4000
MAX_FILE = 20 * 1024 * 1024
MAX_MESSAGE = 25 * 1024 * 1024
TYPING_GUESS_S = 10 * 60           # «escribiendo…» supuesto mientras el evento espera
DEFAULT_TYPING_S = 60

# tipo real -> (kind, MIME, extensiones aceptadas en el nombre)
TYPES = {
    "jpeg": ("image", "image/jpeg", {"jpg", "jpeg"}),
    "png": ("image", "image/png", {"png"}),
    "webp": ("image", "image/webp", {"webp"}),
    "gif": ("image", "image/gif", {"gif"}),
    "pdf": ("document", "application/pdf", {"pdf"}),
    "txt": ("document", "text/plain; charset=utf-8", {"txt"}),
    "csv": ("document", "text/csv; charset=utf-8", {"csv"}),
    "docx": ("document", tg_media.REAL_TYPES["docx"][2], {"docx"}),
    "xlsx": ("document", tg_media.REAL_TYPES["xlsx"][2], {"xlsx"}),
    "zip": ("document", "application/zip", {"zip"}),
}
_EXT = {ext: real for real, (_, _, exts) in TYPES.items() for ext in exts}
_MSG_ID = re.compile(r"^w_[0-9a-f]{32}$")
_FILE_REF = re.compile(r"^f_[0-9a-f]{32}$")


class Rejected(Exception):
    """Un mensaje que no se guardó. `code`: empty, too_long, too_big, bad_type."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# --- carpetas -------------------------------------------------------------------

def root(state_dir: Path | None = None) -> Path:
    base = Path(state_dir) if state_dir is not None else paths.state_dir()
    return base / "webchat"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _dirs(state_dir: Path | None) -> Path:
    r = _private_dir(root(state_dir))
    _private_dir(r / "files")
    _private_dir(r / "outbox")
    return r


@contextlib.contextmanager
def _locked(r: Path):
    fd = os.open(r / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _now_z() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_z(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _write_private(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


# --- tipos de archivo ---------------------------------------------------------------

def _sniff(path: Path, data: bytes) -> str | None:
    """Qué es el archivo por sus bytes (WEBCHAT.md §4), o None."""
    head = data[:16]
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "gif"
    real = tg_media.sniff(path)
    if real in ("jpeg", "png", "webp", "pdf", "docx", "xlsx"):
        return real
    if real is not None:
        return None                                     # audio, video, pptx…: no van
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(path) as zf:
                zf.infolist()
        except (zipfile.BadZipFile, OSError):
            return None
        return "zip"
    if b"\x00" in data:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text"


def _check_file(path: Path, name: str, data: bytes) -> str:
    """El tipo real si el nombre y los bytes coinciden; si no, Rejected(bad_type)."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    declared = _EXT.get(ext)
    if declared is None:
        raise Rejected("bad_type", name)
    real = _sniff(path, data)
    if real == "text" and declared in ("txt", "csv"):
        return declared
    if real != declared:
        raise Rejected("bad_type", name)
    return real


def _clean_name(name: str) -> str:
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = "".join(ch for ch in name if ch.isprintable() and ch not in "\r\n")
    return name[:200] or "archivo"


def check_upload(path: Path, name: str, data: bytes) -> tuple[str, str]:
    """
    Para la pasarela (SMS_GATEWAY.md §13): `(nombre limpio, kind)` de un archivo ya escrito
    en `path`, o Rejected (`too_big`, `bad_type`). Las mismas reglas que `append`.
    """
    name = _clean_name(name)
    if len(data) > MAX_FILE:
        raise Rejected("too_big", name)
    real = _check_file(path, name, data)
    return name, TYPES[real][0]


def private_dir(path: Path) -> Path:
    """Una carpeta 0700 (la de las subidas pendientes de la pasarela, §13)."""
    return _private_dir(path)


def write_private(path: Path, data: bytes) -> None:
    """Un archivo 0600, escrito completo o nada."""
    _write_private(path, data)


# --- escribir -----------------------------------------------------------------------

def append(by: str, text: str, files: list[tuple[str, bytes]] | None = None, *,
           owner: dict | None = None, rules: dict | None = None, origin: str = "web",
           reply_to: str | None = None, state_dir: Path | None = None) -> dict:
    """
    Guarda un mensaje y lo devuelve. `files` es `[(nombre, bytes)]`.

    `by="owner"` exige `owner={"name", "email"}` y escribe el evento `webchat.received`
    con su `observed`. `by="agent"` no escribe evento. `rules` es la nota de reglas del
    dueño (`rules.notice`), si tiene. `origin` es `web` o `app` (desde PaynaniApp, por la
    pasarela): sólo cambia el aviso al agente. Un error es `Rejected(code)`.

    `reply_to` (PRD #685 F2) es el `w_…` del mensaje que se cita. El mensaje guarda una copia
    de la cita (`ref`, `name`, `excerpt`), así que se ve igual aunque cambien los nombres. Si
    el original ya no está, el mensaje se guarda igual, sin cita y con `missing: true` (FR-7).
    Un `reply_to` sin forma de `w_…` es `Rejected("bad_reply")`.
    """
    if by not in ("owner", "agent"):
        raise ValueError(f"by debe ser owner o agent, no {by!r}")
    if by == "owner" and not (owner and (owner.get("email") or owner.get("name"))):
        raise ValueError("un mensaje del dueño necesita owner={'name', 'email'}")
    text = str(text or "").replace("\r\n", "\n").strip()
    files = list(files or [])
    if not text and not files:
        raise Rejected("empty")
    if len(text) > MAX_TEXT:
        raise Rejected("too_long", f"{len(text)} > {MAX_TEXT}")
    total = 0
    for name, data in files:
        if len(data) > MAX_FILE:
            raise Rejected("too_big", _clean_name(name))
        total += len(data)
    if total > MAX_MESSAGE:
        raise Rejected("too_big", "mensaje")
    if reply_to is not None and not _MSG_ID.match(str(reply_to)):
        raise Rejected("bad_reply", str(reply_to)[:40])

    r = _dirs(state_dir)
    quote = None
    if reply_to is not None:
        original = next((m for m in _all(state_dir) if m.get("id") == reply_to), None)
        quote = (_quote(original, owner, state_dir) if original is not None
                 else {"ref": None, "name": "", "excerpt": "", "missing": True})
    hexpart = secrets.token_hex(16)
    msg_id = "w_" + hexpart
    stored: list[Path] = []
    entries = []
    try:
        for n, (name, data) in enumerate(files):
            name = _clean_name(name)
            ref = "f_" + secrets.token_hex(16)
            path = r / "files" / ref
            _write_private(path, data)
            stored.append(path)
            real = _check_file(path, name, data)
            kind, _mime, _ = TYPES[real]
            entries.append({"n": n, "name": name, "kind": kind, "size": len(data), "ref": ref,
                            "type": real})
    except BaseException:
        for path in stored:
            with contextlib.suppress(OSError):
                path.unlink()
        raise

    message = {"id": msg_id, "dir": "in" if by == "owner" else "out", "by": by, "at": _now_z(),
               "text": text, "files": entries}
    if quote is not None:
        message["reply_to"] = quote
    envelope = None
    if by == "owner":
        message["event_id"] = "wc:" + hexpart
        if owner.get("name"):
            message["owner_name"] = str(owner["name"])[:200]   # para citarlo después (#699, Iris)
        envelope = ev.webchat_event(
            message_id=msg_id, owner_name=owner.get("name", ""), owner_email=owner.get("email", ""),
            text=text, files=entries, sent_at=message["at"], local_time=time.strftime("%H:%M:%S"),
            observed_at=message["at"], rules=rules, origin=origin,
            reply_excerpt=(quote or {}).get("excerpt") or None)
    with _locked(r):
        _append_line(r / "messages.jsonl", message)
        if by == "agent":
            _typing_write(r, None)
            _draft_write(r, None)
    if envelope is not None:
        state = r.parent
        ev.append(state / "events.jsonl", envelope)
        ledger.observed(ledger.path_for(state / "events.jsonl"), envelope)
    return message


def excerpt_of(message: dict) -> str:
    """El extracto de una cita (contrato de FR-14): una línea, hasta 100 caracteres. Una foto
    sin texto es «📷» y un documento, «📄 nombre»."""
    text = " ".join(str(message.get("text") or "").split())
    if text:
        return text[:100]
    files = message.get("files") or []
    if not files:
        return ""
    first = files[0]
    return "📷" if first.get("kind") == "image" else f"📄 {first.get('name') or ''}".strip()[:100]


def _owner_name(original: dict, owner: dict | None) -> str:
    """El nombre del dueño para la cita: el de su sesión si es él quien responde, o el que
    quedó en su mensaje al escribirlo (`owner_name`, cuando responde el agente)."""
    if owner and owner.get("name"):
        return str(owner["name"])
    return str(original.get("owner_name") or "")


def _agent_name() -> str:
    """AGENT_EMAIL_FROM_NAME, el nombre con el que firma el agente; o cadena vacía."""
    with contextlib.suppress(Exception):
        from .. import envfile  # noqa: PLC0415
        return str(envfile.read_env().get("AGENT_EMAIL_FROM_NAME") or "")
    return ""


def _quote(original: dict, owner: dict | None, state_dir: Path | None = None) -> dict:
    name = _agent_name() if original.get("by") == "agent" else _owner_name(original, owner)
    return {"ref": original["id"], "name": name, "excerpt": excerpt_of(original), "missing": False}


def message(msg_id: str, *, state_dir: Path | None = None) -> dict | None:
    """Un mensaje por su `w_…`, o None."""
    if not _MSG_ID.match(str(msg_id or "")):
        return None
    found = next((m for m in _all(state_dir) if m.get("id") == msg_id), None)
    return _public(found, _reaction_state(state_dir)) if found is not None else None


# --- reacciones (PRD #685 F3) ---------------------------------------------------------

def _reaction_rows(state_dir: Path | None) -> list[dict]:
    path = root(state_dir) / "reactions.jsonl"
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                with contextlib.suppress(ValueError):
                    obj = json.loads(line)
                    if (isinstance(obj, dict) and _MSG_ID.match(str(obj.get("ref", "")))
                            and obj.get("by") in ("owner", "agent")):
                        out.append(obj)
    except FileNotFoundError:
        return []
    return out


def _reaction_state(state_dir: Path | None) -> dict[str, dict[str, str]]:
    """`{w_…: {"owner": emoji, "agent": emoji}}`: la última de cada uno; "" la quitó."""
    state: dict[str, dict[str, str]] = {}
    for row in _reaction_rows(state_dir):
        state.setdefault(row["ref"], {})[row["by"]] = str(row.get("emoji") or "")
    return state


def reactions_of(current: dict[str, str] | None) -> list[dict]:
    """
    Las reacciones de un mensaje como las pide FR-14: `[{emoji, count, mine}]`, primero la
    nuestra y luego por `count`. En Webchat «la nuestra» es la del dueño; la del agente cuenta
    como de la otra persona.
    """
    groups: dict[str, dict] = {}
    for by in ("owner", "agent"):
        emoji = (current or {}).get(by) or ""
        if not emoji:
            continue
        g = groups.setdefault(emoji_key(emoji), {"emoji": emoji, "count": 0, "mine": False})
        g["count"] += 1
        if by == "owner":
            g["mine"] = True
            g["emoji"] = emoji
    return sorted(groups.values(), key=lambda g: (not g["mine"], -g["count"]))


def react(ref: str, emoji: str, *, by: str = "owner", owner: dict | None = None,
          state_dir: Path | None = None) -> dict:
    """
    Pone (`emoji`) o quita (`""`) la reacción del dueño (`by="owner"`, desde la web) o del
    agente (`by="agent"`, desde la CLI) en el mensaje `ref` (`w_…`). Una por mensaje y por
    parte: otra la reemplaza (FR-11). Devuelve `{"ref", "reactions"}`.

    La del dueño avisa al agente (FR-16a) con un evento `wc:` de `kind: "reaction"`; la del
    agente no avisa. Poner la misma que ya está, o quitar una que no hay, no cambia nada ni
    avisa. Errores: `Rejected("not_found")` y `Rejected("bad_emoji")`.
    """
    if by not in ("owner", "agent"):
        raise ValueError(f"by debe ser owner o agent, no {by!r}")
    emoji = str(emoji or "").strip()
    if emoji and not valid_emoji(emoji):
        raise Rejected("bad_emoji", emoji[:MAX_EMOJI])
    if not _MSG_ID.match(str(ref or "")):
        raise Rejected("not_found", str(ref)[:40])
    r = _dirs(state_dir)
    envelope = None
    with _locked(r):
        original = next((m for m in _all(state_dir) if m.get("id") == ref), None)
        if original is None:
            raise Rejected("not_found", ref)
        current = _reaction_state(state_dir).get(ref, {})
        before = current.get(by) or ""
        if emoji_key(before) != emoji_key(emoji):
            row = {"ref": ref, "by": by, "emoji": emoji, "at": _now_z()}
            if by == "owner":
                hexpart = secrets.token_hex(16)
                row["event_id"] = "wc:" + hexpart
                name = _owner_name({}, owner) or _last_owner_name(state_dir)
                envelope = ev.webchat_reaction_event(
                    event_hex=hexpart, message_id=ref, owner_name=name,
                    owner_email=(owner or {}).get("email", ""), emoji=emoji or before,
                    removed=not emoji, excerpt=excerpt_of(original), sent_at=row["at"],
                    local_time=time.strftime("%H:%M:%S"), observed_at=row["at"])
            _append_line(r / "reactions.jsonl", row)
            current = dict(current, **{by: emoji})
    if envelope is not None:
        state = r.parent
        ev.append(state / "events.jsonl", envelope)
        ledger.observed(ledger.path_for(state / "events.jsonl"), envelope)
    return {"ref": ref, "reactions": reactions_of(current)}


def _last_owner_name(state_dir: Path | None) -> str:
    for m in reversed(_all(state_dir)):
        if m.get("by") == "owner" and m.get("owner_name"):
            return str(m["owner_name"])
    return ""


def reaction_for_event(event_id: str, *, state_dir: Path | None = None) -> dict | None:
    """La reacción del dueño de un evento `wc:<hex>` de `kind: "reaction"`, o None."""
    event_id = str(event_id or "")
    if not event_id.startswith("wc:"):
        return None
    return next((row for row in _reaction_rows(state_dir) if row.get("event_id") == event_id), None)


def _append_line(path: Path, obj: dict) -> None:
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
        os.fsync(fd)
    finally:
        os.close(fd)


# --- leer ---------------------------------------------------------------------------

def _all(state_dir: Path | None) -> list[dict]:
    path = root(state_dir) / "messages.jsonl"
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                with contextlib.suppress(ValueError):
                    obj = json.loads(line)
                    if isinstance(obj, dict) and _MSG_ID.match(str(obj.get("id", ""))):
                        out.append(obj)
    except FileNotFoundError:
        return []
    return out


def _public(message: dict, reactions: dict[str, dict[str, str]] | None = None) -> dict:
    """Lo que ven la web y la CLI: sin el tipo interno de cada archivo, y con `reactions`
    si el mensaje tiene alguna (FR-14; sin reacciones, el campo no viene)."""
    out = dict(message)
    out["files"] = [{k: f[k] for k in ("n", "name", "kind", "size", "ref") if k in f}
                    for f in message.get("files", [])]
    found = reactions_of((reactions or {}).get(message.get("id")))
    if found:
        out["reactions"] = found
    return out


def messages(after: str | None = None, limit: int = 50, before: str | None = None, *,
             state_dir: Path | None = None) -> list[dict]:
    """
    Los mensajes en orden. Con `after=<id>`, sólo los posteriores (refresco); con
    `before=<id>`, los anteriores («Mensajes anteriores»). Siempre los últimos `limit`
    del rango.
    """
    rows = _all(state_dir)
    ids = [m["id"] for m in rows]
    if after:
        rows = rows[ids.index(after) + 1:] if after in ids else rows
    if before:
        rows = rows[:ids.index(before)] if before in ids else []
    limit = max(1, int(limit))
    reactions = _reaction_state(state_dir)
    return [_public(m, reactions) for m in rows[-limit:]]


def file_path(ref: str, *, state_dir: Path | None = None) -> tuple[Path, str, str] | None:
    """`(ruta, mime, nombre original)` de un adjunto, o None. Valida el formato del ref."""
    if not _FILE_REF.match(str(ref or "")):
        return None
    path = root(state_dir) / "files" / ref
    if not path.is_file():
        return None
    for message in reversed(_all(state_dir)):
        for f in message.get("files", []):
            if f.get("ref") == ref and f.get("type") in TYPES:
                return path, TYPES[f["type"]][1], f.get("name") or "archivo"
    return None


# --- «escribiendo…» -----------------------------------------------------------------

def _typing_write(r: Path, until: str | None) -> None:
    path = r / "typing.json"
    if until is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    _write_private(path, json.dumps({"until": until}).encode())


def typing(seconds: int = DEFAULT_TYPING_S, *, state_dir: Path | None = None) -> None:
    """El agente dice que está escribiendo, por `seconds` (1 a 600)."""
    seconds = min(max(int(seconds), 1), 600)
    r = _dirs(state_dir)
    until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))
    with _locked(r):
        _typing_write(r, until)


def typing_off(*, state_dir: Path | None = None) -> None:
    r = _dirs(state_dir)
    with _locked(r):
        _typing_write(r, None)


def is_typing(now: dt.datetime | None = None, *, state_dir: Path | None = None) -> bool:
    """
    «escribiendo…» (WEBCHAT.md §4): mientras `typing.json` siga vigente o haya un
    borrador de `--stream`, o mientras el
    último mensaje sea del dueño y su evento esté `dispatched`/`presented`, por
    10 minutos como máximo.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    r = root(state_dir)
    try:
        until = _parse_z(json.loads((r / "typing.json").read_text()).get("until"))
    except (OSError, ValueError, AttributeError):
        until = None
    if until is not None and until > now:
        return True
    if draft(now, state_dir=state_dir) is not None:
        return True
    rows = _all(state_dir)
    if not rows or rows[-1].get("by") != "owner":
        return False
    last = rows[-1]
    at = _parse_z(last.get("at"))
    if at is None or now - at > dt.timedelta(seconds=TYPING_GUESS_S):
        return False
    state = ledger.latest(r.parent / "lifecycle.jsonl").get(last.get("event_id", ""), {})
    return state.get("state") in ("dispatched", "presented")


# --- la respuesta por partes (`webchat send --stream`) ------------------------------

def _draft_write(r: Path, text: str | None) -> None:
    path = r / "draft.json"
    if text is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    _write_private(path, json.dumps({"text": text, "at": _now_z()}, ensure_ascii=False).encode("utf-8"))


def draft_set(text: str, *, state_dir: Path | None = None) -> None:
    """
    El borrador completo de la respuesta que el agente va escribiendo (no sólo lo
    nuevo), para que un lector que llega tarde vea todo. `append("agent", …)` lo borra.
    """
    text = str(text or "").replace("\r\n", "\n")
    if len(text) > MAX_TEXT:
        raise Rejected("too_long", f"{len(text)} > {MAX_TEXT}")
    r = _dirs(state_dir)
    with _locked(r):
        _draft_write(r, text)


def draft_clear(*, state_dir: Path | None = None) -> None:
    r = _dirs(state_dir)
    with _locked(r):
        _draft_write(r, None)


def draft(now: dt.datetime | None = None, *, state_dir: Path | None = None) -> dict | None:
    """
    `{"text", "at"}` del borrador, o None si no hay. Uno sin cambios por más de
    10 minutos cuenta como None, por si el agente se cayó a medias.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        data = json.loads((root(state_dir) / "draft.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    at = _parse_z(data.get("at"))
    if at is None or now - at > dt.timedelta(seconds=TYPING_GUESS_S):
        return None
    return {"text": str(data.get("text") or ""), "at": data["at"]}


def message_for_event(event_id: str, *, state_dir: Path | None = None) -> dict | None:
    """El mensaje del dueño de un evento `wc:<hex>`, con el `type` interno de cada archivo."""
    event_id = str(event_id or "")
    if not event_id.startswith("wc:"):
        return None
    msg_id = "w_" + event_id[3:]
    if not _MSG_ID.match(msg_id):
        return None
    for message in _all(state_dir):
        if message.get("id") == msg_id and message.get("by") == "owner":
            return message
    return None
