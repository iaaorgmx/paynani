"""
La hora de cada mensaje de un hilo (PRD #455, 4.4; T4 de #456).

Va en la zona del navegador: `assets/time.js` reescribe cada `<time datetime>` con
`Intl`. Lo que este módulo escribe es lo que queda si el script no corre (Q50 = A):
la misma forma, en la zona del host y con el formato del idioma de la página.

- Hoy: solo la hora y, entre paréntesis, hace cuánto. «12:25 p. m. (hace 9 minutos)».
- Antes: la fecha corta y la hora. «21 oct, 12:25 p. m.», con el año si es de otro.
- En `title`, la fecha completa con la zona, para verla al pasar el cursor.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import i18n

MONTHS = {
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "fr": ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."),
    "pt": ("jan.", "fev.", "mar.", "abr.", "mai.", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."),
}
MONTHS_LONG = {
    "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
    "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"),
    "pt": ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
           "novembro", "dezembro"),
}
WEEKDAYS = {
    "es": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "fr": ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"),
    "pt": ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"),
}


def _base(lang: str) -> str:
    base = (lang or "es-MX").split("-")[0].lower()
    return base if base in MONTHS else "es"


def clock(when: datetime, lang: str) -> str:
    """La hora como la escribe cada idioma: «12:25 PM», «12:25 p. m.» o «12:25»."""
    if lang in ("en-US", "es-MX"):
        hour = when.hour % 12 or 12
        mark = ("AM" if when.hour < 12 else "PM") if lang == "en-US" else ("a. m." if when.hour < 12 else "p. m.")
        return f"{hour}:{when.minute:02d} {mark}"
    return f"{when.hour:02d}:{when.minute:02d}"


def short_date(when: datetime, lang: str, *, year: bool) -> str:
    base = _base(lang)
    month = MONTHS[base][when.month - 1]
    if base == "en":
        return f"{month} {when.day}" + (f", {when.year}" if year else "")
    if base == "pt":
        return f"{when.day} de {month}" + (f" de {when.year}" if year else "")
    return f"{when.day} {month}" + (f" {when.year}" if year else "")


def full(when: datetime, lang: str) -> str:
    """«miércoles, 21 de octubre de 2026, 12:25 p. m. CDT»: lo que se ve al pasar el cursor."""
    base = _base(lang)
    day = WEEKDAYS[base][when.weekday()]
    month = MONTHS_LONG[base][when.month - 1]
    zone = when.strftime("%Z") or when.strftime("%z")
    if base == "en":
        date = f"{day}, {month} {when.day}, {when.year}"
    elif base == "fr":
        date = f"{day} {when.day} {month} {when.year}"
    else:
        date = f"{day}, {when.day} de {month} de {when.year}"
    return f"{date}, {clock(when, lang)} {zone}".strip()


def ago(seconds: float) -> str:
    """«hace 9 minutos» y sus pares, de las cadenas web.time.* del idioma de la página."""
    minutes = max(0, int(seconds // 60))
    if minutes < 1:
        return i18n.t("web.time.now")
    if minutes < 60:
        return i18n.t("web.time.min1") if minutes == 1 else i18n.t("web.time.mins", n=minutes)
    hours = minutes // 60
    return i18n.t("web.time.hour1") if hours == 1 else i18n.t("web.time.hours", n=hours)


def parse(stamp: str) -> datetime | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def render(stamp: str, lang: str, *, now: datetime | None = None, tz=None,
           short: bool = False) -> tuple[str, str, str]:
    """
    (ISO en UTC para `datetime`, el texto que se ve, la fecha completa para `title`), en
    la zona `tz` (la del host si es None). Un `stamp` que no se entiende sale tal cual.
    `short` es para las listas, como Gmail: de hoy, solo la hora, sin «hace …».
    """
    when = parse(stamp)
    if when is None:
        return "", stamp or "", ""
    local = when.astimezone(tz)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    iso = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if local.date() == now.date():
        shown = clock(local, lang) if short else f"{clock(local, lang)} ({ago((now - local).total_seconds())})"
    else:
        shown = f"{short_date(local, lang, year=local.year != now.year)}, {clock(local, lang)}"
    return iso, shown, full(local, lang)
