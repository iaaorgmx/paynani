#!/usr/bin/env python3
"""
Tests for the time of each message in a PaynaniWeb thread (PRD #455 4.4; T4 of
#456). An assertion script, like the rest of this suite.

`when.render()` es lo que se ve si `assets/time.js` no corre: la zona del host y el
formato de cada idioma. Aquí la zona es fija (CDT, la de Julian) y «ahora» también,
para que las horas del hilo del PRD salgan como en Gmail: 12:25, 12:27, 12:28 y 12:30.
"""
from __future__ import annotations

import http.client
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, notify, strings, users, when  # noqa: E402,F401

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


CDT = timezone(timedelta(hours=-5), "CDT")
NOW = datetime(2026, 10, 21, 17, 34, tzinfo=timezone.utc)    # 12:34 en la Ciudad de México


def shown(stamp, lang, now=NOW):
    i18n.set_current(lang)
    return when.render(stamp, lang, now=now, tz=CDT)


# --- el hilo del PRD, hoy: la hora y hace cuánto ---------------------------------------------
for stamp, en, mx in (("2026-10-21T17:25:00Z", "12:25 PM (9 minutes ago)", "12:25 p. m. (hace 9 minutos)"),
                      ("2026-10-21T17:27:00Z", "12:27 PM (7 minutes ago)", "12:27 p. m. (hace 7 minutos)"),
                      ("2026-10-21T17:28:00Z", "12:28 PM (6 minutes ago)", "12:28 p. m. (hace 6 minutos)"),
                      ("2026-10-21T17:30:00Z", "12:30 PM (4 minutes ago)", "12:30 p. m. (hace 4 minutos)")):
    check(f"{stamp}: en-US como Gmail", en, shown(stamp, "en-US")[1])
    check(f"{stamp}: es-MX", mx, shown(stamp, "es-MX")[1])
check("es-ES, fr-FR y pt-BR van en 24 h", ("12:25 (hace 9 minutos)", "12:25 (il y a 9 minutes)", "12:25 (há 9 minutos)"),
      tuple(shown("2026-10-21T17:25:00Z", lang)[1] for lang in ("es-ES", "fr-FR", "pt-BR")))
check("el atributo datetime va en UTC", "2026-10-21T17:25:00Z", shown("2026-10-21T17:25:00Z", "es-MX")[0])
check("una fecha con zona (la cabecera Date) se entiende igual", "12:25 p. m. (hace 9 minutos)",
      shown("2026-10-21T12:25:00-05:00", "es-MX")[1])
check("hace menos de un minuto: «ahora»", "12:34 p. m. (ahora)", shown("2026-10-21T17:34:20Z", "es-MX")[1])
check("hace una hora y hace tres", ("11:34 a. m. (hace 1 hora)", "9:30 a. m. (hace 3 horas)"),
      (shown("2026-10-21T16:34:00Z", "es-MX")[1], shown("2026-10-21T14:30:00Z", "es-MX")[1]))
check("medianoche y mediodía en 12 h", ("12:05 a. m. (hace 12 horas)", "12:00 PM (34 minutes ago)"),
      (shown("2026-10-21T05:05:00Z", "es-MX")[1], shown("2026-10-21T17:00:00Z", "en-US")[1]))

check("short (las listas): de hoy solo la hora, sin «hace …»", ("12:25 PM", "12:25 p. m."),
      (when.render("2026-10-21T17:25:00Z", "en-US", now=NOW, tz=CDT, short=True)[1],
       when.render("2026-10-21T17:25:00Z", "es-MX", now=NOW, tz=CDT, short=True)[1]))
check("short: de otro día, igual que sin short", shown("2026-10-20T17:25:00Z", "es-MX")[1],
      when.render("2026-10-20T17:25:00Z", "es-MX", now=NOW, tz=CDT, short=True)[1])

# --- antes de hoy: la fecha corta ---------------------------------------------------------------
check("de otro día del año: la fecha corta y la hora, sin año",
      ("Oct 20, 12:25 PM", "20 oct, 12:25 p. m.", "20 oct, 12:25", "20 oct., 12:25", "20 de out., 12:25"),
      tuple(shown("2026-10-20T17:25:00Z", lang)[1] for lang in ("en-US", "es-MX", "es-ES", "fr-FR", "pt-BR")))
check("de otro año: con el año", ("Dec 31, 2025, 7:00 PM", "31 dic 2025, 7:00 p. m.", "31 de dez. de 2025, 19:00"),
      tuple(shown("2026-01-01T00:00:00Z", lang)[1] for lang in ("en-US", "es-MX", "pt-BR")))
check("la zona decide el día: las 00:30 UTC del 22 todavía son el 21 en CDT", True,
      shown("2026-10-22T00:30:00Z", "es-MX", now=datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc))[1].startswith("7:30 p. m. (hace"))

# --- la fecha completa, al pasar el cursor -------------------------------------------------------
check("title: la fecha completa con la zona",
      ("Wednesday, October 21, 2026, 12:25 PM CDT", "miércoles, 21 de octubre de 2026, 12:25 p. m. CDT",
       "mercredi 21 octobre 2026, 12:25 CDT", "quarta-feira, 21 de outubro de 2026, 12:25 CDT"),
      tuple(shown("2026-10-21T17:25:00Z", lang)[2] for lang in ("en-US", "es-MX", "fr-FR", "pt-BR")))
check("una hora que no se entiende sale tal cual, sin datetime", ("", "ayer", ""), shown("ayer", "es-MX"))
check("sin hora: nada", ("", "", ""), shown("", "es-MX"))
check("sin tz, la del host", True, when.render("2026-10-21T17:25:00Z", "es-MX")[0] == "2026-10-21T17:25:00Z")
i18n.set_current("es-MX")

# --- el script se sirve y no cambia la CSP ---------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
users.create("dueno@example.com", "Dueño", "una-contraseña-larga", tmp / "web" / "user.json")
ctx = app.Context(tmp / "web" / "user.json", notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", state_dir=tmp / "state",
                  roster_path=tmp / "roster.md")
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
conn.request("GET", "/assets/time.js", headers={"Host": "agente.ngrok.app"})
r = conn.getresponse()
body = r.read().decode("utf-8")
check("/assets/time.js se sirve como JavaScript, sin sesión", (200, True, True),
      (r.status, r.getheader("Content-Type", "").startswith("application/javascript"), "Intl.RelativeTimeFormat" in body))
check("y solo toca los <time datetime> del hilo y de las listas", True,
      "'.mensajes time[datetime], .correos time[datetime]'" in body)
check("en las listas (data-corto), de hoy solo la hora, como Gmail", True, "hasAttribute('data-corto')" in body)
check("con menos de un minuto dice «ahora», como when.py, y no «este minuto» (revisión de #460)", True,
      "if (minutes === 0) {" in body and "rtf.format(0, 'second')" in body)
httpd.shutdown()
httpd.server_close()
shell_src = (ROOT / "scripts" / "paynani_lib" / "web" / "shell.py").read_text(encoding="utf-8")
check("el marco lo carga con defer, desde /assets/ (la CSP no cambia)", True,
      '<script src="/assets/time.js" defer></script>' in shell_src)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
