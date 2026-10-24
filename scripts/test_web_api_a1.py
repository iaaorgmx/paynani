#!/usr/bin/env python3
"""A1: token persistence, authentication, HTTP errors and concurrent limits."""
from __future__ import annotations

import datetime as dt
import http.client
import json
import stat
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))
from paynani_lib.web import api_auth, api_tokens, app, users  # noqa: E402


def check(condition, label):
    assert condition, label
    print("ok", label)


temp = Path(tempfile.mkdtemp())
user_file = temp / "web" / "user.json"
users.create("owner@example.com", "Owner", "valid-password-123", user_file)
store = api_tokens.path_for(user_file)
secret, record = api_tokens.create("test", path=store)
check(secret.startswith("pn_") and len(record["prefix"]) == 11, "token prefix")
check(secret not in store.read_text() and record["sha256"] in store.read_text(), "only digest stored")
check(stat.S_IMODE(store.stat().st_mode) == 0o600 and stat.S_IMODE(store.parent.stat().st_mode) == 0o700,
      "private file modes")
check(api_tokens.lookup(secret, path=store)[0] == "ok", "valid token")
check(api_tokens.lookup(secret + "x", path=store)[0] == "invalid_token", "bad token")
expired, _ = api_tokens.create("expired", path=store, expires_at="2020-01-01T00:00:00Z")
check(api_tokens.lookup(expired, path=store)[0] == "token_expired", "expired token")
records = json.loads(store.read_text())
records[0]["revoked_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
store.write_text(json.dumps(records))
check(api_tokens.lookup(secret, path=store)[0] == "token_revoked", "revoked token")
secret, record = api_tokens.create("valid", path=store)
ctx = app.Context(user_file=user_file)
server = app.serve(port=0, ctx=ctx)
threading.Thread(target=server.serve_forever, daemon=True).start()


def request(token=None, *, path="/api/agent", ip="198.51.100.1", form=None, json_body=None,
            header=True, method="POST"):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=8)
    headers = {"Host": "example.ngrok.io", "X-Forwarded-For": ip}
    if token and header:
        headers["Authorization"] = "Bearer " + token
    if json_body is not None:
        payload = json.dumps(json_body)
        headers["Content-Type"] = "application/json"
    else:
        data = {"action": "GetUsage"}
        data.update(form or {})
        if token and not header:
            data["api_token"] = token
        payload = urlencode(data)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    conn.request(method, path, body=payload if method == "POST" else None, headers=headers)
    response = conn.getresponse()
    body = json.loads(response.read())
    conn.close()
    check(body["request_id"] == response.getheader("X-Request-Id") and len(body["request_id"]) == 16,
          "request id in body and header")
    return response.status, body


status, body = request(secret)
check((status, body["code"]) == (400, "invalid_action"), "valid token reaches action boundary")
check(json.loads(store.read_text())[-1]["last_used_at"] is not None, "last use recorded")
check(request(secret, header=False)[1]["code"] == "invalid_action", "form token accepted")
check(request(secret, json_body={"action": "GetUsage", "api_token": secret}, header=False)[1]["code"] ==
      "invalid_action", "JSON token accepted")
check(request(secret, json_body={"action": "GetUsage"})[1]["code"] == "invalid_action",
      "Bearer token accepted with JSON")
check(request(secret, path="/api/agent?api_token=" + secret)[1]["code"] == "invalid_token",
      "URL token rejected")
check(request(secret, path="/api/agent?api_token=")[1]["code"] == "invalid_token",
      "empty URL token rejected")
check(request(expired)[1]["code"] == "token_expired", "expired error distinct")
check(request(secret + "x")[1]["code"] == "invalid_token", "invalid error distinct")
check(request(secret, method="GET")[0] == 405, "only POST")

ip = "198.51.100.50"
for _ in range(10):
    check(request("pn_bad", ip=ip)[0] == 401, "failed authentication")
check(request(secret, ip=ip)[1]["code"] == "too_many_attempts", "10 failures block address")
check(request(secret, ip="198.51.100.51")[1]["code"] == "invalid_action", "other address unaffected")
check(secret not in json.dumps(request(secret)[1]), "no token in API error")

class Clock:
    now = 1_800_000_000.0
    def __call__(self):
        return self.now

clock = Clock()
boundary = api_auth.Limits(clock)
for _ in range(10):
    boundary.fail("198.51.100.90")
check(boundary.blocked_for("198.51.100.90") == 900, "block lasts fifteen minutes")
clock.now += 901
check(boundary.blocked_for("198.51.100.90") == 0, "block expires")
for _ in range(60):
    assert boundary.admit_call("another-token") == 0
check(boundary.admit_call("another-token") == 60, "minute limit")
clock.now += 60
check(boundary.admit_call("another-token") == 0, "minute window expires")

limits = api_auth.Limits()
results = []
lock = threading.Lock()
def call():
    result = limits.admit_call("same-token")
    with lock:
        results.append(result)
workers = [threading.Thread(target=call) for _ in range(64)]
for worker in workers:
    worker.start()
for worker in workers:
    worker.join()
check(results.count(0) == 60 and len(results) == 64,
      "60 per minute under concurrent calls")
rate_token, _ = api_tokens.create("rate", path=store)
for _ in range(60):
    request(rate_token, ip="198.51.100.60")
status, body = request(rate_token, ip="198.51.100.60")
check(status == 429 and body["code"] == "rate_limited" and body["retry_after"] > 0,
      "HTTP 61st call is rate limited")
server.shutdown()
server.server_close()
