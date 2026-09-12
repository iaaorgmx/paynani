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
from paynani_lib.i18n_data import CATALOGUES  # noqa: E402
from paynani_lib.server import make_handler  # noqa: E402

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

    round_tripped = envfile.read_env()
    check("envfile: read_env round-trips an owned value", round_tripped["AGENT_EMAIL_ACCOUNT"] == VALID["AGENT_EMAIL_ACCOUNT"])
    check("envfile: read_env also returns an unowned key", round_tripped.get("SOME_OTHER_TOKEN") == "do-not-touch-me")

    quoted = tmp / "quoted.env"
    quoted.write_text('KEY_A="value with spaces"\nKEY_B=\'single\'\nKEY_C=bare\n', encoding="utf-8")
    os.environ["PAYNANI_ENV"] = str(quoted)
    parsed = envfile.read_env()
    check("envfile: one layer of double quotes is stripped", parsed["KEY_A"] == "value with spaces")
    check("envfile: one layer of single quotes is stripped", parsed["KEY_B"] == "single")
    check("envfile: an unquoted value is returned as-is", parsed["KEY_C"] == "bare")

    # Symlink case: write_env must follow the link, never replace it, matching
    # the arrangement INSTALL.md recommends for harness-workspace credentials.
    real_target = tmp / "real.env"
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

print()
if failures:
    print(f"{len(failures)} failed:")
    for name in failures:
        print(f"  {name}")
    sys.exit(1)

print("all paynani CLI checks passed")
