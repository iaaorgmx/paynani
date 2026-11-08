#!/usr/bin/env python3
"""A2: owner token screen, password/CSRF gates, usage, and one-time secret."""
from __future__ import annotations

import ast
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

# Python 3.10 rejects escaped quotes in a nested f-string expression, while the
# Python 3.12 used by some CI jobs accepts them. Keep template fragments separate.
template_path = ROOT / "scripts" / "paynani_lib" / "web" / "token_pages.py"
template_tree = ast.parse(template_path.read_text(encoding="utf-8"), feature_version=(3, 10))
assert not any(isinstance(child, ast.JoinedStr)
               for node in ast.walk(template_tree) if isinstance(node, ast.FormattedValue)
               for child in ast.walk(node.value)), "nested f-string in Python 3.10 template"

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
    # #717: cada fila de la lista lleva el chevron de las listas, que abre el detalle.
    status, _, page = req("GET", "/api-tokens", cookie=cookie)
    assert status == 200 and f'<td class="token-ir"><a href="/api-tokens/detail?id={record["sha256"]}"' in page
    assert '<span class="flecha fila-flecha" aria-hidden="true"><svg' in page
    status, _, page = req("GET", "/api-tokens/detail?id=" + record["sha256"], cookie=cookie)
    assert status == 200 and secret not in page
    assert req("POST", "/api-tokens/agent-replies", form={"csrf": csrf, "id": record["sha256"], "password": password}, cookie=cookie)[0] == 303
    assert api_tokens.list_records(path=api_tokens.path_for(user_file))[0]["agent_replies"] is False
    assert req("POST", "/api-tokens/revoke", form={"csrf": csrf, "id": record["sha256"], "password": password}, cookie=cookie)[0] == 303
    assert api_tokens.lookup(secret, path=api_tokens.path_for(user_file))[0] == "token_revoked"
    assert req("POST", "/api-tokens/revoke", form={"csrf": csrf, "id": record["sha256"], "password": password}, cookie=cookie)[0] == 400
    # #760: el detalle nuevo y «Delete this token», sólo para vencidos o revocados.
    token_file = api_tokens.path_for(user_file)
    status, _, page = req("GET", "/api-tokens/detail?id=" + record["sha256"], cookie=cookie)
    assert status == 200 and 'action="/api-tokens/delete"' in page and 'action="/api-tokens/revoke"' not in page
    assert 'estado-token-revoked' in page and 'class="tok-tarjeta"' in page and '<progress class="tok-uso"' in page
    assert not re.search(r">[^<]*\d{2}:\d{2}:\d{2}\.\d{6}", page), "ISO con microsegundos a la vista"
    assert 'style="' not in page
    _, active = api_tokens.create("Activo", permissions=["read"], path=token_file)
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=22)).isoformat()
    _, expired = api_tokens.create("Vencido", permissions=["read"], path=token_file)
    raw = json.loads(token_file.read_text(encoding="utf-8"))
    for row in raw:
        if row["sha256"] == expired["sha256"]:
            row["expires_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
        if row["sha256"] == active["sha256"]:
            row["expires_at"] = future
    token_file.write_text(json.dumps(raw), encoding="utf-8")
    status, _, page = req("GET", "/api-tokens/detail?id=" + active["sha256"], cookie=cookie)
    assert status == 200 and 'action="/api-tokens/revoke"' in page and 'action="/api-tokens/delete"' not in page
    assert 'estado-token-active' in page and "22" in page
    status, _, page = req("GET", "/api-tokens/detail?id=" + expired["sha256"], cookie=cookie)
    assert status == 200 and 'estado-token-expired' in page and 'action="/api-tokens/delete"' in page
    delete_form = {"csrf": csrf, "id": active["sha256"], "password": password}
    status, _, page = req("POST", "/api-tokens/delete", form=delete_form, cookie=cookie)
    assert status == 400 and 'role="alert"' in page
    assert api_tokens.get_record(active["sha256"], path=token_file) is not None
    delete_form["id"] = expired["sha256"]
    assert req("POST", "/api-tokens/delete", form={**delete_form, "csrf": "bad"}, cookie=cookie)[0] == 403
    assert req("POST", "/api-tokens/delete", form={**delete_form, "password": "wrong"}, cookie=cookie)[0] == 400
    assert req("POST", "/api-tokens/delete", form=delete_form, cookie=cookie, origin="https://evil.example")[0] == 403
    assert api_tokens.get_record(expired["sha256"], path=token_file) is not None
    status, headers, _ = req("POST", "/api-tokens/delete", form=delete_form, cookie=cookie)
    assert status == 303 and headers["Location"].endswith("/api-tokens?deleted=1")
    assert api_tokens.get_record(expired["sha256"], path=token_file) is None
    status, _, page = req("GET", "/api-tokens?deleted=1", cookie=cookie)
    assert status == 200 and 'class="aviso-ok"' in page
    assert req("POST", "/api-tokens/delete", form=delete_form, cookie=cookie)[0] == 400
    revoked_form = {"csrf": csrf, "id": record["sha256"], "password": password}
    assert req("POST", "/api-tokens/delete", form=revoked_form, cookie=cookie)[0] == 303
    assert api_tokens.get_record(record["sha256"], path=token_file) is None
    for lang in ("es-MX", "en-US", "es-ES", "fr-FR", "pt-BR"):
        _, _, localized = req("GET", f"/api-tokens/detail?id={active['sha256']}&lang={lang}", cookie=cookie)
        assert "web.tokens." not in localized and "&amp;#" not in localized, lang
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
