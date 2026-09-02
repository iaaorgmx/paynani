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


def normalise(address: str) -> str:
    """Strip every space and casefold — mirrors `tr -d [:blank:]` in send.sh."""
    return re.sub(r"\s+", "", address or "").lower()


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
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return set()

    allowed: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            line = line.strip("|").strip()
            if not line:
                continue
            if set(line.replace("|", "").strip()) <= set("-: \t"):
                continue
        for field in line.split("|"):
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
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return entries

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("|"):
            line = line.strip("|").strip()
            if not line:
                continue
            if set(line.replace("|", "").strip()) <= set("-: \t"):
                continue
        fields = [f.strip() for f in line.split("|")]
        index = next((i for i, f in enumerate(fields) if "@" in normalise(f)), None)
        if index is None:
            continue
        entries.append({
            "name": fields[index - 1] if index else "",
            "address": normalise(fields[index]),
            "type": fields[index + 1] if index + 1 < len(fields) else "",
        })
    return entries


def sender_address(message: Message) -> str:
    """The From address, normalised. Empty when the header is missing or junk."""
    for _, addr in getaddresses(message.get_all("From", [])):
        if addr:
            return normalise(addr)
    return ""


def sender_is_listed(message: Message, allowed: set[str]) -> bool:
    """True when From is on the roster.

    From only — never Reply-To. Reply-To is set by the sender, so honouring it
    would let an unlisted stranger borrow a listed address by putting one in a
    header. The roster answers "did my human vouch for whoever wrote this", and
    only From carries that claim.
    """
    address = sender_address(message)
    return bool(address) and address in allowed
