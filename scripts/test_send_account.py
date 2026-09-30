#!/usr/bin/env python3
"""
Tests for `scripts/send.sh --account <id>` (#283, part 5 of the multi-account PRD
in #276).

Nothing is sent: himalaya is faked, and what the fake was given is what these
tests read back. The point of the option is one rule, held in every case below:
a message sent from an additional account is held to **that account's roster**,
not to roster.md. Someone on the main roster but not on the account's is
refused; someone on the account's roster but not on the main one is allowed;
and without --account nothing about send.sh changes.
"""

import json
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEND = ROOT / "scripts" / "send.sh"

passed = failed = 0


def check(desc, condition, detail=""):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}")
        if detail:
            print(detail)
        failed += 1


MAIN_ROSTER = "| Name | Email | Type |\n|---|---|---|\n| Metis | metis.claude.tob@gmail.com | AI Agent |\n"
VENTAS_ROSTER = "| Name | Email | Type |\n|---|---|---|\n| Ana Ruiz | ana@dominio.test | Human |\n"


def account(account_id, **overrides):
    entry = {
        "id": account_id,
        "email": f"{account_id}@dominio.test",
        "from_name": f"{account_id.title()} Dominio",
        "imap": {"host": "mail.dominio.test", "port": 993},
        "smtp": {"host": "mail.dominio.test", "port": 465},
        "password_env": f"PAYNANI_ACCOUNT_{account_id.upper()}_PASSWORD",
        "roster": f"rosters/{account_id}.md",
        "mailboxes": ["INBOX"],
        "enabled": True,
    }
    entry.update(overrides)
    return entry


class Home:
    """One temporary install: env file, rosters, accounts.json, himalaya config and a fake himalaya."""

    def __init__(self, accounts=None, write_ventas_roster=True):
        self.raw = tempfile.TemporaryDirectory()
        tmp = self.tmp = pathlib.Path(self.raw.name)
        (tmp / "bin").mkdir()
        (tmp / "rosters").mkdir()
        self.log = tmp / "himalaya.log"
        self.message = tmp / "message.eml"
        fake = tmp / "bin" / "himalaya"
        fake.write_text(f"""#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
    printf 'himalaya v2.1.0\\n'
    exit 0
fi
printf '%s\\n' "$*" >> {self.log}
if [ "$3" = "smtp" ] && [ "$4" = "send" ]; then
    cat > {self.message}
fi
exit 0
""")
        fake.chmod(0o755)
        (tmp / "roster.md").write_text(MAIN_ROSTER)
        if write_ventas_roster:
            (tmp / "rosters" / "ventas.md").write_text(VENTAS_ROSTER)
        (tmp / "agent-signature.txt").write_text("-- \nFIRMA DEL AGENTE\n")
        (tmp / ".env").write_text(
            "PAYNANI_EMAIL=agent@main.test\nPAYNANI_FROM_NAME=Agente Principal\n"
            f"PAYNANI_SIGNATURE_FILE={tmp / 'agent-signature.txt'}\n")
        entries = accounts if accounts is not None else [account("ventas")]
        (tmp / "accounts.json").write_text(json.dumps({"schema_version": 1, "accounts": entries}))
        (tmp / "himalaya.toml").write_text("""[accounts.paynani]
email = "agent@main.test"
[accounts.paynani.smtp]
server = "smtps://smtp.main.test:465"

[accounts.paynani-ventas]
email = "ventas@dominio.test"
[accounts.paynani-ventas.smtp]
server = "smtps://mail.dominio.test:465"
""")
        (tmp / "body.txt").write_text("hola\n")
        self.env = os.environ.copy()
        self.env.update({
            "PATH": f"{tmp / 'bin'}:{self.env.get('PATH', '')}",
            "ROSTER": str(tmp / "roster.md"),
            "ENV_FILE": str(tmp / ".env"),
            "HIMALAYA_CONFIG": str(tmp / "himalaya.toml"),
            "PAYNANI_STATE": str(tmp / "state"),
        })

    def send(self, to, *args):
        run = subprocess.run([str(SEND), *args, to, "asunto", str(self.tmp / "body.txt")],
                             text=True, capture_output=True, env=self.env)
        calls = self.log.read_text() if self.log.exists() else ""
        message = self.message.read_text() if self.message.exists() else ""
        sent_log = self.tmp / "state" / "sent.log"
        return run, calls, message, sent_log.read_text() if sent_log.exists() else ""

    def close(self):
        self.raw.cleanup()


