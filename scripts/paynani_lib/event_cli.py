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

from paynani_lib import accounts  # noqa: E402  (absolute: test_event_lifecycle.py imports this file as a top-level module)


def _accounts_file() -> Path:
    """accounts.json beside the env file, which is where `paynani account add` writes it."""
    return env_file().parent / accounts.FILENAME


def _account_for(record):
    """
    The additional account this event came from, or None for the agent's own.

    An event of `ventas@` is read with `ventas@`'s login and held to `ventas@`'s
    roster; deciding it against the agent's roster.md would be the other
    account's permission (#276). The account id is on the record, and for a record
    that lost it the event id still has it. RuntimeError, saying which account,
    when accounts.json no longer lists it: the agent's login must not stand in
    for an account that is gone.
    """
    account_id = str(record.get("account_id") or "").strip()
    path = _accounts_file()
    if not account_id:
        try:
            known = {a["id"] for a in accounts.load(path)}
            if known:
                account_id = accounts.parse_event_id(str(record.get("event_id") or ""), known_ids=known)[0]
        except accounts.AccountsError:
            return None
    if not account_id or account_id == accounts.MAIN:
        return None
    try:
        return accounts.get(account_id, path)
    except accounts.AccountsError as exc:
        raise RuntimeError(f"this event belongs to account {account_id!r}: {exc}") from exc


def _roster_of(account):
    return accounts.roster_path(account, _accounts_file()) if account else roster_file()


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
        "schema_version", "event_type", "event_id", "source", "account", "account_id",
        "mailbox", "uidvalidity", "uid", "observed_at", "sent_at", "sender",
        "subject", "roster_match", "authenticated_sender", "message_id",
        "provider_id", "recipient_role", "notifier_headers", "inspection_command",
    )
    return {key: record[key] for key in allowed if key in record}


def _roster_label(account) -> str:
    """The name of the roster that decides for this account, as a reader knows it."""
    return account["roster"] if account is not None else "roster.md"


