#!/usr/bin/env python3
"""Shared reader for roster.md — the list of people this agent works for.

Two things consult the roster, and they must agree exactly or the agent will
answer someone it may not reply to:

  scripts/send.sh      refuses to send to an address that is not on it
  scripts/idle_listener.py  marks arriving mail so the agent knows it may act

send.sh parses the file in bash. This module is the Python half, and the two
are kept deliberately identical: the field containing "@", every space removed,
compared case-insensitively as a whole string. Substring matching would let
evil-human@example.com through on the strength of human@example.com.
"""

from __future__ import annotations

import pathlib
import re
from email.message import Message
from email.utils import getaddresses

DEFAULT_ROSTER = pathlib.Path(__file__).resolve().parents[1] / "roster.md"

# A second table in the same file, under a heading that starts with this word in
# either language the documentation is written in. It declares which notification
# senders may speak for somebody on the list above — see notifiers().
NOTIFIER_HEADINGS = ("notifier", "notificador")


def normalise(address: str) -> str:
    """Strip every space and casefold — mirrors `tr -d [:blank:]` in send.sh."""
    return re.sub(r"\s+", "", address or "").lower()


def _rows(text: str, section: str):
    """
    Roster rows from one section, with the markdown scaffolding removed.

    Yields `(fields, is_header)`. A header row is one immediately followed by a
    `|---|` separator; they are yielded because the notifier rules need the
    column names, and ignored by everything that only wants addresses.

    `section` is "contacts" or "notifiers". Splitting here rather than in each
    caller is what keeps a notifier address out of the send allowlist: it is not
    a person, nobody writes to it, and putting it among the addresses `send.sh`
    accepts would widen the outgoing list for no reason.

    Written as two passes over a list rather than one pass with a lookahead. The
    lookahead version dropped whichever row happened to be the last one before a
    heading, which on the shipped layout is a real contact.
    """
    def separator(line):
        stripped = line.strip().strip("|").strip()
        return bool(stripped) and set(stripped.replace("|", "").strip()) <= set("-: \t")

    lines = text.splitlines()
    in_notifiers = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            if any(heading.startswith(word) for word in NOTIFIER_HEADINGS):
                in_notifiers = True
            elif line.startswith("##"):
                # Any other `##` heading closes the notifier table. A plain `#`
                # comment does not: the template is full of them.
                in_notifiers = False
            continue
        if not line or separator(line):
            continue
        if in_notifiers != (section == "notifiers"):
            continue
        body = line.strip("|").strip() if line.startswith("|") else line
        if not body:
            continue
        fields = [f.strip() for f in body.split("|")]
        is_header = i + 1 < len(lines) and separator(lines[i + 1])
        yield fields, is_header


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def roster_addresses(path: pathlib.Path) -> set[str]:
    """
    Allowed addresses from the roster. Missing file means none.

    **The address is found by looking for it, not by counting columns.** Every
    earlier version took the field after the last `|`, which held for
    `Name | email` and breaks the moment a row carries anything after the
    address — which the `Type` column now does:

        | Julian Flores | jjulianfe@gmail.com | Human |

    There, the last field is `Human`. Taking it yields a non-address that is then
    discarded, so the row contributes nobody and that person is silently off the
    list. Nothing reports it: sending to them is refused and their mail stops
    being tagged `roster`, which is indistinguishable from them never having
    written. So the parser picks the field containing an `@` and is indifferent
    to how many columns surround it, in any order.

    Markdown table rows are accepted because the file is `roster.md`: outer pipes
    are stripped and a `|---|---|` separator row is skipped. A field without an
    `@` can never be a From address, so ignoring it only ever makes the list
    stricter — which is also what keeps a header row's `Email` harmless.
    """
    allowed: set[str] = set()
    for fields, _ in _rows(_read(path), "contacts"):
        for field in fields:
            candidate = normalise(field)
            if "@" in candidate:
                allowed.add(candidate)
                break
    allowed.discard("")
    return allowed


