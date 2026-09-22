#!/usr/bin/env python3
"""Focused tests for scripts/send.sh."""

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


def write_common(tmp: pathlib.Path, himalaya_version: str, failure_mode: str = ""):
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "himalaya.log"
    fake = bin_dir / "himalaya"
    fake.write_text(f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {log}
if [ "$1" = "--version" ]; then
    printf '%s\\n' "{himalaya_version}"
    exit 0
fi
if [ "$1" = "-a" ] && [ "{failure_mode}" = "unexpected-a" ]; then
    printf "unexpected argument '-a'\\n" >&2
    exit 2
fi
if [ "$3" = "smtp" ] && [ "{failure_mode}" = "no-smtp" ]; then
    printf "unrecognized subcommand 'smtp'\\n" >&2
    exit 2
fi
if [ "$1" = "-a" ] && [ "$3" = "send" ]; then
    printf 'SMTP SHOULD NOT RUN\\n' >> {log}
    exit 0
fi
exit 0
""")
    fake.chmod(0o755)
    roster = tmp / "roster.md"
    roster.write_text("| Name | Email | Type |\n|---|---|---|\n| Metis | metis.claude.tob@gmail.com | AI Agent |\n")
    env_file = tmp / ".env"
    env_file.write_text("PAYNANI_EMAIL=atenea.buffay.hermes@agenteiamail.com\n")
    body = tmp / "body.txt"
    body.write_text("hello\n")
    config = tmp / "himalaya.toml"
    config.write_text("""[accounts.paynani]
email = "atenea.buffay.hermes@agenteiamail.com"
[accounts.paynani.smtp]
server = "smtps://smtp.example:465"
""")
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
        "ROSTER": str(roster),
        "ENV_FILE": str(env_file),
        "HIMALAYA_CONFIG": str(config),
    })
    return env, body, log


def run_send(himalaya_version: str, *args: str, failure_mode: str = ""):
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        env, body, log = write_common(tmp, himalaya_version, failure_mode)
        cmd = [str(SEND), *args, "metis.claude.tob@gmail.com", "subject", str(body)]
        run = subprocess.run(cmd, text=True, capture_output=True, env=env)
        calls = log.read_text() if log.exists() else ""
        return run, calls


for mode, observed in (("unexpected-a", "unexpected argument '-a'"), ("no-smtp", "unrecognized subcommand 'smtp'")):
    run, calls = run_send("himalaya v1.2.0", failure_mode=mode)
    check(f"send.sh refuses Himalaya v1 before SMTP ({observed})", run.returncode != 0 and "paynani needs v2.x to send" in run.stderr and "v1.x has no `smtp send`" in run.stderr and "Upgrading the binary alone is not enough" in run.stderr, run.stderr)
    check(f"Himalaya v1 refusal does not reach legacy failure ({observed})", observed not in run.stderr and "smtp send" not in calls and calls.strip() == "--version", calls + run.stderr)

run, calls = run_send("himalaya v2.1.0", "--dry-run")
check("send.sh dry-run still works with Himalaya v2", run.returncode == 0 and "dry-run: nothing sent" in run.stdout, run.stdout + run.stderr)
check("Himalaya v2 dry-run checks version without sending", "--version" in calls and "smtp send" not in calls, calls)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
