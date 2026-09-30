#!/usr/bin/env python3
"""
Tests for `paynani account add` and `paynani account remove` (#282, part 4 of
the multi-account PRD in #276). An assertion script, not unittest.TestCase --
see scripts/test_all.sh for why that is the convention here.

Nothing here touches a real mail server, a real systemd, or the real .env: the
IMAP probe, the service control and the himalaya config path are replaced, and
every file lives in a temporary directory. What is checked is what this command
owns: that a failed login writes nothing, that the password is never on argv
and never printed, that the ten-account limit and the id rules hold before any
network call, and that `remove` moves the roster instead of deleting it.

The shape of accounts.json is the one in the PRD (#276, section 1). The tests
read and write it as plain JSON rather than through scripts/paynani_lib/
accounts.py, so they check the file the command leaves behind and not the
helper that reads it.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "harness"))

from paynani_lib import accounts_cli  # noqa: E402

failures = []


def check(name, condition):
    if condition:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}")
        failures.append(name)


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


SECRET = "s3cret-ventas-pw"
OTHER_SECRET = "s3cret-soporte-pw"

BASE_ENV = (
    "AGENT_EMAIL_ACCOUNT=agent@example.com\n"
    "AGENT_EMAIL_PASSWORD=main-account-password\n"
    "AGENT_EMAIL_FROM_NAME=Test Agent\n"
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com\n"
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993\n"
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=smtp.example.com\n"
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465\n"
    "TELEGRAM_TOKEN=unrelated-telegram-value\n"
)


def password_key(account_id):
    return "PAYNANI_ACCOUNT_" + account_id.upper().replace("-", "_") + "_PASSWORD"


class FakeService:
    """Stands in for account_service (part 3, #281): records, starts nothing."""

    def __init__(self):
        self.enabled = []
        self.disabled = []

    def enable(self, account_id):
        self.enabled.append(account_id)
        return True

    def disable(self, account_id):
        self.disabled.append(account_id)
        return True


class World:
    """One temporary install: .env, himalaya config, accounts.json, rosters/."""

    def __init__(self, existing=()):
        self.dir = Path(tempfile.mkdtemp(prefix="paynani-test-account-"))
        self.env = self.dir / ".env"
        self.env.write_text(BASE_ENV, encoding="utf-8")
        self.env.chmod(0o600)
        self.accounts = self.dir / "accounts.json"
        self.himalaya = self.dir / "himalaya-config.toml"
        self.himalaya.write_text('[accounts.paynani]\nemail = "agent@example.com"\ndefault = true\n', encoding="utf-8")
        self.rosters = self.dir / "rosters"
        self.service = FakeService()
        self.probes = []
        self.probe_ok = True
        self.prompts = []
        self.answers = []
        os.environ["PAYNANI_ENV"] = str(self.env)
        for account_id in existing:
            self.seed(account_id)
        accounts_cli.account_service = self.service
        accounts_cli.himalaya_config_path = lambda: self.himalaya
        accounts_cli.probe_imap = self._probe
        accounts_cli.getpass.getpass = self._getpass
        accounts_cli.input = self._input
        accounts_cli.stdin_is_tty = lambda: True

    def seed(self, account_id, password=OTHER_SECRET):
        data = json.loads(self.accounts.read_text()) if self.accounts.exists() else {"schema_version": 1, "accounts": []}
        data["accounts"].append({
            "id": account_id,
            "email": f"{account_id}@dominio.com",
            "from_name": account_id.title(),
            "imap": {"host": "mail.dominio.com", "port": 993},
            "smtp": {"host": "mail.dominio.com", "port": 465},
            "password_env": password_key(account_id),
            "roster": f"rosters/{account_id}.md",
            "mailboxes": ["INBOX"],
            "enabled": True,
        })
        self.accounts.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.accounts.chmod(0o600)
        self.rosters.mkdir(exist_ok=True)
        (self.rosters / f"{account_id}.md").write_text(f"| Name | Email |\n|---|---|\n| Contacto {account_id} | c@{account_id}.test |\n", encoding="utf-8")
        with self.env.open("a", encoding="utf-8") as handle:
            handle.write(f"{password_key(account_id)}={password}\n")
        block = (
            f"\n[accounts.paynani-{account_id}]\nemail = \"{account_id}@dominio.com\"\n"
            f"[accounts.paynani-{account_id}.imap]\nserver = \"imaps://mail.dominio.com:993\"\n"
        )
        with self.himalaya.open("a", encoding="utf-8") as handle:
            handle.write(block)

    def _probe(self, host, port, user, password):
        self.probes.append((host, port, user, password))
        return {"ok": self.probe_ok, "steps": [{"ok": self.probe_ok, "text": "login", "detail": "" if self.probe_ok else "AUTHENTICATIONFAILED"}]}

    def _getpass(self, prompt=""):
        self.prompts.append(prompt)
        return SECRET

    def _input(self, prompt=""):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else ""

    def accounts_data(self):
        return json.loads(self.accounts.read_text()) if self.accounts.exists() else None

    def ids(self):
        data = self.accounts_data()
        return [a["id"] for a in data["accounts"]] if data else []

    def snapshot(self):
        """Every file the command may touch, as bytes, so 'nothing written' is exact."""
        paths = [self.env, self.accounts, self.himalaya]
        out = {str(p): p.read_bytes() for p in paths if p.exists()}
        if self.rosters.exists():
            for p in sorted(self.rosters.rglob("*")):
                if p.is_file():
                    out[str(p)] = p.read_bytes()
        return out

    def cleanup(self):
        os.environ.pop("PAYNANI_ENV", None)
        shutil.rmtree(self.dir, ignore_errors=True)


def add_args(account_id="ventas", **kw):
    fields = dict(id=account_id, email=f"{account_id}@dominio.com", imap_host="mail.dominio.com", imap_port=993,
                  smtp_host="mail.dominio.com", smtp_port=465, from_name="Ventas Dominio", mailbox=None)
    fields.update(kw)
    return Args(**fields)


def run(fn, args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(args)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# add: the good path
# ---------------------------------------------------------------------------

w = World()
try:
    before_env = w.env.read_text()
    rc, out, err = run(accounts_cli.run_add, add_args())
    check("add: a working login exits 0", rc == 0)
    check("add: the login was tested with the address, host, port and the prompted password",
          w.probes == [("mail.dominio.com", 993, "ventas@dominio.com", SECRET)])
    check("add: the password was asked for with getpass, once", len(w.prompts) == 1)
    data = w.accounts_data()
    entry = (data or {}).get("accounts", [{}])[0]
    check("add: accounts.json has schema_version 1 and the one account", data is not None and data.get("schema_version") == 1 and w.ids() == ["ventas"])
    check("add: the entry carries email, hosts, ports, roster and mailboxes",
          entry.get("email") == "ventas@dominio.com" and entry.get("imap") == {"host": "mail.dominio.com", "port": 993}
          and entry.get("smtp") == {"host": "mail.dominio.com", "port": 465}
          and entry.get("roster") == "rosters/ventas.md" and entry.get("mailboxes") == ["INBOX"])
    check("add: the entry names the password variable and never holds the password",
          entry.get("password_env") == "PAYNANI_ACCOUNT_VENTAS_PASSWORD" and SECRET not in w.accounts.read_text())
    check("add: accounts.json is mode 600", stat.S_IMODE(w.accounts.stat().st_mode) == 0o600)
    env_now = w.env.read_text()
    check("add: the password went into the .env under the derived name", f"PAYNANI_ACCOUNT_VENTAS_PASSWORD={SECRET}" in env_now)
    check("add: every other .env line survived byte for byte", env_now.startswith(before_env))
    check("add: the .env is still mode 600", stat.S_IMODE(w.env.stat().st_mode) == 0o600)
    check("add: the roster was created from the template", (w.rosters / "ventas.md").is_file())
    config = w.himalaya.read_text()
    check("add: himalaya got [accounts.paynani-ventas] with the IMAP and SMTP servers",
          "[accounts.paynani-ventas]" in config and "imaps://mail.dominio.com:993" in config and "smtps://mail.dominio.com:465" in config)
    check("add: himalaya reads the password through env_secret.py, not inline",
          "env_secret.py" in config and "PAYNANI_ACCOUNT_VENTAS_PASSWORD" in config and SECRET not in config)
    check("add: the existing himalaya account is untouched", '[accounts.paynani]\nemail = "agent@example.com"' in config)
    check("add: the service was started for that account", w.service.enabled == ["ventas"])
    check("add: the next step names the account's own roster", "rosters/ventas.md" in out)
    check("add: the password is not printed", SECRET not in out and SECRET not in err)
finally:
    w.cleanup()


# ---------------------------------------------------------------------------
# add: refusals write nothing
# ---------------------------------------------------------------------------

w = World()
try:
    w.probe_ok = False
    before = w.snapshot()
    rc, out, err = run(accounts_cli.run_add, add_args())
    check("add: a failed login exits 1", rc == 1)
    check("add: a failed login leaves every file byte for byte as it was", w.snapshot() == before)
    check("add: a failed login creates no accounts.json, roster or service", not w.accounts.exists() and not w.rosters.exists() and w.service.enabled == [])
    check("add: a failed login says why", "AUTHENTICATIONFAILED" in out + err)
    check("add: a failed login does not print the password", SECRET not in out + err)
finally:
    w.cleanup()

w = World(existing=[f"cuenta-{n}" for n in range(10)])
try:
    before = w.snapshot()
    rc, out, err = run(accounts_cli.run_add, add_args("una-mas"))
    check("add: an eleventh account is refused", rc == 1 and len(w.ids()) == 10)
    check("add: the limit is checked before any network call", w.probes == [] and w.prompts == [])
    check("add: the limit refusal writes nothing", w.snapshot() == before)
    check("add: the refusal names the limit", "10" in out + err)
finally:
    w.cleanup()

w = World(existing=["ventas"])
try:
    before = w.snapshot()
    rc, out, err = run(accounts_cli.run_add, add_args("ventas"))
    check("add: a repeated id is refused", rc == 1 and w.ids() == ["ventas"])
    check("add: a repeated id asks for no password and probes nothing", w.probes == [] and w.prompts == [])
    check("add: a repeated id writes nothing", w.snapshot() == before)
finally:
    w.cleanup()

for bad in ("main", "Ventas", "ventas!", "-ventas", "a" * 32, ""):
    w = World()
    try:
        before = w.snapshot()
        rc, out, err = run(accounts_cli.run_add, add_args(bad or "empty", id=bad))
        check(f"add: the id {bad!r} is refused before any prompt or probe", rc == 1 and w.probes == [] and w.prompts == [])
        check(f"add: the id {bad!r} writes nothing", w.snapshot() == before)
    finally:
        w.cleanup()

w = World()
try:
    before = w.snapshot()
    rc, out, err = run(accounts_cli.run_add, add_args(mailbox=["INBOX", "Ventas"]))
    check("add: two mailboxes are refused, because the listener watches one per account (#280)", rc == 1 and "one mailbox" in err)
    check("add: two mailboxes are refused before any prompt, probe or write", w.probes == [] and w.prompts == [] and w.snapshot() == before)
    rc, out, err = run(accounts_cli.run_add, add_args(mailbox=["Ventas"]))
    check("add: a single non-default mailbox is written as given", rc == 0 and w.accounts_data()["accounts"][0]["mailboxes"] == ["Ventas"])
finally:
    w.cleanup()

w = World()
try:
    check("add: the command has no password argument to fill in", not hasattr(add_args(), "password"))
    accounts_cli.stdin_is_tty = lambda: False
    before = w.snapshot()
    rc, out, err = run(accounts_cli.run_add, add_args())
    check("add: with no TTY it refuses instead of reading a password from stdin",
          rc != 0 and w.probes == [] and w.prompts == [])
    check("add: the no-TTY refusal writes nothing", w.snapshot() == before)
finally:
    w.cleanup()


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

w = World(existing=["ventas", "soporte"])
try:
    rc, out, err = run(accounts_cli.run_remove, Args(id="ventas", yes=True))
    check("remove --yes exits 0", rc == 0)
    check("remove: the service for that account was stopped, and only that one", w.service.disabled == ["ventas"])
    check("remove: the account left accounts.json and the other stayed", w.ids() == ["soporte"])
    check("remove: its password left the .env and the other's stayed",
          password_key("ventas") not in w.env.read_text() and f"{password_key('soporte')}={OTHER_SECRET}" in w.env.read_text())
    check("remove: the unrelated .env lines survived", "TELEGRAM_TOKEN=unrelated-telegram-value" in w.env.read_text())
    config = w.himalaya.read_text()
    check("remove: its himalaya section is gone, the other's and the main account's stayed",
          "paynani-ventas" not in config and "[accounts.paynani-soporte]" in config and "[accounts.paynani]" in config)
    kept = w.rosters / "removed" / "ventas.md"
    check("remove: the roster was moved to rosters/removed/, not deleted",
          kept.is_file() and "Contacto ventas" in kept.read_text() and not (w.rosters / "ventas.md").exists())
    check("remove: the other account's roster was not touched", (w.rosters / "soporte.md").is_file())
    check("remove: nothing secret is printed", OTHER_SECRET not in out + err)
finally:
    w.cleanup()

w = World(existing=["ventas"])
try:
    before = w.snapshot()
    w.answers = ["n"]
    rc, out, err = run(accounts_cli.run_remove, Args(id="ventas", yes=False))
    check("remove: answering no changes nothing", rc != 0 and w.snapshot() == before and w.service.disabled == [])
    w.answers = [""]
    rc, out, err = run(accounts_cli.run_remove, Args(id="ventas", yes=False))
    check("remove: an empty answer is a no", rc != 0 and w.snapshot() == before and w.service.disabled == [])
    w.answers = ["s"]
    rc, out, err = run(accounts_cli.run_remove, Args(id="ventas", yes=False))
    check("remove: an explicit yes goes ahead", rc == 0 and w.ids() == [] and w.service.disabled == ["ventas"])
finally:
    w.cleanup()

w = World(existing=["ventas"])
try:
    before = w.snapshot()
    rc, out, err = run(accounts_cli.run_remove, Args(id="no-existe", yes=True))
    check("remove: an id that is not configured exits 1 and changes nothing", rc == 1 and w.snapshot() == before and w.service.disabled == [])
    rc, out, err = run(accounts_cli.run_remove, Args(id="main", yes=True))
    check("remove: 'main' is not an additional account and cannot be removed", rc == 1 and w.snapshot() == before)
finally:
    w.cleanup()

w = World(existing=["ventas"])
try:
    run(accounts_cli.run_remove, Args(id="ventas", yes=True))
    first = (w.rosters / "removed" / "ventas.md").read_text()
    w.seed("ventas")
    (w.rosters / "ventas.md").write_text("| Name | Email |\n|---|---|\n| Otro contacto | otro@ventas.test |\n", encoding="utf-8")
    rc, out, err = run(accounts_cli.run_remove, Args(id="ventas", yes=True))
    check("remove: a second removal of the same id succeeds", rc == 0)
    check("remove: it does not overwrite the roster kept by the first one",
          (w.rosters / "removed" / "ventas.md").read_text() == first)
    kept_files = sorted(p.name for p in (w.rosters / "removed").iterdir())
    check("remove: both rosters are kept under different names", len(kept_files) == 2)
finally:
    w.cleanup()


# ---------------------------------------------------------------------------
# account_service (#281) answers with the state it left the service in
# ---------------------------------------------------------------------------

class StateService:
    """account_service as Ximena's #286 has it: enable/disable return a state string, or raise."""

    def __init__(self, enable_state="active", disable_state="inactive", raises=None):
        self.enable_state, self.disable_state, self.raises = enable_state, disable_state, raises
        self.enabled, self.disabled = [], []

    def enable(self, account_id):
        if self.raises:
            raise self.raises
        self.enabled.append(account_id)
        return self.enable_state

    def disable(self, account_id):
        if self.raises:
            raise self.raises
        self.disabled.append(account_id)
        return self.disable_state


w = World()
try:
    accounts_cli.account_service = StateService(enable_state="failed")
    rc, out, err = run(accounts_cli.run_add, add_args())
    check("add: a service that comes up 'failed' is not reported as started", rc == 1 and "did not start" in err)
    check("add: ... but the account it could not start stays configured", w.ids() == ["ventas"] and (w.rosters / "ventas.md").is_file())
    check("add: ... and the message says how to start it by hand", "paynani-idle@ventas.service" in err)
finally:
    w.cleanup()

w = World()
try:
    accounts_cli.account_service = StateService(raises=RuntimeError("systemctl not found"))
    rc, out, err = run(accounts_cli.run_add, add_args())
    check("add: a service layer that raises is reported, not hidden", rc == 1 and "systemctl not found" in err and w.ids() == ["ventas"])
finally:
    w.cleanup()

w = World(existing=["ventas"])
try:
    accounts_cli.account_service = StateService(disable_state="active")
    before = w.snapshot()
    rc, out, err = run(accounts_cli.run_remove, Args(id="ventas", yes=True))
    check("remove: a service that is still 'active' after disable stops the removal", rc == 1 and w.snapshot() == before)
    accounts_cli.account_service = StateService(disable_state="inactive")
    rc, out, err = run(accounts_cli.run_remove, Args(id="ventas", yes=True))
    check("remove: a service that is 'inactive' after disable lets it go ahead", rc == 0 and w.ids() == [])
finally:
    w.cleanup()


# ---------------------------------------------------------------------------
# roster add / remove --roster: an account's own roster, and nothing else
# ---------------------------------------------------------------------------

from paynani_lib import roster_cli  # noqa: E402

real_run_tests = roster_cli._run_regression_tests
roster_cli._run_regression_tests = lambda: (True, "mocked: test_roster.sh and test_listener.py have their own entries")
main_roster = REPO / "roster.md"


def main_roster_state():
    return main_roster.read_bytes() if main_roster.exists() else None


class RArgs:
    def __init__(self, **kw):
        self.name = None
        self.address = None
        self.type = None
        self.github = None
        self.yes = True
        self.roster = None
        self.__dict__.update(kw)


w = World(existing=["ventas", "soporte"])
try:
    main_before = main_roster_state()
    soporte_before = (w.rosters / "soporte.md").read_bytes()
    rc, out, err = run(roster_cli.run_add, RArgs(name="Ana Ventas", address="ana@ventas.test", roster="rosters/ventas.md"))
    check("roster add --roster: adds the contact to that account's roster", rc == 0 and "ana@ventas.test" in (w.rosters / "ventas.md").read_text())
    check("roster add --roster: the main roster.md is not touched", main_roster_state() == main_before)
    check("roster add --roster: another account's roster is not touched", (w.rosters / "soporte.md").read_bytes() == soporte_before)

    rc, out, err = run(roster_cli.run_remove, RArgs(address="ana@ventas.test", roster="rosters/ventas.md"))
    check("roster remove --roster: removes the contact from that account's roster",
          rc == 0 and "ana@ventas.test" not in (w.rosters / "ventas.md").read_text())
    check("roster remove --roster: the main roster.md is still not touched", main_roster_state() == main_before)

    for label, given in (("a file that is not any account's roster", "rosters/otro.md"),
                         ("a path that climbs out of the directory", "../roster.md"),
                         ("an absolute path", str(w.env))):
        before = w.snapshot()
        rc, out, err = run(roster_cli.run_add, RArgs(name="X", address="x@nada.test", roster=given))
        check(f"roster add --roster: {label} is refused", rc == 1)
        check(f"roster add --roster: {label} writes nothing", w.snapshot() == before and main_roster_state() == main_before)
finally:
    roster_cli._run_regression_tests = real_run_tests
    w.cleanup()

w = World()
try:
    rc, out, err = run(roster_cli.run_add, RArgs(name="X", address="x@nada.test", roster="rosters/ventas.md"))
    check("roster add --roster: with no accounts.json at all it is refused", rc == 1)
finally:
    w.cleanup()


# ---------------------------------------------------------------------------

print()
if failures:
    print(f"{len(failures)} failed:")
    for name in failures:
        print(f"  {name}")
    sys.exit(1)

print("all account add/remove checks passed")
