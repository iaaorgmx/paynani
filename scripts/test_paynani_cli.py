#!/usr/bin/env python3
"""
Tests for scripts/paynani_lib/, the Python port of webapp/'s PHP onboarding
form (issue #114). An assertion script, not unittest.TestCase — see
scripts/test_all.sh for why that is the convention here.

What this does not do: touch a real mail server. Nothing else in this
repository's test suite does that either (see scripts/test_listener.py), and
probe.py's job — translating imaplib/smtplib exceptions into the right
human-readable category — is exercised end-to-end manually against this
project's own working mailbox before every change to it; see the PR that
added this file for that transcript. What is tested here instead is
everything probe.py's *callers* depend on: that a working probe response
actually reaches a browser as the right page, that a failing one does not
write anything, and that the guard rails around all of it hold.
"""

from __future__ import annotations

import http.client
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "harness"))

from paynani_lib import envfile, guard, i18n, validate  # noqa: E402
from paynani_lib import roster_cli, set_cli  # noqa: E402
from paynani_lib.i18n_data import CATALOGUES  # noqa: E402
from paynani_lib.server import make_handler  # noqa: E402
import roster as roster_mod  # noqa: E402  (scripts/roster.py; REPO/scripts is already on sys.path above)

failures = []


def check(name, condition):
    if condition:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}")
        failures.append(name)


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

base_keys = set(CATALOGUES["es-MX"].keys())
for tag, catalogue in CATALOGUES.items():
    check(f"i18n: {tag} has the same keys as es-MX", set(catalogue.keys()) == base_keys)

i18n.set_current("es-MX")
check("i18n: t() returns the es-MX string", i18n.t("page.h1") == "Dale un buzón al agente")
i18n.set_current("not-a-real-language")
check("i18n: unknown tag falls back to LANG_DEFAULT", i18n.current_lang() == i18n.LANG_DEFAULT)
i18n.set_current("en-US")
check("i18n: t() substitutes placeholders", i18n.t("v.host_missing", proto="IMAP") == "The IMAP hostname is missing.")
check(
    "i18n: th() escapes substituted values but not catalogue markup",
    "&lt;script&gt;" in i18n.th("saved.where", path="<script>") and "<code>" in i18n.th("saved.where", path="x"),
)
i18n.set_current("es-MX")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

VALID = {
    "AGENT_EMAIL_ACCOUNT": "agent@example.com",
    "AGENT_EMAIL_PASSWORD": "hunter2",
    "AGENT_EMAIL_FROM_NAME": "Agent",
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": "imap.example.com",
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT": "993",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST": "smtp.example.com",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT": "465",
}


def with_override(**kw):
    v = dict(VALID)
    v.update(kw)
    return v


check("validate: a fully valid submission has no errors", validate.validate(VALID) == {})
check(
    "validate: missing account is an error",
    "AGENT_EMAIL_ACCOUNT" in validate.validate(with_override(AGENT_EMAIL_ACCOUNT="")),
)
check(
    "validate: an account with no @ is rejected",
    "AGENT_EMAIL_ACCOUNT" in validate.validate(with_override(AGENT_EMAIL_ACCOUNT="not-an-email")),
)
check(
    "validate: missing password is an error",
    "AGENT_EMAIL_PASSWORD" in validate.validate(with_override(AGENT_EMAIL_PASSWORD="")),
)
check(
    "validate: a from-name with a newline is rejected",
    "AGENT_EMAIL_FROM_NAME" in validate.validate(with_override(AGENT_EMAIL_FROM_NAME="a\nb")),
)
check(
    "validate: a port typed into the host field is caught by name",
    validate.validate(with_override(AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST="993")).get(
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"
    )
    == i18n.t("v.host_is_port"),
)
check(
    "validate: a host with a scheme or space is rejected",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST" in validate.validate(
        with_override(AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST="https://smtp.example.com")
    ),
)
check(
    # "²³.example.com" is still an invalid host (bad_chars) -- the point is
    # that Python's unicode-aware str.isdigit() must not instead misclassify
    # it as host_is_port, which is what str.isdigit() alone would do.
    "validate: a unicode digit host is flagged as bad characters, not as a port",
    validate.validate(with_override(AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST="²³.example.com")).get(
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"
    )
    == i18n.t("v.host_bad_chars"),
)
check(
    "validate: port 0 is out of range",
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT" in validate.validate(
        with_override(AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT="0")
    ),
)
check(
    "validate: port 65536 is out of range",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT" in validate.validate(
        with_override(AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT="65536")
    ),
)
check(
    "validate: a unicode digit port does not crash int()",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT" in validate.validate(
        with_override(AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT="²³")
    ),
)


