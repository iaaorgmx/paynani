"""
Leer y editar la tabla de contactos de un roster desde la pantalla «Roster» de
PaynaniApp (R2 de #410, SMS_GATEWAY.md §11, PRD #409 R-2–R-5).

Esto es el núcleo, sin WebSocket: `sms/roster_api.py` lo llama con lo que pidió
el teléfono emparejado. Nada de aquí lo alcanza un correo ni un SMS: el único
camino es la conexión autenticada del teléfono, igual que `paynani roster` sólo
lo alcanza una persona en la terminal (ver roster_cli.py).

Las reglas que se cumplen aquí, para cualquier cambio:
  - **Un solo paso:** se compara el `etag` y se escribe dentro de `locked()`, el
    mismo bloqueo que toma `paynani roster` (roster_cli._apply_change_core). Un
    `paynani roster add` que entre en medio espera; no se pierde ninguno de los
    dos cambios.
  - **Copia fechada** del archivo antes de escribir (Q4), en `state/history/`.
  - **Escritura atómica** con el mismo mecanismo de roster_cli (temporal y
    rename), y **relectura**: si el archivo no vuelve a leerse como los contactos
    que se pidieron, se restaura byte por byte y el cambio no cuenta.
  - **La fila del dueño** (el primer contacto `Human`) no se borra ni deja de ser
    `Human`.

A diferencia de `paynani roster`, aquí no se corren `test_roster.sh` ni
`test_listener.py` antes de escribir: prueban el código con rosters de prueba, no
este archivo, y tardan decenas de segundos que la app (que espera 15) no tiene. Lo
que comprueba el cambio es la relectura del archivo escrito, como con
`run_tests=False` en roster_cli (#361).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import re
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "harness"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import phone  # noqa: E402
import roster as roster_mod  # noqa: E402

TEMPLATE = _REPO_ROOT / "roster.md.example"

# Los nombres canónicos que ve la app (`columns` de roster.list), por el nombre
# canónico de roster.py. `address` es el nombre viejo de `Email`.
COLUMN_NAMES = {"name": "Name", "email": "Email", "address": "Email", "type": "Type",
                "github": "GitHub", "phone": "Phone", "rules": "Rules", "telegram": "Telegram"}
TYPES = {"": "", "human": "Human", "ai agent": "AI Agent"}
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
EMAIL = re.compile(r"^[^@\s|<>,;]+@[^@\s|<>,;]+\.[^@\s|<>,;]+$")
NAME_MAX = 120


class EditError(Exception):
    """Un pedido que no se aplica. `code` es el de SMS_GATEWAY.md §11."""

    def __init__(self, code: str, field: str = "", reason: str = "", detail: str = "",
                 etag: str | None = None):
        super().__init__(detail or code)
        self.code = code
        self.field = field
        self.reason = reason
        self.detail = detail
        self.etag = etag

    def as_error(self) -> dict:
        out = {"code": self.code}
        if self.field:
            out["field"] = self.field
        if self.reason:
            out["reason"] = self.reason
        if self.detail:
            out["detail"] = self.detail
        if self.etag is not None:
            out["etag"] = self.etag
        return out


# --- etag y bloqueo -------------------------------------------------------

def etag_of(data: bytes | None) -> str:
    """El SHA-256 en hex del archivo tal como está en disco, o `""` si no existe."""
    return "" if data is None else hashlib.sha256(data).hexdigest()


def read_bytes(path: Path) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


def lock_path(path: Path, state_dir: Path) -> Path:
    """
    El archivo de bloqueo de `path`, en `state/locks/`.

    No se bloquea el roster mismo: la escritura atómica lo reemplaza por otro
    inode, y quien estuviera esperando el bloqueo del viejo entraría sobre un
    archivo que ya no es el roster. Uno aparte, que nunca se reemplaza, sirve a
    los dos lados.
    """
    key = hashlib.sha256(str(Path(path).resolve()).encode("utf-8")).hexdigest()[:24]
    return Path(state_dir) / "locks" / f"roster-{key}.lock"


@contextlib.contextmanager
def locked(path: Path, state_dir: Path, timeout_s: float = 10.0):
    """Bloqueo exclusivo de `path` entre procesos (flock). `TimeoutError` si no llega."""
    lock = lock_path(path, state_dir)
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{path} está bloqueado por otro proceso")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# --- la tabla -------------------------------------------------------------

def table(text: str):
    """
    `(header_idx, header_fields, rows)` de la tabla de contactos, con `rows` como
    `[(line_idx, fields), ...]` en su orden. `(None, None, [])` sin tabla.
    """
    header_idx = header_fields = None
    rows = []
    for fields, is_header, idx in roster_mod._rows(text, "contacts"):
        if is_header:
            if header_idx is None:
                header_idx, header_fields = idx, fields
            continue
        if header_idx is not None and idx > header_idx:
            rows.append((idx, fields))
    return header_idx, header_fields, rows


def columns(header_fields) -> list[str]:
    """Las columnas que conoce la app, en el orden de la tabla y sin repetir."""
    out = []
    for raw in header_fields or []:
        name = COLUMN_NAMES.get(roster_mod.canonical_column(raw))
        if name and name not in out:
            out.append(name)
    return out


def _cells(header_fields, fields) -> dict:
    by = {}
    for raw, value in zip(header_fields, fields):
        key = roster_mod.canonical_column(raw)
        if key == "address":
            key = "email"
        if key not in by:
            by[key] = value.strip()
    return by


def _phones(cell: str) -> list[str]:
    """La celda Phone como lista, cada número en E.164 si se puede leer, o tal cual."""
    out = []
    for raw in phone.split_cell(cell or ""):
        number = phone.to_e164(raw) or raw.strip()
        if number and number not in out:
            out.append(number)
    return out


def members(text: str) -> tuple[list[str], list[dict]]:
    """`(columns, members)` como los devuelve `roster.list`, sin `has_rules`."""
    _, header_fields, rows = table(text)
    owner_seen = False
    out = []
    for n, (_, fields) in enumerate(rows, start=1):
        cells = _cells(header_fields, fields)
        email = cells.get("email", "")
        if not email:
            email = next((f.strip() for f in fields if "@" in f and not f.strip().startswith("@")), "")
        type_ = TYPES.get(cells.get("type", "").strip().lower(), cells.get("type", ""))
        owner = not owner_seen and type_ == "Human"
        owner_seen = owner_seen or owner
        out.append({"row": n, "name": cells.get("name", ""), "email": email, "type": type_,
                    "github": cells.get("github", ""), "phones": _phones(cells.get("phone", "")),
                    "telegram": cells.get(roster_mod.TELEGRAM_COLUMN, ""),
                    "owner": owner, "rules": cells.get("rules") or None})
    return columns(header_fields), out


def _signature(text: str) -> list[tuple]:
    """Lo que tiene que quedar igual al releer: cada fila, en orden."""
    _, rows = members(text)
    return [(m["name"], roster_mod.normalise(m["email"]), m["type"], m["github"],
             tuple(m["phones"]), m["telegram"], m["rules"]) for m in rows]


# --- validación ------------------------------------------------------------

def _fail(field: str, reason: str, detail: str):
    raise EditError("invalid", field=field, reason=reason, detail=detail)


def validate(member: dict, cols: list[str], others: list[dict], *, owner: bool, kept_telegram: str = "") -> dict:
    """
    El contacto que mandó la app, ya limpio, o `EditError("invalid")` con la
    primera regla que falla, en el orden de la tabla de SMS_GATEWAY.md §11.
    `others` son las demás filas del mismo roster. `kept_telegram` es el Telegram que
    la fila ya tiene, en una edición sin la llave `telegram`: se conserva tal cual
    (_render) y cuenta como canal (revisión de Ximena en #622).
    """
    if not isinstance(member, dict):
        _fail("member", "required", "falta member")

    def text(key):
        value = member.get(key, "")
        if value is None:
            return ""
        if not isinstance(value, str):
            _fail(key, "required" if key == "name" else key, f"{key} no es texto")
        return value.strip()

    name = text("name")
    if not name or "|" in name or "\n" in name or "\r" in name or len(name) > NAME_MAX:
        _fail("name", "required", "el nombre va lleno, en una línea y sin «|»")
    email = text("email")
    if email and not EMAIL.match(email):
        _fail("email", "email_format", f"«{email}» no es un correo válido")
    raw_phones = member.get("phones") or []
    if not isinstance(raw_phones, list) or not all(isinstance(p, str) for p in raw_phones):
        _fail("phones", "phone_e164", "phones es una lista de números")
    phones = []
    for raw in raw_phones:
        number = raw.strip()
        if not E164.match(number):
            _fail("phones", "phone_e164", f"«{number}» no está en E.164 (+525511112222)")
        if number not in phones:
            phones.append(number)
    # Telegram (PRD #609 FR-11, FR-15): un id numérico o un @usuario, con la misma regla
    # que lee el servicio (roster.telegram_value). Sin la llave en `member`, una edición
    # conserva lo que la fila ya tenía (ver _render).
    has_telegram = "telegram" in member
    telegram = text("telegram") if has_telegram else ""
    tg = None
    if telegram:
        tg = roster_mod.telegram_value(telegram)
        if tg is None:
            # Sin repetir lo que se escribió: un id de Telegram no va en el detalle (#612).
            _fail("telegram", "telegram", "no es un id de Telegram ni un @usuario")
        telegram = tg[1] if tg[0] == "id" else "@" + tg[1]
    if not email and not phones and not telegram and not (not has_telegram and kept_telegram):
        _fail("email", "no_channel", "hace falta un correo, un teléfono o Telegram")
    norm = roster_mod.normalise(email)
    for other in others:
        if norm and roster_mod.normalise(other["email"]) == norm:
            _fail("email", "duplicate_email", f"{email} ya es de {other['name'] or 'otra fila'}")
    taken = {p: o["name"] for o in others for p in o["phones"]}
    for number in phones:
        if number in taken:
            _fail("phones", "duplicate_phone", f"{number} ya es de {taken[number] or 'otra fila'}")
    if tg is not None:
        for other in others:
            if roster_mod.telegram_value(other.get("telegram", "")) == tg:
                # El valor no va en el detalle: el id de Telegram sólo se ve en el formulario (FR-15).
                _fail("telegram", "duplicate_telegram", f"ese Telegram ya es de {other['name'] or 'otra fila'}")
    type_raw = text("type")
    if type_raw.lower() not in TYPES:
        _fail("type", "type", f"«{type_raw}» no es Human ni AI Agent")
    type_ = TYPES[type_raw.lower()]
    github = text("github")
    if github and not roster_mod.validate_github_login(github):
        _fail("github", "github", f"«{github}» no es un login de GitHub")
    if owner and type_ != "Human":
        _fail("type", "owner_type", "la fila del dueño sigue siendo Human")
    if phones and "Phone" not in cols:
        _fail("phones", "no_phone_column", "este roster no tiene columna Phone")
    if github and "GitHub" not in cols:
        _fail("github", "no_github_column", "este roster no tiene columna GitHub")
    if type_ and "Type" not in cols:
        _fail("type", "no_type_column", "este roster no tiene columna Type")
    if "Email" not in cols and email:
        _fail("email", "no_email_column", "este roster no tiene columna Email")
    if telegram and "Telegram" not in cols:
        # save_text agrega la columna antes de validar (Q269 = A, #628); esto sólo
        # protege a quien llame a validate con otras columnas.
        _fail("telegram", "no_telegram_column", "este roster no tiene columna Telegram")
    clean = {"name": name, "email": email, "type": type_, "github": github, "phones": phones}
    if has_telegram:
        clean["telegram"] = telegram
    return clean


def _render(header_fields, values: dict, old_fields=None) -> str:
    """
    Una fila con las columnas del archivo, en su orden. Una columna que la app no
    conoce conserva lo que tenía la fila (una edición no borra datos que no ve), y
    en un alta queda vacía.
    """
    old = list(old_fields or [])
    cells = []
    for i, raw in enumerate(header_fields):
        key = roster_mod.canonical_column(raw)
        if key == "address":
            key = "email"
        if key == "phone":
            cells.append(", ".join(values.get("phones") or []))
        elif key in ("name", "email", "type", "github"):
            cells.append(values.get(key, ""))
        elif key == "rules" and "rules" in values:
            cells.append(values["rules"] or "")
        elif key == roster_mod.TELEGRAM_COLUMN and "telegram" in values:
            cells.append(values["telegram"] or "")
        else:
            cells.append(old[i].strip() if i < len(old) else "")
    return "| " + " | ".join(cells) + " |"


def _join(lines: list[str], text: str) -> str:
    """Las líneas otra vez, con el fin de línea que tenía el archivo (un roster con CRLF lo conserva)."""
    eol = "\r\n" if "\r\n" in text else "\n"
    trailing = eol if text.endswith(("\n", "\r\n")) or not text else ""
    return eol.join(lines) + trailing


def _row(rows, row) -> tuple[int, list]:
    if not isinstance(row, int) or isinstance(row, bool) or not 1 <= row <= len(rows):
        raise EditError("not_found", field="row", detail=f"no hay fila {row!r}")
    return rows[row - 1]


def save_text(text: str, row, member: dict) -> tuple[str, int, dict]:
    """
    `(new_text, row, cleaned)` para un alta (`row` None) o la edición de `row`.
    No escribe nada.
    """
    header_idx, header_fields, rows = table(text)
    if header_idx is None:
        raise EditError("unreadable", detail="el roster no tiene tabla de contactos")
    schema_error = roster_mod.write_schema_error(text)
    if schema_error:
        raise EditError("unreadable", detail=schema_error)
    if isinstance(member, dict) and str(member.get("telegram") or "").strip():
        cols, _ = members(text)
        if "Telegram" not in cols:
            # Q269 = A (#628): guardar un Telegram crea la columna, vacía en las demás
            # filas. Sin un valor de Telegram el archivo no cambia de forma.
            text = _add_column(text, "Telegram")
            header_idx, header_fields, rows = table(text)
    cols, current = members(text)
    lines = text.splitlines()
    if row is None:
        clean = validate(member, cols, current, owner=False)
        insert_at = (rows[-1][0] if rows else header_idx + 1) + 1
        lines.insert(insert_at, _render(header_fields, clean))
        return _join(lines, text), len(rows) + 1, clean
    line_idx, fields = _row(rows, row)
    others = [m for m in current if m["row"] != row]
    kept = current[row - 1]["telegram"] if isinstance(member, dict) and "telegram" not in member else ""
    clean = validate(member, cols, others, owner=current[row - 1]["owner"], kept_telegram=kept)
    lines[line_idx] = _render(header_fields, clean, fields)
    return _join(lines, text), row, clean


def delete_text(text: str, row) -> tuple[str, dict]:
    """`(new_text, member)` sin la fila `row`. La fila del dueño da `owner_row`."""
    header_idx, _, rows = table(text)
    if header_idx is None:
        raise EditError("unreadable", detail="el roster no tiene tabla de contactos")
    schema_error = roster_mod.write_schema_error(text)
    if schema_error:
        raise EditError("unreadable", detail=schema_error)
    line_idx, _ = _row(rows, row)
    _, current = members(text)
    gone = current[row - 1]
    if gone["owner"]:
        raise EditError("owner_row", field="row", detail="la fila del dueño no se borra desde la app")
    lines = text.splitlines()
    del lines[line_idx]
    return _join(lines, text), gone


def _add_column(text: str, name: str) -> str:
    """
    La tabla de contactos con la columna `name` al final, vacía en todas las filas.
    Sólo para `Rules` (SMS_GATEWAY.md §11) y `Telegram` (#628). Las demás celdas no cambian.
    """
    header_idx, header_fields, rows = table(text)
    lines = text.splitlines()
    lines[header_idx] = lines[header_idx].rstrip().rstrip("|").rstrip() + f" | {name} |"
    sep = lines[header_idx + 1].rstrip()
    lines[header_idx + 1] = (sep if sep.endswith("|") else sep + "|") + "---|"
    for idx, other in rows:
        cells = list(other) + [""] * (len(header_fields) - len(other))
        lines[idx] = "| " + " | ".join(c.strip() for c in cells) + " |  |"
    return _join(lines, text)


def set_rules_text(text: str, row, rules_id: str) -> str:
    """
    El roster con `rules_id` en la columna `Rules` de `row` (I-1). Si la tabla no
    tiene esa columna, la agrega al final: es la única columna que la pasarela
    agrega por su cuenta (SMS_GATEWAY.md §11). Las demás celdas no cambian.
    """
    header_idx, header_fields, rows = table(text)
    if header_idx is None:
        raise EditError("unreadable", detail="el roster no tiene tabla de contactos")
    schema_error = roster_mod.write_schema_error(text)
    if schema_error:
        raise EditError("unreadable", detail=schema_error)
    _row(rows, row)
    canon = [roster_mod.canonical_column(h) for h in header_fields]
    if "rules" not in canon:
        text = _add_column(text, "Rules")
        header_idx, header_fields, rows = table(text)
        canon = [roster_mod.canonical_column(h) for h in header_fields]
    line_idx, fields = _row(rows, row)
    lines = text.splitlines()
    cells = [f.strip() for f in fields] + [""] * (len(header_fields) - len(fields))
    cells[canon.index("rules")] = rules_id
    lines[line_idx] = "| " + " | ".join(cells) + " |"
    return _join(lines, text)


# --- escribir ---------------------------------------------------------------

def history_copy(path: Path, data: bytes, history_dir: Path, label: str) -> Path:
    """La copia fechada de `data` (Q4, I-4c). Nunca se sobrescribe una anterior."""
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = history_dir / f"{label}.{stamp}{path.suffix}"
    n = 1
    while target.exists():
        n += 1
        target = history_dir / f"{label}.{stamp}-{n}{path.suffix}"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return target


def write_checked(path: Path, original: bytes | None, new_text: str, check) -> None:
    """
    Escribe atómicamente y relee. Si `check(texto_releído)` es falso o algo falla,
    restaura el archivo byte por byte (o lo quita, si esta escritura lo creó) y
    lanza `EditError("write_failed")`.
    """
    from paynani_lib import roster_cli  # el mismo mecanismo de escritura

    try:
        roster_cli._write_atomic(path, new_text)
        if check(path.read_text(encoding="utf-8")):
            return
        failure = "el archivo escrito no se volvió a leer igual"
    except (OSError, UnicodeDecodeError) as exc:
        failure = f"no se pudo escribir: {exc}"
    try:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            roster_cli._write_bytes_atomic(path, original)
    except OSError as exc:
        raise EditError("write_failed", detail=f"{failure}, y no se pudo restaurar: {exc}") from exc
    raise EditError("write_failed", detail=f"{failure}; se restauró")


def apply(path: Path, expected_etag: str, transform, *, state_dir: Path, label: str,
          template: Path = TEMPLATE) -> dict:
    """
    Aplica `transform(text) -> (new_text, info)` a `path` en un solo paso:
    bloqueo, `etag`, copia fechada, escritura atómica y relectura.

    Un archivo que no existe empieza desde `template` (como `paynani roster add`)
    y su `etag` es `""`. Devuelve `{"etag", "etag_before", "backup", "info", "text"}`.
    """
    path = Path(path)
    if not isinstance(expected_etag, str):
        raise EditError("missing_field", field="etag", detail="falta etag")
    try:
        with locked(path, state_dir):
            data = read_bytes(path)
            current = etag_of(data)
            if expected_etag != current:
                raise EditError("conflict", detail="el archivo cambió", etag=current)
            try:
                text = data.decode("utf-8") if data is not None else template.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise EditError("unreadable", detail=str(exc)) from exc
            new_text, info = transform(text)
            backup = history_copy(path, data, Path(state_dir) / "history", label) if data is not None else None
            if data is None:
                # El roster de una cuenta adicional que todavía no existe: su carpeta
                # (rosters/) puede faltar también. accounts.py ya comprobó que está
                # dentro de la carpeta de accounts.json.
                path.parent.mkdir(parents=True, exist_ok=True)
            expected = _signature(new_text)
            write_checked(path, data, new_text, lambda again: _signature(again) == expected)
            return {"etag": etag_of(read_bytes(path)), "etag_before": current,
                    "backup": str(backup) if backup else "", "info": info, "text": new_text}
    except TimeoutError as exc:
        raise EditError("write_failed", detail=str(exc)) from exc


def apply_file(path: Path, expected_etag: str, new_text: str, *, state_dir: Path, label: str) -> dict:
    """
    Escribe `new_text` en `path` (un archivo de reglas, I-4c) en un solo paso: el
    mismo bloqueo, `etag`, copia fechada, escritura atómica y relectura que `apply`,
    sin la plantilla del roster. `{"etag", "etag_before", "backup"}`.
    """
    path = Path(path)
    if not isinstance(expected_etag, str):
        raise EditError("missing_field", field="etag", detail="falta etag")
    try:
        with locked(path, state_dir):
            data = read_bytes(path)
            current = etag_of(data)
            if expected_etag != current:
                raise EditError("conflict", detail="el archivo cambió", etag=current)
            backup = history_copy(path, data, Path(state_dir) / "history", label) if data is not None else None
            if data is None:
                # Las instrucciones no son un secreto, pero tampoco son de nadie más
                # que del dueño: 700 la carpeta y 600 el archivo, que la escritura
                # atómica conserva.
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            write_checked(path, data, new_text, lambda again: again == new_text)
            return {"etag": etag_of(read_bytes(path)), "etag_before": current,
                    "backup": str(backup) if backup else ""}
    except TimeoutError as exc:
        raise EditError("write_failed", detail=str(exc)) from exc
