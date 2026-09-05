#!/usr/bin/env python3
"""Contract tests for the OpenAI Codex adapter."""

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from adapters import codex, claudecode


def envelope(text="[mail 09:00:00, sent 08:59:00, roster] Someone — Subject", **kw):
    base = {"event_id": "evt-1", "notification_text": text}
    base.update(kw)
    return base


class SpoolDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self.tmp.name) / "state"
        patcher = mock.patch.object(codex, "_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def spool_text(self):
        return codex.spool_path().read_text(encoding="utf-8")

    def register_session(self, session_id="thread-1"):
        codex.session_path().parent.mkdir(parents=True, exist_ok=True)
        codex.session_path().write_text(session_id + "\n", encoding="utf-8")

    def queue_result(self, returncode=0, stdout="", stderr=""):
        import subprocess
        return subprocess.CompletedProcess(["codex"], returncode, stdout=stdout, stderr=stderr)

    def test_delivery_appends_one_line_and_is_accepted(self):
        result = codex.deliver(envelope("first"))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(self.spool_text(), "first\n")

    def test_delivery_appends_rather_than_overwrites(self):
        codex.deliver(envelope("first"))
        codex.deliver(envelope("second"))
        self.assertEqual(self.spool_text(), "first\nsecond\n")

    def test_offsets_are_stable_across_deliveries(self):
        codex.deliver(envelope("first"))
        prefix = self.spool_text()
        codex.deliver(envelope("second"))
        self.assertTrue(self.spool_text().startswith(prefix))

    def test_embedded_newlines_do_not_become_two_events(self):
        codex.deliver(envelope("has\nnewline"))
        self.assertEqual(len(self.spool_text().splitlines()), 1)

    def test_trailing_newline_is_not_doubled(self):
        codex.deliver(envelope("already ends\n"))
        self.assertEqual(self.spool_text(), "already ends\n")

    def test_unicode_survives_the_round_trip(self):
        codex.deliver(envelope("ñ á ¿de veras?"))
        self.assertIn("ñ á ¿de veras?", self.spool_text())

    def test_missing_text_is_config_not_retry(self):
        result = codex.deliver(envelope(text=""))
        self.assertEqual(result.status, "config")

    def test_missing_event_id_is_config_not_queued(self):
        result = codex.deliver(envelope("text", event_id=""))
        self.assertEqual(result.status, "config")
        self.assertFalse(codex.spool_path().exists())

    def test_unwritable_state_is_config_not_retry(self):
        self.state.mkdir(parents=True)
        self.state.chmod(0o500)
        self.addCleanup(self.state.chmod, 0o700)
        result = codex.deliver(envelope("nope"))
        self.assertEqual(result.status, "config")

    def test_check_does_not_require_a_codex_binary(self):
        with mock.patch.object(codex, "find_binary", lambda: None):
            result = codex.check()
        self.assertTrue(result.ok, result.detail)

    def test_live_queue_acceptance_acknowledges_the_spool_offset(self):
        self.register_session()
        with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
            with mock.patch.object(codex.subprocess, "run",
                                   lambda *a, **kw: self.queue_result(0)):
                result = codex.deliver(envelope("queued", event_id="imap:INBOX:42:7"))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(str(codex.spool_path().stat().st_size),
                         codex.offset_path().read_text(encoding="utf-8"))

    def test_live_queue_message_names_only_the_event_id(self):
        self.register_session()
        calls = []

        def run(*args, **kwargs):
            calls.append(args[0])
            return self.queue_result(0)

        with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
            with mock.patch.object(codex.subprocess, "run", run):
                codex.deliver(envelope("BODY MUST NOT BE QUEUED", event_id="evt-777"))
        command = calls[0]
        message = command[command.index("--message") + 1]
        self.assertIn("evt-777", message)
        self.assertNotIn("BODY MUST NOT BE QUEUED", message)

    def test_queue_usage_error_is_config(self):
        self.register_session()
        with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
            with mock.patch.object(codex.subprocess, "run",
                                   lambda *a, **kw: self.queue_result(2, stderr="usage")):
                result = codex.deliver(envelope("queued"))
        self.assertEqual(result.status, "config")

    def test_queue_no_active_session_falls_back_to_spool(self):
        self.register_session()
        with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
            with mock.patch.object(codex.subprocess, "run",
                                   lambda *a, **kw: self.queue_result(
                                       1, stderr="Error: No active session found matching 'x'.")):
                result = codex.deliver(envelope("queued"))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(self.spool_text(), "queued\n")
        self.assertFalse(codex.offset_path().exists())
        self.assertFalse(codex.session_path().exists())

    def test_queue_readonly_database_is_config(self):
        self.register_session()
        with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
            with mock.patch.object(codex.subprocess, "run",
                                   lambda *a, **kw: self.queue_result(
                                       1, stderr="attempt to write a readonly database")):
                result = codex.deliver(envelope("queued"))
        self.assertEqual(result.status, "config")

    def test_agent_mode_is_fallback_when_no_live_session_exists(self):
        calls = []

        def run(*args, **kwargs):
            calls.append(args[0])
            return self.queue_result(0)

        env = {"PAYNANI_CODEX_MODE": "agent"}
        with mock.patch.dict(os.environ, env):
            with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
                with mock.patch.object(codex.subprocess, "run", run):
                    result = codex.deliver(envelope("agent", event_id="evt-agent"))
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(calls[0][:3], ["/usr/bin/codex", "exec", "--cd"])
        self.assertEqual(str(codex.spool_path().stat().st_size),
                         codex.offset_path().read_text(encoding="utf-8"))

    def test_failed_agent_mode_still_accepts_the_spooled_event(self):
        env = {"PAYNANI_CODEX_MODE": "agent"}
        with mock.patch.dict(os.environ, env):
            with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
                with mock.patch.object(codex.subprocess, "run",
                                       lambda *a, **kw: self.queue_result(1, stderr="boom")):
                    result = codex.deliver(envelope("agent"))
        self.assertTrue(result.ok, result.detail)
        self.assertIn("agent run failed", result.detail)
        self.assertFalse(codex.offset_path().exists())


class SpoolNaming(unittest.TestCase):
    def test_spool_is_not_a_dot_log(self):
        self.assertFalse(codex.SPOOL_RELATIVE.endswith(".log"))

    def test_codex_and_claude_spools_are_distinct(self):
        self.assertNotEqual(codex.SPOOL_RELATIVE, claudecode.SPOOL_RELATIVE)


class Detection(unittest.TestCase):
    def test_detect_follows_the_binary_not_the_directory(self):
        with mock.patch.object(codex, "find_binary", lambda: None):
            self.assertFalse(codex.detect())
        with mock.patch.object(codex, "find_binary", lambda: "/usr/bin/codex"):
            self.assertTrue(codex.detect())

    def test_explicit_override_wins(self):
        with mock.patch.dict(os.environ, {"CODEX": "/nonexistent/codex"}):
            self.assertIsNone(codex.find_binary())


class SpoolReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        sys.path.insert(0, str(ROOT / "harness"))
        import session_start as ss
        self.ss = ss
        self.spool = self.state / "codex.spool"
        self.offset = self.state / "codex.offset"
        self.session = self.state / "codex.session"
        for attr, value in (("CODEX_SPOOL", self.spool), ("CODEX_OFFSET", self.offset),
                            ("CODEX_SESSION", self.session)):
            patcher = mock.patch.object(ss, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _emit(self, stdin_text="", argv=None, **stubs):
        import contextlib, io, json as _json
        ss = self.ss
        defaults = {
            "unit_state": lambda unit: "active",
            "dispatcher_faults": lambda: [],
            "read_backlog": lambda: ([], False),
            "selected_runtime": lambda: "codex",
            "version_line": lambda: None,
            "local_code_line": lambda: "",
        }
        defaults.update(stubs)
        patchers = [mock.patch.object(ss, name, value) for name, value in defaults.items()]
        patchers.append(mock.patch.object(ss.sys, "stdin", io.StringIO(stdin_text)))
        patchers.append(mock.patch.object(ss.sys, "argv", argv or ["session_start.py"]))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ss.main()
        raw = buf.getvalue()
        return raw, _json.loads(raw) if raw.strip() else None

    def test_a_healthy_host_emits_no_null_system_message(self):
        raw, payload = self._emit()
        self.assertNotIn('"systemMessage": null', raw)
        self.assertNotIn("systemMessage", payload)
        self.assertIn("additionalContext", payload["hookSpecificOutput"])

    def test_session_start_registers_session_id_from_stdin(self):
        self._emit(stdin_text='{"session_id":"thread-123","hook_event_name":"SessionStart"}')
        self.assertEqual(self.session.read_text(encoding="utf-8"), "thread-123\n")

    def test_empty_stdin_does_not_break_or_register_a_session(self):
        raw, payload = self._emit(stdin_text="")
        self.assertTrue(raw.strip())
        self.assertIn("hookSpecificOutput", payload)
        self.assertFalse(self.session.exists())

    def test_malformed_stdin_does_not_break_or_register_a_session(self):
        raw, payload = self._emit(stdin_text="{not json")
        self.assertTrue(raw.strip())
        self.assertIn("hookSpecificOutput", payload)
        self.assertFalse(self.session.exists())

    def test_session_end_removes_the_registered_session(self):
        self.session.parent.mkdir(parents=True, exist_ok=True)
        self.session.write_text("thread-123\n", encoding="utf-8")
        raw, _ = self._emit(argv=["session_start.py", "--session-end"])
        self.assertEqual(raw, "")
        self.assertFalse(self.session.exists())

    def test_everything_is_replayed_from_a_cold_start(self):
        self.spool.write_text("one\ntwo\n", encoding="utf-8")
        lines, capped, through = self.ss.read_spool_backlog(self.spool, self.offset)
        self.assertEqual(lines, ["one", "two"])
        self.assertFalse(capped)
        self.assertEqual(through, self.spool.stat().st_size)

    def test_only_what_is_past_the_offset_is_replayed(self):
        self.spool.write_text("one\ntwo\n", encoding="utf-8")
        self.offset.write_text("4", encoding="utf-8")
        lines, _, _ = self.ss.read_spool_backlog(self.spool, self.offset)
        self.assertEqual(lines, ["two"])

    def test_codex_replay_acknowledges_after_output(self):
        self.spool.write_text("one\n", encoding="utf-8")
        self._emit()
        self.assertEqual(str(self.spool.stat().st_size), self.offset.read_text(encoding="utf-8"))

    def test_a_truncated_spool_replays_rather_than_skips(self):
        self.spool.write_text("fresh\n", encoding="utf-8")
        self.offset.write_text("9999", encoding="utf-8")
        lines, _, _ = self.ss.read_spool_backlog(self.spool, self.offset)
        self.assertEqual(lines, ["fresh"])

    def test_replay_is_capped_without_acknowledging_unshown_mail(self):
        count = self.ss.MAX_REPLAY + 5
        self.spool.write_text("".join(f"line{i}\n" for i in range(count)), encoding="utf-8")
        lines, capped, through = self.ss.read_spool_backlog(self.spool, self.offset)
        self.assertEqual(len(lines), self.ss.MAX_REPLAY)
        self.assertEqual(lines[0], "line0")
        self.assertEqual(lines[-1], f"line{self.ss.MAX_REPLAY - 1}")
        self.assertTrue(capped)
        self.assertLess(through, self.spool.stat().st_size)

    def test_acknowledged_capped_replay_resumes_at_the_next_unshown_line(self):
        count = self.ss.MAX_REPLAY + 5
        self.spool.write_text("".join(f"line{i}\n" for i in range(count)), encoding="utf-8")
        self._emit()
        lines, capped, _ = self.ss.read_spool_backlog(self.spool, self.offset)
        self.assertEqual(lines, [f"line{i}" for i in range(self.ss.MAX_REPLAY, count)])
        self.assertFalse(capped)

    def test_oversized_context_is_not_acknowledged(self):
        self.spool.write_text("one\n", encoding="utf-8")
        with mock.patch.object(self.ss, "CODEX_ACK_CONTEXT_LIMIT", 1):
            self._emit()
        self.assertFalse(self.offset.exists())

    def test_unknown_service_status_is_not_reported_as_down(self):
        self.spool.write_text("one\n", encoding="utf-8")
        _, payload = self._emit(unit_state=lambda unit: "unknown")
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("STATUS UNKNOWN", context)
        self.assertNotIn("IS DOWN", context)
        self.assertEqual(payload["systemMessage"],
                         "Mail service status unknown — could not query service manager")

    def test_systemd_bus_failure_is_unknown_not_down(self):
        import subprocess
        completed = subprocess.CompletedProcess(
            ["systemctl"], 1, stdout="", stderr="Failed to connect to bus: Operation not permitted")
        with mock.patch.object(self.ss.platform, "system", lambda: "Linux"):
            with mock.patch.object(self.ss.subprocess, "run", lambda *a, **kw: completed):
                self.assertEqual(self.ss.unit_state("paynani-idle.service"), "unknown")

    def test_codex_queue_delivery_is_said(self):
        self.spool.write_text("one\n", encoding="utf-8")
        _, payload = self._emit()
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("codex queue", context)


class HookRegistration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = pathlib.Path(self.tmp.name) / "hooks.json"
        sys.path.insert(0, str(ROOT / "scripts"))
        import importlib
        self.hook = importlib.import_module("codex_hook")

    def run_install(self):
        return self.hook.install(self.settings)

    def load(self):
        import json
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def commands(self, event):
        return [h["command"]
                for entry in self.load()["hooks"].get(event, [])
                for h in entry["hooks"]]

    def test_creates_the_file_when_absent(self):
        self.run_install()
        self.assertTrue(self.hook.already_registered(self.load()))

    def test_unrelated_hooks_survive(self):
        import json
        self.settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.py"}]}]},
        }), encoding="utf-8")
        self.run_install()
        after = self.load()
        self.assertEqual(after["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "mine.py")

    def test_an_existing_session_start_hook_is_kept(self):
        import json
        self.settings.write_text(json.dumps({
            "hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "theirs.py"}]}]},
        }), encoding="utf-8")
        self.run_install()
        commands = self.commands("SessionStart")
        self.assertIn("theirs.py", commands)
        self.assertIn(self.hook.start_command(), commands)
        self.assertEqual(len(commands), 2)
        self.assertEqual(self.commands("SessionEnd"), [self.hook.end_command()])

    def test_installing_twice_does_not_duplicate(self):
        self.run_install()
        self.run_install()
        self.assertEqual(self.commands("SessionStart"), [self.hook.start_command()])
        self.assertEqual(self.commands("SessionEnd"), [self.hook.end_command()])

    def test_fragments_use_codex_hook_shapes(self):
        self.run_install()
        entry = self.load()["hooks"]["SessionStart"][0]
        hook = entry["hooks"][0]
        self.assertEqual(entry["matcher"], self.hook.START_MATCHER)
        self.assertEqual(hook["additionalContextLimit"], self.hook.ADDITIONAL_CONTEXT_LIMIT)
        end_entry = self.load()["hooks"]["SessionEnd"][0]
        end_hook = end_entry["hooks"][0]
        self.assertEqual(end_entry["matcher"], self.hook.END_MATCHER)
        self.assertNotIn("additionalContextLimit", end_hook)
        self.assertIn("--session-end", end_hook["command"])

    def test_an_existing_file_is_backed_up(self):
        self.settings.write_text('{"theme": "dark"}', encoding="utf-8")
        self.run_install()
        self.assertTrue(self.settings.with_suffix(".json.paynani.bak").is_file())

    def test_unparseable_settings_are_refused_not_repaired(self):
        self.settings.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_install()
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{ not json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
