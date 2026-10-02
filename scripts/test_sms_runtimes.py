#!/usr/bin/env python3
"""
SMS and call events reach the runtimes like mail does (SRV-6, SMS_GATEWAY.md §6).
An assertion script, like the rest of this suite.

The adapters are generic over `notification_text`; this pins the places that were
written for mail only: the Claude Code spool line, the "still unattended" list
the SessionStart hook prints, and the standing rule in AGENTS.md.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "scripts"))

import event as ev  # noqa: E402
import session_start  # noqa: E402
from adapters import claudecode  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


sms = ev.sms_event(device_id="d_abc123", message_id="a" * 64, e164="+525511112222", raw_sender="55 1111 2222",
                   sender_name="Ana López", text="¿tienen mesa para 4?", sent_at="", roster_match=True,
                   local_time="03:09:45")
missed = ev.call_event(kind=ev.CALL_MISSED, device_id="d_abc123", call_id="c" * 64, e164="+525511112222",
                       raw_caller="55 1111 2222", caller_name="Ana López", started_at="", roster_match=True,
                       local_time="10:02:00")
answered = ev.call_event(kind=ev.CALL_ANSWERED, device_id="d_abc123", call_id="e" * 64, e164="+525511112222",
                         raw_caller="55 1111 2222", caller_name="Ana López", started_at="", roster_match=True,
                         local_time="10:05:00", duration_s=125)

# --- Claude Code: the watcher shows exactly the journal's line -------------------
tmp = Path(tempfile.mkdtemp())
os.environ.pop("PAYNANI_CLAUDE_MODE", None)
with mock.patch.object(claudecode, "_state_dir", lambda: tmp / "state"):
    results = [claudecode.deliver(e) for e in (sms, missed, answered)]
    spool = claudecode.spool_path().read_text(encoding="utf-8").splitlines()
check("claudecode: SMS y llamadas se aceptan", [True, True, True], [r.ok for r in results])
check("claudecode: cada evento es una línea del spool, igual que su notification_text",
      [e["notification_text"] for e in (sms, missed, answered)], spool)
check("la línea del SMS trae la etiqueta roster, el remitente, el extracto y el comando", True,
      all(part in spool[0] for part in ("[sms 03:09:45, roster]", "Ana López +525511112222", "¿tienen mesa para 4?",
                                         f"scripts/paynani event show {sms['event_id']}")))
check("la llamada contestada dice la duración", True, "2 min 5 s" in spool[2])

# --- "todavía sin atender" (SessionStart) --------------------------------------
check("unattended_line: un SMS dice SMS, no deja un guion colgado", True,
      session_start.unattended_line(sms["event_id"], sms).endswith("Ana López <+525511112222> — SMS"))
check("unattended_line: llamada perdida y contestada", ("llamada perdida", "llamada contestada"),
      tuple(session_start.unattended_line(e["event_id"], e).rsplit(" — ", 1)[1] for e in (missed, answered)))
mail = ev.mail_event(account="a@x", mailbox="INBOX", uidvalidity=1, uid=2, sender_name="Dulce", sender_address="dulce@example.com",
                     subject="haz algo", sent_at="", roster_match=True, notification_text="[mail 12:00:00, roster] Dulce — haz algo")
check("unattended_line: el correo sigue igual (con su asunto)", True,
      session_start.unattended_line(mail["event_id"], mail).endswith("Dulce <dulce@example.com> — haz algo"))

# --- la regla permanente del agente ------------------------------------------------
rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
check("AGENTS.md explica la etiqueta roster del SMS y de las llamadas", True,
      all(part in rules for part in ("[sms 03:09:45, roster]", "event show <id> --body", "sms send <number>",
                                      "[llamada perdida", "exit 3", "sms.gateway.offline")))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
