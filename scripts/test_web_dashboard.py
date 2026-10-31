#!/usr/bin/env python3
"""
Tests del Dashboard de la página inicial (PRD #602): el modelo de `dashboard.build()`
con un `Fake` y una hora fija (el color del estado general, los conteos de hoy y de 7
días en la zona del host, el selector de cuenta, lo que necesita atención y la
actividad sin cuerpos ni textos), y la página y `/dashboard.json` en un PaynaniWeb real
en un puerto libre.

Nada aquí lee ni escribe la configuración real: todo va con `dashboard.Fake` y un
`state/` temporal, y al final se comprueba que el sha256 del `.env` y de la
configuración de Himalaya de la instalación no cambiaron.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import guard, i18n  # noqa: E402
from paynani_lib.web import app, auth, dashboard, dashboard_pages, dashboard_strings, notify, users  # noqa: E402

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
NOW = dt.datetime(2026, 10, 30, 23, 30, tzinfo=CST)          # 2026-10-31 05:30 UTC


def utc(local: str) -> str:
    """Una hora local de CST como la escribe el ledger, en UTC con Z."""
    value = dt.datetime.fromisoformat(local).replace(tzinfo=CST).astimezone(dt.timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def row(event_id, local, state, roster=True, who="Metis", subject="Hola"):
    return {"event_id": event_id, "observed_at": utc(local), "state": state, "roster": roster,
            "sender_name": who, "sender_address": f"{who.lower()}@example.com", "subject": subject}


ACCOUNTS = [{"id": "main", "email": "agente@example.com", "enabled": True, "agent": True},
            {"id": "ventas", "email": "ventas@example.com", "enabled": True, "agent": False}]
MAIL = {
    "main": [
        row("imap:INBOX:1:1", "2026-10-30T09:00:00", "handled"),
        row("imap:INBOX:1:2", "2026-10-30T10:00:00", "replied"),
        row("imap:INBOX:1:3", "2026-10-30T23:10:00", "dispatched", who="Ximena", subject="Revisión"),
        # 23:59 local del 29 = 05:59 UTC del 30: es de ayer en CST aunque en UTC sea hoy.
        row("imap:INBOX:1:4", "2026-10-29T23:59:00", "closed"),
        # 00:01 local del 30 = 06:01 UTC: de hoy.
        row("imap:INBOX:1:5", "2026-10-30T00:01:00", "closed"),
        # Fuera del roster y abierto: no es un aviso.
        row("imap:INBOX:1:6", "2026-10-30T11:00:00", "dispatched", roster=False, who="Spam"),
        # De hace 9 días: fuera de los 7.
        row("imap:INBOX:1:7", "2026-10-21T12:00:00", "handled"),
    ],
    "ventas": [row("ventas:imap:INBOX:2:1", "2026-10-30T12:00:00", "observed", who="Cliente", subject="Cotización")],
}
SMS_TEXT = "texto-secreto-del-sms"
SMS = [
    {"epoch": dt.datetime(2026, 10, 30, 22, 41, tzinfo=CST).timestamp(), "kind": "received", "status": "",
     "name": "Julián", "number": "+5215512345678"},
    {"epoch": dt.datetime(2026, 10, 30, 22, 45, tzinfo=CST).timestamp(), "kind": "human", "status": "failed",
     "name": "", "number": "+5215512345678"},
    {"epoch": dt.datetime(2026, 10, 29, 8, 0, tzinfo=CST).timestamp(), "kind": "agent", "status": "delivered",
     "name": "", "number": "+5215599999999"},
]


def fake(**over):
    data = dict(accounts=ACCOUNTS, mail=MAIL,
                sent={"main": [{"at": utc("2026-10-30T23:20:00"), "to": "metis@example.com", "subject": "Re: Hola",
                                "message_id": "<a@b>"}]},
                sms=SMS, roster={"count": 12, "changes": [{"at": utc("2026-10-30T18:12:00"), "action": "add",
                                                          "name": "Atenea", "device_id": "web:1.2.3.4"}]},
                tokens=[{"name": "Plantako", "expires_at": "2026-11-04T00:00:00Z", "revoked_at": None},
                        {"name": "Viejo", "expires_at": "2026-11-02T00:00:00Z", "revoked_at": "2026-10-01T00:00:00Z"},
                        {"name": "Lejos", "expires_at": "2027-01-01T00:00:00Z", "revoked_at": None}],
                version={"installed": "0.17.1", "latest": "0.18.0", "checked_at": ""},
                whatsapp={"status": {"state": "connected"},
                          "received": [{"at": utc("2026-10-30T22:30:00"), "name": "", "number": "+5215511112222"}]})
    data.update(over)
    return dashboard.Fake(**data)


i18n.set_current("es-MX")

# ---- El modelo -------------------------------------------------------------------
m = dashboard.build(fake(), NOW)
check("FR-8: correo de hoy, todas las cuentas, en CST (no cuenta las 23:59 del 29)",
      {"received": 6, "handled": 2, "replied": 1, "open": 3}, m["mail_today"])
check("FR-8: avisos abiertos sólo del roster (no el de fuera del roster)", 2, m["open_notices"])
check("y el más viejo primero", "Cliente", m["oldest_notice"]["who"])
check("FR-8: SMS de hoy", {"in": 1, "out": 1, "failed": 1}, m["sms_today"])
check("FR-8: roster y su último cambio", (12, "18:12"), (m["roster_count"], m["roster_last_change"].strftime("%H:%M")))
week = {w["day"].isoformat(): (w["closed"], w["open"]) for w in m["week"]}
check("FR-14: 7 días que terminan hoy", ["2026-10-24", "2026-10-30"], [min(week), max(week)])
check("FR-14: el 29 cuenta el correo de las 23:59 local", (1, 0), week["2026-10-29"])
check("FR-14: hoy, cerrados y abiertos (de todas las cuentas)", (3, 3), week["2026-10-30"])
check("FR-14: lo de hace 9 días no entra", 7, m["week_received"])
check("FR-7: la zona del host", "CST (UTC−06:00)", m["zone"])

m1 = dashboard.build(fake(), NOW, "ventas")
check("FR-9: con una cuenta, sólo esa", ({"received": 1, "handled": 0, "replied": 0, "open": 1}, 1),
      (m1["mail_today"], m1["open_notices"]))
m2 = dashboard.build(fake(), NOW, "no-existe")
check("FR-9: una cuenta que no existe cuenta como todas y lo dice", (True, "", 6),
      (m2["account_unknown"], m2["account"], m2["mail_today"]["received"]))

check("FR-5: todo ok → verde", "ok", dashboard.overall([{"status": "ok"}]))
check("FR-5: un warning → amarillo", "warning", dashboard.overall([{"status": "ok"}, {"status": "warning"}]))
check("FR-5: un unknown → amarillo", "warning", dashboard.overall([{"status": "unknown"}]))
check("FR-5: un blocked → rojo", "blocked", dashboard.overall([{"status": "warning"}, {"status": "blocked"}]))

kinds = [a["kind"] for a in m["attention"]]
check("FR-12: avisos, SMS fallido, token por vencer y versión nueva, en orden",
      ["notices", "sms_failed", "token", "version"], kinds)
check("FR-12: el token revocado y el lejano no entran", ["Plantako"], [a["name"] for a in m["attention"] if a["kind"] == "token"])
bad = dashboard.build(fake(health={"checks": [{"name": "listener", "status": "blocked", "summary": "listener is failed"},
                                              {"name": "queue", "status": "ok", "summary": ""}], "network_at": ""},
                           services=dict(fake().data["services"], additional=[
                               {"id": "ventas", "email": "ventas@example.com", "enabled": True, "unit": "failed"}])), NOW)
check("FR-12: una revisión que no está en ok va primero, y la cuenta caída después",
      ["check", "account"], [a["kind"] for a in bad["attention"]][:2])
check("FR-5: y el estado general es rojo", ("blocked", 1, 2), (bad["status"], bad["checks_ok"], bad["checks_total"]))
calm = dashboard.build(fake(mail={}, sms=[], tokens=[], version={"installed": "1.0.0", "latest": "1.0.0"}), NOW)
check("FR-13: sin nada pendiente, la lista está vacía", [], calm["attention"])

check("FR-16: la actividad, 10 como máximo y la más reciente primero",
      (10, "sent"), (len(m["activity"]), m["activity"][0]["channel"]))
every = {a["channel"] for a in dashboard.build(fake(mail={}), NOW)["activity"]}
check("FR-16: enviado, SMS, WhatsApp y roster entran", {"sent", "sms", "whatsapp", "roster"}, every)
nowa = dashboard.build(fake(whatsapp=None), NOW)
check("FR-10: sin WhatsApp configurado no hay fila", None, nowa["whatsapp"])

nums = dashboard.numbers(m)
blob = json.dumps(nums, ensure_ascii=False)
check("FR-19: el JSON no trae direcciones, teléfonos, asuntos ni nombres",
      [], [x for x in ("@", "+52", "Hola", "Revisión", "Metis", "Plantako", SMS_TEXT) if x in blob])
check("FR-19: pero sí los números", (6, 2, "ok"), (nums["mail_today"]["received"], nums["open_notices"], nums["status"]))

# ---- La página -------------------------------------------------------------------
html = dashboard_pages.body(m, "Julián Flores")
check("el saludo con la hora del host", True, "Buenas noches, Julián." in html)
check("FR-17: ningún texto de SMS en el HTML", False, SMS_TEXT in html)
check("FR-15: la gráfica con role=img y su tabla", (True, True), ('role="img"' in html, 'class="solo-lector"' in html))
check("sin atributos style", [], re.findall(r'\sstyle="', html))
check("el script, con defer", True, '<script src="/assets/dashboard.js" defer></script>' in html)
check("FR-9: el selector con dos cuentas", True, 'name="cuenta"' in html)
check("FR-12: el enlace para renovar el token", True, 'href="/api-tokens"' in html)
one = dashboard_pages.body(dashboard.build(fake(accounts=ACCOUNTS[:1]), NOW), "J")
check("FR-9: con una sola cuenta no hay selector", False, 'name="cuenta"' in one)
check("FR-13: «Nada pendiente»", True, i18n.th("web.dash.attention.none") in dashboard_pages.body(calm, "J"))

for lang in dashboard_strings.STRINGS:
    i18n.set_current(lang)
    page = dashboard_pages.body(m, "J")
    check(f"FR-4: {lang} sin claves sin traducir", [], re.findall(r"web\.dash\.[a-z_.]+", page))
i18n.set_current("es-MX")

# ---- PaynaniWeb ------------------------------------------------------------------
PASSWORD = "una-contraseña-larga"
tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
user_file = tmp / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
source = fake()
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda l: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", state_dir=tmp / "state",
                  roster_path=tmp / "roster.md", dashboard_source=source, now=lambda: NOW)
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


status, hdrs, _ = req("GET", "/dashboard.json")
check("FR-19: /dashboard.json sin sesión va a la entrada", (303, True), (status, hdrs.get("location", "").startswith("/login")))
_, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]

status, hdrs, page = req("GET", "/?lang=es-MX", cookie=cookie)
check("FR-1: / es el Dashboard", (200, True, True), (status, 'class="dash"' in page, "Necesita tu atención" in page))
check("FR-1: con el título «Inicio»", True, "<h1>Inicio</h1>" in page)
check("no-store", True, "no-store" in hdrs.get("cache-control", ""))
check("la CSP no cambió", guard.CSP + "; connect-src 'self'", hdrs.get("content-security-policy"))
check("sin atributos style", [], re.findall(r'\sstyle="', page))
status, hdrs, page = req("GET", "/?cuenta=ventas", cookie=cookie)
check("FR-9: ?cuenta=ventas", (200, True), (status, 'data-dash-src="/dashboard.json?cuenta=ventas"' in page))
status, _, page = req("GET", "/?cuenta=%3Cx%3E", cookie=cookie)
check("FR-9: una cuenta rara no se pinta", (200, False), (status, "<x>" in page))

status, hdrs, body = req("GET", "/dashboard.json", cookie=cookie)
data = json.loads(body)
check("FR-18: /dashboard.json con sesión", (200, "application/json; charset=UTF-8", 6),
      (status, hdrs.get("content-type"), data["mail_today"]["received"]))
check("FR-19: no-store en el JSON", True, "no-store" in hdrs.get("cache-control", ""))
check("FR-19: sin datos personales", [], [x for x in ("@", "+52", "Hola", "Metis") if x in body])
status, hdrs, js = req("GET", "/assets/dashboard.js")
check("/assets/dashboard.js se sirve como JavaScript", (200, True, True),
      (status, hdrs.get("content-type", "").startswith("application/javascript"), "data-dash-src" in js))
check("FR-20: leer el Dashboard no escribe en state/", [], sorted(p.name for p in (tmp / "state").iterdir()
                                                                if p.name not in ("api_security",)))

httpd.shutdown()
check("la configuración real no cambió (.env y Himalaya)", BEFORE, [sha(p) for p in REAL])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
