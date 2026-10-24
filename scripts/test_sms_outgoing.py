#!/usr/bin/env python3
"""
Tests for the shared send function (PRD #489 FR-13, T1 #504): one way to
create an SMS order for the agent, the owner (PaynaniWeb) and the API.
An assertion script, like the rest of this suite. No network, no gateway.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import outgoing  # noqa: E402
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


def fresh():
    return store_mod.Store(Path(tempfile.mkdtemp()) / "state")


def statuses(st):
    path = st.root / "orders.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def refused(fn):
    try:
        fn()
    except outgoing.Refused as exc:
        return exc
    return None


NOW = 1_800_000_000.0  # 2027-01-15T08:00:00Z
WEB = "203.0.113.7"

# --- ids y orígenes -------------------------------------------------------------
check("order_origin o_", "agent", store_mod.order_origin("o_" + "a" * 32))
check("order_origin w_", "owner", store_mod.order_origin("w_" + "a" * 32))
check("order_origin a_", "api", store_mod.order_origin("a_" + "a" * 32))
check("order_origin rechaza otro prefijo", None, store_mod.order_origin("x_" + "a" * 32))
check("valid_order_id rechaza una ruta", False, store_mod.valid_order_id("../device"))
check("new_order_id del dueño", True, store_mod.valid_order_id(outgoing.new_order_id("owner"))
      and outgoing.new_order_id("owner").startswith("w_"))

# --- el agente: igual que antes -------------------------------------------------
st = fresh()
order = outgoing.queue(st, to="+52 1 55 1111 2222", text="Hola", now=NOW)
check("agente: id o_", True, order["id"].startswith("o_"))
check("agente: número en E.164 (México sin el 1)", "+525511112222", order["to"])
check("agente: la orden no lleva origin", False, "origin" in order)
check("agente: vence en 15 minutos", "2027-01-15T08:15:00Z", order["expires_at"])
check("agente: en outbox y en pending_orders", [order["id"]], [o["id"] for o in st.pending_orders()])
rec = statuses(st)
check("agente: un queued en orders.jsonl", ["queued"], [r["status"] for r in rec])
check("agente: el queued no lleva origin", False, "origin" in rec[0])
check("agente: id del estado como la pasarela", outgoing.status_id(order["id"], "queued"), rec[0]["id"])
check("agente: sim_slot opcional", 1, outgoing.queue(st, to="+5215511112222", text="x", sim_slot=1, now=NOW)["sim_slot"])

# --- el dueño -------------------------------------------------------------------
st = fresh()
order = outgoing.queue(st, to="+5215511112222", text="Hola", origin="owner", source=WEB,
                       agent_pause_min=30, now=NOW)
check("dueño: id w_", True, order["id"].startswith("w_"))
check("dueño: origin owner", "owner", order["origin"])
check("dueño: agent_pause_min", 30, order["agent_pause_min"])
check("dueño: queued con origin y source", ("owner", WEB),
      (statuses(st)[0]["origin"], statuses(st)[0]["source"]))
check("dueño: la pasarela todavía no la manda", [], st.pending_orders())
check("dueño: pending_orders con el origen", [order["id"]], [o["id"] for o in st.pending_orders(origins=("owner",))])
check("dueño: sin casilla, pausa 0", 0, outgoing.queue(st, to="+5215511112222", text="x", origin="owner", source=WEB, now=NOW)["agent_pause_min"])
exc = refused(lambda: outgoing.queue(st, to="+5215511112222", text="x", origin="owner", source=WEB, agent_pause_min=1441, now=NOW))
check("dueño: pausa fuera de rango", "invalid_pause", exc and exc.code)

# --- la API ---------------------------------------------------------------------
st = fresh()
order = outgoing.queue(st, to="+5215511112222", text="Recordatorio", origin="api", token="citas", now=NOW)
check("api: id a_", True, order["id"].startswith("a_"))
check("api: la orden lleva el token", "citas", order["token"])
check("api: el queued lleva el token", "citas", statuses(st)[0]["token"])
check("api: no lleva agent_pause_min", False, "agent_pause_min" in order)

# --- validación: no escribe nada --------------------------------------------------
st = fresh()
exc = refused(lambda: outgoing.queue(st, to="+5215511112222", text="   ", now=NOW))
check("texto vacío", "empty_text", exc and exc.code)
exc = refused(lambda: outgoing.queue(st, to="+5215511112222", text="x" * 1001, now=NOW))
check("texto de 1,001", "text_too_long", exc and exc.code)
check("1,000 caracteres sí", True, bool(outgoing.queue(st, to="+5215511112222", text="x" * 1000, now=NOW)))
st = fresh()
exc = refused(lambda: outgoing.queue(st, to="no es número", text="x", now=NOW))
check("número inválido", "invalid_number", exc and exc.code)
exc = refused(lambda: outgoing.queue(st, to="+5215511112222", text="x", ttl_min=0, now=NOW))
check("ttl 0", "invalid_ttl", exc and exc.code)
check("nada escrito tras los rechazos", ([], []), (st.pending_orders(origins=("agent", "owner", "api")), statuses(st)))
try:
    outgoing.queue(st, to="+5215511112222", text="x", origin="martian", now=NOW)
    check("origen desconocido lanza ValueError", True, False)
except ValueError:
    check("origen desconocido lanza ValueError", True)

# --- tope por hora --------------------------------------------------------------
st = fresh()
outgoing.queue(st, to="+5215511112222", text="1", origin="owner", source=WEB, per_hour=2, now=NOW)
outgoing.queue(st, to="+5215511112222", text="2", origin="owner", source=WEB, per_hour=2, now=NOW + 60)
exc = refused(lambda: outgoing.queue(st, to="+5215511112222", text="3", origin="owner", source=WEB, per_hour=2, now=NOW + 120))
check("tope: la tercera se rechaza", "rate_limited", exc and exc.code)
check("tope: se libera una hora después de la primera", "2027-01-15T09:00:00Z", exc and exc.retry_at)
check("tope: la rechazada no se escribió", 2, len(st.pending_orders(origins=("owner",))))
check("tope: las del agente no cuentan", True,
      bool(outgoing.queue(st, to="+5215511112222", text="a", origin="agent", now=NOW + 120)))
check("tope: pasada la hora vuelve a dejar", True,
      bool(outgoing.queue(st, to="+5215511112222", text="4", origin="owner", source=WEB, per_hour=2, now=NOW + 3601)))
st = fresh()
outgoing.queue(st, to="+5215511112222", text="1", origin="api", token="citas", per_hour=1, now=NOW)
exc = refused(lambda: outgoing.queue(st, to="+5215511112222", text="2", origin="api", token="citas", per_hour=1, now=NOW))
check("tope por token", "rate_limited", exc and exc.code)
check("otro token tiene su propio tope", True,
      bool(outgoing.queue(st, to="+5215511112222", text="1", origin="api", token="facturas", per_hour=1, now=NOW)))

# --- revisión de Ximena en #513: rechazos estables, sin escribir nada ------------
st = fresh()
for label, kwargs, code in [
    ("api sin token", dict(origin="api"), "missing_token"),
    ("api con token vacío", dict(origin="api", token="  "), "missing_token"),
    ("dueño sin source", dict(origin="owner"), "missing_source"),
    ("dueño con source vacío", dict(origin="owner", source=""), "missing_source"),
    ("pausa no numérica", dict(origin="owner", source=WEB, agent_pause_min="abc"), "invalid_pause"),
    ("pausa negativa", dict(origin="owner", source=WEB, agent_pause_min=-1), "invalid_pause"),
    ("pausa booleana", dict(origin="owner", source=WEB, agent_pause_min=True), "invalid_pause"),
    ("per_hour 0", dict(origin="owner", source=WEB, per_hour=0), "invalid_limit"),
    ("per_hour negativo", dict(origin="owner", source=WEB, per_hour=-5), "invalid_limit"),
    ("per_hour no entero", dict(origin="api", token="citas", per_hour="30"), "invalid_limit"),
]:
    exc = refused(lambda kw=kwargs: outgoing.queue(st, to="+5215511112222", text="x", now=NOW, **kw))
    check(f"revisión: {label}", code, exc and exc.code)
check("revisión: ningún rechazo escribió nada",
      ([], [], []), (st.pending_orders(origins=("agent", "owner", "api")), statuses(st),
                     sorted(p.name for p in (st.root / "outbox").iterdir())))
check("revisión: pausa como texto válido", 45,
      outgoing.queue(st, to="+5215511112222", text="x", origin="owner", source=WEB, agent_pause_min="45", now=NOW)["agent_pause_min"])

# --- Revisión de #519: el tope por hora con envíos al mismo tiempo ----------------------
# El conteo se hace lento a propósito: sin el candado, todos ven 0 y todos escriben.
import multiprocessing  # noqa: E402
import threading  # noqa: E402
import time as _time  # noqa: E402

_real_recent = outgoing.recent_queued


def _slow_recent(*a, **kw):
    out = _real_recent(*a, **kw)
    _time.sleep(0.3)
    return out


def _send_one(root, results, index):
    try:
        outgoing.queue(store_mod.Store(root), to="+5215511112222", text=f"carrera {index}", origin="owner",
                       source=WEB, per_hour=1)
        results[index] = "queued"
    except outgoing.Refused as exc:
        results[index] = exc.code


outgoing.recent_queued = _slow_recent
try:
    race = fresh()
    results = {}
    barrier = threading.Barrier(4)
    threads = [threading.Thread(target=lambda i=i: (barrier.wait(), _send_one(race.root.parent, results, i)))
               for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    check("carrera con hilos y per_hour=1: sale uno, los otros rate_limited",
          ["queued", "rate_limited", "rate_limited", "rate_limited"], sorted(results.values()))
    check("carrera con hilos: una sola orden w_ y un solo queued",
          (1, 1), (len(list((race.root / "outbox").glob("w_*.json"))), len(statuses(race))))

    # Procesos: con fork heredan el conteo lento; el candado es del sistema, no de Python.
    race = fresh()
    ctx = multiprocessing.get_context("fork")
    manager_results = ctx.Manager().dict()
    procs = [ctx.Process(target=_send_one, args=(race.root.parent, manager_results, i)) for i in range(3)]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join()
    check("carrera con procesos y per_hour=1: sale uno",
          ["queued", "rate_limited", "rate_limited"], sorted(manager_results.values()))
    check("carrera con procesos: una sola orden en outbox",
          1, len(list((race.root / "outbox").glob("w_*.json"))))
finally:
    outgoing.recent_queued = _real_recent

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
