"""
El formato de los avisos al dueño que llevan datos: la conclusión primero, los datos en
renglones y al final qué hacer si no fue él. Cada aviso sale dos veces, en texto plano y
en HTML adaptable al teléfono, y `notify.Notifier.owner(..., html=...)` manda las dos
partes con `send.sh --html`.

El HTML va con estilos en línea y tablas, sin imágenes ni nada de fuera: es lo que los
clientes de correo respetan. Los colores son los de `brand/README.md`.

Los tres avisos de «Apps conectadas» (PRD #719) están aquí: `app_connected`,
`app_disconnected` y `app_revoked`. Ninguno lleva el token.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field

from . import when

GRANA = "#8f2d2b"
TINTA = "#1c1c1a"
PAPEL = "#f7f7f5"
GRIS = "#66655f"
LINEA = "#dedcd6"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


@dataclass
class Notice:
    title: str                                    # el encabezado del HTML: qué pasó, en pocas palabras
    lead: str                                     # la conclusión: la primera línea del correo
    rows: list[tuple[str, str]] = field(default_factory=list)   # (etiqueta, valor); sin valor no sale
    after: list[str] = field(default_factory=list)              # párrafos después de los datos
    warn_title: str = ""                          # «Si no fuiste tú»
    warn: list[str] = field(default_factory=list)               # los pasos; `así` es un comando

    def text(self) -> str:
        rows = [(label, value) for label, value in self.rows if value]
        width = max((len(label) for label, _ in rows), default=0) + 1
        lines = [self.lead, ""]
        lines += [f"  {(label + ':').ljust(width)}  {value}" for label, value in rows]
        if rows:
            lines.append("")
        for paragraph in self.after:
            lines += [paragraph, ""]
        if self.warn:
            lines.append(f"{self.warn_title}:")
            lines += [f"  - {step}" for step in self.warn]
            lines.append("")
        return "\n".join(lines).rstrip("\n") + "\n"

    def html(self) -> str:
        e = _html.escape
        rows = "".join(
            f'<tr><td style="padding:6px 12px 6px 0;color:{GRIS};font-size:14px;line-height:20px;'
            f'vertical-align:top;white-space:nowrap">{e(label)}</td>'
            f'<td style="padding:6px 0;color:{TINTA};font-size:15px;line-height:20px;font-weight:600;'
            f'vertical-align:top;word-break:break-word">{e(value)}</td></tr>'
            for label, value in self.rows if value)
        if rows:
            rows = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                    f'style="margin:0 0 20px;border-top:1px solid {LINEA};border-bottom:1px solid {LINEA}">'
                    f'<tr><td style="padding:8px 0"><table role="presentation" cellpadding="0" cellspacing="0" '
                    f'border="0">{rows}</table></td></tr></table>')
        after = "".join(f'<p style="margin:0 0 16px;font-size:15px;line-height:22px;color:{TINTA}">'
                        f'{_inline(paragraph)}</p>' for paragraph in self.after)
        warn = ""
        if self.warn:
            steps = "".join(f'<li style="margin:0 0 6px">{_inline(step)}</li>' for step in self.warn)
            warn = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
                    f'<tr><td style="padding:14px 16px;background:{PAPEL};border-left:4px solid {GRANA};'
                    f'border-radius:4px">'
                    f'<p style="margin:0 0 8px;font-size:15px;line-height:22px;font-weight:700;color:{GRANA}">'
                    f'{e(self.warn_title)}</p>'
                    f'<ul style="margin:0;padding:0 0 0 20px;font-size:15px;line-height:22px;color:{TINTA}">'
                    f'{steps}</ul></td></tr></table>')
        return (
            '<!DOCTYPE html>\n<html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(self.title)}</title></head>'
            f'<body style="margin:0;padding:0;background:{PAPEL}">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="background:{PAPEL}"><tr><td align="center" style="padding:24px 12px">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="max-width:560px;background:#ffffff;border:1px solid {LINEA};border-radius:10px;'
            f'font-family:{_FONT}"><tr><td style="padding:24px 24px 20px">'
            f'<p style="margin:0 0 16px;font-size:13px;line-height:16px;font-weight:700;letter-spacing:.04em;'
            f'color:{GRANA}">paynani</p>'
            f'<h1 style="margin:0 0 10px;font-size:20px;line-height:26px;font-weight:700;color:{TINTA}">'
            f'{e(self.title)}</h1>'
            f'<p style="margin:0 0 20px;font-size:15px;line-height:22px;color:{TINTA}">{e(self.lead)}</p>'
            f'{rows}{after}{warn}'
            '</td></tr></table>'
            f'<p style="margin:14px 0 0;font-family:{_FONT};font-size:12px;line-height:18px;color:{GRIS}">'
            'Aviso automático de tu instalación de paynani.</p>'
            '</td></tr></table></body></html>\n')


def _inline(text: str) -> str:
    """El texto escapado; lo que va entre acentos graves es un comando y sale en monoespaciado."""
    parts = text.split("`")
    if len(parts) % 2 == 0:          # un acento sin pareja: se deja tal cual
        return _html.escape(text)
    out = []
    for index, part in enumerate(parts):
        if index % 2:
            # inline-block: un comando que no cabe baja entero a su renglón y se parte en los
            # espacios, no a media palabra.
            out.append(f'<code style="display:inline-block;max-width:100%;font-family:{_MONO};font-size:13px;'
                       f'line-height:20px;background:#ffffff;border:1px solid {LINEA};border-radius:4px;'
                       f'padding:2px 6px;overflow-wrap:anywhere">{_html.escape(part)}</code>')
        else:
            out.append(_html.escape(part))
    return "".join(out)


def moment(stamp: str | None, lang: str = "es-MX") -> str:
    """«jueves, 5 de noviembre de 2026, 13:48 CST», en la zona del host; lo que no se entiende, tal cual."""
    parsed = when.parse(stamp or "")
    return when.full(parsed.astimezone(), lang) if parsed else (stamp or "")


def _app(record: dict) -> str:
    return f"{record.get('app_name') or 'app'} {record.get('app_version') or ''}".strip()


def app_connected(record: dict, address: str) -> Notice:
    """Una app se emparejó con un código (`POST /api/owner/pair`)."""
    client = record["client_id"]
    return Notice(
        title="Nueva app conectada",
        lead=f"Se conectó «{record['name']}» a tu paynani. Ahora puede administrar esta instalación.",
        rows=[("App", _app(record)), ("Nombre", record["name"]), ("Dirección", address),
              ("Cuándo", moment(record.get("paired_at"))), ("Cómo", "con un código de emparejamiento"),
              ("Id", client)],
        warn_title="Si no fuiste tú, revócala",
        warn=["En PaynaniWeb, «Apps conectadas».",
              f"O en la terminal: `scripts/paynani web clients revoke {client}`"])


def app_disconnected(record: dict, address: str) -> Notice:
    """La app se revocó a sí misma (la acción `Disconnect`)."""
    return Notice(
        title="App desconectada",
        lead=f"«{record['name']}» se desconectó de tu paynani. Su token ya no abre la API del dueño.",
        rows=[("App", _app(record)), ("Nombre", record["name"]), ("Dirección", address),
              ("Cuándo", moment(record.get("revoked_at"))), ("Cómo", "desde la propia app"),
              ("Id", record["client_id"])],
        after=["Para volver a conectarla hace falta un código de emparejamiento nuevo."])


def app_revoked(record: dict, address: str) -> Notice:
    """El dueño la revocó en PaynaniWeb, «Apps conectadas»."""
    return Notice(
        title="App revocada",
        lead=f"Se revocó «{record['name']}» desde PaynaniWeb. Su token ya no abre la API del dueño.",
        rows=[("App", _app(record)), ("Nombre", record["name"]), ("Dirección", address),
              ("Cuándo", moment(record.get("revoked_at"))), ("Cómo", "en PaynaniWeb, «Apps conectadas»"),
              ("Id", record["client_id"])],
        warn_title="Si no fuiste tú",
        warn=["Cambia la contraseña de PaynaniWeb con `scripts/paynani web passwd`, que cierra todas "
              "las sesiones.",
              "Revisa las demás en «Apps conectadas»."])
