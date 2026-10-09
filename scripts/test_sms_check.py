#!/usr/bin/env python3
"""
Tests for `paynani sms check` (#350, punto 4): the guided check after pairing.
An assertion script, like the rest of this suite.

Nada de red ni de teléfono: la respuesta de /sms/health, el estado del servicio,
el teléfono y `sms send` se pasan como dobles.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import check as sms_check  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


tmp = Path(tempfile.mkdtemp())
os.environ["PAYNANI_STATE"] = str(tmp / "state")
(tmp / "state").mkdir()
os.environ["PAYNANI_SMS_PORT"] = "8770"
os.environ["PAYNANI_SMS_PUBLIC_URL"] = "https://agente.ngrok.app"

ACTIVE = {"unit": "active", "name": "paynani-sms.service"}
PHONE = {"device_id": "d_abc123", "model": "Pixel 6", "app_version": "0.6.3", "online": True,
         "last_seen_age_s": 7, "orders_queued": 0, "offline_notified": False,
         "sims": [{"slot": 0, "number": "+525512345678", "country": "MX"}]}


def answers(*urls_ok):
    def fetch(base):
        return ({"ok": True, "phone_connected": True}, None) if base in urls_ok else (None, "connection refused")
    return fetch


ALL_OK = answers("http://127.0.0.1:8770", "https://agente.ngrok.app")


def run(to="", wait_reply=0, gateway=ACTIVE, phone=PHONE, fetch=ALL_OK, send=None):
    out = io.StringIO()
    code = sms_check.run(SimpleNamespace(to=to, wait=5, wait_reply=wait_reply), out=out,
                         gateway_facts=gateway, phone_facts=dict(phone) if phone else phone, fetch=fetch, send=send)
    return code, out.getvalue()


# --- sin --to ---------------------------------------------------------------------------
code, text = run()
check("todo bien: sale con 0", 0, code)
check("todo bien: servicio, pasarela local, túnel, teléfono y número", True,
      all(s in text for s in ("ok    gateway service: paynani-sms.service active",
                              "ok    gateway on this machine: answers on port 8770",
                              "ok    tunnel: https://agente.ngrok.app reaches the gateway",
                              "ok    phone: d_abc123 (Pixel 6) online, last heartbeat 7 s ago, PaynaniApp 0.6.3",
                              "ok    phone number: +525512345678")))
check("todo bien: sugiere la prueba de ida y vuelta", True, "sms check --to" in text)

code, text = run(gateway=None)
check("sin servicio instalado: FAIL y no revisa el puerto (en WSL puede ser de otra instalación)", (1, False),
      (code, "gateway on this machine" in text))

code, text = run(fetch=answers("http://127.0.0.1:8770"))
check("el túnel no llega: FAIL con la dirección", (1, True),
      (code, "FAIL  tunnel: https://agente.ngrok.app/sms/health does not reach the gateway" in text))

os.environ["PAYNANI_SMS_PUBLIC_URL"] = ""
code, text = run()
check("sin PAYNANI_SMS_PUBLIC_URL: FAIL que lo dice", (1, True), (code, "PAYNANI_SMS_PUBLIC_URL is not set" in text))
os.environ["PAYNANI_SMS_PUBLIC_URL"] = "https://ab-cd.trycloudflare.com"
code, text = run(fetch=answers("http://127.0.0.1:8770", "https://ab-cd.trycloudflare.com"))
check("túnel rápido de Cloudflare: aviso (no falla) por la dirección que cambia", (0, True),
      (code, "warn  tunnel: a trycloudflare.com quick tunnel changes address" in text))
os.environ["PAYNANI_SMS_PUBLIC_URL"] = "https://agente.ngrok.app"

code, text = run(phone=None)
check("sin teléfono emparejado: FAIL con el comando para emparejar", (1, True), (code, "sms pair" in text))
code, text = run(phone=dict(PHONE, online=False, last_seen_age_s=400))
check("teléfono sin conexión: FAIL que sugiere abrir Paynani (cierre del fabricante)", (1, True),
      (code, "offline, last heartbeat 400 s ago" in text and "Open Paynani on the phone" in text))
code, text = run(phone=dict(PHONE, online=False, last_seen_age_s=None))
check("emparejado pero nunca conectado", (1, True), (code, "has never connected" in text))
code, text = run(phone=dict(PHONE, sims=[{"slot": 0, "number": None}]))
check("SIM sin número: aviso, no falla", (0, True), (code, "warn  phone number: the SIM does not expose it" in text))

# --- con --to -----------------------------------------------------------------------------
sent = []


def fake_send(code):
    def send(args):
        sent.append(args)
        return code
    return send


code, text = run(to="55 1234")
check("--to que no es número: rechazo con 2 y nada enviado", (2, []), (code, sent))
code, text = run(to="+15550001111", phone=dict(PHONE, online=False, last_seen_age_s=400), send=fake_send(0))
check("con un FAIL no manda el SMS de prueba", (1, [], True), (code, sent, "Not sending the test text" in text))
code, text = run(to="+15550001111", send=fake_send(0))
check("--to: manda por sms send al número normalizado, con un texto de prueba", (0, "+15550001111", True),
      (code, sent[-1].number, sent[-1].text[0].startswith("paynani sms check")))
check("--to sin --wait-reply: dice cómo ver la respuesta", True, "sms.received" in text)
code, text = run(to="+15550001111", send=fake_send(2))
check("sms send rechaza (no está en el roster): sale con 2", 2, code)
code, text = run(to="+15550001111", send=fake_send(3))
check("el teléfono no lo mandó a tiempo: FAIL", (1, True), (code, "no delivery (exit 3" in text))

# --- la respuesta -------------------------------------------------------------------------------
journal = tmp / "state" / "events.jsonl"
journal.write_text(json.dumps({"event_type": "sms.received", "sender": {"address": "+15550001111"},
                               "event_id": "sms:viejo"}) + "\n")
offset = sms_check.journal_size(journal)
with journal.open("a") as fh:
    fh.write(json.dumps({"event_type": "sms.received", "sender": {"address": "+15559999999"}, "event_id": "sms:otro"}) + "\n")
    fh.write("no es json\n")
    fh.write(json.dumps({"event_type": "sms.received", "sender": {"address": "+15550001111"},
                         "event_id": "sms:nuevo", "roster_match": True}) + "\n")
got = sms_check.wait_for_reply(journal, offset, "+15550001111", 0)
check("wait_for_reply: sólo lo escrito después del envío y sólo de ese número", "sms:nuevo", got and got["event_id"])
check("wait_for_reply: nada de ese número, None al vencer", None,
      sms_check.wait_for_reply(journal, offset, "+15558888888", 0))
ticks = iter([0.0, 0.5, 1.0, 2.5])
slept = []
check("wait_for_reply: sondea hasta el plazo", None,
      sms_check.wait_for_reply(journal, offset, "+15558888888", 2, poll_s=1.0,
                               clock=lambda: next(ticks), sleep=slept.append))
check("wait_for_reply: durmió entre sondeos", 2, len(slept))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
