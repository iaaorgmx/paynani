#!/usr/bin/env python3
"""
The envelope, the journal, and the rule the whole design rests on: the cursor
moves past a record only when a runtime has accepted it.

Every silent-loss defect this project has had was a version of moving it when
the runtime had not. Those live in the dispatcher now rather than in a shell
loop, so they are tested here.

    python3 scripts/test_dispatch.py
"""

import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import event as ev
import dispatch
from adapters import accepted, config, retry

passed = failed = 0


def check(desc, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}\n       expected: {expected!r}\n       actual:   {actual!r}")
        failed += 1


class Fake:
    """An adapter that answers however a test needs it to, and keeps the receipts."""

    NAME = "fake"

    def __init__(self, script=None, default=None):
        self.script = list(script or [])
        self.default = default or accepted()
        self.seen = []

    def check(self):
        return accepted()

    def deliver(self, envelope):
        self.seen.append(envelope["event_id"])
        return self.script.pop(0) if self.script else self.default


def journal_with(*subjects, roster=True):
    d = pathlib.Path(tempfile.mkdtemp())
    j, c = d / "events.jsonl", d / "dispatch.offset"
    for i, subject in enumerate(subjects, start=1):
        ev.append(j, ev.mail_event(
            account="agent@example.com", mailbox="INBOX", uidvalidity=42, uid=i,
            sender_name="Dulce Mercado", sender_address="dmercado@example.com",
            subject=subject, sent_at="2026-08-18T12:00:00Z", roster_match=roster,
            notification_text=f"[mail 12:00:00] Dulce Mercado — {subject}"))
    return j, c


# --- the envelope -----------------------------------------------------------

e = ev.mail_event(account="Agent@Example.COM", mailbox="INBOX", uidvalidity=42, uid=7,
                  sender_name="Dulce", sender_address="Dulce@Example.COM", subject="hola",
                  sent_at="", roster_match=True, notification_text="[mail] x")

check("event_id is stable and carries uidvalidity", "imap:INBOX:42:7", e["event_id"])
check("account is normalised", "agent@example.com", e["account"])
check("sender address is normalised", "dulce@example.com", e["sender"]["address"])
check("roster_match is recorded", True, e["roster_match"])
check("a roster match is never authenticated identity", False, e["authenticated_sender"])
check("no message body is carried", [], [k for k in e if k in ("body", "content", "text")])
check("no credential is carried", [], [k for k in e if "password" in k.lower()])

same = ev.mail_event(account="agent@example.com", mailbox="INBOX", uidvalidity=42, uid=7,
                     sender_name="Dulce", sender_address="dulce@example.com", subject="hola",
                     sent_at="", roster_match=True, notification_text="[mail] x")
check("the same message gets the same id across restarts", e["event_id"], same["event_id"])

rebuilt = ev.mail_event(account="agent@example.com", mailbox="INBOX", uidvalidity=43, uid=7,
                        sender_name="D", sender_address="d@example.com", subject="other",
                        sent_at="", roster_match=False, notification_text="[mail] y")
check("a UIDVALIDITY reset produces a new id rather than colliding",
      True, rebuilt["event_id"] != e["event_id"])

# --- the journal ------------------------------------------------------------

j, c = journal_with("uno", "dos", "tres")
records = [r for r, _ in ev.read_from(j, 0)]
check("every record reads back", 3, len(records))
check("records keep their order", ["uno", "dos", "tres"], [r["subject"] for r in records])

with j.open("ab") as fh:
    fh.write(b'{"event_id":"imap:INBOX:42:4","subject":"part')
check("a half-written record is not read", 3, len([r for r, _ in ev.read_from(j, 0)]))

j2, _ = journal_with("solo")
end = [off for _, off in ev.read_from(j2, 0)][0]
check("the offset returned is the end of that record", j2.stat().st_size, end)

j3, _ = journal_with("ascii")
ev.append(j3, ev.mail_event(
    account="a@b.c", mailbox="INBOX", uidvalidity=1, uid=99,
    sender_name="Ximena Salazar", sender_address="x@example.com",
    subject="cotización — presupuesto ✓", sent_at="", roster_match=True,
    notification_text="[mail] cotización"))
check("a non-ASCII subject survives the round trip", "cotización — presupuesto ✓",
      [r for r, _ in ev.read_from(j3, 0)][-1]["subject"])

# --- the cursor -------------------------------------------------------------

