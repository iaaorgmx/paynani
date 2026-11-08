#!/usr/bin/env python3
"""Tests for `--runtime antigravity` in the installer's Python side (PRD #749, T4, FR-5 and FR-12).

- harness_step: the hooks step for doctor (`harness_step`) and bootstrap_user.py;
- bootstrap_user.py: the runtime list and finding a harness root two levels deep;
- install_manifest.py, upgrade_plan.py and healthcheck.py: the runtime is known.

Everything works on temporary homes and a temporary state directory, so the real
~/.gemini, ~/.claude and paynani state are never read or written.
"""

import importlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import diagnostics, harness_step  # noqa: E402

antigravity_hook = importlib.import_module("antigravity_hook")


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.hooks = self.home / ".gemini" / "config" / "hooks.json"

    def put(self, data):
        self.hooks.parent.mkdir(parents=True, exist_ok=True)
        self.hooks.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


class HarnessStep(TempHome):
    def test_antigravity_has_a_step_and_its_file(self):
        self.assertTrue(harness_step.has_step("antigravity"))
        self.assertEqual(harness_step.target("antigravity", self.home), self.hooks)
        self.assertEqual(harness_step.describe("antigravity"), "the Antigravity CLI session hooks")
        self.assertEqual(harness_step.command("antigravity"),
                         f"python3 {ROOT / 'scripts' / 'antigravity_hook.py'} --install")

    def test_states(self):
        other = {e: [{"type": "command", "command": "python3 /other/harness/session_start.py --antigravity", "timeout": 10}]
                 for e in antigravity_hook.EVENTS}
        cases = [
            (None, "absent"),
            ({"theirs": {"Stop": []}}, "absent"),
            ({"paynani": antigravity_hook.block()}, "present"),
            ({"paynani": {"enabled": False, **antigravity_hook.block()}}, "stale"),
            ({"paynani": other}, "stale"),
            ("{ broken", "unknown"),
            ("[1]", "unknown"),
        ]
        for content, expected in cases:
            with self.subTest(expected=expected, content=content):
                if content is None:
                    self.hooks.unlink(missing_ok=True)
                else:
                    self.put(content)
                self.assertEqual(harness_step.state("antigravity", self.home), expected)

    def test_install_through_the_step_writes_only_the_paynani_key(self):
        self.put({"theirs": {"Stop": [{"command": "x.sh"}]}})
        ok, output = harness_step.install("antigravity", self.home)
        self.assertTrue(ok, output)
        data = json.loads(self.hooks.read_text(encoding="utf-8"))
        self.assertEqual(data["theirs"], {"Stop": [{"command": "x.sh"}]})
        self.assertEqual(data["paynani"], antigravity_hook.block())
        self.assertEqual(harness_step.state("antigravity", self.home), "present")

    def test_show_is_the_block_the_script_prints(self):
        self.assertEqual(json.loads(harness_step.show("antigravity")), {"paynani": antigravity_hook.block()})


class DoctorRow(TempHome):
    def row(self):
        with mock.patch("pathlib.Path.home", return_value=self.home):
            rows = diagnostics._harness_step_checks("antigravity")
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_blocked_while_the_hooks_are_missing(self):
        row = self.row()
        self.assertEqual((row["name"], row["status"]), ("harness_step", "blocked"))
        self.assertIn("missing", row["summary"] if "summary" in row else json.dumps(row))
        self.assertIn("antigravity_hook.py --install", json.dumps(row))

    def test_ok_once_registered(self):
        self.put({"paynani": antigravity_hook.block()})
        self.assertEqual(self.row()["status"], "ok")

    def test_out_of_date_for_another_clone_and_unknown_for_a_broken_file(self):
        self.put({"paynani": {"enabled": False, **antigravity_hook.block()}})
        row = self.row()
        self.assertEqual(row["status"], "blocked")
        self.assertIn("out of date", json.dumps(row))
        self.put("{ broken")
        self.assertEqual(self.row()["status"], "unknown")


