#!/usr/bin/env python3
"""Deliver canonical paynani envelopes to authenticated Hermes routes."""

import hashlib
import hmac
import ipaddress
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from . import accepted, config, retry

# This module is imported under two different package names — `adapters.hermes`
# by the dispatcher, which puts harness/ on the path, and `harness.adapters.
# hermes` by scripts/hermes_smoke.py, which puts the repo root there instead. A
# relative import works for exactly one of them, so harness/ is put on the path
# here and `paths` imported by its bare name, which works for both.
_HARNESS = Path(__file__).resolve().parent.parent
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

from paths import state_dir   # noqa: E402

NAME = "hermes"
TIMEOUT = 30
MAX_RESPONSE_BYTES = 1024 * 1024


class _ResponseTooLarge(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(
    _NoRedirect,
    urllib.request.ProxyHandler({}),
)


def _open(request):
    return _OPENER.open(request, timeout=TIMEOUT)


def _read_response(handle):
    raw = handle.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise _ResponseTooLarge(
            f"Hermes response exceeds {MAX_RESPONSE_BYTES} bytes"
        )
    return raw


def _signature_mode():
    """V2 by default; VERSION remains a compatibility alias for early adopters."""
    return os.environ.get(
        "HERMES_SIGNATURE_MODE",
        os.environ.get("HERMES_SIGNATURE_VERSION", "v2"),
    ).strip().lower()


def _timestamp():
    return str(int(time.time()))


def _body(envelope):
    return json.dumps(
        envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _url_error(url):
    """Return an actionable safety error, or an empty string for an allowed URL."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
    except ValueError:
        return "Hermes route URL is invalid. Fix HERMES_*_URL."
    loopback = host.lower() == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if parsed.scheme not in ("http", "https") or not host:
        return "Hermes route URL must be an absolute HTTP(S) URL. Fix HERMES_*_URL."
    if parsed.username or parsed.password:
        return "Hermes route URL must not contain credentials. Use HERMES_*_SECRET_FILE."
    if not loopback:
        if parsed.scheme != "https":
            return "Non-loopback Hermes routes require HTTPS. Fix HERMES_*_URL."
        if os.environ.get("HERMES_ALLOW_REMOTE", "").lower() not in ("1", "true", "yes"):
            return (
                "Non-loopback Hermes routes require explicit opt-in. Set "
                "HERMES_ALLOW_REMOTE=1 after verifying TLS and the destination."
            )
    return ""


def _request_id(envelope, url):
    route_class = "roster" if envelope.get("roster_match") else "notify"
    material = (
        f"{envelope.get('account', '')}\0{envelope.get('event_id', '')}\0{url}"
    ).encode("utf-8")
    return f"paynani-{route_class}-v1-" + hashlib.sha256(material).hexdigest()


def _attempt_path(envelope, url):
    material = (
        f"{envelope.get('account', '')}\0{envelope.get('event_id', '')}\0{url}"
    ).encode("utf-8")
    return (
        state_dir() / "hermes-attempts"
        / (hashlib.sha256(material).hexdigest() + ".json")
    )


def _attempt_read(path):
    if not path.exists():
        return None, ""
    if path.is_symlink():
        return None, f"Hermes attempt state {path} must not be a symlink"
    try:
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != os.geteuid():
            return None, f"Hermes attempt state {path} must be a service-owned regular file"
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            return None, f"Hermes attempt state {path} must have mode 0600"
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value.get("attempt_id"), str) or type(value.get("failed")) is not bool:
            raise ValueError("invalid fields")
        return value, ""
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"cannot read Hermes attempt state {path}: {exc}"


def _attempt_write(path, attempt_id, failed):
    directory = path.parent
    temporary = directory / (path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory_stat = directory.stat()
        if (
            directory.is_symlink()
            or not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.geteuid()
            or stat.S_IMODE(directory_stat.st_mode) & 0o077
        ):
            return f"Hermes attempt-state directory {directory} must be service-owned mode 0700"
        data = json.dumps(
            {"attempt_id": attempt_id, "failed": failed},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return ""
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return f"cannot persist Hermes direct-attempt state at {path}: {exc}"


def _attempt_clear(path):
    try:
        path.unlink(missing_ok=True)
        return ""
    except OSError as exc:
        return f"cannot clear Hermes direct-attempt state at {path}: {exc}"


def _load_secret(secret_file):
    secret_path = Path(secret_file).expanduser()
    requirement = (
        "secret must be a non-symlink regular file owned by the service user "
        "with mode 0600"
    )
    try:
        if secret_path.is_symlink():
            return None, requirement
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(secret_path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            secret_stat = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(secret_stat.st_mode)
                or stat.S_IMODE(secret_stat.st_mode) != 0o600
                or secret_stat.st_uid != os.geteuid()
            ):
                return None, requirement
            secret = handle.read().rstrip(b"\r\n")
    except OSError as exc:
        return None, f"{requirement}; file cannot be read: {exc}"
    if not secret:
        return None, "secret file is empty"
    return secret, ""


def _route_settings():
    health_url = os.environ.get("HERMES_HEALTH_URL", "").strip()
    if not health_url:
        return None, config(
            "Hermes runtime is incomplete. Set HERMES_HEALTH_URL in the "
            "dispatcher service."
        )
    health_error = _url_error(health_url)
    if health_error:
        return None, config(f"Hermes health endpoint: {health_error}")
    routes = {}
    for label in ("notify", "roster"):
        upper = label.upper()
        url = os.environ.get(f"HERMES_{upper}_URL", "").strip()
        secret_file = os.environ.get(f"HERMES_{upper}_SECRET_FILE", "").strip()
        if not url or not secret_file:
            return None, config(
                f"Hermes {label} route is not configured. Set HERMES_{upper}_URL "
                f"and HERMES_{upper}_SECRET_FILE."
            )
        url_error = _url_error(url)
        if url_error:
            return None, config(f"Hermes {label} route: {url_error}")
        secret, secret_error = _load_secret(secret_file)
        if secret_error:
            return None, config(
                f"Hermes {label} route {secret_error}. Fix "
                f"HERMES_{upper}_SECRET_FILE."
            )
        routes[label] = (url, secret)
    if hmac.compare_digest(routes["notify"][1], routes["roster"][1]):
        return None, config(
            "Hermes notify and roster routes must use a unique secret each because "
            "the generic signature does not bind the route path."
        )
    signature_mode = _signature_mode()
    if signature_mode not in ("v1", "v2"):
        return None, config(
            "Unknown HERMES_SIGNATURE_MODE; use v2 or explicit legacy v1."
        )
    return routes, None


def _classify(http_status, payload, route_class, expected_route):
    status = payload.get("status") if isinstance(payload, dict) else None
    response_route = payload.get("route") if isinstance(payload, dict) else None
    if response_route and response_route != expected_route:
        return config(
            f"Hermes answered for route {response_route!r}, not configured route "
            f"{expected_route!r}. Check the route URL and secret pairing."
        )
    if http_status == 200 and status == "duplicate":
        return accepted(
            "Hermes recognized a duplicate transport ID (HTTP 200); verify "
            "user-facing delivery after any ambiguous timeout"
        )
    if route_class == "roster" and http_status == 202 and status == "accepted":
        return accepted(
            "Hermes queued the agent run (HTTP 202); completion is unconfirmed"
        )
    if route_class == "notify" and http_status == 200 and status == "delivered":
        return accepted("Hermes completed direct delivery (HTTP 200)")
    if http_status in (200, 202) and status in ("accepted", "delivered"):
        expected = (
            "direct HTTP 200 delivered"
            if route_class == "notify"
            else "agent HTTP 202 accepted"
        )
        return config(
            f"Hermes returned {http_status} status={status!r} for the {route_class} "
            f"route; expected {expected}. Check that route URLs and secrets are not swapped."
        )
    if http_status == 200 and status == "ignored":
        return config(
            "Hermes ignored an event the adapter expected to route. Check route "
            "event filters and HERMES_*_URL."
        )
    if 300 <= http_status <= 399:
        return config(
            f"Hermes route returned redirect HTTP {http_status}. Redirects are "
            "refused so signatures and exact POST bodies cannot cross origins."
        )
    if http_status in (400, 401, 403, 404, 413):
        return config(
            f"Hermes route returned HTTP {http_status}. Check HERMES_*_URL, the "
            "matching secret file, route permissions, and payload limits."
        )
    if http_status in (408, 429) or 500 <= http_status <= 599:
        return retry(f"Hermes route returned retryable HTTP {http_status}")
    return retry(
        f"Hermes route returned unexpected HTTP {http_status} status={status!r}"
    )


def _send(url, secret, body, request_id):
    signature_version = _signature_mode()
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": request_id,
    }
    if signature_version == "v1":
        headers["X-Webhook-Signature"] = hmac.new(
            secret, body, hashlib.sha256
        ).hexdigest()
    else:
        timestamp = _timestamp()
        headers["X-Webhook-Timestamp"] = timestamp
        headers["X-Webhook-Signature-V2"] = hmac.new(
            secret, timestamp.encode("ascii") + b"." + body, hashlib.sha256
        ).hexdigest()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with _open(request) as response:
            raw = _read_response(response)
            http_status = response.status
    except urllib.error.HTTPError as exc:
        raw = _read_response(exc)
        http_status = exc.code
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = {}
    return http_status, payload


def deliver(envelope):
    if not isinstance(envelope, dict) or not str(envelope.get("event_id", "")).strip():
        return config(
            "Hermes cannot deliver an envelope without event_id. Inspect the "
            "journal record; ordered delivery remains halted."
        )
    if not str(envelope.get("account", "")).strip():
        return config(
            "Hermes cannot derive an account-scoped transport ID without account. "
            "Inspect the journal record; ordered delivery remains halted."
        )
    if (
        envelope.get("event_type") == "email.received"
        and type(envelope.get("roster_match")) is not bool
    ):
        return config(
            "Hermes requires email.received roster_match to be a boolean. "
            "Inspect the journal record; ordered delivery remains halted."
        )
    routes, route_error = _route_settings()
    if route_error or routes is None:
        return route_error
    route_class = "roster" if envelope.get("roster_match") else "notify"
    url, secret = routes[route_class]
    expected_route = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]

    body = _body(envelope)
    signature_version = _signature_mode()
    request_id = _request_id(envelope, url)
    attempt_path = None
    if route_class == "notify":
        attempt_path = _attempt_path(envelope, url)
        attempt, attempt_error = _attempt_read(attempt_path)
        if attempt_error:
            return config(attempt_error + "; ordered delivery remains halted")
        if attempt is None:
            attempt = {"attempt_id": request_id, "failed": False}
            attempt_error = _attempt_write(attempt_path, request_id, False)
        elif attempt["failed"]:
            request_id = request_id + "-attempt-" + uuid.uuid4().hex
            attempt_error = _attempt_write(attempt_path, request_id, False)
        else:
            request_id = attempt["attempt_id"]
            attempt_error = ""
        if attempt_error:
            return config(attempt_error + "; no direct request was sent")

    http_status, payload = 0, {}
    try:
        maximum_attempts = 2 if route_class == "notify" else 1
        for attempt_number in range(maximum_attempts):
            http_status, payload = _send(url, secret, body, request_id)
            if http_status != 502 or route_class != "notify":
                break
            attempt_error = _attempt_write(attempt_path, request_id, True)
            if attempt_error:
                return config(attempt_error + "; ordered delivery remains halted")
            if attempt_number + 1 < maximum_attempts:
                request_id = (
                    _request_id(envelope, url) + "-attempt-" + uuid.uuid4().hex
                )
                attempt_error = _attempt_write(attempt_path, request_id, False)
                if attempt_error:
                    return config(attempt_error + "; no retry request was sent")
    except _ResponseTooLarge as exc:
        return config(f"{exc}; check HERMES_*_URL and gateway response limits")
    except (OSError, urllib.error.URLError) as exc:
        return retry(
            "Hermes route is unreachable or timed out; retrying the stable "
            f"transport ID has duplicate risk if the gateway accepted it: {exc}"
        )

    result = _classify(http_status, payload, route_class, expected_route)
    if result.ok and attempt_path is not None:
        attempt_error = _attempt_clear(attempt_path)
        if attempt_error:
            return config(attempt_error + "; ordered delivery remains halted")
    if signature_version == "v1":
        warning = "Legacy V1 has no replay protection; migrate the Hermes route to V2."
        result.detail = f"{result.detail}; {warning}" if result.detail else warning
    return result


def detect():
    return all(
        os.environ.get(name, "").strip()
        for name in (
            "HERMES_NOTIFY_URL",
            "HERMES_NOTIFY_SECRET_FILE",
            "HERMES_ROSTER_URL",
            "HERMES_ROSTER_SECRET_FILE",
            "HERMES_HEALTH_URL",
        )
    )


def _health(url):
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with _open(request) as response:
            raw = _read_response(response)
            http_status = response.status
    except urllib.error.HTTPError as exc:
        http_status = exc.code
        try:
            raw = _read_response(exc)
        except _ResponseTooLarge as size_error:
            return config(
                f"{size_error}; fix HERMES_HEALTH_URL or gateway response limits"
            )
    except _ResponseTooLarge as exc:
        return config(
            f"{exc}; fix HERMES_HEALTH_URL or gateway response limits"
        )
    except (OSError, urllib.error.URLError) as exc:
        return retry(f"Hermes health endpoint is unreachable or timed out: {exc}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = {}
    if http_status == 200 and payload.get("status") == "ok":
        return accepted(
            "Hermes webhook server answers GET /health; this is reachability, "
            "not route readiness or agent completion"
        )
    if 300 <= http_status <= 399:
        return config(
            f"Hermes health URL returned redirect HTTP {http_status}; use the "
            "final validated health URL directly."
        )
    if http_status in (400, 401, 403, 404, 413):
        return config(
            f"Hermes health URL returned HTTP {http_status}. Fix HERMES_HEALTH_URL."
        )
    return retry(
        f"Hermes health URL returned HTTP {http_status} status="
        f"{payload.get('status')!r}"
    )


def check():
    if not detect():
        return config(
            "Hermes routes are incomplete. Configure both notify and roster URLs, "
            "secret files, and HERMES_HEALTH_URL in the dispatcher service."
        )
    _routes, route_error = _route_settings()
    if route_error:
        return route_error
    signature_version = _signature_mode()
    health_url = os.environ["HERMES_HEALTH_URL"].strip()
    result = _health(health_url)
    if signature_version == "v1":
        warning = "legacy V1 has no replay protection"
        result.detail = f"{result.detail}; {warning}" if result.detail else warning
    return result
