#!/usr/bin/env python3
"""
Tests for scripts/bootstrap_user.py, the owner's half of the sudo installer
(BOOT-2, #342).

Everything outside the Python process is replaced: HOME and the himalaya config
live in a temporary directory, the roster is redirected the way
test_paynani_cli.py does it, the IMAP and SMTP probes are stubs, and every
command (install.sh, himalaya, doctor, healthcheck, send.sh, git) goes through a
recording runner. What each case reads back is the files the step wrote and the
exact argv the runner was given, so "the password is not on any command line"
is checked against the calls and not assumed.

    python3 scripts/test_bootstrap_user.py
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import bootstrap_user as bu  # noqa: E402
from paynani_lib import accounts_cli, envfile, i18n, probe, roster_cli  # noqa: E402

failures = []
passed = 0


def check(name, condition, detail=""):
    global passed
    if condition:
        passed += 1
        print(f"ok   {name}")
    else:
        failures.append(name)
        print(f"FAIL {name}" + (f"\n     {detail}" if detail else ""))


SECRET = "s3cret-pass-XYZ-1234"
ENV_FILE_TEXT = (
    "AGENT_EMAIL_ACCOUNT=agent@example.com\n"
    f"AGENT_EMAIL_PASSWORD={SECRET}\n"
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=mail.example.com\n"
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993\n"
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=mail.example.com\n"
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465\n"
)


def has(*needles):
    """A matcher: the command line contains every needle."""
    return lambda argv: all(n in " ".join(argv) for n in needles)


class Runner:
    """Records every command; answers 0 and nothing unless a rule says otherwise."""

    def __init__(self):
        self.calls = []
        self.rules = []   # (matcher, returncode, stdout, stderr, side effect or None)
        self.add(has("scripts/paynani", "doctor"), 0, json.dumps({"status": "ok", "checks": []}))

    def add(self, matcher, rc=0, out="", err="", effect=None):
        self.rules.insert(0, (matcher, rc, out, err, effect))

    def __call__(self, argv, **kwargs):
        argv = [str(a) for a in argv]
        self.calls.append((argv, kwargs))
        for matcher, rc, out, err, effect in self.rules:
            if matcher(argv):
                if effect:
                    effect()
                if callable(out):
                    out = out()   # a rule can answer differently each time it is asked
                return subprocess.CompletedProcess(argv, rc, out, err)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def ran(self, *needles):
        return [argv for argv, _ in self.calls if all(n in " ".join(argv) for n in needles)]


def ok_probe(*_args):
    return {"ok": True, "steps": [{"ok": True, "text": "fine", "detail": ""}]}


def bad_probe(*_args):
    return {"ok": False, "steps": [{"ok": False, "text": "The server refused the login.", "detail": "check the password"}]}


class World:
    """A sandbox: HOME, the himalaya config, the credentials file and the roster."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bootstrap-user-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env_dest = self.home / ".claude" / "workspace" / ".env"
        self.roster = self.tmp / "roster.md"
        self.himalaya = self.tmp / "xdg" / "himalaya" / "config.toml"
        self.env_file = self.tmp / "creds.env"
        self.env_file.write_text(ENV_FILE_TEXT, encoding="utf-8")
        self.state = self.tmp / "state"
        self.saved = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "PAYNANI_ENV", "PAYNANI_STATE", "LANG")}
        os.environ["PAYNANI_STATE"] = str(self.state)
        os.environ["HOME"] = str(self.home)
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "xdg")
        os.environ["PAYNANI_ENV"] = str(self.env_dest)
        os.environ["LANG"] = "en_US.UTF-8"
        self.real_roster_file = roster_cli.roster_file
        roster_cli.roster_file = lambda: self.roster
        # The installer must not run test_roster.sh and test_listener.py (#361): this stub FAILS
        # and counts, so a roster step that ran them would fail the run and show in the count.
        # The rest of the real roster flow (creation from the template, the address check,
        # the write, the read back) stays.
        self.regression_runs = []
        self.real_regression = roster_cli._run_regression_tests
        roster_cli._run_regression_tests = lambda: self.regression_runs.append(1) or (False, "must never run in the installer")
        self.real_probes = (probe.probe_imap, probe.probe_smtp)
        self.probe_calls = []
        probe.probe_imap = lambda *a: self.probe_calls.append(("imap", a[0])) or ok_probe()
        probe.probe_smtp = lambda *a: self.probe_calls.append(("smtp", a[0])) or ok_probe()
        self.runner = Runner()
        self.sleeps = []
        self.lines = []

    def close(self):
        roster_cli.roster_file = self.real_roster_file
        roster_cli._run_regression_tests = self.real_regression
        probe.probe_imap, probe.probe_smtp = self.real_probes
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def run(self, *argv, interactive=False, ask=None, secret=None, lang="en_US.UTF-8"):
        os.environ["LANG"] = lang
        self.lines = []
        overrides = {"run": self.runner, "out": lambda *a: self.lines.append(" ".join(str(x) for x in a)),
                     "interactive": interactive, "sleep": lambda seconds: self.sleeps.append(seconds)}
        if ask:
            overrides["ask"] = ask
        if secret:
            overrides["secret"] = secret
        return bu.main(list(argv), ctx_overrides=overrides)

    @property
    def text(self):
        return "\n".join(self.lines)

    def full(self, *extra):
        return ["--runtime", "claudecode", "--ref", "v0.12.0", "--env-file", str(self.env_file),
                "--owner-name", "Ada Owner", "--owner-email", "ada@example.org", "--yes", *extra]

    def fingerprint(self):
        out = {}
        for label, path in (("env", self.env_dest), ("roster", self.roster), ("himalaya", self.himalaya)):
            out[label] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return out


