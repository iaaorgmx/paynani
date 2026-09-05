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

    def test_an_empty_log_is_not_a_fault(self):
        self.log.write_text("")
        self.assertEqual([], self.ss.dispatcher_faults())

    def test_the_dispatcher_marks_the_lines_this_filter_drops(self):
        """The writer and the reader must agree, so read the writer's source."""
        source = (ROOT / "harness" / "dispatch.py").read_text()
        self.assertIn("def note(message):", source)
        self.assertIn("log(ev.ROUTINE_PREFIX + message)", source)
        for routine in ("delivering to {runtime}", "delivery recovered",
                        "compacted the event journal"):
            self.assertIn(routine, source)
            line = next(ln for ln in source.splitlines() if routine in ln and "(" in ln)
            self.assertTrue(line.strip().startswith("note("),
                            f"routine line is not marked: {line.strip()}")


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
        deadline = __import__("time").time() + 5
        while not (self.state / "session.watch.lock").exists():
            if __import__("time").time() > deadline:
                self.fail("first watcher never took the lock")
            __import__("time").sleep(0.05)
        __import__("time").sleep(0.3)
        second = sp.run(["bash", str(self.WATCH), str(self.state), "0"],
                        capture_output=True, text=True, timeout=10)
        self.assertEqual(second.returncode, 0)
        self.assertIn("already watching", second.stderr)

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
