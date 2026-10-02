#!/usr/bin/env python3
"""
Tests for `paynani sms send` and `paynani sms status` (SRV-3, SMS_GATEWAY.md).
An assertion script, like the rest of this suite.

No network and no gateway process: the state directory is temporary and a
thread plays the phone by appending statuses to orders.jsonl, the way the
gateway does when the app reports.
"""
from __future__ import annotations

import contextlib
import io
import json
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import cli  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human |  | +52 1 55 1111 2222 |
| Sin Teléfono | sin@example.com | Human |  |  |
"""

tmp = Path(tempfile.mkdtemp())
roster = tmp / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
state = tmp / "state"
store = store_mod.Store(state)
cli._store = lambda: store
cli.paths.roster = lambda: roster
ORDERS = state / "sms" / "orders.jsonl"
OUTBOX = state / "sms" / "outbox"


def send(number, *text, wait=0, ttl=15, sim=None):
    out, err = io.StringIO(), io.StringIO()
    args = SimpleNamespace(number=number, text=list(text), wait=wait, ttl=ttl, sim=sim)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.run_send(args)
    return code, out.getvalue(), err.getvalue()


def status(order_id):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.run_status(SimpleNamespace(order_id=order_id))
    return code, out.getvalue(), err.getvalue()


def order_id_in(text):
    return next(w for w in text.split() if w.startswith("o_"))


def phone_reports(order_id, *states, delay=0.3):
    """Hace de app: cada estado como lo escribiría la pasarela."""
    def run():
        for s in states:
            time.sleep(delay)
            store.append_status({"id": gw.status_id(order_id, s), "order_id": order_id,
                                 "status": s, "at": store_mod.now_utc()})
    t = threading.Thread(target=run)
    t.start()
    return t


def queued():
    return sorted(p.name for p in OUTBOX.glob("*.json"))


# --- portón: nada se encola ----------------------------------------------
code, _, err = send("+525511112222", "Hola")
check("sin teléfono emparejado: código 1, nada en outbox", (1, True, []),
      (code, "paynani sms pair" in err, queued()))

store.save_device({"device_id": "d_abc123", "token_sha256": "0" * 64, "paired_at": store_mod.now_utc(),
                   "last_seen": None, "connected": False, "sims": []})

code, _, err = send("+525599990000", "Hola")
check("número fuera del roster: código 2 y nada en outbox", (2, True, []),
      (code, "not in" in err, queued()))
code, _, err = send("AMAZON", "Hola")
check("remitente alfanumérico: código 2", (2, True), (code, "not a phone number" in err))
code, _, err = send("+525511112222", "   ")
check("texto vacío: código 2", (2, True), (code, "empty_text" in err))
code, _, err = send("+525511112222", "x" * 1001)
check("texto de 1,001 caracteres: text_too_long, código 2, nada en outbox", (2, True, []),
      (code, "text_too_long" in err, queued()))
code, _, err = send("+525511112222", "Hola", ttl=0)
check("--ttl 0: código 2", 2, code)
check("los rechazos no tocan orders.jsonl", False, ORDERS.exists())

# --- encolar -----------------------------------------------------------------
code, out, _ = send("55 1111 2222", "Sí,", "les apartamos mesa a las 8.", sim=1)
oid = order_id_in(out)
check("encola con el número del roster escrito sin +52: código 3 (sin estado final)", (3, True), (code, store_mod.valid_order_id(oid)))
files = queued()
check("outbox/<id>.json", [f"{oid}.json"], files)
order = json.loads((OUTBOX / files[0]).read_text(encoding="utf-8"))
check("la orden: id, E.164, texto unido, SIM, vencimiento",
      (oid, "+525511112222", "Sí, les apartamos mesa a las 8.", 1, True),
      (order["id"], order["to"], order["text"], order.get("sim_slot"), order["expires_at"] > store_mod.now_utc()))
check("outbox/<id>.json es 600 y la carpeta 700",
      (0o600, 0o700), (stat.S_IMODE((OUTBOX / files[0]).stat().st_mode), stat.S_IMODE(OUTBOX.stat().st_mode)))
check("teléfono desconectado: lo dice en pantalla", True, "not connected" in out)
check("sin respuesta: dice cómo ver el estado", True, f"paynani sms status {oid}" in out)
code, out, _ = status(oid)
check("status: la orden quedó 'queued'", (0, True), (code, "queued" in out))

# --- sin estado final: código 3, la orden sigue en outbox ----------------------
before = set(queued())
code, out, _ = send("+525511112222", "Nadie contesta", wait=0)
pending = order_id_in(out)
check("--wait 0 sin estado final: código 3, y la orden sigue en outbox",
      (3, True, True), (code, f"{pending}.json" in queued(), pending + ".json" not in before))

# --- espera y estados ----------------------------------------------------------
code, out, _ = send("+525511112222", "Sin SIM")
oid2 = order_id_in(out)
check("sin --sim la orden no lleva sim_slot", False,
      "sim_slot" in json.loads((OUTBOX / f"{oid2}.json").read_text(encoding="utf-8")))
known = {oid, oid2, pending}


def send_with_phone(*states):
    """send() espera en este hilo; el 'teléfono' contesta desde otro, ya con el id en outbox."""
    box = {}
    th = threading.Thread(target=lambda: box.update(r=send("+525511112222", "Con respuesta", wait=5)))
    th.start()
    deadline = time.time() + 3
    new = []
    while time.time() < deadline and not new:
        time.sleep(0.05)
        new = [p.stem for p in OUTBOX.glob("*.json") if p.stem not in known]
    known.add(new[0])
    phone_reports(new[0], *states).join()
    th.join()
    return new[0], box["r"]


sent_id, (code, out, _) = send_with_phone("accepted", "sent")
check("sent: código 0 y lo muestra", (0, True, True), (code, "sent" in out, "accepted" in out))
_, (code, out, _) = send_with_phone("failed")
check("failed: código 1", (1, True), (code, "failed" in out))
code, out, _ = status(sent_id)
check("status: queued, accepted y sent en orden", ["queued", "accepted", "sent"],
      [l.split()[1] for l in out.strip().splitlines()])

# --- status ---------------------------------------------------------------------
code, _, err = status("../device")
check("status con un id mal formado: código 2", 2, code)
code, _, err = status("o_" + "0" * 32)
check("status de una orden que no existe: código 1", 1, code)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
