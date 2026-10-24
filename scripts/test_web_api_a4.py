#!/usr/bin/env python3
"""
Tests for SendSms and GetSmsStatus (A4 #496 of PRD #491: FR-6 to FR-10). An
assertion script, like the rest of this suite.

Un PaynaniWeb real en un puerto libre, con el estado de la pasarela en una carpeta
temporal. SendSms sólo deja la orden en outbox/ (la pasarela la manda después):
nada sale de la máquina.
"""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import outgoing  # noqa: E402
from paynani_lib.sms import store as sms_store  # noqa: E402
from paynani_lib.sms.gateway import status_id  # noqa: E402
from paynani_lib.web import api_tokens, app, notify, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


CLIENTE = "+525588887777"
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
roster = tmp / "roster.md"
roster.write_text("# roster\n\n# 1. Approved contacts\n\n| Name | Email | Type | GitHub | Phone |\n"
                  "|---|---|---|---|---|\n| Ana | ana@example.com | Human |  | +525511112222 |\n", encoding="utf-8")
user_file = tmp / "web" / "user.json"
users.create("dueno@example.com", "Dueño", "una-contraseña-larga", user_file)
owner_mail = []
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: owner_mail.append(a), log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "no-accounts.json",
                  state_dir=state, roster_path=roster)
st = sms_store.Store(state)
store_path = api_tokens.path_for(user_file)


def token(name, permissions=("sms.send",), limits=None):
    secret, record = api_tokens.create(name, permissions=list(permissions), limits=limits, path=store_path)
    return secret, record


sender, sender_rec = token("citas")
other, _ = token("citas")              # mismo nombre, otro token
reader, _ = token("lector", permissions=("read",))
tiny, tiny_rec = token("tope", limits={"sms_per_hour": 2, "sms_per_day": 3})

httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def api(secret, action, **params):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", "/api/agent", body=json.dumps({"action": action, **params}),
                 headers={"Host": "agente.ngrok.app", "X-Forwarded-For": "203.0.113.9",
                          "Authorization": "Bearer " + secret, "Content-Type": "application/json"})
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


def outbox():
    return sorted(p.name for p in (st.root / "outbox").glob("a_*.json")) if (st.root / "outbox").exists() else []


# --- Permiso y FR-10: sin teléfono, app vieja -------------------------------------------
status, body = api(reader, "SendSms", to=CLIENTE, text="hola", idempotency_key="k1")
check("sin sms.send: 403 forbidden", (403, "forbidden", "sms.send"), (status, body["code"], body.get("permission")))
status, body = api(sender, "SendSms", to=CLIENTE, text="hola", idempotency_key="k1")
check("FR-10: sin teléfono emparejado, no_phone", (409, "no_phone", []), (status, body["code"], outbox()))
st.save_device({"device_id": "d_1", "sims": [{"slot": 0, "country": "MX"}], "accepts_owner_out": True,
                "connected": False, "last_seen": "2026-01-01T00:00:00Z"})
status, body = api(sender, "SendSms", to=CLIENTE, text="hola", idempotency_key="k1")
check("FR-10: app sin accepts_api_out, app_outdated", (409, "app_outdated", []), (status, body["code"], outbox()))
st.touch(accepts_api_out=True)

# --- FR-7: idempotency_key obligatoria y válida ---------------------------------------
status, body = api(sender, "SendSms", to=CLIENTE, text="hola")
check("sin idempotency_key: missing_parameter", (400, "missing_parameter", "idempotency_key"),
      (status, body["code"], body.get("field")))
for bad in ("con espacio", "x" * 129, "ñ"):
    status, body = api(sender, "SendSms", to=CLIENTE, text="hola", idempotency_key=bad)
    check(f"idempotency_key inválida {bad[:12]!r}: invalid_parameter", (400, "invalid_parameter"), (status, body["code"]))

# --- FR-6: envío a un número fuera del roster, con la región del teléfono ----------------
status, body = api(sender, "SendSms", to="55 8888 7777", text="Su cita es mañana", idempotency_key="cita-1")
order = body.get("order", {})
check("FR-6: success, orden a_ con el número en E.164", (200, True, CLIENTE, "queued"),
      (status, order.get("id", "").startswith("a_"), order.get("to"), order.get("status")))
check("FR-10: teléfono desconectado: phone_online false y el aviso de los 15 minutos", (False, True),
      (body["phone_online"], "15 minutes" in body.get("notice", "")))
check("no es duplicado", False, body["duplicate"])
saved = json.loads((st.root / "outbox" / f"{order['id']}.json").read_text())
check("la orden lleva origin api y el nombre del token", ("api", "citas"), (saved.get("origin"), saved.get("token")))
queued = [json.loads(l) for l in (st.root / "orders.jsonl").read_text().splitlines()][-1]
check("orders.jsonl: token_id, la llave, el hash y la dirección", (sender_rec["prefix"], "cita-1", True, "203.0.113.9"),
      (queued.get("token_id"), queued.get("idempotency_key"), len(queued.get("content_sha256", "")) == 64,
       queued.get("source")))