j, c = journal_with("uno", "dos")
fake = Fake()
dispatch.run_once(fake, j, c)
check("everything accepted: cursor reaches the end", j.stat().st_size, ev.read_cursor(c))
check("everything accepted: each record delivered once", 2, len(fake.seen))

j, c = journal_with("uno", "dos", "tres")
first_end = [off for _, off in ev.read_from(j, 0)][0]
fake = Fake(script=[accepted(), config("no runtime")], default=config("no runtime"))
dispatch.CONFIG_RETRY = 0.05
dispatch.run_once(fake, j, c, stop=lambda: len(fake.seen) >= 4)
check("a configuration fault does not advance the cursor", first_end, ev.read_cursor(c))
check("a configuration fault does not skip to the next record", "imap:INBOX:42:2", fake.seen[-1])

j, c = journal_with("uno", "dos")
fake = Fake(script=[retry("runtime restarting"), retry("still down"), accepted(), accepted()])
dispatch.RETRY_MIN = dispatch.RETRY_MAX = 0.01
dispatch.run_once(fake, j, c)
check("a transient failure is retried in place until it lands",
      j.stat().st_size, ev.read_cursor(c))
check("retrying does not reorder or skip",
      ["imap:INBOX:42:1", "imap:INBOX:42:1", "imap:INBOX:42:1", "imap:INBOX:42:2"], fake.seen)

j, c = journal_with("uno", "dos", "tres")
fake = Fake(script=[accepted(), retry("down")], default=retry("down"))
dispatch.run_once(fake, j, c, stop=lambda: len(fake.seen) >= 3)
check("a stuck record holds the queue rather than being stepped over",
      first_end, ev.read_cursor(c))
check("nothing behind a stuck record is delivered early",
      [], [s for s in fake.seen if s == "imap:INBOX:42:3"])

# The recovery #37 needed a process exit for: here the dispatcher simply keeps
# trying, because reading a journal by offset consumes nothing.
j, c = journal_with("uno")
fake = Fake(script=[retry("down"), retry("down"), retry("down"), accepted()])
dispatch.run_once(fake, j, c)
check("recovery needs no restart and no exit", j.stat().st_size, ev.read_cursor(c))

j, c = journal_with("uno", "dos")
fake = Fake()
dispatch.run_once(fake, j, c)
before = ev.read_cursor(c)
dispatch.run_once(fake, j, c)
check("a second pass redelivers nothing", 2, len(fake.seen))
check("a second pass leaves the cursor alone", before, ev.read_cursor(c))

j, c = journal_with("uno", "dos")
fake = Fake()
dispatch.run_once(fake, j, c)
seen_first = list(fake.seen)
again = Fake()
dispatch.run_once(again, j, c)
check("a restart resumes from the cursor rather than the start", [], again.seen)

# --- runtime selection ------------------------------------------------------

try:
    dispatch.load_adapter("nonesuch")
    check("an unknown runtime is refused", "SystemExit", "no error")
except SystemExit as exc:
    check("an unknown runtime is refused by name", True, "nonesuch" in str(exc))
    check("an unknown runtime lists OpenClaw", True, "openclaw" in str(exc))
    check("an unknown runtime lists Hermes", True, "hermes" in str(exc))

check("openclaw is available in this checkout", True, "openclaw" in dispatch.available())
check("hermes is available in this checkout", True, "hermes" in dispatch.available())
check("an explicit runtime is taken as given", "openclaw", dispatch.select_runtime("openclaw"))

original_uniform = dispatch.random.uniform
original_jitter = dispatch.RETRY_JITTER
dispatch.random.uniform = lambda _low, high: high
dispatch.RETRY_JITTER = 0.2
check("retry jitter is capped at the configured maximum", 10, dispatch._jitter(10, 10))
check("retry jitter varies an uncapped delay", 6, dispatch._jitter(5, 10))
dispatch.random.uniform = original_uniform
dispatch.RETRY_JITTER = original_jitter

original_sleep = dispatch._sleep
original_pace = dispatch.CATCHUP_PACE
paced_sleeps = []
dispatch._sleep = lambda seconds, _stop: paced_sleeps.append(seconds)
dispatch.CATCHUP_PACE = 0.05
dispatch.RETRY_JITTER = 0
paced_journal, paced_cursor = journal_with("one", "two")
dispatch.run_once(Fake(default=accepted()), paced_journal, paced_cursor)
check("catch-up delivery is paced after each accepted record", [0.05, 0.05], paced_sleeps)
dispatch._sleep = original_sleep
dispatch.CATCHUP_PACE = original_pace
dispatch.RETRY_JITTER = original_jitter

