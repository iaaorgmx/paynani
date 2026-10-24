#!/usr/bin/env python3
"""A2: owner token screen, password/CSRF gates, usage, and one-time secret."""
from __future__ import annotations

import datetime as dt
import http.client
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))
from paynani_lib.web import api_tokens, app, auth, notify, token_pages, users  # noqa: E402

tmp = Path(tempfile.mkdtemp())
user_file = tmp / "web" / "user.json"
password = "valid-password-123"
users.create("owner@example.com", "Owner", password, user_file)
ctx = app.Context(user_file=user_file, accounts_file=tmp / "accounts.json", state_dir=tmp / "state",
                  notifier=notify.Notifier(send=lambda *args: None, log=lambda line: None))
server = app.serve(port=0, ctx=ctx)
threading.Thread(target=server.serve_forever, daemon=True).start()


def req(method: str, path: str, *, form: dict | None = None, cookie: str = "", origin: str = "https://example.ngrok.io"):
    headers = {"Host": "example.ngrok.io"}
    if cookie:
        headers["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        headers.update({"Origin": origin, "Content-Type": "application/x-www-form-urlencoded"})
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read().decode("utf-8")
    conn.close()
    return result


try:
    assert req("GET", "/api-tokens")[0] == 303
    status, headers, _ = req("POST", "/login", form={"email": "owner@example.com", "password": password})
    assert status == 303
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert cookie.startswith(auth.SESSION_COOKIE)
    status, _, page = req("GET", "/api-tokens", cookie=cookie)
    assert status == 200 and "Crear token" in page
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    form = {"csrf": csrf, "name": "Metis", "expiry": "30d", "permission_read": "1",
            "permission_sms.send": "1", "sms_per_hour": "30", "sms_per_day": "200",
            "agent_replies": "1", "password": password}
    assert req("POST", "/api-tokens/new", form={**form, "csrf": "bad"}, cookie=cookie)[0] == 403
    assert req("POST", "/api-tokens/new", form=form, cookie=cookie, origin="https://evil.example")[0] == 403
    assert req("POST", "/api-tokens/new", form={**form, "password": "wrong"}, cookie=cookie)[0] == 400
    assert not api_tokens.list_records(path=api_tokens.path_for(user_file))
    status, _, page = req("POST", "/api-tokens/new", form=form, cookie=cookie)
    assert status == 200 and "Token creado" in page
    secret = re.search(r'<code>(pn_[^<]+)</code>', page).group(1)
    records = api_tokens.list_records(path=api_tokens.path_for(user_file))
    record = records[0]
    assert secret not in json.dumps(records) and record["agent_replies"] is True
    assert record["permissions"] == ["read", "sms.send"]
    assert "https://example.ngrok.io/api/agents.md" in page
    status, _, page = req("GET", "/api-tokens/detail?id=" + record["sha256"], cookie=cookie)
    assert status == 200 and secret not in page
    assert req("POST", "/api-tokens/agent-replies", form={"csrf": csrf, "id": record["sha256"], "password": password}, cookie=cookie)[0] == 303
    assert api_tokens.list_records(path=api_tokens.path_for(user_file))[0]["agent_replies"] is False
    assert req("POST", "/api-tokens/revoke", form={"csrf": csrf, "id": record["sha256"], "password": password}, cookie=cookie)[0] == 303
    assert api_tokens.lookup(secret, path=api_tokens.path_for(user_file))[0] == "token_revoked"
    assert req("POST", "/api-tokens/revoke", form={"csrf": csrf, "id": record["sha256"], "password": password}, cookie=cookie)[0] == 400
    now = dt.datetime.now(dt.timezone.utc)
    orders = tmp / "state" / "sms" / "orders.jsonl"
    orders.parent.mkdir(parents=True)
    orders.write_text("\n".join(json.dumps(row) for row in [
        {"status": "queued", "token_id": record["prefix"], "at": now.isoformat()},
        {"status": "sent", "token_id": record["prefix"], "at": now.isoformat()},
        {"status": "queued", "token_id": "other", "at": now.isoformat()},
        {"status": "queued", "token_id": record["prefix"], "at": (now - dt.timedelta(days=1)).isoformat()},
    ]))
    assert token_pages.usage_today(tmp / "state", record["prefix"], now=now) == 1
    try:
        token_pages.expiry_from_form("custom", "2020-01-01T00:00")
        assert False, "past expiry accepted"
    except ValueError:
        pass
    for lang in ("es-MX", "en-US", "es-ES", "fr-FR", "pt-BR"):
        _, _, localized = req("GET", "/api-tokens?lang=" + lang, cookie=cookie)
        assert "web.tokens." not in localized
    print("ok A2 token screen")
finally:
    server.shutdown()
