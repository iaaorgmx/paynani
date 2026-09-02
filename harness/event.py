#!/usr/bin/env python3
"""
The canonical event envelope, and the append-only journal that holds it.

This is the seam between the half that knows about mail and the half that knows
about a harness. The listener writes envelopes; a runtime adapter reads them and
delivers them. Neither has to know anything about the other, which is the whole
reason this file exists: before it, delivering to a second harness meant parsing
a human-readable log line written for a person to read.

Two properties the rest of the design leans on:

**A record is only ever read once it is whole.** Records are appended as one
write each and consumed only up to the last newline, so a reader can never see
half of one. Without that the cursor could stop inside a record and the next read
would start mid-JSON.

**The cursor is a byte offset of a record boundary.** It advances only past
records a runtime has accepted, so the answer to "what has been delivered" is one
number on disk that survives a restart.
"""

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

MAIL_RECEIVED = "email.received"
LISTENER_ERROR = "listener.error"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def event_id(mailbox, uidvalidity, uid):
    """
    Stable across retries and restarts, which is what makes an adapter's
    deduplication mean anything.

    UIDVALIDITY is in here deliberately. A mailbox rebuilt on the server resets
    UIDs, so without it a new message could take the ID of an old one. Including
    it means a reset produces new IDs instead: the cost is that mail already seen
    can be delivered a second time after a rebuild, which is a duplicate rather
    than a collision, and duplicates are what this design accepts.
    """
    return f"imap:{mailbox}:{uidvalidity}:{uid}"