ANA = "ana@dominio.test"
METIS = "metis.claude.tob@gmail.com"

# --- the account's roster decides, in both directions -----------------------------

h = Home()
try:
    run, calls, msg, _ = h.send(ANA, "--account", "ventas", "--dry-run")
    check("--account: a contact on the account's roster is allowed", run.returncode == 0 and "dry-run: nothing sent" in run.stdout,
          run.stdout + run.stderr)
    check("--account: dry-run says which account and which roster it used",
          "Account: ventas" in run.stdout and "ventas@dominio.test" in run.stdout and str(h.tmp / "rosters" / "ventas.md") in run.stdout,
          run.stdout)
    check("--account: dry-run shows the roster row from the account's roster",
          "To: ana@dominio.test (roster row: Ana Ruiz | ana@dominio.test | Human)" in run.stdout, run.stdout)

    run, calls, msg, _ = h.send(METIS, "--account", "ventas")
    check("--account: someone only on the MAIN roster is refused with 2", run.returncode == 2 and "REFUSED" in run.stderr, run.stderr)
    check("--account: ... and nothing was handed to himalaya", "smtp send" not in calls and msg == "", calls)
    check("--account: the refusal names the account's roster, not roster.md",
          str(h.tmp / "rosters" / "ventas.md") in run.stderr, run.stderr)

    run, calls, msg, _ = h.send(ANA)
    check("no --account: someone only on the account's roster is refused by roster.md", run.returncode == 2 and "REFUSED" in run.stderr, run.stderr)

    run, calls, msg, _ = h.send(METIS, "--dry-run")
    check("no --account: the main roster still allows its own contact", run.returncode == 0, run.stdout + run.stderr)
    check("no --account: dry-run output has no Account line, exactly as before", "Account:" not in run.stdout, run.stdout)
finally:
    h.close()

# --- the message leaves from the account ------------------------------------------

h = Home()
try:
    run, calls, msg, sent_log = h.send(ANA, "--account", "ventas")
    check("--account: a real send exits 0", run.returncode == 0, run.stdout + run.stderr)
    check("--account: it sends through himalaya account paynani-ventas with ventas@ as the envelope sender",
          "-a paynani-ventas smtp send --mail-from ventas@dominio.test --rcpt-to ana@dominio.test" in calls, calls)
    check("--account: the From header is the account's address and display name",
          'From: "Ventas Dominio" <ventas@dominio.test>' in msg or "From: Ventas Dominio <ventas@dominio.test>" in msg, msg)
    check("--account: the agent's own address is nowhere in the message", "agent@main.test" not in msg, msg)
    check("--account: sent.log records which account sent it", "account=ventas" in sent_log, sent_log)

    run, calls, msg, sent_log = h.send(METIS)
    check("no --account: still sends through paynani as the agent's own address",
          "-a paynani smtp send --mail-from agent@main.test --rcpt-to metis.claude.tob@gmail.com" in calls, calls)
    check("no --account: its sent.log line (the last) has no account field",
          "account=" not in sent_log.strip().splitlines()[-1], sent_log)
finally:
    h.close()

h = Home()
try:
    run, calls, msg, sent_log = h.send(ANA, "--account", "ventas", "--check")
    check("--account: --check prints the message from the account", run.returncode == 0 and "From: \"Ventas Dominio\" <ventas@dominio.test>" in run.stdout,
          run.stdout + run.stderr)
    check("--account: --check hands nothing to himalaya and writes no sent.log", "smtp send" not in calls and sent_log == "", calls)
finally:
    h.close()

# --- refusals ---------------------------------------------------------------------

h = Home()
try:
    run, calls, msg, _ = h.send(ANA, "--account", "nope", "--dry-run")
    check("--account: an id that is not in accounts.json is refused with 2, naming it",
          run.returncode == 2 and "nope" in run.stderr, run.stderr)
    check("--account: ... and nothing is sent", "smtp send" not in calls and msg == "")
finally:
    h.close()

h = Home(accounts=[account("ventas", smtp=None)])
try:
    run, calls, msg, _ = h.send(ANA, "--account", "ventas", "--dry-run")
    check("--account: an account with no SMTP server is refused with 2, saying so",
          run.returncode == 2 and "smtp" in run.stderr.lower(), run.stderr)
finally:
    h.close()

