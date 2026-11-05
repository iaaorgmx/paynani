"""
`GetChanges` de la API del dueño (FR-A8 de iaaorgmx/PaynaniWebMT#2, A2 #720).

PaynaniWebMT pregunta cada 3 o 30 segundos qué cambió, y sólo vuelve a pedir esas
áreas. El cursor es opaco para el cliente y lleva dos cosas:

- hasta dónde se leyó `events.jsonl` (byte e inodo). Las líneas nuevas dicen qué
  cuenta de correo recibió algo (`mail:<cuenta>`) y en qué canal llegó un mensaje;
- una huella por área: fecha, tamaño e inodo de los archivos de estado de ese canal.
  Cualquier escritura cambia la huella, así que no hay huecos; y como el cursor nuevo
  ya la incluye, el mismo cambio no se vuelve a reportar.

Las huellas se calculan antes de devolver el cursor: lo que se escriba después sale
en la siguiente llamada. Si `events.jsonl` rota (otro inodo o más corto que el cursor),
se reportan todas las cuentas de correo. Un cursor vacío o que no se entiende da todas
las áreas con `reset: true`, y el cliente vuelve a pedir todo.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

VERSION = "c1"
CHANNEL_AREAS = ("sms", "whatsapp", "telegram", "webchat")
AREAS = (*CHANNEL_AREAS, "roster", "agent", "dashboard")
ALL_MAIL = "mail:*"
MAX_EVENT_BYTES = 4 * 1024 * 1024        # lo más que se lee de events.jsonl por llamada
MAX_ENTRIES = 5000                       # por área; una carpeta enorme no frena la respuesta
# Lo que cambia sin que cambie nada que se vea: candados, sockets, cachés de envío y archivos
# que sólo se bajan cuando alguien los pide.
SKIP = {"auth", "media", "uploads", "files", "lock", "control.sock", "rate.json", "queue.lock", "optout.lock"}
# Los archivos de cada área, relativos a `state/`. Las carpetas se recorren.
SOURCES = {
    "sms": ("sms",),
    "whatsapp": ("whatsapp",),
    "telegram": ("telegram",),
    "webchat": ("webchat",),
    "agent": ("delivery.json", "codex.delivery.json", "dispatch.json", "idle.json", "lifecycle.jsonl"),
    "mail": ("sent.log",),
    "dashboard": ("doctor.json", "version.check"),
}
_EVENT_AREA = (("sms:", "sms"), ("wa:", "whatsapp"), ("tg:", "telegram"), ("webchat", "webchat"))


def _stat_rows(path: Path, budget: list[int]) -> list[str]:
    try:
        st = path.lstat()
    except OSError:
        return [f"{path.name}:-"]
    if not (path.is_dir() and not path.is_symlink()):
        return [f"{path}:{st.st_mtime_ns}:{st.st_size}:{st.st_ino}"]
    # De una carpeta no cuenta su fecha (crear un candado la cambia): cuentan sus entradas,
    # así que agregar o quitar un archivo visible cambia la huella por el nombre.
    rows = [f"{path}:dir"]
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name)
    except OSError:
        return rows
    for entry in entries:
        if budget[0] <= 0:
            break
        if entry.name in SKIP:
            continue
        budget[0] -= 1
        rows.extend(_stat_rows(Path(entry.path), budget))
    return rows


def fingerprint(paths) -> str:
    budget = [MAX_ENTRIES]
    rows = []
    for path in paths:
        rows.extend(_stat_rows(Path(path), budget))
    return hashlib.sha256("\n".join(rows).encode("utf-8", "replace")).hexdigest()[:16]


def _encode(state: dict) -> str:
    raw = json.dumps(state, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return VERSION + "." + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(cursor: str) -> dict | None:
    if not isinstance(cursor, str) or not cursor.startswith(VERSION + "."):
        return None
    body = cursor[len(VERSION) + 1:]
    try:
        state = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, UnicodeError):
        return None
    if (not isinstance(state, dict) or not isinstance(state.get("o"), int) or not isinstance(state.get("f"), dict)
            or state["o"] < 0):
        return None
    return state


def _new_events(events: Path, offset: int, inode: int) -> tuple[set[str], int, int, bool]:
    """Áreas de las líneas nuevas, el byte y el inodo nuevos, y si rotó."""
    try:
        st = events.stat()
    except OSError:
        return set(), 0, 0, offset > 0
    rotated = bool(inode) and st.st_ino != inode or st.st_size < offset
    start = 0 if rotated else offset
    areas: set[str] = set()
    with events.open("rb") as stream:
        stream.seek(start)
        chunk = stream.read(MAX_EVENT_BYTES)
    # Sólo líneas completas: una a medio escribir se lee en la próxima llamada.
    end = chunk.rfind(b"\n") + 1
    for line in chunk[:end].splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        account = str(event.get("account") or "")
        kind = str(event.get("event_type") or "")
        if kind.startswith("email."):
            areas.add("mail:" + account if account else ALL_MAIL)
            continue
        for prefix, area in _EVENT_AREA:
            if account.startswith(prefix):
                areas.add(area)
                break
    return areas, start + end, st.st_ino, rotated


def changes(state_dir: Path, roster_path: Path, cursor: str = "", *, agent_status: str = "") -> dict:
    """`{cursor, changed: [...], reset}`: las áreas que cambiaron desde `cursor`."""
    state_dir = Path(state_dir)
    prints = {area: fingerprint(state_dir / name for name in names) for area, names in SOURCES.items()}
    prints["roster"] = fingerprint([Path(roster_path), state_dir / "roster_changes.jsonl"])
    # El estado del agente también depende de los servicios, que no son archivos.
    prints["agent"] = hashlib.sha256((prints["agent"] + agent_status).encode()).hexdigest()[:16]
    old = _decode(cursor) if cursor else None
    events = state_dir / "events.jsonl"
    if old is None:
        try:
            st = events.stat()
            offset, inode = st.st_size, st.st_ino
        except OSError:
            offset, inode = 0, 0
        return {"cursor": _encode({"o": offset, "i": inode, "f": prints}),
                "changed": sorted({*AREAS, ALL_MAIL}), "reset": True}
    changed, offset, inode, rotated = _new_events(events, old["o"], int(old.get("i") or 0))
    if rotated:
        changed.add(ALL_MAIL)
    for area, value in prints.items():
        if old["f"].get(area) != value:
            changed.add(ALL_MAIL if area == "mail" else area)
    if changed:
        changed.add("dashboard")
    return {"cursor": _encode({"o": offset, "i": inode, "f": prints}), "changed": sorted(changed), "reset": False}
