#!/usr/bin/env python3
"""Tests for scripts/antigravity_hook.py (PRD #749, T3, FR-3 and FR-12).

Every test works on a hooks.json inside a temporary directory, and the command-line
tests also run with HOME pointing there, so the real ~/.gemini is never read or written.
"""

import importlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "antigravity_hook.py"
sys.path.insert(0, str(ROOT / "scripts"))
hook = importlib.import_module("antigravity_hook")

THEIRS = {
    "safety-gate": {"PreToolUse": [{"matcher": "run_command", "hooks": [{"type": "command", "command": "gate.sh"}]}]},
    "session-init": {"SessionStart": [{"type": "command", "command": "init.sh", "timeout": 5}]},
    "reminder": {"enabled": False, "PreInvocation": [{"command": "remind.sh"}]},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.settings = self.home / ".gemini" / "config" / "hooks.json"

    def put(self, data):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data)
        self.settings.write_text(text, encoding="utf-8")

    def load(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def cli(self, *args):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=30)


class Shape(Base):
    def test_block_is_the_documented_agy_shape(self):
        block = hook.block()
        self.assertEqual(list(block), ["SessionStart", "PreInvocation"])
        for event in hook.EVENTS:
            self.assertEqual(block[event], [{"type": "command", "command": hook.command(), "timeout": 10}])
            self.assertNotIn("matcher", block[event][0])

    def test_command_runs_session_start_of_this_clone_with_the_flag(self):
        self.assertEqual(hook.command(), f"python3 {ROOT / 'harness' / 'session_start.py'} --antigravity"
                         if " " not in str(ROOT) else hook.command())
        self.assertTrue(hook.command().endswith(" --antigravity"))
        self.assertIn(str(ROOT / "harness" / "session_start.py"), hook.command().replace("'", ""))

    def test_a_path_with_spaces_is_quoted_for_sh(self):
        old = hook.HOOK
        try:
            hook.HOOK = pathlib.Path("/tmp/my clone/harness/session_start.py")
            self.assertEqual(hook.command(), "python3 '/tmp/my clone/harness/session_start.py' --antigravity")
        finally:
            hook.HOOK = old

    def test_default_path_is_the_global_hooks_file(self):
        self.assertEqual(hook.SETTINGS, pathlib.Path.home() / ".gemini" / "config" / "hooks.json")


class Install(Base):
    def test_creates_the_file_and_its_folder_when_absent(self):
        hook.install(self.settings)
        self.assertEqual(self.load(), {"paynani": hook.block()})
        self.assertFalse(self.settings.with_suffix(".json.paynani.bak").exists(), "nothing to back up")

    def test_other_keys_survive_untouched_and_in_order(self):
        self.put(THEIRS)
        hook.install(self.settings)
        after = self.load()
        self.assertEqual(list(after), ["safety-gate", "session-init", "reminder", "paynani"])
        for key, value in THEIRS.items():
            self.assertEqual(after[key], value)
        self.assertEqual(after["paynani"], hook.block())

    def test_an_existing_file_is_backed_up_byte_for_byte(self):
        self.put(THEIRS)
        before = self.settings.read_bytes()
        hook.install(self.settings)
        self.assertEqual(self.settings.with_suffix(".json.paynani.bak").read_bytes(), before)
        self.assertFalse(self.settings.with_suffix(".json.paynani.tmp").exists())

    def test_the_file_keeps_its_mode(self):
        self.put(THEIRS)
        os.chmod(self.settings, 0o600)
        hook.install(self.settings)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        hook.uninstall(self.settings)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)

    def test_installing_twice_changes_nothing_the_second_time(self):
        self.put(THEIRS)
        hook.install(self.settings)
        first = self.settings.read_bytes()
        backup = self.settings.with_suffix(".json.paynani.bak")
        backup.unlink()
        hook.install(self.settings)
        self.assertEqual(self.settings.read_bytes(), first)
        self.assertFalse(backup.exists(), "no write, so no backup")

    def test_a_stale_or_disabled_paynani_key_is_converged(self):
        for stale in ({"enabled": False, **hook.block()},
                      {"SessionStart": [{"type": "command", "command": "python3 /old/clone/harness/session_start.py --antigravity"}]},
                      "not an object"):
            with self.subTest(stale=stale):
                self.put({"session-init": THEIRS["session-init"], "paynani": stale})
                self.assertFalse(hook.already_registered(self.load()))
                hook.install(self.settings)
                self.assertEqual(self.load(), {"session-init": THEIRS["session-init"], "paynani": hook.block()})

    def test_an_empty_file_is_treated_as_absent(self):
        self.put("  \n")
        hook.install(self.settings)
        self.assertEqual(self.load(), {"paynani": hook.block()})

    def test_invalid_json_is_refused_not_repaired(self):
        for text in ("{ not json", "[1, 2]", '"text"'):
            with self.subTest(text=text):
                self.put(text)
                with self.assertRaises(SystemExit):
                    hook.install(self.settings)
                self.assertEqual(self.settings.read_text(encoding="utf-8"), text)