def with_world(function):
    world = World()
    try:
        function(world)
    finally:
        world.close()


# --- a fresh run ---------------------------------------------------------------

def fresh(w):
    code = w.run(*w.full())
    check("a fresh run with --env-file exits 0", code == 0, w.text)
    check("it says ready, in English by default", "Ready. paynani is installed and verified." in w.text, w.text)
    check("the credentials file is written, mode 600",
          w.env_dest.is_file() and stat.S_IMODE(w.env_dest.stat().st_mode) == 0o600)
    env_text = w.env_dest.read_text()
    check("it carries the seven mailbox keys",
          all(k in env_text for k in ("AGENT_EMAIL_ACCOUNT=agent@example.com", "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=mail.example.com",
                                      "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465")))
    himalaya = w.himalaya.read_text()
    check("himalaya gets [accounts.paynani], default, with the v2 inbox alias",
          "[accounts.paynani]" in himalaya and "default = true" in himalaya and 'mailbox.alias.inbox = "INBOX"' in himalaya)
    check("both backends are written", "[accounts.paynani.imap]" in himalaya and "[accounts.paynani.smtp]" in himalaya
          and 'server = "imaps://mail.example.com:993"' in himalaya and 'server = "smtps://mail.example.com:465"' in himalaya)
    check("the password is read by a command from the credentials file, never written",
          f"env_secret.py {w.env_dest} AGENT_EMAIL_PASSWORD" in himalaya.replace("'", "") and SECRET not in himalaya)
    check("roster.md is created with the owner", "ada@example.org" in w.roster.read_text() and "Ada Owner" in w.roster.read_text())
    check("#361: the roster step did not run the regression suites on this machine", w.regression_runs == [], str(w.regression_runs))
    installs = w.runner.ran("install.sh")
    check("install.sh runs once with the runtime", len(installs) == 1 and installs[0][-2:] == ["--runtime", "claudecode"], str(installs))
    check("...with PAYNANI_ENV pointing at the credentials file",
          w.runner.calls[[a for a, _ in w.runner.calls].index(installs[0])][1]["env"].get("PAYNANI_ENV") == str(w.env_dest))
    check("himalaya is checked and a real envelope list is read",
          w.runner.ran("himalaya", "account", "check", "-a", "paynani") and w.runner.ran("himalaya", "envelope", "list", "-a", "paynani"))
    check("doctor and healthcheck both run", w.runner.ran("doctor", "--json") and w.runner.ran("healthcheck.py"))
    check("the steps run in the PRD order",
          [i for i, (a, _) in enumerate(w.runner.calls) if "install.sh" in " ".join(a)][0]
          < [i for i, (a, _) in enumerate(w.runner.calls) if "doctor" in " ".join(a)][0])

    everything = w.text + "\n" + "\n".join(" ".join(a) for a, _ in w.runner.calls)
    check("the password is in no output and on no command line", SECRET not in everything)
    env_seen = [kw.get("env") or {} for _, kw in w.runner.calls]
    check("...nor in the environment given to any command", all(SECRET not in str(e) for e in env_seen))


