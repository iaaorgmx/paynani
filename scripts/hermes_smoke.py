#!/usr/bin/env python3
"""Verify Hermes health and both signed paynani routes for FR7 install."""

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.adapters import RETRY  # noqa: E402
from harness.adapters import hermes  # noqa: E402
from harness.event import listener_error, mail_event  # noqa: E402

EX_CONFIG = 78
EX_TEMPFAIL = 75


def _fail(result, label):
    print(f"install: {label} failed: {result.detail}", file=sys.stderr)
    return EX_TEMPFAIL if result.status == RETRY else EX_CONFIG


def _envelope(roster_match, token):
    route = "roster" if roster_match else "notify"
    return mail_event(
        account="installer-smoke@invalid.example",
        mailbox="INBOX",
        uidvalidity="installer-smoke",
        uid=int(token[:15], 16) + (1 if roster_match else 0),
        sender_name="Paynani Installer Smoke",
        sender_address="installer-smoke@invalid.example",
        subject=f"paynani installer {route} smoke probe",
        sent_at="",
        roster_match=roster_match,
        notification_text=f"paynani installer {route} route smoke probe",
    )


def _listener_error_envelope(token):
    return listener_error(
        account="installer-smoke@invalid.example",
        message=f"installer synthetic listener error smoke probe {token}",
    )


def main():
    if os.environ.get("HERMES_SIGNATURE_MODE", "v2").strip().lower() != "v2":
        print("install: Hermes installer smoke probes require HERMES_SIGNATURE_MODE=v2", file=sys.stderr)
        return EX_CONFIG

    health = hermes.check()
    if not health.ok:
        return _fail(health, "Hermes health probe")
    print("hermes_health_probe=accepted scope=reachability-only")

    token = uuid.uuid4().hex
    notify = hermes.deliver(_envelope(False, token))
    if notify is None:
        print("install: Hermes notify-route smoke probe returned no result", file=sys.stderr)
        return EX_CONFIG
    if not notify.ok:
        return _fail(notify, "Hermes notify-route smoke probe")
    print("hermes_notify_smoke=delivered")

    listener_error_result = hermes.deliver(_listener_error_envelope(token))
    if listener_error_result is None:
        print("install: Hermes listener.error notify-route smoke probe returned no result", file=sys.stderr)
        return EX_CONFIG
    if not listener_error_result.ok:
        return _fail(listener_error_result, "Hermes listener.error notify-route smoke probe")
    print("hermes_notify_listener_error_smoke=delivered")

    roster = hermes.deliver(_envelope(True, token))
    if roster is None:
        print("install: Hermes roster-route smoke probe returned no result", file=sys.stderr)
        return EX_CONFIG
    if not roster.ok:
        return _fail(roster, "Hermes roster-route smoke probe")
    print("hermes_roster_smoke=accepted completion=unconfirmed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