class Uninstall(Base):
    def test_removes_only_the_paynani_key(self):
        self.put(THEIRS)
        hook.install(self.settings)
        hook.uninstall(self.settings)
        self.assertEqual(self.load(), THEIRS)

    def test_without_the_key_nothing_is_written(self):
        self.put(THEIRS)
        before = self.settings.read_bytes()
        self.assertEqual(hook.uninstall(self.settings), 0)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertFalse(self.settings.with_suffix(".json.paynani.bak").exists())

    def test_without_a_file_nothing_is_created(self):
        self.assertEqual(hook.uninstall(self.settings), 0)
        self.assertFalse(self.settings.exists())

    def test_backs_up_before_removing(self):
        self.put({"paynani": hook.block(), **THEIRS})
        before = self.settings.read_bytes()
        hook.uninstall(self.settings)
        self.assertEqual(self.settings.with_suffix(".json.paynani.bak").read_bytes(), before)


class State(Base):
    def test_each_state(self):
        other = {e: [{"type": "command", "command": "python3 /other/harness/session_start.py --antigravity", "timeout": 10}]
                 for e in hook.EVENTS}
        cases = [
            ({}, "missing"),
            (THEIRS, "missing"),
            ({"paynani": hook.block()}, "registered"),
            ({"paynani": {"enabled": False, **hook.block()}}, "disabled"),
            ({"paynani": other}, "other-clone"),
            ({"paynani": {"SessionStart": hook.block()["SessionStart"]}}, "different"),
            ({"paynani": []}, "different"),
        ]
        for settings, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(hook.state(settings), expected)


class CommandLine(Base):
    def test_print_shows_the_block_and_writes_nothing(self):
        result = self.cli("--print")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"paynani": hook.block()})
        self.assertFalse((self.home / ".gemini").exists())

    def test_check_install_check_uninstall_on_the_default_path(self):
        result = self.cli("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"NOT registered in {self.settings}: no 'paynani' key", result.stdout)
        self.assertIn("antigravity_hook.py --install", result.stdout)
        self.assertEqual(result.stderr, "")

        self.put(THEIRS)
        result = self.cli("--install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"PreInvocation"', result.stdout, "shows what it writes")
        self.assertIn("backed up", result.stdout)
        self.assertEqual(self.load()["paynani"], hook.block())

        result = self.cli("--check")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("registered in", result.stdout)

        result = self.cli("--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.load(), THEIRS)

    def test_check_names_another_clone(self):
        self.put({"paynani": {e: [{"type": "command", "command": "python3 /x/harness/session_start.py --antigravity", "timeout": 10}]
                              for e in hook.EVENTS}})
        result = self.cli("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("points to another clone", result.stdout)

    def test_settings_flag_acts_on_that_file_only(self):
        other = self.home / "elsewhere" / "hooks.json"
        result = self.cli("--install", "--settings", str(other))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(other.read_text(encoding="utf-8")), {"paynani": hook.block()})
        self.assertFalse(self.settings.exists())

    def test_invalid_json_exits_with_a_message_and_no_change(self):
        self.put("{ broken")
        result = self.cli("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not valid JSON", result.stderr)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{ broken")

    def sandboxed(self, script, *args):
        """Like agy's sandbox (#775): ANTIGRAVITY_AGENTAPI_EXE set and a read-only home."""
        env = dict(os.environ, HOME=str(self.home), ANTIGRAVITY_AGENTAPI_EXE="/usr/bin/true")
        os.chmod(self.home, 0o555)
        self.addCleanup(os.chmod, self.home, 0o755)
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=env, timeout=30)

    def test_check_inside_the_sandbox_says_it_cannot_tell(self):
        result = self.sandboxed(SCRIPT, "--check")
        self.assertEqual(result.returncode, hook.COULD_NOT_TELL, result.stdout + result.stderr)
        self.assertIn(f"could not read {self.settings} from here", result.stdout)
        self.assertIn("outside the sandbox", result.stdout)
        self.assertNotIn("NOT registered", result.stdout)
        self.assertNotIn("--install", result.stdout)

    def test_rules_check_inside_the_sandbox_says_it_cannot_tell(self):
        result = self.sandboxed(SCRIPT.with_name("antigravity_rules.py"), "--check")
        self.assertEqual(result.returncode, hook.COULD_NOT_TELL, result.stdout + result.stderr)
        self.assertIn(f"could not read {self.home / '.gemini' / 'GEMINI.md'} from here", result.stdout)
        self.assertNotIn("ABSENT", result.stdout)

    def test_a_registered_block_still_reads_ok_inside_the_sandbox(self):
        self.put({"paynani": hook.block()})
        result = self.sandboxed(SCRIPT, "--check")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_in_sandbox_needs_both_signs(self):
        self.assertFalse(hook.in_sandbox(env={}, home=self.home))
        self.assertFalse(hook.in_sandbox(env={"ANTIGRAVITY_AGENTAPI_EXE": "/x/agy"}, home=self.home),
                         "agy running a command outside the sandbox: the home is writable")
        os.chmod(self.home, 0o555)
        self.addCleanup(os.chmod, self.home, 0o755)
        self.assertFalse(hook.in_sandbox(env={}, home=self.home))
        self.assertTrue(hook.in_sandbox(env={"ANTIGRAVITY_AGENTAPI_EXE": "/x/agy"}, home=self.home))

    def test_one_action_is_required(self):
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertNotEqual(self.cli("--install", "--uninstall").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
