#!/usr/bin/env python3
"""
Tests for replies in Webchat (PRD #685 F2, the FR-14 contract on #685): `store.append(...,
reply_to=)`, the quote saved in the message, the notice to the agent (FR-16),
`webchat send --reply-to`, `webchat thread` and `event show wc:… --body`.

The store and the CLI run on a temporary PAYNANI_STATE. The agent's name comes from a
patched `envfile.read_env`, never from the real .env.
"""
from __future__ import annotations

import inspect
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
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00"
       b"\x00\x00IEND\xaeB`\x82")
envfile.read_env = lambda: {"AGENT_EMAIL_FROM_NAME": "Agente Prueba"}


def events():
    path = STATE / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cli(*argv):
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "paynani"), *argv],
                          capture_output=True, text=True, env=ENV, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


# --- la web lo detecta -------------------------------------------------------------------
check("append acepta reply_to", True, "reply_to" in inspect.signature(store.append).parameters)
check("webchat_pages.replies ve el almacén del núcleo", True, webchat_pages.replies(store))

# --- el agente escribe; el dueño le responde citándolo ----------------------------------
agent_msg = store.append("agent", "¿Te mando el reporte de hoy\no el de la semana?", [], state_dir=STATE)
check("un mensaje sin cita no trae reply_to", False, "reply_to" in agent_msg)
reply = store.append("owner", "El de la semana", [], owner=OWNER, reply_to=agent_msg["id"], state_dir=STATE)
check("la cita lleva el ref del original", agent_msg["id"], reply["reply_to"]["ref"])
check("la cita a un mensaje del agente lleva su nombre", "Agente Prueba", reply["reply_to"]["name"])
check("el extracto va en una línea", "¿Te mando el reporte de hoy o el de la semana?", reply["reply_to"]["excerpt"])
check("missing es false", False, reply["reply_to"]["missing"])
stored = store.messages(state_dir=STATE)[-1]
check("la cita queda guardada en el hilo", reply["reply_to"], stored.get("reply_to"))

notice = events()[-1]["notification_text"]
check("el aviso dice que es una respuesta (FR-16)", True,
      "(PaynaniWeb) (respondiendo a «¿Te mando el reporte de hoy o el de la…»): El de la semana" in notice)
check("el aviso sigue en una sola línea", 1, len(notice.splitlines()))

# --- el dueño cita su propio mensaje y una foto -----------------------------------------
photo = store.append("owner", "", [("foto.png", PNG)], owner=OWNER, state_dir=STATE)
own = store.append("owner", "Esta es la de ayer", [], owner=OWNER, reply_to=photo["id"], state_dir=STATE)
check("la cita a un mensaje del dueño lleva su nombre", "Dueña Prueba", own["reply_to"]["name"])
check("una foto sin texto se cita como 📷", "📷", own["reply_to"]["excerpt"])
check("un documento se cita con su nombre", "📄 a.pdf",
      store.excerpt_of({"files": [{"kind": "document", "name": "a.pdf"}]}))
check("el extracto se corta en 100", 100, len(store.excerpt_of({"text": "x" * 300})))

# --- un id con forma pero que no está: sale sin cita, no se pierde (FR-7) ---------------
gone = store.append("owner", "¿Y esto?", [], owner=OWNER, reply_to="w_" + "0" * 32, state_dir=STATE)
check("un original que no está deja missing", True, gone["reply_to"]["missing"])
check("y sin ref", None, gone["reply_to"]["ref"])
check("el mensaje se guardó", gone["id"], store.messages(state_dir=STATE)[-1]["id"])
check("el aviso no inventa una cita", False, "respondiendo a" in events()[-1]["notification_text"])

# --- un reply_to sin forma se rechaza ----------------------------------------------------
for bad in ("tg:123", "w_xyz", "../w_" + "a" * 32, ""):
    try:
        store.append("owner", "hola", [], owner=OWNER, reply_to=bad, state_dir=STATE)
        check(f"reply_to {bad!r} se rechaza", "bad_reply", None)
    except store.Rejected as exc:
        check(f"reply_to {bad!r} se rechaza", "bad_reply", exc.code)

# --- la CLI --------------------------------------------------------------------------------
rc, out, err = cli("webchat", "send", "--reply-to", reply["id"], "Va, te lo mando en un rato")
check("webchat send --reply-to sale bien", 0, rc)
check("y dice a quién cita", True, f"reply_to {reply['id']}" in out)
last = store.messages(state_dir=STATE)[-1]
check("el mensaje del agente guarda la cita", reply["id"], (last.get("reply_to") or {}).get("ref"))
check("con el nombre del dueño", "Dueña Prueba", (last.get("reply_to") or {}).get("name"))

rc, out, err = cli("webchat", "send", "--reply-to", "tg:1", "hola")
check("--reply-to sin forma de w_ da 2", 2, rc)
check("y explica qué esperaba", True, "w_" in err)

rc, out, err = cli("webchat", "thread", "--limit", "20")
check("webchat thread muestra los ids, para --reply-to", True, reply["id"] in out)
check("y marca las respuestas", True, "(respondiendo a «El de la semana»)" in out)
check("y las que salieron sin cita", True, "(se mandó sin cita)" in out)

rc, out, err = cli("event", "show", reply["event_id"], "--body")
check("event show --body sale bien", 0, rc)
check("imprime el texto citado completo arriba", True,
      f"--- in reply to Agente Prueba ({agent_msg['id']}) ---\n¿Te mando el reporte de hoy\no el de la semana?" in out)
check("la cita va antes del cuerpo", True, out.index("--- in reply to") < out.index("--- verified body ---"))
check("y dice cómo citar este mensaje", True, f"--reply-to {reply['id']}" in out)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
