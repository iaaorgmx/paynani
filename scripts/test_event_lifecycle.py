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

    body_conn = FakeImap()
    event_cli.idle_listener.connect = lambda env: body_conn
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        code = event_cli.run_show(SimpleNamespace(event_id=authorized["event_id"], body=True))
    check("event show --body fetches and prints only after verification",
          code == 0 and body_conn.queries == ["(BODY.PEEK[])"] and "private body" in shown.getvalue())
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
