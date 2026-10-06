#!/usr/bin/env python3
"""Regression coverage for the macOS launchd installer."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


if sys.platform != "darwin":
    print(f"skip {Path(__file__).name} (not a macOS host: {sys.platform})")
    raise SystemExit(0)


class MacOSInstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.home = (self.root / "home").resolve()
        self.home.mkdir(mode=0o700)
        self.clone = (self.home / "workspace" / "paynani").resolve()
        self.clone.parent.mkdir(parents=True)
        ignore = shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".env",
            "hermes",
            "install.manifest",
            "roster.md",
            "runtime.env",
            "state",
        )
        shutil.copytree(ROOT, self.clone, ignore=ignore)

        self.env_file = (self.root / "mail.env").resolve()
        self.env_file.write_text(
            "\n".join(
                (
                    "PAYNANI_IMAP_HOST=imap.example.invalid",
                    "PAYNANI_IMAP_PORT=993",
                    "PAYNANI_EMAIL=agent@example.invalid",
                    "PAYNANI_PASSWORD=not-used",
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.env_file.chmod(0o600)

        self.bin = (self.root / "bin").resolve()
        self.bin.mkdir()
        self.launchctl_log = (self.root / "launchctl.log").resolve()
        self.launchctl_state = (self.root / "launchctl-state").resolve()
        self.launchctl_state.mkdir()
        self._write_executable(
            "launchctl",
            f"""\
            #!/usr/bin/env bash
            set -eu
            state_dir={self.launchctl_state}
            log={self.launchctl_log}
            printf '%s\\n' "$*" >>"$log"
            case "$1" in
              print)
                label=${{2##*/}}
                if [ -e "$state_dir/$label" ]; then
                  printf 'state = running\\n'
                  exit 0
                fi
                exit 113
                ;;
              bootout)
                target=${{3:-}}
                label=${{target##*/}}
                label=${{label%.plist}}
                rm -f "$state_dir/$label"
                exit 0
                ;;
              bootstrap)
                target=${{3:-}}
                label=${{target##*/}}
                label=${{label%.plist}}
                : >"$state_dir/$label"
                exit 0
                ;;
              enable)
                exit 0
                ;;
            esac
            exit 64
            """,
        )
        self._write_executable("himalaya", "#!/usr/bin/env bash\nprintf 'himalaya fake\\n'\n")
        self._write_executable(
            "openclaw",
            "#!/usr/bin/env bash\nprintf 'OpenClaw 2026.9.2 (test)\\n'\n",
        )

        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ.get('PATH', '')}",
            "PAYNANI_ENV": str(self.env_file),
        }
        self.addCleanup(self.temp.cleanup)

    def _write_executable(self, name: str, body: str) -> Path:
        path = self.bin / name
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        path.chmod(0o700)
        return path

    def run_install(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.clone / "scripts" / "install_macos.py"), *args],
            cwd=self.clone,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=20,
        )

    def read_plist(self, label: str) -> dict:
        path = self.home / "Library" / "LaunchAgents" / f"{label}.plist"
        with path.open("rb") as fh:
            return plistlib.load(fh)

    def test_openclaw_install_converges_launchagents_and_runtime_env(self):
        first = self.run_install("--runtime", "openclaw")
        output = first.stdout + first.stderr
        self.assertEqual(10, first.returncode, output)
        self.assertIn("platform=macos-launchd", output)
        self.assertIn("openclaw_probe=accepted", output)
        self.assertIn("verification_report_end result=passed", output)

        runtime_env = self.clone / "runtime.env"
        self.assertEqual(0o600, stat.S_IMODE(runtime_env.stat().st_mode))
        runtime_text = runtime_env.read_text(encoding="utf-8")
        self.assertIn('PAYNANI_RUNTIME="openclaw"', runtime_text)
        self.assertIn(f'PAYNANI_ENV="{self.env_file}"', runtime_text)
        self.assertIn('PAYNANI_SUPERVISOR="launchd"', runtime_text)
        self.assertIn('OPENCLAW="', runtime_text)

        state = self.clone / "state"
        self.assertTrue(state.is_dir())
        self.assertEqual(0o700, stat.S_IMODE(state.stat().st_mode))

        idle = self.read_plist("com.paynani.idle")
        dispatch = self.read_plist("com.paynani.dispatch")
        logrotate = self.read_plist("com.paynani.logrotate")

        self.assertEqual("com.paynani.idle", idle["Label"])
        self.assertEqual("com.paynani.dispatch", dispatch["Label"])
        self.assertEqual("com.paynani.logrotate", logrotate["Label"])
        self.assertTrue(idle["RunAtLoad"])
        self.assertTrue(idle["KeepAlive"])
        self.assertTrue(dispatch["RunAtLoad"])
        self.assertTrue(dispatch["KeepAlive"])
        self.assertEqual({"Hour": 3, "Minute": 17}, logrotate["StartCalendarInterval"])

        for plist in (idle, dispatch, logrotate):
            self.assertEqual(str(self.clone), plist["WorkingDirectory"])
            env = plist["EnvironmentVariables"]
            self.assertEqual("openclaw", env["PAYNANI_RUNTIME"])
            self.assertEqual(str(self.env_file), env["PAYNANI_ENV"])
            self.assertIn("OPENCLAW", env)

        commands = self.launchctl_log.read_text(encoding="utf-8")
        self.assertIn("bootstrap", commands)
        self.assertIn("enable gui/", commands)

        second = self.run_install("--runtime", "openclaw")
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)

    def test_opencode_install_needs_no_binary_and_names_the_plugin_step(self):
        first = self.run_install("--runtime", "opencode")
        output = first.stdout + first.stderr
        self.assertEqual(10, first.returncode, output)
        self.assertIn("opencode_spool_probe=accepted", output)
        self.assertIn("scripts/opencode_plugin.py --install", output)
        self.assertIn("verification_report_end result=passed", output)
        runtime_text = (self.clone / "runtime.env").read_text(encoding="utf-8")
        self.assertIn('PAYNANI_RUNTIME="opencode"', runtime_text)
        self.assertNotIn("OPENCLAW=", runtime_text)
        env = self.read_plist("com.paynani.dispatch")["EnvironmentVariables"]
        self.assertEqual("opencode", env["PAYNANI_RUNTIME"])
        second = self.run_install("--runtime", "opencode")
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)

    def test_dry_run_reports_plan_without_writing_artifacts(self):
        completed = self.run_install("--runtime", "openclaw", "--dry-run")
        output = completed.stdout + completed.stderr
        self.assertEqual(10, completed.returncode, output)
        self.assertIn("platform=macos-launchd", output)
        self.assertIn("runtime_probe=deferred", output)
        self.assertIn("inventory planned-launchagent=", output)
        self.assertIn("inventory planned-runtime-env=", output)
        self.assertFalse((self.clone / "runtime.env").exists())
        self.assertFalse((self.clone / "state").exists())
        self.assertFalse((self.home / "Library" / "LaunchAgents").exists())

    def test_account_plist_shape_matches_listener_contract(self):
        sys.path.insert(0, str(self.clone / "scripts"))
        import install_macos

        old = os.environ.get("PAYNANI_ENV")
        os.environ["PAYNANI_ENV"] = str(self.env_file)
        try:
            plist = install_macos.plist_for_account("iris", "/usr/bin/python3", "openclaw")
        finally:
            if old is None:
                os.environ.pop("PAYNANI_ENV", None)
            else:
                os.environ["PAYNANI_ENV"] = old
        self.assertEqual("com.paynani.idle.iris", plist["Label"])
        self.assertEqual(
            [
                "/usr/bin/python3",
                str(self.clone / "scripts" / "idle_listener.py"),
                "--account",
                "iris",
                "--env",
                str(self.env_file),
                "--journal",
                str(self.clone / "state" / "events.jsonl"),
            ],
            plist["ProgramArguments"],
        )
        self.assertEqual(
            str(self.clone / "state" / "accounts" / "iris" / "mail.log"),
            plist["StandardOutPath"],
        )

    def test_uninstall_removes_owned_launchagents_and_runtime_env(self):
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        completed = self.run_install("--runtime", "openclaw", "--uninstall")
        output = completed.stdout + completed.stderr
        self.assertEqual(10, completed.returncode, output)
        self.assertIn("removed_runtime_env=", output)
        self.assertFalse((self.clone / "runtime.env").exists())
        for label in ("com.paynani.idle", "com.paynani.dispatch", "com.paynani.logrotate"):
            self.assertFalse((self.home / "Library" / "LaunchAgents" / f"{label}.plist").exists())

    def manifest_records(self) -> dict[str, tuple[str, str]]:
        """path -> (kind, digest) as the manifest lists them."""
        lines = (self.clone / "install.manifest").read_text(encoding="utf-8").splitlines()
        records = {}
        for line in lines[2:]:
            _, kind, path, digest = line.split("\t")
            records[path] = (kind, digest)
        return records

    def test_install_writes_the_ownership_manifest(self):
        completed = self.run_install("--runtime", "openclaw")
        self.assertEqual(10, completed.returncode, completed.stdout + completed.stderr)
        manifest = self.clone / "install.manifest"
        self.assertEqual(0o600, stat.S_IMODE(manifest.stat().st_mode))
        lines = manifest.read_text(encoding="utf-8").splitlines()
        self.assertEqual(["version\t1", "runtime\topenclaw"], lines[:2])
        agents = self.home / "Library" / "LaunchAgents"
        expected = {str(agents / f"{label}.plist")
                    for label in ("com.paynani.idle", "com.paynani.dispatch", "com.paynani.logrotate")}
        expected.add(str(self.clone / "runtime.env"))
        records = self.manifest_records()
        self.assertEqual(expected, set(records))
        for path, (kind, digest) in records.items():
            self.assertEqual("file", kind)
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest, path)

    def test_the_plan_no_longer_refuses_for_a_missing_manifest(self):
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        # A subprocess from inside the clone, so upgrade_plan resolves the
        # manifest of this clone and not of whichever test imported it first.
        code = (
            "import json, sys; sys.path.insert(0, 'scripts'); import upgrade_plan as u; "
            "state, lines = u.read_manifest(); "
            "print(json.dumps([state, u.manifest_drift(lines) if state == 'present' else lines]))"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=self.clone, env=self.env,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(["present", []], json.loads(result.stdout))

    def test_upgrade_gives_an_installed_host_without_a_manifest_one(self):
        # A host installed before the manifest existed: LaunchAgents and
        # runtime.env are already here, install.manifest is not.
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        (self.clone / "install.manifest").unlink()
        completed = self.run_install("--runtime", "openclaw", "--upgrade")
        self.assertIn(completed.returncode, (0, 10), completed.stdout + completed.stderr)
        self.assertEqual(4, len(self.manifest_records()))

    def test_rerun_keeps_the_manifest_and_tracks_a_changed_plist(self):
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        before = self.manifest_records()
        self.assertEqual(0, self.run_install("--runtime", "openclaw").returncode)
        self.assertEqual(before, self.manifest_records())
        idle = self.home / "Library" / "LaunchAgents" / "com.paynani.idle.plist"
        idle.write_bytes(idle.read_bytes() + b" ")
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        records = self.manifest_records()
        self.assertEqual(hashlib.sha256(idle.read_bytes()).hexdigest(), records[str(idle)][1])

    def test_a_new_runtime_carries_the_manifest_over(self):
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        completed = self.run_install("--runtime", "opencode")
        self.assertIn(completed.returncode, (0, 10), completed.stdout + completed.stderr)
        lines = (self.clone / "install.manifest").read_text(encoding="utf-8").splitlines()
        self.assertEqual("runtime\topencode", lines[1])
        self.assertEqual(4, len(self.manifest_records()))

    def test_dry_run_does_not_create_the_manifest(self):
        self.run_install("--runtime", "openclaw", "--dry-run")
        self.assertFalse((self.clone / "install.manifest").exists())

    def test_uninstall_removes_the_manifest(self):
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        completed = self.run_install("--runtime", "openclaw", "--uninstall")
        self.assertEqual(10, completed.returncode, completed.stdout + completed.stderr)
        self.assertFalse((self.clone / "install.manifest").exists())

    def test_refuses_hermes_on_macos_before_writing(self):
        completed = self.run_install("--runtime", "hermes")
        output = completed.stdout + completed.stderr
        self.assertEqual(64, completed.returncode, output)
        self.assertIn("macOS install currently supports --runtime openclaw, codex and opencode only", output)
        self.assertFalse((self.clone / "runtime.env").exists())
        self.assertFalse((self.home / "Library" / "LaunchAgents").exists())


if __name__ == "__main__":
    unittest.main()