first_id = order["id"]

# --- FR-7: la misma llave ------------------------------------------------------------------
status, body = api(sender, "SendSms", to=CLIENTE, text="Su cita es mañana", idempotency_key="cita-1")
check("FR-7: misma llave y contenido: la misma orden, duplicate true, sin otra orden",
      (200, first_id, True, 1), (status, body["order"]["id"], body["duplicate"], len(outbox())))
status, body = api(sender, "SendSms", to=CLIENTE, text="Otro texto", idempotency_key="cita-1")
check("FR-7: misma llave y otro texto: 409 idempotency_conflict con la orden", (409, "idempotency_conflict", first_id),
      (status, body["code"], body.get("order_id")))
status, body = api(sender, "SendSms", to="+525500001111", text="Su cita es mañana", idempotency_key="cita-1")
check("FR-7: misma llave y otro número: idempotency_conflict", (409, "idempotency_conflict"), (status, body["code"]))
status, body = api(other, "SendSms", to=CLIENTE, text="Su cita es mañana", idempotency_key="cita-1")
check("otro token con la misma llave (y el mismo nombre): orden nueva", (200, False, 2),
      (status, body["duplicate"], len(outbox())))
other_id = body["order"]["id"]

# --- FR-8: baja y pausa ----------------------------------------------------------------
(st.root / "optout.json").write_text(json.dumps({"numbers": {"+525511110000": {"at": "2026-10-24T10:00:00Z"}}}))
status, body = api(sender, "SendSms", to="+525511110000", text="hola", idempotency_key="b-1")
check("FR-8: número dado de baja: 403 opted_out y nada en outbox", (403, "opted_out", 2),
      (status, body["code"], len(outbox())))
st.append_human({"id": "h1", "local_id": "h_" + "1" * 32, "to": "+525522223333", "status": "sent",
                 "at": sms_store.now_utc(), "agent_pause_min": 30, "pause_until": "2099-01-01T00:00:00Z"})
status, body = api(sender, "SendSms", to="+525522223333", text="hola", idempotency_key="p-1")
check("FR-8: el dueño acaba de contestar: 409 human_replied con hasta cuándo", (409, "human_replied", "2099-01-01T00:00:00Z"),
      (status, body["code"], body.get("until")))
# El reintento de una orden que sí salió no cambia por una baja posterior.
(st.root / "optout.json").write_text(json.dumps({"numbers": {CLIENTE: {"at": "2026-10-24T10:00:00Z"}}}))
status, body = api(sender, "SendSms", to=CLIENTE, text="Su cita es mañana", idempotency_key="cita-1")
check("FR-7 antes que FR-8: la llave repetida devuelve su orden aunque el número ya esté de baja",
      (200, first_id, True), (status, body["order"]["id"], body["duplicate"]))
(st.root / "optout.json").unlink()

# Revisión de #522: el reintento con la misma llave no depende del estado del teléfono.
device_saved = st.device()
st.touch(accepts_api_out=False)
status, body = api(sender, "SendSms", to=CLIENTE, text="Su cita es mañana", idempotency_key="cita-1")
check("FR-7: la app dejó de anunciar accepts_api_out: el reintento devuelve su orden, no app_outdated",
      (200, first_id, True), (status, body.get("order", {}).get("id"), body.get("duplicate")))
st.revoke()
status, body = api(sender, "SendSms", to=CLIENTE, text="Su cita es mañana", idempotency_key="cita-1")
check("FR-7: sin teléfono emparejado: el reintento devuelve su orden, no no_phone",
      (200, first_id, True), (status, body.get("order", {}).get("id"), body.get("duplicate")))
status, body = api(sender, "SendSms", to=CLIENTE, text="Una nueva", idempotency_key="nueva-sin-tel")
check("…pero una llave nueva sin teléfono sigue siendo no_phone", (409, "no_phone"), (status, body["code"]))
st.save_device(device_saved)

# --- Validaciones del texto y del número ---------------------------------------------------
status, body = api(sender, "SendSms", to="hola", text="x", idempotency_key="v-1")
check("número ilegible: 400 invalid_number", (400, "invalid_number", "to"), (status, body["code"], body.get("field")))
status, body = api(sender, "SendSms", to=CLIENTE, text="  ", idempotency_key="v-2")
check("texto vacío: 400 empty_text", (400, "empty_text"), (status, body["code"]))
status, body = api(sender, "SendSms", to=CLIENTE, text="x" * 1001, idempotency_key="v-3")
check("más de 1000: 400 text_too_long", (400, "text_too_long"), (status, body["code"]))

