#!/usr/bin/env python3
"""
Tests for the phone's battery (PaynaniApp#109, SMS_GATEWAY.md §3 and §7):
`device.status` from the app, `sms.gateway.battery_low` / `battery_ok`, the last
battery in `sms.gateway.offline`, the thresholds in `sms.env`, and what `paynani
status` and `healthcheck` show. An assertion script, like the rest of this suite.

Nada de red: los mensajes se pasan a `_dispatch` con un WebSocket falso. El reloj
de la pasarela es `CLOCK[0]` (`Gateway.clock`), y `battery_tick(now)` recibe el suyo.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import event as ev  # noqa: E402
import healthcheck  # noqa: E402
from paynani_lib.sms import config as sms_config  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import health  # noqa: E402

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


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_text(self, text):
        self.sent.append(json.loads(text))


T0 = 1_800_000_000.0
HEX = "a" * 64
SETTLE = gw.BATTERY_SETTLE_S
CLOCK = [T0]  # el reloj de la pasarela en las pruebas; dispatch lo pone en la hora de la lectura


def new_gateway(**kw):
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    g = gw.Gateway(state, state / "events.jsonl", tmp / "roster.md", **kw)
    g.clock = lambda: CLOCK[0]
    g.store.save_device({"device_id": "d_abc123", "token_sha256": "0" * 64, "paired_at": stamp(T0 - 3600),
                         "model": "BV5500Pro", "last_seen": stamp(T0), "connected": True, "sims": []})
    return g, state


def status(pct, charging=False, at=T0, sid=HEX, **extra):
    msg = {"type": "device.status", "id": sid, "battery_pct": pct, "charging": charging,
           "plugged": "usb" if charging else "none", "battery_temp_c": 31.5, "measured_at": int(at * 1000)}
    msg.update(extra)
    return msg


def dispatch(g, ws, msg, now=None):
    """Entrega msg con la pasarela en `now` (por omisión, la hora de la lectura)."""
    measured = msg.get("measured_at")
    CLOCK[0] = now if now is not None else (measured / 1000 if isinstance(measured, int) and measured < 10**14 else T0)
    asyncio.run(g._dispatch(ws, "d_abc123", json.dumps(msg)))


def kinds(state):
    return [(e["event_type"], e.get("level")) for e in journal_events(state / "events.jsonl")]


# --- protocolo: accepts, device.status, ack ---------------------------------------------
check("welcome.accepts anuncia device.status", True, "device.status" in gw.ACCEPTS)
g, state = new_gateway()
ws = FakeWS()
dispatch(g, ws, status(80))
dev = g.store.device()
check("device.status se guarda en device.json", (80, False, "none", 31.5, stamp(T0)),
      (dev["battery_pct"], dev["charging"], dev["plugged"], dev["battery_temp_c"], dev["battery_measured_at"]))
check("y se contesta ack stored", {"type": "ack", "id": HEX, "result": "stored"}, ws.sent[-1])
dispatch(g, ws, status(90, at=T0 - 60, sid="b" * 64))
check("una lectura más vieja (de la cola) no pisa a la nueva: ack duplicate", (80, "duplicate"),
      (g.store.device()["battery_pct"], ws.sent[-1]["result"]))
dispatch(g, ws, status(150, sid="c" * 64))
check("battery_pct fuera de 0..100: error missing_field y ack rejected", ("missing_field", "rejected"),
      (ws.sent[-2].get("code"), ws.sent[-1]["result"]))
dispatch(g, ws, {"type": "device.status", "id": "corto", "battery_pct": 50, "charging": False, "measured_at": 1})
check("un id que no es de 64 hex se rechaza", "rejected", ws.sent[-1]["result"])
dispatch(g, ws, status(70, charging="sí", sid="d" * 64))
check("charging que no es booleano se rechaza", "rejected", ws.sent[-1]["result"])
check("nada de eso tocó la lectura guardada", 80, g.store.device()["battery_pct"])

# --- umbrales y una vez por nivel -------------------------------------------------------
# Sin cargar desde T0: los avisos salen desde T0 + SETTLE (cable flojo, punto 4 de la revisión).
g, state = new_gateway()
g.conn = object()  # conectado
ws = FakeWS()
dispatch(g, ws, status(60, at=T0))
check("60 %: sin aviso", None, g.battery_tick(now=T0 + 5))
dispatch(g, ws, status(24, at=T0 + 60, sid="1" * 64))
check("baja de 25 % hace poco desconectado: todavía nada", None, g.battery_tick(now=T0 + 65))
dispatch(g, ws, status(24, at=T0 + SETTLE, sid="b" * 64))
check("baja de 25 % tras 5 min sin cargar: battery_low warn", "warn", g.battery_tick(now=T0 + SETTLE + 5))
check("una sola vez: la siguiente revisión no repite", None, g.battery_tick(now=T0 + SETTLE + 10))
dispatch(g, ws, status(20, at=T0 + SETTLE + 60, sid="2" * 64))
check("sigue bajando sobre el crítico: nada", None, g.battery_tick(now=T0 + SETTLE + 65))
dispatch(g, ws, status(9, at=T0 + SETTLE + 120, sid="3" * 64))
check("baja de 10 %: battery_low critical", "critical", g.battery_tick(now=T0 + SETTLE + 125))
dispatch(g, ws, status(5, at=T0 + SETTLE + 180, sid="4" * 64))
check("ya avisado el crítico: nada más", None, g.battery_tick(now=T0 + SETTLE + 185))
check("en el diario: a lo más dos avisos por descarga",
      [("sms.gateway.battery_low", "warn"), ("sms.gateway.battery_low", "critical")], kinds(state))
low = journal_events(state / "events.jsonl")[0]
check("el aviso dice el porcentaje, que no carga y que lo conecten, sin roster_match",
      (True, True, "roster_match" in low, "sms:d_abc123"),
      ("24 %" in low["notification_text"], "conecten al cargador" in low["notification_text"], False, low["account"]))

# --- recuperación ------------------------------------------------------------------------
dispatch(g, ws, status(6, charging=True, at=T0 + SETTLE + 240, sid="5" * 64))
check("al conectar el cargador: battery_ok", "ok", g.battery_tick(now=T0 + SETTLE + 241))
check("battery_ok una sola vez", None, g.battery_tick(now=T0 + SETTLE + 246))
check("y la marca se limpia", "", g.store.device()["battery_alert_level"])
check("el diario termina en battery_ok", ("sms.gateway.battery_ok", None), kinds(state)[-1])

# --- salto directo y reintento ------------------------------------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(30, at=T0))
dispatch(g, ws, status(5, at=T0 + SETTLE, sid="c" * 64))
check("del 30 % al 5 % de golpe: sólo critical", "critical", g.battery_tick(now=T0 + SETTLE + 1))
check("…una vez, sin warn", [("sms.gateway.battery_low", "critical")], kinds(state))
g, state = new_gateway()
g.conn = object()
dispatch(g, FakeWS(), status(20, at=T0))
real_publish = g._publish
g._publish = lambda envelope: False
check("si no se pudo escribir el aviso: sin marca", (None, ""),
      (g.battery_tick(now=T0 + SETTLE), g.store.device().get("battery_alert_level") or ""))
g._publish = real_publish
check("…y la siguiente revisión lo reintenta", "warn", g.battery_tick(now=T0 + SETTLE + 30))

# --- cable flojo: conecta y desconecta cada minuto --------------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(20, at=T0))
check("cable flojo: el primer warn sale tras 5 min sin cargar", "warn", g.battery_tick(now=T0 + SETTLE))
results = []
for i in range(8):
    t = T0 + SETTLE + 60 * (i + 1)
    dispatch(g, ws, status(20, charging=(i % 2 == 0), at=t, sid=f"{i:064x}"))
    results.append(g.battery_tick(now=t + 1))
check("cable flojo: 8 minutos alternando dan un solo ok y ningún warn más", ["ok"] + [None] * 7, results)
dispatch(g, ws, status(20, at=T0 + SETTLE + 600, sid="d" * 64))
dispatch(g, ws, status(19, at=T0 + 2 * SETTLE + 600, sid="e" * 64))
check("cable flojo: ya 5 min sin cargar, warn otra vez", "warn", g.battery_tick(now=T0 + 2 * SETTLE + 601))
check("cable flojo: en total warn, ok, warn",
      [("sms.gateway.battery_low", "warn"), ("sms.gateway.battery_ok", None), ("sms.gateway.battery_low", "warn")],
      kinds(state))

# --- histéresis ----------------------------------------------------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(24, at=T0))
check("histéresis: 24 % avisa warn", "warn", g.battery_tick(now=T0 + SETTLE))
dispatch(g, ws, status(27, at=T0 + SETTLE + 60, sid="6" * 64))
check("histéresis: 27 % sin cargar (bajo 25 + 5) no dice battery_ok", None, g.battery_tick(now=T0 + SETTLE + 61))
dispatch(g, ws, status(24, at=T0 + SETTLE + 120, sid="7" * 64))
check("histéresis: vuelve a 24 % y no repite warn", None, g.battery_tick(now=T0 + SETTLE + 121))
dispatch(g, ws, status(30, at=T0 + SETTLE + 180, sid="8" * 64))
check("histéresis: 30 % (25 + 5) sí dice battery_ok", "ok", g.battery_tick(now=T0 + SETTLE + 181))
check("histéresis: un solo warn y un solo ok", [("sms.gateway.battery_low", "warn"), ("sms.gateway.battery_ok", None)],
      kinds(state))

# --- dato viejo, sin dato, desconectado -------------------------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(5, at=T0))
check("recibido hace 21 min: ningún aviso", None, g.battery_tick(now=T0 + 21 * 60))
check("recibido hace 19 min: sí avisa", "critical", g.battery_tick(now=T0 + 19 * 60))
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(5, at=T0 - 30 * 60), now=T0)
check("reloj del teléfono 30 min atrasado: lo viejo se mide con la llegada y sí avisa", "critical",
      g.battery_tick(now=T0 + SETTLE))
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(5, at=T0 + 4 * 60), now=T0)
check("reloj del teléfono 4 min adelantado: se acepta", "stored", ws.sent[-1]["result"])
check("…y se vuelve viejo a los 20 min de llegar, no de measured_at", None, g.battery_tick(now=T0 + 21 * 60))
g, state = new_gateway()
g.conn = object()
check("app vieja (sin device.status): ningún aviso", None, g.battery_tick(now=T0))
g, state = new_gateway()
ws = FakeWS()
dispatch(g, ws, status(5, at=T0))
check("sin conexión no hay aviso de batería (lo dice sms.gateway.offline)", None, g.battery_tick(now=T0 + SETTLE))
check("cargando no avisa aunque esté bajo", None,
      (lambda g2: (g2.store.touch(charging=True), g2.battery_tick(now=T0 + SETTLE))[1])(g))

# --- measured_at fuera de rango y tipos raros --------------------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(80, at=T0 + 86400), now=T0)
check("measured_at un día en el futuro: error y ack rejected",
      ("missing_field", "rejected", True), (ws.sent[-2]["code"], ws.sent[-1]["result"], "fuera de rango" in ws.sent[-2]["detail"]))
check("…y no se guarda", None, g.store.device().get("battery_pct"))
dispatch(g, ws, status(5, at=T0), now=T0)
check("…así que una lectura real después sí se guarda y avisa", ("stored", "critical"),
      (ws.sent[-1]["result"], g.battery_tick(now=T0 + SETTLE)))
dispatch(g, ws, status(80, sid="f" * 64, measured_at=10 ** 20), now=T0)
check("measured_at enorme: ack rejected, sin excepción", "rejected", ws.sent[-1]["result"])
dispatch(g, ws, status(80, at=T0 - 31 * 86400, sid="9" * 64), now=T0)
check("measured_at de hace 31 días: rejected", "rejected", ws.sent[-1]["result"])
for label, extra in (("battery_pct 50.0", {"battery_pct": 50.0}), ("battery_pct True", {"battery_pct": True}),
                     ("charging 1", {"charging": 1}), ("measured_at como texto", {"measured_at": str(int(T0 * 1000))})):
    dispatch(g, ws, status(80, at=T0, sid="8" * 64, **extra), now=T0)
    check(f"{label}: rejected", "rejected", ws.sent[-1]["result"])
dispatch(g, ws, status(80, at=T0 + 1, sid="7" * 64, battery_temp_c=float("nan")), now=T0)
check("battery_temp_c NaN: se guarda la lectura sin temperatura", ("stored", None),
      (ws.sent[-1]["result"], g.store.device().get("battery_temp_c")))
check("…y device.json sigue siendo JSON estricto", True,
      "NaN" not in (state / "sms" / "device.json").read_text(encoding="utf-8"))
dispatch(g, ws, status(80, at=T0 + 2, sid="6" * 64, battery_temp_c=500), now=T0)
check("battery_temp_c 500: sin temperatura", None, g.store.device().get("battery_temp_c"))

# --- un hello con una lectura mala no tumba la sesión ----------------------------------
g, state = new_gateway()
for bad in ({"battery_pct": 50, "charging": False, "measured_at": 10 ** 20},
            {"battery_pct": 50, "charging": False, "measured_at": int((T0 + 86400) * 1000)},
            {"battery_pct": "x"}):
    ok = True
    try:
        if g._device_status_problem(bad) is None:
            g._store_device_status(bad)
    except Exception:  # noqa: BLE001
        ok = False
    check(f"hello.device_status malo ({str(bad)[:40]}…): no lanza y no se guarda", (True, None),
          (ok, g.store.device().get("battery_pct")))

# --- la marca sobrevive a un reinicio de la pasarela ----------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(20, at=T0))
check("reinicio: warn", "warn", g.battery_tick(now=T0 + SETTLE))
g2 = gw.Gateway(state, state / "events.jsonl", state.parent / "roster.md")
g2.conn = object()
check("una pasarela nueva sobre el mismo device.json no repite warn", None, g2.battery_tick(now=T0 + SETTLE + 1))

# --- el saludo trae la última lectura --------------------------------------------------
g, state = new_gateway()
check("hello.device_status se guarda (sin id ni ack)", True,
      g._device_status_problem({"battery_pct": 42, "charging": True, "measured_at": int(T0 * 1000)}) is None
      and g._store_device_status({"battery_pct": 42, "charging": True, "plugged": "ac", "measured_at": int(T0 * 1000)}))
check("…y queda en device.json", (42, True, "ac"),
      (g.store.device()["battery_pct"], g.store.device()["charging"], g.store.device()["plugged"]))
check("plugged desconocido se guarda como none", True,
      g._store_device_status({"battery_pct": 41, "charging": False, "plugged": "solar", "measured_at": int(T0 * 1000) + 1000})
      and g.store.device()["plugged"] == "none")

# --- sms.gateway.offline con la última batería ----------------------------------------
g, state = new_gateway()
g.store.touch(connected=False, last_seen=stamp(T0 - 200))
g._store_device_status({"battery_pct": 8, "charging": False, "measured_at": int((T0 - 210) * 1000)})
g.started_at = T0 - 1000
check("offline sale con el teléfono callado", "offline", g.health_tick(now=T0))
off = journal_events(state / "events.jsonl")[-1]
check("offline incluye la última batería conocida", (True, 8),
      ("última batería 8 %" in off["notification_text"], off.get("last_battery_pct")))
check("una lectura de hoy va con la hora; una de otro día, con la fecha", (5, 11),
      (len(gw._when_local(T0 - 210, T0)), len(gw._when_local(T0 - 2 * 86400, T0))))
g, state = new_gateway()
g.store.touch(connected=False, last_seen=stamp(T0 - 200))
g.started_at = T0 - 1000
g.health_tick(now=T0)
off = journal_events(state / "events.jsonl")[-1]
check("sin lectura (app vieja): offline como antes, sin batería", (False, False),
      ("batería" in off["notification_text"], "last_battery_pct" in off))

# --- eventos: forma del sobre -----------------------------------------------------------
e = ev.gateway_battery_event(kind=ev.GATEWAY_BATTERY_OK, device_id="d_abc123", local_time="03:10:00", battery_pct=31,
                             charging=True, observed_at="2026-10-18T09:10:00Z")
check("battery_ok: tipo, cuenta, carga y comando", ("sms.gateway.battery_ok", "sms:d_abc123", True, "scripts/paynani status"),
      (e["event_type"], e["account"], e["charging"], e["inspection_command"]))
try:
    ev.gateway_battery_event(kind=ev.GATEWAY_BATTERY_LOW, device_id="d", local_time="x", battery_pct=1, charging=False)
    bad = False
except ValueError:
    bad = True
check("battery_low sin nivel es un error", True, bad)

# --- sms.env ---------------------------------------------------------------------------
check("umbrales por omisión 25 y 10 (Q88)", (25, 10), sms_config.battery_thresholds({}))
check("umbrales desde sms.env", (30, 15), sms_config.battery_thresholds(
    {"PAYNANI_SMS_BATTERY_WARN_PCT": "30", "PAYNANI_SMS_BATTERY_CRITICAL_PCT": "15"}))
check("un crítico por encima del aviso vuelve a los de omisión", (25, 10), sms_config.battery_thresholds(
    {"PAYNANI_SMS_BATTERY_WARN_PCT": "10", "PAYNANI_SMS_BATTERY_CRITICAL_PCT": "20"}))
check("un valor que no es número vuelve a los de omisión", (25, 10), sms_config.battery_thresholds(
    {"PAYNANI_SMS_BATTERY_WARN_PCT": "mucho"}))
for raw in ("0", "100"):
    problems = []
    check(f"un aviso de {raw} vuelve a los de omisión y se dice por qué", ((25, 10), 1),
          (sms_config.battery_thresholds({"PAYNANI_SMS_BATTERY_WARN_PCT": raw}, problems), len(problems)))
problems = []
sms_config.battery_thresholds({"PAYNANI_SMS_BATTERY_WARN_PCT": "10", "PAYNANI_SMS_BATTERY_CRITICAL_PCT": "20"}, problems)
check("un crítico sobre el aviso también se dice", True, len(problems) == 1 and "crítico" in problems[0])
problems = []
sms_config.battery_thresholds({}, problems)
check("sin claves no hay nada que decir", [], problems)
tmp = Path(tempfile.mkdtemp())
(tmp / "sms.env").write_text("PAYNANI_SMS_BATTERY_WARN_PCT=35\nPAYNANI_SMS_BATTERY_CRITICAL_PCT=12\nOTRA=1\n")
env = {}
sms_config.load_sms_env(tmp / "sms.env", env)
check("load_sms_env acepta las dos claves nuevas y nada más", {"PAYNANI_SMS_BATTERY_WARN_PCT": "35",
                                                             "PAYNANI_SMS_BATTERY_CRITICAL_PCT": "12"}, env)
g, state = new_gateway(battery_warn_pct=35, battery_critical_pct=12)
g.conn = object()
dispatch(g, FakeWS(), status(34))
check("la pasarela usa los umbrales que le pasan", "warn", g.battery_tick(now=T0 + SETTLE))

# --- paynani status y healthcheck --------------------------------------------------------
g, state = new_gateway()
f = health.phone_facts(state, now=T0)
check("status: app sin device.status dice batería desconocida", True,
      "battery unknown" in health.describe(f)[0])
CLOCK[0] = T0 - 70
g._store_device_status({"battery_pct": 23, "charging": False, "measured_at": int((T0 - 70) * 1000)})
g.store.touch(battery_alert_level="warn")
f = health.phone_facts(state, now=T0)
line = health.describe(f)[0]
check("status: porcentaje, si carga, antigüedad y el aviso enviado", True,
      "battery 23 % not charging, read 1 min 10 s ago (alerts below 25 % and 10 %)" in line
      and "battery_low warn was sent" in line)
check("healthcheck avisa batería baja sin cargar", True,
      any("23 % battery and not charging" in w for w in healthcheck.sms_phone_warnings(f)))
f = health.phone_facts(state, now=T0 + 30 * 60)
check("status: un dato de hace 30 min se marca viejo", True, "stale" in health.describe(f)[0])
check("healthcheck no avisa por un dato viejo", [], [w for w in healthcheck.sms_phone_warnings(f) if "battery" in w])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