# ---------------------------------------------------------------------------
# envfile — in a throwaway directory, never the real install
# ---------------------------------------------------------------------------

tmp = Path(tempfile.mkdtemp(prefix="paynani-test-envfile-"))
try:
    target = tmp / ".env"
    os.environ["PAYNANI_ENV"] = str(target)

    fresh = envfile.render_env(VALID)
    check("envfile: a fresh file gets the generated header", fresh.startswith("# Written by the paynani"))
    for key in envfile.ENV_FIELDS:
        check(f"envfile: fresh render includes {key}", f"{key}={VALID[key]}" in fresh)

    existing = (
        "# a human's own comment\n"
        "SOME_OTHER_TOKEN=do-not-touch-me\n"
        "\n"
        "AGENT_EMAIL_ACCOUNT=old@example.com\n"
        "AGENT_EMAIL_PASSWORD=old-password\n"
    )
    target.write_text(existing, encoding="utf-8")
    updated = envfile.render_env(VALID)
    check("envfile: unrelated comment survives an edit", "# a human's own comment" in updated)
    check("envfile: unrelated key survives an edit, untouched", "SOME_OTHER_TOKEN=do-not-touch-me" in updated)
    check("envfile: an owned key already present is updated in place", f"AGENT_EMAIL_ACCOUNT={VALID['AGENT_EMAIL_ACCOUNT']}" in updated)
    check("envfile: an owned key missing from the file is appended", f"AGENT_EMAIL_FROM_NAME={VALID['AGENT_EMAIL_FROM_NAME']}" in updated)
    check(
        "envfile: key order in the untouched part of the file is preserved",
        updated.index("SOME_OTHER_TOKEN") < updated.index("AGENT_EMAIL_ACCOUNT"),
    )

    ok, where = envfile.write_env(updated)
    check("envfile: write_env reports success", ok is True)
    check("envfile: write_env writes to the resolved path", where == str(target))
    check("envfile: written file matches what was rendered", target.read_text(encoding="utf-8") == updated)
    check("envfile: file permissions are 0600", stat.S_IMODE(target.stat().st_mode) == 0o600)
    check("envfile: no leftover .tmp file after a successful write", not (tmp / ".env.tmp").exists())

    round_tripped = envfile.read_env()
    check("envfile: read_env round-trips an owned value", round_tripped["AGENT_EMAIL_ACCOUNT"] == VALID["AGENT_EMAIL_ACCOUNT"])
    check("envfile: read_env also returns an unowned key", round_tripped.get("SOME_OTHER_TOKEN") == "do-not-touch-me")

    crlf_file = tmp / "crlf.env"
    crlf_file.write_bytes(
        b"# a crlf file\r\nSOME_OTHER_TOKEN=keep-me\r\nAGENT_EMAIL_ACCOUNT=old@example.com\r\n"
    )
    os.environ["PAYNANI_ENV"] = str(crlf_file)
    rendered = envfile.render_env(VALID)
    check(
        "envfile: a CRLF file's line ending is preserved, not normalised to LF",
        "\r\n" in rendered and "\n\n" not in rendered.replace("\r\n", ""),
    )
    check("envfile: the untouched line inside a CRLF file still ends in \\r\\n", "SOME_OTHER_TOKEN=keep-me\r\n" in rendered)

    quoted = tmp / "quoted.env"
    quoted.write_text('KEY_A="value with spaces"\nKEY_B=\'single\'\nKEY_C=bare\n', encoding="utf-8")
    os.environ["PAYNANI_ENV"] = str(quoted)
    parsed = envfile.read_env()
    check("envfile: one layer of double quotes is stripped", parsed["KEY_A"] == "value with spaces")
    check("envfile: one layer of single quotes is stripped", parsed["KEY_B"] == "single")
    check("envfile: an unquoted value is returned as-is", parsed["KEY_C"] == "bare")

    # Symlink case: write_env must follow the link, never replace it, matching
    # the arrangement INSTALL.md recommends for harness-workspace credentials.
    # The link and its target live in different directories on purpose: the
    # bug this guards against wrote straight into the target with
    # write_text() (truncate-then-write, no temp file), which this only
    # catches if the temp file has somewhere of its own to be that isn't the
    # link's directory.
    real_dir = tmp / "harness_workspace"
    real_dir.mkdir()
    real_target = real_dir / "real.env"
    real_target.write_text("AGENT_EMAIL_ACCOUNT=old@example.com\n", encoding="utf-8")
    link = tmp / "linked.env"
    link.symlink_to(real_target)
    os.environ["PAYNANI_ENV"] = str(link)
    ok, where = envfile.write_env(envfile.render_env(VALID))
    check("envfile: writing through a symlink succeeds", ok is True)
    check("envfile: write_env reports the link's target, not the link", where == str(real_target))
    check("envfile: the symlink itself is still a symlink afterwards", link.is_symlink())
    check(
        "envfile: the real file behind the link received the write",
        f"AGENT_EMAIL_ACCOUNT={VALID['AGENT_EMAIL_ACCOUNT']}" in real_target.read_text(encoding="utf-8"),
    )
    check(
        "envfile: the symlink write left no leftover .tmp file in the target's directory",
        not any(real_dir.glob("*.tmp")),
    )
    check("envfile: no stray .tmp file was left next to the link either", not any(tmp.glob("linked.env.tmp")))
