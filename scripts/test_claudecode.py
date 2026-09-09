#!/usr/bin/env python3
"""Contract tests for the Claude Code adapter."""

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from adapters import claudecode


def envelope(text="[mail 09:00:00, sent 08:59:00, roster] Someone — Subject", **kw):
    base = {"event_id": "evt-1", "notification_text": text}
    base.update(kw)
    return base


class DispatcherFaults(unittest.TestCase):
    """Which lines of the dispatcher's diagnostics count as a fault (#15).

    The file holds two kinds. A complaint means mail is being journalled and not
    delivered, which nothing else can see. A routine note means the dispatcher
    said what it was doing. Reading both as complaints made every healthy install
    open every session with a warning, and an alarm that sounds on the good path
    is one people stop reading.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        sys.path.insert(0, str(ROOT / "harness"))
        import session_start as ss
        import event as ev
        self.ss, self.ev = ss, ev
        self.log = pathlib.Path(self.tmp.name) / "dispatch.err.log"
        patcher = mock.patch.object(ss, "DISPATCH_ERR", self.log)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_routine_startup_note_is_not_a_fault(self):
        self.log.write_text(self.ev.ROUTINE_PREFIX + "delivering to claudecode (/x)\n")
        self.assertEqual([], self.ss.dispatcher_faults())

    def test_a_real_complaint_still_is(self):
        self.log.write_text("claudecode cannot deliver imap:INBOX:1:5: spool is full\n")
        self.assertEqual(1, len(self.ss.dispatcher_faults()))

    def test_a_complaint_among_routine_notes_survives(self):
        self.log.write_text(
            self.ev.ROUTINE_PREFIX + "delivering to claudecode (/x)\n"
            "claudecode refused imap:INBOX:1:5: no\n"
            + self.ev.ROUTINE_PREFIX + "delivery recovered: imap:INBOX:1:6\n")
        faults = self.ss.dispatcher_faults()
        self.assertEqual(1, len(faults))
        self.assertIn("refused", faults[0])

    def test_an_unmarked_line_from_an_older_version_still_counts(self):
        # Backwards compatibility falls the safe way: a log written before the
        # marker existed keeps raising the warning rather than going quiet.
        self.log.write_text("delivering to claudecode (/x)\n")
        self.assertEqual(1, len(self.ss.dispatcher_faults()))

    def test_a_stale_unmarked_line_is_ignored_once_the_dispatcher_restarted(self):
        # #59: on a host old enough to have an unmarked line from before the ok:
        # prefix existed, every clean restart since must retire it, not keep
        # citing it forever.
        self.log.write_text(
            "delivering to claudecode (/x)\n"
            + self.ev.ROUTINE_PREFIX + "delivering to claudecode (/x)\n")
        self.assertEqual([], self.ss.dispatcher_faults())

    def test_a_real_fault_after_the_latest_startup_still_counts(self):
        # The other half of #59's fix: cutting on the latest startup must not
        # start swallowing genuine complaints that come after it (#15, reversed).
        self.log.write_text(
            self.ev.ROUTINE_PREFIX + "delivering to claudecode (/x)\n"
            "claudecode cannot deliver imap:INBOX:1:5: spool is full\n")
        faults = self.ss.dispatcher_faults()
        self.assertEqual(1, len(faults))
        self.assertIn("spool is full", faults[0])

    def test_an_empty_log_is_not_a_fault(self):
        self.log.write_text("")
        self.assertEqual([], self.ss.dispatcher_faults())

    def test_the_dispatcher_marks_the_lines_this_filter_drops(self):
        """The writer and the reader must agree, so read the writer's source."""
        source = (ROOT / "harness" / "dispatch.py").read_text()
        self.assertIn("def note(message):", source)
        self.assertIn("log(ev.ROUTINE_PREFIX + message)", source)
        self.assertIn("note(f\"{ev.STARTUP_NOTE}{runtime}\"", source)
        for routine in ("delivery recovered", "compacted the event journal"):
            self.assertIn(routine, source)
            line = next(ln for ln in source.splitlines() if routine in ln and "(" in ln)
            self.assertTrue(line.strip().startswith("note("),
                            f"routine line is not marked: {line.strip()}")

    def test_the_startup_marker_is_one_constant_not_two_literals(self):
        """
        #59 review: dispatch.py used to write "delivering to {runtime}" as a bare
        literal while session_start.py matched "delivering to " as a second, typed
        by hand. A test that also typed the string twice would keep passing the
        day only one of those changed. Reading both sources for the same
        constant is the only check that would actually catch that drift.
        """
        dispatch_source = (ROOT / "harness" / "dispatch.py").read_text()
        session_start_source = (ROOT / "harness" / "session_start.py").read_text()
        self.assertIn("ev.STARTUP_NOTE", dispatch_source)
        self.assertIn("ev.STARTUP_NOTE", session_start_source)
        self.assertEqual(self.ev.STARTUP_NOTE, "delivering to ")


class SpoolDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self.tmp.name) / "state"
        patcher = mock.patch.object(claudecode, "_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        os.environ.pop("PAYNANI_CLAUDE_MODE", None)

    def spool_text(self):
        return claudecode.spool_path().read_text(encoding="utf-8")

    def test_delivery_appends_one_line_and_is_accepted(self):
        result = claudecode.deliver(envelope("first"))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(self.spool_text(), "first\n")

    def test_delivery_appends_rather_than_overwrites(self):
        claudecode.deliver(envelope("first"))
        claudecode.deliver(envelope("second"))
        self.assertEqual(self.spool_text(), "first\nsecond\n")

    def test_offsets_are_stable_across_deliveries(self):
        """
        Both session-side readers index this file by byte offset. A delivery must
        only ever extend it: rewriting or reordering would resume the next reader
        at the wrong place, which shows mail twice or steps over it silently.
        """
        claudecode.deliver(envelope("first"))
        prefix = self.spool_text()
        claudecode.deliver(envelope("second"))
        self.assertTrue(self.spool_text().startswith(prefix))

    def test_embedded_newlines_do_not_become_two_events(self):
        """One record is one line, or the reader's line count stops matching."""
        claudecode.deliver(envelope("has\nnewline"))
        self.assertEqual(len(self.spool_text().splitlines()), 1)

    def test_trailing_newline_is_not_doubled(self):
        claudecode.deliver(envelope("already ends\n"))
        self.assertEqual(self.spool_text(), "already ends\n")

    def test_unicode_survives_the_round_trip(self):
        claudecode.deliver(envelope("ñ á ¿de veras?"))
        self.assertIn("ñ á ¿de veras?", self.spool_text())

    def test_missing_text_is_config_not_retry(self):
        """Retrying forever on a malformed record is a silent stall."""
        result = claudecode.deliver(envelope(text=""))
        self.assertEqual(result.status, "config")

    def test_unwritable_state_is_config_not_retry(self):
        self.state.mkdir(parents=True)
        self.state.chmod(0o500)
        self.addCleanup(self.state.chmod, 0o700)
        result = claudecode.deliver(envelope("nope"))
        self.assertEqual(result.status, "config")


class SpoolNaming(unittest.TestCase):
    def test_spool_is_not_a_dot_log(self):
        """
        rotate_logs.py rotates every *.log in the state directory, and rotation
        renumbers bytes underneath two readers that index by offset. This name is
        load-bearing; see the module docstring.
        """
        self.assertFalse(claudecode.SPOOL_RELATIVE.endswith(".log"))


class Detection(unittest.TestCase):
    def test_detect_follows_the_binary_not_the_directory(self):
        with mock.patch.object(claudecode, "find_binary", lambda: None):
            self.assertFalse(claudecode.detect())
        with mock.patch.object(claudecode, "find_binary", lambda: "/usr/bin/claude"):
            self.assertTrue(claudecode.detect())

    def test_explicit_override_wins(self):
        with mock.patch.dict(os.environ, {"CLAUDE": "/nonexistent/claude"}):
            self.assertIsNone(claudecode.find_binary())


class AgentMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self.tmp.name) / "state"
        patcher = mock.patch.object(claudecode, "_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_off_by_default(self):
        with mock.patch.object(claudecode, "_start_agent_run") as run:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PAYNANI_CLAUDE_MODE", None)
                claudecode.deliver(envelope("x"))
        run.assert_not_called()

    def test_a_failed_agent_run_still_accepts_because_the_event_is_spooled(self):
        """
        Returning RETRY here would append the same line again on every attempt,
        so a failing agent run would fill the spool with duplicates of a message
        that was already delivered.
        """
        from adapters import retry as retry_result
        with mock.patch.dict(os.environ, {"PAYNANI_CLAUDE_MODE": "agent"}):
            with mock.patch.object(claudecode, "_start_agent_run",
                                   lambda text: retry_result("boom")):
                result = claudecode.deliver(envelope("x"))
        self.assertTrue(result.ok)
        self.assertIn("agent run failed", result.detail)
        self.assertEqual(claudecode.spool_path().read_text(encoding="utf-8"), "x\n")


class SpoolReplay(unittest.TestCase):
    """The session-start side: what a new session is told it missed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        sys.path.insert(0, str(ROOT / "harness"))
        import session_start as ss
        self.ss = ss
        self.spool = self.state / "session.spool"
        self.offset = self.state / "session.offset"
        for attr, value in (("SPOOL", self.spool), ("SESSION_OFFSET", self.offset)):
            patcher = mock.patch.object(ss, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _emit(self, **stubs):
        """Run main() with a stubbed host and return (raw stdout, parsed)."""
        import contextlib, io, json as _json
        ss = self.ss
        defaults = {
            "unit_state": lambda unit: "active",
            "dispatcher_faults": lambda: [],
            "read_backlog": lambda: ([], False),
            "read_spool_backlog": lambda: (["[mail] one"], False, 32),
            "selected_runtime": lambda: "claudecode",
            "version_line": lambda: None,
            "local_code_line": lambda: "",
        }
        defaults.update(stubs)
        patchers = [mock.patch.object(ss, name, value) for name, value in defaults.items()]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ss.main()
        raw = buf.getvalue()
        return raw, _json.loads(raw)

    def test_a_healthy_host_emits_no_null_system_message(self):
        """
        Claude Code validates this payload and rejects `"systemMessage": null`
        with `Hook JSON output validation failed — (root): Invalid input`, which
        discards the whole hook: no replay, no watch command, no offset.

        The failure is inverted, which is how it survived a release. Every branch
        that fills systemMessage is a branch where something is broken, so the
        hook worked on every unhealthy install and failed only on a healthy one
        with mail waiting — the case it exists for. Found by #78 criterion 6, on
        the second session of the first Claude Code host, after the install that
        had been masking it was repaired.
        """
        raw, payload = self._emit()
        self.assertNotIn('"systemMessage": null', raw)
        self.assertNotIn("systemMessage", payload)
        self.assertIn("additionalContext", payload["hookSpecificOutput"])

    def test_a_problem_still_reaches_the_status_line(self):
        """Omitting the key when empty must not omit it when there is a problem."""
        _, payload = self._emit(unit_state=lambda unit: "down" if unit == self.ss.SERVICE else "active")
        self.assertIn("systemMessage", payload)
        self.assertIn("DOWN", payload["systemMessage"])

    def test_everything_is_replayed_from_a_cold_start(self):
        self.spool.write_text("one\ntwo\n", encoding="utf-8")
        lines, capped, through = self.ss.read_spool_backlog()
        self.assertEqual(lines, ["one", "two"])
        self.assertFalse(capped)
        self.assertEqual(through, self.spool.stat().st_size)

    def test_only_what_is_past_the_offset_is_replayed(self):
        self.spool.write_text("one\ntwo\n", encoding="utf-8")
        self.offset.write_text("4", encoding="utf-8")
        lines, _, _ = self.ss.read_spool_backlog()
        self.assertEqual(lines, ["two"])

    def test_reading_does_not_advance_the_offset(self):
        """
        Arming the watch acknowledges the replay, not reading it. A hook that
        advanced the offset would claim an arming it cannot observe, and an agent
        that never armed would silently lose that mail.
        """
        self.spool.write_text("one\n", encoding="utf-8")
        self.ss.read_spool_backlog()
        self.assertFalse(self.offset.exists())

    def test_a_truncated_spool_replays_rather_than_skips(self):
        """
        A spool shorter than the recorded offset was replaced or truncated.
        Trusting the stale offset steps over everything now in it, and a skipped
        message is indistinguishable from a quiet mailbox.
        """
        self.spool.write_text("fresh\n", encoding="utf-8")
        self.offset.write_text("9999", encoding="utf-8")
        lines, _, _ = self.ss.read_spool_backlog()
        self.assertEqual(lines, ["fresh"])

    def test_a_corrupt_offset_replays_rather_than_skips(self):
        self.spool.write_text("fresh\n", encoding="utf-8")
        self.offset.write_text("not-a-number", encoding="utf-8")
        lines, _, _ = self.ss.read_spool_backlog()
        self.assertEqual(lines, ["fresh"])

    def test_replay_is_capped_without_acknowledging_unshown_mail(self):
        """
        Trimming protects the context window. The offset must stop at the last
        line actually shown, or the unshown messages are silently acknowledged.
        """
        count = self.ss.MAX_REPLAY + 5
        self.spool.write_text("".join(f"line{i}\n" for i in range(count)), encoding="utf-8")
        lines, capped, through = self.ss.read_spool_backlog()
        self.assertEqual(len(lines), self.ss.MAX_REPLAY)
        self.assertEqual(lines[0], "line0")
        self.assertEqual(lines[-1], f"line{self.ss.MAX_REPLAY - 1}")
        self.assertTrue(capped)
        self.assertLess(through, self.spool.stat().st_size)

    def test_missing_spool_is_quiet(self):
        lines, capped, through = self.ss.read_spool_backlog()
        self.assertEqual(lines, [])
        self.assertEqual(through, 0)


class Watcher(unittest.TestCase):
    """The shell side: one watcher, and an offset that advances exactly."""

    WATCH = ROOT / "harness/session_watch.sh"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)

    def test_a_second_watcher_refuses_rather_than_racing(self):
        """
        Two consumers of one stream racing on one cursor duplicated events and
        corrupted the record of what had been seen. Every other runtime avoids
        this by never letting a session arm a watcher; this one cannot, so the
        guard lives here instead.
        """
        import subprocess as sp
        (self.state / "session.spool").write_text("", encoding="utf-8")
        first = sp.Popen(["bash", str(self.WATCH), str(self.state), "0"],
                         stdout=sp.PIPE, stderr=sp.PIPE, text=True)
        self.addCleanup(lambda: (first.kill(), first.stdout.close(), first.stderr.close()))
        # The lock is the directory, not the file. The file was the flock
        # target and it is only created where `flock` exists, so waiting on it
        # made this test hang on any host without it -- macOS, where the thing
        # under test was broken in the first place (#105).
        deadline = __import__("time").time() + 5
        while not (self.state / "session.watch.lock.d").exists():
            if __import__("time").time() > deadline:
                self.fail("first watcher never took the lock")
            __import__("time").sleep(0.05)
        __import__("time").sleep(0.3)
        second = sp.run(["bash", str(self.WATCH), str(self.state), "0"],
                        capture_output=True, text=True, timeout=10)
        self.assertEqual(second.returncode, 0)
        # stdout, not stderr (#62): a Monitor only turns stdout into a
        # notification, so the second session must see this line to know it
        # is not armed rather than mistaking silence for a quiet mailbox.
        self.assertIn("already watching", second.stdout)
        self.assertEqual(second.stderr, "")

    def test_arming_records_the_offset_it_was_given(self):
        """Arming is the acknowledgement; it must land before any mail does."""
        import subprocess as sp, time
        (self.state / "session.spool").write_text("a\nb\n", encoding="utf-8")
        proc = sp.Popen(["bash", str(self.WATCH), str(self.state), "4"],
                        stdout=sp.PIPE, stderr=sp.PIPE, text=True)
        self.addCleanup(lambda: (proc.kill(), proc.stdout.close(), proc.stderr.close()))
        deadline = time.time() + 5
        offset = self.state / "session.offset"
        while not offset.exists():
            if time.time() > deadline:
                self.fail("offset was never written")
            time.sleep(0.05)
        self.assertGreaterEqual(int(offset.read_text().strip()), 4)

    # ---- a host without flock: what #105 was ------------------------------
    #
    # `flock` is util-linux and macOS does not ship it. The old guard read the
    # missing command's exit 127 as "somebody else holds this", so every session
    # on a Mac announced a watcher that did not exist and armed nothing.
    #
    # These run against a PATH built out of symlinks to what the script actually
    # uses, minus flock. That is closer to the real thing than mocking, and it
    # runs on Linux, so the platform that has the tool still proves the branch
    # for the platform that does not.

    def _path_without_flock(self):
        import shutil as sh
        bin_dir = pathlib.Path(self.tmp.name) / "nobin"
        bin_dir.mkdir(exist_ok=True)
        for tool in ("bash", "sh", "ps", "awk", "tail", "wc", "tr", "mkdir",
                     "rm", "mv", "cat", "sleep", "kill", "printf", "sed"):
            found = sh.which(tool)
            if found:
                link = bin_dir / tool
                if not link.exists():
                    link.symlink_to(found)
        self.assertIsNone(sh.which("flock", path=str(bin_dir)),
                          "the fixture PATH must not contain flock")
        return {**os.environ, "PATH": str(bin_dir)}

    def _wait_for_arming(self, proc, timeout=8):
        import time
        offset = self.state / "session.offset"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if offset.exists() and (self.state / "session.watch.lock.d").exists():
                return True
            if proc.poll() is not None:
                return False
            time.sleep(0.05)
        return False

    def test_it_arms_without_the_flock_binary(self):
        """#105: no flock is not the same as somebody else is watching."""
        import subprocess as sp
        (self.state / "session.spool").write_text("", encoding="utf-8")
        proc = sp.Popen(["bash", str(self.WATCH), str(self.state), "0"],
                        stdout=sp.PIPE, stderr=sp.PIPE, text=True,
                        env=self._path_without_flock())
        self.addCleanup(lambda: (proc.kill(), proc.stdout.close(), proc.stderr.close()))
        self.assertTrue(self._wait_for_arming(proc),
                        "the watcher did not arm on a host without flock")

    def test_two_without_flock_still_yield_exactly_one_watcher(self):
        """
        The guard has to keep guarding once the binary it used is gone.

        Losing exclusivity here is not a smaller bug than #105, it is the one the
        guard was written for: two readers advancing one cursor is how events got
        duplicated and the record of what had been seen was corrupted.
        """
        import subprocess as sp
        env = self._path_without_flock()
        (self.state / "session.spool").write_text("", encoding="utf-8")
        first = sp.Popen(["bash", str(self.WATCH), str(self.state), "0"],
                         stdout=sp.PIPE, stderr=sp.PIPE, text=True, env=env)
        self.addCleanup(lambda: (first.kill(), first.stdout.close(), first.stderr.close()))
        self.assertTrue(self._wait_for_arming(first))

        second = sp.run(["bash", str(self.WATCH), str(self.state), "0"],
                        capture_output=True, text=True, timeout=15, env=env)
        self.assertEqual(0, second.returncode)
        self.assertIn("already watching", second.stdout)
        self.assertEqual("", second.stderr)

    # ---- a holder that is alive and useless: what #62 was -----------------

    def test_a_suspended_session_is_taken_over_rather_than_deferred_to(self):
        """
        #62, and the reason this is not just a portability fix.

        A watcher whose parent session had been suspended for nearly nine hours
        kept draining the spool and advancing the cursor. The next session could
        not arm, was not told, and never replayed the backlog either, because the
        offset said it had been seen. Every indicator green, no mail delivered.

        Alive is not the same as usable, and the guard has to ask the second
        question.
        """
        import subprocess as sp, signal, time
        (self.state / "session.spool").write_text("", encoding="utf-8")

        # Something alive and stopped, standing in for the suspended session.
        holder = sp.Popen(["sleep", "300"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        holder.send_signal(signal.SIGSTOP)
        deadline = time.time() + 5
        while time.time() < deadline:
            state = sp.run(["ps", "-o", "state=", "-p", str(holder.pid)],
                           capture_output=True, text=True).stdout.strip()
            if state.startswith("T"):
                break
            time.sleep(0.05)
        else:
            self.skipTest("could not put the stand-in holder into a stopped state")

        lock = self.state / "session.watch.lock.d"
        lock.mkdir()
        (lock / "owner").write_text(
            f"watcher={holder.pid}\nsession={holder.pid}\n", encoding="utf-8")

        proc = sp.Popen(["bash", str(self.WATCH), str(self.state), "0"],
                        stdout=sp.PIPE, stderr=sp.PIPE, text=True)
        self.addCleanup(lambda: (proc.kill(), proc.stdout.close(), proc.stderr.close()))
        self.assertTrue(self._wait_for_arming(proc),
                        "the watcher deferred to a suspended session instead of taking over")

        owner = (lock / "owner").read_text(encoding="utf-8")
        self.assertNotIn(f"session={holder.pid}", owner,
                         "the suspended session still owns the lock")

    # ---- the cursor is a claim, and it stops when the claim stops being true --

    def test_a_suspended_session_stops_the_cursor_rather_than_advancing_it(self):
        """
        #110, and the half of #62 that survived its own fix.

        Two things are proved here at once, and the second is why the tree in
        this test has three levels instead of two.

        The cursor: a watcher that keeps advancing it while nothing is being
        rendered marks mail as seen by nobody. The next session's hook reads that
        cursor to decide what to replay, so those messages are skipped then and
        never shown afterwards either -- 8h43m and 3299 bytes on one host.

        The pid: the process to watch is not $PPID. The harness runs this through
        a wrapper, so $PPID is a shell that stays healthy while the session above
        it is stopped. The grandparent here stands in for the session and the
        parent for that wrapper, which is the shape measured on a live host.
        """
        import subprocess as sp, signal, time
        spool = self.state / "session.spool"
        spool.write_text("", encoding="utf-8")
        out = self.state / "watch.out"

        # grandparent -> parent -> watcher, so stopping the grandparent leaves
        # $PPID untouched. `exec` keeps the watcher as the parent's own process
        # rather than adding a level.
        inner = f"exec bash {self.WATCH} {self.state} 0"
        holder = sp.Popen(["bash", "-c", f"bash -c {inner!r} > {out} 2>&1"])
        self.addCleanup(lambda: (holder.send_signal(signal.SIGCONT),
                                 holder.kill(), holder.wait()))

        def wait_for(predicate, what, limit=15):
            deadline = time.time() + limit
            while time.time() < deadline:
                if predicate():
                    return
                time.sleep(0.1)
            self.fail(f"timed out waiting for {what}")

        offset = self.state / "session.offset"
        wait_for(offset.exists, "the watcher to arm")

        # Healthy first, or the rest proves nothing: a watcher that never
        # advances would pass the assertion below for the wrong reason.
        with spool.open("a", encoding="utf-8") as handle:
            handle.write("hola\n")
        wait_for(lambda: offset.read_text().strip() == "5",
                 "the cursor to advance while the session is healthy")

        holder.send_signal(signal.SIGSTOP)
        wait_for(lambda: sp.run(["ps", "-o", "state=", "-p", str(holder.pid)],
                                capture_output=True, text=True).stdout.strip().startswith("T"),
                 "the stand-in session to stop")

        # Wait for the watcher to notice before writing, and this wait is the
        # design rather than test slack. Suspension is caught on a timer because
        # `ps` costs ~8.1ms against 25us for `kill -0`, so a line arriving inside
        # that interval is still processed. Writing immediately after the stop
        # asserts a stronger property than the code offers, which is exactly what
        # this test did on its first run: it failed, correctly.
        wait_for(lambda: "suspended" in out.read_text(encoding="utf-8"),
                 "the watcher to notice the suspension")

        with spool.open("a", encoding="utf-8") as handle:
            handle.write("adios\n")
        time.sleep(3)
        self.assertEqual("5", offset.read_text().strip(),
                         "the cursor advanced past a line nobody could have seen")
        self.assertIn("suspended", out.read_text(encoding="utf-8"))
        self.assertIn("replays what is left", out.read_text(encoding="utf-8"))

    def test_the_ancestor_chain_stops_where_this_user_stops(self):
        """
        The walk has to end at the last process this user can signal.

        Walking to pid 1 collects the login shell's own ancestors and then kernel
        threads, and `kill -0` fails on those for want of permission rather than
        because they died. Reading that as "the session is gone" stopped the
        watcher on the first line it ever read. Found by running it; kept so it
        stays found.

        The check happens inside the shell that collected the chain. Handing the
        pids back to Python and testing them there races with the shell's own
        exit: its ancestors include processes that are gone a moment later, and
        the test failed for that instead of for the thing it is about.
        """
        import subprocess as sp
        script = self._ancestors_function() + """
chain=$(ancestors $PPID)
[ -n "$chain" ] || { echo "EMPTY"; exit 1; }
for pid in $chain; do
    kill -0 "$pid" 2>/dev/null || { echo "UNSIGNALLABLE $pid"; exit 1; }
done
echo "OK $chain"
"""
        done = sp.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertTrue(done.stdout.startswith("OK "), done.stdout)

    def _ancestors_function(self):
        source = self.WATCH.read_text(encoding="utf-8")
        start = source.index("ancestors() {")
        end = source.index("\n}\n", start) + len("\n}\n")
        return source[start:end]

    def test_the_guard_never_asks_which_operating_system_this_is(self):
        """
        #61, #68 and #80 were all one mistake: asking about the machine to learn
        about a tool. The rule this file enforces on itself is the one that
        would have prevented them.
        """
        source = self.WATCH.read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                          if not line.lstrip().startswith("#"))
        for name in ("uname", "OSTYPE", "Darwin", "darwin"):
            self.assertNotIn(name, code,
                             f"the watcher decides something by {name}; "
                             "detect the capability instead")


class HookRegistration(unittest.TestCase):
    """settings.json is the user's file. We merge into it and never own it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = pathlib.Path(self.tmp.name) / "settings.json"
        sys.path.insert(0, str(ROOT / "scripts"))
        import importlib
        self.hook = importlib.import_module("claude_hook")

    def run_install(self):
        return self.hook.install(self.settings)

    def load(self):
        import json
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def test_creates_the_file_when_absent(self):
        self.run_install()
        self.assertTrue(self.hook.already_registered(self.load()))

    def test_unrelated_settings_survive(self):
        import json
        self.settings.write_text(json.dumps({
            "theme": "dark",
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.py"}]}]},
        }), encoding="utf-8")
        self.run_install()
        after = self.load()
        self.assertEqual(after["theme"], "dark")
        self.assertEqual(after["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "mine.py")

    def test_an_existing_session_start_hook_is_kept(self):
        """Claude Code runs every SessionStart hook. Replacing the list silently
        disables whatever the host was already doing at startup."""
        import json
        self.settings.write_text(json.dumps({
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "theirs.py"}]}]},
        }), encoding="utf-8")
        self.run_install()
        commands = [h["command"]
                    for entry in self.load()["hooks"]["SessionStart"]
                    for h in entry["hooks"]]
        self.assertIn("theirs.py", commands)
        self.assertEqual(len(commands), 2)

    def test_installing_twice_does_not_duplicate(self):
        self.run_install()
        self.run_install()
        commands = [h["command"]
                    for entry in self.load()["hooks"]["SessionStart"]
                    for h in entry["hooks"]]
        self.assertEqual(len(commands), 1)

    def test_an_existing_file_is_backed_up(self):
        self.settings.write_text('{"theme": "dark"}', encoding="utf-8")
        self.run_install()
        self.assertTrue(self.settings.with_suffix(".json.paynani.bak").is_file())

    def test_unparseable_settings_are_refused_not_repaired(self):
        """Rewriting a file we could not parse is how an install eats
        configuration it was never asked to touch."""
        self.settings.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_install()
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{ not json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
