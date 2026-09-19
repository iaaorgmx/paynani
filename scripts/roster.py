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

# The one notifier a `GitHub` column declares by itself. A handle in that column
# exists for exactly one purpose, matching GitHub's notification mail back to the
# person, so recording one is the decision the `## Notifiers` table used to ask
# for a second time. On nine of ten hosts the second time never happened, and the
# team's whole coordination channel arrived untagged (#188).
GITHUB_NOTIFIER = {"address": "notifications@github.com",
                   "header": "X-GitHub-Sender", "column": "github"}

# Versioned roster schema aliases. Canonical names are what write paths require;
# aliases are read-only compatibility so older rosters keep working until an
# explicit migration rewrites their header.
SCHEMA_ALIAS_VERSION = 1
COLUMN_ALIASES = {"username": "github"}
CANONICAL_COLUMNS = {"name", "email", "address", "type", "github"}


def canonical_column(name: str) -> str:
    folded = (name or "").strip().lower()
    return COLUMN_ALIASES.get(folded, folded)


def legacy_columns(text: str) -> list[tuple[str, str]]:
    _, header_fields, _ = _contacts_table_bounds(text)
    if not header_fields:
        return []
    out = []
    for field in header_fields:
        folded = field.strip().lower()
        canonical = canonical_column(field)
        if folded != canonical:
            out.append((field.strip(), canonical))
    return out


def needs_migration(text: str) -> bool:
    return bool(legacy_columns(text))


def write_schema_error(text: str) -> str | None:
    """Explain why a roster must be migrated before any ordinary write.

    Legacy aliases remain readable so an upgrade never breaks delivery, but
    add/remove paths must not silently keep extending the old schema.  The
    explicit migrator (and batch apply, which includes migration in its plan)
    are the only writers allowed to cross that boundary.
    """
    if needs_migration(text):
        return "roster.md uses a legacy schema; run: paynani roster migrate --apply"
    return None


def normalise(address: str) -> str:
    """Strip every space and casefold — mirrors `tr -d [:blank:]` in send.sh."""
    return re.sub(r"\s+", "", address or "").lower()


def _is_separator(line: str) -> bool:
    stripped = line.strip().strip("|").strip()
    return bool(stripped) and set(stripped.replace("|", "").strip()) <= set("-: \t")


def _rows(text: str, section: str):
    """
    Roster rows from one section, with the markdown scaffolding removed.

    Yields `(fields, is_header, line_index)`. `line_index` is this row's
    position in `text.splitlines()`, carried through for add_contact() and
    remove_contact() below, which need to know exactly which line to insert
    before or delete rather than only what it says. A header row is one
    immediately followed by a `|---|` separator; they are yielded because the
    notifier rules need the column names, and ignored by everything that only
    wants addresses.

    `section` is "contacts" or "notifiers". Splitting here rather than in each
    caller is what keeps a notifier address out of the send allowlist: it is not
    a person, nobody writes to it, and putting it among the addresses `send.sh`
    accepts would widen the outgoing list for no reason.

    Written as two passes over a list rather than one pass with a lookahead. The
    lookahead version dropped whichever row happened to be the last one before a
    heading, which on the shipped layout is a real contact.
    """
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
        if not line or _is_separator(line):
            continue
        if in_notifiers != (section == "notifiers"):
            continue
        body = line.strip("|").strip() if line.startswith("|") else line
        if not body:
            continue
        fields = [f.strip() for f in body.split("|")]
        is_header = i + 1 < len(lines) and _is_separator(lines[i + 1])
        yield fields, is_header, i


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
    return _addresses_from_text(_read(path))


def _addresses_from_text(text: str) -> set[str]:
    allowed: set[str] = set()
    for fields, _, _ in _rows(text, "contacts"):
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
    for fields, is_header, _ in _rows(_read(path), "contacts"):
        if is_header:
            headers = [canonical_column(f) for f in fields]
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


def _contacts_table_bounds(text: str):
    """
    (header_line_index, header_fields, last_row_line_index) for the contacts
    table, or (None, None, None) if roster.md has no header row for it.

    `last_row_line_index` is where a new row is inserted *after* — the last
    existing contact row, or the header's separator line when the table is
    otherwise empty. Kept separate from add_contact()/remove_contact() so
    both can share one answer to "where is this table" instead of two
    slightly different scans.
    """
    header_idx = None
    header_fields = None
    last_idx = None
    for fields, is_header, idx in _rows(text, "contacts"):
        if is_header:
            header_idx = idx
            header_fields = fields
            continue
        last_idx = idx
    return header_idx, header_fields, last_idx


