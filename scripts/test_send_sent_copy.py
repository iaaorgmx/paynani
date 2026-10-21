#!/usr/bin/env python3
"""
Tests for the copy `scripts/send.sh` keeps in Sent (#435, Julian's Q45 = A).

Nothing is sent: himalaya is faked, and what the fake was given is what these
tests read back. One rule holds in every case: the copy is the exact bytes SMTP
was given, it lands in the folder marked \\Sent flagged \\Seen, Gmail is skipped,
and a copy that cannot be saved never fails the send -- it is written down in
sent.log as `sent-copy=failed` instead.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEND = ROOT / "scripts" / "send.sh"
sys.path.insert(0, str(ROOT / "scripts"))

from paynani_lib import sent_copy  # noqa: E402

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


def same(desc, expected, actual):
    """check() for an expected value: `check(desc, expected, actual)` would pass on any truthy tuple."""
    check(desc, expected == actual, f"     expected {expected!r}\n     got      {actual!r}")


SENT_BOX = [{"name": "Inbox", "attributes": ["\\HasChildren"]},
            {"name": "INBOX.Sent", "attributes": ["\\HasNoChildren", "\\Sent"]},
            {"name": "INBOX.Trash", "attributes": ["\\Trash"]}]


class Home:
    """One temporary install with a fake himalaya: `imap list` answers `boxes`, `imap append` keeps stdin."""

    def __init__(self, imap_server="imaps://mail.example.test:993", boxes=SENT_BOX, append_exit=0, list_exit=0):
        self.raw = tempfile.TemporaryDirectory()
        tmp = self.tmp = pathlib.Path(self.raw.name)
        (tmp / "bin").mkdir()
        self.log = tmp / "himalaya.log"
        self.sent = tmp / "smtp.eml"
        self.copy = tmp / "copy.eml"
        (tmp / "boxes.json").write_text(json.dumps({"mailboxes": boxes}))
        fake = tmp / "bin" / "himalaya"
        fake.write_text(f"""#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
    printf 'himalaya v2.2.1\\n'
    exit 0
fi
printf '%s\\n' "$*" >> {self.log}
if [ "$3" = "smtp" ] && [ "$4" = "send" ]; then
    cat > {self.sent}
    exit 0
fi
if [ "$3" = "imap" ] && [ "$4" = "list" ]; then
    [ {list_exit} -eq 0 ] || exit {list_exit}
    cat {tmp / 'boxes.json'}
    exit 0
fi
if [ "$3" = "imap" ] && [ "$4" = "append" ]; then
    cat > {self.copy}
    exit {append_exit}
fi
exit 0
""")
        fake.chmod(0o755)
        (tmp / "roster.md").write_text("| Name | Email | Type |\n|---|---|---|\n| Metis | metis.claude.tob@gmail.com | AI Agent |\n")
        (tmp / ".env").write_text("PAYNANI_EMAIL=agent@example.test\n")
        imap = f'\n[accounts.paynani.imap]\nserver = "{imap_server}"\n' if imap_server else ""
        (tmp / "himalaya.toml").write_text(f"""[accounts.paynani]
