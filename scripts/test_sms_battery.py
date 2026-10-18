#!/usr/bin/env python3
"""
Tests for the phone's battery (PaynaniApp#109, SMS_GATEWAY.md §3 and §7):
`device.status` from the app, `sms.gateway.battery_low` / `battery_ok`, the last
battery in `sms.gateway.offline`, the thresholds in `sms.env`, and what `paynani
status` and `healthcheck` show. An assertion script, like the rest of this suite.

Nada de red: los mensajes se pasan a `_dispatch` con un WebSocket falso, y el
tiempo a `battery_tick(now)`.
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


def new_gateway(**kw):
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    g = gw.Gateway(state, state / "events.jsonl", tmp / "roster.md", **kw)
    g.store.save_device({"device_id": "d_abc123", "token_sha256": "0" * 64, "paired_at": stamp(T0 - 3600),
                         "model": "BV5500Pro", "last_seen": stamp(T0), "connected": True, "sims": []})
    return g, state


def status(pct, charging=False, at=T0, sid=HEX, **extra):
    msg = {"type": "device.status", "id": sid, "battery_pct": pct, "charging": charging,
           "plugged": "usb" if charging else "none", "battery_temp_c": 31.5, "measured_at": int(at * 1000)}
    msg.update(extra)
    return msg


def dispatch(g, ws, msg):
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
g, state = new_gateway()
g.conn = object()  # conectado
ws = FakeWS()
dispatch(g, ws, status(60, at=T0))
check("60 %: sin aviso", None, g.battery_tick(now=T0 + 5))
dispatch(g, ws, status(24, at=T0 + 60, sid="1" * 64))
check("baja de 25 %: battery_low warn", "warn", g.battery_tick(now=T0 + 65))
check("una sola vez: la siguiente revisión no repite", None, g.battery_tick(now=T0 + 70))
dispatch(g, ws, status(20, at=T0 + 120, sid="2" * 64))
check("sigue bajando sobre el crítico: nada", None, g.battery_tick(now=T0 + 125))
dispatch(g, ws, status(9, at=T0 + 180, sid="3" * 64))
check("baja de 10 %: battery_low critical", "critical", g.battery_tick(now=T0 + 185))
dispatch(g, ws, status(5, at=T0 + 240, sid="4" * 64))
check("ya avisado el crítico: nada más", None, g.battery_tick(now=T0 + 245))
check("en el diario: a lo más dos avisos por descarga",
      [("sms.gateway.battery_low", "warn"), ("sms.gateway.battery_low", "critical")], kinds(state))
low = journal_events(state / "events.jsonl")[0]
check("el aviso dice el porcentaje, que no carga y que lo conecten, sin roster_match",
      (True, True, "roster_match" in low, "sms:d_abc123"),
      ("24 %" in low["notification_text"], "conecten al cargador" in low["notification_text"], False, low["account"]))

# --- recuperación ------------------------------------------------------------------------
dispatch(g, ws, status(6, charging=True, at=T0 + 300, sid="5" * 64))
check("al conectar el cargador: battery_ok", "ok", g.battery_tick(now=T0 + 301))
check("battery_ok una sola vez", None, g.battery_tick(now=T0 + 306))
check("y la marca se limpia", "", g.store.device()["battery_alert_level"])
check("el diario termina en battery_ok", ("sms.gateway.battery_ok", None), kinds(state)[-1])

# --- histéresis ----------------------------------------------------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(24, at=T0))
check("histéresis: 24 % avisa warn", "warn", g.battery_tick(now=T0 + 1))
dispatch(g, ws, status(27, at=T0 + 60, sid="6" * 64))
check("histéresis: 27 % sin cargar (bajo 25 + 5) no dice battery_ok", None, g.battery_tick(now=T0 + 61))
dispatch(g, ws, status(24, at=T0 + 120, sid="7" * 64))
check("histéresis: vuelve a 24 % y no repite warn", None, g.battery_tick(now=T0 + 121))
dispatch(g, ws, status(30, at=T0 + 180, sid="8" * 64))
check("histéresis: 30 % (25 + 5) sí dice battery_ok", "ok", g.battery_tick(now=T0 + 181))
check("histéresis: un solo warn y un solo ok", [("sms.gateway.battery_low", "warn"), ("sms.gateway.battery_ok", None)],
      kinds(state))

# --- dato viejo, sin dato, desconectado -------------------------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(5, at=T0))
check("dato de hace 21 min: ningún aviso", None, g.battery_tick(now=T0 + 21 * 60))
check("dato de hace 19 min: sí avisa", "critical", g.battery_tick(now=T0 + 19 * 60))
g, state = new_gateway()
g.conn = object()
check("app vieja (sin device.status): ningún aviso", None, g.battery_tick(now=T0))
g, state = new_gateway()
ws = FakeWS()
dispatch(g, ws, status(5, at=T0))
check("sin conexión no hay aviso de batería (lo dice sms.gateway.offline)", None, g.battery_tick(now=T0 + 5))
check("cargando no avisa aunque esté bajo", None, (lambda g2: (g2.store.touch(charging=True), g2.battery_tick(now=T0 + 5))[1])(g))

# --- la marca sobrevive a un reinicio de la pasarela ----------------------------------
g, state = new_gateway()
g.conn = object()
ws = FakeWS()
dispatch(g, ws, status(20, at=T0))
check("reinicio: warn", "warn", g.battery_tick(now=T0 + 1))
g2 = gw.Gateway(state, state / "events.jsonl", state.parent / "roster.md")
g2.conn = object()
check("una pasarela nueva sobre el mismo device.json no repite warn", None, g2.battery_tick(now=T0 + 2))

# --- el saludo trae la última lectura --------------------------------------------------
g, state = new_gateway()
check("hello.device_status se guarda (sin id ni ack)", True,
      g._store_device_status({"battery_pct": 42, "charging": True, "plugged": "ac", "measured_at": int(T0 * 1000)}))
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
tmp = Path(tempfile.mkdtemp())
(tmp / "sms.env").write_text("PAYNANI_SMS_BATTERY_WARN_PCT=35\nPAYNANI_SMS_BATTERY_CRITICAL_PCT=12\nOTRA=1\n")
env = {}
sms_config.load_sms_env(tmp / "sms.env", env)
check("load_sms_env acepta las dos claves nuevas y nada más", {"PAYNANI_SMS_BATTERY_WARN_PCT": "35",
                                                             "PAYNANI_SMS_BATTERY_CRITICAL_PCT": "12"}, env)
g, state = new_gateway(battery_warn_pct=35, battery_critical_pct=12)
g.conn = object()
dispatch(g, FakeWS(), status(34))
check("la pasarela usa los umbrales que le pasan", "warn", g.battery_tick(now=T0 + 1))

# --- paynani status y healthcheck --------------------------------------------------------
g, state = new_gateway()
f = health.phone_facts(state, now=T0)
check("status: app sin device.status dice batería desconocida", True,
      "battery unknown" in health.describe(f)[0])
g._store_device_status({"battery_pct": 23, "charging": False, "measured_at": int((T0 - 70) * 1000)})
g.store.touch(battery_alert_level="warn")
f = health.phone_facts(state, now=T0)
line = health.describe(f)[0]
check("status: porcentaje, si carga, antigüedad y el aviso enviado", True,
      "battery 23 % not charging, read 1 min 10 s ago" in line and "battery_low warn was sent" in line)
check("healthcheck avisa batería baja sin cargar", True,
      any("23 % battery and not charging" in w for w in healthcheck.sms_phone_warnings(f)))
f = health.phone_facts(state, now=T0 + 30 * 60)
check("status: un dato de hace 30 min se marca viejo", True, "stale" in health.describe(f)[0])
check("healthcheck no avisa por un dato viejo", [], [w for w in healthcheck.sms_phone_warnings(f) if "battery" in w])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
