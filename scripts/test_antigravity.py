#!/usr/bin/env python3
"""Contract tests for the Antigravity CLI adapter (#749 T1)."""

import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from adapters import antigravity  # noqa: E402
import capabilities  # noqa: E402
import dispatch  # noqa: E402


def envelope(text="[mail 09:00:00, sent 08:59:00, roster] Someone — Subject", **kw):
    base = {"event_id": "evt-1", "notification_text": text}
    base.update(kw)
    return base


class Spool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name) / "state"
        patcher = mock.patch.object(antigravity, "_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_deliver_appends_one_line_and_accepts(self):
        result = antigravity.deliver(envelope())
        self.assertTrue(result.ok, result)
        lines = antigravity.spool_path().read_text(encoding="utf-8").splitlines()
        self.assertEqual(["[mail 09:00:00, sent 08:59:00, roster] Someone — Subject"], lines)

    def test_two_events_are_two_lines_in_order(self):
        antigravity.deliver(envelope("first"))
        antigravity.deliver(envelope("second"))
        self.assertEqual(["first", "second"],
                         antigravity.spool_path().read_text().splitlines())

    def test_a_folded_subject_stays_one_record(self):
        antigravity.deliver(envelope("line one\r\n line two\nthree\r"))
        self.assertEqual(1, len(antigravity.spool_path().read_text().splitlines()))

    def test_no_text_is_config(self):
        result = antigravity.deliver(envelope(""))
        self.assertEqual("config", result.status)
        self.assertIn("evt-1", result.detail)
        self.assertFalse(antigravity.spool_path().exists())

    @unittest.skipIf(os.geteuid() == 0, "root can write anywhere")
    def test_unwritable_state_is_config_not_retry(self):
        self.state.mkdir(parents=True)
        self.state.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(self.state.chmod, stat.S_IRWXU)
        self.assertEqual("config", antigravity.check().status)
        result = antigravity.deliver(envelope())
        self.assertEqual("config", result.status)
        self.assertIn("Antigravity", result.detail)

    def test_check_accepts_a_writable_state_dir(self):
        result = antigravity.check()
        self.assertTrue(result.ok, result)
        self.assertEqual(str(antigravity.spool_path()), result.detail)

    def test_spool_is_not_a_dot_log(self):
        # rotate_logs.py rotates *.log, and the hook reads the spool by offset.
        self.assertFalse(antigravity.SPOOL_RELATIVE.endswith(".log"))
        self.assertNotEqual("session.spool", antigravity.SPOOL_RELATIVE)


class Binary(unittest.TestCase):
    def test_detect_follows_the_binary(self):
        with mock.patch.object(antigravity, "find_binary", lambda: None):
            self.assertFalse(antigravity.detect())
        with mock.patch.object(antigravity, "find_binary", lambda: "/usr/bin/agy"):
            self.assertTrue(antigravity.detect())

    def test_an_explicit_binary_that_is_missing_is_not_found(self):
        with mock.patch.dict(os.environ, {"AGY": "/nonexistent/agy"}):
            self.assertIsNone(antigravity.find_binary())

    def test_the_installer_path_is_found_without_path(self):
        with tempfile.TemporaryDirectory() as home:
            binary = pathlib.Path(home) / ".local" / "bin" / "agy"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n")
            binary.chmod(0o755)
            env = {"HOME": home, "PATH": "/nonexistent", "AGY": ""}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(str(binary), antigravity.find_binary())


class Registration(unittest.TestCase):
    def test_dispatch_knows_and_loads_it(self):
        self.assertIn("antigravity", dispatch.KNOWN_RUNTIMES)
        self.assertIn("antigravity", dispatch.available())
        self.assertIs(antigravity, dispatch.load_adapter("antigravity"))

    def test_capabilities_declare_replay_only(self):
        self.assertEqual([], capabilities.validate())
        spec = capabilities.as_dict()["adapters"]["antigravity"]
        self.assertEqual("replay-only", spec["derived_level"])
        self.assertEqual(["replay"], list(spec["static"]["delivery_modes"]))
        self.assertEqual("session_start_hook", spec["static"]["session_discovery"])

    def test_the_matrix_names_it(self):
        self.assertIn("Antigravity CLI (`antigravity`)", capabilities.markdown_table())


if __name__ == "__main__":
    unittest.main(verbosity=1)