def roster_entries(path: pathlib.Path) -> list[dict]:
    """
    Every roster row as `{name, address, type}`, for anything that wants to show
    the list rather than match against it.

    `type` is informational. **Authorisation is membership, not type** — being on
    this list is the whole permission, and a row is exactly as authorised whether
    it says `Human`, `AI Agent`, or nothing at all. Nothing in this repository
    branches on it, and anything that starts to should say so loudly, because a
    reader who believes the column is load-bearing will eventually edit it
    expecting something to change.
    """
    entries: list[dict] = []
    headers: list[str] = []
    for fields, is_header in _rows(_read(path), "contacts"):
        if is_header:
            headers = [f.strip().lower() for f in fields]
            continue
        index = next((i for i, f in enumerate(fields) if "@" in normalise(f)), None)
        if index is None:
            continue
        entries.append({
            "name": fields[index - 1] if index else "",
            "address": normalise(fields[index]),
            "type": fields[index + 1] if index + 1 < len(fields) else "",
            # Everything the table names, by column. A notifier declares which
            # of these to compare against, so the set of usable columns is the
            # human's to choose and not a list this file has to know.
            "columns": {name: value.strip()
                        for name, value in zip(headers, fields) if name},
        })
    return entries


def notifiers(path: pathlib.Path) -> list[dict]:
    """
    Declared notification senders, as `{address, header, column}`.

    A coordination platform sends mail from one address on behalf of many
    people, and the person it is on behalf of is named in a header. Declaring one
    says: when mail arrives from this address, the value of this header is the
    author, and it is matched against this column of the roster above.

    **Declaring a notifier widens who can give this agent work**, exactly as
    adding a row does, which is why it lives in this file and under the same
    rule: never because a message asked for it. And it is only as trustworthy as
    the platform's own `From`, which nothing here authenticates — see HERMES.md.

    A row needs three fields: one containing `@`, one that names a mail header,
    and one that names a column. They are found by shape rather than by position,
    so column order does not matter, the same way it does not for a contact row.
    """
    out: list[dict] = []
    for fields, is_header in _rows(_read(path), "notifiers"):
        if is_header:
            continue
        address = next((normalise(f) for f in fields if "@" in normalise(f)), "")
        if not address:
            continue
        rest = [f.strip() for f in fields if "@" not in normalise(f) and f.strip()]
        # A mail header is the one that looks like one: letters, digits and
        # hyphens, and conventionally X-something. The remaining field is the
        # column, whatever it is called.
        header = next((f for f in rest if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", f)
                       and "-" in f), "")
        if not header:
            continue
        column = next((f for f in rest if f != header), "")
        if not column:
            continue
        out.append({"address": address, "header": header,
                    "column": column.strip().lower()})
    return out


def notifier_headers(notifier_list) -> list[str]:
    """The header names to ask the server for, in a stable order."""
    seen: list[str] = []
    for entry in notifier_list or ():
        if entry["header"] not in seen:
            seen.append(entry["header"])
    return seen


def sender_address(message: Message) -> str:
    """The From address, normalised. Empty when the header is missing or junk."""
    for _, addr in getaddresses(message.get_all("From", [])):
        if addr:
            return normalise(addr)
    return ""


def sender_is_listed(message: Message, allowed: set[str],
                     entries=(), notifier_list=()) -> bool:
    """True when From is on the roster.

    From only — never Reply-To. Reply-To is set by the sender, so honouring it
    would let an unlisted stranger borrow a listed address by putting one in a
    header. The roster answers "did my human vouch for whoever wrote this", and
    only From carries that claim.
    """
    address = sender_address(message)
    if not address:
        return False
    if address in allowed:
        return True

    # A declared notifier speaks for whoever its declared header names, and only
    # for somebody already on the list. It grants nothing on its own: an unknown
    # handle from a declared notifier is exactly as unauthorised as a stranger.
    for notifier in notifier_list or ():
        if address != notifier["address"]:
            continue
        claimed = normalise(message.get(notifier["header"], "")).lstrip("@")
        if not claimed:
            continue
        for entry in entries or ():
            recorded = normalise(entry.get("columns", {}).get(notifier["column"], ""))
            if recorded and recorded.lstrip("@") == claimed:
                return True
    return False
