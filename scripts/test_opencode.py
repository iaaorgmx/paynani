#!/usr/bin/env python3
"""Contract tests for the OpenCode adapter, its session_start.py modes and plugin registration."""

import contextlib
import importlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "scripts"))

from adapters import claudecode, codex, opencode


def envelope(text="[mail 09:00:00, sent 08:59:00, roster] Someone - Subject", **kw):
    base = {"event_id": "imap:INBOX:42:7", "notification_text": text}
    base.update(kw)
    return base


class SpoolDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name) / "state"
        patcher = mock.patch.object(opencode, "_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def records(self):
        text = opencode.spool_path().read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def test_delivery_appends_one_json_line_and_is_accepted(self):
        result = opencode.deliver(envelope("first"))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(self.records(),
                         [{"event_id": "imap:INBOX:42:7", "notification_text": "first"}])

    def test_delivery_appends_rather_than_overwrites(self):
        opencode.deliver(envelope("first"))
        opencode.deliver(envelope("second", event_id="imap:INBOX:42:8"))
        self.assertEqual([r["notification_text"] for r in self.records()], ["first", "second"])

    def test_embedded_newlines_become_one_line(self):
        opencode.deliver(envelope("subject\r\nfolded\nagain\rend", event_id="id\n2"))
        text = opencode.spool_path().read_text(encoding="utf-8")
        self.assertEqual(len(text.splitlines()), 1)
        self.assertEqual(self.records()[0]["notification_text"], "subject folded again end")
        self.assertEqual(self.records()[0]["event_id"], "id 2")

    def test_unicode_survives(self):
        opencode.deliver(envelope("Julián: ¿Revisas el café? ☕"))
        self.assertEqual(self.records()[0]["notification_text"], "Julián: ¿Revisas el café? ☕")

    def test_missing_notification_text_is_a_config_fault(self):
        result = opencode.deliver({"event_id": "x"})
        self.assertEqual(result.status, "config")
        self.assertFalse(opencode.spool_path().exists())

    def test_missing_event_id_is_a_config_fault(self):
        result = opencode.deliver({"notification_text": "hello"})
        self.assertEqual(result.status, "config")
        self.assertFalse(opencode.spool_path().exists())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write anywhere")
    def test_unwritable_spool_is_a_config_fault(self):
        self.state.mkdir(parents=True)
        opencode.spool_path().write_text("", encoding="utf-8")
        opencode.spool_path().chmod(0o400)
        self.addCleanup(opencode.spool_path().chmod, 0o600)
        self.assertEqual(opencode.check().status, "config")
        self.assertEqual(opencode.deliver(envelope()).status, "config")

    def test_check_does_not_require_an_opencode_binary(self):
        with mock.patch.object(opencode, "find_binary", lambda: None):
            self.assertTrue(opencode.check().ok)

    def test_file_names_are_not_logs_and_not_shared(self):
        for name in (opencode.SPOOL_RELATIVE, opencode.OFFSET_RELATIVE):
            self.assertFalse(name.endswith(".log"), name)
        self.assertNotIn(opencode.SPOOL_RELATIVE, (codex.SPOOL_RELATIVE, claudecode.SPOOL_RELATIVE))
        self.assertNotEqual(opencode.OFFSET_RELATIVE, codex.OFFSET_RELATIVE)


class Detection(unittest.TestCase):
    def test_explicit_binary_wins_and_must_be_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = pathlib.Path(tmp) / "opencode"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            with mock.patch.dict(os.environ, {"OPENCODE": str(binary)}):
                self.assertEqual(opencode.find_binary(), str(binary))
                self.assertTrue(opencode.detect())
            binary.chmod(0o644)
            with mock.patch.dict(os.environ, {"OPENCODE": str(binary)}):
                self.assertIsNone(opencode.find_binary())

    def test_the_official_installer_location_is_a_candidate(self):
        self.assertIn("~/.opencode/bin/opencode", opencode.CANDIDATES)

    def test_a_config_directory_alone_is_not_opencode(self):
        with tempfile.TemporaryDirectory() as home:
            (pathlib.Path(home) / ".config" / "opencode").mkdir(parents=True)
            env = {"HOME": home, "PATH": "/nonexistent", "OPENCODE": ""}
            with mock.patch.dict(os.environ, env):
                self.assertFalse(opencode.detect())

    def test_the_dispatcher_knows_the_runtime(self):
        import dispatch
        self.assertIn("opencode", dispatch.KNOWN_RUNTIMES)


class SessionStartModes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        import session_start as ss
        self.ss = ss
        self.spool = self.state / "opencode.spool"
        self.offset = self.state / "opencode.offset"
        self.lock = self.state / "opencode.watch.lock.d"
        for attr, value in (("OPENCODE_SPOOL", self.spool), ("OPENCODE_OFFSET", self.offset),
                            ("OPENCODE_LOCK", self.lock),
                            ("JOURNAL", self.state / "events.jsonl")):
            patcher = mock.patch.object(ss, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_mode(self, *args, **stubs):
        defaults = {
            "unit_state": lambda unit: "active",
            "dispatcher_faults": lambda: [],
        }
        defaults.update(stubs)
        for name, value in defaults.items():
            patcher = mock.patch.object(self.ss, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        buf = io.StringIO()
        with mock.patch.object(self.ss.sys, "argv", ["session_start.py", *args]):
            with contextlib.redirect_stdout(buf):
                code = self.ss.main()
        raw = buf.getvalue()
        return code, (json.loads(raw) if raw.strip() else None)

    def spool_event(self, event_id="imap:INBOX:42:7", text="[mail 09:00:00, roster] Julian - Hola"):
        line = json.dumps({"event_id": event_id, "notification_text": text},
                          ensure_ascii=False) + "\n"
        with open(self.spool, "a", encoding="utf-8") as handle:
            handle.write(line)

    def test_nothing_pending_is_an_empty_prompt(self):
        code, payload = self.run_mode("--opencode-pending")
        self.assertEqual(code, 0)
        self.assertEqual(payload["prompt"], "")
        self.assertEqual(payload["count"], 0)

    def test_pending_names_event_ids_and_does_not_acknowledge(self):
        self.spool_event("imap:INBOX:42:7", "[mail] Julian - SECRET BODY LINE")
        self.spool_event("imap:INBOX:42:8")
        code, payload = self.run_mode("--opencode-pending")
        self.assertEqual(code, 0)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["through"], self.spool.stat().st_size)
        self.assertIn("imap:INBOX:42:7", payload["prompt"])
        self.assertIn("imap:INBOX:42:8", payload["prompt"])
        self.assertNotIn("SECRET BODY LINE", payload["prompt"])
        self.assertIn("roster", payload["prompt"])
        self.assertFalse(self.offset.exists())

    def test_pending_is_capped_and_through_stops_at_the_cap(self):
        for uid in range(self.ss.MAX_REPLAY + 3):
            self.spool_event(f"imap:INBOX:42:{uid}")
        _, payload = self.run_mode("--opencode-pending")
        self.assertTrue(payload["capped"])
        self.assertEqual(payload["count"], self.ss.MAX_REPLAY)
        self.assertLess(payload["through"], self.spool.stat().st_size)

    def test_status_is_only_computed_when_asked(self):
        calls = []
        def unit_state(unit):
            calls.append(unit)
            return "down"
        _, quiet = self.run_mode("--opencode-pending", unit_state=unit_state)
        self.assertEqual(quiet["system"], "")
        self.assertEqual(calls, [])
        _, loud = self.run_mode("--opencode-pending", "--status", unit_state=unit_state)
        self.assertIn("DOWN", loud["system"])

    def test_ack_moves_the_offset_forward_only(self):
        self.spool_event()
        size = self.spool.stat().st_size
        code, payload = self.run_mode("--opencode-ack", str(size))
        self.assertEqual((code, payload), (0, {"offset": size}))
        code, payload = self.run_mode("--opencode-ack", "0")
        self.assertEqual((code, payload), (0, {"offset": size}))
        self.assertEqual(self.offset.read_text(encoding="utf-8"), str(size))

    def test_ack_refuses_an_offset_past_the_spool_or_garbage(self):
        self.spool_event()
        for value in (str(self.spool.stat().st_size + 1), "-1", "twelve"):
            code, payload = self.run_mode("--opencode-ack", value)
            self.assertEqual((code, payload), (2, None), value)
        self.assertFalse(self.offset.exists())

    def test_acknowledged_mail_is_not_pending_again(self):
        self.spool_event("imap:INBOX:42:7")
        _, first = self.run_mode("--opencode-pending")
        self.run_mode("--opencode-ack", str(first["through"]))
        self.spool_event("imap:INBOX:42:8")
        _, second = self.run_mode("--opencode-pending")
        self.assertNotIn("imap:INBOX:42:7", second["prompt"])
        self.assertIn("imap:INBOX:42:8", second["prompt"])

    def test_the_first_claim_wins_and_a_second_live_process_does_not(self):
        me = os.getpid()
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (other.kill(), other.wait()))
        _, first = self.run_mode("--opencode-claim", str(me))
        self.assertEqual(first, {"owner": True, "holder": me})
        _, again = self.run_mode("--opencode-claim", str(me))
        self.assertTrue(again["owner"])
        _, second = self.run_mode("--opencode-claim", str(other.pid))
        self.assertEqual(second, {"owner": False, "holder": me})

    def test_a_dead_owner_is_taken_over(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        _, first = self.run_mode("--opencode-claim", str(dead.pid))
        self.assertTrue(first["owner"])
        _, taken = self.run_mode("--opencode-claim", str(os.getpid()))
        self.assertEqual(taken, {"owner": True, "holder": os.getpid()})
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["opencode.watch.lock.d"])

    def test_a_lock_still_being_claimed_is_not_taken_over(self):
        self.lock.mkdir()
        _, payload = self.run_mode("--opencode-claim", str(os.getpid()))
        self.assertFalse(payload["owner"])
        old = time.time() - self.ss.OPENCODE_LOCK_GRACE - 5
        os.utime(self.lock, (old, old))
        _, payload = self.run_mode("--opencode-claim", str(os.getpid()))
        self.assertTrue(payload["owner"])

    def test_release_only_removes_the_callers_lock(self):
        me = os.getpid()
        self.run_mode("--opencode-claim", str(me))
        _, payload = self.run_mode("--opencode-release", str(me + 1))
        self.assertEqual(payload, {"released": False})
        self.assertTrue(self.lock.exists())
        _, payload = self.run_mode("--opencode-release", str(me))
        self.assertEqual(payload, {"released": True})
        self.assertFalse(self.lock.exists())

    def test_unknown_mode_prints_nothing(self):
        code, payload = self.run_mode("--opencode-bogus")
        self.assertEqual((code, payload), (2, None))

    def test_spool_paths_are_the_opencode_pair(self):
        self.assertEqual(self.ss.spool_paths("opencode"), (self.spool, self.offset))


class PluginRegistration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = pathlib.Path(self.tmp.name) / "plugins" / "paynani.js"
        self.tool = importlib.import_module("opencode_plugin")

    def run_tool(self, *args, env=None):
        full = dict(os.environ)
        full.update(env or {})
        return subprocess.run([sys.executable, str(ROOT / "scripts/opencode_plugin.py"), *args],
                              capture_output=True, text=True, env=full, timeout=30)

    def test_install_is_idempotent_and_check_agrees(self):
        self.assertEqual(self.run_tool("--check", "--target", str(self.target)).returncode, 1)
        first = self.run_tool("--install", "--target", str(self.target))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn(str(self.target), first.stdout)
        second = self.run_tool("--install", "--target", str(self.target))
        self.assertIn("nothing to do", second.stdout)
        self.assertEqual(self.run_tool("--check", "--target", str(self.target)).returncode, 0)

    def test_the_generated_file_exports_exactly_the_plugin(self):
        text = self.tool.content()
        exports = [line for line in text.splitlines() if line.startswith("export")]
        self.assertEqual(len(exports), 1)
        self.assertIn("{ PaynaniPlugin }", exports[0])
        self.assertIn(json.dumps(str(ROOT / "harness/opencode/paynani.js")), exports[0])

    def test_a_different_file_is_backed_up_before_it_is_replaced(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("// mine\n", encoding="utf-8")
        result = self.run_tool("--install", "--target", str(self.target))
        self.assertEqual(result.returncode, 0, result.stderr)
        backup = self.target.with_name("paynani.js.paynani.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), "// mine\n")

    def test_uninstall_leaves_a_file_paynani_did_not_write(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("// mine\n", encoding="utf-8")
        result = self.run_tool("--uninstall", "--target", str(self.target))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.target.exists())

    def test_uninstall_removes_its_own_file(self):
        self.run_tool("--install", "--target", str(self.target))
        result = self.run_tool("--uninstall", "--target", str(self.target))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())

    def test_default_target_follows_opencode_config_dir(self):
        with mock.patch.dict(os.environ, {"OPENCODE_CONFIG_DIR": "/srv/oc"}):
            self.assertEqual(self.tool.default_target(), pathlib.Path("/srv/oc/plugins/paynani.js"))
        with mock.patch.dict(os.environ, {"OPENCODE_CONFIG_DIR": "", "XDG_CONFIG_HOME": "/srv/xdg"}):
            self.assertEqual(self.tool.default_target(),
                             pathlib.Path("/srv/xdg/opencode/plugins/paynani.js"))

    def test_print_changes_nothing(self):
        result = self.run_tool("--print", "--target", str(self.target))
        self.assertEqual(result.returncode, 0)
        self.assertIn("PaynaniPlugin", result.stdout)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