# --- durability, locking, corruption, compaction -----------------------------
#
# Every case below was a way of losing or duplicating an event that the first
# version of this code allowed. They are the reason the journal is not simply a
# file that gets appended to and read.

import subprocess
import threading

# A short write leaves a truncated line in the queue, and one os.write is not
# obliged to take everything it is given.
big = "x" * 200000
j, c = journal_with("small")
before = j.stat().st_size
ev.append(j, ev.mail_event(
    account="a@b.c", mailbox="INBOX", uidvalidity=1, uid=500,
    sender_name="Long", sender_address="l@x.com", subject=big, sent_at="",
    roster_match=False, notification_text="[mail] long"))
records = [r for r, _ in ev.read_from(j, 0)]
check("a large record is written whole", 2, len(records))
check("a large record reads back intact", len(big), len(records[-1]["subject"]))

# The listener persists its UID after this returns. If append reports success
# without the bytes being on disk, a crash in between loses the message.
j2, _ = journal_with("durable")
check("append reports the true end of file", j2.stat().st_size,
      [off for _, off in ev.read_from(j2, 0)][-1])

# A journal that cannot be written must raise, not return quietly. The listener
# relies on that to refuse to acknowledge a message it did not queue.
unwritable = pathlib.Path(tempfile.mkdtemp()) / "nodir"
unwritable.write_text("i am a file, not a directory")
try:
    ev.append(unwritable / "events.jsonl", {"event_id": "x"})
    check("an unwritable journal raises", "raised", "returned quietly")
except (OSError, ValueError):
    check("an unwritable journal raises rather than returning quietly", True, True)

# A complete record that will not parse stops the queue. Skipping it advanced
# the cursor past it as soon as anything behind it was accepted, which is a
# dead-letter policy nobody chose.
j, c = journal_with("uno", "dos")
first_end = [off for _, off in ev.read_from(j, 0)][0]
with j.open("ab") as fh:
    fh.write(b"{ this is not json }\n")
ev.append(j, ev.mail_event(
    account="a@b.c", mailbox="INBOX", uidvalidity=42, uid=9, sender_name="After",
    sender_address="a@x.com", subject="behind the damage", sent_at="",
    roster_match=False, notification_text="[mail] after"))
seen_kinds = [type(r).__name__ for r, _ in ev.read_from(j, 0)]
check("a damaged record is surfaced, not skipped", True, "Corrupt" in seen_kinds)

fake = Fake()
dispatch.run_once(fake, j, c)
check("the cursor stops at the damaged record", first_end * 2, ev.read_cursor(c))
check("nothing behind a damaged record is delivered", 2, len(fake.seen))
check("the record behind the damage is not delivered",
      [], [x for x in fake.seen if x == "imap:INBOX:42:9"])

# Two dispatchers on one journal deliver the same record twice.
lock = pathlib.Path(tempfile.mkdtemp()) / "dispatch.lock"
held = dispatch.claim(lock)
try:
    dispatch.claim(lock)
    check("a second dispatcher is refused", "SystemExit", "it started")
except SystemExit as exc:
    check("a second dispatcher is refused", True, "another dispatcher" in str(exc))
os.close(held)
second = dispatch.claim(lock)
check("the lock is released when the holder exits", True, second > 0)
os.close(second)

# Compaction used to read the size, then truncate, with an append able to land
# in between and be destroyed.
j, c = journal_with("uno", "dos")
ev.write_cursor(c, j.stat().st_size)
freed = ev.compact(j, c, min_size=1)
check("a fully delivered journal compacts", True, freed > 0)
check("compaction empties the file", 0, j.stat().st_size)
check("compaction resets the cursor", 0, ev.read_cursor(c))

j, c = journal_with("uno", "dos")
ev.write_cursor(c, 0)
check("an undelivered journal is never compacted", 0, ev.compact(j, c, min_size=1))
check("an undelivered journal keeps its records", 2, len([r for r, _ in ev.read_from(j, 0)]))

j, c = journal_with("uno")
ev.write_cursor(c, j.stat().st_size)
appended = []

def appender():
    for i in range(60):
        appended.append(ev.append(j, ev.mail_event(
            account="a@b.c", mailbox="INBOX", uidvalidity=42, uid=1000 + i,
            sender_name="Racer", sender_address="r@x.com", subject=f"concurrent {i}",
            sent_at="", roster_match=False, notification_text=f"[mail] concurrent {i}")))

