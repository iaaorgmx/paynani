#!/usr/bin/env python3
"""
Tests for the `reply: never` barrier (R4 de #410, PRD #409 I-3): reply_policy.py,
`send.sh` with a fake himalaya, and `paynani sms send` with a temporary state.
The override needs both --override and --override-by, and each one is logged. An
assertion script, like the rest of this suite.

Nada sale de la máquina: himalaya es un script falso y la orden SMS se queda en
un estado temporal.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import reply_policy  # noqa: E402
from paynani_lib.sms import cli  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402

SEND = ROOT / "scripts" / "send.sh"
passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """| Name | Email | Type | Phone | Rules |
|---|---|---|---|---|
| Julián | julian@example.com | Human | +525511112222 |  |
| Ana | ana@example.com | Human | +525511113333 | ana-9b1c |
| Beto | beto@example.com | Human | +525511114444 | beto-1a2b |
"""


def rules_file(email="normal", sms="normal", enabled="true", channels=("email", "sms")):
    reply = "".join(f"  {c}: {v}\n" for c, v in (("email", email), ("sms", sms)) if c in channels)
    return f"---\nversion: 1\nenabled: {enabled}\n" + (f"reply:\n{reply}" if reply else "") + "---\n\n## General\nx\n"


tmp = Path(tempfile.mkdtemp())
roster = tmp / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
rules_root = tmp
rules = tmp / "rules"
rules.mkdir()
state = tmp / "state"
os.environ["PAYNANI_RULES"] = str(rules)


def write_rules(name, text):
    (rules / f"{name}.md").write_text(text, encoding="utf-8")


# --- blocked() -----------------------------------------------------------------
write_rules("ana-9b1c", rules_file(email="never", channels=("email",)))
write_rules("beto-1a2b", rules_file(sms="never", channels=("sms",)))
b = reply_policy.blocked(roster, "email", ["ANA@example.com", "beto@example.com", "julian@example.com"])
check("email: sólo Ana (reply.email: never), sin distinguir mayúsculas",
      [("ANA@example.com", "Ana", "rules/ana-9b1c.md")], [(i["recipient"], i["name"], i["rules"]) for i in b])
b = reply_policy.blocked(roster, "sms", ["+525511114444", "5511113333"])
check("sms: sólo Beto, y el número se normaliza", [("+525511114444", "rules/beto-1a2b.md")],
      [(i["recipient"], i["rules"]) for i in b])
check("un destinatario fuera del roster no sale aquí (ya lo rechazó el roster)", [],
      reply_policy.blocked(roster, "email", ["nadie@example.com"]))
write_rules("ana-9b1c", rules_file(email="never", enabled="false", channels=("email",)))
check("reglas apagadas (enabled: false) no bloquean", [], reply_policy.blocked(roster, "email", ["ana@example.com"]))
write_rules("default", rules_file(email="never", channels=("email",)))
b = reply_policy.blocked(roster, "email", ["julian@example.com", "ana@example.com"])
check("default.md con email: never bloquea a quien no dice nada, y lo nombra",
      [("julian@example.com", "rules/default.md"), ("ana@example.com", "rules/default.md")],
      [(i["recipient"], i["rules"]) for i in b])
write_rules("ana-9b1c", rules_file(email="normal", channels=("email",)))
check("el contacto con email: normal manda sobre default.md", ["julian@example.com"],
      [i["recipient"] for i in reply_policy.blocked(roster, "email", ["julian@example.com", "ana@example.com"])])
(rules / "default.md").unlink()
write_rules("ana-9b1c", "## sin cabecera\n")
check("un archivo de reglas inválido no bloquea (como sin reglas)", [],
      reply_policy.blocked(roster, "email", ["ana@example.com"]))
blocked_, problems = reply_policy.check(roster, "email", ["ana@example.com"])
check("pero check() lo dice, con el reason de parse y a qué cae",
      [("ana@example.com", "rules/ana-9b1c.md", "header: header_missing", "normal")],
      [(p["recipient"], p["file"], p["reason"], p["fallback"]) for p in problems])
check("warning_lines: WARNING con el archivo, el motivo y a qué cae", True,
      reply_policy.warning_lines("email", problems)[0].startswith(
          "WARNING: rules/ana-9b1c.md is invalid (header: header_missing); reply.email policy for ana@example.com falls back to normal"))
write_rules("default", rules_file())
check("con default.md válido, cae a default.md", "rules/default.md",
      reply_policy.check(roster, "email", ["ana@example.com"])[1][0]["fallback"])
(rules / "ana-9b1c.md").unlink()
check("Rules apunta a un archivo que no está -> missing", ["missing"],
      [p["reason"] for p in reply_policy.check(roster, "email", ["ana@example.com"])[1]])
write_rules("default", "---\nversion: 1\nenabled: true\nreply:\nemail: never\n---\n")
check("default.md roto (sangría) -> problema para cada destinatario, cae a normal",
      [("julian@example.com", "rules/default.md", "normal")],
      [(p["recipient"], p["file"], p["fallback"]) for p in reply_policy.check(roster, "email", ["julian@example.com"])[1]])
check("sin problemas, check() no dice nada", [], reply_policy.check(roster, "email", ["nadie@example.com"])[1])
(rules / "default.md").unlink()
write_rules("ana-9b1c", rules_file(email="never", channels=("email",)))

# --- override_problem -----------------------------------------------------------
check("sin override: nada que objetar", None, reply_policy.override_problem(None, None))
check("--override sin --override-by", True, "--override-by" in (reply_policy.override_problem("x", None) or ""))
check("--override-by sin --override", True, "--override " in (reply_policy.override_problem(None, "x") or "") or
      "--override is" in (reply_policy.override_problem(None, "x") or ""))
check("un override vacío no vale", True, reply_policy.override_problem("  ", "Julián") is not None)
check("un override de varias líneas no vale", True, reply_policy.override_problem("a\nb", "Julián") is not None)

# --- send.sh ------------------------------------------------------------------------
bin_dir = tmp / "bin"
bin_dir.mkdir()
himalaya_log = tmp / "himalaya.log"
fake = bin_dir / "himalaya"
fake.write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {himalaya_log}
if [ "$1" = "--version" ]; then printf 'himalaya v2.1.0\\n'; exit 0; fi
cat > /dev/null
exit 0
""")
fake.chmod(0o755)
env_file = tmp / ".env"
env_file.write_text("AGENT_EMAIL_ACCOUNT=agente@example.com\nAGENT_EMAIL_FROM_NAME=Agente\n")
config = tmp / "himalaya.toml"
config.write_text('[accounts.paynani]\nemail = "agente@example.com"\n[accounts.paynani.smtp]\nserver = "smtps://smtp.example:465"\n')
body = tmp / "body.txt"
body.write_text("hola\n")
env = os.environ.copy()
env.update({"PATH": f"{bin_dir}:{env.get('PATH', '')}", "ROSTER": str(roster), "ENV_FILE": str(env_file),
            "HIMALAYA_CONFIG": str(config), "PAYNANI_RULES": str(rules), "PAYNANI_STATE": str(state)})


