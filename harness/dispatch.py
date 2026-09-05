#!/usr/bin/env python3
"""
Read the event journal, hand each record to the configured runtime, and move the
cursor only once the runtime has taken it.

This replaces `watch.sh`, and it is not a translation of it. The old watcher read
a log through `tail -F`, which meant a line it had consumed was gone from the
pipe whether or not it had been delivered. Retrying meant holding the line in
memory; recovering from a sustained failure meant killing the process so systemd
could start it again from a stored offset.

Reading a journal by offset removes the reason for all of that. Nothing is
consumed by being read, so a failed record can be retried in place forever
without the process dying and without anything being held anywhere. The exit and
restart dance is gone.

What is left is one rule: **the cursor moves past a record only when an adapter
has accepted it.** Every silent-loss defect this project has had was some version
of moving it when the runtime had not.
"""

import argparse
import errno
import fcntl
import importlib
import os
import random
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import event as ev   # noqa: E402
from adapters import ACCEPTED, CONFIG, RETRY   # noqa: E402
from paths import state_dir   # noqa: E402

STATE_DIR = state_dir()
JOURNAL = STATE_DIR / "events.jsonl"
CURSOR = STATE_DIR / "dispatch.offset"
LOCK = STATE_DIR / "dispatch.lock"
# What the runtime last said, kept where a health check can read it. The adapter
# knows the HTTP result; this file is the runtime-neutral durable observation of
# it, which is the dispatcher's to own because it is the thing that decided the
# cursor could move.
STATUS = STATE_DIR / "delivery.json"
# Compact once the journal is worth compacting, and only from here: the
# dispatcher is the only process that knows what it has delivered.
JOURNAL_MAX = int(os.environ.get("DISPATCH_JOURNAL_MAX", 4 * 1024 * 1024))

KNOWN_RUNTIMES = ("openclaw", "hermes", "claudecode", "codex")

# How long to wait before trying a failed record again. Doubling, capped, so a
# runtime that is down for an hour is retried every minute rather than every
# second, and one that blinks is retried almost at once.
RETRY_MIN = float(os.environ.get("DISPATCH_RETRY_MIN", 2))
RETRY_MAX = float(os.environ.get("DISPATCH_RETRY_MAX", 60))
RETRY_JITTER = float(os.environ.get("DISPATCH_RETRY_JITTER", 0.2))
# Accepted backlog is deliberately paced so a recovered fleet does not turn a
# quiet outage into a synchronized burst against Hermes route rate limits.
CATCHUP_PACE = float(os.environ.get("DISPATCH_CATCHUP_PACE", 0.05))
# Configuration faults get their own, longer, pause. Nothing about retrying fixes
# them, so the only reason to try again at all is to notice when a human has.
CONFIG_RETRY = float(os.environ.get("DISPATCH_CONFIG_RETRY", 60))
# How often to look for new records when the journal is quiet.
POLL = float(os.environ.get("DISPATCH_POLL", 1))


def log(message):
    """
    Diagnostics go to stderr, which the unit appends to a file a person can read.

    The dispatcher cannot report its own failures through the runtime it is
    failing to reach, so this file is the only way a broken delivery path becomes
    visible. session_start.py reads it at the start of the next session.
    """
    print(message, file=sys.stderr, flush=True)


def note(message):
    """
    A routine diagnostic: something happened and nothing is wrong.

    Same file as log(), marked so session_start.py can tell the two apart. It
    used to be indistinguishable, which meant the line every healthy startup
    writes was read as a fault and every session opened with a warning. An alarm
    that sounds on the good path is one people learn to ignore, and this one
    exists for the failure nothing else can see.
    """
    log(ev.ROUTINE_PREFIX + message)


# What has already been written to each status file, so an answer that has not
# changed is not written again. Keyed by the resolved path, because one process
# may write more than one, and holding every field that is persisted, because
# anything left out of the key is a change this cannot see.
#
# The remembered answer is paired with the state of the file it went into. A
# cached answer says what was written, never that it is still there: delete the
# file under a running dispatcher and, without this, the same continuing result
# is suppressed for the life of the process and the record never comes back.
_WRITTEN = {}