t = threading.Thread(target=appender)
t.start()
for _ in range(60):
    ev.compact(j, c, min_size=1)
t.join()

# Nothing in this test is ever delivered, so every one of the 60 appended events
# must still be readable from wherever the cursor ended up. Compaction may only
# fire while the cursor covers the whole file, which is true here exactly once,
# before the first append lands; after that it must decline every time.
undelivered = [r for r, _ in ev.read_from(j, ev.read_cursor(c))]
check("compaction never destroys an event that was not delivered",
      60, len([r for r in undelivered if isinstance(r, dict)
               and r.get("subject", "").startswith("concurrent")]))
check("no record is left damaged by a concurrent compaction",
      [], [r for r in undelivered if isinstance(r, ev.Corrupt)])

# --- listener faults --------------------------------------------------------

fault = ev.listener_error(account="a@b.c", message="connection lost (TimeoutError)")
check("a listener fault is an event like any other", "listener.error", fault["event_type"])
check("a listener fault renders for a runtime that takes one string",
      True, fault["notification_text"].startswith("[listener]"))
same_fault = ev.listener_error(account="a@b.c", message="connection lost (TimeoutError)",
                               observed_at=fault["observed_at"])
check("the same fault gets the same id in another process",
      fault["event_id"], same_fault["event_id"])

stable = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, 'harness'); import event;"
     "print(event.listener_error(account='a@b.c', message='m', observed_at='t')['event_id'])"],
    capture_output=True, text=True, cwd=str(ROOT))
check("fault ids do not change with the process hash seed",
      ev.listener_error(account="a@b.c", message="m", observed_at="t")["event_id"],
      stable.stdout.strip())

# --- what the runtime last said ---------------------------------------------
#
# A health check cannot ask an adapter what happened an hour ago, and must never
# reconstruct it from a reachability check: a gateway answering now says nothing
# about whether something accepted earlier was ever acted on. So the dispatcher
# records it, because it is the thing that decided the cursor could move.

j, c = journal_with("uno", "dos")
status = j.parent / "delivery.json"
fake = Fake(default=accepted("HTTP 202 status=accepted; agent completion externally unconfirmed"))
dispatch.run_once(fake, j, c, status_path=status)
recorded = json.loads(status.read_text())
check("an accepted delivery is recorded", "imap:INBOX:42:2",
      recorded["last_accepted"]["event_id"])
check("the adapter's own words are kept verbatim",
      "HTTP 202 status=accepted; agent completion externally unconfirmed",
      recorded["last_accepted"]["detail"])
check("the runtime that took it is named", "fake", recorded["last_accepted"]["runtime"])
check("nothing was refused", None, recorded.get("last_error"))

# The status file is readable by anyone who can read the state directory, so it
# holds an identifier and a sentence, never the mail.
raw = status.read_text()
for leak in ("Dulce", "dmercado@example.com", "uno", "dos", "notification_text"):
    check(f"the status file does not carry {leak!r}", False, leak in raw)
check("the status file is not world readable", "0o600",
      oct(status.stat().st_mode & 0o777))

j, c = journal_with("uno")
status = j.parent / "delivery.json"
fake = Fake(script=[retry("gateway timed out"), accepted("HTTP 200 status=delivered")])
dispatch.RETRY_MIN = dispatch.RETRY_MAX = 0.01
dispatch._WRITTEN.clear()
dispatch.run_once(fake, j, c, status_path=status)
recorded = json.loads(status.read_text())
check("a refusal is recorded as well", True, "gateway timed out" in recorded["last_error"]["detail"])
check("and the eventual acceptance replaces nothing but itself",
      "HTTP 200 status=delivered", recorded["last_accepted"]["detail"])
check("a refusal records which status it was", True,
      recorded["last_error"]["detail"].startswith("retry:"))

# A runtime that is down answers once per retry; the file must not be rewritten
# every two seconds for the same sentence.
j, c = journal_with("uno")
status = j.parent / "delivery.json"
dispatch._WRITTEN.clear()
fake = Fake(default=retry("still down"))
dispatch.run_once(fake, j, c, stop=lambda: len(fake.seen) >= 5, status_path=status)
first = status.stat().st_mtime_ns
dispatch.run_once(fake, j, c, stop=lambda: len(fake.seen) >= 10, status_path=status)
check("an unchanged answer is not rewritten", first, status.stat().st_mtime_ns)

