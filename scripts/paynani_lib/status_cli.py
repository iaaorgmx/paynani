"""Operational event and Codex delivery status."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "harness"))

import ledger  # noqa: E402
from adapters import codex as codex_adapter  # noqa: E402
from paths import state_dir  # noqa: E402


def _integer(path):
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def _nonempty(path):
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def facts():
    state = state_dir()
    current = ledger.latest(state / "lifecycle.jsonl")
    counts = {}
    for item in current.values():
        name = item.get("state", "unknown")
        counts[name] = counts.get(name, 0) + 1
    spool = state / "codex.spool"
    session = state / "codex.session"
    delivery = {}
    try:
        delivery = json.loads((state / "delivery.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    codex_delivery = {}
    try:
        codex_delivery = json.loads((state / "codex.delivery.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {
        "lifecycle_counts": counts,
        "events_known": len(current),
        "events": [current[event_id] for event_id in sorted(current)],
        "codex": {
            "session_registered": _nonempty(session),
            "spool_bytes": spool.stat().st_size if spool.exists() else 0,
            "acknowledged_bytes": _integer(state / "codex.offset"),
            "delivery": delivery,
            "activity": codex_delivery,
            "queue_contract": codex_adapter.queue_contract(),
        },
    }


def run(args) -> int:
    data = facts()
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    print(f"Events: {data['events_known']}")
    for state, count in sorted(data["lifecycle_counts"].items()):
        print(f"  {state}: {count}")
    for item in data["events"]:
        related = f" → {item['related_event_id']}" if item.get("related_event_id") else ""
        detail = f" ({item['detail']})" if item.get("detail") else ""
        print(f"  {item.get('event_id', '')}: {item.get('state', 'unknown')}{related}{detail}")
    codex = data["codex"]
    print(f"Codex session: {'registered' if codex['session_registered'] else 'not registered'}")
    print(f"Codex spool: {codex['acknowledged_bytes']}/{codex['spool_bytes']} bytes acknowledged")
    accepted = codex["delivery"].get("last_accepted")
    error = codex["delivery"].get("last_error")
    if accepted:
        print(f"Last accepted: {accepted.get('event_id', '')} ({accepted.get('detail', '') or 'ok'})")
    if error:
        print(f"Last error: {error.get('event_id', '')} ({error.get('detail', '')})")
    for key, label in (("last_queue", "Last queue"), ("last_spool", "Last spool fallback"),
                       ("last_replay", "Last replay")):
        item = codex["activity"].get(key)
        if item:
            print(f"{label}: {item.get('event_id', '')} at {item.get('at', '')}")
    contract = codex["queue_contract"]
    print(f"Codex queue contract: {contract['state']} ({contract['detail']})")
    return 0
