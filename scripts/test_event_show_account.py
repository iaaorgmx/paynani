#!/usr/bin/env python3
"""
`paynani event show` for events of an additional account (#283, part 5 of the
multi-account PRD in #276).

An event from `ventas@` must be read with `ventas@`'s login, checked against
`ventas@`'s roster, and must say which account it came from. The agent's own
account must behave exactly as before. IMAP is faked; what is asserted is which
login the connection was opened with and which roster decided.
"""

import contextlib
import email.message
import io
import json
import pathlib
import sys
import tempfile
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "paynani_lib"))

import event
import event_cli
import ledger

passed = failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}")
        if detail:
            print(detail)


MAIN_ROSTER = "| Name | Email | Type |\n|---|---|---|\n| Metis | metis@example.com | AI Agent |\n"
VENTAS_ROSTER = "| Name | Email | Type |\n|---|---|---|\n| Ana Ruiz | ana@dominio.test | Human |\n"


def message(sender, to, message_id):
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Message-ID"] = message_id
    msg.set_content("cuerpo privado")
    return msg


class FakeImap:
    def __init__(self, raw_message):
        self.raw = raw_message
        self.queries = []

    def select(self, mailbox, readonly=False):
        return "OK", []

    def status(self, mailbox, query):
        return "OK", [b"INBOX (UIDVALIDITY 77)"]

    def uid(self, command, uid, query):
        self.queries.append(query)
        return "OK", [(f"{uid} (UID {uid} BODY[] {{100}}".encode(), self.raw.as_bytes())]

    def logout(self):
        return "BYE", []


def show(tmp, event_id, *, body=True):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = event_cli.run_show(SimpleNamespace(event_id=event_id, body=body))
    return code, out.getvalue(), err.getvalue()