h = Home(write_ventas_roster=False)
try:
    run, calls, msg, _ = h.send(ANA, "--account", "ventas", "--dry-run")
    check("--account: an account whose roster file is missing is refused with 2", run.returncode == 2 and "roster" in run.stderr, run.stderr)
    check("--account: ... and the message says how to create it", "--roster rosters/ventas.md" in run.stderr, run.stderr)
finally:
    h.close()

h = Home()
try:
    (h.tmp / "accounts.json").write_text("{ not json")
    run, calls, msg, _ = h.send(ANA, "--account", "ventas", "--dry-run")
    check("--account: an unusable accounts.json is refused with 2", run.returncode == 2 and "REFUSED" in run.stderr, run.stderr)
finally:
    h.close()

# --- the agent's signature never goes out on an account's mail --------------------

h = Home()
try:
    run, calls, msg, _ = h.send(METIS)
    check("no --account: the agent's own mail still carries the agent's signature", "FIRMA DEL AGENTE" in msg, msg)

    run, calls, msg, _ = h.send(ANA, "--account", "ventas")
    check("--account with no signature_file: the agent's signature is NOT added", run.returncode == 0 and "FIRMA DEL AGENTE" not in msg, msg)
    run, calls, msg, _ = h.send(ANA, "--account", "ventas", "--dry-run")
    check("--account with no signature_file: dry-run says so",
          "Signature: no (account ventas has no signature_file)" in run.stdout, run.stdout)
    run, calls, msg, _ = h.send(METIS, "--dry-run")
    check("no --account: dry-run still reports the agent's signature as before",
          "Signature: yes (text/plain, source: PAYNANI_SIGNATURE_FILE)" in run.stdout, run.stdout)
finally:
    h.close()

h = Home(accounts=[account("ventas", signature_file="signatures/ventas.txt")])
try:
    (h.tmp / "signatures").mkdir()
    (h.tmp / "signatures" / "ventas.txt").write_text("-- \nVentas Dominio\nwww.dominio.test\n")
    run, calls, msg, _ = h.send(ANA, "--account", "ventas")
    check("--account with a signature_file: the message carries that signature",
          run.returncode == 0 and "Ventas Dominio\nwww.dominio.test" in msg, msg)
    check("... and not the agent's", "FIRMA DEL AGENTE" not in msg, msg)
    run, calls, msg, _ = h.send(ANA, "--account", "ventas", "--dry-run")
    check("--account with a signature_file: dry-run names its source",
          "Signature: yes (source: accounts.json signature_file)" in run.stdout, run.stdout)
finally:
    h.close()

h = Home(accounts=[account("ventas", signature_file="signatures/falta.txt")])
try:
    run, calls, msg, _ = h.send(ANA, "--account", "ventas")
    check("--account with an unreadable signature_file: refused with 2, saying which",
          run.returncode == 2 and "REFUSED" in run.stderr and "falta.txt" in run.stderr, run.stderr)
    check("... and nothing was sent", "smtp send" not in calls and msg == "", calls)
finally:
    h.close()

# accounts.json holds the same line on signature_file as on roster
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from paynani_lib import accounts as accounts_mod  # noqa: E402


def refused_signature(value):
    try:
        accounts_mod.validate({"accounts": [account("ventas", signature_file=value)]})
    except accounts_mod.AccountsError as exc:
        return str(exc)
    return None


for label, value in (("an absolute path", "/etc/passwd"), ("~", "~/firma.txt"), ("a path that climbs out", "../firma.txt"),
                     ("a number", 5), ("blank", "   ")):
    reason = refused_signature(value)
    check(f"accounts.json: signature_file as {label} is refused, naming the field",
          reason is not None and "signature_file" in reason, str(reason))
check("accounts.json: a relative signature_file inside the directory is accepted", refused_signature("signatures/ventas.txt") is None)
[normal] = accounts_mod.validate({"accounts": [account("ventas")]})
check("accounts.json: an account without signature_file has None, not an error", normal["signature_file"] is None)

# --- a display name cannot smuggle a header ---------------------------------------

h = Home(accounts=[account("ventas", from_name="Ventas\nBcc: robo@evil.test")])
try:
    run, calls, msg, _ = h.send(ANA, "--account", "ventas")
    headers = msg.split("\n\n", 1)[0]
    check("--account: a newline in from_name does not start another header", "\nBcc:" not in headers, headers)
    check("--account: ... and the only envelope recipient is the roster one", calls.count("--rcpt-to") == 1 and "evil.test" not in calls, calls)
finally:
    h.close()

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