# --- FR-9: topes por token --------------------------------------------------------------
codes = [api(tiny, "SendSms", to=CLIENTE, text=f"t{i}", idempotency_key=f"t-{i}")[1].get("code", "ok") for i in range(3)]
check("FR-9: tope de 2 por hora: el tercero quota_exceeded", ["ok", "ok", "quota_exceeded"], codes)
status, body = api(tiny, "SendSms", to=CLIENTE, text="t9", idempotency_key="t-9")
check("quota_exceeded: 429 con retry_at", (429, True), (status, bool(body.get("retry_at"))))
daily, daily_rec = token("daycap", limits={"sms_per_hour": 2, "sms_per_day": 1})
check("A7: el primer SMS alcanza el tope diario", 200,
      api(daily, "SendSms", to=CLIENTE, text="one", idempotency_key="day-1")[0])
check("A7: reintentar la llave no envía otro SMS", 200,
      api(daily, "SendSms", to=CLIENTE, text="one", idempotency_key="day-1")[0])
check("A7: el siguiente SMS rebasa el tope diario", "quota_exceeded",
      api(daily, "SendSms", to=CLIENTE, text="two", idempotency_key="day-2")[1]["code"])
ctx.notifier.wait()
daily_mail = [m for m in owner_mail if "tope diario" in m[1]]
check("A7: un solo correo al dueño por el tope diario", (1, True),
      (len(daily_mail), "one" not in daily_mail[0][2] if daily_mail else False))
# Por día: tres órdenes de hace 2 horas cuentan para el día y no para la hora.
day = sms_store.Store(Path(tempfile.mkdtemp()) / "s")
for i in range(3):
    outgoing.queue(day, to=CLIENTE, text=f"d{i}", origin="api", token="x", token_id="pn_dia", source="t",
                   now=outgoing.time.time() - 7200)
try:
    outgoing.queue(day, to=CLIENTE, text="d3", origin="api", token="x", token_id="pn_dia", source="t",
                   per_hour=30, per_day=3)
    code = "queued"
except outgoing.Refused as exc:
    code = exc.code
check("FR-9: tope de 3 por día con 3 de hace 2 horas: quota_exceeded", "quota_exceeded", code)
status, body = api(sender, "SendSms", to=CLIENTE, text="otro del token citas", idempotency_key="c-2")
check("los topes son por token: citas sigue enviando", 200, status)

# --- GetSmsStatus -----------------------------------------------------------------------
status, body = api(sender, "GetSmsStatus", order_id=first_id)
check("GetSmsStatus: en cola, con la historia", (200, "queued", ["queued"]),
      (status, body["order"]["status"], [h["status"] for h in body["order"]["history"]]))
for s, extra in (("accepted", {}), ("sent", {}), ("failed", {"error": "RESULT_ERROR_NO_SERVICE"})):
    st.append_status({"id": status_id(first_id, s), "order_id": first_id, "status": s,
                      "at": sms_store.now_utc(), **extra})
status, body = api(sender, "GetSmsStatus", order_id=first_id)
check("GetSmsStatus: último estado failed con su código", ("failed", "RESULT_ERROR_NO_SERVICE", 4),
      (body["order"]["status"], body["order"].get("error"), len(body["order"]["history"])))
status, body = api(sender, "GetSmsStatus", order_id=other_id)
check("GetSmsStatus de la orden de otro token: 404 not_found", (404, "not_found"), (status, body["code"]))
status, body = api(sender, "GetSmsStatus", order_id="a_" + "0" * 32)
check("GetSmsStatus de una orden que no existe: 404", (404, "not_found"), (status, body["code"]))
status, body = api(sender, "GetSmsStatus", order_id="w_" + "0" * 32)
check("GetSmsStatus de una orden w_: invalid_parameter", (400, "invalid_parameter"), (status, body["code"]))
path = st.root / "outbox" / f"{other_id}.json"
saved = json.loads(path.read_text())
saved["expires_at"] = "2020-01-01T00:00:00Z"
path.write_text(json.dumps(saved))
status, body = api(other, "GetSmsStatus", order_id=other_id)
check("GetSmsStatus: en cola pasada su hora, expired", "expired", body["order"]["status"])
status, body = api(reader, "GetSmsStatus", order_id=first_id)
check("GetSmsStatus sin sms.send: forbidden", (403, "forbidden"), (status, body["code"]))

# --- Conectado: sin aviso ------------------------------------------------------------------
st.touch(connected=True, last_seen=sms_store.now_utc())
status, body = api(sender, "SendSms", to=CLIENTE, text="conectado", idempotency_key="on-1")
check("conectado: phone_online true y sin notice", (True, False), (body["phone_online"], "notice" in body))

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
