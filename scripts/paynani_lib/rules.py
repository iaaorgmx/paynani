"""
Instrucciones del agente por contacto (R3 de #410, PRD #409 I-1 a I-6): los
archivos `rules/<id>.md` y `rules/default.md` de la instalación.

Un archivo es una cabecera YAML entre `---` y Markdown libre debajo:

    ---
    version: 1
    enabled: true
    reply:
      email: normal
      sms: never
    updated_at: 2026-10-20T07:00:00Z
    updated_by: phone d_fb89b8
    ---

    ## General
    …

La cabecera es un subconjunto fijo de YAML que este módulo lee y escribe por su
cuenta, sin depender de PyYAML: llaves conocidas, `true`/`false`, y `reply` con
dos hijos sangrados. Cualquier otra cosa se rechaza con el campo que falla (I-6).

Las reglas **no autorizan nada** (I-5): no agregan destinatarios ni permisos, y
nada de aquí lo alcanza un correo o un SMS. Las escribe sólo la pantalla «Roster»
del teléfono emparejado (sms/roster_api.py) o una persona con su editor.

`rules/` es uno por instalación, en el clon junto a `roster.md`, y fuera de git
(.gitignore), como el roster.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from paynani_lib.roster_edit import EditError  # noqa: E402

DEFAULT_ID = "default"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
MAX_BYTES = 32 * 1024
VERSION = 1
CHANNELS = ("email", "sms")
REPLY_VALUES = ("normal", "never")
KEYS = ("version", "enabled", "reply", "updated_at", "updated_by")


def rules_dir(root: Path | None = None) -> Path:
    """
    `rules/` de la instalación: en el clon, junto a roster.md. `PAYNANI_RULES`
    (una carpeta) lo cambia, como `ROSTER` en send.sh: para las pruebas.
    """
    if root is None:
        override = os.environ.get("PAYNANI_RULES", "").strip()
        if override:
            return Path(override).expanduser()
    return (_REPO_ROOT if root is None else Path(root)) / "rules"


def path_for(rules_id: str, root: Path | None = None) -> Path:
    if rules_id != DEFAULT_ID and not ID_RE.match(rules_id or ""):
        raise EditError("invalid", field="rules", reason="rules_id", detail=f"«{rules_id}» no es un id de reglas")
    return rules_dir(root) / f"{rules_id}.md"


# --- leer y validar ------------------------------------------------------------

def _bad(field: str, reason: str, detail: str):
    raise EditError("invalid", field=field, reason=reason, detail=detail)


def split(text: str) -> tuple[list[str], str]:
    """`(líneas de la cabecera, cuerpo)`. Sin cabecera entre `---`: `header_missing`."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        _bad("header", "header_missing", "el archivo empieza con una cabecera entre ---")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    _bad("header", "header_missing", "la cabecera no cierra con ---")


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parse(text: str) -> dict:
    """
    La cabecera validada: `{"version", "enabled", "reply": {"email", "sms"},
    "reply_set": {...}, "updated_at", "updated_by", "body"}`. `reply_set` dice qué
    canales escribió el archivo, para que `default.md` cuente donde el contacto no
    dice nada. Lanza `EditError("invalid")` con el primer campo que falla.
    """
    if not isinstance(text, str):
        _bad("text", "required", "text es texto")
    if len(text.encode("utf-8")) > MAX_BYTES:
        _bad("text", "too_large", f"más de {MAX_BYTES:,} bytes")
    header, body = split(text)
    values: dict = {}
    reply: dict = {}
    in_reply = False
    for raw in header:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw[:1] in (" ", "\t")
        key, sep, value = raw.strip().partition(":")
        key = key.strip()
        if not sep:
            _bad("header", "unknown_key", f"«{raw.strip()}» no es llave: valor")
        if indented:
            if not in_reply:
                _bad("header", "unknown_key", f"«{key}» sangrada fuera de reply")
            if key not in CHANNELS:
                _bad("header", "unknown_key", f"reply.{key} no existe (email, sms)")
            if key in reply:
                _bad(f"header.reply.{key}", "value", f"reply.{key} está dos veces")
            reply[key] = _scalar(value)
            continue
        in_reply = key == "reply"
        if key not in KEYS:
            _bad("header", "unknown_key", f"«{key}» no es una llave de la cabecera")
        if key in values:
            _bad(f"header.{key}", "value", f"{key} está dos veces")
        if key == "reply":
            if value.strip():
                _bad("header.reply", "value", "reply lleva email y sms debajo, sangrados")
            values["reply"] = True
            continue
        values[key] = _scalar(value)
    if values.get("version") != str(VERSION):
        _bad("header.version", "value", "version es 1")
    if values.get("enabled") not in ("true", "false"):
        _bad("header.enabled", "value", "enabled es true o false")
    for channel in CHANNELS:
        if channel in reply and reply[channel] not in REPLY_VALUES:
            _bad(f"header.reply.{channel}", "value", f"reply.{channel} es normal o never")
    return {"version": VERSION, "enabled": values["enabled"] == "true",
            "reply": {c: reply.get(c, "normal") for c in CHANNELS},
            "reply_set": {c for c in CHANNELS if c in reply},
            "updated_at": values.get("updated_at", ""), "updated_by": values.get("updated_by", ""),
            "body": body}


