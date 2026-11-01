#!/usr/bin/env python3
"""
Tests del agente de IA en PaynaniWeb (#644): el semáforo (Q293), el modelo de la página
con un `dashboard.Fake` y una hora fija (atendidos hoy en la zona del host, la mediana de
respuesta, la última respuesta y lo que hizo hoy), el bloque del menú en todas las páginas
(debajo del usuario y arriba de «Management», con el nombre en 16 px sin negritas) y la
página `/agent` en un PaynaniWeb real en un puerto libre.

Nada aquí lee ni escribe la configuración real: todo va con `dashboard.Fake` y un
`state/` temporal, y al final se comprueba el sha256 del `.env` y de Himalaya.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import agent, agent_strings, app, auth, dashboard, notify, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


REAL = [Path.home() / ".claude/workspace/.env", Path.home() / ".config/himalaya/config.toml"]
BEFORE = [sha(p) for p in REAL]

CST = dt.timezone(dt.timedelta(hours=-6), "CST")
NOW = dt.datetime(2026, 11, 1, 9, 0, tzinfo=CST)


def utc(local: str) -> str:
    value = dt.datetime.fromisoformat(local).replace(tzinfo=CST).astimezone(dt.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def row(event_id, seen, state, at, who="Metis", subject="Hola"):
    return {"event_id": event_id, "observed_at": utc(seen), "state": state, "state_at": utc(at), "roster": True,
            "sender_name": who, "sender_address": f"{who.lower()}@example.com", "subject": subject}


def services(dispatcher="active", live=True, pending=0):
    return {"listener": {"unit": "active", "heartbeat_age_s": 5}, "dispatcher": {"unit": dispatcher},
            "session": {"live": live, "armed_at": utc("2026-11-01T08:46:00"), "expires_at": utc("2026-11-01T09:16:00")},
            "phone": None, "additional": [], "queue": {"pending": pending}}


# ---- El semáforo (Q293) ------------------------------------------------------------
check("Claude Code con sesión vigilando: online", "online", agent.status(services(), "claudecode"))
check("Claude Code sin sesión: no_session", "no_session", agent.status(services(live=False), "claudecode"))
check("despachador detenido: offline aunque haya sesión", "offline", agent.status(services(dispatcher="inactive"), "claudecode"))
check("despachador que no se puede consultar: offline", "offline", agent.status(services(dispatcher="unknown"), "claudecode"))
check("OpenClaw no tiene sesión que vigilar: online con el despachador activo", "online",
      agent.status(services(live=False), "openclaw"))
check("Hermes con el despachador detenido: offline", "offline", agent.status(services(dispatcher="failed"), "hermes"))
check("etiquetas de los runtimes", ("Claude Code", "OpenClaw", "Hermes", "?"),
      tuple(agent.runtime_label(r) for r in ("claudecode", "openclaw", "hermes", "")))

# ---- El modelo -------------------------------------------------------------------
MAIL = [
    row("imap:INBOX:1:1", "2026-11-01T08:00:00", "replied", "2026-11-01T08:02:00", who="Julian", subject="Clima"),
    row("imap:INBOX:1:2", "2026-11-01T08:10:00", "replied", "2026-11-01T08:16:00"),
    row("imap:INBOX:1:3", "2026-11-01T08:20:00", "replied", "2026-11-01T08:21:00"),
    row("imap:INBOX:1:4", "2026-11-01T07:30:00", "handled", "2026-11-01T07:31:00", who="GitHub"),
    row("imap:INBOX:1:5", "2026-11-01T08:50:00", "dispatched", "2026-11-01T08:50:05"),
    # Respondido ayer en CST (23:59 del 31) aunque en UTC ya sea el 1: no cuenta hoy.
    row("imap:INBOX:1:6", "2026-10-31T23:00:00", "replied", "2026-10-31T23:59:00"),
]
SENT = [{"at": utc("2026-11-01T08:21:00"), "to": "Metis", "subject": "Re: Hola", "message_id": "<a@x>"}]
SMS = [{"epoch": dt.datetime(2026, 11, 1, 8, 40, tzinfo=CST).timestamp(), "kind": "agent", "status": "delivered",
        "name": "", "number": "+15550001111"},
       {"epoch": dt.datetime(2026, 11, 1, 8, 55, tzinfo=CST).timestamp(), "kind": "received", "status": "",
        "name": "", "number": "+15550001111"}]
fake = dashboard.Fake(mail={"main": MAIL}, sent={"main": SENT}, sms=SMS, services=services(pending=1),
                      roster={"count": 5, "changes": []},
                      telegram={"state": "running", "bot_username": "NegocioBot"},
                      agent={"name": "Iris <Agente>", "email": "iris@example.com", "runtime": "claudecode"})
model = agent.build(fake, NOW)
check("atendidos hoy: 3 respondidos y 1 cerrado; el de ayer y el abierto no cuentan", {"replied": 3, "closed": 1},
      model["handled"])
check("la mediana de respuesta de hoy (2, 6 y 1 min): 2 min", 120.0, model["reply_median_s"])
check("esperando al agente: lo de la cola", 1, model["waiting"])
check("la última respuesta es el SMS de las 08:40, más nuevo que el correo de las 08:21",
      ("sms", "+15550001111", "08:40"), (model["last_reply"]["channel"], model["last_reply"]["who"],
                                          model["last_reply"]["at"].strftime("%H:%M")))
check("lo que hizo hoy: 4 correos cerrados y 1 SMS, el más nuevo primero, sin lo recibido",
      ["sms", "mail", "mail", "mail", "mail"], [a["channel"] for a in model["activity"]])
check("el modelo trae el estado, el runtime y que vigila con sesión", ("online", "Claude Code", True),
      (model["status"], model["runtime_label"], model["watches"]))
empty = agent.build(dashboard.Fake(), NOW)
check("sin respuestas hoy: sin mediana ni última respuesta", (None, None), (empty["reply_median_s"], empty["last_reply"]))
check("sin nombre del agente, la parte de su correo antes de la @", "agent",
      agent.summary(dashboard.Fake(agent={"name": "", "email": "agent@example.com", "runtime": ""}))["name"])

# ---- La web ----------------------------------------------------------------------
PASSWORD = "una-contraseña-larga"
tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
user_file = tmp / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
SOURCE = {"fake": fake}


class Switch(dashboard.Source):
    """Deja cambiar la fuente a media prueba (el estado, o una que falla)."""
    def __getattribute__(self, name):
        if name.startswith("_") or name not in dashboard.Source.__dict__:
            return object.__getattribute__(self, name)
        return getattr(SOURCE["fake"], name)


ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda l: None),
                  agent_email="iris@example.com", accounts_file=tmp / "accounts.json", state_dir=tmp / "state",
                  roster_path=tmp / "roster.md", dashboard_source=Switch(), now=lambda: NOW)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, cookie=""):
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.5"}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = f"https://{HOST}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


def menu(page: str) -> str:
    return page.split('<aside class="lateral"', 1)[1].split("</aside>", 1)[0]


status, hdrs, _ = req("GET", "/agent")
check("sin sesión, /agent va a la entrada", (303, True), (status, hdrs.get("location", "").startswith("/login")))
_, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]

for path in ("/?lang=en-US", "/about?lang=en-US", "/roster?lang=en-US"):
    _, _, page = req("GET", path, cookie=cookie)
    side = menu(page)
    order = [side.find(mark) for mark in ('<div class="usuario">', 'href="/profile"', '<a class="usuario agente-usuario"',
                                          '<div class="grupo">Management</div>')]
    check(f"{path.split('?')[0]}: el bloque va debajo del usuario y arriba de «Management»", True,
          -1 not in order and order == sorted(order))
_, _, page = req("GET", "/?lang=en-US", cookie=cookie)
side = menu(page)
check("el nombre del agente va escapado", True, "<b>Iris &lt;Agente&gt;</b>" in side)
check("debajo del nombre, el harness y el estado (Q293)", True,
      '<span class="agente-chip">Claude Code</span><span class="agente-chip agente-ok"><i aria-hidden="true"></i>Online</span>' in side)
check("el ícono de robot en el lugar del de Perfil", True, 'class="perfil agente-icono"' in side)
check("fuera de /agent el bloque no está activo", False, 'agente-usuario activo' in side)
check("no hay entrada «AI Agent» en Management (Q298)", 1, side.count('href="/agent"'))

status, _, page = req("GET", "/agent?lang=en-US", cookie=cookie)
check("/agent: 200 con el título «AI Agent»", (200, True), (status, "<h1>AI Agent</h1>" in page))
check("en /agent el bloque queda marcado", True,
      bool(re.search(r'<a class="usuario agente-usuario activo" href="/agent" aria-current="page"', page)))
check("el encabezado: estado, desde cuándo vigila y la próxima renovación", (True, True, True),
      ('salud salud-ok' in page, "Watching the mail since 08:46" in page, "next at 09:16" in page))
check("las cuatro cifras: 4 atendidos, 1 en cola, 08:40 y 2 min", (True, True, True, True),
      ('data-dash="agent.handled">4<' in page, 'data-dash="agent.waiting">1<' in page,
       'data-dash="agent.last">08:40<' in page, 'data-dash="agent.median">2 min<' in page))
check("las secciones (Q296), con «Channels» (Julian)", (True, True, True, True),
      (">The agent</h3>" in page, ">Channels</h3>" in page, ">What the agent did today</h3>" in page,
       ">If the status changes</h3>" in page))
check("Channels: correo con el roster y Telegram con su bot", (True, True),
      ("iris@example.com · 5 contacts in the roster" in page, "@NegocioBot" in page))
check("sin atributos style", [], re.findall(r'\sstyle="', page))

SOURCE["fake"] = dashboard.Fake(services=services(live=False),
                                agent={"name": "Iris", "email": "iris@example.com", "runtime": "claudecode"})
_, _, page = req("GET", "/agent?lang=en-US", cookie=cookie)
check("sin sesión: ámbar «No session» en el bloque y en la página", (True, True, True),
      ('agente-chip agente-warn' in menu(page), 'salud salud-warn' in page, "Not armed" in page))
SOURCE["fake"] = dashboard.Fake(services=services(dispatcher="inactive"),
                                agent={"name": "Iris", "email": "iris@example.com", "runtime": "openclaw"})
_, _, page = req("GET", "/agent?lang=en-US", cookie=cookie)
check("despachador detenido: rojo «Offline»", (True, True), ('agente-chip agente-bad' in menu(page), 'salud salud-bad' in page))
check("OpenClaw no tiene vigilancia: «Always on»", True, "OpenClaw listens all the time; it has no watch" in page)


class Broken(dashboard.Fake):
    def agent(self):
        raise RuntimeError("roto")


SOURCE["fake"] = Broken()
status, _, page = req("GET", "/?lang=en-US", cookie=cookie)
check("si leer el agente falla, la página sale sin el bloque", (200, False), (status, "agente-usuario" in page))

SOURCE["fake"] = fake
for lang in agent_strings.STRINGS:
    status, _, page = req("GET", f"/agent?lang={lang}", cookie=cookie)
    check(f"{lang}: sin claves sin traducir", (200, []), (status, re.findall(r"web\.(?:agent|dash)\.[a-z_.]+", page)))
i18n.set_current("es-MX")

httpd.shutdown()
check("el .env y Himalaya de la instalación no cambiaron", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
