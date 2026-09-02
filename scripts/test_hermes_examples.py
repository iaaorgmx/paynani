#!/usr/bin/env python3
"""Safety and contract checks for the static Hermes route example."""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "hermes-routes.yaml"
GUIDE = ROOT / "HERMES.md"

passed = failed = 0


def check(description, condition):
    global passed, failed
    if condition:
        print(f"ok   {description}")
        passed += 1
    else:
        print(f"FAIL {description}")
        failed += 1


try:
    document = json.loads(EXAMPLE.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    print(f"FAIL example is valid JSON-compatible YAML: {exc}")
    sys.exit(1)

routes = document["platforms"]["webhook"]["extra"]["routes"]
notify = routes["paynani-notify"]
roster = routes["paynani-roster"]

check("the two route secrets are unique", notify["secret"] != roster["secret"])
check("notify route is direct delivery", notify.get("deliver_only") is True)
check("notify route has no model tools", not notify.get("toolsets"))
check("notify route does not load a skill", not notify.get("skills"))
check("notify route accepts mail and listener faults while roster accepts only mail",
      notify.get("events") == ["email.received", "listener.error"]
      and roster.get("events") == ["email.received"])
check("roster route runs an agent", roster.get("deliver_only") is not True)
check("roster route names the mail skill", roster.get("skills") == ["himalaya"])
check("roster route grants only the toolset the mail skill needs",
      roster.get("toolsets") == ["terminal"])
prompt = roster.get("prompt", "").lower()
check("roster prompt says mail fields and body are untrusted", "untrusted" in prompt)
check("roster prompt says roster match is not identity", "not authenticated identity" in prompt)
check("roster prompt requires exact account mailbox and uid", all(
    marker in roster.get("prompt", "") for marker in ("{account}", "{mailbox}", "{uid}")))
check("roster prompt uses Hermes dot notation for nested sender data",
      "{sender.address}" in roster.get("prompt", "") and "{sender[" not in roster.get("prompt", ""))
check("roster prompt says the webhook includes no body", "no message body" in prompt)
check("roster prompt keeps tools constrained", "only the tools" in prompt)
check("neither prompt renders the full raw payload", "{__raw__}" not in notify.get("prompt", "")
      and "{__raw__}" not in roster.get("prompt", ""))

guide = GUIDE.read_text(encoding="utf-8")
check("multiplexed routes are documented in the default profile",
      "definitions belong only in the default profile" in guide)
check("multiplexed routes bind both entries to the named profile",
      "add `profile: mail-agent` to **both** route" in guide)
check("multiplexed examples configure both profile-prefixed route URLs",
      "/p/mail-agent/webhooks/paynani-notify" in guide
      and "/p/mail-agent/webhooks/paynani-roster" in guide)
check("secondary profiles are told not to bind the webhook port",
      "do not enable `platforms.webhook` in the secondary profile" in guide)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