def render(parsed: dict, *, updated_at: str, updated_by: str) -> str:
    """
    El archivo con su cabecera en forma canónica y `updated_at`/`updated_by` de la
    pasarela, no de quien lo mandó. Un canal que el archivo no escribió no se
    escribe, para que siga contando el de `default.md`.
    """
    lines = ["---", f"version: {VERSION}", f"enabled: {'true' if parsed['enabled'] else 'false'}"]
    channels = [c for c in CHANNELS if c in parsed["reply_set"]]
    if channels:
        lines.append("reply:")
        lines += [f"  {c}: {parsed['reply'][c]}" for c in channels]
    lines += [f"updated_at: {updated_at}", f"updated_by: {updated_by}", "---"]
    body = parsed["body"]
    return "\n".join(lines) + "\n" + (body if body.endswith("\n") or not body else body + "\n")


# --- secciones y regla efectiva ---------------------------------------------------

def sections(body: str) -> list[tuple[str, str]]:
    """
    `[(nombre, texto), ...]` por cada `## Nombre`, en orden. Lo que va antes del
    primer `##` es la sección `""`. El nombre se compara sin mayúsculas ni espacios
    de más.
    """
    out: list[tuple[str, list[str]]] = [("", [])]
    for line in body.splitlines():
        m = re.match(r"^##(?!#)\s*(.*?)\s*$", line)
        if m:
            out.append((m.group(1), []))
            continue
        out[-1][1].append(line)
    cleaned = [(name, "\n".join(lines).strip("\n")) for name, lines in out]
    return [(name, text) for name, text in cleaned if name or text.strip()]


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _active(text: str | None) -> dict | None:
    """El archivo leído si existe, es válido y tiene `enabled: true`; si no, None."""
    if not text:
        return None
    try:
        parsed = parse(text)
    except EditError:
        return None
    return parsed if parsed["enabled"] else None


def effective(default_text: str | None, contact_text: str | None) -> str:
    """
    La regla efectiva del contacto (R-7, I-4b): las secciones de `default.md`, y cada
    sección del contacto con el mismo nombre sustituye a la general completa; las que
    no están en `default.md` van después, en su orden. Un archivo apagado
    (`enabled: false`), inválido o que no existe no cuenta. Dentro de un archivo,
    `## Correo`/`## SMS` sobre `## General` (I-2) lo aplica el agente al leerla: aquí
    las dos se conservan.
    """
    base = _active(default_text)
    own = _active(contact_text)
    merged: list[tuple[str, str]] = list(sections(base["body"])) if base else []
    for name, text in sections(own["body"]) if own else []:
        for i, (existing, _) in enumerate(merged):
            if _key(existing) == _key(name):
                merged[i] = (name, text)
                break
        else:
            merged.append((name, text))
    parts = []
    for name, text in merged:
        parts.append(f"## {name}\n{text}".rstrip() if name else text)
    return "\n\n".join(p for p in parts if p.strip()).strip() + ("\n" if merged else "")


def effective_reply(default_text: str | None, contact_text: str | None) -> dict:
    """
    La política `reply` que vale para el contacto, por canal (I-3): la del contacto si
    la escribió y está activo, si no la de `default.md`, si no `normal`.
    """
    out = {c: "normal" for c in CHANNELS}
    for parsed in (_active(default_text), _active(contact_text)):
        if parsed:
            for c in parsed["reply_set"]:
                out[c] = parsed["reply"][c]
    return out


# --- ids ---------------------------------------------------------------------------

def new_id(name: str, taken) -> str:
    """
    Un id para el contacto: su nombre en minúsculas sin acentos, con guiones, más 4
    hex al azar (`ana-ruiz-9b1c`). Nunca `default` ni uno de `taken`.
    """
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:40].strip("-") or "contacto"
    taken = set(taken)
    while True:
        candidate = f"{slug}-{secrets.token_hex(2)}"
        if candidate not in taken and candidate != DEFAULT_ID and ID_RE.match(candidate):
            return candidate


def removed_name(rules_id: str, stamp: str) -> str:
    """`<id>.removed-<AAAAMMDDTHHMMSSZ>.md`, para la baja de un contacto con reglas."""
    return f"{rules_id}.removed-{stamp}.md"


def notice(rules_id, root: Path | None = None) -> dict | None:
    """
    Qué reglas nombra el aviso de un mensaje de un contacto del roster (A-1):
    `{"file": "rules/<id>.md", "status": "active"}`, o `"invalid"` si el archivo no
    pasa la validación (para que un error a mano no deje de aplicarse sin que nadie
    lo sepa, nota de #421), o None si no hay reglas que leer.

    Las del contacto si existen y están activas; si están apagadas o no hay, las
    generales (`rules/default.md`), si existen y están activas. El agente lee
    `default.md` y luego las del contacto (AGENTS.md).
    """
    def read(name):
        try:
            return path_for(name, root).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, EditError):
            return None

    for name in ([rules_id] if rules_id else []) + [DEFAULT_ID]:
        text = read(name)
        if text is None:
            continue
        try:
            parsed = parse(text)
        except EditError:
            return {"file": f"rules/{name}.md", "status": "invalid"}
        if parsed["enabled"]:
            return {"file": f"rules/{name}.md", "status": "active"}
    return None


def tag(note: dict | None) -> str:
    """La parte del corchete del aviso: `reglas: rules/x.md` o `reglas inválidas: rules/x.md`."""
    if not note:
        return ""
    label = "reglas" if note["status"] == "active" else "reglas inválidas"
    return f"{label}: {note['file']}"
