#!/usr/bin/env python3
"""Regression coverage for the macOS launchd installer."""

from __future__ import annotations

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

    def test_uninstall_removes_owned_launchagents_and_runtime_env(self):
        self.assertEqual(10, self.run_install("--runtime", "openclaw").returncode)
        completed = self.run_install("--runtime", "openclaw", "--uninstall")
        output = completed.stdout + completed.stderr
        self.assertEqual(10, completed.returncode, output)
        self.assertIn("removed_runtime_env=", output)
        self.assertFalse((self.clone / "runtime.env").exists())
        for label in ("com.paynani.idle", "com.paynani.dispatch", "com.paynani.logrotate"):
            self.assertFalse((self.home / "Library" / "LaunchAgents" / f"{label}.plist").exists())

    def test_refuses_hermes_on_macos_before_writing(self):
        completed = self.run_install("--runtime", "hermes")
        output = completed.stdout + completed.stderr
        self.assertEqual(64, completed.returncode, output)
        self.assertIn("macOS install currently supports --runtime openclaw and codex only", output)
        self.assertFalse((self.clone / "runtime.env").exists())
        self.assertFalse((self.home / "Library" / "LaunchAgents").exists())


if __name__ == "__main__":
    unittest.main()
