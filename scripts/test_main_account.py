#!/usr/bin/env python3
"""
#591 N2: any change to the main mailbox account from PaynaniWeb. .env and the
[accounts.paynani] tables of himalaya change together or not at all: probe
first, keep what was there, write, restart, and roll back if the listener does
not come back. The roster is never touched; no value reaches Result or the audit.
"""

from __future__ import annotations

import fcntl
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from paynani_lib import envfile, listener_control  # noqa: E402
from paynani_lib import main_account as ma  # noqa: E402

passed = failed = 0


def check(desc, condition, detail=""):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}" + (f"\n       {detail}" if detail else ""))
        failed += 1


OLD_ENV = ("# hand-written comment\n"
           "AGENT_EMAIL_ACCOUNT=viejo@example.org\n"
           "AGENT_EMAIL_PASSWORD=old-secret\n"
           "AGENT_EMAIL_FROM_NAME=Agente\n"
           "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.org\n"
           "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993\n"
           "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=smtp.example.org\n"
           "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465\n"
           "OTHER_TOKEN=keep-me\n")

OLD_HIMALAYA = ('[accounts.paynani]\n'
                'email = "viejo@example.org"\n'
                'display-name = "Agente"\n'
                'default = true\n'
                'mailbox.alias.inbox = "INBOX"\n'
                'mailbox.alias.sent = "[Gmail]/Sent Mail"\n'
                '\n'
                '[accounts.paynani.imap]\n'
                'server = "imaps://imap.example.org:993"\n'
                '[accounts.paynani.imap.sasl.plain]\n'
                'authcid = "viejo@example.org"\n'
                'password.cmd = "python3 env_secret.py .env AGENT_EMAIL_PASSWORD"\n'
                '\n'
                '[accounts.paynani.smtp]\n'
                'server = "smtps://smtp.example.org:465"\n'
                '[accounts.paynani.smtp.sasl.plain]\n'
                'authcid = "viejo@example.org"\n'
                'password.cmd = "python3 env_secret.py .env AGENT_EMAIL_PASSWORD"\n'
                '\n'
                '[accounts.paynani-ventas]\n'
                'email = "ventas@example.org"\n'
                '[accounts.paynani-ventas.imap.sasl.plain]\n'
                'authcid = "ventas@example.org"\n')

OLD_STATE = {"mailbox": "INBOX", "uidvalidity": "1", "last_uid": 1503, "account": "viejo@example.org",
             "heartbeat_at": "2026-10-30T20:00:00Z", "pid": 100, "imap_reconnect_attempts": 3}

NEW = {"AGENT_EMAIL_ACCOUNT": "nuevo@example.net", "AGENT_EMAIL_PASSWORD": "new-secret",
       "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": "imap.example.net",
       "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST": "smtp.example.net"}


def ok_probe(*args):
    return {"ok": True, "steps": [{"ok": True, "text": "login", "detail": ""}]}


def bad_probe(*args):
    return {"ok": False, "steps": [{"ok": False, "text": "login", "detail": "AUTHENTICATIONFAILED"}]}


def raising_probe(host, port, user, password):
    raise ConnectionResetError("reset while sending new-secret")


class Fake:
    """The listener as listener_control sees it, with every call recorded."""

    def __init__(self, back_on_new=True, back_on_old=True, restart_ok=True):
        self.back_on_new, self.back_on_old, self.restart_ok = back_on_new, back_on_old, restart_ok
        self.restarts, self.waits = 0, []

    def restart(self, account=None):
        self.restarts += 1
        if not self.restart_ok and self.restarts == 1:
            return listener_control.Restart(False, "failed", "", 100, "Unit not found")
        return listener_control.Restart(True, "requested", "2026-10-30T21:00:00Z", 100 + self.restarts)

    def wait(self, since, account=None, timeout_s=60, *, expect=None, previous_pid=None, **_):
        self.waits.append((expect, previous_pid))
        back = self.back_on_new if expect == "nuevo@example.net" else self.back_on_old
        if back:
            return listener_control.Status("connected", "2026-10-30T21:00:01Z", 500, "INBOX", expect)
        return listener_control.Status("waiting", last_error="login rejected by imap.example.net for nuevo@example.net",
                                       detail="the listener is not connected yet")


