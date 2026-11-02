#!/usr/bin/env python3
"""
Tests for `paynani webchat send | typing | thread` and `event show wc:… --body`
(#648 W-2, WEBCHAT.md §6). An assertion script, like the rest of this suite.

Corre la CLI real en un subproceso con PAYNANI_STATE en una carpeta temporal. Nada
sale de la máquina y la instalación real no se toca.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import ledger  # noqa: E402
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


def cli(*argv, stdin=None):
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "paynani"), *argv], input=stdin,
                          capture_output=True, text=True, env=ENV, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


def state_of(event_id):
    return ledger.latest(STATE / "lifecycle.jsonl").get(event_id, {}).get("state")


# --- el dueño escribe dos veces; el agente contesta una ---------------------------------
first = store.append("owner", "¿Cómo vamos?", [("foto.png", PNG)], owner=OWNER, state_dir=STATE)
second = store.append("owner", "Y otra cosa", [], owner=OWNER, state_dir=STATE)
check("los dos eventos quedan observed", ("observed", "observed"),
      (state_of(first["event_id"]), state_of(second["event_id"])))

rc, out, err = cli("event", "show", first["event_id"])
shown = json.loads(out)
check("event show wc: sin --body: 0, el sobre y sin cuerpo", (0, "webchat.received", False, False),
      (rc, shown.get("event_type"), "verified body" in out, str(STATE) in out))
check("event show trae el ciclo de vida", True, any(r.get("state") == "observed" for r in shown.get("lifecycle", [])))
rc, out, err = cli("event", "show", first["event_id"], "--body")
check("--body: 0 y el texto completo", (0, True), (rc, "--- verified body ---\n¿Cómo vamos?" in out))
photo = store.file_path(first["files"][0]["ref"], state_dir=STATE)[0]
check("--body da la ruta local de la foto", True, str(photo) in out)
check("y dice cómo contestar", True, "scripts/paynani webchat send" in out)
rc, out, err = cli("event", "show", "wc:" + "0" * 32, "--body")
check("un wc: que no existe: 1", 1, rc)

rc, out, err = cli("webchat", "typing", "--seconds", "30")
check("typing: 0 y «escribiendo…»", (0, True), (rc, store.is_typing(state_dir=STATE)))
rc, out, err = cli("webchat", "send", "Vamos", "bien")
check("send con texto: 0 y w_… sent", (0, True), (rc, out.startswith("w_") and out.rstrip().endswith("\tsent")))
last = store.messages(state_dir=STATE)[-1]
check("el mensaje del agente se guarda como out/agent", ("out", "agent", "Vamos bien"),
      (last["dir"], last["by"], last["text"]))
check("send quita «escribiendo…»", False, store.is_typing(state_dir=STATE))
check("los dos webchat.received quedan replied", ("replied", "replied"),
      (state_of(first["event_id"]), state_of(second["event_id"])))
detail = ledger.latest(STATE / "lifecycle.jsonl")[first["event_id"]]
check("con el id de la respuesta y runtime webchat", (last["id"], "webchat"),
      (detail.get("detail"), detail.get("runtime")))

# Un evento que el agente ya cerró no se vuelve a tocar.
third = store.append("owner", "gracias", [], owner=OWNER, state_dir=STATE)
ledger.transition(STATE / "lifecycle.jsonl", third["event_id"], "handled")
cli("webchat", "send", "De nada")
check("un evento handled sigue handled", "handled", state_of(third["event_id"]))

# --- stdin y --file ------------------------------------------------------------------
rc, out, err = cli("webchat", "send", stdin="desde stdin\n")
check("sin texto lee stdin", (0, "desde stdin"), (rc, store.messages(state_dir=STATE)[-1]["text"]))
outbox = STATE / "webchat" / "outbox"
outbox.mkdir(parents=True, exist_ok=True)
(outbox / "reporte.png").write_bytes(PNG)
rc, out, err = cli("webchat", "send", "el reporte", "--file", str(outbox / "reporte.png"))
sent = store.messages(state_dir=STATE)[-1]
check("--file de outbox/: 0, con el archivo", (0, ["reporte.png"]), (rc, [f["name"] for f in sent["files"]]))
outside = tmp / "fuera.png"
outside.write_bytes(PNG)
before = len(store.messages(limit=100, state_dir=STATE))
rc, out, err = cli("webchat", "send", "x", "--file", str(outside))
check("--file fuera de outbox/: 2 y no guarda nada", (2, before, True),
      (rc, len(store.messages(limit=100, state_dir=STATE)), "outbox" in err))
link = outbox / "atajo.png"
link.symlink_to(outside)
rc, out, err = cli("webchat", "send", "x", "--file", str(link))
check("un symlink en outbox/ que apunta afuera también: 2", 2, rc)
(outbox / "mentira.pdf").write_bytes(PNG)
rc, out, err = cli("webchat", "send", "x", "--file", str(outbox / "mentira.pdf"))
check("un PNG llamado .pdf: 2, bad_type", (2, True), (rc, "bad_type" in err))
rc, out, err = cli("webchat", "send", "x" * 4001)
check("más de 4000 caracteres: 2, too_long", (2, True), (rc, "too_long" in err))

# --- --stream -------------------------------------------------------------------------
store.append("owner", "cuéntame", [], owner=OWNER, state_dir=STATE)
proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "paynani"), "webchat", "send", "--stream"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
proc.stdin.write("Primera parte, ".encode())
proc.stdin.flush()
seen = None
for _ in range(50):
    time.sleep(0.1)
    seen = store.draft(state_dir=STATE)
    if seen:
        break
check("--stream deja el borrador mientras escribe", "Primera parte, ", (seen or {}).get("text"))
check("con borrador, «escribiendo…»", True, store.is_typing(state_dir=STATE))
time.sleep(0.4)
proc.stdin.write("ñandú y segunda.".encode())
proc.stdin.flush()
grown = None
for _ in range(50):
    time.sleep(0.1)
    grown = store.draft(state_dir=STATE)
    if grown and grown["text"].endswith("segunda."):
        break
check("el borrador es el texto completo, no sólo lo nuevo", "Primera parte, ñandú y segunda.",
      (grown or {}).get("text"))
out, err = proc.communicate(timeout=30)
check("al cerrar stdin: 0 y el mensaje final", (0, "Primera parte, ñandú y segunda."),
      (proc.returncode, store.messages(state_dir=STATE)[-1]["text"]))
check("y el borrador desaparece", None, store.draft(state_dir=STATE))
rc, out, err = cli("webchat", "send", "--stream", stdin="")
check("--stream vacío: 2, sin mensaje y sin borrador", (2, None), (rc, store.draft(state_dir=STATE)))
rc, out, err = cli("webchat", "send", "--stream", "texto")
check("--stream con texto en la línea: 2", 2, rc)

# --- borrador viejo, typing --off, thread ------------------------------------------------
store.draft_set("a medias", state_dir=STATE)
draft_path = STATE / "webchat" / "draft.json"
check("draft.json es 0600", 0o600, draft_path.stat().st_mode & 0o777)
old = json.loads(draft_path.read_text())
old["at"] = "2020-01-01T00:00:00Z"
draft_path.write_text(json.dumps(old))
check("un borrador de hace más de 10 min cuenta como None", None, store.draft(state_dir=STATE))
store.draft_clear(state_dir=STATE)

cli("webchat", "typing")
rc, out, err = cli("webchat", "typing", "--off")
check("typing --off: 0 y sin «escribiendo…»", (0, False), (rc, store.is_typing(state_dir=STATE)))
rc, out, err = cli("webchat", "thread", "--limit", "3")
check("thread: los 3 últimos, con flechas", (0, 3, True), (rc, len(out.strip().splitlines()), "→" in out))
rc, out, err = cli("webchat", "thread", "--json")
data = json.loads(out)
check("thread --json: mensajes y typing, sin el tipo interno", (True, False, True),
      (isinstance(data["messages"], list), data["typing"],
       all("type" not in f for m in data["messages"] for f in m["files"])))
rc, out, err = cli("webchat", "thread")
check("thread marca las fotos", True, "[foto: foto.png]" in out)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