email = "agent@example.test"
[accounts.paynani.smtp]
server = "smtps://mail.example.test:465"
{imap}""")
        (tmp / "body.txt").write_text("hola, ¿cómo vas?\n")
        self.env = os.environ.copy()
        self.env.update({
            "PATH": f"{tmp / 'bin'}:{self.env.get('PATH', '')}",
            "ROSTER": str(tmp / "roster.md"),
            "ENV_FILE": str(tmp / ".env"),
            "HIMALAYA_CONFIG": str(tmp / "himalaya.toml"),
            "PAYNANI_STATE": str(tmp / "state"),
            "TMPDIR": str(tmp),
        })

    def send(self, *args):
        run = subprocess.run([str(SEND), *args, "metis.claude.tob@gmail.com", "asunto", str(self.tmp / "body.txt")],
                             text=True, capture_output=True, env=self.env)
        log = self.tmp / "state" / "sent.log"
        return run, (self.log.read_text() if self.log.exists() else ""), (log.read_text() if log.exists() else "")

    def leftovers(self):
        return sorted(p.name for p in self.tmp.glob("paynani-send.*"))

    def close(self):
        self.raw.cleanup()


# --- a server that is not Gmail: the copy is saved ---------------------------------
h = Home()
try:
    run, calls, log = h.send()
    check("not Gmail: the send succeeds", run.returncode == 0 and "sent to metis.claude.tob@gmail.com" in run.stdout,
          run.stdout + run.stderr)
    check("... and the copy went to the folder marked \\Sent, flagged \\Seen",
          "-a paynani imap append INBOX.Sent -f \\Seen" in calls, calls)
    check("... after the SMTP send, never before",
          calls.find("smtp send") < calls.find("imap append"), calls)
    check("... byte for byte the message SMTP was given",
          h.copy.exists() and h.copy.read_bytes() == h.sent.read_bytes() and b"Message-ID: <" in h.copy.read_bytes())
    mid = next(l for l in h.sent.read_text().splitlines() if l.startswith("Message-ID: ")).split(": ", 1)[1]
    check("... sent.log says sent-copy=saved, with the same Message-ID",
          "\tsent-copy=saved\t" in log and log.rstrip("\n").endswith(f"message-id={mid}"), log)
    check("... no warning", "warning" not in run.stderr, run.stderr)
    check("... and the message file is gone", h.leftovers() == [], h.leftovers())
    run, calls, log = h.send("--bcc", "metis.claude.tob@gmail.com")
    check("Bcc stays out of the copy too", "Bcc" not in h.copy.read_text() and "metis" not in h.copy.read_text().split("To:")[0])
finally:
    h.close()

# --- Gmail keeps its own copy -------------------------------------------------------
for server in ("imaps://imap.gmail.com:993", "imap.gmail.com"):
    h = Home(imap_server=server)
    try:
        run, calls, log = h.send()
        same(f"Gmail ({server}): sent, no APPEND, sent-copy=skipped",
              (0, False, True), (run.returncode, "imap append" in calls, "\tsent-copy=skipped\t" in log))
    finally:
        h.close()

# --- no IMAP in the account: nowhere to put it ------------------------------------
h = Home(imap_server="")
try:
    run, calls, log = h.send()
    same("no IMAP block: sent, nothing asked of IMAP, sent-copy=skipped",
          (0, "", True), (run.returncode, "\n".join(l for l in calls.splitlines() if " imap " in l), "\tsent-copy=skipped\t" in log))
finally:
    h.close()

# --- the folder by its name when nothing is marked \Sent -------------------------
h = Home(boxes=[{"name": "INBOX", "attributes": []}, {"name": "Enviados", "attributes": ["\\HasNoChildren"]}])
try:
    run, calls, log = h.send()
    check("no \\Sent mark: a well-known name (Enviados)", "imap append Enviados -f \\Seen" in calls and "sent-copy=saved" in log, calls)
finally:
    h.close()

# --- a copy that fails never fails the send -----------------------------------------
for label, kw, reason in (("APPEND fails", {"append_exit": 1}, "append"),
                          ("LIST fails", {"list_exit": 1}, "no-sent-folder"),
                          ("no Sent folder at all", {"boxes": [{"name": "INBOX", "attributes": []}]}, "no-sent-folder")):
    h = Home(**kw)
    try:
        run, calls, log = h.send()
        check(f"{label}: the send still exits 0 and says it was sent",
              run.returncode == 0 and "sent to metis.claude.tob@gmail.com" in run.stdout, run.stdout + run.stderr)
        check(f"{label}: a warning naming why, sent-copy=failed in sent.log",
              f"no copy was saved in Sent ({reason})" in run.stderr and "\tsent-copy=failed\t" in log, run.stderr + log)
        check(f"{label}: nothing is created", "imap create" not in calls, calls)
        check(f"{label}: the message file is gone", h.leftovers() == [], h.leftovers())
    finally:
        h.close()

# --- --check and --dry-run save nothing ----------------------------------------------
h = Home()
try:
    for flag in ("--check", "--dry-run"):
        run, calls, log = h.send(flag)
        same(f"{flag}: no APPEND and no sent.log", (0, False, ""), (run.returncode, "imap append" in calls, log))
finally:
    h.close()

# --- sent_copy.py on its own --------------------------------------------------------
same("is_gmail", (True, True, False, False),
      (sent_copy.is_gmail("imap.gmail.com"), sent_copy.is_gmail("imap.googlemail.com"),
       sent_copy.is_gmail("gmail.example.test"), sent_copy.is_gmail("mail.example.test")))
run = subprocess.run([sys.executable, str(ROOT / "scripts" / "paynani_lib" / "sent_copy.py")], capture_output=True, text=True)
same("sent_copy.py with no arguments: one line, exit 0", (0, "failed usage"), (run.returncode, run.stdout.strip()))

# --- paynani doctor says which account does not keep a copy -------------------------
sys.path.insert(0, str(ROOT / "harness"))
from paynani_lib import diagnostics  # noqa: E402

with tempfile.TemporaryDirectory() as raw:
    tmp = pathlib.Path(raw)
    (tmp / "h.toml").write_text("""[accounts.paynani]
