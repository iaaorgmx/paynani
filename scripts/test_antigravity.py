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

    def test_capabilities_declare_replay_only_with_opt_in_agent_runs(self):
        self.assertEqual([], capabilities.validate())
        spec = capabilities.as_dict()["adapters"]["antigravity"]
        self.assertEqual("replay-only", spec["derived_level"])
        self.assertEqual(["replay"], list(spec["static"]["delivery_modes"]))
        self.assertEqual("session_start_hook", spec["static"]["session_discovery"])
        self.assertEqual("opt_in", spec["static"]["starts_agent_run"])

    def test_the_matrix_names_it(self):
        self.assertIn("Antigravity CLI (`antigravity`)", capabilities.markdown_table())


FAKE_AGY = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_AGY_ARGS"], "w") as f:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "path": os.environ.get("PATH", "")}, f)
mode = os.environ.get("FAKE_AGY_MODE", "success")
if mode == "success":
    print(json.dumps({"conversation_id": "c-1", "status": "SUCCESS", "response": "ok\n", "num_turns": 1}))
elif mode == "timeout":
    print(json.dumps({"conversation_id": "c-2", "status": "ERROR", "response": "",
                      "error": "print timeout after 5s with the turn still in progress; the response is partial",
                      "finished_reason": "print_timeout"}))
    print("AGY_ERROR: " + json.dumps({"short_error": "print timeout", "status": "DEADLINE_EXCEEDED",
                                       "retryable": False, "reason": "print_timeout"}), file=sys.stderr)
    sys.exit(3)
elif mode == "login":
    print("error: secret keyring is locked", file=sys.stderr)
    sys.exit(1)
elif mode == "permission":
    print(json.dumps({"conversation_id": "c-3", "status": "SUCCESS", "response": "could not run it\n"}))
    print("permission for command(rm -rf x) denied by the user settings", file=sys.stderr)
elif mode == "garbage":
    print("panic: something went wrong", file=sys.stderr)
    sys.exit(2)
