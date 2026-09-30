#!/usr/bin/env python3
"""Small copytruncate log rotator for paynani when system logrotate is unavailable."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import event as ev   # noqa: E402
from paths import state_dir   # noqa: E402

# Asked for, not assumed. A hard-coded state path here would be the one consumer
# with no way to redirect it, and that failure is silent: main() would recreate
# the wrong directory empty, glob no logs, print nothing and exit 0 — so the
# timer reports success every week while the real logs grow without bound.
STATE_DIR = state_dir()
STATE_FILE = STATE_DIR / "rotate-state.json"
LIFECYCLE = STATE_DIR / "lifecycle.jsonl"
JOURNAL = STATE_DIR / "events.jsonl"
CURSOR = STATE_DIR / "dispatch.offset"
MAX_ROTATIONS = 4
MIN_INTERVAL = 7 * 24 * 60 * 60
ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

# The event journal is deliberately not rotated here. It is a queue, not a log:
# the cursor is a byte offset into that exact file. Retention below removes only
# already-delivered additional-account lines, under the same journal lock, and
# rewrites the cursor to the matching byte boundary.


def load_state() -> dict[str, float]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict[str, float]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    os.replace(tmp, STATE_FILE)


def rotate(path: Path) -> None:
    for i in range(MAX_ROTATIONS, 0, -1):
        src = path.with_name(f"{path.name}.{i}")
        dst = path.with_name(f"{path.name}.{i + 1}")
        if i == MAX_ROTATIONS and src.exists():
            src.unlink()
        elif src.exists():
            os.replace(src, dst)

    first = path.with_name(f"{path.name}.1")
    with path.open("rb") as src, first.open("wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
    with path.open("r+b") as fh:
        fh.truncate(0)


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def record_time(record):
    if not isinstance(record, dict):
        return None
    for key in ("at", "observed_at", "created_at"):
        parsed = parse_time(record.get(key))
        if parsed:
            return parsed
    envelope = record.get("envelope")
    if isinstance(envelope, dict):
        for key in ("observed_at", "at", "created_at"):
            parsed = parse_time(envelope.get(key))
            if parsed:
                return parsed
    return None


def additional_account_id(record):
    if not isinstance(record, dict):
        return ""
    for source in (record, record.get("envelope")):
        if not isinstance(source, dict):
            continue
        account_id = str(source.get("account_id") or "").strip()
        if account_id and account_id != "main" and ACCOUNT_ID_RE.match(account_id):
            return account_id

    event_id = str(record.get("event_id") or "")
    parts = event_id.split(":")
    if len(parts) >= 5 and parts[0] == "imap":
        account_id = parts[1]
        if account_id != "main" and ACCOUNT_ID_RE.match(account_id):
            return account_id
    return ""


def retention_days():
    try:
        return max(0, int(os.environ.get("PAYNANI_RETENTION_DAYS", "90")))
    except ValueError:
        return 90


def cutoff_time(now=None, days=None):
    days = retention_days() if days is None else max(0, int(days))
    now = now or datetime.now(timezone.utc)
    return now.timestamp() - (days * 24 * 60 * 60)


def prune_lifecycle(path=LIFECYCLE, now=None, days=None):
    path = Path(path)
    if not path.is_file():
        return 0
    cutoff = cutoff_time(now, days)
    with ev.locked(path):
        lines = path.read_bytes().splitlines(keepends=True)
        events = {}

        for line in lines:
            if not line.endswith(b"\n"):
                continue
            try:
                record = json.loads(line.strip().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            event_id = str(record.get("event_id") or "")
            if event_id and additional_account_id(record):
                events.setdefault(event_id, []).append(record)

        expired = set()
        for event_id, group in events.items():
            timestamps = [record_time(record) for record in group]
            if timestamps and all(stamp is not None for stamp in timestamps):
                if max(stamp.timestamp() for stamp in timestamps) < cutoff:
                    expired.add(event_id)

        if not expired:
            return 0

        kept = []
        removed = 0
        for line in lines:
            try:
                record = json.loads(line.strip().decode("utf-8")) if line.endswith(b"\n") else None
            except (ValueError, UnicodeDecodeError):
                record = None
            if isinstance(record, dict) and str(record.get("event_id") or "") in expired:
                removed += 1
                continue
            kept.append(line)

        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as fh:
            for line in kept:
                fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return removed


def prune_journal(journal=JOURNAL, cursor=CURSOR, now=None, days=None):
    journal = Path(journal)
    cursor = Path(cursor)
    if not journal.is_file():
        return 0
    cutoff = cutoff_time(now, days)

    with ev.locked(journal):
        cursor_offset = ev.read_cursor(cursor)
        size = journal.stat().st_size
        if cursor_offset > size:
            cursor_offset = 0
        lines = journal.read_bytes().splitlines(keepends=True)
        pos = 0
        kept = []
        removed = 0
        removed_before_cursor = 0

        for line in lines:
            end = pos + len(line)
            complete = line.endswith(b"\n")
            remove = False
            if complete and end <= cursor_offset:
                text = line.strip()
                if text:
                    try:
                        record = json.loads(text.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        record = None
                    timestamp = record_time(record)
                    if (
                        isinstance(record, dict)
                        and additional_account_id(record)
                        and timestamp
                        and timestamp.timestamp() < cutoff
                    ):
                        remove = True
            if remove:
                removed += 1
                removed_before_cursor += len(line)
            else:
                kept.append(line)
            pos = end

        if not removed:
            return 0

        tmp = journal.with_suffix(journal.suffix + ".tmp")
        with tmp.open("wb") as fh:
            for line in kept:
                fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, journal)
        ev.write_cursor(cursor, max(0, cursor_offset - removed_before_cursor))
        return removed


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    state = load_state()
    changed = False

    for path in sorted(STATE_DIR.glob("*.log")):
        try:
            if not path.is_file() or path.stat().st_size == 0:
                continue
            last = float(state.get(str(path), 0))
            if now - last < MIN_INTERVAL:
                continue
            rotate(path)
            state[str(path)] = now
            changed = True
            print(f"rotated {path}")
        except OSError as exc:
            print(f"could not rotate {path}: {exc}", file=os.sys.stderr)

    if changed:
        save_state(state)
    try:
        removed = prune_lifecycle()
        if removed:
            print(f"retained {LIFECYCLE}: removed {removed} old additional-account record(s)")
    except OSError as exc:
        print(f"could not retain {LIFECYCLE}: {exc}", file=os.sys.stderr)
    try:
        removed = prune_journal()
        if removed:
            print(f"retained {JOURNAL}: removed {removed} old additional-account record(s)")
    except OSError as exc:
        print(f"could not retain {JOURNAL}: {exc}", file=os.sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