# Columns add_contact() knows how to fill. Anything else in the header is left
# blank rather than guessed at — a table with a column this doesn't recognise
# should fail closed on that field, not invent a value for it.
_KNOWN_COLUMNS = {
    "name": "name",
    "email": "address",
    "address": "address",
    "type": "type",
    "github": "github",
}


def add_contact(text: str, name: str, address: str, *, type_: str = "", github: str = "") -> tuple[bool, str]:
    """
    Add one row to the contacts table.

    Returns `(True, new_text)` on success, or `(False, reason)` — unchanged
    text is never returned as if it were the new version, so a caller cannot
    write a "success" result that silently did nothing.

    Column order and the columns actually present are read from the file's own
    header row rather than assumed, so this works on the shipped
    `Name | Email | Type | GitHub` layout and on the plain `Name | address`
    layout the docstring above says older rosters still use. A field whose
    column does not exist in this file is refused rather than silently
    dropped — `--github` on a two-column roster would otherwise look like it
    worked and leave no GitHub handle anywhere.
    """
    norm = normalise(address)
    if not norm or "@" not in norm:
        return False, f"{address!r} is not an email address"
    if norm in _addresses_from_text(text):
        return False, f"{address} is already on the roster"

    header_idx, header_fields, last_idx = _contacts_table_bounds(text)
    if header_idx is None:
        return False, "roster.md has no contacts table (no header row found)"

    schema_error = write_schema_error(text)
    if schema_error:
        return False, schema_error

    lower_headers = [h.strip().lower() for h in header_fields]
    canonical_headers = [canonical_column(h) for h in header_fields]
    if github and "github" not in lower_headers:
        return False, "roster.md's contacts table has no GitHub column; add one by hand first"
    if type_ and "type" not in canonical_headers:
        return False, "roster.md's contacts table has no Type column; add one by hand first"

    provided = {"name": name, "address": address, "type": type_, "github": github}
    cells = []
    for raw_column in header_fields:
        column = canonical_column(raw_column)
        key = _KNOWN_COLUMNS.get(column)
        cells.append(provided.get(key, "") if key else "")
    new_row = "| " + " | ".join(cells) + " |"

    lines = text.splitlines()
    # header_idx + 1 is always the separator row (that is what made is_header
    # true for it), so an otherwise-empty table inserts right after that.
    insert_at = (last_idx if last_idx is not None else header_idx + 1) + 1
    lines.insert(insert_at, new_row)
    trailing = "\n" if text.endswith(("\n", "\r\n")) else ""
    return True, "\n".join(lines) + trailing


def remove_contact(text: str, address: str) -> tuple[bool, str]:
    """
    Remove the contacts-table row whose address matches, exactly as
    roster_addresses() would have matched it (normalised, case-insensitive).

    Returns `(True, new_text)` or `(False, reason)`, with the same
    never-claim-success-and-change-nothing rule as add_contact().
    """
    norm = normalise(address)
    target_idx = None
    for fields, is_header, idx in _rows(text, "contacts"):
        if is_header:
            continue
        if any(normalise(f) == norm for f in fields):
            target_idx = idx
            break
    if target_idx is None:
        return False, f"{address} is not on the roster"

    schema_error = write_schema_error(text)
    if schema_error:
        return False, schema_error

    lines = text.splitlines()
    del lines[target_idx]
    trailing = "\n" if text.endswith(("\n", "\r\n")) else ""
    return True, "\n".join(lines) + trailing


def migrate_text(text: str) -> tuple[bool, str, list[str]]:
    """Rewrite legacy contact header columns to their canonical names.

    Only the header row changes; data rows, comments and surrounding text stay
    untouched. Returns (changed, new_text, notes).
    """
    lines = text.splitlines()
    trailing = "\n" if text.endswith(("\n", "\r\n")) else ""
    for fields, is_header, idx in _rows(text, "contacts"):
        if not is_header:
            continue
        changed = False
        new_fields = []
        notes = []
        for field in fields:
            canonical = canonical_column(field)
            if canonical != field.strip().lower():
                pretty = "GitHub" if canonical == "github" else canonical
                new_fields.append(pretty)
                notes.append(f"{field.strip()} -> {pretty}")
                changed = True
            else:
                new_fields.append(field.strip())
        if not changed:
            return False, text, []
        lines[idx] = "| " + " | ".join(new_fields) + " |"
        return True, "\n".join(lines) + trailing, notes
    return False, text, []


def validate_github_login(login: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login or ""))


