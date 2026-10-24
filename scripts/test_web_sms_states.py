#!/usr/bin/env python3
"""
Tests for the SMS statuses in PaynaniWeb (T4 #507 of PRD #489: FR-5, FR-7). An
assertion script, like the rest of this suite.

Un PaynaniWeb real en un puerto libre, con el estado de la pasarela en una carpeta
temporal. Los estados se escriben en orders.jsonl como lo hace la pasarela; nada
sale de la máquina.
"""
from __future__ import annotations

import http.client
import json
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.sms import outgoing  # noqa: E402
from paynani_lib.sms import store as sms_store  # noqa: E402
from paynani_lib.sms.gateway import status_id  # noqa: E402
from paynani_lib.web import app, auth, messages_pages, notify, strings, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ANA = "+525511112222"
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
roster = tmp / "roster.md"
roster.write_text(f"""# roster

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human |  | {ANA} |
""", encoding="utf-8")
st = sms_store.Store(state)
st.save_device({"device_id": "d_1", "sims": [{"slot": 0, "country": "MX"}], "accepts_owner_out": True,
                "connected": False, "last_seen": "2026-01-01T00:00:00Z"})
PASSWORD = "una-contraseña-larga"
user_file = tmp / "web" / "user.json"
users.create("dueno@example.com", "Dueño", PASSWORD, user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "no-accounts.json",
                  state_dir=state, roster_path=roster)
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