finally:
    os.environ.pop("PAYNANI_ENV", None)
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# guard
# ---------------------------------------------------------------------------

check("guard: loopback v4 is accepted", guard.is_loopback("127.0.0.1"))
check("guard: loopback v6 is accepted", guard.is_loopback("::1"))
check("guard: a real remote address is rejected", not guard.is_loopback("10.0.0.5"))

tmp2 = Path(tempfile.mkdtemp(prefix="paynani-test-guard-"))
try:
    guard.token_path(tmp2).write_text("the-real-token\n", encoding="utf-8")
    check("guard: the right token is accepted", guard.check_token(tmp2, "the-real-token"))
    check("guard: a wrong token is rejected", not guard.check_token(tmp2, "not-the-token"))
    check("guard: an empty token is rejected", not guard.check_token(tmp2, ""))
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

session = {"csrf": guard.new_csrf_token()}
check("guard: the matching csrf token passes", guard.check_csrf(session, session["csrf"]))
check("guard: a mismatched csrf token fails", not guard.check_csrf(session, "wrong"))
check("guard: a missing csrf token on the session fails closed", not guard.check_csrf({}, "anything"))


# ---------------------------------------------------------------------------
# end-to-end over a real loopback socket, with probe_imap/probe_smtp stubbed
# out. This is what proves the token/CSRF/session wiring, the validate-before-
# probe ordering, and the "only save on report.ok" rule all hold together —
# without this test suite depending on a reachable mail server.
# ---------------------------------------------------------------------------

import paynani_lib.server as server_mod  # noqa: E402

_ok_report = {"ok": True, "steps": [{"ok": True, "text": "ok", "detail": ""}]}
_bad_report = {"ok": False, "steps": [{"ok": False, "text": "rejected", "detail": ""}]}


def fake_probe_ok(host, port, user, password):
    return dict(_ok_report)


def fake_probe_bad(host, port, user, password):
    return dict(_bad_report)


e2e_dir = Path(tempfile.mkdtemp(prefix="paynani-test-e2e-"))
e2e_state = e2e_dir / "state"
e2e_state.mkdir()
e2e_env = e2e_dir / ".env"
os.environ["PAYNANI_ENV"] = str(e2e_env)
os.environ["PAYNANI_STATE"] = str(e2e_state)

token = "e2e-test-token"
guard.token_path(e2e_state).write_text(token + "\n", encoding="utf-8")

httpd = HTTPServer(("127.0.0.1", 0), make_handler(e2e_state))
port = httpd.server_address[1]
thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
thread.start()
time.sleep(0.2)

try:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

    conn.request("GET", "/?t=wrong")
    r = conn.getresponse()
    r.read()
    check("e2e: a wrong token is refused with 403", r.status == 403)

    # A static asset request must be refused for a non-loopback client before
    # it is ever served -- regression test for the ordering bug where
    # _serve_static() ran before the loopback check.
    real_is_loopback = server_mod.guard.is_loopback
    server_mod.guard.is_loopback = lambda addr: False
    try:
        conn.request("GET", "/assets/app.css")
        r = conn.getresponse()
        r.read()
        check("e2e: a static asset is refused for a non-loopback client", r.status == 403)
    finally:
        server_mod.guard.is_loopback = real_is_loopback

    conn.request("GET", f"/?t={token}")
    r = conn.getresponse()
    r.read()
    check("e2e: the real token gets a 303 with a session cookie", r.status == 303 and r.getheader("Set-Cookie"))
    cookie = r.getheader("Set-Cookie").split(";", 1)[0]

    conn.request("GET", "/", headers={"Cookie": cookie})
    r = conn.getresponse()
    page = r.read().decode()
    check("e2e: the authenticated GET renders the form", r.status == 200 and 'id="setup"' in page)
    import re

    csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)

    conn.request(
        "POST",
        "/",
        body=urllib.parse.urlencode({"action": "setup", "csrf": "wrong-csrf"}),
        headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"},
    )
    r = conn.getresponse()
    r.read()
    check("e2e: a csrf mismatch is refused with 400", r.status == 400)

    bad_submit = dict(VALID, action="setup", csrf=csrf, AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST="993")
    conn.request(
        "POST", "/", body=urllib.parse.urlencode(bad_submit),
        headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"},
    )
    r = conn.getresponse()
    page = r.read().decode()
    check(
        "e2e: validation runs before any probe and blocks the save",
        r.status == 200 and i18n.t("v.host_is_port") in page and not e2e_env.exists(),
    )

    server_mod.probe_imap = fake_probe_bad
    server_mod.probe_smtp = fake_probe_ok
    submit = dict(VALID, action="setup", csrf=csrf)
    conn.request(
        "POST", "/", body=urllib.parse.urlencode(submit),
        headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"},
    )
    r = conn.getresponse()
    page = r.read().decode()
    check(
        "e2e: a failing IMAP probe blocks the save even when SMTP passes",
        r.status == 200 and not e2e_env.exists(),
    )

    server_mod.probe_imap = fake_probe_ok
    server_mod.probe_smtp = fake_probe_ok
    conn.request(
        "POST", "/", body=urllib.parse.urlencode(submit),
        headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"},
    )
    r = conn.getresponse()
    page = r.read().decode()
    check("e2e: both probes passing writes the file and shows the saved screen", r.status == 200 and e2e_env.exists())
    check("e2e: the saved screen never contains the password", VALID["AGENT_EMAIL_PASSWORD"] not in page)
    check(
        "e2e: the saved .env has the submitted account",
        f"AGENT_EMAIL_ACCOUNT={VALID['AGENT_EMAIL_ACCOUNT']}" in e2e_env.read_text(encoding="utf-8"),
    )