# Suppression must not blind the record to a change. Anything left out of the
# key is a change it cannot see, and the write it skips is the one that would
# have corrected the file.
j, c = journal_with("uno")
one = j.parent / "one.json"
two = j.parent / "two.json"
dispatch._WRITTEN.clear()
same = ("last_accepted", "imap:INBOX:42:1", "runtime-a", "HTTP 200 status=delivered")
dispatch.note_delivery(one, *same)
dispatch.note_delivery(two, *same)
check("the same answer at a different path is still written", True, two.is_file())
check("and both files carry it", "runtime-a",
      json.loads(two.read_text())["last_accepted"]["runtime"])

dispatch.note_delivery(one, "last_accepted", "imap:INBOX:42:1", "runtime-b",
                       "HTTP 200 status=delivered")
check("a changed runtime with otherwise identical values is written",
      "runtime-b", json.loads(one.read_text())["last_accepted"]["runtime"])

dispatch.note_delivery(one, "last_error", "imap:INBOX:42:1", "runtime-b",
                       "HTTP 200 status=delivered")
check("the same detail under a different kind is written", True,
      "last_error" in json.loads(one.read_text()))

# A remembered answer says what was written, never that it is still there.
dispatch._WRITTEN.clear()
gone = j.parent / "gone.json"
dispatch.note_delivery(gone, *same)
gone.unlink()
dispatch.note_delivery(gone, *same)
check("a deleted status file is recreated by the next identical result", True, gone.is_file())
check("and carries the same answer", "runtime-a",
      json.loads(gone.read_text())["last_accepted"]["runtime"])

# Replaced rather than removed: a different file at the same path is not the
# record this process wrote.
replaced = j.parent / "replaced.json"
dispatch._WRITTEN.clear()
dispatch.note_delivery(replaced, *same)
replaced.write_text("{}")
dispatch.note_delivery(replaced, *same)
check("a status file replaced underneath is rewritten", "runtime-a",
      json.loads(replaced.read_text())["last_accepted"]["runtime"])

# An untouched file is still not rewritten, which is the point of the cache.
steady = j.parent / "steady.json"
dispatch._WRITTEN.clear()
dispatch.note_delivery(steady, *same)
first_write = steady.stat().st_mtime_ns
dispatch.note_delivery(steady, *same)
check("an untouched file with an unchanged answer is left alone",
      first_write, steady.stat().st_mtime_ns)

# A write that failed has not happened, and must not suppress the next attempt.
wall = j.parent / "wall"
wall.write_text("a file where a directory would need to be")
blocked = wall / "delivery.json"
dispatch._WRITTEN.clear()
dispatch.note_delivery(blocked, *same)
check("a failed write is not remembered as done", None,
      dispatch._WRITTEN.get(str(blocked)))

# --- the fault transition state ---------------------------------------------
#
# The sequence that matters is the one run() actually performs: a fault fails to
# journal, and the very next pass succeeds. Nothing asks about the fault again on
# that pass, so unless what is owed is carried, the outage and its recovery both
# vanish and the episode reads as though nothing happened.

sys.path.insert(0, str(ROOT / "scripts"))
import idle_listener as listener


def fault_log():
    d = pathlib.Path(tempfile.mkdtemp())
    wall = d / "wall"
    wall.write_text("a file where a directory would need to be")
    fl = listener.FaultLog(wall / "events.jsonl", "a@b.c")
    return fl, d / "events.jsonl"


def faults_in(journal):
    return [r["message"] for r, _ in ev.read_from(journal, 0)
            if isinstance(r, dict) and r.get("event_type") == "listener.error"]


# The exact production sequence: one failed append, then recovery.
fl, good = fault_log()
fl.fault("connection lost (TimeoutError)")
check("a fault that could not be journalled is not marked as recorded", None, fl.recorded)
check("but it is remembered as owed", "connection lost (TimeoutError)", fl.pending)

fl.journal = good          # writability returns
fl.recovered()             # the next pass succeeds, exactly as run() does
check("the outage is journalled on the recovering pass, without a second failure",
      ["connection lost (TimeoutError)", listener.RECOVERED], faults_in(good))
check("and nothing is left owed", (None, None), (fl.recorded, fl.pending))

# A sustained outage writes one record, not one per retry.
fl, good = fault_log()
fl.journal = good
for _ in range(5):
    fl.fault("connection lost (TimeoutError)")
