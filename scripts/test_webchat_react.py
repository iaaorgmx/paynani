#!/usr/bin/env python3
"""
Tests for reactions in Webchat (PRD #685 F3, the FR-14 contract on #685): `store.react`,
`reactions` in each message, the notice to the agent when the owner reacts (FR-16a),
`webchat react`, `webchat thread` and `event show wc:… --body` of a reaction.

The store and the CLI run on a temporary PAYNANI_STATE.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import envfile  # noqa: E402
from paynani_lib.web import webchat_pages  # noqa: E402
from paynani_lib.webchat import store  # noqa: E402

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
STATE = tmp / "state"
STATE.mkdir()
ENV = dict(os.environ, PAYNANI_STATE=str(STATE))
OWNER = {"name": "Dueña Prueba", "email": "duena@example.com"}
envfile.read_env = lambda: {"AGENT_EMAIL_FROM_NAME": "Agente Prueba"}


def events():
    path = STATE / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cli(*argv):
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "paynani"), *argv],
                          capture_output=True, text=True, env=ENV, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


def rejected(fn):
    try:
        fn()
    except store.Rejected as exc:
        return exc.code
    return None


# --- la web lo detecta -------------------------------------------------------------------
check("webchat_pages.reacts ve el almacén del núcleo", True, webchat_pages.reacts(store))

owner_msg = store.append("owner", "¿Ya salió el reporte de la semana?", [], owner=OWNER, state_dir=STATE)
agent_msg = store.append("agent", "Sí, te lo mandé al correo hace un rato.", [], state_dir=STATE)
n_events = len(events())

# --- el dueño reacciona desde la web ------------------------------------------------------
res = store.react(agent_msg["id"], "👍", by="owner", state_dir=STATE)
check("devuelve el ref", agent_msg["id"], res["ref"])
check("y las reacciones del mensaje", [{"emoji": "👍", "count": 1, "mine": True}], res["reactions"])
check("el hilo trae reactions en ese mensaje", res["reactions"],
      store.messages(state_dir=STATE)[-1].get("reactions"))
check("sin reacciones, el campo no viene", False, "reactions" in store.messages(state_dir=STATE)[0])
check("store.message también las trae", res["reactions"],
      store.message(agent_msg["id"], state_dir=STATE).get("reactions"))

new = events()[n_events:]
check("la del dueño avisa al agente (FR-16a)", 1, len(new))
ev = new[0]
check("con kind reaction", "reaction", ev["kind"])
check("y un event_id wc: propio, distinto del mensaje", True,
      ev["event_id"].startswith("wc:") and ev["event_id"] != "wc:" + agent_msg["id"][2:])
check("el aviso dice el emoji y el extracto", True,
      "Dueña Prueba (PaynaniWeb) reaccionó 👍 a «Sí, te lo mandé al correo hace un rato.»"
      in ev["notification_text"])
check("y cómo verlo", True, f"[scripts/paynani event show {ev['event_id']}]" in ev["notification_text"])
check("el evento queda observed en el ledger", True,
      ev["event_id"] in (STATE / "lifecycle.jsonl").read_text(encoding="utf-8"))
react_event = ev["event_id"]

# --- la misma no cambia nada; otra la reemplaza -------------------------------------------
n_events = len(events())
store.react(agent_msg["id"], "👍", by="owner", state_dir=STATE)
check("poner la misma no avisa otra vez", n_events, len(events()))
res = store.react(agent_msg["id"], "❤️", by="owner", state_dir=STATE)
check("otra la reemplaza (FR-11): una por mensaje", [{"emoji": "❤️", "count": 1, "mine": True}], res["reactions"])
check("cambiar da un solo aviso, con la nueva", True,
      len(events()) == n_events + 1 and "reaccionó ❤️ a" in events()[-1]["notification_text"])

# --- el emoji, normalizado (Iris, #685) ------------------------------------------------
n_events = len(events())
store.react(agent_msg["id"], "❤", by="owner", state_dir=STATE)
check("«❤» sin U+FE0F es la misma que «❤️»: no avisa", n_events, len(events()))
res = store.react(agent_msg["id"], "❤", by="agent", state_dir=STATE)
check("la del agente y la del dueño se cuentan juntas", [{"emoji": "❤️", "count": 2, "mine": True}],
      res["reactions"])
check("la del agente no avisa", n_events, len(events()))

# --- quitar ---------------------------------------------------------------------------
n_events = len(events())
res = store.react(agent_msg["id"], "", by="owner", state_dir=STATE)
check("vacío quita la del dueño; queda la del agente", [{"emoji": "❤", "count": 1, "mine": False}],
      res["reactions"])
check("quitar también avisa", True,
      len(events()) == n_events + 1
      and "Dueña Prueba (PaynaniWeb) quitó su reacción ❤️ de «Sí, te lo mandé" in events()[-1]["notification_text"])
n_events = len(events())
store.react(agent_msg["id"], "", by="owner", state_dir=STATE)
check("quitar una que no hay no avisa", n_events, len(events()))

# --- el orden: primero la nuestra -----------------------------------------------------
store.react(owner_msg["id"], "👀", by="agent", state_dir=STATE)
res = store.react(owner_msg["id"], "🔥", by="owner", state_dir=STATE)
check("primero la nuestra, luego la otra", ["🔥", "👀"], [r["emoji"] for r in res["reactions"]])

# --- errores ----------------------------------------------------------------------------
missing = "w_" + "0" * 32
check("un ref que no existe es not_found", "not_found", rejected(lambda: store.react(missing, "👍", state_dir=STATE)))
check("un ref sin forma de w_ es not_found", "not_found", rejected(lambda: store.react("tg:1", "👍", state_dir=STATE)))
for bad in ("hola", "👍 👍", "👍👍", "🇲🇽🇺🇸", "<b>", "a👍", "️", "👍" * 9):
    check(f"{bad!r} no es un emoji: bad_emoji", "bad_emoji",
          rejected(lambda bad=bad: store.react(agent_msg["id"], bad, state_dir=STATE)))
for good in ("👍", "❤️", "❤", "👨‍👩‍👧", "👍🏽", "1️⃣", "🇲🇽", "🏴󠁧󠁢󠁳󠁣󠁴󠁿"):
    check(f"{good!r} es un emoji", True, store.valid_emoji(good))
try:
    store.react(agent_msg["id"], "👍", by="web", state_dir=STATE)
    check("by sólo es owner o agent", "ValueError", None)
except ValueError:
    check("by sólo es owner o agent", True)

# --- la CLI del agente --------------------------------------------------------------------
n_events = len(events())
rc, out, err = cli("webchat", "react", owner_msg["id"], "👍")
check("webchat react sale bien", 0, rc)
check("y dice cómo quedó", True, out.startswith(f"{owner_msg['id']}\treacted 👍\t[🔥 dueño, 👍 agente]"))
check("la del agente no avisa (FR-16a)", n_events, len(events()))
rc, out, err = cli("webchat", "thread", "--limit", "20")
check("webchat thread muestra las reacciones", True, "[🔥 dueño, 👍 agente]" in out)
rc, out, err = cli("webchat", "react", owner_msg["id"], "--remove")
check("--remove quita la del agente", True, rc == 0 and "\tremoved\t[🔥 dueño]" in out)
rc, out, err = cli("webchat", "react", owner_msg["id"])
check("sin emoji ni --remove da 2", 2, rc)
rc, out, err = cli("webchat", "react", owner_msg["id"], "👍", "--remove")
check("--remove con emoji da 2", 2, rc)
rc, out, err = cli("webchat", "react", missing, "👍")
check("un ref que no existe da 2", True, rc == 2 and "not_found" in err)

# --- event show de una reacción --------------------------------------------------------
rc, out, err = cli("event", "show", react_event)
check("event show de una reacción sale bien", 0, rc)
check("con la reacción en el JSON", {"ref": agent_msg["id"], "emoji": "👍", "removed": False},
      json.loads(out[:out.rindex("}") + 1])["reaction"])
rc, out, err = cli("event", "show", react_event, "--body")
check("event show --body sale bien", 0, rc)
check("imprime la reacción y el mensaje completo", True,
      f"--- reaction: 👍 on {agent_msg['id']} ---\nSí, te lo mandé al correo hace un rato." in out)
check("y dice cómo reaccionar o contestar", True, f"webchat react {agent_msg['id']} <emoji>" in out)
removed_event = next(e["event_id"] for e in events() if "quitó su reacción" in e["notification_text"])
rc, out, err = cli("event", "show", removed_event, "--body")
check("la de quitar dice cuál quitó", True, f"--- reaction: removed ❤️ on {agent_msg['id']} ---" in out)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