'''


class AgentMode(unittest.TestCase):
    """PAYNANI_ANTIGRAVITY_MODE=agent runs `agy -p` per event (#749 F2, FR-9/FR-10)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.state = base / "state"
        self.clone = base / "clone"
        self.clone.mkdir()
        self.agy = base / "agy"
        self.agy.write_text(FAKE_AGY.replace("/usr/bin/env python3", sys.executable, 1), encoding="utf-8")
        self.agy.chmod(0o755)
        self.args = base / "args.json"
        for patcher in (mock.patch.object(antigravity, "_state_dir", lambda: self.state),
                        mock.patch.object(antigravity, "_repo_root", lambda: self.clone),
                        mock.patch.dict(os.environ, {"AGY": str(self.agy), "FAKE_AGY_ARGS": str(self.args),
                                                     "PAYNANI_ANTIGRAVITY_MODE": "agent",
                                                     "PAYNANI_ANTIGRAVITY_TIMEOUT": "5"})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def deliver(self, mode="success"):
        with mock.patch.dict(os.environ, {"FAKE_AGY_MODE": mode}):
            return antigravity.deliver(envelope())

    def test_success_runs_agy_p_in_the_clone_and_records_it(self):
        result = self.deliver("success")
        self.assertTrue(result.ok, result)
        self.assertIn("completed", result.detail)
        call = __import__("json").loads(self.args.read_text())
        self.assertEqual(str(self.clone), call["cwd"])
        argv = call["argv"]
        self.assertEqual("-p", argv[0])
        self.assertIn("Someone — Subject", argv[1])
        self.assertIn("evt-1", argv[1])
        self.assertEqual(["--output-format", "json", "--print-timeout", "5s"], argv[2:])
        record = antigravity.last_agent_run()
        self.assertTrue(record["ok"])
        self.assertEqual("c-1", record["conversation_id"])
        self.assertEqual("evt-1", record["event_id"])
        self.assertEqual(0o600, stat.S_IMODE(antigravity.status_path().stat().st_mode))

    def test_never_skips_permissions(self):
        self.deliver("success")
        argv = __import__("json").loads(self.args.read_text())["argv"]
        self.assertNotIn("--dangerously-skip-permissions", argv)

    def test_the_spool_is_written_either_way(self):
        for mode in ("success", "timeout", "login", "permission", "garbage"):
            self.deliver(mode)
        self.assertEqual(5, len(antigravity.spool_path().read_text().splitlines()))

    def test_a_failed_run_is_still_accepted_and_named(self):
        cases = {"timeout": "timeout", "login": "login", "permission": "permission", "garbage": "run"}
        for mode, problem in cases.items():
            with self.subTest(mode=mode):
                result = self.deliver(mode)
                # Accepted: the line is in the spool, and a retry would append it again.
                self.assertTrue(result.ok, result)
                self.assertIn(f"agy -p failed ({problem})", result.detail)
                record = antigravity.last_agent_run()
                self.assertFalse(record["ok"])
                self.assertEqual(problem, record["problem"])

    def test_success_with_a_refused_permission_is_not_success(self):
        self.deliver("permission")
        record = antigravity.last_agent_run()
        self.assertEqual("SUCCESS", record["status"])
        self.assertFalse(record["ok"])
        self.assertIn("denied", record["detail"])

    def test_the_timeout_reason_comes_from_agy(self):
        self.deliver("timeout")
        record = antigravity.last_agent_run()
        self.assertEqual("print_timeout", record["finished_reason"])
        self.assertEqual(3, record["exit"])

    def test_the_record_keeps_no_prompt_or_reply(self):
        self.deliver("success")
        text = antigravity.status_path().read_text()
        self.assertNotIn("Subject", text)
        self.assertNotIn("ok\\n", text)

    def test_mode_off_runs_nothing(self):
        with mock.patch.dict(os.environ, {"PAYNANI_ANTIGRAVITY_MODE": ""}):
            result = antigravity.deliver(envelope())
        self.assertTrue(result.ok, result)
        self.assertFalse(self.args.exists())
        self.assertIsNone(antigravity.last_agent_run())

    def test_no_binary_is_recorded_not_raised(self):
        with mock.patch.object(antigravity, "find_binary", lambda: None):
            result = antigravity.deliver(envelope())
        self.assertTrue(result.ok, result)
        self.assertEqual("run", antigravity.last_agent_run()["problem"])

    def test_the_run_gets_the_user_bin_folders_on_path(self):
        # #749 F2 field test: under systemd the agent's send.sh could not find
        # himalaya in ~/.local/bin, and the turn timed out.
        home = pathlib.Path(self.tmp.name) / "home"
        (home / ".local/bin").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": "/usr/bin:/bin"}):
            self.deliver("success")
        path = __import__("json").loads(self.args.read_text())["path"].split(os.pathsep)
        self.assertEqual(["/usr/bin", "/bin"], path[:2])
        self.assertIn(str(home / ".local/bin"), path)
        self.assertIn(str(self.agy.parent), path)

    def test_run_env_keeps_order_and_skips_missing_folders(self):
        home = pathlib.Path(self.tmp.name) / "home2"
        (home / ".local/bin").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"HOME": str(home),
                                          "PATH": os.pathsep.join([str(home / ".local/bin"), "/usr/bin"])}):
            path = antigravity.run_env().get("PATH").split(os.pathsep)
        self.assertEqual([str(home / ".local/bin"), "/usr/bin"], path)

    def test_a_bad_timeout_falls_back(self):
        for value in ("", "x", "0", "-4"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"PAYNANI_ANTIGRAVITY_TIMEOUT": value}):
                self.assertEqual(antigravity.DEFAULT_TIMEOUT, antigravity.run_timeout())


class Doctor(unittest.TestCase):
    """`paynani doctor` reads the last run (#749 FR-10)."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from paynani_lib import diagnostics
        self.diagnostics = diagnostics
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = pathlib.Path(self.tmp.name)
        patcher = mock.patch.object(antigravity, "_state_dir", lambda: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, mode=""):
        with mock.patch.dict(os.environ, {"PAYNANI_ANTIGRAVITY_MODE": mode}):
            return self.diagnostics._observation_check("last_agent_run", {"runtime": {"selected": "antigravity"}})

    def test_mode_off_is_ok(self):
        self.assertEqual("ok", self.check()["status"])

    def test_mode_on_without_a_run_is_unknown(self):
        self.assertEqual("unknown", self.check("agent")["status"])

    def test_a_login_failure_is_a_warning_with_the_fix(self):
        antigravity._note_run({"event_id": "e", "at": "t", "ok": False, "problem": "login",
                               "detail": "secret keyring is locked"})
        result = self.check("agent")
        self.assertEqual("warning", result["status"])
        self.assertIn("Google login", result["summary"])
        self.assertIn("GEMINI_API_KEY", result["next_command"])

    def test_a_good_run_is_ok(self):
        antigravity._note_run({"event_id": "e", "at": "t", "ok": True, "problem": "", "detail": ""})
        self.assertEqual("ok", self.check("agent")["status"])

    def test_mode_off_after_an_old_failure_is_ok(self):
        # Iris's review of #761: with the mode off there is nothing to fix.
        antigravity._note_run({"event_id": "e", "at": "t", "ok": False, "problem": "login",
                               "detail": "secret keyring is locked"})
        result = self.check("")
        self.assertEqual("ok", result["status"])
        self.assertFalse(result["facts"]["last_agent_run"]["ok"])


class Classify(unittest.TestCase):
    """classify_run() on what agy prints (#749 FR-10)."""

    GOOD = '{"conversation_id": "c", "status": "SUCCESS", "response": "ok"}'

    def test_a_good_run_with_login_words_in_its_log_is_still_good(self):
        # Iris's review of #761: agy writes log lines to stderr.
        for stderr in ("I1108 keyring: using libsecret backend\n",
                       "debug: telemetry not logged in, skipping\n",
                       "warning: authentication required for an optional plugin\n"):
            with self.subTest(stderr=stderr):
                ok, problem, _, _ = antigravity.classify_run(0, self.GOOD, stderr)
                self.assertEqual((True, ""), (ok, problem))

    def test_a_good_run_with_a_refused_permission_is_not_good(self):
        ok, problem, _, _ = antigravity.classify_run(0, self.GOOD, "permission for command(x) denied\n")
        self.assertEqual((False, "permission"), (ok, problem))

    def test_a_failed_run_with_a_locked_keyring_is_login(self):
        ok, problem, _, _ = antigravity.classify_run(1, "", "error: secret keyring is locked\n")
        self.assertEqual((False, "login"), (ok, problem))

    def test_the_bare_word_keyring_is_not_login(self):
        ok, problem, _, _ = antigravity.classify_run(1, "", "keyring backend: libsecret\npanic: boom\n")
        self.assertEqual((False, "run"), (ok, problem))


if __name__ == "__main__":
    unittest.main(verbosity=1)