check("a sustained outage is recorded once", 1, len(faults_in(good)))
fl.recovered()
check("and reads as one fault then one recovery",
      ["connection lost (TimeoutError)", listener.RECOVERED], faults_in(good))

# A different fault is a new transition.
fl, good = fault_log()
fl.journal = good
fl.fault("connection lost (TimeoutError)")
fl.fault("journal unwritable: no space left on device")
check("a different fault is recorded as its own transition", 2, len(faults_in(good)))

# Nothing went wrong, so nothing is said.
fl, good = fault_log()
fl.journal = good
fl.recovered()
check("recovery writes nothing when nothing went wrong", [], faults_in(good))

# A recovery that cannot be written leaves the outage open rather than ending it.
fl, good = fault_log()
fl.journal = good
fl.fault("connection lost (TimeoutError)")
broken = fl.journal
fl.journal = pathlib.Path(str(good.parent / "wall")) / "events.jsonl"
fl.recovered()
check("a recovery that cannot be journalled keeps the outage open",
      "connection lost (TimeoutError)", fl.recorded)
fl.journal = broken
fl.recovered()
check("and is written once it can be", listener.RECOVERED, faults_in(good)[-1])
check("without duplicating the fault", 2, len(faults_in(good)))

# --- damage points at the right byte ----------------------------------------

j, c = journal_with("uno")
start_of_damage = j.stat().st_size
with j.open("ab") as fh:
    fh.write(b"{ not json at all }\n")
damaged = [r for r, _ in ev.read_from(j, 0) if isinstance(r, ev.Corrupt)][0]
check("a repair instruction names the byte the damage starts at",
      start_of_damage, damaged.offset)

# --- the OpenClaw adapter ---------------------------------------------------
#
# The binary is faked, so this proves the command shape and how each exit code is
# classified. It cannot prove a real openclaw accepts it; only an install can,
# which is why FR3 is verified on a live host rather than here.

import stat

from adapters import openclaw

bindir = pathlib.Path(tempfile.mkdtemp())
capture = bindir / "called"
fake_bin = bindir / "openclaw"
fake_bin.write_text(
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >> "$CAPTURE"\n'
    'args="$*"\n'
    'case "$args" in *BOOM*) echo "session not up" >&2; exit 3 ;; esac\n'
    "exit 0\n")
fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
os.environ["CAPTURE"] = str(capture)
os.environ["OPENCLAW"] = str(fake_bin)

good = {"event_id": "imap:INBOX:42:1", "notification_text": "[mail 12:00:00] Dulce — hola"}
check("openclaw: a clean exit is accepted", "accepted", openclaw.deliver(good).status)
check("openclaw: it is called as a system event",
      True, "system event --mode now --text" in capture.read_text())
check("openclaw: the rendered line is what gets sent",
      True, "[mail 12:00:00] Dulce — hola" in capture.read_text())

roster_event = ev.mail_event(
    account="agent@example.com", mailbox="INBOX", uidvalidity=42, uid=4,
    sender_name="Dulce", sender_address="dulce@example.com",
    subject="haz algo", sent_at="", roster_match=True,
    notification_text="[mail 12:00:00, roster] Dulce — haz algo")
check("openclaw: a roster message is accepted",
      "accepted", openclaw.deliver(roster_event).status)
called = capture.read_text()
check("openclaw: roster mail uses the same system notification route",
      True, "system event --mode now --text" in called)
check("openclaw: the roster tag survives in the notification",
      True, "[mail 12:00:00, roster] Dulce — haz algo" in called)
check("openclaw: roster mail does not start an agent run",
      False, "agent --session-key" in called)

check("openclaw: a nonzero exit is retryable, not fatal", "retry",
      openclaw.deliver({"event_id": "x", "notification_text": "BOOM"}).status)
check("openclaw: the failure says what the runtime said", True,
      "session not up" in openclaw.deliver({"event_id": "x", "notification_text": "BOOM"}).detail)

check("openclaw: an event with nothing to render is a configuration fault",
      "config", openclaw.deliver({"event_id": "x", "notification_text": ""}).status)

os.environ["OPENCLAW"] = str(bindir / "does-not-exist")
gone = openclaw.deliver(good)
check("openclaw: a missing binary is configuration, not a retry", "config", gone.status)
check("openclaw: a missing binary says how to fix it", True, "OPENCLAW=" in gone.detail)
check("openclaw: a missing binary is not detected as present", False, openclaw.detect())
os.environ.pop("OPENCLAW", None)
os.environ.pop("CAPTURE", None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