with_world(fresh)


# --- B2: twice in a row ------------------------------------------------------------

def twice(w):
    first = w.run(*w.full())
    before = w.fingerprint()
    calls_before = len(w.runner.calls)
    probed_before = len(w.probe_calls)
    second = w.run(*w.full())
    after = w.fingerprint()
    check("B2: the second run exits 0 and says ready again", first == 0 and second == 0 and "Ready." in w.text, w.text)
    check("B2: the credentials file, roster and himalaya config are byte-identical", before == after, f"{before} {after}")
    check("B2: a second run does not probe the mailbox again", len(w.probe_calls) == probed_before == 2, str(w.probe_calls))
    check("B2: it still re-verifies", len(w.runner.calls) > calls_before and w.runner.ran("doctor"))


with_world(twice)


# --- B3: what is there is not touched -----------------------------------------------

def existing(w):
    w.env_dest.parent.mkdir(parents=True)
    pre_env = ENV_FILE_TEXT.replace(SECRET, "already-there-pass") + "OTHER_TOOL_TOKEN=keep-me\n"
    w.env_dest.write_text(pre_env, encoding="utf-8")
    w.roster.write_text("| Name | Email |\n|---|---|\n| Someone | someone@example.org |\n", encoding="utf-8")
    w.himalaya.parent.mkdir(parents=True)
    w.himalaya.write_text('[accounts.paynani]\nemail = "agent@example.com"\n# hand edited\n', encoding="utf-8")
    snapshot = (w.env_dest.read_bytes(), w.roster.read_bytes(), w.himalaya.read_bytes())
    code = w.run(*w.full())
    check("B3: with everything already there the run still succeeds", code == 0, w.text)
    check("B3: the .env is not touched (other keys and the existing password survive)", w.env_dest.read_bytes() == snapshot[0])
    check("B3: roster.md is not touched", w.roster.read_bytes() == snapshot[1])
    check("B3: the himalaya section is not touched", w.himalaya.read_bytes() == snapshot[2])
    check("B3: the mailbox is not probed when its credentials are already there", w.probe_calls == [], str(w.probe_calls))


with_world(existing)


def env_without_credentials(w):
    w.env_dest.parent.mkdir(parents=True)
    w.env_dest.write_text("# mine\nOTHER_TOOL_TOKEN=keep-me\n", encoding="utf-8")
    code = w.run(*w.full())
    text = w.env_dest.read_text()
    check("B3: an .env with other keys but no mailbox gets the mailbox without losing them",
          code == 0 and "OTHER_TOOL_TOKEN=keep-me" in text and "# mine" in text and "AGENT_EMAIL_ACCOUNT=agent@example.com" in text, text)


with_world(env_without_credentials)


def paynani_schema(w):
    w.env_file.write_text(
        "PAYNANI_EMAIL=agent@example.com\n"
        f"PAYNANI_PASSWORD={SECRET}\n"
        "PAYNANI_IMAP_HOST=imap.example.com\nPAYNANI_IMAP_PORT=993\n"
        "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=smtp.example.com\nAGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=587\n", encoding="utf-8")
    code = w.run(*w.full())
    himalaya = w.himalaya.read_text()
    check("an --env-file in the PAYNANI_* schema is accepted", code == 0, w.text)
    check("...and lands under the keys the web form writes", "AGENT_EMAIL_ACCOUNT=agent@example.com" in w.env_dest.read_text())
    check("...with its own hosts in himalaya", 'imaps://imap.example.com:993' in himalaya and 'smtps://smtp.example.com:587' in himalaya)


with_world(paynani_schema)


# --- B6 and the runtime -------------------------------------------------------------

def several_runtimes(w):
    (w.home / ".openclaw").mkdir()
    (w.home / ".claude").mkdir()
    code = w.run("--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada", "--owner-email", "ada@example.org", "--yes")
    check("B6: two runtimes detected and --yes without --runtime exits 2", code == 2, w.text)
    check("B6: it names both and does not choose", "openclaw" in w.text and "claudecode" in w.text and "pass --runtime" in w.text)
    check("B6: nothing was written and nothing ran", not w.env_dest.exists() and not w.roster.exists() and w.runner.calls == [])


with_world(several_runtimes)