def scenario(td, *, imap=ok_probe, smtp=ok_probe, fake=None, additional=(), himalaya=OLD_HIMALAYA,
             uidnext=lambda merged: {"uidvalidity": "77", "last_uid": 41}):
    td = pathlib.Path(td)
    env, cfg, state = td / ".env", td / "himalaya" / "config.toml", td / "state"
    env.write_text(OLD_ENV)
    cfg.parent.mkdir()
    if himalaya is not None:
        cfg.write_text(himalaya)
        cfg.chmod(0o640)
    state.mkdir()
    (state / "idle.json").write_text(json.dumps(OLD_STATE))
    roster = td / "roster.md"
    roster.write_text("| Name | Email |\n|---|---|\n| Julian | julian@example.org |\n")
    fake = fake or Fake()
    saved = (envfile.env_path, ma.himalaya_config_path, listener_control.state_dir, ma.probe_imap,
             ma.probe_smtp, ma.accounts.load, listener_control.restart, listener_control.wait, ma._uidnext)
    envfile.env_path = lambda: env
    ma.himalaya_config_path = lambda: cfg
    listener_control.state_dir = lambda: state
    ma.probe_imap, ma.probe_smtp = imap, smtp
    ma.accounts.load = lambda path=None: [{"id": "ventas", "email": a} for a in additional]
    listener_control.restart, listener_control.wait = fake.restart, fake.wait
    ma._uidnext = uidnext
    return env, cfg, state, roster, fake, saved


def restore(saved):
    (envfile.env_path, ma.himalaya_config_path, listener_control.state_dir, ma.probe_imap,
     ma.probe_smtp, ma.accounts.load, listener_control.restart, listener_control.wait, ma._uidnext) = saved


def audit(state):
    path = state / "main_account_changes.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def files_as_before(env, cfg, state):
    return (env.read_text() == OLD_ENV and cfg.read_text() == OLD_HIMALAYA
            and json.loads((state / "idle.json").read_text()) == OLD_STATE)


check("the public names are envfile's", ma.FIELDS is envfile.ENV_FIELDS)

# --- check: nothing is written ----------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td)
    try:
        r = ma.check(NEW)
        check("check passes a mailbox that probes fine", r.ok and r.code == "checked", r)
        check("check names the fields that change, in schema order",
              r.changed == ["AGENT_EMAIL_ACCOUNT", "AGENT_EMAIL_PASSWORD", "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST",
                            "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST"], r.changed)
        check("check tags each probe step with its protocol", [s["protocol"] for s in r.probe] == ["imap", "smtp"])
        check("check writes nothing and restarts nothing", files_as_before(env, cfg, state) and fake.restarts == 0)
    finally:
        restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td)
    try:
        r = ma.update({"AGENT_EMAIL_SIGNATURE": "x"}, by="web")
        check("a key outside the schema is unknown_field", not r.ok and r.code == "unknown_field", r)
        r = ma.update({"AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": "imap.example.org"}, by="web")
        check("a change to the current value is unchanged and writes nothing",
              r.ok and r.code == "unchanged" and files_as_before(env, cfg, state) and fake.restarts == 0, r)
        r = ma.update({"AGENT_EMAIL_ACCOUNT": "no-es-correo"}, by="web")
        check("an invalid address is refused with its field and no value",
              not r.ok and r.code == "invalid" and "AGENT_EMAIL_ACCOUNT" in r.field_errors
              and "no-es-correo" not in repr(r), r)
        check("refusals before writing are not audited", audit(state) == [])
    finally:
        restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td, additional=("Nuevo@Example.net",))
    try:
        r = ma.update(NEW, by="web")
        check("an address that is already an additional account is refused",
              not r.ok and r.code == "is_additional_account" and files_as_before(env, cfg, state), r)
    finally:
        restore(saved)

