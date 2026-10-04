#!/usr/bin/env python3
"""
The owner's half of the sudo installer (BOOT-2, #342).

`bootstrap.sh` does what needs root -- packages, himalaya, linger, the clone --
and then runs this as the owner, with the arguments of the hand over fixed in
#341:

    python3 scripts/bootstrap_user.py --runtime R --ref REF [--env-file F]
        [--owner-name N --owner-email E] [--yes] [--with-sms] [--upgrade]
        [--dry-run] [--test-mail]

Everything that belongs to the owner happens here, in the order of the PRD
(#335, steps 7 to 13): the runtime, the mailbox credentials, the himalaya
account, the roster row, the installer, the harness permission rules, and a
verification that only says "ready" when `paynani doctor` and `healthcheck.py`
both come out ok.

Each step is a function that returns (ok, detail). `main()` runs them in order
and stops at the first one that fails, naming the step and the command that
repeats it. The mailbox password is held in memory only: it is never printed,
never put in a command line, and never written anywhere but the credentials
file, mode 600.

Exit codes: 0 ready, 1 a step failed, 2 missing data (with --yes or without a
terminal) or an invalid option.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "scripts"))

import paths as harness_paths  # noqa: E402
from paynani_lib import accounts_cli, envfile, himalaya_config, i18n, probe, roster_cli, validate  # noqa: E402

EX_OK, EX_STEP, EX_USAGE = 0, 1, 2
RUNTIMES = ("openclaw", "hermes", "claudecode", "codex", "opencode")
RUNTIME_OF_ROOT = {".openclaw": "openclaw", ".hermes": "hermes", ".claude": "claudecode",
                   ".codex": "codex", ".opencode": "opencode"}
HIMALAYA_NAME = "paynani"

# Where each piece of the mailbox lives, in the order the listener prefers them
# (scripts/idle_listener.py KEYS): PAYNANI_* wins where both are set. The SMTP
# side only has the AGENT_EMAIL_ names; himalaya carries it for the listener.
SCHEMA = {
    "account": ("PAYNANI_EMAIL", "AGENT_EMAIL_ACCOUNT"),
    "password": ("PAYNANI_PASSWORD", "AGENT_EMAIL_PASSWORD"),
    "imap_host": ("PAYNANI_IMAP_HOST", "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"),
    "imap_port": ("PAYNANI_IMAP_PORT", "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT"),
    "smtp_host": ("AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST",),
    "smtp_port": ("AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT",),
    "from_name": ("AGENT_EMAIL_FROM_NAME",),
}
REQUIRED = ("account", "password", "imap_host", "imap_port")
ENV_KEY = {
    "account": "AGENT_EMAIL_ACCOUNT", "password": "AGENT_EMAIL_PASSWORD",
    "from_name": "AGENT_EMAIL_FROM_NAME",
    "imap_host": "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST",
    "imap_port": "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT",
    "smtp_host": "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST",
    "smtp_port": "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT",
}
ONBOARD_WAIT_SECONDS = 15 * 60
# install.sh has just restarted the listener and the dispatcher, and for a few seconds
# `paynani doctor` answers "unknown" while the new processes have not written their
# state yet (version_drift since #266: unknown right after a restart, ok about 10 s
# later). Only "unknown" is waited for; "warning" and "blocked" do not fix themselves.
DOCTOR_WAIT_SECONDS = 60
DOCTOR_POLL_SECONDS = 2


class NeedData(Exception):
    """Something is missing and nobody can be asked: exit 2, not 1."""


@dataclass
class Ctx:
    args: argparse.Namespace
    home: Path
    interactive: bool
    ask: Callable[[str], str] = input
    secret: Callable[[str], str] = getpass.getpass
    run: Callable = subprocess.run
    sleep: Callable[[float], None] = time.sleep
    out: Callable[..., None] = print
    runtime: str = ""
    env_path: Path | None = None
    mailbox: dict = field(default_factory=dict)   # the pieces of SCHEMA; holds the password
    password_key: str = "AGENT_EMAIL_PASSWORD"
    owner: str = ""

    def say(self, text: str) -> None:
        self.out(text)

    def would(self, text: str) -> None:
        self.out(f"would: {text}")

    def L(self, key: str, **vars) -> str:
        return i18n.t(key, **vars)


# --- small helpers -----------------------------------------------------------

def parse_env_file(path: Path) -> dict:
    """KEY=value lines of any file, the way envfile.read_env reads the real one."""
    out = {}
    for line in re.split(r"\r\n|\n|\r", Path(path).read_text(encoding="utf-8-sig")):
        match = envfile._KEY_VALUE_RE.match(line)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[match.group(1)] = value
    return out


def mailbox_from(values: dict) -> dict:
    """The pieces of the mailbox found in an env mapping, whichever schema names them."""
    found = {}
    for piece, names in SCHEMA.items():
        for name in names:
            value = (values.get(name) or "").strip()
            if value:
                found[piece] = value
                found[f"{piece}_key"] = name
                break
    return found


def env_values(mailbox: dict) -> dict:
    return {ENV_KEY[piece]: mailbox.get(piece, "") for piece in ENV_KEY}


def run_quiet(ctx: Ctx, argv, **kwargs):
    return ctx.run([str(a) for a in argv], capture_output=True, text=True, **kwargs)


def himalaya_env(ctx: Ctx) -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{ctx.home}/.local/bin:{env.get('PATH', '')}"
    return env


def first_lines(text: str, count: int = 6) -> str:
    return "\n".join((text or "").strip().splitlines()[:count])


def need_terminal(ctx: Ctx, what: str) -> None:
    if not ctx.interactive:
        raise NeedData(f"{what} is missing and there is nobody to ask (--yes or no terminal)")


# --- 7. runtime --------------------------------------------------------------

def detect_runtimes(home: Path) -> list[str]:
    found = []
    for root in harness_paths.HARNESS_ROOTS:
        name = RUNTIME_OF_ROOT.get(Path(root).name)
        if name and (Path(home) / Path(root).name).is_dir():
            found.append(name)
    return found


def step_runtime(ctx: Ctx):
    chosen = ctx.args.runtime
    if chosen:
        if chosen not in RUNTIMES:
            raise NeedData(f"--runtime must be one of: {' '.join(RUNTIMES)}")
        ctx.runtime = chosen
        return True, f"{chosen} (given)"
    found = detect_runtimes(ctx.home)
    if not found:
        raise NeedData("no harness found on this host: pass --runtime")
    if len(found) == 1:
        if ctx.args.yes:
            ctx.runtime = found[0]
            return True, f"{found[0]} (the only one found)"
        need_terminal(ctx, "the runtime")
        answer = ctx.ask(ctx.L("b.runtime_confirm", runtime=found[0])).strip().lower()
        if answer not in ("", "y", "yes", "s", "si", "sí", "o", "oui", "sim"):
            raise NeedData("not confirmed: pass --runtime")
        ctx.runtime = found[0]
        return True, f"{found[0]} (confirmed)"
    # Several: never choose alone (B6).
    if ctx.args.yes or not ctx.interactive:
        raise NeedData(f"several runtimes found ({' '.join(found)}): pass --runtime")
    answer = ctx.ask(ctx.L("b.runtime_choose", list=", ".join(found))).strip()
    if answer not in found:
        raise NeedData(f"'{answer}' is not one of: {' '.join(found)}")
    ctx.runtime = answer
    return True, f"{answer} (chosen)"


# --- 8. credentials ------------------------------------------------------------

def collect_interactively(ctx: Ctx, mailbox: dict) -> dict:
    mailbox = dict(mailbox)
    prompts = (("account", "b.ask_account", None), ("imap_host", "b.ask_imap_host", None),
               ("imap_port", "b.ask_imap_port", "993"), ("smtp_host", "b.ask_smtp_host", None),
               ("smtp_port", "b.ask_smtp_port", "465"))
    for piece, key, default in prompts:
        if mailbox.get(piece):
            continue
        suffix = {"default": default} if default else {}
        answer = ctx.ask(ctx.L(key, **suffix)).strip()
        mailbox[piece] = answer or (default or "")
    if not mailbox.get("password"):
        mailbox["password"] = ctx.secret(ctx.L("b.ask_password"))
    return mailbox


def step_credentials(ctx: Ctx):
    dest = envfile.env_path()
    ctx.env_path = dest
    current = mailbox_from(envfile.read_env())
    if all(current.get(piece) for piece in REQUIRED):
        ctx.mailbox = current
        ctx.password_key = current["password_key"]
        return True, f"credentials already in {dest} (not touched)"

    if ctx.args.dry_run:
        source = "--env-file" if ctx.args.env_file else "the terminal"
        ctx.would(f"read the mailbox credentials from {source}, test IMAP and SMTP, and write {dest} (mode 600)")
        return True, "dry run"

    mailbox = dict(current)
    if ctx.args.env_file:
        mailbox.update(mailbox_from(parse_env_file(Path(ctx.args.env_file))))
        missing = [piece for piece in (*REQUIRED, "smtp_host", "smtp_port") if not mailbox.get(piece)]
        if missing:
            raise NeedData(f"--env-file lacks: {', '.join(missing)}")
    elif ctx.interactive:
        mailbox = collect_interactively(ctx, mailbox)
    elif ctx.args.yes:
        raise NeedData("no mailbox credentials: pass --env-file (paynani .env format)")
    else:
        ok, detail = wait_for_onboarding(ctx, dest)
        if not ok:
            return False, detail
        mailbox = mailbox_from(envfile.read_env())
        ctx.mailbox = mailbox
        ctx.password_key = mailbox.get("password_key", "AGENT_EMAIL_PASSWORD")
        return True, f"credentials written to {dest} by paynani onboard"

    values = env_values(mailbox)
    errors = validate.validate_env(values)
    if errors:
        return False, "\n".join(f"{key}: {message}" for key, message in errors.items())

    for protocol, probe_fn, host_key, port_key in (
            ("IMAP", probe.probe_imap, "imap_host", "imap_port"),
            ("SMTP", probe.probe_smtp, "smtp_host", "smtp_port")):
        result = probe_fn(mailbox[host_key], int(mailbox[port_key]), mailbox["account"], mailbox["password"])
        if not result["ok"]:
            reasons = [f"{s['text']} {s['detail']}".strip() for s in result["steps"] if not s["ok"]]
            return False, f"{protocol} check failed: " + "; ".join(reasons)

    written, where = envfile.write_env(envfile.render_env(values))
    if not written:
        return False, where
    ctx.mailbox = mailbox
    ctx.password_key = "AGENT_EMAIL_PASSWORD"
    os.environ["PAYNANI_ENV"] = str(dest)
    return True, f"credentials written to {where} (mode 600)"


def wait_for_onboarding(ctx: Ctx, dest: Path):
    """No terminal and no --env-file: hand the owner the onboarding form and wait for the file."""
    ctx.say(ctx.L("b.onboard_wait"))
    ctx.run([str(ROOT / "scripts" / "paynani"), "onboard"], cwd=str(ROOT))
    deadline = ONBOARD_WAIT_SECONDS
    while deadline > 0:
        if all(mailbox_from(envfile.read_env()).get(piece) for piece in REQUIRED):
            return True, ""
        ctx.sleep(3)
        deadline -= 3
    return False, f"no credentials appeared in {dest}: run scripts/paynani onboard"


# --- 9. himalaya ---------------------------------------------------------------

def step_himalaya(ctx: Ctx):
    config = accounts_cli.himalaya_config_path()
    text = accounts_cli._read_text(config) or ""
    present = accounts_cli._has_himalaya_section(text, HIMALAYA_NAME)
    mailbox = ctx.mailbox
    if ctx.args.dry_run:
        ctx.would(f"{'keep' if present else 'add'} [accounts.{HIMALAYA_NAME}] in {config}, then "
                  f"himalaya account check -a {HIMALAYA_NAME} and envelope list")
        return True, "dry run"
    if not present:
        if not (mailbox.get("smtp_host") and mailbox.get("smtp_port")):
            raise NeedData("the SMTP host and port are missing (AGENT_EMAIL_OUTGOING_SERVER_SMTP_*)")
        secret = himalaya_config.secret_command(ROOT / "scripts" / "env_secret.py", ctx.env_path, ctx.password_key)
        block = himalaya_config.account_block(
            HIMALAYA_NAME, mailbox["account"],
            {"host": mailbox["imap_host"], "port": mailbox["imap_port"]},
            {"host": mailbox["smtp_host"], "port": mailbox["smtp_port"]},
            secret, default=True)
        accounts_cli._write_himalaya(config, (text.rstrip("\n") + "\n\n" if text.strip() else "") + block)
        note = f"[accounts.{HIMALAYA_NAME}] added to {config}"
    else:
        note = f"[accounts.{HIMALAYA_NAME}] already in {config} (not touched)"
    env = himalaya_env(ctx)
    for argv in (["himalaya", "account", "check", "-a", HIMALAYA_NAME],
                 ["himalaya", "envelope", "list", "-a", HIMALAYA_NAME, "-s", "5"]):
        done = run_quiet(ctx, argv, env=env)
        if done.returncode != 0:
            return False, f"{' '.join(argv)} failed:\n{first_lines(done.stderr or done.stdout)}"
    return True, note


# --- 10. roster ------------------------------------------------------------------

def step_roster(ctx: Ctx):
    path = roster_cli.roster_file()
    if path.exists():
        return True, f"{path} already exists (not touched)"
    name, email = ctx.args.owner_name, ctx.args.owner_email
    if ctx.args.dry_run:
        ctx.would(f'paynani roster add "{name or "<owner>"}" {email or "<email>"} --type Human --yes')
        return True, "dry run"
    if not (name and email):
        need_terminal(ctx, "the owner's name and email (--owner-name, --owner-email)")
        name = name or ctx.ask(ctx.L("b.ask_owner_name")).strip()
        email = email or ctx.ask(ctx.L("b.ask_owner_email")).strip()
    problems = []
    if not name.strip() or "\n" in name or "\r" in name:
        problems.append("the owner's name must be one non-empty line")
    if not validate._looks_like_email(email.strip()):
        problems.append(f"{email!r} does not look like an email address")
    elif email.strip().lower() == ctx.mailbox.get("account", "").strip().lower():
        problems.append("the owner's address cannot be the agent's own mailbox")
    if problems:
        return False, "\n".join(problems)
    status, detail = roster_cli.add_contact_noninteractive(name, email, type_="Human")
    if status not in ("added", "duplicate"):
        return False, f"roster {status}: {detail}"
    ctx.owner = f"{name} <{email}>"
    return True, f"{name} <{email}> in {path}"


# --- 11. installer or upgrade ------------------------------------------------------

def step_install(ctx: Ctx):
    env = dict(os.environ)
    if ctx.env_path:
        env["PAYNANI_ENV"] = str(ctx.env_path)
    if ctx.args.upgrade:
        if not ctx.args.ref:
            return False, "--upgrade needs --ref"
        commands = [["git", "-C", str(ROOT), "fetch", "--tags", "--force", "origin"],
                    [str(ROOT / "scripts" / "version.sh"), "--apply", ctx.args.ref]]
        accepted = (0,)
    else:
        argv = [str(ROOT / "scripts" / "install.sh"), "--runtime", ctx.runtime]
        if ctx.args.with_sms:
            argv.append("--with-sms")
        commands = [argv]
        accepted = (0, 10)   # 10 is install.sh saying "I changed things": the normal first run
    for argv in commands:
        if ctx.args.dry_run:
            ctx.would(" ".join(argv))
            continue
        done = ctx.run(argv, cwd=str(ROOT), env=env)
        if done.returncode not in accepted:
            return False, f"{' '.join(argv)} exited {done.returncode}"
    return True, "upgraded" if ctx.args.upgrade else f"install.sh --runtime {ctx.runtime}"


# --- 12. harness permission rules --------------------------------------------------

def step_rules(ctx: Ctx):
    try:
        from paynani_lib import harness_rules
    except ImportError:
        return True, "harness rules: skipped (not in this ref)"
    if ctx.args.dry_run:
        for line in harness_rules.plan(ctx.runtime, ROOT):
            ctx.would(line)
        return True, "dry run"
    ok, detail = harness_rules.apply(ctx.runtime, ROOT, assume_yes=ctx.args.yes,
                                     confirm=ctx.ask, out=ctx.say)
    return ok, detail


# --- 13. verification -----------------------------------------------------------------

def doctor_failure(status: str, report: dict, waited: int) -> str:
    """Every row that is not ok, with its state and detail, so a failed run can be diagnosed from its log."""
    rows = [f"  {c.get('name', '?')}: {c.get('status', '?')} - {c.get('summary', '')}"
            + (f" (next: {c['next_command']})" if c.get("next_command") else "")
            for c in report.get("checks", []) if isinstance(c, dict) and c.get("status") != "ok"]
    head = f"paynani doctor says {status}" + (f" after waiting {waited}s" if waited else "") + ":"
    return "\n".join([head, *rows, "run scripts/paynani doctor"])


def step_verify(ctx: Ctx):
    if ctx.args.dry_run:
        ctx.would("scripts/paynani doctor --json and scripts/healthcheck.py"
                  + (", then a test message to the owner" if ctx.args.test_mail else ""))
        return True, "dry run"
    waited = 0
    while True:
        doctor = run_quiet(ctx, [ROOT / "scripts" / "paynani", "doctor", "--json"], cwd=str(ROOT))
        try:
            report = json.loads(doctor.stdout)
            status = report["status"]
        except (ValueError, KeyError, TypeError):
            return False, f"paynani doctor gave no status:\n{first_lines(doctor.stderr or doctor.stdout)}"
        if status == "ok":
            break
        if status != "unknown" or waited >= DOCTOR_WAIT_SECONDS:
            return False, doctor_failure(status, report, waited)
        ctx.sleep(DOCTOR_POLL_SECONDS)
        waited += DOCTOR_POLL_SECONDS
    health = run_quiet(ctx, [sys.executable, ROOT / "scripts" / "healthcheck.py"], cwd=str(ROOT))
    if health.returncode != 0:
        return False, f"healthcheck.py failed:\n{first_lines(health.stdout or health.stderr)}"
    if ctx.args.test_mail:
        target = ctx.args.owner_email
        if not target:
            return False, "--test-mail needs --owner-email"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as body:
            body.write("paynani was installed on this machine. This message is the test of the mailbox.\n")
        try:
            sent = run_quiet(ctx, [ROOT / "scripts" / "send.sh", target, "paynani: installation test", body.name],
                             cwd=str(ROOT))
        finally:
            Path(body.name).unlink(missing_ok=True)
        if sent.returncode != 0:
            return False, f"send.sh to the owner failed:\n{first_lines(sent.stderr or sent.stdout)}"
    return True, "doctor ok, healthcheck ok" + (", test message sent" if ctx.args.test_mail else "")


# --- driver ----------------------------------------------------------------------------

def steps_for(args):
    return [
        ("runtime", step_runtime, f"scripts/bootstrap_user.py --runtime <runtime> (one of: {' '.join(RUNTIMES)})"),
        ("credentials", step_credentials, "scripts/paynani onboard, or --env-file FILE"),
        ("himalaya", step_himalaya, f"himalaya account check -a {HIMALAYA_NAME}"),
        ("roster", step_roster, 'scripts/paynani roster add "NAME" EMAIL --type Human --yes'),
        ("install" if not args.upgrade else "upgrade", step_install,
         "scripts/version.sh --apply REF" if args.upgrade else "scripts/install.sh --runtime <runtime>"),
        ("harness rules", step_rules, "scripts/bootstrap_user.py --yes (adds the permission rules)"),
        ("verification", step_verify, "scripts/paynani doctor && scripts/healthcheck.py"),
    ]


def parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runtime", default="")
    p.add_argument("--ref", default="")
    p.add_argument("--env-file", default="")
    p.add_argument("--owner-name", default="")
    p.add_argument("--owner-email", default="")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--with-sms", action="store_true")
    p.add_argument("--upgrade", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--test-mail", action="store_true")
    return p


def language() -> str:
    return "es-MX" if os.environ.get("LANG", "").lower().startswith("es") else "en-US"


def main(argv=None, *, ctx_overrides: dict | None = None) -> int:
    args = parser().parse_args(argv)
    if bool(args.owner_name) != bool(args.owner_email):
        print("bootstrap_user: --owner-name and --owner-email go together", file=sys.stderr)
        return EX_USAGE
    i18n.set_current(language())
    ctx = Ctx(args=args, home=Path.home(),
              interactive=bool(not args.yes and sys.stdin.isatty()))
    for key, value in (ctx_overrides or {}).items():
        setattr(ctx, key, value)

    steps = steps_for(args)
    try:
        for number, (name, function, repeat) in enumerate(steps, start=1):
            ctx.say(f"[{number}/{len(steps)}] {name}")
            ok, detail = function(ctx)
            if not ok:
                ctx.say(detail)
                ctx.say(ctx.L("b.not_ready", step=name))
                ctx.say(ctx.L("b.repeat", command=repeat))
                return EX_STEP
            ctx.say(f"      {detail}")
    except NeedData as exc:
        ctx.say(f"bootstrap_user: {exc}")
        return EX_USAGE

    if args.dry_run:
        return EX_OK
    ctx.say(ctx.L("b.ready"))
    ctx.say(ctx.L("b.sum_runtime", value=ctx.runtime))
    ctx.say(ctx.L("b.sum_creds", value=ctx.env_path))
    ctx.say(ctx.L("b.sum_clone", value=ROOT))
    if ctx.owner:
        ctx.say(ctx.L("b.sum_owner", value=ctx.owner))
    return EX_OK


if __name__ == "__main__":
    sys.exit(main())