def mail_event(*, account, mailbox, uidvalidity, uid, sender_name, sender_address,
               subject, sent_at, roster_match, notification_text, observed_at=None):
    """
    One arrived message, as structure rather than prose.

    No body and no credentials, ever. The listener is a doorbell: it says that
    mail arrived and from whom, and reading it is the agent's job through
    Himalaya, afterwards. An envelope that carried the body would put untrusted
    content into every transport that touches it.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": MAIL_RECEIVED,
        "event_id": event_id(mailbox, uidvalidity, uid),
        "source": "paynani",
        # Which configured account, not which folder. An adapter that has to
        # fetch the message needs both, and a route serving more than one install
        # cannot work out the first from the second.
        "account": (account or "").strip().lower(),
        "mailbox": mailbox,
        "uidvalidity": str(uidvalidity),
        "uid": int(uid),
        "observed_at": observed_at or _now(),
        "sent_at": sent_at or "",
        "sender": {"name": sender_name or "", "address": (sender_address or "").lower()},
        "subject": subject or "",
        # An exact match against a human-maintained allowlist, compared against a
        # From header that anyone can forge. That is routing metadata and nothing
        # more. It is not authenticated identity, and no consumer may present it
        # as one; the separate field below stays false until something actually
        # validates provider authentication results.
        "roster_match": bool(roster_match),
        "authenticated_sender": False,
        # The rendered line, kept because OpenClaw's delivery takes exactly one
        # string and this is where its wording is decided. Adapters that build
        # their own payload should read the structured fields instead: this is
        # for display, not for routing.
        "notification_text": notification_text,
    }


def listener_error(*, account, message, observed_at=None):
    """
    A listener fault, in the same stream as the mail.

    It travels the same path as everything else on purpose. A fault reported
    somewhere a delivery is not looked at is a fault nobody sees, and silence
    that reads as an empty mailbox is the failure this project exists to prevent.
    """
    # Resolved first, because the id is derived from it. Hashing the argument
    # rather than the value gave the same fault two different ids depending on
    # whether the caller passed a time or let this fill one in.
    observed_at = observed_at or _now()
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": LISTENER_ERROR,
        "event_id": "listener:" + hashlib.sha256(
            f"{observed_at}|{message}".encode("utf-8")).hexdigest()[:16],
        "source": "paynani",
        "account": (account or "").strip().lower(),
        "observed_at": observed_at,
        "message": message,
        "notification_text": f"[listener] {message}",
    }


LOCK_SUFFIX = ".lock"


@contextmanager
def locked(journal):
    """
    Hold the journal lock.

    Appending is a single `O_APPEND` write and needs no lock against another
    append. The lock exists for compaction, which reads the size, decides, and
    truncates: without it an append landing between the decision and the
    truncation is destroyed, and it was never delivered. One lock taken by both
    closes that window.

    The lock is a separate file, not the journal, so truncating the journal
    cannot disturb it.
    """
    path = Path(str(journal) + LOCK_SUFFIX)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def append(journal, record):
    """
    Add one record durably. Returns the offset just past it.

    Raises on any failure, and the caller must treat that as "this message is
    not queued". Returning quietly here is how a message gets marked seen by the
    listener while existing nowhere a dispatcher will look.

    Three things this has to get right, in order:

    - **Write every byte.** One `os.write` may write fewer bytes than it was
      given. A short write leaves a truncated line in the queue.
    - **Then flush it to disk.** The listener persists its last-seen UID after
      this returns, and that state is what stops a message being fetched twice.
      If the UID reaches the disk and the record does not, a crash in between
      loses the message for good. `fsync` is what orders those two.
    - **Only then report the offset.** It is the caller's evidence the record is
      safe to acknowledge.
    """
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    data = line.encode("utf-8")
    with locked(journal):
        fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
            os.fsync(fd)
            return os.lseek(fd, 0, os.SEEK_CUR)
        finally:
            os.close(fd)


def compact(journal, cursor_path, min_size=0):
    """
    Empty the journal, but only while holding the lock and only when the cursor
    proves every record in it was delivered. Returns the number of bytes freed.

    The size is read inside the lock, so an append cannot land between the
    decision and the truncation. Truncating before resetting the cursor is
    deliberate: interrupted in between, the cursor points past the end of an
    empty file, which readers already treat as "start from the beginning", and
    that is correct because there is nothing left to read.
    """
    journal = Path(journal)
    with locked(journal):
        if not journal.is_file():
            return 0
        size = journal.stat().st_size
        if size < min_size or size == 0:
            return 0
        if read_cursor(cursor_path) < size:
            return 0
        with journal.open("r+b") as fh:
            fh.truncate(0)
            fh.flush()
            os.fsync(fh.fileno())
        write_cursor(cursor_path, 0)
        return size


class Corrupt:
    """
    A complete record that will not parse.

    Yielded rather than skipped. Skipping it advanced the cursor past it as soon
    as anything after it was accepted, which is a dead-letter policy nobody chose
    and no one was told about. It stops the queue instead, loudly, and a person
    decides what to do about it.
    """

    __slots__ = ("raw", "offset")

    def __init__(self, raw, offset):
        self.raw = raw
        self.offset = offset


def read_from(journal, offset):
    """
    Yield (record, offset_past_it) for records at or after `offset`.

    A trailing fragment is left alone: the writer may be partway through it, and
    it will be whole by the next read. A complete line that will not parse is
    yielded as `Corrupt` so the consumer can refuse to move past it.
    """
    journal = Path(journal)
    if not journal.is_file():
        return
    size = journal.stat().st_size
    # A journal shorter than the cursor means it was compacted or replaced.
    if offset > size:
        offset = 0
    with journal.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
    pos = offset
    for chunk in data.split(b"\n")[:-1]:
        # Where this record starts, kept before the cursor moves past it: a
        # repair instruction has to name the byte the damage begins at, not the
        # one after it ends.
        start = pos
        pos += len(chunk) + 1
        text = chunk.strip()
        if not text:
            continue
        try:
            yield json.loads(text.decode("utf-8")), pos
        except (ValueError, UnicodeDecodeError):
            yield Corrupt(text[:200], start), pos


def read_cursor(path):
    try:
        return int(Path(path).read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def write_cursor(path, offset):
    """
    Replaced whole rather than rewritten in place, so a reader never catches a
    half-written number. It is the one value that decides what has been
    delivered.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(str(int(offset)))
    os.replace(tmp, path)
