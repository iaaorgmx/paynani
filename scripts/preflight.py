#!/usr/bin/env python3
"""Check that the configured IMAP server supports IDLE and returns UIDVALIDITY."""

import getpass
import imaplib
import os
import socket
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
from paths import env_file   # noqa: E402

ENV = env_file()

# Both key schemas, same order of preference as idle_listener.py. INSTALL.md tells
# you to point at an existing workspace .env, so this has to read one.
KEYS = {
    "host": ("PAYNANI_IMAP_HOST", "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"),
    "port": ("PAYNANI_IMAP_PORT", "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT"),
    "user": ("PAYNANI_EMAIL", "AGENT_EMAIL_ACCOUNT"),
    "password": ("PAYNANI_PASSWORD", "AGENT_EMAIL_PASSWORD"),
}

LEGACY_AMBIGUOUS = (
    "AGENT_EMAIL_INCOMING_SERVER_IMAP",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP",
)


def lookup(env, field):
    """First non-empty value among the accepted names, or None to prompt."""
    for key in KEYS[field]:
        value = env.get(key, "").strip()
        if value:
            return value
    return None


def ask(prompt, secret=False):
    """Prompt, but fail with a sentence rather than a traceback when there is
    no terminal. An agent runs this non-interactively, and EOFError reads as a
    broken tool instead of a missing setting."""
    try:
        return getpass.getpass(prompt) if secret else input(prompt).strip()
    except EOFError:
        print()
        print(f"needed {prompt.strip()} and there is no terminal to ask on.")
        print(f"Put it in {ENV}, or set PAYNANI_ENV to the file that has it.")
        raise SystemExit(1)


def load_env(path: Path) -> dict[str, str]:
    env = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    env = load_env(ENV)

    # Running before there is anything to check, with no terminal to ask on.
    # Left to itself this falls through to ask() and exits complaining about a
    # missing IMAP host, which reads as a broken tool or a misconfigured one.
    # It is neither: it is this check running before the mailbox exists. An
    # agent told to stop on failure and not work around it will do exactly that,
    # on the one host where the setup form it never reached was the answer.
    if not env and not sys.stdin.isatty():
        print(f"nothing to check yet: {ENV} does not exist or holds no settings,")
        print("and there is no terminal to ask on.")
        print()
        print("This check needs an account to test, so it runs after the mailbox")
        print("exists rather than before. If your human has not set one up, serve")
        print("the form with scripts/setup_web.sh and run this again once it has")
        print("written the file. AGENTS.md step 2 is the fork this belongs to.")
        return 1

    # Named for a server, holding a port. Say so rather than dialling it.
    for key in LEGACY_AMBIGUOUS:
        if env.get(key, "").strip().isdigit():
            print(f"{key} holds a port, not a hostname — that is the old schema.")
            print(f"Split it into {key}_HOST and {key}_PORT.")
            return 1

    host = lookup(env, "host") or ask("IMAP host: ")
    if host.isdigit():
        print(f"IMAP host is {host!r}, which is a port, not a hostname")
        return 1
    port = int(lookup(env, "port") or ask("IMAP port [993]: ") or 993)
    user = lookup(env, "user") or ask("username (full email): ")
    pw = lookup(env, "password") or ask("password: ", secret=True)

    print(f"checking {user} at {host}:{port} (from {ENV if env else 'prompts'})")

    # This is the first thing a new install runs. Each failure gets a sentence
    # saying what to do, because a traceback here reads as "the tool is broken"
    # rather than "the hostname is wrong".
    try:
        c = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=30)
    except ssl.SSLCertVerificationError as exc:
        print(f"TLS certificate does not cover {host!r}: {exc}")
        print("Mail servers often present a certificate for the underlying host")
        print("rather than for mail.<yourdomain>. Read the names it does cover:")
        print(f"  openssl s_client -connect {host}:{port} -servername {host} </dev/null \\")
        print("    2>/dev/null | openssl x509 -noout -subject -ext subjectAltName")
        return 1
    except socket.gaierror:
        print(f"cannot resolve {host!r} — check the hostname")
        return 1
    except (OSError, socket.timeout) as exc:
        print(f"cannot reach {host}:{port} — {exc}")
        return 1

    try:
        c.login(user, pw)
    except imaplib.IMAP4.error as exc:
        print(f"login rejected for {user}: {exc}")
        print("If the provider offers app-passwords, use one rather than the account password.")
        return 1

    caps = [x.decode() if isinstance(x, bytes) else str(x) for x in c.capabilities]
    idle = "IDLE" in caps
    print("IDLE advertised:", idle)
    c.select("INBOX")
    typ, data = c.status("INBOX", "(UIDVALIDITY MESSAGES)")
    print("status:", data)
    c.logout()

    if not idle:
        print()
        print("This server does not advertise IDLE. paynani is push-based and")
        print("does not fall back to polling — stop here and tell your human.")
    return 0 if idle and typ == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
