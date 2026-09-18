#!/usr/bin/env python3
"""Append-only lifecycle ledger for canonical paynani events.

The event journal is the delivery queue and may be compacted.  This ledger is
an audit trail: it never carries mail bodies, never drives the dispatch cursor,
and survives journal compaction so status can explain what happened later.
"""

from __future__ import annotations

import time
from pathlib import Path

import event as ev

SCHEMA_VERSION = 1
STATES = ("observed", "dispatched", "presented", "handled", "replied", "closed", "suppressed")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def path_for(journal):
    return Path(journal).with_name("lifecycle.jsonl")


def transition(ledger_path, event_id, state, *, runtime="", detail="",
               message_id="", provider_id="", related_event_id="", at=None,
               envelope=None):
    """Append one transition, unless it is byte-for-byte the current state."""
    if state not in STATES:
        raise ValueError(f"unknown lifecycle state {state!r}")
    event_id = str(event_id or "").strip()
    if not event_id:
        raise ValueError("a lifecycle transition requires event_id")
    previous = latest(ledger_path).get(event_id)
    identity = (state, runtime or "", detail or "", related_event_id or "")
    if previous and identity == tuple(previous.get(k, "") for k in
                                      ("state", "runtime", "detail", "related_event_id")):
        return False
    record = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "state": state,
        "at": at or _now(),
    }
    for key, value in (("runtime", runtime), ("detail", detail),
                       ("message_id", message_id), ("provider_id", provider_id),
                       ("related_event_id", related_event_id)):
        if value:
            record[key] = str(value)
    if envelope:
        record["envelope"] = envelope
    ev.append(ledger_path, record)
    return True


def observed(ledger_path, envelope):
    event_id = str(envelope.get("event_id") or "").strip()
    if event_id and event_id in latest(ledger_path):
        return False
    safe_keys = (
        "schema_version", "event_type", "event_id", "source", "account",
        "mailbox", "uidvalidity", "uid", "observed_at", "sent_at", "sender",
        "subject", "roster_match", "authenticated_sender", "message_id",
        "provider_id", "inspection_command",
    )
    safe_envelope = {key: envelope[key] for key in safe_keys if key in envelope}
    return transition(
        ledger_path, event_id, "observed",
        message_id=envelope.get("message_id", ""),
        provider_id=envelope.get("provider_id", ""),
        at=envelope.get("observed_at") or None,
        envelope=safe_envelope,
    )


def records(ledger_path):
    out = []
    stream = ev.read_from(ledger_path, 0)
    if stream is None:
        return out
    for record, _ in stream:
        if not isinstance(record, ev.Corrupt) and isinstance(record, dict):
            out.append(record)
    return out


def latest(ledger_path):
    out = {}
    for record in records(ledger_path):
        event_id = str(record.get("event_id") or "")
        if event_id:
            out[event_id] = record
    return out


def history(ledger_path, event_id):
    return [r for r in records(ledger_path) if r.get("event_id") == event_id]


def duplicate_of(ledger_path, envelope):
    """Return the earlier canonical event represented by this envelope."""
    event_id = str(envelope.get("event_id") or "")
    message_id = str(envelope.get("message_id") or "").strip().lower()
    provider_id = str(envelope.get("provider_id") or "").strip().lower()
    for record in records(ledger_path):
        earlier = str(record.get("event_id") or "")
        if not earlier:
            continue
        if earlier == event_id and record.get("state") not in ("observed",):
            return earlier
        if earlier == event_id:
            continue
        same_provider = provider_id and provider_id == str(record.get("provider_id") or "").lower()
        same_message = message_id and message_id == str(record.get("message_id") or "").lower()
        if same_provider or same_message:
            return earlier
    return ""
