#!/usr/bin/env python3
"""
Tests for the listener watching an additional account (#276, part 2: #280).

What matters here is separation. An additional account's mail must say which
account received it, carry an event id no other account can produce, and be
judged against that account's roster and nobody else's. And the agent's own
account must come out byte-for-byte as it did before accounts existed.
"""

from __future__ import annotations

import email
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import event as ev  # noqa: E402
import idle_listener as listener  # noqa: E402
import ledger  # noqa: E402
import session_start  # noqa: E402
from paynani_lib import accounts  # noqa: E402

passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def as_account(account_id, label):
    listener.ACCOUNT_ID = account_id
    listener.ACCOUNT_LABEL = label


# --- event ids ---------------------------------------------------------------

check("main keeps today's event id", "imap:INBOX:1:7", ev.event_id("INBOX", 1, 7))
check("an explicit main is the same", "imap:INBOX:1:7", ev.event_id("INBOX", 1, 7, "main"))
check("an additional account puts its id first", "imap:ventas:INBOX:1:7",
      ev.event_id("INBOX", 1, 7, "ventas"))
check("harness/event.py and accounts.py agree", accounts.event_id("ventas", "INBOX", 1, 7),
      ev.event_id("INBOX", 1, 7, "ventas"))
check("and accounts.py reads it back", ("ventas", "INBOX", "1", "7"),
      accounts.parse_event_id(ev.event_id("INBOX", 1, 7, "ventas")))


def mail(account_id=None):
    return ev.mail_event(account="x@d.example", mailbox="INBOX", uidvalidity=1, uid=7,
                         sender_name="Ana", sender_address="ana@c.example", subject="Hola",
                         sent_at="", roster_match=True, notification_text="[mail] Ana — Hola",
                         observed_at="2026-09-30T06:00:00Z", account_id=account_id)


check("a main mail event has no account_id key", False, "account_id" in mail())
check("and is identical with account_id=None or 'main'", mail(), mail("main"))
check("an additional account's mail event carries account_id", "ventas", mail("ventas")["account_id"])
check("and its inspection command names its own id",
      "scripts/paynani event show imap:ventas:INBOX:1:7", mail("ventas")["inspection_command"])
check("session_start finds that id in a notice", {"imap:ventas:INBOX:1:7"},
      session_start.event_ids_in(["[mail 10:02:11, ventas@d.example, roster] Ana — Hola "
                                  "[scripts/paynani event show imap:ventas:INBOX:1:7]"]))

fault_main = ev.listener_error(account="x@d.example", message="connection lost",
                               observed_at="2026-09-30T06:00:00Z")
fault_ventas = ev.listener_error(account="v@d.example", message="connection lost",
                                 observed_at="2026-09-30T06:00:00Z", account_id="ventas")
check("a main listener fault reads as before", "[listener] connection lost",
      fault_main["notification_text"])
check("an account's listener fault names the account", "[listener ventas] connection lost",
      fault_ventas["notification_text"])
check("the same fault in the same second on two accounts is two events", True,
      fault_main["event_id"] != fault_ventas["event_id"])
check("a main fault has no account_id key", False, "account_id" in fault_main)

journal = Path(tempfile.mkdtemp()) / "lifecycle.jsonl"
ledger.observed(journal, mail("ventas"))
check("the ledger keeps account_id", "ventas",
      ledger.latest(journal)["imap:ventas:INBOX:1:7"]["envelope"]["account_id"])

# --- the notice --------------------------------------------------------------

as_account(None, "")
line = listener.parts("Ana <ana@c.example>", "Hola", "", True)["notification_text"]
check("main's notice has no account in it", True,
      line.startswith("[mail ") and ", roster] Ana" in line and "@d.example" not in line)
as_account("ventas", "ventas@d.example")
line = listener.parts("Ana <ana@c.example>", "Hola", "Tue, 29 Sep 2026 23:00:00 -0500", True)["notification_text"]
check("an account's notice names it, before the roster tag", True,
      ", ventas@d.example, roster] Ana — Hola" in line)
line = listener.parts("Ana <ana@c.example>", "Hola", "", False)["notification_text"]
check("and without the tag when the sender is not on that roster", True,
      line.endswith(", ventas@d.example] Ana — Hola"))