email = "a@x.test"
[accounts.paynani.imap]
server = "imaps://mail.x.test:993"
[accounts.paynani-gm]
email = "b@gmail.com"
[accounts.paynani-gm.imap]
server = "imaps://imap.gmail.com:993"
[accounts.paynani-sin]
email = "c@x.test"
[accounts.paynani-sin.smtp]
server = "smtps://mail.x.test:465"
""")
    os.environ["HIMALAYA_CONFIG"] = str(tmp / "h.toml")
    log = tmp / "sent.log"
    log.write_text("2026-10-21T10:00:00Z\tto=a@b.test\tcc=\tbcc=\tsubject=x\tmessage-id=<1@x>\n")

    def row(*args):
        c = diagnostics._sent_copy_check(*args)
        return c["status"], c["summary"]

    same("doctor: a send from before this version -> ok, from the next send",
          ("ok", "sent mail will be copied to Sent from the next send"), row("sent_copy", "paynani", "", log))
    with open(log, "a") as fh:
        fh.write("2026-10-21T10:01:00Z\tto=a@b.test\tcc=\tbcc=\tsubject=x\tsent-copy=failed\tmessage-id=<2@x>\n")
        fh.write("2026-10-21T10:02:00Z\tto=a@b.test\tcc=\tbcc=\tsubject=x\tsent-copy=saved\tmessage-id=<3@x>\taccount=otra\n")
    same("doctor: the account's last send failed its copy -> warning",
          "warning", row("sent_copy", "paynani", "", log)[0])
    same("doctor: ... another account's line does not count for it", True,
          diagnostics._last_sent(log, "")["message-id"] == "<2@x>")
    with open(log, "a") as fh:
        fh.write("2026-10-21T10:03:00Z\tto=a@b.test\tcc=\tbcc=\tsubject=x\tsent-copy=saved\tmessage-id=<4@x>\n")
    same("doctor: saved -> ok", ("ok", "sent mail is copied to Sent"), row("sent_copy", "paynani", "", log))
    same("doctor: Gmail -> ok, paynani adds none", "ok", row("account:gm:sent_copy", "paynani-gm", "gm", log)[0])
    same("doctor: no IMAP -> warning that names the account", ("warning", True),
          (row("account:sin:sent_copy", "paynani-sin", "sin", log)[0],
           "[accounts.paynani-sin] has no IMAP" in row("account:sin:sent_copy", "paynani-sin", "sin", log)[1]))

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