for name, kwargs in (("a failed SMTP probe", {"smtp": bad_probe}),
                     ("a probe that raises", {"imap": raising_probe})):
    with tempfile.TemporaryDirectory() as td:
        env, cfg, state, roster, fake, saved = scenario(td, **kwargs)
        try:
            r = ma.update(NEW, by="web")
            check(f"{name} stops the change before writing",
                  not r.ok and r.code == "probe_failed" and files_as_before(env, cfg, state) and fake.restarts == 0, r)
            check(f"{name} does not leak the exception text", "new-secret" not in repr(r), r)
        finally:
            restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td, uidnext=lambda merged: None)
    try:
        r = ma.update(NEW, by="web")
        check("a new INBOX without UIDNEXT is not switched to blind",
              not r.ok and r.code == "probe_failed" and "UIDNEXT" in r.detail and files_as_before(env, cfg, state), r)
    finally:
        restore(saved)

# --- update: a new mailbox ----------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td)
    roster_before = roster.read_text()
    try:
        r = ma.update(NEW, by="web:203.0.113.5", timeout_s=5)
        check("the change succeeds and the listener is back", r.ok and r.code == "updated" and r.ready == "connected", r)
        text = env.read_text()
        check(".env holds the new mailbox",
              "AGENT_EMAIL_ACCOUNT=nuevo@example.net" in text and "AGENT_EMAIL_PASSWORD=new-secret" in text
              and "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.net" in text, text)
        check(".env keeps its comments, unknown keys and what did not change",
              "# hand-written comment" in text and "OTHER_TOKEN=keep-me" in text
              and "AGENT_EMAIL_FROM_NAME=Agente" in text and "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993" in text, text)
        h = cfg.read_text()
        check("himalaya's main tables point at the new mailbox",
              'email = "nuevo@example.net"' in h and 'server = "imaps://imap.example.net:993"' in h
              and 'server = "smtps://smtp.example.net:465"' in h and h.count('authcid = "nuevo@example.net"') == 2, h)
        check("himalaya keeps the other lines, and the password stays out of it",
              'mailbox.alias.sent = "[Gmail]/Sent Mail"' in h and 'display-name = "Agente"' in h
              and h.count("password.cmd") == 2 and "new-secret" not in h, h)
        check("an additional account's tables are not touched",
              '[accounts.paynani-ventas]\nemail = "ventas@example.org"' in h and 'authcid = "ventas@example.org"' in h, h)
        check("the himalaya config keeps its permissions", (cfg.stat().st_mode & 0o777) == 0o640, oct(cfg.stat().st_mode))
        s = json.loads((state / "idle.json").read_text())
        check("the cursor starts at the UIDNEXT the probe saw, for the new address",
              s["last_uid"] == 41 and s["uidvalidity"] == "77" and s["account"] == "nuevo@example.net"
              and s["mailbox"] == "INBOX", s)
        check("the listener telemetry stays", s.get("imap_reconnect_attempts") == 3, s)
        check("the wait asks for the new address and a new process", fake.waits == [("nuevo@example.net", 101)],
              fake.waits)
        check("roster.md is not touched", roster.read_text() == roster_before)
        log = audit(state)
        check("the change is audited with who, which fields and the result",
              len(log) == 1 and log[0]["by"] == "web:203.0.113.5" and log[0]["result"] == "updated"
              and log[0]["fields"] == r.changed and log[0]["rollback"] == "none", log)
        leaks = json.dumps(log) + repr(r)
        check("no password, address or host reaches the audit or the Result",
              not any(v in leaks for v in ("new-secret", "old-secret", "nuevo@example.net", "viejo@example.org",
                                           "imap.example.net")), leaks)
    finally:
        restore(saved)