_, hdrs, _ = req("POST", "/login", form={"email": "dueno@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
th = i18n.th
t = i18n.t
VER = f"/messages/ver?n={quote(ANA, safe='')}"
ESTADOS = f"/messages/estados?n={quote(ANA, safe='')}"


def estados():
    status, hdrs, body = req("GET", ESTADOS, cookie=cookie)
    return status, hdrs, (json.loads(body) if status == 200 else body)


def mark(oid, status, **extra):
    st.append_status({"id": status_id(oid, status), "order_id": oid, "status": status,
                      "at": sms_store.now_utc(), **extra})


def order(text, **kw):
    return outgoing.queue(st, to=ANA, text=text, origin="owner", source="203.0.113.5", region="MX", **kw)


# --- FR-7: teléfono desconectado ----------------------------------------------------
first = order("Hola Ana")
status, _, page = req("GET", VER, cookie=cookie)
check("desconectado: la conversación lo dice, con los 15 minutos", True,
      th("web.sms.offline", min=outgoing.DEFAULT_TTL_MIN) in page and 'id="sms-offline"' in page)
check("desconectado: el mensaje de la web queda «en cola»", True,
      f'data-sms-id="{first["id"]}"' in page and f'>{t("web.sms.status.queued")}</span>' in page)
status, hdrs, data = estados()
check("estados: JSON sin caché, con offline y el conteo", (200, "no-store", True, 1),
      (status, hdrs.get("cache-control"), data["offline"], data["count"]))
check("estados: el mensaje con su estado y su etiqueta", [{"id": first["id"], "status": "queued",
                                                          "label": t("web.sms.status.queued")}], data["items"])

# Vence a los 15 minutos aunque la pasarela no lo haya marcado (sólo vence con el teléfono conectado).
path = st.root / "outbox" / f"{first['id']}.json"
saved = json.loads(path.read_text())
saved["expires_at"] = "2020-01-01T00:00:00Z"
path.write_text(json.dumps(saved))
_, _, data = estados()
check("FR-7: pasada su hora sin salir, «vencido»", "expired", data["items"][0]["status"])
status, _, page = req("GET", VER, cookie=cookie)
check("FR-7: la conversación también dice vencido", True, f'>{t("web.sms.status.expired")}</span>' in page)

# --- Conectado: sin aviso ---------------------------------------------------------
st.touch(connected=True, last_seen=sms_store.now_utc())
status, _, page = req("GET", VER, cookie=cookie)
check("conectado: sin el aviso de desconectado", False, 'id="sms-offline"' in page)
_, _, data = estados()
check("conectado: estados dice offline false", False, data["offline"])

# --- FR-5: cada estado ---------------------------------------------------------------
second = order("¿Confirmas mañana?")
_, _, data = estados()
check("un mensaje nuevo sube el conteo (sms.js recarga)", 2, data["count"])
by_id = lambda d, oid: next(i for i in d["items"] if i["id"] == oid)  # noqa: E731
for status in ("accepted", "sent", "delivered"):
    mark(second["id"], status)
    _, _, data = estados()
    check(f"FR-5: {status}", (status, t(f"web.sms.status.{status}")),
          (by_id(data, second["id"])["status"], by_id(data, second["id"])["label"]))

third = order("Uno que falla")
mark(third["id"], "failed", error="RESULT_ERROR_NO_SERVICE")
_, _, data = estados()
check("FR-5: falló con el código", ("failed", f'{t("web.sms.status.failed")} (RESULT_ERROR_NO_SERVICE)'),
      (by_id(data, third["id"])["status"], by_id(data, third["id"])["label"]))
fourth = order("Uno rechazado")
mark(fourth["id"], "rejected", error="not_allowed")
_, _, data = estados()
check("FR-5: rechazado con la razón", f'{t("web.sms.status.rejected")} (not_allowed)',
      by_id(data, fourth["id"])["label"])
status, _, page = req("GET", VER, cookie=cookie)
check("la conversación muestra el código y la razón", True,
      "(RESULT_ERROR_NO_SERVICE)" in page and "(not_allowed)" in page)
check("cada mensaje de la web dice «desde PaynaniWeb»", 4, page.count(th("web.sms.by_owner_web")))

# El código viene del teléfono: se escapa.
fifth = order("Uno raro")
mark(fifth["id"], "failed", error='<img src=x onerror=alert(1)>')
status, _, page = req("GET", VER, cookie=cookie)
check("un código con HTML sale escapado", (False, True), ("<img src=x" in page, "&lt;img src=x" in page))

# Lo del agente no lleva data-sms-id: sms.js sólo toca lo de la web.
agent = outgoing.queue(st, to=ANA, text="Del agente", origin="agent")
status, _, page = req("GET", VER, cookie=cookie)
check("lo del agente no lleva data-sms-id", False, f'data-sms-id="{agent["id"]}"' in page)
_, _, data = estados()
check("estados sólo trae órdenes w_", True, all(i["id"].startswith("w_") for i in data["items"]))

# --- El script -------------------------------------------------------------------------
check("la conversación trae el gancho de sms.js con su URL y su conteo", True,
      re.search(r'<div hidden id="sms-watch" data-url="/messages/estados\?n=%2B525511112222" data-count="\d+">',
                page) is not None and "/assets/sms.js" in page)
status, _, js = req("GET", "/assets/sms.js")
check("sms.js pregunta los estados y recarga con lo nuevo", (200, True, True),
      (status, "sms-watch" in js, "location.reload" in js))

# --- Sin sesión, nada ---------------------------------------------------------------
status, hdrs, body = req("GET", ESTADOS)
check("estados sin sesión: no da los datos", (True, False), (status in (302, 303, 401), "items" in body))
status, _, data = estados()
check("estados de un número sin nada: vacío", (200, 0, []),
      (status, *(lambda d: (d["count"], d["items"]))(json.loads(req("GET", "/messages/estados?n=%2B1999", cookie=cookie)[2]))))

# --- FR-10 -----------------------------------------------------------------------------
missing = [lang for lang in strings.STRINGS if "web.sms.offline" not in strings.STRINGS[lang]]
check("FR-10: el aviso de desconectado en los cinco idiomas", [], missing)
check("status_label sin código no agrega paréntesis", t("web.sms.status.failed"), messages_pages.status_label("failed"))

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
