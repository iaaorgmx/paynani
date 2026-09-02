#!/usr/bin/env python3
"""Isolated installer contract tests for the Hermes FR7 flow."""

import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
import sys
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.event import listener_error, mail_event


class _HermesFixture(BaseHTTPRequestHandler):
    requests = []
    reject_notify = False
    notify_secret = b"notify-installer-secret"
    roster_secret = b"roster-installer-secret"

    def do_GET(self):
        type(self).requests.append(("GET", self.path, dict(self.headers), b""))
        self._answer(200, {"status": "ok", "platform": "webhook"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).requests.append(("POST", self.path, dict(self.headers), body))
        if self.path.endswith("paynani-notify"):
            if type(self).reject_notify:
                self._answer(401, {"status": "error"})
            else:
                self._answer(200, {"status": "delivered", "route": "paynani-notify"})
        else:
            self._answer(202, {"status": "accepted", "route": "paynani-roster"})

    def _answer(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        del format, args
        pass


class HermesInstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.state = self.root / "systemd-state"
        self.home.mkdir(mode=0o700)
        self.bin.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)

        # The clone is the install, so the installer under test has to be a
        # clone inside the sandbox. Running ROOT/scripts/install.sh against a
        # fake HOME converges into the real repository instead — and because the
        # ignore rules keep those artifacts out of `git status`, that leak is
        # invisible until something reads them back.
        self.clone = self.home / "workspace" / "paynani"
        self.clone.parent.mkdir(parents=True)
        shutil.copytree(ROOT, self.clone, symlinks=True)
        for leftover in ("state", ".env", "runtime.env", "install.manifest", "hermes"):
            target = self.clone / leftover
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
        self.install = self.clone / "scripts" / "install.sh"
        self.systemd_log = self.root / "systemd.log"
        self.runtime_log = self.root / "runtime.log"
        self._write_fakes()

        self.notify_secret = self.root / "notify.secret"
        self.roster_secret = self.root / "roster.secret"
        self.notify_secret.write_bytes(_HermesFixture.notify_secret + b"\n")
        self.roster_secret.write_bytes(_HermesFixture.roster_secret + b"\n")
        self.notify_secret.chmod(0o600)
        self.roster_secret.chmod(0o600)

        _HermesFixture.requests = []
        _HermesFixture.reject_notify = False
        _HermesFixture.notify_secret = b"notify-installer-secret"
        _HermesFixture.roster_secret = b"roster-installer-secret"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _HermesFixture)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        base = f"http://127.0.0.1:{self.server.server_port}"
        self.urls = {
            "HERMES_NOTIFY_URL": base + "/webhooks/paynani-notify",
            "HERMES_ROSTER_URL": base + "/webhooks/paynani-roster",
            "HERMES_HEALTH_URL": base + "/health",
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def _write(self, name, text):
        path = self.bin / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def _write_fakes(self):
        self._write(
            "systemctl",
            """#!/usr/bin/env bash
case "$*" in
  '--user show-environment') printf 'PATH=%s\\n' "$FAKE_SERVICE_PATH" ;;
  '--user daemon-reload') printf '%s\\n' "$*" >>"$FAKE_SYSTEMD_LOG" ;;
  '--user is-enabled --quiet '*) unit=${*: -1}; [[ -e "$FAKE_SYSTEMD_STATE/$unit.enabled" ]] ;;
  '--user is-active --quiet '*) unit=${*: -1}; [[ -e "$FAKE_SYSTEMD_STATE/$unit.active" ]] ;;
  '--user enable --now '*) unit=${*: -1}; : >"$FAKE_SYSTEMD_STATE/$unit.enabled"; : >"$FAKE_SYSTEMD_STATE/$unit.active"; printf '%s\\n' "$*" >>"$FAKE_SYSTEMD_LOG" ;;
  '--user restart '*) unit=${*: -1}; : >"$FAKE_SYSTEMD_STATE/$unit.active"; printf '%s\\n' "$*" >>"$FAKE_SYSTEMD_LOG" ;;
  *) exit 2 ;;
esac
""",
        )
        self._write(
            "systemd-analyze",
            """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_SYSTEMD_LOG"
[[ "$1" == verify ]]
""",
        )
        self._write("loginctl", "#!/usr/bin/env bash\nprintf 'yes\\n'\n")
        self._write("id", "#!/usr/bin/env bash\nprintf 'test-user\\n'\n")
        self._write("openclaw", "#!/usr/bin/env bash\n[[ \"$1\" == --version ]]\n")
        self._write("systemd-run", "#!/usr/bin/env bash\n\"${@: -2}\"\n")
        self._write(
            "hermes",
            """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$FAKE_RUNTIME_LOG"
[[ "$1" == webhook && "$2" == --help ]] || exit 9
printf 'Hermes webhook support\\n'
""",
        )

    def _environment(self, include_urls=True):
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.startswith("HERMES_") or name.startswith("PAYNANI_"):
                environment.pop(name)
        environment.update(
            {
                "HOME": str(self.home),
                "USER": "untrusted; value",
                "PATH": f"{self.bin}:/usr/bin:/bin",
                "FAKE_SERVICE_PATH": f"{self.bin}:/usr/bin:/bin",
                "FAKE_SYSTEMD_LOG": str(self.systemd_log),
                "FAKE_SYSTEMD_STATE": str(self.state),
                "FAKE_RUNTIME_LOG": str(self.runtime_log),
            }
        )
        if include_urls:
            environment.update(self.urls)
        return environment

    def _run(self, include_urls=True, external_secrets=True, upgrade=False):
        arguments = [str(self.install), "--runtime", "hermes", "--profile", "default"]
        if upgrade:
            arguments.append("--upgrade")
        if external_secrets:
            arguments.extend(
                [
                    "--non-interactive",
                    "--notify-secret-file",
                    str(self.notify_secret),
                    "--roster-secret-file",
                    str(self.roster_secret),
                ]
            )
        return subprocess.run(
            arguments,
            cwd=self.clone,
            env=self._environment(include_urls),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_openclaw_to_hermes_upgrade_restarts_owned_runtime_boundary(self):
        openclaw = subprocess.run(
            [str(self.install), "--runtime", "openclaw"],
            cwd=self.clone,
            env=self._environment(include_urls=False),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(10, openclaw.returncode, openclaw.stdout + openclaw.stderr)
        self.systemd_log.write_text("", encoding="utf-8")

        migrated = self._run(upgrade=True)
        self.assertEqual(10, migrated.returncode, migrated.stdout + migrated.stderr)
        manifest = self.clone / "install.manifest"
        runtime_env = self.clone / "runtime.env"
        self.assertIn("runtime\thermes\n", manifest.read_text(encoding="utf-8"))
        self.assertIn('PAYNANI_RUNTIME="hermes"\n', runtime_env.read_text(encoding="utf-8"))
        calls = self.systemd_log.read_text(encoding="utf-8")
        for unit in (
            "paynani-idle.service",
            "paynani-dispatch.service",
            "paynani-logrotate.timer",
        ):
            self.assertIn(f"--user restart {unit}", calls)

        self.systemd_log.write_text("", encoding="utf-8")
        repeated = self._run(upgrade=True)
        self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
        self.assertNotIn("--user restart", self.systemd_log.read_text(encoding="utf-8"))

    def test_missing_route_urls_refuse_before_filesystem_or_runtime_mutation(self):
        completed = self._run(include_urls=False)

        self.assertEqual(78, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("HERMES_NOTIFY_URL", completed.stderr)
        self.assertFalse((self.home / ".config").exists())
        # The install root is now inside the working tree, and the ignore rules
        # keep anything written there out of `git status` — so a refusal that
        # still wrote would leave no visible trace. Say it out loud instead.
        for leftover in ("install.manifest", "runtime.env", "hermes", "state"):
            self.assertFalse(
                (self.clone / leftover).exists(),
                f"refused install wrote {leftover} into the install root",
            )
        self.assertFalse(self.runtime_log.exists())
        self.assertEqual([], _HermesFixture.requests)

    def test_external_secrets_health_and_both_signed_routes_converge(self):
        completed = self._run()

        self.assertEqual(10, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("hermes_webhook_probe=accepted", completed.stdout)
        self.assertIn("hermes_health_probe=accepted", completed.stdout)
        self.assertIn("hermes_notify_smoke=delivered", completed.stdout)
        self.assertIn("hermes_notify_listener_error_smoke=delivered", completed.stdout)
        self.assertIn("hermes_roster_smoke=accepted completion=unconfirmed", completed.stdout)
        self.assertIn("verification_report_begin", completed.stdout)
        self.assertIn("verification_runtime=hermes", completed.stdout)
        for unit in (
            "paynani-idle.service",
            "paynani-dispatch.service",
            "paynani-logrotate.service",
            "paynani-logrotate.timer",
        ):
            self.assertIn(
                f"verification_unit={self.home}/.config/systemd/user/{unit}",
                completed.stdout,
            )
        self.assertIn(
            f"verification_secret=notify path={self.notify_secret} mode=0600 validated=true",
            completed.stdout,
        )
        self.assertIn(
            f"verification_secret=roster path={self.roster_secret} mode=0600 validated=true",
            completed.stdout,
        )
        self.assertIn("verification_smoke=health result=accepted scope=reachability-only", completed.stdout)
        self.assertIn("verification_smoke=notify-email.received result=delivered", completed.stdout)
        self.assertIn("verification_smoke=notify-listener.error result=delivered", completed.stdout)
        self.assertIn(
            "verification_smoke=roster-email.received result=accepted completion=unconfirmed",
            completed.stdout,
        )
        self.assertIn("verification_report_end result=passed", completed.stdout)

        runtime_env = self.clone / "runtime.env"
        text = runtime_env.read_text(encoding="utf-8")
        self.assertEqual(0o600, runtime_env.stat().st_mode & 0o777)
        self.assertIn('PAYNANI_RUNTIME="hermes"', text)
        for name, value in self.urls.items():
            self.assertIn(f"{name}=", text)
            self.assertIn(value, text)
        self.assertIn(str(self.notify_secret), text)
        self.assertIn(str(self.roster_secret), text)
        self.assertNotIn(_HermesFixture.notify_secret.decode(), text)
        self.assertNotIn(_HermesFixture.roster_secret.decode(), text)
        self.assertIn('HERMES_SIGNATURE_MODE="v2"', text)

        requests = _HermesFixture.requests
        self.assertEqual(["GET", "POST", "POST", "POST"], [item[0] for item in requests])
        self.assertEqual("/health", requests[0][1])
        for method, path, headers, body in requests[1:]:
            self.assertEqual("POST", method)
            secret = (
                _HermesFixture.notify_secret
                if path.endswith("paynani-notify")
                else _HermesFixture.roster_secret
            )
            timestamp = headers["X-Webhook-Timestamp"]
            expected = hmac.new(
                secret,
                timestamp.encode("ascii") + b"." + body,
                hashlib.sha256,
            ).hexdigest()
            self.assertEqual(expected, headers["X-Webhook-Signature-V2"])
            self.assertNotIn("X-Webhook-Signature", headers)
            self.assertFalse(any(name.lower().startswith("svix-") for name in headers))
            envelope = json.loads(body)
            self.assertIn(envelope["event_type"], ("email.received", "listener.error"))
            if envelope["event_type"] == "listener.error":
                production = listener_error(account="probe@example.invalid", message="probe")
                self.assertEqual(set(production), set(envelope))
                self.assertIsInstance(envelope["observed_at"], str)
                self.assertIn("message", envelope)
                self.assertNotIn("roster_match", envelope)
                self.assertNotIn("authenticated_sender", envelope)
            else:
                production = mail_event(
                    account="probe@example.invalid",
                    mailbox="INBOX",
                    uidvalidity=1,
                    uid=1,
                    sender_name="Installer Smoke",
                    sender_address="installer-smoke@invalid.example",
                    subject="probe",
                    sent_at="",
                    roster_match=False,
                    notification_text="probe",
                )
                self.assertEqual(set(production), set(envelope))
                self.assertIsInstance(envelope["sender"], dict)
                self.assertIsInstance(envelope["observed_at"], str)
                self.assertFalse(envelope["authenticated_sender"])
            self.assertEqual("paynani", envelope["source"])

        runtime_calls = self.runtime_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(["webhook --help"], runtime_calls)
        systemd_calls = self.systemd_log.read_text(encoding="utf-8")
        self.assertIn("verify ", systemd_calls)
        self.assertIn("--user enable --now paynani-dispatch.service", systemd_calls)

    def test_rejected_signed_route_fails_closed_before_service_activation(self):
        _HermesFixture.reject_notify = True

        completed = self._run()

        self.assertEqual(78, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("notify-route smoke probe failed", completed.stderr)
        self.assertFalse(any(self.state.glob("*.enabled")))
        systemd_calls = self.systemd_log.read_text(encoding="utf-8")
        self.assertNotIn("--user enable --now", systemd_calls)
        self.assertEqual(["GET", "POST"], [item[0] for item in _HermesFixture.requests])

    def test_interactive_secrets_are_shown_once_then_reused_for_route_probes(self):
        generated = self._run(external_secrets=False)

        self.assertEqual(78, generated.returncode, generated.stdout + generated.stderr)
        notify_match = re.search(r"^hermes_notify_secret=(\S+)$", generated.stdout, re.MULTILINE)
        roster_match = re.search(r"^hermes_roster_secret=(\S+)$", generated.stdout, re.MULTILINE)
        if notify_match is None or roster_match is None:
            self.fail("generated secrets were not shown exactly once")
        notify_value = notify_match.group(1)
        roster_value = roster_match.group(1)
        self.assertNotEqual(notify_value, roster_value)
        self.assertIn("configure the two Hermes routes", generated.stderr)
        self.assertEqual([], _HermesFixture.requests)
        self.assertFalse(any(self.state.glob("*.enabled")))

        default_dir = self.clone / "hermes"
        notify_path = default_dir / "notify.secret"
        roster_path = default_dir / "roster.secret"
        self.assertEqual(notify_value, notify_path.read_text(encoding="utf-8").strip())
        self.assertEqual(roster_value, roster_path.read_text(encoding="utf-8").strip())
        self.assertEqual(0o600, notify_path.stat().st_mode & 0o777)
        self.assertEqual(0o600, roster_path.stat().st_mode & 0o777)

        _HermesFixture.notify_secret = notify_value.encode("utf-8")
        _HermesFixture.roster_secret = roster_value.encode("utf-8")
        converged = self._run(external_secrets=False)

        self.assertEqual(10, converged.returncode, converged.stdout + converged.stderr)
        self.assertNotIn("hermes_notify_secret=", converged.stdout)
        self.assertNotIn("hermes_roster_secret=", converged.stdout)
        self.assertEqual(["GET", "POST", "POST", "POST"], [item[0] for item in _HermesFixture.requests])


if __name__ == "__main__":
    unittest.main()
