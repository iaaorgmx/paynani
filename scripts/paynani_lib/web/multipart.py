"""
`multipart/form-data` con la biblioteca estándar (#648): `cgi` ya no está en Python 3.13,
así que se lee con `email.parser` (`policy.HTTP`). Quien llama ya revisó `Content-Length`
contra su límite antes de leer el cuerpo.

`parse(raw, content_type)` → `(campos, archivos)`: los campos de texto como `form_fields`
(el primer valor de cada nombre) y los archivos como `[{field, name, mime, data}]`, sin
los vacíos que manda un `<input type="file">` sin elegir nada. El nombre del archivo es
sólo el último tramo (sin carpetas) y nunca llega a una ruta.
"""
from __future__ import annotations

import email.parser
import email.policy

MAX_PARTS = 40


class Malformed(ValueError):
    pass


def parse(raw: bytes, content_type: str) -> tuple[dict, list[dict]]:
    if not content_type.lower().startswith("multipart/form-data") or "boundary=" not in content_type.lower():
        raise Malformed("not multipart/form-data")
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", "replace")
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + raw)
    if not message.is_multipart():
        raise Malformed("no parts")
    fields: dict[str, str] = {}
    files: list[dict] = []
    for count, part in enumerate(message.iter_parts()):
        if count >= MAX_PARTS:
            raise Malformed("too many parts")
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition") or ""
        filename = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if filename is None:
            if name and name not in fields:
                fields[name] = data.decode(part.get_content_charset() or "utf-8", "replace")
            continue
        base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not base and not data:
            continue                         # un <input type="file"> sin archivo
        files.append({"field": name, "name": base or "archivo", "mime": part.get_content_type(), "data": data})
    return fields, files
