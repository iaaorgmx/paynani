"""
Archivos que llegan por Telegram (PRD #609 FR-18; TELEGRAM.md §1, `media/`).

El nombre, el MIME y el tamaño que manda Telegram son datos no confiables. Aquí:

- `declared()` dice qué tipo dijo Telegram que es (por el MIME o, sin MIME útil, por la
  extensión del nombre), como una de las categorías de `REAL_TYPES`;
- `sniff()` dice qué es de verdad por su contenido: firmas de imagen (JPEG, PNG, WebP),
  PDF, audio y video, y OOXML (`.docx`, `.xlsx`, `.pptx`) revisando el ZIP sin extraerlo;
- el archivo se acepta sólo si las dos coinciden. Los formatos OLE (`.doc`, `.xls`,
  `.ppt`), los OOXML con macros y cualquier otro tipo se rechazan.

La descarga, el límite de bytes y el nombre aleatorio están en el servicio.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

# tipo real -> (categoría, extensión, MIME)
REAL_TYPES = {
    "jpeg": ("image", "jpg", "image/jpeg"),
    "png": ("image", "png", "image/png"),
    "webp": ("image", "webp", "image/webp"),
    "pdf": ("pdf", "pdf", "application/pdf"),
    "ogg": ("audio", "ogg", "audio/ogg"),
    "mp3": ("audio", "mp3", "audio/mpeg"),
    "m4a": ("audio", "m4a", "audio/mp4"),
    "wav": ("audio", "wav", "audio/wav"),
    "mp4": ("video", "mp4", "video/mp4"),
    "mov": ("video", "mov", "video/quicktime"),
    "webm": ("video", "webm", "video/webm"),
    "docx": ("docx", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "xlsx": ("xlsx", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "pptx": ("pptx", "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}

_OOXML_MIME = {mime: cat for cat, (_, _, mime) in REAL_TYPES.items() if cat in ("docx", "xlsx", "pptx")}
_EXT = {"jpg": "image", "jpeg": "image", "png": "image", "webp": "image", "pdf": "pdf",
        "ogg": "audio", "oga": "audio", "opus": "audio", "mp3": "audio", "m4a": "audio", "wav": "audio",
        "mp4": "video", "mov": "video", "webm": "video", "docx": "docx", "xlsx": "xlsx", "pptx": "pptx"}
# El tipo de mensaje de Telegram que no trae MIME propio.
_KIND = {"image": "image", "voice": "audio", "video": "video"}

# OOXML: la parte principal y su content type (sin macros: los .docm/.xlsm/.pptm
# tienen otro content type, y además se rechaza cualquier vbaProject.bin).
_MAIN = {
    "docx": ("word/document.xml",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
    "xlsx": ("xl/workbook.xml",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
    "pptx": ("ppt/presentation.xml",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
}
MAX_ZIP_ENTRIES = 2000
MAX_UNZIPPED = 200 * 1024 * 1024
MAX_RATIO = 200                 # tamaño descomprimido / comprimido de una entrada
MAX_CONTENT_TYPES = 1024 * 1024


def declared(kind: str, mime: str | None, filename: str | None) -> str | None:
    """La categoría que declaró Telegram, o None si no es un tipo que paynani acepta."""
    if kind in _KIND and not mime:
        return _KIND[kind]
    mime = (mime or "").split(";", 1)[0].strip().lower()
    if mime in _OOXML_MIME:
        return _OOXML_MIME[mime]
    if mime == "application/pdf":
        return "pdf"
    for prefix in ("image", "audio", "video"):
        if mime.startswith(prefix + "/"):
            return prefix
    if mime in ("", "application/octet-stream"):
        ext = Path(str(filename or "")).suffix.lower().lstrip(".")
        if ext:
            return _EXT.get(ext)
        return _KIND.get(kind)
    return None


def sniff(path: Path) -> str | None:
    """El tipo real del archivo por su contenido, o None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return None
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B "):
            return "m4a"
        if brand == b"qt  ":
            return "mov"
        return "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if head.startswith(b"PK\x03\x04"):
        return ooxml(path)
    return None


def ooxml(path: Path) -> str | None:
    """`docx`, `xlsx` o `pptx` si el ZIP es un OOXML sin macros, revisado sin extraerlo."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                return None
            total = 0
            names = set()
            for info in infos:
                total += info.file_size
                if total > MAX_UNZIPPED:
                    return None
                if info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                    return None                      # una bomba de compresión
                names.add(info.filename)
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                return None
            if "[Content_Types].xml" not in names:
                return None
            ct = zf.getinfo("[Content_Types].xml")
            if ct.file_size > MAX_CONTENT_TYPES:
                return None
            overrides = _overrides(zf.read(ct))
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError):
        return None
    if overrides is None:
        return None
    found = [kind for kind, (part, ctype) in _MAIN.items()
             if part in names and overrides.get("/" + part) == ctype]
    return found[0] if len(found) == 1 else None


_CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"


def _overrides(raw: bytes) -> dict[str, str] | None:
    """
    `{PartName: ContentType}` de los `Override` de `[Content_Types].xml`, o None si el
    XML no es válido, trae DOCTYPE o entidades, no es un `Types`, o una parte aparece dos
    veces (ambiguo). Así la parte principal se valida con su propio `Override`, no con
    un texto que aparezca en cualquier lugar del archivo (Ximena, #618).
    """
    import xml.etree.ElementTree as ET

    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return None
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        return None
    if root.tag != _CT_NS + "Types":
        return None
    out: dict[str, str] = {}
    for el in root:
        if el.tag != _CT_NS + "Override":
            continue
        part = (el.get("PartName") or "").strip()
        ctype = (el.get("ContentType") or "").strip()
        if not part or part.lower() in {p.lower() for p in out}:
            return None
        out[part] = ctype
    return out


def accept(path: Path, category: str | None) -> str | None:
    """El tipo real si coincide con la categoría declarada; si no, None (rechazado por tipo)."""
    if category is None:
        return None
    real = sniff(path)
    if real is None or REAL_TYPES[real][0] != category:
        return None
    return real


def remove(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
