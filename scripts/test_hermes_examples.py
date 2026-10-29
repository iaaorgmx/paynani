#!/usr/bin/env python3
"""Safety and contract checks for the static Hermes route example."""

import json
import pathlib
import re
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
# #582: Hermes answers 200 ignored for an event type a route does not list, and
# the dispatcher holds the whole queue behind it, mail included. So the lists are
# exact, and every event type paynani writes must reach at least the notify route.
NOTIFY_EVENTS = ["email.received", "listener.error", "sms.received", "sms.human_sent",
                 "sms.unseen", "sms.gateway.offline", "sms.gateway.online",
                 "sms.gateway.battery_low", "sms.gateway.battery_ok",
                 "whatsapp.received", "whatsapp.health", "call.missed", "call.answered"]
ROSTER_EVENTS = ["email.received", "sms.received", "sms.human_sent",
                 "whatsapp.received", "call.missed", "call.answered"]
check("notify route accepts every event type, roster only the ones with a sender",
      notify.get("events") == NOTIFY_EVENTS and roster.get("events") == ROSTER_EVENTS)
written = set(re.findall(r'^[A-Z_]+ = "([a-z_]+\.[a-z_.]+)"$',
                         (ROOT / "harness" / "event.py").read_text(encoding="utf-8"), re.M))
check("every event type in harness/event.py is on the notify route (#582)",
      bool(written) and written <= set(NOTIFY_EVENTS))
check("every event type on the roster route is also on the notify route",
      set(ROSTER_EVENTS) <= set(NOTIFY_EVENTS))
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
check("roster prompt names the event type", "{event_type}" in roster.get("prompt", ""))
raw_prompt = roster.get("prompt", "")
check("roster prompt reads texts and WhatsApp messages with event show --body",
      "For sms.received, sms.human_sent and whatsapp.received: read it only with "
      "scripts/paynani event show {event_id} --body." in raw_prompt)
# A call has no body: `event show --body` exits 2 for it (test_sms_gateway.py,
# test_whatsapp_service.py), so the prompt must send calls to plain event show.
check("roster prompt reads calls with event show and without --body",
      "For call.missed and call.answered: a call has no body; read it only with "
      "scripts/paynani event show {event_id}, without --body." in raw_prompt)
check("roster prompt never pairs a call type with --body in the same sentence",
      not any("call." in sentence and "--body" in sentence.replace("without --body", "")
              for sentence in raw_prompt.split(". ")))
check("roster prompt forbids writing first and linking WhatsApp",
      "never write first" in prompt and "never run paynani whatsapp link or unlink" in prompt)
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