def one_runtime(w):
    (w.home / ".hermes").mkdir()
    code = w.run("--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada", "--owner-email", "ada@example.org", "--yes")
    check("one runtime detected and --yes: it is used", code == 0 and w.runner.ran("install.sh", "hermes"), w.text)


with_world(one_runtime)


def one_runtime_declined(w):
    (w.home / ".hermes").mkdir()
    code = w.run("--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada", "--owner-email", "ada@example.org",
                 interactive=True, ask=lambda _p: "n")
    check("one runtime detected and the owner says no: exit 2, nothing installed", code == 2 and not w.runner.ran("install.sh"), w.text)


with_world(one_runtime_declined)


def runtime_chosen(w):
    (w.home / ".openclaw").mkdir()
    (w.home / ".codex").mkdir()
    code = w.run("--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada", "--owner-email", "ada@example.org",
                 interactive=True, ask=lambda _p: "codex")
    check("two runtimes and a terminal: the owner chooses", code == 0 and w.runner.ran("install.sh", "codex"), w.text)


with_world(runtime_chosen)


def no_runtime(w):
    check("no runtime anywhere and none given: exit 2", w.run("--ref", "v0.12.0", "--yes") == 2)


with_world(no_runtime)


def bad_runtime(w):
    check("an unknown --runtime: exit 2", w.run("--runtime", "emacs", "--yes") == 2)


with_world(bad_runtime)


# --- credentials: prompts, validation, probes ------------------------------------------

def prompted(w):
    # account, IMAP host, IMAP port (default), SMTP host, SMTP port (default), then "Add them?" for the harness rules
    answers = iter(["agent@example.com", "mail.example.com", "", "mail.example.com", "", "y"])
    code = w.run("--runtime", "claudecode", "--ref", "v0.12.0", "--owner-name", "Ada", "--owner-email", "ada@example.org",
                 interactive=True, ask=lambda _p: next(answers), secret=lambda _p: SECRET)
    check("with a terminal the mailbox is asked for and the ports default to 993 and 465",
          code == 0 and "IMAP_PORT=993" in w.env_dest.read_text() and "SMTP_PORT=465" in w.env_dest.read_text(), w.text)
    check("the password typed is never printed", SECRET not in w.text)


with_world(prompted)


def probe_fails(w):
    probe.probe_imap = bad_probe
    code = w.run(*w.full())
    check("an IMAP probe that fails stops the run at credentials with exit 1", code == 1 and "credentials" in w.text, w.text)
    check("...writes no credentials file", not w.env_dest.exists())
    check("...says what failed without the password", "refused the login" in w.text and SECRET not in w.text)
    check("...says it is not ready and how to repeat the step",
          "Not ready" in w.text and "To repeat it" in w.text and "ready." not in w.text.replace("Not ready", ""), w.text)
    check("...and nothing after it ran", w.runner.calls == [] and not w.roster.exists() and not w.himalaya.exists())


with_world(probe_fails)


def smtp_probe_fails(w):
    probe.probe_smtp = bad_probe
    code = w.run(*w.full())
    check("an SMTP probe that fails stops the run too", code == 1 and "SMTP check failed" in w.text and not w.env_dest.exists(), w.text)


with_world(smtp_probe_fails)


def invalid_values(w):
    w.env_file.write_text(ENV_FILE_TEXT.replace("agent@example.com", "not-an-address"), encoding="utf-8")
    code = w.run(*w.full())
    check("an invalid address is refused by the form's own validation (exit 1)",
          code == 1 and "AGENT_EMAIL_ACCOUNT" in w.text and not w.env_dest.exists(), w.text)


with_world(invalid_values)


def env_file_incomplete(w):
    w.env_file.write_text("AGENT_EMAIL_ACCOUNT=agent@example.com\nAGENT_EMAIL_PASSWORD=x\n", encoding="utf-8")
    code = w.run(*w.full())
    check("an --env-file that lacks hosts: exit 2 naming what is missing",
          code == 2 and "imap_host" in w.text and "smtp_host" in w.text, w.text)


with_world(env_file_incomplete)


def nothing_to_ask(w):
    code = w.run("--runtime", "claudecode", "--ref", "v0.12.0", "--yes")
    check("--yes with no --env-file and no credentials: exit 2", code == 2 and "--env-file" in w.text, w.text)


with_world(nothing_to_ask)