# --- update: the same mailbox -------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td)
    try:
        r = ma.update({"AGENT_EMAIL_PASSWORD": "rotated", "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT": "587"},
                      by="web", timeout_s=5)
        s = json.loads((state / "idle.json").read_text())
        check("the same address keeps its cursor", r.ok and s.get("last_uid") == 1503, (r, s))
        h = cfg.read_text()
        check("a new port keeps the scheme the table had", 'server = "smtps://smtp.example.org:587"' in h, h)
        check("a password change restarts and waits for the same address", fake.waits == [("viejo@example.org", 101)],
              fake.waits)
    finally:
        restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td)
    try:
        r = ma.update({"AGENT_EMAIL_FROM_NAME": "Agente Nuevo"}, by="web")
        h = cfg.read_text()
        check("a new sender name reaches .env and display-name without a probe or a restart",
              r.ok and r.code == "updated" and r.probe == [] and fake.restarts == 0
              and "AGENT_EMAIL_FROM_NAME=Agente Nuevo" in env.read_text() and 'display-name = "Agente Nuevo"' in h, r)
    finally:
        restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td, himalaya=None)
    try:
        r = ma.update(NEW, by="web", timeout_s=5)
        h = cfg.read_text()
        check("with no himalaya config, the main tables are written from scratch",
              r.ok and "[accounts.paynani]" in h and "default = true" in h and 'email = "nuevo@example.net"' in h, h)
    finally:
        restore(saved)

# --- update: rollback -----------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td, fake=Fake(back_on_new=False))
    try:
        r = ma.update(NEW, by="web", timeout_s=1)
        check("a listener that does not come back on the new mailbox rolls back",
              not r.ok and r.code == "not_ready" and r.rollback == "ok" and r.ready == "waiting", r)
        check("the reason is told without the address", r.detail == "the server refused the login", r.detail)
        check("after the rollback the three files are as they were", files_as_before(env, cfg, state))
        check("the rollback restarts and waits for the old address",
              fake.waits == [("nuevo@example.net", 101), ("viejo@example.org", 102)], fake.waits)
        check("the rollback is audited", audit(state)[-1]["result"] == "not_ready"
              and audit(state)[-1]["rollback"] == "ok", audit(state))
    finally:
        restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td, fake=Fake(back_on_new=False, back_on_old=False))
    try:
        r = ma.update(NEW, by="web", timeout_s=1)
        check("a rollback whose listener does not come back either says so",
              not r.ok and r.code == "not_ready" and r.rollback == "failed" and files_as_before(env, cfg, state), r)
    finally:
        restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td, fake=Fake(restart_ok=False))
    try:
        r = ma.update(NEW, by="web", timeout_s=1)
        check("a restart that fails rolls back",
              not r.ok and r.code == "restart_failed" and r.rollback == "ok" and files_as_before(env, cfg, state), r)
    finally:
        restore(saved)

with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td)
    real_write = ma._write_himalaya

    def broken(path, text):
        raise OSError(28, "No space left on device", str(path))
    ma._write_himalaya = broken
    try:
        r = ma.update(NEW, by="web", timeout_s=1)
        check("a himalaya write that fails rolls .env back",
              not r.ok and r.code == "write_failed" and env.read_text() == OLD_ENV, (r, env.read_text()))
    finally:
        ma._write_himalaya = real_write
        restore(saved)

# --- one change at a time ---------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    env, cfg, state, roster, fake, saved = scenario(td)
    try:
        with open(state / "main_account.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = ma.update(NEW, by="web", timeout_s=1)
        check("a second change while one is running is busy and writes nothing",
              not r.ok and r.code == "busy" and files_as_before(env, cfg, state) and fake.restarts == 0, r)
        check("once the first one is done the lock is free again", ma.update(NEW, by="web", timeout_s=1).ok)
    finally:
        restore(saved)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
