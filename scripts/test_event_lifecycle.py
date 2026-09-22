#!/usr/bin/env python3
"""Acceptance tests for issue #171's event lifecycle and inspection surface."""

import contextlib
import email.message
import io
import pathlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "paynani_lib"))

import dispatch
import event
import event_cli
import ledger
import roster
from adapters import accepted
from adapters import codex

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}")


def envelope(uid, *, address="outsider@example.com", roster_match=False, message_id=""):
    return event.mail_event(
        account="agent@example.com", mailbox="INBOX", uidvalidity="77", uid=uid,
        sender_name="Sender", sender_address=address, subject="Work", sent_at="",
        roster_match=roster_match, notification_text="mail", message_id=message_id,
    )


with tempfile.TemporaryDirectory() as raw:
    tmp = pathlib.Path(raw)
    journal = tmp / "events.jsonl"
    lifecycle = tmp / "lifecycle.jsonl"
    outsider = envelope(1)
    event.append(journal, outsider)

    old_state_dir = event_cli.state_dir
    old_roster_file = event_cli.roster_file
    old_fetch = event_cli.idle_listener.connect
    roster_path = tmp / "roster.md"
    roster_path.write_text("| Name | Email | Type | GitHub |\n|---|---|---|---|\n| Known | known@example.com | Human | known |\n")
    event_cli.state_dir = lambda: tmp
    event_cli.roster_file = lambda: roster_path
    event_cli.idle_listener.connect = lambda env: (_ for _ in ()).throw(AssertionError("network used"))
    stderr = io.StringIO()
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = event_cli.run_show(SimpleNamespace(event_id=outsider["event_id"], body=True))
    check("an unlisted event body is refused", code == 2)
    check("roster rejection happens before any IMAP body fetch", "listener did not record" in stderr.getvalue())
    check("the safe envelope is still shown", outsider["event_id"] in stdout.getvalue())
    ledger.observed(lifecycle, outsider)
    journal.write_text("")
    recovered = event_cli._find(outsider["event_id"])
    check("a compacted journal event resolves from the append-only ledger",
          recovered and recovered["event_id"] == outsider["event_id"])
    observed_row = ledger.history(lifecycle, outsider["event_id"])[0]
    check("the lifecycle ledger stores no rendered mail or body",
          "notification_text" not in observed_row["envelope"] and "body" not in observed_row["envelope"])

    authorized = envelope(9, address="known@example.com", roster_match=True,
                          message_id="<known-9@example.test>")
    event.append(journal, authorized)
    raw_message = email.message.EmailMessage()
    raw_message["From"] = "Known <known@example.com>"
    raw_message["To"] = "Agent <agent@example.com>"
    raw_message["Message-ID"] = "<known-9@example.test>"
    raw_message.set_content("private body")

    class FakeImap:
        def __init__(self):
            self.queries = []

        def select(self, mailbox, readonly=False):
            return "OK", []

        def status(self, mailbox, query):
            return "OK", [b'INBOX (UIDVALIDITY 77)']

        def uid(self, command, uid, query):
            self.queries.append(query)
            return "OK", [(b'9 (UID 9 BODY[] {100}', raw_message.as_bytes())]

        def logout(self):
            return "BYE", []

    env_path = tmp / ".env"
    env_path.write_text("PAYNANI_EMAIL=agent@example.com\n")
    old_env_file = event_cli.env_file
    event_cli.env_file = lambda: env_path
    header_conn = FakeImap()
    event_cli.idle_listener.connect = lambda env: header_conn
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        code = event_cli.run_show(SimpleNamespace(event_id=authorized["event_id"], body=False))
    check("event show verifies the exact roster envelope", code == 0 and "\"envelope_verified\": true" in shown.getvalue())
    check("event show without --body fetches headers only",
          header_conn.queries == ["(BODY.PEEK[HEADER])"] and "private body" not in shown.getvalue())
    shown_data = event_cli.json.loads(shown.getvalue())
    check("event show without --body uses the reverified recipient role",
          shown_data["recipient_role"] == "to")

    recorded_authorized = dict(authorized)
    recorded_authorized["recipient_role"] = "cc"
    journal.write_text("")
    event.append(journal, recorded_authorized)
    header_conn = FakeImap()
    event_cli.idle_listener.connect = lambda env: header_conn
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        code = event_cli.run_show(SimpleNamespace(event_id=authorized["event_id"], body=False))
    shown_data = event_cli.json.loads(shown.getvalue())
    check("event show without --body reports recipient-role disagreement",
          code == 0
          and shown_data["recipient_role"] == "to"
          and shown_data["recipient_role_recorded"] == "cc"
          and shown_data["recipient_role_disagreement"] is True)

    journal.write_text("")
    event.append(journal, authorized)
    body_conn = FakeImap()
    event_cli.idle_listener.connect = lambda env: body_conn
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        code = event_cli.run_show(SimpleNamespace(event_id=authorized["event_id"], body=True))
    check("event show --body fetches and prints only after verification",
          code == 0 and body_conn.queries == ["(BODY.PEEK[])"] and "private body" in shown.getvalue())

    shown_json = shown.getvalue().split("\n--- verified body ---", 1)[0]
    shown_data = event_cli.json.loads(shown_json)
    check("a direct recipient treats the whole verified body as instruction",
          shown_data["recipient_role"] == "to"
          and shown_data["marker_for_me"] is True
          and shown_data["marker_lines"] == [])

    roster_path.write_text(
        "| Name | Email | Type | GitHub |\n|---|---|---|---|\n"
        "| Known | known@example.com | Human | known |\n"
        "| Ocelotl | agent@example.com | AI Agent | ocelotlcodextob |\n"
        "| Ares | ares@example.com | AI Agent | aresclaudetob |\n"
    )
    cc_message = email.message.EmailMessage()
    cc_message["From"] = "Known <known@example.com>"
    cc_message["To"] = "Julian <julian@example.com>"
    cc_message["Cc"] = "Agent <agent@example.com>"
    cc_message["Message-ID"] = "<known-9@example.test>"
    cc_message.set_content(
        "  Ocelotl: run the Codex row\n"
        "AGENT@EXAMPLE.COM: capture the output\n"
        "Ares: this one is not for Ocelotl\n"
    )
    body = event_cli._body_text(cc_message)
    legacy_record = {"account": "agent@example.com"}
    summary = event_cli._marker_summary(legacy_record, cc_message, body)
    check("level 1 matches a roster name followed by a colon",
          "Ocelotl: run the Codex row" in summary["marker_lines"])
    check("level 1 matches the agent address followed by a colon",
          "AGENT@EXAMPLE.COM: capture the output" in summary["marker_lines"])
    check("level 1 ignores another agent's marker",
          "Ares: this one is not for Ocelotl" not in summary["marker_lines"])
    check("level 1 is case-insensitive",
          summary["marker_for_me"] is True and len(summary["marker_lines"]) == 2)

    no_marker = email.message.EmailMessage()
    no_marker["From"] = "Known <known@example.com>"
    no_marker["Cc"] = "Agent <agent@example.com>"
    no_marker.set_content("Please keep this for context.\n")
    summary = event_cli._marker_summary(
        legacy_record, no_marker, event_cli._body_text(no_marker))
    check("copy without a level 1 marker is reported as context, not silent action",
          summary["recipient_role"] == "cc" and summary["marker_for_me"] is False)
    recorded_record = {"account": "agent@example.com", "recipient_role": "to"}
    summary = event_cli._marker_summary(recorded_record, cc_message, body)
    check("verified message recipient_role wins over a recorded journal value",
          summary["recipient_role"] == "cc")
    check("recipient_role disagreement preserves the recorded value",
          summary["recipient_role_recorded"] == "to")
    check("recipient_role disagreement is flagged",
          summary["recipient_role_disagreement"] is True)
    event_cli.env_file = old_env_file
    event_cli.state_dir = old_state_dir
    event_cli.roster_file = old_roster_file
    event_cli.idle_listener.connect = old_fetch

    notifier_roster = tmp / "notifier.md"
    notifier_roster.write_text(
        "| Name | Email | Type | GitHub |\n|---|---|---|---|\n"
        "| Ximena | ximena@example.com | AI Agent | ximenasalazartob |\n\n"
        "## Notifiers\n\n| Address | Header | Column |\n|---|---|---|\n"
        "| notifications@github.com | X-GitHub-Sender | GitHub |\n"
    )
    message = email.message.EmailMessage()
    message["From"] = "notifications@github.com"
    message["X-GitHub-Sender"] = "ximenasalazartob"
    decision = roster.explain_sender(
        message, roster.roster_addresses(notifier_roster),
        roster.roster_entries(notifier_roster), roster.notifiers(notifier_roster),
    )
    check("GitHub notifier attribution is explained as authorized", decision["matched"])
    check("the notifier explanation identifies its declared header", "X-GitHub-Sender" in decision["reason"])

    old_roster_file = event_cli.roster_file
    event_cli.roster_file = lambda: notifier_roster
    rejected_notifier = envelope(10, address="notifications@github.com", roster_match=False)
    rejected_notifier["notifier_headers"] = {"X-GitHub-Sender": "ocelotlcodextob"}
    rejected_decision = event_cli._authorization(rejected_notifier)
    check("event show explains a rejected notifier header value against the roster",
          "X-GitHub-Sender=ocelotlcodextob matches no contact in the github column"
          in rejected_decision["reason"])
    check("event show keeps rejected notifier events with headers unauthorized",
          rejected_decision["matched"] is False)
    legacy_rejected_notifier = envelope(11, address="notifications@github.com", roster_match=False)
    legacy_rejected_decision = event_cli._authorization(legacy_rejected_notifier)
    check("event show does not invent a missing notifier header for rejected legacy events",
          "cannot determine notifier authorization" in legacy_rejected_decision["reason"]
          and "roster.md" in legacy_rejected_decision["reason"])
    check("event show keeps rejected legacy notifier events unauthorized",
          legacy_rejected_decision["matched"] is False)
    event_cli.roster_file = old_roster_file

    first = envelope(2, address="known@example.com", roster_match=True,
                     message_id="<provider-42@example.test>")
    duplicate = envelope(3, address="known@example.com", roster_match=True,
                         message_id="<provider-42@example.test>")
    event.append(journal, first)
    event.append(journal, duplicate)

    class Fake:
        NAME = "fake"

        def __init__(self):
            self.events = []

        def deliver(self, record):
            self.events.append(record["event_id"])
            return accepted()

    fake = Fake()
    old_pace = dispatch.CATCHUP_PACE
    dispatch.CATCHUP_PACE = 0
    dispatch.run_once(fake, journal, tmp / "cursor", ledger_path=lifecycle)
    dispatch.CATCHUP_PACE = old_pace
    check("the provider message is delivered once", fake.events.count(first["event_id"]) == 1)
    check("the provider duplicate is not delivered", duplicate["event_id"] not in fake.events)
    latest = ledger.latest(lifecycle)
    check("the provider duplicate is recorded as suppressed", latest[duplicate["event_id"]]["state"] == "suppressed")
    check("the suppression points to the canonical event", latest[duplicate["event_id"]]["related_event_id"] == first["event_id"])

old_find_binary = codex.find_binary
old_run = codex.subprocess.run
codex.find_binary = lambda: "/bin/codex"
codex.subprocess.run = lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="unknown command")
check("a changed Codex queue CLI is unsupported, not broken",
      codex.queue_contract()["state"] == "unsupported")

def timeout(*args, **kwargs):
    raise subprocess.TimeoutExpired(args[0], 10)

codex.subprocess.run = timeout
check("a nonresponsive advertised Codex CLI is broken", codex.queue_contract()["state"] == "broken")
codex.find_binary = old_find_binary
codex.subprocess.run = old_run

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
