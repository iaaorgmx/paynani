#!/usr/bin/env python3
"""Contract tests for the Hermes Generic HMAC adapter."""

import hashlib
import hmac
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from adapters import hermes


class _Handler(BaseHTTPRequestHandler):
    requests = []
    health_requests = []
    response_queue = []
    response_status = 202
    response_body = {
        "status": "accepted",
        "route": "paynani-roster",
        "event": "email.received",
        "delivery_id": "placeholder",
    }
    health_status = 200
    health_body = {"status": "ok", "platform": "webhook"}
    health_location: str | None = None

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).requests.append((self.path, dict(self.headers), body))
        if type(self).response_queue:
            response_status, response_body = type(self).response_queue.pop(0)
        else:
            response_status, response_body = (
                type(self).response_status,
                type(self).response_body,
            )
        response = dict(response_body)
        location = response.pop("_location", None)
        response["delivery_id"] = self.headers.get("X-Request-ID")
        data = json.dumps(response).encode("utf-8")
        self.send_response(response_status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        type(self).health_requests.append((self.path, dict(self.headers)))
        data = json.dumps(type(self).health_body).encode("utf-8")
        self.send_response(type(self).health_status)
        if type(self).health_location:
            self.send_header("Location", str(type(self).health_location))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


class _RejectingProxy(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        type(self).requests.append(self.path)
        self.send_response(502)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args):
        pass


class HermesAdapterTest(unittest.TestCase):
    def setUp(self):
        _Handler.requests = []
        _Handler.health_requests = []
        _Handler.response_queue = []
        _Handler.health_status = 200
        _Handler.health_body = {"status": "ok", "platform": "webhook"}
        _Handler.health_location = None
        _Handler.response_status = 202
        _Handler.response_body = {
            "status": "accepted",
            "route": "paynani-roster",
            "event": "email.received",
            "delivery_id": "placeholder",
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.temp.name)
        self.notify_secret = root / "notify.secret"
        self.roster_secret = root / "roster.secret"
        self.notify_secret.write_text("notify-test-secret\n", encoding="utf-8")
        self.roster_secret.write_text("roster-test-secret\n", encoding="utf-8")
        self.notify_secret.chmod(0o600)
        self.roster_secret.chmod(0o600)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.state = root / "state"
        self.env = mock.patch.dict(os.environ, {
            "PAYNANI_STATE": str(self.state),
            "HERMES_NOTIFY_URL": self.base + "/webhooks/paynani-notify",
            "HERMES_NOTIFY_SECRET_FILE": str(self.notify_secret),
            "HERMES_ROSTER_URL": self.base + "/webhooks/paynani-roster",
            "HERMES_ROSTER_SECRET_FILE": str(self.roster_secret),
            "HERMES_HEALTH_URL": self.base + "/health",
        }, clear=False)
        self.env.start()
        self.envelope = {
            "schema_version": 1,
            "event_type": "email.received",
            "event_id": "imap:INBOX:42:7",
            "source": "paynani",
            "account": "agent@example.com",
            "mailbox": "INBOX",
            "uidvalidity": "42",
            "uid": 7,
            "sender": {"name": "Dulce", "address": "dulce@example.com"},
            "subject": "cotización ✓",
            "roster_match": True,
            "authenticated_sender": False,
            "notification_text": "[mail] cotización ✓",
        }

    def tearDown(self):
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_roster_event_uses_exact_body_generic_v2_signature(self):
        with mock.patch.object(hermes.time, "time", return_value=1_700_000_000):
            result = hermes.deliver(self.envelope)

        self.assertTrue(result.ok, result.detail)
        self.assertEqual(1, len(_Handler.requests))
        path, headers, body = _Handler.requests[0]
        self.assertEqual("/webhooks/paynani-roster", path)
        self.assertEqual(self.envelope, json.loads(body.decode("utf-8")))
        expected = hmac.new(
            b"roster-test-secret",
            b"1700000000." + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual("1700000000", headers["X-Webhook-Timestamp"])
        self.assertEqual(expected, headers["X-Webhook-Signature-V2"])
        self.assertNotIn("X-Webhook-Signature", headers)
        self.assertFalse(any(name.lower().startswith("svix-") for name in headers))

    def test_ambient_http_proxy_cannot_intercept_signed_loopback_delivery(self):
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), _RejectingProxy)
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        _RejectingProxy.requests = []
        proxy_thread.start()
        try:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "harness")
            environment["HERMES_TEST_ENVELOPE"] = json.dumps(self.envelope)
            proxy_url = f"http://127.0.0.1:{proxy.server_port}"
            environment["http_proxy"] = proxy_url
            environment["HTTP_PROXY"] = proxy_url
            environment.pop("no_proxy", None)
            environment.pop("NO_PROXY", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json, os; "
                        "from adapters import hermes; "
                        "result = hermes.deliver(json.loads("
                        "os.environ['HERMES_TEST_ENVELOPE'])); "
                        "print(json.dumps({'status': result.status, "
                        "'detail': result.detail}))"
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
        finally:
            proxy.shutdown()
            proxy.server_close()
            proxy_thread.join(timeout=2)

        result = json.loads(completed.stdout)
        self.assertEqual("accepted", result["status"], result["detail"])
        self.assertEqual([], _RejectingProxy.requests)
        self.assertEqual("/webhooks/paynani-roster", _Handler.requests[0][0])

    def test_listener_fault_uses_direct_notify_route_without_roster_field(self):
        fault = {
            "schema_version": 1,
            "event_type": "listener.error",
            "event_id": "listener:deadbeef",
            "source": "paynani",
            "account": "agent@example.com",
            "observed_at": "2026-08-18T12:00:00Z",
            "message": "connection lost",
            "notification_text": "[listener] connection lost",
        }
        _Handler.response_status = 200
        _Handler.response_body = {
            "status": "delivered",
            "route": "paynani-notify",
        }
        result = hermes.deliver(fault)
        self.assertTrue(result.ok, result.detail)
        self.assertEqual("/webhooks/paynani-notify", _Handler.requests[0][0])

    def test_plain_http_non_loopback_route_is_configuration_error(self):
        os.environ["HERMES_ROSTER_URL"] = "http://example.com/webhooks/paynani-roster"
        result = hermes.deliver(self.envelope)
        self.assertEqual("config", result.status)
        self.assertIn("HTTPS", result.detail)
        self.assertEqual([], _Handler.requests)

    def test_webhook_redirect_is_refused_without_following_location(self):
        _Handler.response_status = 302
        _Handler.response_body = {
            "status": "redirect",
            "_location": self.base + "/redirected",
        }
        result = hermes.deliver(self.envelope)
        self.assertEqual("config", result.status)
        self.assertIn("redirect", result.detail.lower())
        self.assertEqual([], _Handler.health_requests)

    def test_response_body_is_bounded(self):
        with mock.patch.object(hermes, "MAX_RESPONSE_BYTES", 8):
            result = hermes.deliver(self.envelope)
        self.assertEqual("config", result.status)
        self.assertIn("exceeds", result.detail)

    def test_http_and_json_statuses_are_classified_for_the_ordered_queue(self):
        cases = (
            (200, "delivered", "config"),
            (200, "duplicate", "accepted"),
            (200, "ignored", "config"),
            (202, "accepted", "accepted"),
            (400, "error", "config"),
            (401, "error", "config"),
            (403, "error", "config"),
            (404, "error", "config"),
            (408, "error", "retry"),
            (413, "error", "config"),
            (429, "error", "retry"),
            (500, "error", "retry"),
            (503, "error", "retry"),
        )
        for http_status, json_status, expected in cases:
            with self.subTest(http_status=http_status, json_status=json_status):
                _Handler.response_status = http_status
                _Handler.response_body = {"status": json_status}
                result = hermes.deliver(self.envelope)
                self.assertEqual(expected, result.status, result.detail)

    def test_route_mode_and_named_route_are_enforced(self):
        self.envelope["roster_match"] = False
        _Handler.response_status = 202
        _Handler.response_body = {
            "status": "accepted",
            "route": "paynani-notify",
        }
        result = hermes.deliver(self.envelope)
        self.assertEqual("config", result.status)
        self.assertIn("direct", result.detail)

        self.envelope["roster_match"] = True
        _Handler.response_status = 202
        _Handler.response_body = {
            "status": "accepted",
            "route": "different-roster-route",
        }
        result = hermes.deliver(self.envelope)
        self.assertEqual("config", result.status)
        self.assertIn("route", result.detail.lower())

    def test_explicit_direct_502_retries_with_a_new_transport_id(self):
        self.envelope["roster_match"] = False
        _Handler.response_queue = [
            (502, {"status": "error", "error": "Delivery failed"}),
            (200, {"status": "delivered", "route": "paynani-notify"}),
        ]

        result = hermes.deliver(self.envelope)

        self.assertTrue(result.ok, result.detail)
        self.assertEqual(2, len(_Handler.requests))
        headers_first = {key.lower(): value for key, value in _Handler.requests[0][1].items()}
        headers_second = {key.lower(): value for key, value in _Handler.requests[1][1].items()}
        first = headers_first["x-request-id"]
        second = headers_second["x-request-id"]
        self.assertNotEqual(first, second)
        self.assertEqual(
            json.loads(_Handler.requests[0][2]),
            json.loads(_Handler.requests[1][2]),
        )
        self.assertEqual(
            self.envelope["event_id"],
            json.loads(_Handler.requests[1][2])["event_id"],
        )

    def test_repeated_direct_502_persists_failed_attempt_and_never_reuses_base(self):
        self.envelope["roster_match"] = False
        _Handler.response_queue = [
            (502, {"status": "error"}),
            (502, {"status": "error"}),
        ]
        first_result = hermes.deliver(self.envelope)
        self.assertEqual("retry", first_result.status)
        first_ids = [
            {key.lower(): value for key, value in headers.items()}["x-request-id"]
            for _path, headers, _body in _Handler.requests
        ]
        self.assertEqual(2, len(first_ids))

        _Handler.response_queue = [
            (200, {"status": "delivered", "route": "paynani-notify"}),
        ]
        second_result = hermes.deliver(self.envelope)
        self.assertTrue(second_result.ok, second_result.detail)
        third_headers = {
            key.lower(): value for key, value in _Handler.requests[2][1].items()
        }
        third_id = third_headers["x-request-id"]
        self.assertNotIn(third_id, first_ids)
        attempt_dir = self.state / "hermes-attempts"
        self.assertEqual([], list(attempt_dir.glob("*.json")))

    def test_legacy_v1_requires_explicit_mode_and_warns_about_replay(self):
        os.environ["HERMES_SIGNATURE_MODE"] = "v1"

        result = hermes.deliver(self.envelope)

        headers = {key.lower(): value for key, value in _Handler.requests[0][1].items()}
        body = _Handler.requests[0][2]
        expected = hmac.new(
            b"roster-test-secret", body, hashlib.sha256
        ).hexdigest()
        self.assertEqual(expected, headers["x-webhook-signature"])
        self.assertNotIn("x-webhook-signature-v2", headers)
        self.assertNotIn("x-webhook-timestamp", headers)
        self.assertIn("replay", result.detail.lower())

    def test_secret_file_with_group_or_world_permissions_is_refused(self):
        self.roster_secret.chmod(0o644)
        result = hermes.deliver(self.envelope)

        self.assertEqual("config", result.status)
        self.assertIn("0600", result.detail)
        self.assertNotIn("roster-test-secret", result.detail)
        self.assertEqual([], _Handler.requests)

    def test_secret_file_must_be_a_nonsymlink_mode_0600_file(self):
        for case in ("symlink", "mode-0400"):
            with self.subTest(case=case):
                _Handler.requests = []
                if case == "symlink":
                    link = self.roster_secret.with_name("roster-link.secret")
                    link.symlink_to(self.roster_secret)
                    os.environ["HERMES_ROSTER_SECRET_FILE"] = str(link)
                else:
                    self.roster_secret.chmod(0o400)
                result = hermes.deliver(self.envelope)
                self.assertEqual("config", result.status)
                self.assertIn("0600", result.detail)
                self.assertEqual([], _Handler.requests)
                self.roster_secret.chmod(0o600)
                os.environ["HERMES_ROSTER_SECRET_FILE"] = str(self.roster_secret)

    def test_missing_application_event_id_or_account_is_refused_before_transport(self):
        for field in ("event_id", "account"):
            with self.subTest(field=field):
                broken = dict(self.envelope)
                broken.pop(field)
                _Handler.requests = []

                result = hermes.deliver(broken)

                self.assertEqual("config", result.status)
                self.assertIn(field, result.detail)
                self.assertEqual([], _Handler.requests)

    def test_email_event_requires_boolean_roster_match(self):
        for unsafe in (None, "false", 0):
            with self.subTest(roster_match=unsafe):
                _Handler.requests = []
                broken = dict(self.envelope)
                broken["roster_match"] = unsafe
                result = hermes.deliver(broken)
                self.assertEqual("config", result.status)
                self.assertIn("roster_match", result.detail)
                self.assertEqual([], _Handler.requests)

    def test_transport_id_is_stable_and_route_scoped(self):
        _Handler.response_status = 503
        _Handler.response_body = {"status": "error"}
        hermes.deliver(self.envelope)
        hermes.deliver(self.envelope)
        roster_ids = [
            {key.lower(): value for key, value in headers.items()}["x-request-id"]
            for _path, headers, _body in _Handler.requests
        ]
        self.assertEqual(roster_ids[0], roster_ids[1])
        self.assertTrue(roster_ids[0].startswith("paynani-roster-v1-"))

        _Handler.requests = []
        self.envelope["roster_match"] = False
        hermes.deliver(self.envelope)
        notify_headers = {
            key.lower(): value for key, value in _Handler.requests[0][1].items()
        }
        notify_id = notify_headers["x-request-id"]
        self.assertTrue(notify_id.startswith("paynani-notify-v1-"))
        self.assertNotEqual(roster_ids[0], notify_id)

        same_uid_other_account = dict(self.envelope)
        same_uid_other_account["roster_match"] = True
        same_uid_other_account["account"] = "second-agent@example.com"
        other_account_id = hermes._request_id(
            same_uid_other_account,
            os.environ["HERMES_ROSTER_URL"],
        )
        self.assertNotEqual(roster_ids[0], other_account_id)

    def test_check_validates_both_routes_without_sending_mail(self):
        self.notify_secret.chmod(0o644)

        result = hermes.check()

        self.assertEqual("config", result.status)
        self.assertIn("notify", result.detail.lower())
        self.assertIn("0600", result.detail)
        self.assertNotIn("notify-test-secret", result.detail)
        self.assertEqual([], _Handler.requests)

    def test_fixed_v2_signing_and_route_id_vectors(self):
        envelope = {
            "event_id": "imap:INBOX:42:7",
            "roster_match": True,
            "subject": "cotización ✓",
        }
        body = hermes._body(envelope)
        self.assertEqual(
            '{"event_id":"imap:INBOX:42:7","roster_match":true,'
            '"subject":"cotización ✓"}',
            body.decode("utf-8"),
        )
        signature = hmac.new(
            b"fixed-route-secret",
            b"1700000000." + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            "204cce56d3ef989c85631adffa57494f364c07085f1be491c9f4c032ed658712",
            signature,
        )
        self.assertEqual(
            "paynani-roster-v1-"
            "a48136014ce2b3a8b492d2fa2d4ae80100bbdce4660f2d8cb5593891f617a6e0",
            hermes._request_id(
                envelope,
                "https://gateway.example/p/clean/webhooks/paynani-roster",
            ),
        )

    def test_operator_supplied_profile_route_is_used_unchanged(self):
        os.environ["HERMES_ROSTER_URL"] = (
            self.base + "/p/clean-room/webhooks/paynani-roster"
        )
        result = hermes.deliver(self.envelope)
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(
            "/p/clean-room/webhooks/paynani-roster",
            _Handler.requests[0][0],
        )

    def test_explicit_502_attempt_gets_a_fresh_v2_timestamp_and_signature(self):
        self.envelope["roster_match"] = False
        _Handler.response_queue = [
            (502, {"status": "error"}),
            (200, {"status": "delivered"}),
        ]
        with mock.patch.object(
            hermes, "_timestamp", side_effect=("1700000000", "1700000001")
        ):
            result = hermes.deliver(self.envelope)
        self.assertTrue(result.ok, result.detail)
        first = {k.lower(): v for k, v in _Handler.requests[0][1].items()}
        second = {k.lower(): v for k, v in _Handler.requests[1][1].items()}
        self.assertEqual("1700000000", first["x-webhook-timestamp"])
        self.assertEqual("1700000001", second["x-webhook-timestamp"])
        self.assertNotEqual(
            first["x-webhook-signature-v2"], second["x-webhook-signature-v2"]
        )

    def test_network_error_is_retryable_and_does_not_expose_secret(self):
        with mock.patch.object(
            hermes,
            "_open",
            side_effect=hermes.urllib.error.URLError("simulated outage"),
        ):
            result = hermes.deliver(self.envelope)
        self.assertEqual("retry", result.status)
        self.assertIn("duplicate risk", result.detail)
        self.assertNotIn("roster-test-secret", result.detail)

    def test_check_performs_live_health_get_without_claiming_route_readiness(self):
        result = hermes.check()
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(["/health"], [path for path, _ in _Handler.health_requests])
        self.assertEqual([], _Handler.requests)
        self.assertIn("not route readiness", result.detail.lower())

    def test_health_redirect_is_refused_without_following_location(self):
        _Handler.health_status = 302
        _Handler.health_location = f"{self.base}/unrelated-health"

        result = hermes.check()

        self.assertEqual("config", result.status)
        self.assertIn("redirect", result.detail.lower())
        self.assertEqual(["/health"], [path for path, _ in _Handler.health_requests])

    def test_missing_health_url_halts_delivery_as_incomplete_configuration(self):
        os.environ.pop("HERMES_HEALTH_URL")
        result = hermes.deliver(self.envelope)
        self.assertEqual("config", result.status)
        self.assertIn("HERMES_HEALTH_URL", result.detail)
        self.assertEqual([], _Handler.requests)

    def test_check_refuses_reused_route_secret(self):
        self.roster_secret.write_text("notify-test-secret\n", encoding="utf-8")
        result = hermes.check()
        self.assertEqual("config", result.status)
        self.assertIn("unique secret", result.detail)

        delivery = hermes.deliver(self.envelope)
        self.assertEqual("config", delivery.status)
        self.assertIn("unique secret", delivery.detail)
        self.assertEqual([], _Handler.requests)

    def test_profile_prefixed_url_is_sent_unchanged(self):
        os.environ["HERMES_ROSTER_URL"] = (
            self.base + "/p/mail-agent/webhooks/paynani-roster"
        )
        result = hermes.deliver(self.envelope)
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(
            "/p/mail-agent/webhooks/paynani-roster",
            _Handler.requests[0][0],
        )


if __name__ == "__main__":
    unittest.main()
