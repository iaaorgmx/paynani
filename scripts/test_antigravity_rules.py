#!/usr/bin/env python3
"""
Antigravity CLI: the standing rule in ~/.gemini/GEMINI.md and the permission
rules in ~/.gemini/antigravity-cli/settings.json (#749 FR-6, FR-7, T6).
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "paynani_lib"))
import antigravity_rules  # noqa: E402
import harness_rules  # noqa: E402

passed = failed = 0


def check(desc, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {desc}")
    else:
        failed += 1
        print(f"FAIL {desc}\n     expected {expected!r}\n     got      {actual!r}")


def quiet(*_args, **_kwargs):
    pass


# --- the block -------------------------------------------------------------
block = antigravity_rules.block(ROOT)
check("the block starts and ends with the markers", (True, True),
      (block.startswith(antigravity_rules.START + "\n"), block.endswith(antigravity_rules.END + "\n")))
check("it explains the roster tag", True, "`, roster]`" in block)
check("it names this clone's commands", True,
      f"{ROOT}/scripts/paynani event show" in block and f"{ROOT}/scripts/send.sh" in block)
check("it says how to close a notice", True, f"{ROOT}/scripts/paynani event mark <event_id> handled" in block)
check("every channel has its send command", True,
      all(f"paynani {c} send" in block for c in ("sms", "whatsapp", "telegram", "webchat")))
check("it warns that a refused command did not happen", True, "refused did not happen" in block)
check("it never mentions skipping permissions", False, "dangerously" in block)

# --- install / check / uninstall keep the operator's file -------------------
with tempfile.TemporaryDirectory() as tmp:
    target = Path(tmp) / "GEMINI.md"
    check("absent before install", "absent", antigravity_rules.state(target))
    original = "# My own rules\n\nAlways answer in Spanish.\n"
    target.write_text(original)
    antigravity_rules.rules.install(target, wanted=block)
    text = target.read_text()
    check("present after install", "present", antigravity_rules.state(target, root=ROOT))
    check("the operator's text is kept", True, text.startswith(original))
    check("a backup of the first version is left", original, (Path(tmp) / "GEMINI.md.paynani.bak").read_text())
    antigravity_rules.uninstall(target)
    check("uninstall leaves the file as it was", original, target.read_text())

# --- harness_rules: the plan shows both, and writes nothing on «no» ----------
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    steps = harness_rules.plan("antigravity", ROOT, home=home)
    check("the plan has five permission rules and the standing rule", 6, len(steps))
    check("the permission rules go in antigravity-cli/settings.json", True,
          all(str(harness_rules.antigravity_settings(home)) in s for s in steps[:5]))
    check("the last step names GEMINI.md", True, str(harness_rules.antigravity_rules_file(home)) in steps[5])

    shown = []
    ok, detail = harness_rules.apply("antigravity", ROOT, home=home, confirm=lambda _q: "n", out=shown.append)
    check("«no»: ok, and skipped", (True, "harness rules: skipped by the owner"), (ok, detail))
    check("«no»: the rule was shown word for word before asking", True,
          antigravity_rules.START in "\n".join(shown) and f"{ROOT}/scripts/send.sh" in "\n".join(shown))
    check("«no»: nothing written", (False, False),
          (harness_rules.antigravity_settings(home).exists(), harness_rules.antigravity_rules_file(home).exists()))

# --- «yes»: both written, other settings kept, then nothing left to do -------
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    settings = harness_rules.antigravity_settings(home)
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "gemini-x", "permissions": {"allow": ["command(regex:^ls$)"]}}, indent=4))
    ok, detail = harness_rules.apply("antigravity", ROOT, home=home, confirm=lambda _q: "y", out=quiet)
    check("«yes»: ok", True, ok)
    data = json.loads(settings.read_text())
    check("other keys and rules are kept", ("gemini-x", "command(regex:^ls$)"),
          (data["model"], data["permissions"]["allow"][0]))
    check("the five paynani rules are added", harness_rules.antigravity_rules(ROOT), data["permissions"]["allow"][1:])
    check("the file keeps its indentation", True, '\n    "model"' in settings.read_text())
    check("the standing rule is in GEMINI.md", "present",
          antigravity_rules.state(harness_rules.antigravity_rules_file(home), root=ROOT))
    check("a second run has nothing to add", [], harness_rules.plan("antigravity", ROOT, home=home))
    ok, detail = harness_rules.apply("antigravity", ROOT, home=home, confirm=lambda _q: "y", out=quiet)
    check("and says so", (True, "harness rules: already in place"), (ok, detail))

# --- the permission patterns match only the two scripts ----------------------
paynani, send, _watch = harness_rules.scripts(ROOT)
patterns = [re.compile(r[len("command(regex:"):-1]) for r in harness_rules.antigravity_rules(ROOT)]


def allowed(command):
    return any(p.search(command) for p in patterns)


check("scripts/paynani with arguments is allowed", True, allowed(f"{paynani} event mark imap:INBOX:1:2 handled"))
check("scripts/send.sh with arguments is allowed", True, allowed(f"{send} a@b.c Hola body.txt"))
check("scripts/paynani_old is not", False, allowed(f"{paynani}_old event mark x"))
check("a command that only mentions the path is not", False, allowed(f"rm -rf / ; {paynani} event mark x"))
check("session_watch.sh is not (agy has no Monitor to arm it)", False, allowed(f"bash {_watch} state"))

# --- #775: restarting paynani's units at the end of an upgrade -----------------
for command in ("systemctl --user restart paynani-dispatch",
                "systemctl --user restart paynani-dispatch.service",
                "systemctl --user status paynani-web",
                "systemctl --user restart paynani-idle.service paynani-dispatch.service paynani-sms.service",
                "systemctl --user restart paynani-idle@ventas.service"):
    check(f"allowed: {command}", True, allowed(command))
for command in ("systemctl --user stop paynani-dispatch",
                "systemctl --user disable paynani-dispatch",
                "systemctl restart paynani-dispatch",
                "systemctl --user restart sshd",
                "systemctl --user restart paynani-dispatch sshd",
                "systemctl --user restart paynani-dispatch; rm -rf ~",
                "sudo systemctl --user restart paynani-dispatch",
                "systemctl --user restart paynani-evil.service",
                "systemctl --user daemon-reload; rm -rf ~",
                "systemctl --user list-units --all --plain --no-legend '*' | awk '{print $1}' | xargs -r systemctl --user restart",
                "systemctl --user list-units --all --plain --no-legend 'paynani-idle@*.service' | awk '{print $1}' | xargs -r systemctl --user stop"):
    check(f"not allowed: {command}", False, allowed(command))
for command in ("systemctl --user restart paynani-logrotate.timer",
                "systemctl --user daemon-reload"):
    check(f"allowed: {command}", True, allowed(command))

# --- every systemctl line a real upgrade plan prints passes (Iris on #776) -----
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("paynani_upgrade_plan", ROOT / "scripts" / "upgrade_plan.py")
up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(up)
units = [up.LISTENER, up.LISTENER_INSTANCES, up.DISPATCHER, up.SMS_GATEWAY, up.WEB, up.TELEGRAM, up.WHATSAPP]
lines = up.commands({"ok": True, "system": "Linux", "runtime": "antigravity", "reinstall": False,
                     "reinstall_commands": [], "restart_units": units, "restart_runtime": [], "next_session": False})
systemctl_lines = [line for line in lines if line.startswith("systemctl")]
check("the plan has daemon-reload, the named restart and the pattern restarts", True, len(systemctl_lines) >= 3)
for line in systemctl_lines:
    check(f"the plan line passes: {line[:70]}", True, allowed(line))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