class Bootstrap(TempHome):
    def setUp(self):
        super().setUp()
        self.boot = importlib.import_module("bootstrap_user")

    def test_runtime_is_accepted(self):
        self.assertIn("antigravity", self.boot.RUNTIMES)
        self.assertEqual(self.boot.APP_NAMES["antigravity"], "Antigravity CLI")

    def test_a_root_two_levels_deep_is_detected(self):
        roots = ("~/.claude", "~/.gemini/antigravity-cli")
        with mock.patch.object(self.boot.harness_paths, "HARNESS_ROOTS", roots):
            self.assertEqual(self.boot.detect_runtimes(self.home), [])
            (self.home / ".gemini").mkdir()
            self.assertEqual(self.boot.detect_runtimes(self.home), [], "~/.gemini alone is Gemini CLI or the IDE")
            (self.home / ".gemini" / "antigravity-cli").mkdir()
            self.assertEqual(self.boot.detect_runtimes(self.home), ["antigravity"])
            (self.home / ".claude").mkdir()
            self.assertEqual(self.boot.detect_runtimes(self.home), ["claudecode", "antigravity"])

    def test_one_level_roots_still_work(self):
        (self.home / ".codex").mkdir()
        with mock.patch.object(self.boot.harness_paths, "HARNESS_ROOTS", ("~/.codex", "~/.opencode")):
            self.assertEqual(self.boot.detect_runtimes(self.home), ["codex"])

    def test_bootstrap_sh_knows_the_runtime_and_its_root(self):
        text = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("RUNTIMES=(openclaw hermes claudecode codex opencode antigravity)", text)
        self.assertIn("[antigravity]=.gemini/antigravity-cli", text)

    def test_macos_bootstrap_knows_the_runtime_and_its_root(self):
        mac = importlib.import_module("bootstrap_macos")
        self.assertIn("antigravity", mac.MACOS_RUNTIMES)
        self.assertEqual(mac.RUNTIME_ROOT["antigravity"], ".gemini/antigravity-cli")


class ManifestAndPlan(unittest.TestCase):
    def test_manifest_accepts_the_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = pathlib.Path(tmp) / "install.manifest"
            done = subprocess.run([sys.executable, str(ROOT / "scripts" / "install_manifest.py"), "migrate-runtime",
                                   "--manifest", str(manifest), "--from-runtime", "claudecode", "--runtime", "antigravity"],
                                  capture_output=True, text=True, timeout=30)
            self.assertNotIn("invalid choice", done.stderr)
            self.assertNotEqual(done.returncode, 2, done.stderr)

    def test_upgrade_plan_reinstalls_the_hooks_and_names_the_next_session(self):
        plan = importlib.import_module("upgrade_plan")
        hook_rule = plan.classify("scripts/antigravity_hook.py", runtime="antigravity", system="Linux")
        self.assertIn("reinstall-and-restart", json.dumps(hook_rule))
        self.assertIn("python3 scripts/antigravity_hook.py --install", json.dumps(hook_rule))
        start_rule = plan.classify("harness/session_start.py", runtime="antigravity", system="Linux")
        self.assertIn("next-session", json.dumps(start_rule))


class Healthcheck(unittest.TestCase):
    def test_spool_facts_count_what_the_hook_has_not_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = pathlib.Path(tmp)
            (state / "antigravity.spool").write_text("one\ntwo\n", encoding="utf-8")
            (state / "antigravity.offset").write_text("4", encoding="utf-8")
            with mock.patch.dict(os.environ, {"PAYNANI_STATE": str(state)}):
                healthcheck = importlib.import_module("healthcheck")
                facts = healthcheck.spool_facts("antigravity")
        self.assertEqual(facts["spool"], str(state / "antigravity.spool"))
        self.assertEqual((facts["bytes_total"], facts["bytes_unread"]), (8, 4))
        self.assertEqual(facts["session_arming"], "agy-hooks")
        self.assertTrue(facts["writable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