def validate_type(type_: str) -> bool:
    return not type_ or type_ in {"Human", "AI Agent"}


def batch_add_contacts(text: str, contacts: list[dict], *, migrate: bool = True) -> tuple[bool, str, list[str]]:
    """Validate and add every contact, returning a new roster only if all pass."""
    normalised_rows = []
    seen = set(_addresses_from_text(text))
    batch_seen = set()
    for i, item in enumerate(contacts, 1):
        name = str(item.get("name", "")).strip()
        address = str(item.get("address", item.get("email", ""))).strip()
        type_ = str(item.get("type", "")).strip()
        github = str(item.get("github", "")).strip()
        norm = normalise(address)
        if not name:
            return False, text, [f"row {i}: name is required"]
        if not norm or "@" not in norm:
            return False, text, [f"row {i}: {address!r} is not an email address"]
        if norm in seen or norm in batch_seen:
            return False, text, [f"row {i}: {address} is duplicate"]
        if not validate_type(type_):
            return False, text, [f"row {i}: type must be Human or AI Agent"]
        if github and not validate_github_login(github):
            return False, text, [f"row {i}: invalid GitHub login {github!r}"]
        normalised_rows.append((i, name, address, type_, github))
        batch_seen.add(norm)

    working = text
    notes: list[str] = []
    if migrate:
        changed, working, migration_notes = migrate_text(working)
        if changed:
            notes.extend(["migrate " + note for note in migration_notes])
    for i, name, address, type_, github in normalised_rows:
        ok, result = add_contact(working, name, address, type_=type_, github=github)
        if not ok:
            return False, text, [f"row {i}: {result}"]
        working = result
        notes.append(f"add {address}")
    return True, working, notes


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

    **A `GitHub` column in the contacts table declares GitHub's notifier on its
    own** (`GITHUB_NOTIFIER`), unless a row of the table above already names
    that address, in which case the row wins and nothing is added. The column is
    the human's declaration: a handle written there has no other use, and asking
    for it twice produced rosters full of handles that matched nothing (#188).
    Without the column, nothing is implied.
    """
    text = _read(path)
    out: list[dict] = []
    for fields, is_header, _ in _rows(text, "notifiers"):
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
                    "column": canonical_column(column)})
    if _has_github_column(text) and not any(
            n["address"] == GITHUB_NOTIFIER["address"] for n in out):
        out.append(dict(GITHUB_NOTIFIER, implied_by="github column"))
    return out


def _has_github_column(text: str) -> bool:
    for fields, is_header, _ in _rows(text, "contacts"):
        if is_header:
            return GITHUB_NOTIFIER["column"] in (f.strip().lower() for f in fields)
    return False


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
    return explain_sender(message, allowed, entries, notifier_list)["matched"]


def explain_sender(message: Message, allowed: set[str], entries=(), notifier_list=()) -> dict:
    """Explain the exact decision sender_is_listed() makes, without side effects."""
    address = sender_address(message)
    answer = {"matched": False, "from": address, "kind": "none", "reason": ""}
    if not address:
        answer["reason"] = "the From header has no usable address"
        return answer
    if address in allowed:
        entry = next((e for e in entries if normalise(e.get("address", "")) == address), None)
        answer.update({"matched": True, "kind": "contact", "entry": entry,
                       "reason": f"{address} is a contact in roster.md"})
        return answer

    # A declared notifier speaks for whoever its declared header names, and only
    # for somebody already on the list. It grants nothing on its own: an unknown
    # handle from a declared notifier is exactly as unauthorised as a stranger.
    for notifier in notifier_list or ():
        if address != notifier["address"]:
            continue
        claimed = normalise(message.get(notifier["header"], "")).lstrip("@")
        if not claimed:
            answer.update({"kind": "notifier", "notifier": notifier,
                           "reason": f"declared notifier is missing {notifier['header']}"})
            return answer
        for entry in entries or ():
            recorded = normalise(entry.get("columns", {}).get(notifier["column"], ""))
            if recorded and recorded.lstrip("@") == claimed:
                answer.update({"matched": True, "kind": "notifier", "notifier": notifier,
                               "entry": entry,
                               "reason": (f"{notifier['header']}={claimed} matches "
                                          f"the {notifier['column']} column")})
                return answer
        answer.update({"kind": "notifier", "notifier": notifier,
                       "reason": (f"{notifier['header']}={claimed} matches no contact in "
                                  f"the {notifier['column']} column")})
        return answer
    answer["reason"] = f"{address} is neither a contact nor a declared notifier"
    return answer
