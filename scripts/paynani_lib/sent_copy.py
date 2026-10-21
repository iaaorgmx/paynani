#!/usr/bin/env python3
"""
A copy of each sent message in the account's Sent folder (#435, Julian's Q45 = A).

`send.sh` sends with `himalaya smtp send`, which is SMTP only: nothing lands in
Sent unless something puts it there (#117). This puts it there, after the send,
with an IMAP APPEND of the exact bytes that went out -- same Message-ID, so
PaynaniWeb finds it -- flagged `\\Seen`. Recipients notice nothing.

    sent_copy.py <himalaya account> <message file>

prints one line, `saved <folder>`, `skipped <reason>` or `failed <reason>`, and
always exits 0: the message has already gone, and a copy that could not be saved
must never turn into a failed send.

- **Gmail** keeps its own copy of what leaves through its SMTP, so a second one
  would be a duplicate: skipped when the account's IMAP server is Gmail's.
- **No IMAP** in the account's himalaya config: skipped, there is nowhere to put it.
- **The folder** is the one LIST marks `\\Sent` (RFC 6154), or else one with a
  well-known name. None found: failed, and nothing is created.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

SENT_NAMES = ("Sent", "Sent Items", "Sent Messages", "Enviados", "Elementos enviados", "INBOX.Sent", "INBOX/Sent")
GMAIL_HOSTS = ("imap.gmail.com", "imap.googlemail.com")
TIMEOUT = 60


def imap_host(account: str) -> str | None:
    """The account's IMAP host from the himalaya config, or None without an IMAP block."""
    paths = os.environ.get("HIMALAYA_CONFIG") or str(Path.home() / ".config/himalaya/config.toml")
    found = None
    for raw in paths.split(":"):
        p = Path(raw).expanduser() if raw else None
        if not p or not p.exists():
            continue
        acct = tomllib.loads(p.read_text()).get("accounts", {}).get(account, {})
        imap = acct.get("imap") if isinstance(acct, dict) else None
        if isinstance(imap, dict):
            server = str(imap.get("server") or imap.get("host") or "")
            found = (urlsplit(server).hostname if "://" in server else server.split(":")[0]) or ""
    return None if found is None else found.lower()


def is_gmail(host: str) -> bool:
    return host in GMAIL_HOSTS or host.endswith(".gmail.com")


def sent_folder(account: str) -> str | None:
    run = subprocess.run(["himalaya", "-a", account, "imap", "list", "--all", "--json"],
                         capture_output=True, text=True, timeout=TIMEOUT)
    if run.returncode != 0:
        return None
    try:
        boxes = json.loads(run.stdout).get("mailboxes") or []
    except (ValueError, AttributeError):
        return None
    names = []
    for box in boxes:
        if not isinstance(box, dict) or not box.get("name"):
            continue
        if any(str(a).lower() == "\\sent" for a in box.get("attributes") or []):
            return str(box["name"])
        names.append(str(box["name"]))
    lowered = {n.lower(): n for n in names}
    return next((lowered[c.lower()] for c in SENT_NAMES if c.lower() in lowered), None)


def save(account: str, message: Path) -> str:
    host = imap_host(account)
    if host is None:
        return "skipped no-imap"
    if is_gmail(host):
        return "skipped gmail"
    try:
        folder = sent_folder(account)
        if not folder:
            return "failed no-sent-folder"
        with open(message, "rb") as fh:
            run = subprocess.run(["himalaya", "-a", account, "imap", "append", folder, "-f", "\\Seen"],
                                 stdin=fh, capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "failed timeout"
    except OSError as exc:
        return f"failed {type(exc).__name__}"
    return f"saved {folder}" if run.returncode == 0 else "failed append"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: sent_copy.py <himalaya account> <message file>", file=sys.stderr)
        print("failed usage")
        return 0
    try:
        print(save(argv[1], Path(argv[2])))
    except Exception as exc:  # noqa: BLE001 -- never fail a send that already went out
        print(f"failed {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