def onboarding_route(w):
    def owner_fills_the_form():
        w.env_dest.parent.mkdir(parents=True, exist_ok=True)
        w.env_dest.write_text(ENV_FILE_TEXT, encoding="utf-8")

    w.runner.add(has("scripts/paynani", "onboard"), 0, effect=owner_fills_the_form)
    # The credentials come from the form; the only thing asked on the way is "Add them?" for the harness rules.
    code = w.run("--runtime", "claudecode", "--ref", "v0.12.0", "--owner-name", "Ada", "--owner-email", "ada@example.org",
                 ask=lambda _prompt: "y")
    check("without a terminal and without --yes the owner is handed `paynani onboard`", len(w.runner.ran("onboard")) == 1, w.text)
    check("...and the run goes on with what the form wrote", code == 0 and "Ready." in w.text and w.runner.ran("install.sh"), w.text)
    check("...telling the owner to open the link", "paynani onboard" in w.text, w.text)


with_world(onboarding_route)


def onboarding_never_filled(w):
    code = w.run("--runtime", "claudecode", "--ref", "v0.12.0", "--owner-name", "Ada", "--owner-email", "ada@example.org")
    check("if the form is never filled the wait ends and the run fails at credentials",
          code == 1 and "no credentials appeared" in w.text and not w.runner.ran("install.sh"), w.text)


with_world(onboarding_never_filled)


# --- roster -------------------------------------------------------------------------------

def owner_validation(w):
    code = w.run(*w.full()[:-3], "--owner-name", "Ada", "--owner-email", "agent@example.com", "--yes")
    check("the owner's address cannot be the agent's own mailbox (exit 1 at roster)",
          code == 1 and "roster" in w.text and not w.runner.ran("install.sh"), w.text)


with_world(owner_validation)


def roster_written_but_unreadable(w):
    # The write goes through, but the file does not recognise the owner when read back with the
    # reader the listener and send.sh use: the step must fail, not report a roster that is dead.
    real_add = roster_cli.add_contact_noninteractive

    def writes_nothing_useful(name, email, **kwargs):
        w.roster.write_text("# an empty roster, with nobody in it\n", encoding="utf-8")
        return "added", str(w.roster)

    roster_cli.add_contact_noninteractive = writes_nothing_useful
    try:
        code = w.run(*w.full())
    finally:
        roster_cli.add_contact_noninteractive = real_add
    check("a roster that cannot be read back with the owner in it fails the step (exit 1)",
          code == 1 and "could not be read back with the owner in it" in w.text and "Ready." not in w.text, w.text)
    check("...and nothing after it ran", not w.runner.ran("install.sh"))


with_world(roster_written_but_unreadable)


def owner_missing(w):
    code = w.run("--runtime", "claudecode", "--ref", "v0.12.0", "--env-file", str(w.env_file), "--yes")
    check("no owner given with --yes and no roster.md: exit 2", code == 2 and "owner" in w.text, w.text)


with_world(owner_missing)


# --- installer and the steps after it ----------------------------------------------------------

def install_codes(w):
    w.runner.add(has("scripts/install.sh"), 10)
    check("install.sh exiting 10 (it changed things) is a success", w.run(*w.full()) == 0, w.text)


with_world(install_codes)


def install_fails(w):
    w.runner.add(has("scripts/install.sh"), 78)
    code = w.run(*w.full())
    check("install.sh failing stops the run at install with exit 1", code == 1 and "install" in w.text and "exited 78" in w.text, w.text)
    check("...and nothing is reported ready", "Ready." not in w.text and not w.runner.ran("healthcheck.py"))


with_world(install_fails)


def himalaya_fails(w):
    w.runner.add(has("himalaya account check"), 1, "", "authentication failed")
    code = w.run(*w.full())
    check("himalaya account check failing stops the run at himalaya", code == 1 and "himalaya" in w.text and not w.runner.ran("install.sh"), w.text)


with_world(himalaya_fails)


def doctor_not_ok(w):
    w.runner.add(has("scripts/paynani", "doctor"), 0, json.dumps({"status": "warning"}))
    code = w.run(*w.full())
    check("doctor not ok: exit 1, the step is named, never ready",
          code == 1 and "verification" in w.text and "doctor says warning" in w.text and "Ready." not in w.text, w.text)


with_world(doctor_not_ok)


def doctor_json(status, rows=()):
    return json.dumps({"status": status, "checks": list(rows)})