with tempfile.TemporaryDirectory() as raw:
    tmp = pathlib.Path(raw)
    (tmp / "rosters").mkdir()
    (tmp / "roster.md").write_text(MAIN_ROSTER)
    (tmp / "rosters" / "ventas.md").write_text(VENTAS_ROSTER)
    (tmp / ".env").write_text(
        "PAYNANI_EMAIL=agent@example.com\nPAYNANI_PASSWORD=main-secret\n"
        "PAYNANI_ACCOUNT_VENTAS_PASSWORD=ventas-secret\n")
    (tmp / "accounts.json").write_text(json.dumps({"schema_version": 1, "accounts": [{
        "id": "ventas", "email": "ventas@dominio.test",
        "imap": {"host": "mail.dominio.test", "port": 993},
        "smtp": {"host": "mail.dominio.test", "port": 465},
        "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD",
        "roster": "rosters/ventas.md", "mailboxes": ["INBOX"], "enabled": True}]}))

    old = (event_cli.state_dir, event_cli.roster_file, event_cli.env_file, event_cli.idle_listener.connect)
    event_cli.state_dir = lambda: tmp
    event_cli.roster_file = lambda: tmp / "roster.md"
    event_cli.env_file = lambda: tmp / ".env"
    opened = []

    def connect_with(conn):
        def connect(env):
            opened.append(dict(env))
            return conn
        return connect

    try:
        journal = tmp / "events.jsonl"

        # -- an event of the additional account, from someone on ITS roster -------
        ventas_event = event.mail_event(
            account="ventas@dominio.test", account_id="ventas", mailbox="INBOX", uidvalidity="77", uid=2,
            sender_name="Ana Ruiz", sender_address="ana@dominio.test", subject="Cotización", sent_at="",
            roster_match=True, notification_text="mail", message_id="<ana-2@dominio.test>")
        event.append(journal, ventas_event)
        check("the fixture event id carries the account", ventas_event["event_id"].startswith("imap:ventas:INBOX:"),
              ventas_event["event_id"])
        conn = FakeImap(message("Ana Ruiz <ana@dominio.test>", "ventas@dominio.test", "<ana-2@dominio.test>"))
        event_cli.idle_listener.connect = connect_with(conn)
        code, out, err = show(tmp, ventas_event["event_id"])
        check("event show --body of an additional account's event works", code == 0 and "cuerpo privado" in out, out + err)
        check("... it logged in as the account, not as the agent",
              len(opened) == 1 and opened[0].get("PAYNANI_EMAIL") == "ventas@dominio.test"
              and opened[0].get("PAYNANI_PASSWORD") == "ventas-secret", str(opened))
        check("... it was authorised by the account's roster", "ana@dominio.test" in out.split("--- authorized:")[-1], out)
        data = json.loads(out.split("\n--- verified body ---", 1)[0])
        check("... the output says which account", data.get("account_id") == "ventas" and data.get("account") == "ventas@dominio.test", str(data))
        check("... and the secret is nowhere in the output", "ventas-secret" not in out + err)

        # -- the same sender, when the event came from the account but they are only on the MAIN roster
        opened.clear()
        journal.write_text("")
        main_only = event.mail_event(
            account="ventas@dominio.test", account_id="ventas", mailbox="INBOX", uidvalidity="77", uid=3,
            sender_name="Metis", sender_address="metis@example.com", subject="Hola", sent_at="",
            roster_match=True, notification_text="mail", message_id="<metis-3@example.com>")
        event.append(journal, main_only)
        conn = FakeImap(message("Metis <metis@example.com>", "ventas@dominio.test", "<metis-3@example.com>"))
        event_cli.idle_listener.connect = connect_with(conn)
        code, out, err = show(tmp, main_only["event_id"])
        check("a sender only on the main roster is refused for the account's event", code == 2 and "body refused" in err, out + err)
        check("... and no body was printed", "cuerpo privado" not in out)

        # -- an event the listener did not tag roster is refused before any IMAP --
        opened.clear()
        journal.write_text("")
        outsider = event.mail_event(
            account="ventas@dominio.test", account_id="ventas", mailbox="INBOX", uidvalidity="77", uid=4,
            sender_name="Cliente", sender_address="cliente@otro.test", subject="Precio", sent_at="",
            roster_match=False, notification_text="mail", message_id="<c-4@otro.test>")
        event.append(journal, outsider)
        event_cli.idle_listener.connect = lambda env: (_ for _ in ()).throw(AssertionError("network used"))
        code, out, err = show(tmp, outsider["event_id"])
        check("a customer's event is refused without touching IMAP", code == 2 and "listener did not record" in err, out + err)
        check("... but its envelope is still shown, with the account", '"account_id": "ventas"' in out, out)

        # -- the account has been removed since ------------------------------------
        opened.clear()
        journal.write_text("")
        event.append(journal, ventas_event)
        saved = (tmp / "accounts.json").read_text()
        (tmp / "accounts.json").write_text(json.dumps({"schema_version": 1, "accounts": []}))
        event_cli.idle_listener.connect = lambda env: (_ for _ in ()).throw(AssertionError("network used"))
        code, out, err = show(tmp, ventas_event["event_id"])
        check("an event of an account that is no longer in accounts.json is not fetched", code == 1 and "ventas" in err, out + err)
        check("... and it does not fall back to the agent's login", not opened)
        (tmp / "accounts.json").write_text(saved)

        # -- the agent's own account is exactly as before ---------------------------
        opened.clear()
        journal.write_text("")
        main_event = event.mail_event(
            account="agent@example.com", mailbox="INBOX", uidvalidity="77", uid=9,
            sender_name="Metis", sender_address="metis@example.com", subject="Trabajo", sent_at="",
            roster_match=True, notification_text="mail", message_id="<metis-9@example.com>")
        event.append(journal, main_event)
        check("the agent's own event id is the old format", main_event["event_id"].startswith("imap:INBOX:"), main_event["event_id"])
        conn = FakeImap(message("Metis <metis@example.com>", "agent@example.com", "<metis-9@example.com>"))
        event_cli.idle_listener.connect = connect_with(conn)
        code, out, err = show(tmp, main_event["event_id"])
        check("the agent's own event still works with roster.md", code == 0 and "cuerpo privado" in out, out + err)
        check("... with the agent's own login",
              len(opened) == 1 and opened[0] == event_cli.idle_listener.load_env(tmp / ".env"), str(opened))
        data = json.loads(out.split("\n--- verified body ---", 1)[0])
        check("... and no account_id appears in its output", "account_id" not in data, str(data))

        # -- the ledger copy of an additional account's event resolves too ---------
        journal.write_text("")
        ledger.observed(tmp / "lifecycle.jsonl", ventas_event)
        recovered = event_cli._find(ventas_event["event_id"])
        check("a compacted journal event of an account resolves from the ledger, account_id intact",
              recovered and recovered.get("account_id") == "ventas", str(recovered))
    finally:
        event_cli.state_dir, event_cli.roster_file, event_cli.env_file, event_cli.idle_listener.connect = old

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