def _authorization(record, path=None, label="roster.md"):
    """The roster decision for a saved event. `path` is the roster of the event's
    account; None means roster.md, and for an account that is gone (`path` False),
    only what the listener recorded is left to show."""
    sender = (record.get("sender") or {}).get("address", "")
    if path is False:
        return {
            "matched": bool(record.get("roster_match")),
            "kind": "recorded",
            "reason": "the listener recorded this decision; the account's roster is not available any more",
        }
    path = roster_file() if path is None else path
    message = email.message.EmailMessage()
    message["From"] = sender
    for header, value in (record.get("notifier_headers") or {}).items():
        if str(header).strip() and str(value).strip():
            message[str(header).strip()] = str(value).strip()
    notifiers = roster_mod.notifiers(path)
    decision = roster_mod.explain_sender(
        message,
        roster_mod.roster_addresses(path),
        roster_mod.roster_entries(path),
        notifiers,
        roster_label=label,
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
    elif (
        not record.get("roster_match")
        and decision.get("kind") == "notifier"
        and str(decision.get("reason") or "").startswith("declared notifier is missing ")
    ):
        notifier = decision.get("notifier") or {}
        header = notifier.get("header", "the provider header")
        decision = dict(decision)
        decision["reason"] = (
            f"cannot determine notifier authorization from the saved event: "
            f"the journal does not retain {header}; run `paynani roster explain` "
            "against the original message headers and check this host's roster.md"
        )
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


def _agent_roster_entry(agent_address: str, path=None):
    agent = roster_mod.normalise(agent_address)
    for entry in roster_mod.roster_entries(roster_file() if path is None else path):
        if roster_mod.normalise(entry.get("address", "")) == agent:
            return entry
    return {"address": agent, "name": "", "columns": {}}


def _recipient_role(record, message) -> tuple[str, str | None]:
    live = idle_listener.recipient_role_for(message, record.get("account", ""))
    recorded = str(record.get("recipient_role") or "").strip()
    return live, (recorded or None)


def _with_recorded_role_disagreement(summary: dict, recorded: str | None) -> dict:
    if recorded and summary.get("recipient_role") != recorded:
        summary["recipient_role_recorded"] = recorded
        summary["recipient_role_disagreement"] = True
    return summary


def _marker_summary(record, message, body: str, roster_path=None) -> dict:
    role, recorded = _recipient_role(record, message)
    if role == "to":
        return _with_recorded_role_disagreement({
            "recipient_role": role,
            "marker_for_me": True,
            "marker_lines": [],
        }, recorded)

    entry = _agent_roster_entry(record.get("account", ""), roster_path)
    markers = [entry.get("address", ""), entry.get("name", "")]
    prefixes = tuple(
        marker.casefold() + ":"
        for marker in markers
        if str(marker or "").strip()
    )
    marker_lines = [
        line.lstrip()
        for line in body.splitlines()
        if prefixes and line.lstrip().casefold().startswith(prefixes)
    ]
    return _with_recorded_role_disagreement({
        "recipient_role": role,
        "marker_for_me": bool(marker_lines),
        "marker_lines": marker_lines,
    }, recorded)


def fetch_verified(record, *, include_body=False):
    """Fetch one exact UID and recheck its envelope and current roster decision."""
    if record.get("event_type") != event_mod.MAIL_RECEIVED:
        raise RuntimeError("only email.received events have a message body")
    if not record.get("roster_match"):
        raise PermissionError("body refused: the listener did not record a roster match")
    account = _account_for(record)
    env = idle_listener.load_env(env_file())
    if account is not None:
        # The additional account's own login, from accounts.json and the password
        # it names in the .env: never the agent's, which would read the wrong mailbox.
        env = accounts.env_for(account, env)
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

    path = _roster_of(account)
    decision = roster_mod.explain_sender(
        message,
        roster_mod.roster_addresses(path),
        roster_mod.roster_entries(path),
        roster_mod.notifiers(path),
        roster_label=_roster_label(account),
    )
    if not record.get("roster_match") or not decision["matched"]:
        raise PermissionError(f"body refused: {decision['reason']}")
    return message, decision


def run_show(args) -> int:
    record = _find(args.event_id)
    if record is None:
        print(f"Event not found: {args.event_id}", file=sys.stderr)
        return 1
    if record.get("event_type") in _SMS_EVENT_TYPES:
        return _show_sms(record, args)
    try:
        account = _account_for(record)
        roster_path = _roster_of(account) if account is not None else None
    except RuntimeError:
        # The account is gone from accounts.json: the envelope can still be shown,
        # with what the listener recorded; fetching a body below refuses.
        account, roster_path = None, False
    decision = _authorization(record, roster_path, _roster_label(account))
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
    if not args.body:
        if verified is not None:
            role, recorded = _recipient_role(record, verified)
            output.update(_with_recorded_role_disagreement({"recipient_role": role}, recorded))
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if not record.get("roster_match"):
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
        print("body refused: the listener did not record a roster match", file=sys.stderr)
        return 2
    body = _body_text(verified)
    output.update(_marker_summary(record, verified, body, roster_path))
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
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


# SMS y llamadas (SMS_GATEWAY.md §6). El texto de un SMS no está en el sobre:
# vive en state/sms/inbox/ y sólo sale con --body, con la misma regla que el
# cuerpo de un correo: el número tiene que haber sido del roster al llegar y
# seguir siéndolo ahora.
_SMS_EVENT_TYPES = ("sms.received", "call.missed", "call.answered")
_SMS_SAFE_FIELDS = ("event_id", "event_type", "account", "device_id", "observed_at", "sent_at",
                    "started_at", "duration_s", "sender", "roster_match", "authenticated_sender",
                    "provider_id", "notification_text", "inspection_command")


def _show_sms(record, args) -> int:
    from paynani_lib.sms import gateway as sms_gateway
    from paynani_lib.sms.store import Store

    output = {k: record[k] for k in _SMS_SAFE_FIELDS if k in record}
    address = (record.get("sender") or {}).get("address", "")
    in_roster_now = address in sms_gateway.roster_phones(roster_file())
    output["roster_decision"] = {
        "matched": bool(record.get("roster_match")) and in_roster_now,
        "reason": ("the number is on roster.md (Phone)" if in_roster_now
                   else "the number is not on roster.md (Phone) now"),
    }
    output["lifecycle"] = ledger.history(state_dir() / "lifecycle.jsonl", args.event_id)
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    if not args.body:
        return 0
    if record.get("event_type") != "sms.received":
        print("calls have no body", file=sys.stderr)
        return 2
    if not record.get("roster_match"):
        print("body refused: the gateway did not record a roster match", file=sys.stderr)
        return 2
    if not in_roster_now:
        print("body refused: the number is no longer on roster.md", file=sys.stderr)
        return 2
    message_id = str(record.get("provider_id", "")).split(":", 1)[-1]
    saved = Store(state_dir()).inbox(message_id)
    if not saved:
        print("body not found in state/sms/inbox/", file=sys.stderr)
        return 1
    text = str(saved.get("text", ""))
    print("\n--- verified body ---")
    print(text, end="" if text.endswith("\n") else "\n")
    print("--- authorized: the number is on roster.md (Phone) ---")
    return 0
