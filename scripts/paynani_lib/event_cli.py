"""Inspect canonical paynani events without putting mail bodies in the journal."""

from __future__ import annotations

import email
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "harness"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import event as event_mod  # noqa: E402
import idle_listener  # noqa: E402
import ledger  # noqa: E402
import roster as roster_mod  # noqa: E402
from paths import env_file, roster as roster_file, state_dir  # noqa: E402


def _find(event_id: str, journal: Path | None = None):
    journal = journal or state_dir() / "events.jsonl"
    for record, _ in event_mod.read_from(journal, 0) or ():
        if not isinstance(record, event_mod.Corrupt) and record.get("event_id") == event_id:
            return record
    for record in ledger.history(state_dir() / "lifecycle.jsonl", event_id):
        envelope = record.get("envelope")
        if isinstance(envelope, dict) and envelope.get("event_id") == event_id:
            return envelope
    return None


def _safe_record(record):
    allowed = (
        "schema_version", "event_type", "event_id", "source", "account",
        "mailbox", "uidvalidity", "uid", "observed_at", "sent_at", "sender",
        "subject", "roster_match", "authenticated_sender", "message_id",
        "provider_id", "inspection_command",
    )
    return {key: record[key] for key in allowed if key in record}


def _authorization(record):
    sender = (record.get("sender") or {}).get("address", "")
    path = roster_file()
    message = email.message.EmailMessage()
    message["From"] = sender
    decision = roster_mod.explain_sender(
        message,
        roster_mod.roster_addresses(path),
        roster_mod.roster_entries(path),
        roster_mod.notifiers(path),
    )
    # A notifier match depends on a provider header that the legacy event does
    # not retain. The listener's original positive decision is therefore valid
    # for display, while a body fetch rechecks against the fetched message below.
    if record.get("roster_match") and not decision["matched"]:
        decision = {
            "matched": True,
            "kind": "recorded",
            "reason": "the listener recorded a roster/notifier match at observation time",
        }
    return decision


def _body_text(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() != "text/plain":
                continue
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            return (payload or b"").decode(charset, errors="replace")
        return ""
    payload = message.get_payload(decode=True)
    charset = message.get_content_charset() or "utf-8"
    return (payload or b"").decode(charset, errors="replace")


def fetch_verified(record, *, include_body=False):
    """Fetch one exact UID and recheck its envelope and current roster decision."""
    if record.get("event_type") != event_mod.MAIL_RECEIVED:
        raise RuntimeError("only email.received events have a message body")
    if not record.get("roster_match"):
        raise PermissionError("body refused: the listener did not record a roster match")
    env = idle_listener.load_env(env_file())
    configured = idle_listener.lookup(env, "user").strip().lower()
    if configured != str(record.get("account") or "").strip().lower():
        raise RuntimeError("event account does not match the configured mailbox account")

    conn = idle_listener.connect(env)
    try:
        mailbox = str(record.get("mailbox") or "")
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"IMAP refused mailbox {mailbox!r}")
        current_validity = idle_listener.uidvalidity(conn, mailbox)
        if str(current_validity or "") != str(record.get("uidvalidity") or ""):
            raise RuntimeError("UIDVALIDITY changed; refusing to fetch a possibly different message")
        query = "(BODY.PEEK[])" if include_body else "(BODY.PEEK[HEADER])"
        typ, payload = conn.uid("fetch", str(record.get("uid")), query)
        if typ != "OK" or not payload or not isinstance(payload[0], tuple):
            raise RuntimeError("IMAP did not return the exact UID")
        metadata = payload[0][0]
        if isinstance(metadata, bytes):
            expected_uid = str(record.get("uid")).encode("ascii")
            if not re.search(rb"\bUID\s+" + expected_uid + rb"\b", metadata):
                raise RuntimeError("IMAP response did not confirm the requested UID")
        message = email.message_from_bytes(payload[0][1])
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    actual_sender = roster_mod.sender_address(message)
    expected_sender = roster_mod.normalise((record.get("sender") or {}).get("address", ""))
    if actual_sender != expected_sender:
        raise RuntimeError("fetched From does not match the journal envelope")
    expected_mid = str(record.get("message_id") or "").strip().lower()
    actual_mid = idle_listener.decode_hdr(message.get("Message-ID")).strip().lower()
    if expected_mid and actual_mid != expected_mid:
        raise RuntimeError("fetched Message-ID does not match the journal envelope")

    path = roster_file()
    decision = roster_mod.explain_sender(
        message,
        roster_mod.roster_addresses(path),
        roster_mod.roster_entries(path),
        roster_mod.notifiers(path),
    )
    if not record.get("roster_match") or not decision["matched"]:
        raise PermissionError(f"body refused: {decision['reason']}")
    return message, decision


def run_show(args) -> int:
    record = _find(args.event_id)
    if record is None:
        print(f"Event not found: {args.event_id}", file=sys.stderr)
        return 1
    decision = _authorization(record)
    verified = None
    if record.get("roster_match"):
        try:
            verified, decision = fetch_verified(record, include_body=args.body)
        except PermissionError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Envelope verification failed: {exc}", file=sys.stderr)
            return 1
    output = _safe_record(record)
    output["roster_decision"] = decision
    output["envelope_verified"] = bool(verified)
    output["lifecycle"] = ledger.history(state_dir() / "lifecycle.jsonl", args.event_id)
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    if not args.body:
        return 0
    if not record.get("roster_match"):
        print("body refused: the listener did not record a roster match", file=sys.stderr)
        return 2
    body = _body_text(verified)
    print("\n--- verified body ---")
    print(body, end="" if body.endswith("\n") else "\n")
    print(f"--- authorized: {decision['reason']} ---")
    return 0


def run_list(args) -> int:
    journal = state_dir() / "events.jsonl"
    ledger_path = state_dir() / "lifecycle.jsonl"
    envelopes = {}
    order = []
    for item in ledger.records(ledger_path):
        record = item.get("envelope")
        if not isinstance(record, dict):
            continue
        event_id = record.get("event_id", "")
        if event_id and event_id not in envelopes:
            envelopes[event_id] = record
            order.append(event_id)
    for record, _ in event_mod.read_from(journal, 0) or ():
        if isinstance(record, event_mod.Corrupt):
            continue
        event_id = record.get("event_id", "")
        if event_id and event_id not in envelopes:
            envelopes[event_id] = record
            order.append(event_id)
    current = ledger.latest(ledger_path)
    selected = order[-args.limit:] if args.limit > 0 else []
    for event_id in selected:
        record = envelopes[event_id]
        last = current.get(event_id, {})
        print(f"{event_id}\t{last.get('state', 'unknown')}\t{record.get('event_type', '')}")
    return 0


def run_mark(args) -> int:
    record = _find(args.event_id)
    if record is None:
        print(f"Event not found: {args.event_id}", file=sys.stderr)
        return 1
    ledger.transition(
        state_dir() / "lifecycle.jsonl", args.event_id, args.state,
        runtime=args.runtime or "", detail=args.detail or "",
        message_id=record.get("message_id", ""), provider_id=record.get("provider_id", ""),
    )
    print(f"{args.event_id}: {args.state}")
    return 0