def doctor_unknown_then_ok(w):
    answers = iter([doctor_json("unknown"), doctor_json("unknown"), doctor_json("ok")])
    w.runner.add(has("scripts/paynani", "doctor"), 0, lambda: next(answers))
    code = w.run(*w.full())
    check("doctor unknown right after the restart: it waits, and then says ready",
          code == 0 and "Ready." in w.text, w.text)
    check("...asking three times and sleeping two between them", len(w.runner.ran("doctor", "--json")) == 3 and w.sleeps == [2, 2], str(w.sleeps))
    check("...and healthcheck runs once, after doctor is ok", len(w.runner.ran("healthcheck.py")) == 1)


with_world(doctor_unknown_then_ok)


def doctor_always_unknown(w):
    rows = [{"name": "listener", "status": "ok", "summary": "listener service is active"},
            {"name": "version_drift", "status": "unknown", "summary": "no state written yet", "next_command": "scripts/healthcheck.py"}]
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("unknown", rows))
    code = w.run(*w.full())
    check("doctor unknown for good: it gives up after 60 s with exit 1", code == 1 and sum(w.sleeps) == 60 and "Ready." not in w.text, f"{w.sleeps[:3]} {w.text}")
    check("...and lists the rows that are not ok, with their detail",
          "version_drift: unknown - no state written yet" in w.text and "next: scripts/healthcheck.py" in w.text, w.text)
    check("...and not the ones that are", "listener:" not in w.text, w.text)
    check("...saying how long it waited", "after waiting 60s" in w.text, w.text)
    check("...and healthcheck never ran", not w.runner.ran("healthcheck.py"))


with_world(doctor_always_unknown)


WATCH_ROW = {"name": "session_watch_state", "status": "unknown", "summary": "Claude Code session watcher state is observable"}


def doctor_only_the_session_watch_pending(w):
    rows = [{"name": "listener", "status": "ok", "summary": "active"}, WATCH_ROW]
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("unknown", rows))
    code = w.run(*w.full())
    check("a fresh Claude Code install: session_watch_state unknown with no watch ever armed does not stop the run",
          code == 0, w.text)
    check("...it is not waited for (nothing else is unknown)", w.sleeps == [] and len(w.runner.ran("doctor", "--json")) == 1, str(w.sleeps))
    check("...the closing message replaces the plain ready with the owner's step",
          "Ready. One step is left for you: open Claude Code on this machine; the first session arms the mail watch." in w.text
          and "Ready. paynani is installed" not in w.text, w.text)
    check("...and the step says what is pending", "pending: session_watch_state" in w.text, w.text)
    check("...healthcheck still runs", len(w.runner.ran("healthcheck.py")) == 1)


with_world(doctor_only_the_session_watch_pending)


def doctor_pending_in_spanish(w):
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("unknown", [WATCH_ROW]))
    w.run(*w.full(), lang="es_MX.UTF-8")
    check("...and in Spanish when LANG says so",
          "Listo. Falta un paso tuyo: abre Claude Code en esta máquina; la primera sesión arma la vigilancia del correo." in w.text, w.text)


with_world(doctor_pending_in_spanish)


def doctor_pending_codex(w):
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("unknown", [WATCH_ROW]))
    code = w.run("--runtime", "codex", "--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada",
                 "--owner-email", "ada@example.org", "--yes")
    check("with codex the same row is pending, and the message names Codex",
          code == 0 and "open Codex on this machine" in w.text, w.text)


with_world(doctor_pending_codex)


def doctor_pending_other_runtime(w):
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("unknown", [WATCH_ROW]))
    code = w.run("--runtime", "hermes", "--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada",
                 "--owner-email", "ada@example.org", "--yes")
    check("the other runtimes report the generic unknown for that row: accepted too, with the same pending step",
          code == 0 and "open hermes on this machine" in w.text and "pending: session_watch_state" in w.text, w.text)


with_world(doctor_pending_other_runtime)


def doctor_pending_plus_a_real_unknown(w):
    answers = iter([doctor_json("unknown", [WATCH_ROW, {"name": "version_drift", "status": "unknown", "summary": "no state yet"}]),
                    doctor_json("unknown", [WATCH_ROW])])
    w.runner.add(has("scripts/paynani", "doctor"), 0, lambda: next(answers))
    code = w.run(*w.full())
    check("another unknown row is waited for, and the pending one does not keep it waiting after that",
          code == 0 and w.sleeps == [2] and "pending: session_watch_state" in w.text, f"{w.sleeps} {w.text}")


