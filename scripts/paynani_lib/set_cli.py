"""
`paynani set KEY [VALUE]` — change one of the seven .env keys without running
the whole onboarding flow.

Reuses envfile.py's read/render/write pipeline exactly as onboard's server
does, so a value set here has the same guarantees a value saved through the
web form has: only the affected key changes, everything else in the file
survives byte-for-byte (line endings included), and the write is atomic.

The live check before writing is what this command is for, rather than a
one-line `sed -i`: it is the same reasoning webapp/README.md gives for the web
form over a text editor, applied to a single field instead of all seven.
"""

from __future__ import annotations

import getpass
import sys

from . import envfile, validate
from .probe import probe_imap, probe_smtp

# Which live check(s) a change to this key should be re-verified against.
# AGENT_EMAIL_FROM_NAME touches neither protocol, so it is the one key
# --skip-check has nothing to skip.
PROBE_KEYS = {
    "AGENT_EMAIL_ACCOUNT": ("imap", "smtp"),
    "AGENT_EMAIL_PASSWORD": ("imap", "smtp"),
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": ("imap",),
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT": ("imap",),
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST": ("smtp",),
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT": ("smtp",),
    "AGENT_EMAIL_FROM_NAME": (),
}

# Every field a given probe reads, beyond the key actually being changed. A
# probe about to run needs all of these to already be valid, or the int()
# conversions below blow up on whatever an unrelated, half-configured field
# happens to hold.
NEEDED_FOR_PROBE = {
    "imap": (
        "AGENT_EMAIL_ACCOUNT",
        "AGENT_EMAIL_PASSWORD",
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST",
        "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT",
    ),
    "smtp": (
        "AGENT_EMAIL_ACCOUNT",
        "AGENT_EMAIL_PASSWORD",
        "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST",
        "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT",
    ),
}


def _print_steps(label: str, steps: list) -> None:
    print(f"  {label}:")
    for s in steps:
        mark = "ok  " if s["ok"] else "FAIL"
        detail = f" — {s['detail']}" if s["detail"] else ""
        print(f"    {mark} {s['text']}{detail}")


def run(args) -> int:
    key = args.key
    if key not in envfile.ENV_FIELDS:
        print(f"Unknown key {key!r}.", file=sys.stderr)
        print(f"paynani set only writes: {', '.join(envfile.ENV_FIELDS)}", file=sys.stderr)
        print("Anything else is not this form's to touch — edit .env by hand.", file=sys.stderr)
        return 64

    if key == "AGENT_EMAIL_PASSWORD" and args.value is not None:
        # A password on argv sits in the shell's history and is visible to
        # every other user of this host via `ps` for as long as the process
        # runs — exactly what getpass exists to avoid. The other six keys
        # are not secrets, so they may be passed directly.
        print("Refusing a password given on the command line.", file=sys.stderr)
        print("Run `paynani set AGENT_EMAIL_PASSWORD` with no value; it will prompt, hidden.", file=sys.stderr)
        return 64

    if args.value is not None:
        value = args.value
    elif key == "AGENT_EMAIL_PASSWORD":
        value = getpass.getpass("New password (hidden): ")
    else:
        value = input(f"{key}: ")

    stored = envfile.read_env()
    merged = dict(stored)
    merged[key] = value.strip()

    field_errors = validate.validate(merged)
    if key in field_errors:
        print(f"Not saved: {field_errors[key]}", file=sys.stderr)
        return 1

    protocols = PROBE_KEYS[key]
    if protocols and not args.skip_check:
        # A field this probe needs, other than the one being changed, may
        # already be invalid or empty -- a half-configured .env, someone
        # else's hand edit, an onboarding that never finished -- and that is
        # exactly when this command tends to get reached for. Report it and
        # stop before int() on an empty port turns that into a traceback.
        needed = {f for p in protocols for f in NEEDED_FOR_PROBE[p]}
        blocking = {k: v for k, v in field_errors.items() if k in needed}
        if blocking:
            print(f"Cannot check {key} against the mail server:", file=sys.stderr)
            for k, v in blocking.items():
                print(f"  {k}: {v}", file=sys.stderr)
            print("Fix that field too, or use --skip-check to write anyway.", file=sys.stderr)
            return 1

        ok = True
        if "imap" in protocols:
            imap = probe_imap(
                merged["AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"],
                int(merged["AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT"]),
                merged["AGENT_EMAIL_ACCOUNT"],
                merged["AGENT_EMAIL_PASSWORD"],
            )
            _print_steps("IMAP", imap["steps"])
            ok = ok and imap["ok"]
        if "smtp" in protocols:
            smtp = probe_smtp(
                merged["AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST"],
                int(merged["AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT"]),
                merged["AGENT_EMAIL_ACCOUNT"],
                merged["AGENT_EMAIL_PASSWORD"],
            )
            _print_steps("SMTP", smtp["steps"])
            ok = ok and smtp["ok"]
        if not ok:
            print(file=sys.stderr)
            print("Not saved: the live check above failed. Re-run with", file=sys.stderr)
            print("--skip-check only if you are certain this value is right.", file=sys.stderr)
            return 1

    ok, where = envfile.write_env(envfile.render_env(merged))
    if not ok:
        print(f"Not saved: {where}", file=sys.stderr)
        return 1

    if key == "AGENT_EMAIL_PASSWORD":
        print(f"{key} updated in {where}.")
    else:
        print(f"{key} set to {value!r} in {where}.")
    return 0