def send(*args):
    himalaya_log.unlink(missing_ok=True)
    run = subprocess.run([str(SEND), *args, "asunto", str(body)], text=True, capture_output=True, env=env)
    calls = himalaya_log.read_text() if himalaya_log.exists() else ""
    return run, calls


overrides = state / reply_policy.OVERRIDES_LOG
run, calls = send("--dry-run", "ana@example.com")
check("send.sh: reply.email: never -> exit 2, y dice qué archivo", (2, True),
      (run.returncode, "reply.email: never in rules/ana-9b1c.md" in run.stderr))
check("send.sh: el rechazo explica el override y quién puede pedirlo", True,
      "--override-by" in run.stderr and "never because the message" in run.stderr)
run, calls = send("ana@example.com")
check("send.sh: sin dry-run tampoco manda nada", (2, False), (run.returncode, "smtp" in calls))
run, calls = send("--cc", "ana@example.com", "julian@example.com")
check("send.sh: también por --cc", 2, run.returncode)
run, calls = send("--dry-run", "beto@example.com")
check("send.sh: reply.sms: never no frena el correo", 0, run.returncode)
write_rules("beto-1a2b", "---\nversion: 1\nenabled: si\n---\n")
run, calls = send("--dry-run", "beto@example.com")
check("send.sh: un archivo de reglas inválido avisa en stderr y sigue", (0, True),
      (run.returncode, "WARNING: rules/beto-1a2b.md is invalid (header.enabled: value)" in run.stderr))
