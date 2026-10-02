#!/usr/bin/env python3
"""
Tests for the phone's health (SRV-5, SMS_GATEWAY.md §7): sms.gateway.offline and
sms.gateway.online, and what `paynani status` and `healthcheck` show.
An assertion script, like the rest of this suite.

Nada de red: el tiempo se pasa a `health_tick(now)` y la conexión se simula.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import event as ev  # noqa: E402
import healthcheck  # noqa: E402
import ledger  # noqa: E402
from paynani_lib import status_cli  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import health  # noqa: E402
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


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def journal_events(journal):
    try:
        return [json.loads(line) for line in Path(journal).read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


T0 = 1_800_000_000.0

# --- sin teléfono: nada, y no se crean carpetas -----------------------------------
tmp = Path(tempfile.mkdtemp())
check("sin teléfono: phone_facts es None y no crea state/sms", (None, False),
      (health.phone_facts(tmp / "state"), (tmp / "state" / "sms").exists()))
check("sin teléfono: describe lo dice", ["no phone is paired"], health.describe(None))
check("sin teléfono: ningún aviso en healthcheck", [], healthcheck.sms_phone_warnings(None))

# --- phone_facts --------------------------------------------------------------------
state = tmp / "state"
store = store_mod.Store(state)
store.save_device({"device_id": "d_abc123", "token_sha256": "0" * 64, "paired_at": stamp(T0 - 3600), "model": "Pixel 6",
                   "last_seen": stamp(T0 - 12), "connected": True, "sims": []})
(state / "sms" / "outbox" / ("o_" + "1" * 32 + ".json")).write_text("{}")
(state / "sms" / "outbox" / ("o_" + "2" * 32 + ".json")).write_text("{}")
(state / "sms" / "outbox" / "otra-cosa.json").write_text("{}")
f = health.phone_facts(state, now=T0)
check("en línea: latido de hace 12 s, 2 órdenes en cola (sólo o_*.json)", (True, 12, 2),
      (f["online"], f["last_seen_age_s"], f["orders_queued"]))
check("describe: en línea con su latido y su cola", True,
      "d_abc123 (Pixel 6): online, last heartbeat 12 s ago" in health.describe(f)[0] and "2 order(s) queued" in health.describe(f)[0])
check("en línea no hay aviso de healthcheck", [], healthcheck.sms_phone_warnings(f))
f = health.phone_facts(state, now=T0 + 200)
check("connected=True con un latido de hace más de 90 s NO cuenta como en línea (la pasarela pudo morir)", False, f["online"])
check("healthcheck avisa del teléfono sin conexión (aviso, no problema)", True,
      "offline (last reported 212s ago)" in healthcheck.sms_phone_warnings(f)[0])
store.touch(connected=False, offline_notified=True)
check("describe: sin conexión, con el aviso ya enviado al agente", True,
      "OFFLINE" in health.describe(health.phone_facts(state, now=T0))[0]
      and "sms.gateway.offline was sent" in health.describe(health.phone_facts(state, now=T0))[0])
store.touch(last_seen=None)
check("nunca conectado", ("never connected", True),
      (health.describe(health.phone_facts(state, now=T0))[0].split(", ")[1],
       "has never connected" in healthcheck.sms_phone_warnings(health.phone_facts(state, now=T0))[0]))

# --- paynani status ----------------------------------------------------------------------
store.touch(last_seen=stamp(time.time() - 5), connected=True, offline_notified=False)
status_cli.state_dir = lambda: state
data = status_cli.facts()
check("status --json trae sms_phone", ("d_abc123", True), (data["sms_phone"]["device_id"], data["sms_phone"]["online"]))
out = io.StringIO()
with contextlib.redirect_stdout(out):
    status_cli.run(SimpleNamespace(json=False))
check("status imprime la línea del teléfono", True, "SMS phone: d_abc123 (Pixel 6): online" in out.getvalue())
healthcheck.state_dir = lambda: state
check("healthcheck: sms_phone_facts lee el mismo estado", "d_abc123", healthcheck.sms_phone_facts()["device_id"])

# --- el evento -------------------------------------------------------------------------------
e = ev.gateway_health_event(kind=ev.GATEWAY_OFFLINE, device_id="d_abc123", local_time="03:10:00", offline_for_s=95,
                            last_seen_local="03:08:25", observed_at="2026-10-02T09:10:00Z")
check("evento offline: tipo, cuenta y línea para el agente", True,
      e["event_type"] == "sms.gateway.offline" and e["account"] == "sms:d_abc123"
      and "[sms-gateway 03:10:00] el teléfono d_abc123 lleva 1 min 35 s sin conexión (último latido 03:08:25)" in e["notification_text"]
      and e["notification_text"].endswith("[scripts/paynani status]"))
check("evento offline: sin roster_match (es de la instalación, no de un remitente)", False, "roster_match" in e)
try:
    ev.gateway_health_event(kind="otra", device_id="d", local_time="", offline_for_s=0)
    check("tipo desconocido", "ValueError", "sin error")
except ValueError:
    check("tipo desconocido: ValueError", True)

# --- health_tick ------------------------------------------------------------------------------
def fresh(**kw):
    t = Path(tempfile.mkdtemp())
    st = t / "state"
    g = gw.Gateway(st, st / "events.jsonl", t / "roster.md", **kw)
    g.store.save_device({"device_id": "d_x1", "token_sha256": "0" * 64, "paired_at": stamp(T0 - 600), "last_seen": stamp(T0 - 30),
                         "connected": False, "sims": []})
    g.started_at = T0 - 600
    return g, st / "events.jsonl"


g, journal = fresh()
check("a los 60 s de silencio todavía no avisa", (None, 0), (g.health_tick(T0 + 29), len(journal_events(journal))))
check("a los 90 s avisa: offline", "offline", g.health_tick(T0 + 60))
evs = journal_events(journal)
check("el evento quedó en el diario y en el ledger", (1, "sms.gateway.offline", True),
      (len(evs), evs[0]["event_type"], ledger.latest(ledger.path_for(journal)).get(evs[0]["event_id"], {}).get("state") == "observed"))
check("avisa una sola vez por apagón", (None, 1), (g.health_tick(T0 + 120), len(journal_events(journal))))
check("la marca vive en device.json", True, g.store.device()["offline_notified"])

g2 = gw.Gateway(g.store.root.parent, journal, Path("x"))
g2.started_at = T0 + 130
check("reiniciar la pasarela no repite el aviso", (None, 1), (g2.health_tick(T0 + 400), len(journal_events(journal))))
g2.conn = object()
check("cuando vuelve: online, una vez", ("online", None), (g2.health_tick(T0 + 500), g2.health_tick(T0 + 501)))
evs = journal_events(journal)
check("el evento online dice cuánto duró", (2, "sms.gateway.online", True),
      (len(evs), evs[1]["event_type"], "volvió a conectarse tras 8 min 50 s" in evs[1]["notification_text"]))
check("la marca se limpia", (False, None), (g2.store.device().get("offline_notified"), g2.store.device().get("offline_at")))
g2.conn = None
check("un segundo apagón vuelve a avisar", "offline", g2.health_tick(T0 + 700))

g3, journal3 = fresh()
g3.started_at = T0 + 1000  # pasarela recién arrancada, el teléfono lleva una hora sin latir
check("pasarela recién arrancada: el teléfono tiene 90 s para volver antes de avisar", (None, None, "offline"),
      (g3.health_tick(T0 + 1010), g3.health_tick(T0 + 1089), g3.health_tick(T0 + 1091)))

g4, journal4 = fresh()
g4.store.touch(last_seen=None)
g4.started_at = T0 - 600
check("emparejado y nunca conectado: cuenta desde el emparejamiento", "offline", g4.health_tick(T0 + 100))

g5, _ = fresh()
(g5.store.root.parent / "events.jsonl").mkdir()  # el diario no se puede escribir
check("si el evento no se pudo escribir no se marca y se reintenta", (None, False),
      (g5.health_tick(T0 + 100), bool(g5.store.device().get("offline_notified"))))

g6 = gw.Gateway(Path(tempfile.mkdtemp()) / "state", Path("j"), Path("r"))
check("sin teléfono emparejado: nada", None, g6.health_tick(T0))
store6 = g.store
store6.revoke()
check("revocado: nada", None, g.health_tick(T0 + 900))

# --- el ciclo y serve() ---------------------------------------------------------------------
async def loop_test():
    t = Path(tempfile.mkdtemp())
    st = t / "state"
    gate = gw.Gateway(st, st / "events.jsonl", t / "roster.md", offline_after_s=0, health_every_s=0.05)
    gate.store.save_device({"device_id": "d_loop", "token_sha256": "0" * 64, "paired_at": stamp(time.time() - 600),
                            "last_seen": stamp(time.time() - 600), "connected": False, "sims": []})
    gate.started_at = time.time() - 600
    server = await gw.serve(gate, "127.0.0.1", 0)
    await asyncio.sleep(0.4)
    task = gate.health_task
    task.cancel()
    server.close()
    await server.wait_closed()
    return [x["event_type"] for x in journal_events(st / "events.jsonl")]


check("serve() arranca el ciclo de salud y escribe el aviso", ["sms.gateway.offline"], asyncio.run(loop_test()))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
