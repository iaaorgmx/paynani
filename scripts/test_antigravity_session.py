#!/usr/bin/env python3
"""The agy hook side of session_start.py (#749 T2)."""

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import session_start as ss  # noqa: E402

LINE_A = "[mail 09:00:00, sent 08:59:00, roster] Ana — Hola [scripts/paynani event show imap:INBOX:1:10]"
LINE_B = "[mail 09:05:00, sent 09:04:00, roster] Ana — Otra [scripts/paynani event show imap:INBOX:1:11]"


class Hook(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.spool = self.dir / "antigravity.spool"
        self.offset = self.dir / "antigravity.offset"
        self.healthy = {"listener": "up", "dispatcher": "up"}
        self.unattended = []
        self.presented = []
        patches = [
            mock.patch.object(ss, "ANTIGRAVITY_SPOOL", self.spool),
            mock.patch.object(ss, "ANTIGRAVITY_OFFSET", self.offset),
            mock.patch.object(ss, "unit_state", self._unit_state),
            mock.patch.object(ss, "dispatcher_faults", lambda: []),
            mock.patch.object(ss, "read_backlog", lambda: ([], False)),
            mock.patch.object(ss, "unattended_roster", lambda **kw: self.unattended),
            mock.patch.object(ss, "version_line", lambda: ""),
            mock.patch.object(ss.ledger, "transition", self._transition),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _unit_state(self, unit):
        return self.healthy["listener" if unit == ss.SERVICE else "dispatcher"]

    def _transition(self, path, event_id, state, **kw):
        self.presented.append((event_id, state, kw.get("runtime")))

    def run_hook(self, payload):
        out = io.StringIO()
        with mock.patch.object(ss, "read_hook_input", lambda: payload), \
                contextlib.redirect_stdout(out):
            self.assertEqual(0, ss.antigravity_command())
        return json.loads(out.getvalue())

    @staticmethod
    def text_of(result):
        steps = result.get("injectSteps") or []
        return steps[0]["systemMessage"]["systemMessage"] if steps else ""

    def common(self, **kw):
        base = {"conversationId": "c-1", "workspacePaths": ["/w"], "transcriptPath": "/t",
                "artifactDirectoryPath": "/a", "modelName": "m", "lastUserInput": "hola"}
        base.update(kw)
        return base

    def test_session_start_replays_the_spool_and_acknowledges(self):
        self.spool.write_text(LINE_A + "\n" + LINE_B + "\n")
        text = self.text_of(self.run_hook(self.common()))
        self.assertIn(LINE_A, text)
        self.assertIn(LINE_B, text)
        self.assertIn("event mark <event_id> handled", text)
        self.assertEqual(str(self.spool.stat().st_size), self.offset.read_text())
        self.assertEqual({"imap:INBOX:1:10", "imap:INBOX:1:11"},
                         {e for e, state, rt in self.presented if state == "presented"})
        self.assertEqual({"antigravity"}, {rt for _, _, rt in self.presented})

    def test_the_same_mail_is_not_shown_twice(self):
        self.spool.write_text(LINE_A + "\n")
        self.run_hook(self.common())
        text = self.text_of(self.run_hook(self.common(invocationNum=0)))
        self.assertNotIn(LINE_A, text)

    def test_turn_start_shows_mail_that_arrived_since(self):
        self.spool.write_text(LINE_A + "\n")
        self.run_hook(self.common())
        with open(self.spool, "a") as handle:
            handle.write(LINE_B + "\n")
        text = self.text_of(self.run_hook(self.common(invocationNum=0, initialNumSteps=4)))
        self.assertIn(LINE_B, text)
        self.assertNotIn(LINE_A, text)

    def test_later_model_calls_say_nothing_and_touch_nothing(self):
        self.spool.write_text(LINE_A + "\n")
        with mock.patch.object(ss, "unit_state", side_effect=AssertionError("slow path")):
            self.assertEqual({}, self.run_hook(self.common(invocationNum=3)))
        self.assertFalse(self.offset.exists())

    def test_a_quiet_turn_is_an_empty_object(self):
        self.assertEqual({}, self.run_hook(self.common(invocationNum=0)))

    def test_a_quiet_session_start_still_says_it_checked(self):
        self.assertIn("no unseen mail", self.text_of(self.run_hook(self.common())))

    def test_a_down_listener_is_said_at_every_turn(self):
        self.healthy["listener"] = "down"
        self.assertIn("MAIL LISTENER IS DOWN",
                      self.text_of(self.run_hook(self.common(invocationNum=0))))

    def test_open_notices_come_with_new_conversations_not_every_turn(self):
        self.unattended = [("imap:INBOX:1:7", {"notification_text": "[mail x, roster] old"})]
        with mock.patch.object(ss, "unattended_line", lambda e, env: e):
            self.assertIn("NOT YET CLOSED", self.text_of(self.run_hook(self.common())))
            self.assertEqual({}, self.run_hook(self.common(invocationNum=0)))

    def test_an_oversized_replay_is_not_acknowledged(self):
        self.spool.write_text(LINE_A + "\n")
        with mock.patch.object(ss, "ANTIGRAVITY_ACK_CONTEXT_LIMIT", 10):
            self.assertIn(LINE_A, self.text_of(self.run_hook(self.common())))
        self.assertFalse(self.offset.exists())

    def test_no_stdin_is_a_session_start(self):
        self.spool.write_text(LINE_A + "\n")
        self.assertIn(LINE_A, self.text_of(self.run_hook({})))

    def test_a_bad_invocation_num_says_nothing(self):
        self.assertEqual({}, self.run_hook(self.common(invocationNum="x")))

    def test_output_shape(self):
        self.assertEqual({}, ss.antigravity_output(""))
        self.assertEqual(
            {"injectSteps": [{"systemMessage": {"systemMessage": "hi",
                                                "metadata": {"source": "paynani"}}}]},
            ss.antigravity_output("hi"))

    def test_main_routes_the_flag(self):
        with mock.patch.object(sys, "argv", ["session_start.py", "--antigravity"]), \
                mock.patch.object(ss, "antigravity_command", lambda: 7):
            self.assertEqual(7, ss.main())

    def test_spool_paths_knows_the_runtime(self):
        self.assertEqual((self.spool, self.offset), ss.spool_paths("antigravity"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