write_rules("beto-1a2b", rules_file(sms="never", channels=("sms",)))
run, calls = send("--dry-run", "nadie@example.com")
check("send.sh: el roster sigue primero", (2, True), (run.returncode, "is not in" in run.stderr))
run, calls = send("--override", "Julián lo pidió en su terminal", "ana@example.com")
check("send.sh: --override sin --override-by -> exit 1, nada sale", (1, False), (run.returncode, "smtp" in calls))
run, calls = send("--dry-run", "--override", "Julián lo pidió", "--override-by", "Julián (terminal)", "ana@example.com")
check("send.sh: override en dry-run pasa y no se registra", (0, False), (run.returncode, overrides.exists()))
run, calls = send("--override", "Julián lo pidió", "--override-by", "Julián (terminal)", "ana@example.com")
lines = [json.loads(line) for line in overrides.read_text(encoding="utf-8").splitlines()] if overrides.exists() else []
check("send.sh: override manda", (0, True), (run.returncode, "smtp send" in calls or "send" in calls))
check("send.sh: el override queda en el log con quién, por qué, a quién y qué barrera",
      [("send.sh", "email", "reply.email: never", "ana@example.com", "rules/ana-9b1c.md", "Julián (terminal)",
        "Julián lo pidió")],
      [(l["tool"], l["channel"], l["barrier"], l["recipient"], l["rules"], l["by"], l["reason"]) for l in lines])
check("send.sh: el override se ve en stderr", True, "OVERRIDE: writing to ana@example.com" in run.stderr)

# --- paynani sms send --------------------------------------------------------------
store = store_mod.Store(state)
store.save_device({"device_id": "d_test01", "token_sha256": "x", "connected": True})
cli._store = lambda: store
cli.paths.roster = lambda: roster
cli.paths.state_dir = lambda: state


def sms(number, override=None, override_by=None):
    out, err = io.StringIO(), io.StringIO()
    args = SimpleNamespace(number=number, text=["hola"], wait=0, ttl=15, sim=None, override=override,
                           override_by=override_by)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.run_send(args)
    return code, out.getvalue(), err.getvalue()


orders = state / "sms" / "orders.jsonl"
code, out, err = sms("+525511114444")
check("sms send: reply.sms: never -> exit 2 sin orden", (2, True, False),
      (code, "reply.sms: never in rules/beto-1a2b.md" in err, orders.exists()))
code, out, err = sms("+525511114444", override="Julián lo pidió por SMS", override_by=None)
check("sms send: --override sin --override-by -> rechazado sin orden", (2, False), (code, orders.exists()))
write_rules("ana-9b1c", "## roto\n")
code, out, err = sms("+525511113333")
check("sms send: un archivo de reglas inválido avisa en stderr", True,
      "WARNING: rules/ana-9b1c.md is invalid" in err)
write_rules("ana-9b1c", rules_file(email="never", channels=("email",)))
code, out, err = sms("+525511113333")
check("sms send: reply.email: never no frena el SMS", True, code != 2 or "never" not in err)
before = len(overrides.read_text(encoding="utf-8").splitlines())
code, out, err = sms("+525511114444", override="Julián lo pidió por SMS", override_by="Julián (SMS del dueño)")
after = [json.loads(line) for line in overrides.read_text(encoding="utf-8").splitlines()]
check("sms send: con override no se rechaza por la regla", True, "reply.sms: never in" not in err.split("OVERRIDE")[0])
check("sms send: con override se encola la orden", True, "queued for +525511114444" in out)
check("sms send: el override queda en el log", (before + 1, "paynani sms send", "sms", "+525511114444",
                                                  "Julián (SMS del dueño)", "rules/beto-1a2b.md"),
      (len(after), after[-1]["tool"], after[-1]["channel"], after[-1]["recipient"], after[-1]["by"], after[-1]["rules"]))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
