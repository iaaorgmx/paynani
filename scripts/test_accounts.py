#!/usr/bin/env python3
"""
Tests for scripts/paynani_lib/accounts.py and `paynani account list|test`
(#276, part 1: #279). An assertion script, like the rest of this suite.

accounts.py is the contract five other parts build on, so what is tested here
is mostly what it refuses: a file that is half understood would start a
listener on a mailbox watched wrong, which is worse than one that does not
start. No test touches a mail server; `account test` gets a fake connection.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import accounts, accounts_cli  # noqa: E402

passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def refused(data):
    """The AccountsError message for `data`, or None if it was accepted."""
    try:
        accounts.validate(data)
    except accounts.AccountsError as exc:
        return str(exc)
    return None


def good(**overrides):
    account = {
        "id": "ventas",
        "email": "ventas@dominio.example",
        "imap": {"host": "mail.dominio.example", "port": 993},
        "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD",
    }
    account.update(overrides)
    return account


# --- what a valid file becomes ----------------------------------------------

[ventas] = accounts.validate({"schema_version": 1, "accounts": [good()]})
check("defaults: INBOX only", ["INBOX"], ventas["mailboxes"])
check("defaults: roster under rosters/<id>.md", "rosters/ventas.md", ventas["roster"])
check("defaults: enabled", True, ventas["enabled"])
check("defaults: no SMTP unless given", None, ventas["smtp"])
check("an absent schema_version is version 1", 1,
      len(accounts.validate({"accounts": [good()]})))
check("an empty list is no accounts", [], accounts.validate({"accounts": []}))
check("the password key is derived from the id", "PAYNANI_ACCOUNT_SOPORTE_TI_PASSWORD",
      accounts.password_key("soporte-ti"))

# --- what it refuses, naming the account and the field ----------------------

for label, data, fragment in (
    ("a list at the top level", [good()], "top level"),
    ("an unknown schema_version", {"schema_version": 2, "accounts": []}, "schema_version"),
    ("an uppercase id", {"accounts": [good(id="Ventas")]}, "`id` must match"),
    ("an id with a space", {"accounts": [good(id="mis ventas")]}, "`id` must match"),
    ("`main`, which is the .env account", {"accounts": [good(id="main")]}, "reserved"),
    ("a repeated id", {"accounts": [good(), good(email="otro@dominio.example")]}, "repeated"),
    ("no email", {"accounts": [good(email="")]}, "`email` is required"),
    ("no imap host", {"accounts": [good(imap={"port": 993})]}, "`imap.host` is required"),
    ("a port where the host goes", {"accounts": [good(imap={"host": "993"})]}, "which is a port"),
    ("a port out of range", {"accounts": [good(imap={"host": "h", "port": 70000})]}, "port must be"),
    ("a port as a string", {"accounts": [good(imap={"host": "h", "port": "993"})]}, "port must be"),
    ("no password_env", {"accounts": [good(password_env=None)]}, "`password_env`"),
    ("a password where the key name goes", {"accounts": [good(password_env="hunter2!")]}, "`password_env`"),
    ("an empty mailbox list", {"accounts": [good(mailboxes=[])]}, "`mailboxes`"),
    ("enabled as a string", {"accounts": [good(enabled="yes")]}, "`enabled`"),
):
    message = refused(data)
    check(f"refuses {label}", True, message is not None and fragment in message)

eleven = [good(id=f"cuenta{n}", email=f"c{n}@d.example") for n in range(11)]
check("refuses more than 10 accounts", True, "limit is 10" in (refused({"accounts": eleven}) or ""))
check("accepts exactly 10", 10, len(accounts.validate({"accounts": eleven[:10]})))
message = refused({"accounts": [good(), good(id="soporte", email="")]})
check("names the account that is wrong", True, "'soporte'" in (message or ""))

# A refused password_env must not echo a password someone typed into it.
message = refused({"accounts": [good(password_env="hunter2!")]}) or ""
check("the refusal does not repeat what was in password_env", False, "hunter2" in message)

# --- load(): a missing file is none, a bad one is an error ------------------

tmp = Path(tempfile.mkdtemp())
missing = tmp / "accounts.json"
check("no file means no accounts", [], accounts.load(missing))
missing.write_text("{ not json", encoding="utf-8")
try:
    accounts.load(missing)
    check("invalid JSON is refused", True, False)
except accounts.AccountsError as exc:
    check("invalid JSON is refused, naming the file", True, str(missing) in str(exc))
path = tmp / "accounts.json"
path.write_text(json.dumps({"schema_version": 1, "accounts": [good(roster="r/v.md")]}), encoding="utf-8")
check("get() finds by id", "ventas@dominio.example", accounts.get("ventas", path)["email"])
try:
    accounts.get("nadie", path)
    check("get() of an unknown id is refused", True, False)
except accounts.AccountsError:
    check("get() of an unknown id is refused", True, True)
check("a relative roster is relative to accounts.json", tmp / "r/v.md",
      accounts.roster_path(accounts.get("ventas", path), path))
for label, roster in (("an absolute roster", "/etc/passwd"), ("a roster with ..", "../../x.md"),
                      ("a roster under ~", "~/r.md"), ("a roster that climbs midway", "rosters/../../x.md")):
    message = refused({"accounts": [good(roster=roster)]}) or ""
    check(f"refuses {label}, naming the account and the field", True,
          "'ventas'" in message and "`roster` must be a relative path" in message)
check("a nested relative roster is fine", "rosters/pyme/ventas.md",
      accounts.validate({"accounts": [good(roster="rosters/pyme/ventas.md")]})[0]["roster"])
check("accounts.json lives beside the .env", Path("/x/y/accounts.json"),
      accounts.accounts_path(environ={"PAYNANI_ENV": "/x/y/.env"}))

# --- the password and the login keys ----------------------------------------

env = {"PAYNANI_ACCOUNT_VENTAS_PASSWORD": "s3cret"}
check("password() reads the named key", "s3cret", accounts.password(ventas, env))
try:
    accounts.password(ventas, {})
    check("a missing password is refused", True, False)
except accounts.AccountsError as exc:
    check("a missing password is refused, naming the key", True,
          "PAYNANI_ACCOUNT_VENTAS_PASSWORD" in str(exc))
check("env_for() speaks connect()'s keys", {
    "PAYNANI_IMAP_HOST": "mail.dominio.example", "PAYNANI_IMAP_PORT": "993",
    "PAYNANI_EMAIL": "ventas@dominio.example", "PAYNANI_PASSWORD": "s3cret",
}, accounts.env_for(ventas, env))

# --- event ids ---------------------------------------------------------------

check("an additional account's event id", "imap:ventas:INBOX:17:42",
      accounts.event_id("ventas", "INBOX", 17, 42))
check("main keeps today's form", "imap:INBOX:17:42", accounts.event_id("main", "INBOX", 17, 42))
check("parse: today's form is main", ("main", "INBOX", "1", "1607"),
      accounts.parse_event_id("imap:INBOX:1:1607"))
check("parse: the account form", ("ventas", "INBOX", "17", "42"),
      accounts.parse_event_id("imap:ventas:INBOX:17:42"))
check("parse: a mailbox with a colon, account form", ("ventas", "Archivo:2026", "17", "42"),
      accounts.parse_event_id("imap:ventas:Archivo:2026:17:42"))
check("parse: an old-form mailbox with a colon is not taken for an unknown account",
      ("main", "lista:ventas", "1", "5"),
      accounts.parse_event_id("imap:lista:ventas:1:5", known_ids={"ventas"}))
check("round trip", ("soporte", "INBOX", "9", "3"),
      accounts.parse_event_id(accounts.event_id("soporte", "INBOX", 9, 3)))
for bad in ("", "evt-1", "imap:INBOX:1", "pop:INBOX:1:2"):
    try:
        accounts.parse_event_id(bad)
        check(f"parse refuses {bad!r}", True, False)
    except accounts.AccountsError:
        check(f"parse refuses {bad!r}", True, True)

# --- paynani account list ----------------------------------------------------

def run(fn, *args, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(*args, **kw)
    return code, out.getvalue(), err.getvalue()


home = Path(tempfile.mkdtemp())
os.environ["PAYNANI_ENV"] = str(home / ".env")
code, out, _ = run(accounts_cli.run_list, SimpleNamespace())
check("list with no accounts.json exits 0", 0, code)
check("and says there are none", True, "no additional accounts" in out)

(home / "rosters").mkdir()
(home / "rosters" / "ventas.md").write_text(
    "| Name | Email | Type |\n|---|---|---|\n| Ana | ana@cliente.example | Human |\n", encoding="utf-8")
(home / "accounts.json").write_text(json.dumps({"accounts": [
    good(), good(id="soporte", email="soporte@dominio.example", enabled=False,
                 password_env="PAYNANI_ACCOUNT_SOPORTE_PASSWORD")]}), encoding="utf-8")
(home / ".env").write_text("PAYNANI_ACCOUNT_VENTAS_PASSWORD=s3cret\n", encoding="utf-8")
code, out, _ = run(accounts_cli.run_list, SimpleNamespace())
check("list exits 0", 0, code)
check("list shows each account", True, "ventas@dominio.example" in out and "soporte@dominio.example" in out)
check("list counts the roster's contacts", True, "(1 contact(s))" in out)
check("list says when a roster is missing", True, "(MISSING)" in out)
check("list shows disabled accounts as such", True, "disabled" in out)
check("list never prints a password", False, "s3cret" in out)

(home / "accounts.json").write_text('{"accounts": [{"id": "X"}]}', encoding="utf-8")
code, _, err = run(accounts_cli.run_list, SimpleNamespace())
check("list of a bad file exits 1 and says why", (1, True), (code, "not usable" in err))

# --- paynani account test ----------------------------------------------------

(home / "accounts.json").write_text(json.dumps({"accounts": [good(mailboxes=["INBOX", "Ventas"])]}),
                                    encoding="utf-8")


class FakeConn:
    def __init__(self, idle=True, refuse=()):
        self.capabilities = ("IMAP4REV1", "IDLE") if idle else ("IMAP4REV1",)
        self.refuse = refuse
        self.logged_out = False

    def select(self, mailbox, readonly=False):
        if mailbox in self.refuse:
            return "NO", [b"no such mailbox"]
        return "OK", [b"12"]

    def logout(self):
        self.logged_out = True


seen = {}


def fake_connect(conn):
    def connect(env):
        seen["env"] = env
        return conn
    return connect


def load_env(_):
    return {"PAYNANI_ACCOUNT_VENTAS_PASSWORD": "s3cret"}


conn = FakeConn()
code, out, _ = run(accounts_cli.run_test, SimpleNamespace(account_id="ventas"),
                   connect=fake_connect(conn), load_env=load_env)
check("test of a good account exits 0", 0, code)
check("test logs in as the account, not as the main one", "ventas@dominio.example",
      seen["env"]["PAYNANI_EMAIL"])
check("test selects every mailbox", True, "ok    select INBOX" in out and "ok    select Ventas" in out)
check("test checks IDLE", True, "ok    IDLE" in out)
check("test logs out", True, conn.logged_out)
check("test never prints the password", False, "s3cret" in out)

code, out, _ = run(accounts_cli.run_test, SimpleNamespace(account_id="ventas"),
                   connect=fake_connect(FakeConn(idle=False, refuse=("Ventas",))), load_env=load_env)
check("a missing mailbox or no IDLE exits 1", 1, code)
check("and each failure is named", True, "FAIL  select Ventas" in out and "FAIL  IDLE" in out)


def rejecting(env):
    raise SystemExit(1)


code, out, _ = run(accounts_cli.run_test, SimpleNamespace(account_id="ventas"),
                   connect=rejecting, load_env=load_env)
check("a rejected login exits 1", (1, True), (code, "FAIL  login" in out))


def unreachable(env):
    raise OSError("Network is unreachable")


code, out, _ = run(accounts_cli.run_test, SimpleNamespace(account_id="ventas"),
                   connect=unreachable, load_env=load_env)
check("a network error is said literally", True, "OSError: Network is unreachable" in out)

code, out, _ = run(accounts_cli.run_test, SimpleNamespace(account_id="ventas"),
                   connect=fake_connect(FakeConn()), load_env=lambda _: {})
check("a missing password fails before connecting", (1, True),
      (code, "FAIL  credentials" in out))

code, _, err = run(accounts_cli.run_test, SimpleNamespace(account_id="nadie"),
                   connect=fake_connect(FakeConn()), load_env=load_env)
check("an unknown account exits 1", (1, True), (code, "no account 'nadie'" in err))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