with_world(doctor_pending_plus_a_real_unknown)


def doctor_himalaya_unknown(w):
    rows = [WATCH_ROW, {"name": "himalaya", "status": "unknown", "summary": "himalaya binary could not be run"}]
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("unknown", rows))
    code = w.run(*w.full())
    check("himalaya unknown retries and, if it stays, fails with exit 1 listing only that row",
          code == 1 and sum(w.sleeps) == 60 and "himalaya: unknown" in w.text and "session_watch_state:" not in w.text, w.text)


with_world(doctor_himalaya_unknown)


def doctor_stale_watch_is_a_failure(w):
    rows = [{"name": "session_watch_state", "status": "warning", "summary": "no Claude Code session is watching mail"}]
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("warning", rows))
    code = w.run(*w.full())
    check("a watch that WAS armed and went stale is a warning, and that fails (only unknown is pending)",
          code == 1 and w.sleeps == [] and "session_watch_state: warning" in w.text and "Ready." not in w.text, w.text)


with_world(doctor_stale_watch_is_a_failure)


def doctor_pending_but_blocked_elsewhere(w):
    rows = [{"name": "session_watch_state", "status": "unknown", "summary": "watcher state"},
            {"name": "smtp", "status": "blocked", "summary": "himalaya config is missing"}]
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("blocked", rows))
    code = w.run(*w.full())
    check("pending does not hide a real failure: smtp blocked fails at once, and only it is listed",
          code == 1 and w.sleeps == [] and "smtp: blocked" in w.text and "session_watch_state:" not in w.text, w.text)


with_world(doctor_pending_but_blocked_elsewhere)


def doctor_warning_does_not_wait(w):
    rows = [{"name": "version_drift", "status": "warning", "summary": "listener is on the old version"}]
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("warning", rows))
    code = w.run(*w.full())
    check("doctor warning fails at once, without waiting", code == 1 and w.sleeps == [] and len(w.runner.ran("doctor", "--json")) == 1, str(w.sleeps))
    check("...and names the row", "version_drift: warning - listener is on the old version" in w.text, w.text)


with_world(doctor_warning_does_not_wait)


def doctor_blocked_does_not_wait(w):
    w.runner.add(has("scripts/paynani", "doctor"), 0, doctor_json("blocked", [{"name": "runtime", "status": "blocked", "summary": "no runtime"}]))
    code = w.run(*w.full())
    check("doctor blocked fails at once too", code == 1 and w.sleeps == [] and "runtime: blocked - no runtime" in w.text, w.text)


with_world(doctor_blocked_does_not_wait)


def doctor_garbage(w):
    w.runner.add(has("scripts/paynani", "doctor"), 1, "not json at all")
    code = w.run(*w.full())
    check("doctor output that is not JSON fails without waiting", code == 1 and w.sleeps == [] and "gave no status" in w.text, w.text)


with_world(doctor_garbage)


def healthcheck_fails(w):
    w.runner.add(has("healthcheck.py"), 1, "mail cannot be detected")
    code = w.run(*w.full())
    check("healthcheck failing: exit 1, never ready", code == 1 and "healthcheck.py failed" in w.text and "Ready." not in w.text, w.text)


with_world(healthcheck_fails)


def test_mail(w):
    code = w.run(*w.full("--test-mail"))
    sent = w.runner.ran("send.sh")
    check("--test-mail sends one message to the owner", code == 0 and len(sent) == 1 and "ada@example.org" in sent[0], str(sent))
    check("...and it is only sent after doctor and healthcheck passed",
          [i for i, (a, _) in enumerate(w.runner.calls) if "send.sh" in " ".join(a)][0]
          > [i for i, (a, _) in enumerate(w.runner.calls) if "healthcheck.py" in " ".join(a)][0])


with_world(test_mail)


def test_mail_fails(w):
    w.runner.add(has("scripts/send.sh"), 1, "", "no route")
    code = w.run(*w.full("--test-mail"))
    check("--test-mail failing is a failed verification, not a silent pass", code == 1 and "send.sh" in w.text and "Ready." not in w.text, w.text)


with_world(test_mail_fails)


# --- harness permission rules ------------------------------------------------------------------------