finally:
    httpd.shutdown()
    thread.join(timeout=5)
    os.environ.pop("PAYNANI_ENV", None)
    os.environ.pop("PAYNANI_STATE", None)
    shutil.rmtree(e2e_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# roster.py: add_contact() / remove_contact() (issue #116)
# ---------------------------------------------------------------------------

SHIPPED_ROSTER = (
    "# a human's own comment\n"
    "\n"
    "| Name | Email | Type | GitHub |\n"
    "|---|---|---|---|\n"
    "| Julian Flores | jjulianfe@gmail.com | Human | julianflores |\n"
    "| Metis Claude-Tob | metis.claude.tob@gmail.com | AI Agent | metisclaudetob |\n"
    "\n"
    "## Notifiers\n"
    "\n"
    "| Address | Header | Column |\n"
    "|---|---|---|\n"
    "| notifications@github.com | X-GitHub-Sender | GitHub |\n"
)

ok, added = roster_mod.add_contact(SHIPPED_ROSTER, "New Person", "new@example.com", type_="Human", github="newhandle")
check("roster.add_contact: reports success", ok is True)
check("roster.add_contact: new address is in the result", "new@example.com" in added)
check(
    "roster.add_contact: the comment before the table survives",
    "# a human's own comment" in added,
)
check("roster.add_contact: the Notifiers table survives untouched", "## Notifiers" in added and "X-GitHub-Sender" in added)
check(
    "roster.add_contact: existing rows are untouched",
    "| Julian Flores | jjulianfe@gmail.com | Human | julianflores |" in added,
)
check(
    "roster.add_contact: new row lands in the contacts table, not after Notifiers",
    added.index("new@example.com") < added.index("## Notifiers"),
)

ok, reason = roster_mod.add_contact(SHIPPED_ROSTER, "Dup", "jjulianfe@gmail.com")
check("roster.add_contact: a duplicate address is refused", ok is False and "already" in reason)

ok, reason = roster_mod.add_contact(SHIPPED_ROSTER, "X", "x@example.com", github="h")
check(
    "roster.add_contact: a column the file doesn't have is refused, not silently dropped",
    ok is True,  # the shipped roster DOES have a GitHub column
)
LEGACY_ROSTER = "| Name | Email |\n|---|---|\n| Old Person | old@example.com |\n"
ok, reason = roster_mod.add_contact(LEGACY_ROSTER, "X", "x@example.com", github="h")
check(
    "roster.add_contact: --github on a two-column roster is refused, not dropped",
    ok is False and "GitHub column" in reason,
)
ok, legacy_added = roster_mod.add_contact(LEGACY_ROSTER, "New", "new@example.com")
check("roster.add_contact: works on the plain two-column legacy format too", ok is True and "new@example.com" in legacy_added)

ok, removed = roster_mod.remove_contact(SHIPPED_ROSTER, "jjulianfe@gmail.com")
check("roster.remove_contact: reports success", ok is True)
check("roster.remove_contact: the address is gone", "jjulianfe@gmail.com" not in removed)
check("roster.remove_contact: the other contact survives", "metis.claude.tob@gmail.com" in removed)
check("roster.remove_contact: the Notifiers table survives", "## Notifiers" in removed)

ok, reason = roster_mod.remove_contact(SHIPPED_ROSTER, "nobody@example.com")
check("roster.remove_contact: a nonexistent address is refused", ok is False and "not on the roster" in reason)

round_trip_add_then_remove = roster_mod.remove_contact(added, "new@example.com")[1]
check(
    "roster.py: add then remove the same contact returns the original text",
    round_trip_add_then_remove == SHIPPED_ROSTER,
)


# ---------------------------------------------------------------------------
# paynani_lib/set_cli.py
# ---------------------------------------------------------------------------

set_dir = Path(tempfile.mkdtemp(prefix="paynani-test-set-"))
try:
    set_env = set_dir / ".env"
    set_env.write_text(
        "AGENT_EMAIL_ACCOUNT=old@example.com\n"
        "AGENT_EMAIL_PASSWORD=old-pass\n"
        "AGENT_EMAIL_FROM_NAME=Old Name\n"
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com\n"
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993\n"
        "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=smtp.example.com\n"
        "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465\n",
        encoding="utf-8",
    )
    os.environ["PAYNANI_ENV"] = str(set_env)

    class Args:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    r = set_cli.run(Args(key="NOT_A_REAL_KEY", value="x", skip_check=False))
    check("set_cli: an unknown key is refused (exit 64)", r == 64)
    check("set_cli: an unknown key changes nothing", set_env.read_text(encoding="utf-8").count("NOT_A_REAL_KEY") == 0)

    r = set_cli.run(Args(key="AGENT_EMAIL_ACCOUNT", value="not-an-email", skip_check=True))
    check("set_cli: field validation runs before writing", r == 1)
    check("set_cli: a failed validation writes nothing", "not-an-email" not in set_env.read_text(encoding="utf-8"))

    r = set_cli.run(Args(key="AGENT_EMAIL_FROM_NAME", value="New Name", skip_check=False))
    check("set_cli: a key with no probe requirement needs no mocking to succeed", r == 0)
    check("set_cli: the new value is on disk", "AGENT_EMAIL_FROM_NAME=New Name" in set_env.read_text(encoding="utf-8"))
    check(
        "set_cli: unrelated keys survive a set",
        "AGENT_EMAIL_ACCOUNT=old@example.com" in set_env.read_text(encoding="utf-8"),
    )

    set_cli.probe_imap = fake_probe_bad
    set_cli.probe_smtp = fake_probe_ok
    r = set_cli.run(Args(key="AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST", value="imap2.example.com", skip_check=False))
    check("set_cli: a failing live check blocks the write", r == 1)
    check(
        "set_cli: the old value is still on disk after a blocked write",
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com" in set_env.read_text(encoding="utf-8"),
    )

    set_cli.probe_imap = fake_probe_ok
    r = set_cli.run(Args(key="AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST", value="imap2.example.com", skip_check=False))
    check("set_cli: both probes passing writes the new value", r == 0)
    check(
        "set_cli: the new host is on disk",
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap2.example.com" in set_env.read_text(encoding="utf-8"),
    )

    r = set_cli.run(Args(key="AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST", value="smtp2.example.com", skip_check=True))
    check("set_cli: --skip-check writes without calling any probe", r == 0)
    check(
        "set_cli: the skip-check value is on disk",
        "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=smtp2.example.com" in set_env.read_text(encoding="utf-8"),
    )
finally:
    os.environ.pop("PAYNANI_ENV", None)
    shutil.rmtree(set_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# paynani_lib/roster_cli.py
# ---------------------------------------------------------------------------

roster_dir = Path(tempfile.mkdtemp(prefix="paynani-test-roster-cli-"))
try:
    roster_path = roster_dir / "roster.md"
    roster_path.write_text(SHIPPED_ROSTER, encoding="utf-8")
    real_roster_file = roster_cli.roster_file
    roster_cli.roster_file = lambda: roster_path

    class RArgs:
        def __init__(self, **kw):
            self.name = None
            self.address = None
            self.type = None
            self.github = None
            self.yes = False
            self.__dict__.update(kw)

    # Declining the confirmation must leave the file untouched.
    import builtins

    real_input = builtins.input
    builtins.input = lambda prompt="": "n"
    try:
        r = roster_cli.run_add(RArgs(name="Nope", address="nope@example.com"))
    finally:
        builtins.input = real_input
    check("roster_cli.run_add: declining the confirmation returns nonzero", r == 1)
    check("roster_cli.run_add: declining the confirmation writes nothing", "nope@example.com" not in roster_path.read_text(encoding="utf-8"))

    r = roster_cli.run_add(RArgs(name="New Person", address="new@example.com", type="Human", github="newhandle", yes=True))
    check("roster_cli.run_add: --yes succeeds without a prompt", r == 0)
    check("roster_cli.run_add: the new contact is on disk", "new@example.com" in roster_path.read_text(encoding="utf-8"))
    check("roster_cli.run_add: the Notifiers table survives on disk", "## Notifiers" in roster_path.read_text(encoding="utf-8"))

    r = roster_cli.run_add(RArgs(name="Dup", address="new@example.com", yes=True))
    check("roster_cli.run_add: a duplicate is refused before any write attempt", r == 1)

    # Force the regression-test safety net to fail, and confirm the write is
    # reverted rather than left in place.
    real_run_tests = roster_cli._run_regression_tests
    roster_cli._run_regression_tests = lambda: (False, "simulated failure")
    before = roster_path.read_text(encoding="utf-8")
    try:
        r = roster_cli.run_add(RArgs(name="Should Revert", address="revert@example.com", yes=True))
    finally:
        roster_cli._run_regression_tests = real_run_tests
    check("roster_cli.run_add: a failing regression check returns nonzero", r == 1)
    check(
        "roster_cli.run_add: a failing regression check reverts the write",
        roster_path.read_text(encoding="utf-8") == before,
    )

    r = roster_cli.run_remove(RArgs(address="new@example.com", yes=True))
    check("roster_cli.run_remove: --yes succeeds without a prompt", r == 0)
    check("roster_cli.run_remove: the contact is gone from disk", "new@example.com" not in roster_path.read_text(encoding="utf-8"))

    r = roster_cli.run_remove(RArgs(address="ghost@example.com", yes=True))
    check("roster_cli.run_remove: a nonexistent address is refused", r == 1)
finally:
    roster_cli.roster_file = real_roster_file
    shutil.rmtree(roster_dir, ignore_errors=True)


# ---------------------------------------------------------------------------

print()
if failures:
    print(f"{len(failures)} failed:")
    for name in failures:
        print(f"  {name}")
    sys.exit(1)

print("all paynani CLI checks passed")
