#!/usr/bin/env python3
"""A7: private audit, alerts and token usage over HTTP."""
from __future__ import annotations

import datetime as dt
import http.client
import json
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))
from paynani_lib.sms.store import Store  # noqa: E402
from paynani_lib.web import api_actions, api_security, api_tokens, app, notify, users  # noqa: E402

tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
user_file = tmp / "web" / "user.json"
users.create("owner@example.com", "Owner", "valid-password-123", user_file)
secret, record = api_tokens.create("Worker", permissions=(), limits={"sms_per_hour": 2, "sms_per_day": 1},
                                    path=api_tokens.path_for(user_file))
mail = []
ctx = app.Context(user_file=user_file, state_dir=state,
                  notifier=notify.Notifier(send=lambda *args: mail.append(args), log=lambda line: None))
server = app.serve(port=0, ctx=ctx)
threading.Thread(target=server.serve_forever, daemon=True).start()


def request(action="GetTokenInfo", *, token=secret, ip="203.0.113.7"):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    conn.request("POST", "/api/agent", body=json.dumps({"action": action}),
                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                          "X-Forwarded-For": ip})
    response = conn.getresponse()
    result = response.status, json.loads(response.read())
    conn.close()
    return result


try:
    code, info = request()
    assert code == 200 and info["result"] == "success"
    assert info["name"] == "Worker" and info["prefix"] == record["prefix"]
    assert info["last_used_at"] and "sha256" not in info and secret not in json.dumps(info)
    assert request("ListRoster")[1]["code"] == "forbidden"

    store = Store(state)
    now = dt.datetime.now(dt.timezone.utc)
    store.append_status({"id": "a_test.queued", "order_id": "a_test", "status": "queued",
                         "token_id": record["prefix"], "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    code, usage = request("GetUsage")
    assert code == 200 and usage["calls"]["minute"] == 3
    assert usage["calls"]["hour"] == 3 and usage["calls"]["day"] == 3
    assert usage["calls"]["per_minute"] == 60
    assert usage["sms"] == {"hour": 1, "day": 1, "per_hour": 2, "per_day": 1}

    call = api_actions.Call(ctx, record, "203.0.113.7", {}, request_id="a" * 16)
    api_actions._daily_limit_alert(call, store, 1)
    api_actions._daily_limit_alert(call, store, 1)
    ctx.notifier.wait()
    assert len(mail) == 1 and "tope diario" in mail[0][1]

    assert request(token=secret + "x")[1]["code"] == "invalid_token"
    for _ in range(9):
        assert request(token="pn_" + "x" * 32, ip="198.51.100.8")[0] == 401
    # A valid credential breaks the consecutive failure streak.
    assert request(ip="198.51.100.8")[0] == 200
    for _ in range(9):
        assert request(token="pn_" + "x" * 32, ip="198.51.100.8")[0] == 401
    assert request(token="pn_" + "x" * 32, ip="198.51.100.8")[0] == 401
    assert request(ip="198.51.100.8")[1]["code"] == "too_many_attempts"
    ctx.notifier.wait()
    assert len(mail) == 2 and "10 fallos" in mail[1][1]

    journal = state / "api_security.jsonl"
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert {"call", "forbidden", "invalid_token", "too_many_attempts", "daily_quota_alert"} <= {r["kind"] for r in rows}
    assert all(set(r) == {"at", "epoch", "kind", "request_id", "prefix", "address"} for r in rows)
    assert secret not in journal.read_text() and "a_test" not in journal.read_text()
    assert all(r["prefix"] in ("", record["prefix"], "pn_xxxxxxxx") for r in rows)

    clock = [time.time()]
    old = api_security.Journal(tmp / "retention", clock=lambda: clock[0])
    old.record("invalid_token", "1" * 16, "", "203.0.113.7")
    clock[0] += 91 * 86400
    old.record("forbidden", "2" * 16, record["prefix"], "203.0.113.7")
    assert [r["kind"] for r in old._rows()] == ["forbidden"]
    assert stat.S_IMODE(old.path.stat().st_mode) == 0o600
    print("ok A7 audit, alerts and usage")
finally:
    server.shutdown()
