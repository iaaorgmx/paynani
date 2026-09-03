#!/usr/bin/env python3
"""
What the health command refuses to call healthy.

The point of this check is the failure where nothing looks wrong: a listener
that died, a runtime nobody can reach, a queue nothing is draining. Each of
those leaves an empty inbox and a calm log, so every assertion below is about
whether the command says something is wrong when nothing is obviously wrong.

    python3 scripts/test_healthcheck.py
"""

import io
import json
import os
import pathlib
import sys
import tempfile
import time
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "scripts"))

import event as ev
import healthcheck as hc

# Fixture replaces hc.runtime_facts wholesale, so the real one is kept here
# while it still exists — one test below is about what it actually does.
REAL_RUNTIME_FACTS = hc.runtime_facts

passed = failed = 0


def check(desc, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}\n       expected: {expected!r}\n       actual:   {actual!r}")
        failed += 1


class Fixture:
    """An install on disk, healthy unless a test breaks something specific."""

    def __init__(self, units=None, reachable=True, runtime="openclaw"):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.units = units or {hc.LISTENER_UNIT: "active", hc.DISPATCH_UNIT: "active"}
        self.reachable = reachable
        self.runtime = runtime
        self.spool_facts = None

        hc.STATE_DIR = self.dir
        hc.LISTENER_STATE = self.dir / "idle.json"
        hc.JOURNAL = self.dir / "events.jsonl"
        hc.CURSOR = self.dir / "dispatch.offset"
        hc.DISPATCH_ERR = self.dir / "dispatch.err.log"
        hc.IDLE_ERR = self.dir / "idle.err.log"
        hc.DELIVERY = self.dir / "delivery.json"
        hc.SENT_LOG = self.dir / "sent.log"

        hc.LISTENER_STATE.write_text(json.dumps(
            {"mailbox": "INBOX", "uidvalidity": "42", "last_uid": 117}))

        env = self.dir / "env"
        env.write_text("PAYNANI_EMAIL=agent@example.com\n"
                       "PAYNANI_PASSWORD=hunter2-do-not-print\n")
        env.chmod(0o600)
        self.env = env

        # An install that can be written to and can write. Both are required for
        # "healthy" and neither was checked before #6, so the healthy fixture
        # has to provide them or every test below would be measuring the wrong
        # failure.
        hc.ROSTER = self.dir / "roster.md"
        hc.ROSTER.write_text("| Name | Email | Type |\n"
                             "|---|---|---|\n"
                             "| Dulce | d@x.com | Human |\n", encoding="utf-8")
        hc.HIMALAYA_CONFIG = self.dir / "himalaya.toml"
        hc.HIMALAYA_CONFIG.write_text(
            "[accounts.paynani]\nemail = \"agent@example.com\"\n", encoding="utf-8")

        hc.unit_state = lambda unit: self.units.get(unit, "unknown")
        hc.env_file = lambda: self.env
        hc.runtime_facts = self._runtime_facts

        # A clean checkout of a published commit, unless a test says otherwise.
        # Stubbed rather than read: the real answer depends on whoever is running
        # the suite, and a test whose result changes with the tester's working
        # tree is not a test.
        self.git = {"is_repo": True, "commit": "abc1234", "branch": "main",
                    "in_origin": True, "dirty_tracked": 0, "ahead": 0, "behind": 0}
        hc.git_facts = lambda: self.git

    def _runtime_facts(self):
        return {"selected": self.runtime, "available": ["openclaw"],
                "reachable": self.reachable,
                "detail": None if self.reachable else "no openclaw binary found",
                "proves_route_readiness": False,
                "runtime_env": None}

    def queue(self, count, age_seconds=0):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                              time.gmtime(time.time() - age_seconds))
        for i in range(count):
            ev.append(hc.JOURNAL, ev.mail_event(
                account="agent@example.com", mailbox="INBOX", uidvalidity=42,
                uid=100 + i, sender_name="Dulce", sender_address="d@x.com",
                subject=f"waiting {i}", sent_at=stamp, roster_match=True,
                notification_text=f"[mail] waiting {i}", observed_at=stamp))
        return self

    def damage(self):
        with hc.JOURNAL.open("ab") as fh:
            fh.write(b"{ not json }\n")
        return self

    def drain(self):
        ev.write_cursor(hc.CURSOR, hc.JOURNAL.stat().st_size)
        return self

    def spool(self, bytes_unread, bytes_total=None):
        """Stand in for spool_facts(), which reads the real Claude Code spool."""
        self.spool_facts = {"spool": str(self.dir / "session.spool"),
                            "bytes_total": bytes_total if bytes_total is not None
                            else bytes_unread,
                            "bytes_unread": bytes_unread,
                            "session_arming": "unobservable"}
        return self

    def sent(self, count=1, age_seconds=0, rotated=False):
        """Write send records in scripts/send.sh's format, live or rotated away."""
        path = hc.SENT_LOG.with_name("sent.log.1") if rotated else hc.SENT_LOG
        lines = []
        for i in range(count):
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                  time.gmtime(time.time() - age_seconds))
            lines.append(f"{stamp}\tto=d@x.com\tcc=\tsubject=Re: waiting {i}"
                         f"\tmessage-id=<{i}@example.com>")
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        if rotated:
            # copytruncate leaves the live file present and empty.
            hc.SENT_LOG.write_text("", encoding="utf-8")
        return self

    def run(self):
        facts = {
            "listener": hc.listener_facts(),
            "dispatcher_unit": hc.unit_state(hc.DISPATCH_UNIT),
            "queue": hc.queue_facts(),
            "runtime": hc.runtime_facts(),
            "delivery": hc.delivery_facts(),
            "config": hc.config_facts(),
            "roster": hc.roster_facts(),
            "himalaya": hc.himalaya_facts(),
            "git": hc.git_facts(),
        }
        facts["spool"] = self.spool_facts
        facts["reply"] = hc.reply_facts(facts["queue"]["cursor"])
        problems, warnings = hc.assess(facts)
        return facts, problems, warnings

    def exit_code(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = hc.main([])
        return code, buf.getvalue()


# --- an install with nothing wrong ------------------------------------------

f = Fixture()
code, text = f.exit_code()
check("a working install exits 0", 0, code)
check("and does not claim a quiet mailbox proves anything", True,
      "not that the mailbox is quiet" in text)

# --- the failures that look like nothing -------------------------------------

f = Fixture(units={hc.LISTENER_UNIT: "inactive", hc.DISPATCH_UNIT: "active"})
code, text = f.exit_code()
check("a dead listener is a failure, not a quiet mailbox", 1, code)
check("and says no mail is being detected at all", True, "detected at all" in text)

f = Fixture(units={hc.LISTENER_UNIT: "active", hc.DISPATCH_UNIT: "failed"})
code, _ = f.exit_code()
check("a failed dispatcher is a failure", 1, code)

f = Fixture(reachable=False)
code, text = f.exit_code()
check("an unreachable runtime is a failure", 1, code)
check("and names the runtime that cannot be reached", True, "openclaw" in text)

f = Fixture(runtime=None)
_, problems, _ = f.run()
check("no runtime selected is a failure", True,
      any("no runtime is selected" in p for p in problems))

# --- the queue ---------------------------------------------------------------

f = Fixture().queue(3, age_seconds=5)
code, _ = f.exit_code()
check("a queue that is moving is not a failure", 0, code)

f = Fixture().queue(3, age_seconds=60 * 60)
code, text = f.exit_code()
check("a queue that has not moved for an hour is a failure", 1, code)
check("and says how long it has been waiting", True, "not moving" in text)

f = Fixture().queue(2).drain()
_, problems, _ = f.run()
check("a drained queue is not a failure", [], problems)

f = Fixture().queue(1).damage().queue(1)
facts, problems, _ = f.run()
check("a damaged record is found", True, facts["queue"]["damaged_at"] is not None)
check("a damaged record is a failure", True,
      any("damaged record" in p for p in problems))
check("nothing behind the damage is counted as merely pending", 1, facts["queue"]["pending"])

# --- what it must never print ------------------------------------------------

f = Fixture()
_, text = f.exit_code()
check("the password is never printed", False, "hunter2-do-not-print" in text)
_, json_text = (lambda: (None, io.StringIO()))()
buf = io.StringIO()
with redirect_stdout(buf):
    hc.main(["--json"])
check("the password is never printed in json either", False,
      "hunter2-do-not-print" in buf.getvalue())
check("the json form is parseable", True, isinstance(json.loads(buf.getvalue()), dict))

# --- permissions -------------------------------------------------------------

f = Fixture()
f.env.chmod(0o644)
_, problems, warnings = f.run()
check("world-readable credentials are worth saying", True,
      any("more readable" in w for w in warnings))
check("but are not a reason to call delivery broken", [], problems)

f = Fixture()
f.env.unlink()
_, problems, _ = f.run()
check("missing credentials are a failure", True,
      any("no credentials" in p for p in problems))

# --- an install that runs perfectly and still cannot do anything (#6) ---------
#
# Both of these leave every unit active, every queue empty and every log calm.
# They are the failure this whole command exists for, and it called them healthy
# until two people found them the same day by different routes.

f = Fixture()
f.dir.joinpath("roster.md").unlink()
_, problems, _ = f.run()
check("a missing roster is a failure", True,
      any("no roster at" in p for p in problems))
check("and names the file it looked for", True,
      any(str(f.dir / "roster.md") in p for p in problems))

f = Fixture()
hc.ROSTER.write_text("| Name | Email | Type |\n|---|---|---|\n", encoding="utf-8")
_, problems, _ = f.run()
check("a roster with a header and no rows is a failure", True,
      any("lists no address" in p for p in problems))
check("and says the silence is what makes it dangerous", True,
      any("nobody having written" in p for p in problems))

f = Fixture()
hc.ROSTER.write_text("# only a comment\n\n", encoding="utf-8")
_, problems, _ = f.run()
check("a roster holding no address at all is a failure", True,
      any("lists no address" in p for p in problems))

f = Fixture()
hc.HIMALAYA_CONFIG.unlink()
_, problems, _ = f.run()
check("no himalaya configuration is a failure", True,
      any("no himalaya configuration" in p for p in problems))

f = Fixture()
hc.HIMALAYA_CONFIG.write_text(
    '[accounts.something-else]\nemail = "other@example.com"\n', encoding="utf-8")
_, problems, _ = f.run()
check("a himalaya config without the send account is a failure", True,
      any("[accounts.paynani]" in p for p in problems))
check("and says sending is impossible, not merely unconfigured", True,
      any("sending is impossible" in p for p in problems))

# The exact case from #1: every other check green while sending was impossible.
f = Fixture()
hc.HIMALAYA_CONFIG.write_text(
    '[accounts.other]\nemail = "other@example.com"\n', encoding="utf-8")
code, _ = f.exit_code()
check("an install that cannot send does not exit 0", 1, code)

# Quoted account names are TOML too, and himalaya accepts them.
f = Fixture()
hc.HIMALAYA_CONFIG.write_text(
    '[accounts."paynani"]\nemail = "agent@example.com"\n', encoding="utf-8")
_, problems, _ = f.run()
check("a quoted account name counts as present", [], problems)

# The listener and this command must read the roster the same way, or one will
# call an install healthy that the other treats as empty.
f = Fixture()
hc.ROSTER.write_text("| AI Agent | Reordered | reordered@example.net |\n", encoding="utf-8")
facts, problems, _ = f.run()
check("the roster is parsed the way the listener parses it", 1,
      facts["roster"]["addresses"])
check("so a reordered row is not read as an empty list", [], problems)

# --- where the credentials path came from (#13) ------------------------------
#
# On a host with two harnesses the resolution is ambiguous on purpose, and
# PAYNANI_ENV settles it. The installer used to settle it once, for the unit,
# and forget: every other tool then resolved to a <clone>/.env that is not there,
# and reported no credentials about an install that was delivering mail.

f = Fixture()
f.env.unlink()
_, problems, _ = f.run()
check("missing credentials say where the path came from", True,
      any("which is where" in p for p in problems))

saved_env = os.environ.pop("PAYNANI_ENV", None)
try:
    runtime_file = pathlib.Path(tempfile.mkdtemp()) / "runtime.env"
    runtime_file.write_text("PAYNANI_RUNTIME=claudecode\n"
                            "PAYNANI_ENV=/somewhere/else/.env\n", encoding="utf-8")
    import paths
    saved_runtime_env = paths.runtime_env
    paths.runtime_env = lambda environ=None, home=None: runtime_file

    check("a recorded PAYNANI_ENV is read back out of runtime.env",
          pathlib.Path("/somewhere/else/.env"), paths.recorded_env(environ={}))
    check("a recorded file wins over falling back to the clone",
          pathlib.Path("/somewhere/else/.env"), paths.env_file(environ={}))
    check("but an explicit PAYNANI_ENV still wins over the recording",
          pathlib.Path("/named/by/hand/.env"),
          paths.env_file(environ={"PAYNANI_ENV": "/named/by/hand/.env"}))
    runtime_file.write_text("PAYNANI_RUNTIME=claudecode\n", encoding="utf-8")
    check("nothing recorded means nothing is invented", None,
          paths.recorded_env(environ={}))
    paths.runtime_env = saved_runtime_env
finally:
    if saved_env is not None:
        os.environ["PAYNANI_ENV"] = saved_env

# --- which code this install is actually running (#12) -----------------------
#
# A tree that differs from the published commit does not stop mail, so none of
# these is a problem. What they must not be is silent: #11 ran a modified
# listener for a day while every check reported on a tree nobody had described.

f = Fixture()
_, problems, warnings = f.run()
check("a clean checkout says nothing", [], warnings)
check("and is certainly not a failure", [], problems)

f = Fixture()
f.git = dict(f.git, dirty_tracked=7)
_, problems, warnings = f.run()
check("a modified tree is worth saying", True,
      any("not running the published code" in w for w in warnings))
check("and says how many files", True, any("7 tracked file(s)" in w for w in warnings))
check("and names the commit they differ from", True,
      any("abc1234" in w for w in warnings))
check("but is never a reason to call delivery broken", [], problems)

f = Fixture()
f.git = dict(f.git, dirty_tracked=7)
code, text = f.exit_code()
check("a modified tree does not change the exit code", 0, code)
check("and the report says the tree differs", True, "tracked file(s) modified" in text)

f = Fixture()
f.git = dict(f.git, in_origin=False)
_, problems, warnings = f.run()
check("a commit on no remote is worth saying", True,
      any("only on this machine" in w for w in warnings))
check("and is still not a failure", [], problems)

f = Fixture()
f.git = dict(f.git, is_repo=False, commit=None, dirty_tracked=None)
_, problems, warnings = f.run()
check("an install that is not a git checkout is not accused of anything", [], warnings)
check("nor called broken", [], problems)

f = Fixture()
f.git = dict(f.git, ahead=3, behind=1)
_, text = f.exit_code()
check("the report says how far the branch is from its upstream", True,
      "3 ahead, 1 behind upstream" in text)

# --- what the runtime last said ----------------------------------------------

f = Fixture()
(f.dir / "delivery.json").write_text(json.dumps({
    "last_accepted": {"event_id": "imap:INBOX:42:117", "at": "2026-08-18T19:20:00Z",
                      "runtime": "hermes",
                      "detail": "HTTP 202 status=accepted; agent completion "
                                "externally unconfirmed"},
    "last_error": {"event_id": "imap:INBOX:42:118", "at": "2026-08-18T19:21:00Z",
                   "runtime": "hermes", "detail": "retry: gateway timed out"},
}))
hc.DELIVERY = f.dir / "delivery.json"
_, text = f.exit_code()
check("the last accepted delivery is reported", True, "imap:INBOX:42:117" in text)
check("with the runtime that accepted it", True, "by hermes" in text)
check("the runtime's own words are shown, not summarised", True,
      "agent completion externally unconfirmed" in text)
check("a later refusal is shown too", True, "gateway timed out" in text)

# Reachability is checked live and separately; it must not be read backwards as
# evidence that something accepted earlier was ever acted on.
facts, _, _ = f.run()
check("reachability does not overwrite the recorded acceptance",
      "HTTP 202 status=accepted; agent completion externally unconfirmed",
      facts["delivery"]["last_accepted"]["detail"])

f = Fixture()
hc.DELIVERY = f.dir / "nothing.json"
_, text = f.exit_code()
check("an install that has delivered nothing says so", True,
      "nothing has been accepted by a runtime yet" in text)

# --- the caveat that stops somebody reading "ok" and leaving ------------------

f = Fixture()
_, text = f.exit_code()
check("reachability is not presented as proof of delivery", True,
      "not that a delivered event reaches anyone" in text)

# --- runtime.env is read, or this command is blind on Hermes (#61) ------------
#
# The services get runtime.env from systemd's EnvironmentFile=; a hand-run
# healthcheck used to get it from nowhere. That mattered asymmetrically:
# openclaw.detect() looks for a binary on the host and is true in any process,
# while hermes.detect() reads five HERMES_* variables out of the environment and
# was false in every process but the units. So the documented command reported
# no runtime on a Hermes install that was delivering mail, and only on Hermes —
# which is why it survived unnoticed as long as it did (agenteiamail 1.7.0).

HERMES_KEYS = ("PAYNANI_RUNTIME", "HERMES_NOTIFY_URL", "HERMES_NOTIFY_SECRET_FILE",
               "HERMES_ROSTER_URL", "HERMES_ROSTER_SECRET_FILE", "HERMES_HEALTH_URL",
               "HERMES_SIGNATURE_MODE")


def without_hermes_env():
    """A process that has never seen runtime.env, which is the bug's precondition."""
    saved = {k: os.environ.pop(k) for k in HERMES_KEYS if k in os.environ}
    return saved


def restore(saved):
    for k in HERMES_KEYS:
        os.environ.pop(k, None)
    os.environ.update(saved)


f = Fixture()
generated = f.dir / "runtime.env"
# Written the way scripts/install.sh writes it: quoted, escaped values.
generated.write_text('PAYNANI_RUNTIME="hermes"\n'
                     'HERMES_NOTIFY_URL="http://127.0.0.1:8644/hooks/paynani-notify"\n'
                     'HERMES_NOTIFY_SECRET_FILE="%s/hermes/notify.secret"\n'
                     'HERMES_ROSTER_URL="http://127.0.0.1:8644/hooks/paynani-roster"\n'
                     'HERMES_ROSTER_SECRET_FILE="%s/hermes/roster.secret"\n'
                     'HERMES_HEALTH_URL="http://127.0.0.1:8644/health"\n'
                     'HERMES_SIGNATURE_MODE="v2"\n' % (f.dir, f.dir))

saved = without_hermes_env()
try:
    check("without runtime.env, hermes cannot be detected at all", False,
          hc.dsp.load_adapter("hermes").detect())

    read = hc.load_runtime_env(generated)
    check("the file is reported as read", generated, read)
    check("and the runtime it names reaches the environment", "hermes",
          os.environ.get("PAYNANI_RUNTIME"))
    check("and every value the adapter detects on", True,
          hc.dsp.load_adapter("hermes").detect())
    check("quoting is undone, not passed through", "http://127.0.0.1:8644/health",
          os.environ.get("HERMES_HEALTH_URL"))
finally:
    restore(saved)

# An explicit variable is an operator overriding the install on purpose.
saved = without_hermes_env()
os.environ["PAYNANI_RUNTIME"] = "openclaw"
try:
    hc.load_runtime_env(generated)
    check("an explicit variable outranks the file", "openclaw",
          os.environ.get("PAYNANI_RUNTIME"))
finally:
    restore(saved)

# A host with no such file is an OpenClaw or manual install, not a fault.
saved = without_hermes_env()
try:
    check("a missing runtime.env is not an error", None,
          hc.load_runtime_env(f.dir / "does-not-exist"))
finally:
    restore(saved)

# End to end: the selection healthcheck performs, on a host configured only by
# the file. The adapter is stubbed because reachability is a separate question —
# what is under test is that a runtime is selected at all.
saved = without_hermes_env()
original_env, original_load = hc.runtime_env, hc.dsp.load_adapter


class Reachable:
    @staticmethod
    def check():
        class R:
            status = hc.ACCEPTED
            detail = "gateway answered"
        return R()


hc.runtime_env = lambda *a, **k: generated
hc.dsp.load_adapter = lambda name: Reachable
try:
    facts = REAL_RUNTIME_FACTS()
    check("runtime_facts selects hermes from the file alone", "hermes", facts["selected"])
    check("and says which file configured it", str(generated), facts["runtime_env"])
finally:
    hc.runtime_env, hc.dsp.load_adapter = original_env, original_load
    restore(saved)

# And when there is genuinely nothing to read, the operator is told this command
# could not see a file — not merely that no runtime exists. The two readings send
# the next person to different places.
missing = f.dir / "absent-runtime.env"
hc.runtime_env = lambda *a, **k: missing
try:
    _, problems, _ = Fixture(runtime=None).run()
    check("a runtime.env that could not be read is named in the failure", True,
          any(str(missing) in p for p in problems))
finally:
    hc.runtime_env = original_env

# --- roster mail that was delivered and never answered (#125) ----------------
#
# The failure this section is about looks healthier than any other in this file:
# listener active, dispatcher active, runtime reachable, queue empty. Everything
# worked. Nothing was answered.

HOUR = 60 * 60

f = Fixture().queue(3, age_seconds=6 * HOUR).drain()
facts, problems, warnings = f.run()
check("three roster messages delivered and nothing sent is a warning", True,
      any("roster message(s) have been delivered" in w for w in warnings))
check("and never a failure, because delivery itself worked", [], problems)
check("and counts what was delivered", 3, facts["reply"]["roster_delivered"])
check("and offers both readings rather than blaming the agent", True,
      any("nothing was attached to be told" in w for w in warnings))
code, text = f.exit_code()
check("so the exit code stays 0", 0, code)
check("and the report says a reply was not judged to be owed", True,
      "not judged here" in text)

f = Fixture()
facts, _, warnings = f.run()
check("a quiet mailbox says nothing at all", [], warnings)
check("and reports no roster mail rather than an unanswered count", None,
      facts["reply"]["unanswered_age_seconds"])

f = Fixture().queue(2, age_seconds=6 * HOUR).drain().sent(2)
facts, _, warnings = f.run()
check("roster mail answered after it arrived is silent", [], warnings)
check("and the send is recorded as seen", 2, facts["reply"]["sends_seen"])

f = Fixture().queue(1, age_seconds=90).drain()
_, _, warnings = f.run()
check("a reply still being written is not accused", [], warnings)

# Mail the dispatcher has not handed over yet belongs to the queue check, not
# this one: an agent cannot answer what it was never given.
f = Fixture().queue(3, age_seconds=6 * HOUR)
facts, _, warnings = f.run()
check("undelivered roster mail is not counted against the agent", 0,
      facts["reply"]["roster_delivered"])
check("and produces no unanswered warning", True,
      not any("roster message(s) have been delivered" in w for w in warnings))

# Absence of the log is not the same fact as a zero in it.
f = Fixture().queue(1, age_seconds=6 * HOUR).drain()
facts, _, warnings = f.run()
check("no sent.log reports absence, not zero sends", (False, None),
      (facts["reply"]["sent_log_present"], facts["reply"]["sends_seen"]))
check("and the absence is said out loud, with both readings of it", True,
      any("never sent anything or predates the log" in w for w in warnings))

f = Fixture().queue(1, age_seconds=6 * HOUR).drain().sent(0 or 1, age_seconds=7 * HOUR)
_, _, warnings = f.run()
check("a send older than the newest roster mail does not count as an answer", True,
      any("roster message(s) have been delivered" in w for w in warnings))

# rotate_logs.py rotates every *.log in the state directory, sent.log included.
# Reading only the live file would report a host that sent mail yesterday as
# never having sent anything.
f = Fixture().queue(1, age_seconds=6 * HOUR).drain().sent(1, rotated=True)
facts, _, warnings = f.run()
check("a rotated sent.log is still read", True, facts["reply"]["sent_log_present"])
check("and its send still answers the roster mail", [], warnings)

# Non-roster mail is reported to the agent and must never be answered, so it
# cannot be evidence that anything is unanswered.
f = Fixture()
stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 6 * HOUR))
ev.append(hc.JOURNAL, ev.mail_event(
    account="agent@example.com", mailbox="INBOX", uidvalidity=42, uid=900,
    sender_name="Stranger", sender_address="s@x.com", subject="unsolicited",
    sent_at=stamp, roster_match=False, notification_text="[mail] unsolicited",
    observed_at=stamp))
f.drain()
facts, _, warnings = f.run()
check("mail from outside the roster is never counted as unanswered", 0,
      facts["reply"]["roster_delivered"])
check("and raises no warning", [], warnings)

# On Claude Code, delivery means the bytes are in the spool. Mail waiting there
# for a session that has not started is that runtime's resting state, and
# spool_facts() already refuses to call it a fault; this check must agree.
f = (Fixture(runtime="claudecode").queue(2, age_seconds=6 * HOUR)
     .drain().spool(bytes_unread=400, bytes_total=400))
facts, _, warnings = f.run()
check("mail still sitting unread in the Claude Code spool is not unanswered", [],
      warnings)
check("though the delivery itself is still counted", 2,
      facts["reply"]["roster_delivered"])

f = (Fixture(runtime="claudecode").queue(2, age_seconds=6 * HOUR)
     .drain().spool(bytes_unread=0, bytes_total=400))
_, _, warnings = f.run()
check("but a spool a session has read through is answerable, and warns", True,
      any("roster message(s) have been delivered" in w for w in warnings))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