def _generation(path):
    """
    Enough of a file's identity to notice it was replaced or removed.

    None when it is not there, which is what makes absence a mismatch rather
    than an unknown.
    """
    try:
        st = path.stat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def note_delivery(status_path, kind, event_id, runtime, detail):
    """
    Record what the runtime said about one event, for a health check to render.

    Deliberately narrow. It holds an event id, a time, a runtime name and the
    adapter's own words: no sender, no subject, no payload, no credentials. A
    status file is read by whoever can read the state directory, and there is no
    reason for mail content to be in it.

    Written only when the answer changes. A runtime that is down produces one
    result per retry, and rewriting the same sentence every two seconds would
    turn a diagnostic into a disk load. What counts as "the same answer" is every
    field that gets persisted, at the path it gets persisted to: a key missing a
    field cannot see that field change, and the write it suppresses is the one
    that would have corrected the record.

    The key is set after the write, never before. Recording an intention as an
    accomplishment is how a failed write suppresses its own retry.
    """
    path = Path(status_path)
    resolved = str(path.expanduser())
    answer = (kind, event_id, runtime, detail or "")
    remembered = _WRITTEN.get(resolved)
    if remembered is not None and remembered == (answer, _generation(path)):
        return

    entry = {
        "event_id": event_id,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime": runtime,
        "detail": detail or "",
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            current = json.loads(path.read_text())
        except (OSError, ValueError):
            current = {}
        current[kind] = entry
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(current, indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        # Losing the status file loses a diagnostic, not an event. Delivery is
        # not held up for it, and the answer stays unrecorded so the next result
        # tries again.
        log(f"could not write the delivery status at {path}: {exc}")
        return

    _WRITTEN[resolved] = (answer, _generation(path))


def claim(lock_path):
    """
    Take exclusive ownership of delivery, or refuse to start.

    Two dispatchers on one journal read the same cursor and deliver the same
    record before either writes the new offset. The unit is meant to be the only
    one, but "meant to" is not a mechanism: a hand-run copy for debugging is
    enough, and the duplicate it causes looks like nothing at all from the
    outside.

    The handle is returned and deliberately not closed. It is held for the life
    of the process; the kernel drops it when this exits, however it exits.
    """
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(handle)
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise SystemExit(
                f"another dispatcher already holds {path}.\n"
                "Only one may deliver: two would hand the same event to the runtime "
                "twice and race on one cursor.\n"
                "Check `systemctl --user status paynani-dispatch.service`."
            )
        raise
    os.write(handle, str(os.getpid()).encode())
    return handle


def load_adapter(name):
    """
    Import one adapter by name, or explain why the name is not usable.

    A runtime this repository has never heard of is a stop, not a warning: acting
    on a guess here means delivering nowhere while reporting success.
    """
    if name not in KNOWN_RUNTIMES:
        known = ", ".join(KNOWN_RUNTIMES)
        raise SystemExit(f"unknown runtime {name!r}. Set PAYNANI_RUNTIME to one of: {known}")
    try:
        return importlib.import_module(f"adapters.{name}")
    except ImportError as exc:
        raise SystemExit(
            f"runtime {name!r} is not implemented in this version: {exc}\n"
            f"Installed version supports: {', '.join(available())}."
        )


def available():
    """Which adapters this checkout actually ships."""
    out = []
    for name in KNOWN_RUNTIMES:
        try:
            importlib.import_module(f"adapters.{name}")
            out.append(name)
        except ImportError:
            continue
    return out


def select_runtime(requested):
    """
    Which runtime to deliver to.

    `auto` picks only when the answer is not a guess. Two runtimes present and
    one chosen silently is how an install ends up delivering to the harness
    nobody is watching, so ambiguity is refused rather than resolved.
    """
    requested = (requested or "auto").strip().lower()
    if requested != "auto":
        return requested

    detected = []
    for name in available():
        module = importlib.import_module(f"adapters.{name}")
        if getattr(module, "detect", lambda: False)():
            detected.append(name)

    if len(detected) == 1:
        return detected[0]
    if not detected:
        raise SystemExit(
            "PAYNANI_RUNTIME=auto found no supported runtime on this host.\n"
            f"This version supports: {', '.join(available())}.\n"
            "Set PAYNANI_RUNTIME explicitly if it is installed somewhere unusual."
        )
    raise SystemExit(
        f"PAYNANI_RUNTIME=auto found more than one runtime ({', '.join(detected)}) "
        "and will not choose between them.\nSet PAYNANI_RUNTIME explicitly."
    )


def deliver_with_retries(adapter, record, stop, status_path=None):
    """
    Keep trying one record until it is accepted or we are asked to stop.

    Returns True when it was accepted. Never gives up on its own: giving up means
    either losing the record or stepping over it, and both are the failure this
    design refuses. A record that cannot be delivered holds the queue, loudly,
    which is the honest state to be in.
    """
    delay = RETRY_MIN
    complaining = False
    while not stop():
        result = adapter.deliver(record)

        if result.status == ACCEPTED:
            if complaining:
                note(f"delivery recovered: {record.get('event_id')} accepted by {adapter.NAME}")
            if status_path:
                note_delivery(status_path, "last_accepted", record.get("event_id"),
                              adapter.NAME, result.detail)
            return True

        if status_path:
            note_delivery(status_path, "last_error", record.get("event_id"),
                          adapter.NAME, f"{result.status}: {result.detail}")

        if result.status == CONFIG:
            # Said every time rather than once. A configuration fault does not
            # clear on its own, and an operator reading the tail of this file an
            # hour later should find it there, not scrolled away above an hour of
            # retry noise.
            log(f"{adapter.NAME} cannot deliver {record.get('event_id')}: {result.detail}")
            log("Mail is journalled and nothing is lost, but nothing is being delivered "
                "either. This needs a person; it will not clear by waiting.")
            _sleep(CONFIG_RETRY, stop)
            continue

        if not complaining:
            log(f"{adapter.NAME} refused {record.get('event_id')}: {result.detail}")
            log(f"Retrying; the cursor stays put, so nothing moves past it.")
            complaining = True
        _sleep(_jitter(delay, RETRY_MAX), stop)
        delay = min(delay * 2, RETRY_MAX)
    return False


def _jitter(seconds, maximum):
    fraction = min(1.0, max(0.0, RETRY_JITTER))
    low = max(0.0, seconds * (1.0 - fraction))
    high = max(low, seconds * (1.0 + fraction))
    return min(maximum, random.uniform(low, high))


def _sleep(seconds, stop):
    """Sleep in slices so a stop signal is noticed promptly."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and not stop():
        time.sleep(min(0.25, max(0.0, end - time.monotonic())))


def run_once(adapter, journal, cursor_path, stop=lambda: False, status_path=None):
    """
    Drain everything currently in the journal. Returns how many were accepted.

    Records are taken strictly in order. There is no dead-letter policy, so the
    first one that cannot be delivered stops the drain rather than being skipped;
    a hole in a byte-offset cursor cannot be represented, and a skipped record
    that nobody counted is exactly the silent loss this exists to prevent.
    """
    delivered = 0
    cursor = ev.read_cursor(cursor_path)
    for record, end in ev.read_from(journal, cursor):
        if stop():
            break

        if isinstance(record, ev.Corrupt):
            # Whole, and unparseable. Something wrote or damaged this file, and
            # nothing here can tell what the record said. Advancing past it would
            # be a dead-letter policy nobody chose; the queue stops instead.
            log(f"the event journal has a damaged record at byte {record.offset}: {record.raw!r}")
            log("Delivery has stopped here rather than stepping over it, so nothing behind "
                "it will be delivered either. This needs a person: inspect "
                f"{journal}, and if the record is genuinely unrecoverable, remove that "
                f"line and the dispatcher will carry on from it.")
            break

        if not deliver_with_retries(adapter, record, stop, status_path):
            break
        ev.write_cursor(cursor_path, end)
        delivered += 1
        if CATCHUP_PACE > 0:
            _sleep(
                _jitter(CATCHUP_PACE, CATCHUP_PACE * 2.0),
                stop,
            )
    return delivered


def maybe_compact(journal, cursor_path):
    """
    Empty a fully delivered journal, from the process that knows it is delivered.

    Compaction used to live in the log rotator, which is a different process on a
    timer with no idea what had been delivered and no lock: it could check the
    size, have the listener append, and then truncate away an event nobody had
    seen. Here it runs between drains, in the only process that owns the cursor,
    and `ev.compact` re-checks under the journal lock before touching anything.
    """
    freed = ev.compact(journal, cursor_path, min_size=JOURNAL_MAX)
    if freed:
        note(f"compacted the event journal ({freed} bytes, all delivered)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default=os.environ.get("PAYNANI_RUNTIME", "auto"))
    parser.add_argument("--journal", default=str(JOURNAL))
    parser.add_argument("--cursor", default=str(CURSOR))
    parser.add_argument("--status", default=str(STATUS),
                        help="where to record what the runtime last said")
    parser.add_argument("--once", action="store_true",
                        help="drain what is there and exit, rather than following")
    args = parser.parse_args(argv)

    runtime = select_runtime(args.runtime)
    adapter = load_adapter(runtime)
    claim(LOCK)

    ready = adapter.check()
    if ready.status != ACCEPTED:
        # Not fatal. The journal is still being written, so mail is not lost, and
        # saying this once at startup is more use than refusing to start and
        # leaving nothing to read.
        log(f"{runtime} is not ready: {ready.detail}")
        log("Starting anyway: events will queue in the journal until it is.")
    else:
        note(f"delivering to {runtime}" + (f" ({ready.detail})" if ready.detail else ""))

    stopped = {"now": False}

    def stop():
        return stopped["now"]

    import signal

    def handle(signum, frame):
        stopped["now"] = True

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    if args.once:
        run_once(adapter, args.journal, args.cursor, stop, args.status)
        return 0

    while not stop():
        run_once(adapter, args.journal, args.cursor, stop, args.status)
        maybe_compact(args.journal, args.cursor)
        _sleep(POLL, stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