def rules_written(w):
    code = w.run(*w.full())
    settings = w.home / ".claude" / "settings.json"
    allow = json.loads(settings.read_text())["permissions"]["allow"] if settings.exists() else []
    check("with --yes the Claude Code permission rules are written", code == 0 and any(str(ROOT / "scripts" / "paynani") in r for r in allow), w.text)
    check("...and only for paynani's own commands", len(allow) == 3 and all("paynani" in r or "send.sh" in r or "session_watch.sh" in r for r in allow), str(allow))


with_world(rules_written)


def rules_no_terminal(w):
    def eof(_prompt):
        raise EOFError

    code = w.run("--runtime", "claudecode", "--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada",
                 "--owner-email", "ada@example.org", ask=eof)
    check("without --yes and without a terminal the rules step fails and says to use --yes",
          code == 1 and "harness rules" in w.text and "--yes" in w.text and "Ready." not in w.text, w.text)


with_world(rules_no_terminal)


def rules_other_runtime(w):
    code = w.run("--runtime", "codex", "--ref", "v0.12.0", "--env-file", str(w.env_file), "--owner-name", "Ada",
                 "--owner-email", "ada@example.org", "--yes")
    check("a runtime without automatic rules prints what to add and still succeeds", code == 0 and "scripts/paynani" in w.text, w.text)
    check("...and writes no Claude Code settings", not (w.home / ".claude" / "settings.json").exists())


with_world(rules_other_runtime)


# --- --upgrade ------------------------------------------------------------------------------------------

def upgrade(w):
    w.run(*w.full())
    before = w.fingerprint()
    w.runner.calls.clear()
    code = w.run(*w.full("--upgrade"))
    check("--upgrade fetches the tags and applies the ref", code == 0 and w.runner.ran("fetch", "--tags") and w.runner.ran("version.sh", "--apply", "v0.12.0"), w.text)
    check("--upgrade does not run install.sh", not w.runner.ran("install.sh"))
    check("--upgrade leaves the credentials, roster and himalaya as they were", w.fingerprint() == before)
    check("--upgrade repeats the verification", w.runner.ran("doctor") and w.runner.ran("healthcheck.py"))


with_world(upgrade)


def upgrade_without_ref(w):
    code = w.run("--runtime", "claudecode", "--env-file", str(w.env_file), "--owner-name", "Ada", "--owner-email", "ada@example.org",
                 "--yes", "--upgrade")
    check("--upgrade without --ref: exit 1 at upgrade", code == 1 and "--ref" in w.text, w.text)


with_world(upgrade_without_ref)


def upgrade_fails(w):
    w.runner.add(has("scripts/version.sh"), 1)
    code = w.run(*w.full("--upgrade"))
    check("version.sh --apply failing stops the upgrade", code == 1 and "upgrade" in w.text and "Ready." not in w.text, w.text)


with_world(upgrade_fails)


# --- --dry-run ----------------------------------------------------------------------------------------------

def dry_run(w):
    code = w.run(*w.full("--dry-run", "--with-sms", "--test-mail"))
    check("--dry-run exits 0", code == 0, w.text)
    check("--dry-run prints the actions with would:", "would:" in w.text and "install.sh --runtime claudecode --with-sms" in w.text, w.text)
    check("--dry-run runs no command at all", w.runner.calls == [])
    check("--dry-run writes nothing: no credentials, roster, himalaya or settings",
          not w.env_dest.exists() and not w.roster.exists() and not w.himalaya.exists() and not (w.home / ".claude").exists())
    check("--dry-run does not say ready", "Ready." not in w.text)
    check("--dry-run never touches the mailbox", w.probe_calls == [], str(w.probe_calls))


with_world(dry_run)


# --- flags and language -----------------------------------------------------------------------------------------

def with_sms(w):
    w.run(*w.full("--with-sms"))
    check("--with-sms reaches install.sh", w.runner.ran("install.sh", "--with-sms"))


with_world(with_sms)


def spanish(w):
    code = w.run(*w.full(), lang="es_MX.UTF-8")
    check("with LANG=es_* the owner-facing summary is in Spanish", code == 0 and "Listo. paynani quedó instalado y verificado." in w.text, w.text)


with_world(spanish)


def owner_flags_together(w):
    check("--owner-name without --owner-email: exit 2", bu.main(["--owner-name", "Ada"]) == 2)


with_world(owner_flags_together)

print(f"\n{passed} passed, {len(failures)} failed")
if failures:
    print("failed:", "; ".join(failures))
raise SystemExit(1 if failures else 0)