as_account(None, "")

# --- each account is judged against its own roster ---------------------------

tmp = Path(tempfile.mkdtemp())
main_roster = tmp / "roster.md"
main_roster.write_text("| Name | Email |\n|---|---|\n| Julian | julian@h.example |\n", encoding="utf-8")
ventas_roster = tmp / "rosters" / "ventas.md"
ventas_roster.parent.mkdir()
ventas_roster.write_text("| Name | Email |\n|---|---|\n| Ana | ana@c.example |\n", encoding="utf-8")


class FakeConn:
    def __init__(self, messages):
        self.messages = messages

    def uid(self, command, *args):
        if command == "search":
            return "OK", [" ".join(str(u) for u in sorted(self.messages)).encode()]
        msg = self.messages[int(args[0])]
        return "OK", [(b"1 (BODY[HEADER.FIELDS ()] {0})", msg.as_bytes())]


def message(sender, to):
    msg = email.message.EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = "Pedido"
    msg["Date"] = "Tue, 29 Sep 2026 23:00:00 -0500"
    msg["Message-Id"] = "<p@c.example>"
    return msg


conn = FakeConn({5: message("Ana <ana@c.example>", "ventas@d.example")})
[(_, in_ventas)] = listener.fetch_since(conn, 0, listener.Listed(ventas_roster), "ventas@d.example")
[(_, in_main)] = listener.fetch_since(conn, 0, listener.Listed(main_roster), "ventas@d.example")
check("Ana is on the ventas roster, so her mail there is roster", True, in_ventas["roster_match"])
check("the same mail judged by the main roster is not", False, in_main["roster_match"])
check("recipient role is worked out against the account's own address", "to",
      in_ventas["recipient_role"])

# --- account_setup: what --account resolves to ----------------------------------

home = Path(tempfile.mkdtemp())
os.environ["PAYNANI_ENV"] = str(home / ".env")
os.environ["PAYNANI_STATE"] = str(home / "state")
(home / ".env").write_text("PAYNANI_ACCOUNT_VENTAS_PASSWORD=s3cret\n", encoding="utf-8")
account = {"id": "ventas", "email": "ventas@d.example",
           "imap": {"host": "mail.d.example", "port": 993},
           "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD", "roster": "rosters/ventas.md"}
path = home / "accounts.json"


def write(*items):
    path.write_text(json.dumps({"accounts": list(items)}), encoding="utf-8")


write(account)
setup = listener.account_setup("ventas", home / ".env", path)
check("the login is the account's", ("ventas@d.example", "s3cret", "mail.d.example"),
      (setup["env"]["PAYNANI_EMAIL"], setup["env"]["PAYNANI_PASSWORD"], setup["env"]["PAYNANI_IMAP_HOST"]))
check("the roster is the account's", home / "rosters/ventas.md", setup["roster"])
check("the state is the account's own", home / "state/accounts/ventas/idle.json", setup["state"])
check("the mailbox is the one it lists", "INBOX", setup["mailbox"])


def refusal(*items, account_id="ventas"):
    write(*items)
    try:
        listener.account_setup(account_id, home / ".env", path)
    except accounts.AccountsError as exc:
        return str(exc)
    return None


check("a disabled account is refused", True, "disabled" in (refusal(dict(account, enabled=False)) or ""))
check("two mailboxes are refused rather than half watched", True,
      "one per account" in (refusal(dict(account, mailboxes=["INBOX", "Ventas"])) or ""))
check("an unknown account is refused", True, "no account 'nadie'" in (refusal(account, account_id="nadie") or ""))
check("a missing password is refused before connecting", True,
      "PAYNANI_ACCOUNT_SOPORTE_PASSWORD" in (refusal(dict(account, id="soporte",
          password_env="PAYNANI_ACCOUNT_SOPORTE_PASSWORD"), account_id="soporte") or ""))

# The main account's run() still reads its own env file: `env=None` is the
# default, and main() only builds one for --account.
import inspect  # noqa: E402
check("run() defaults to reading env_path", None, inspect.signature(listener.run).parameters["env"].default)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
