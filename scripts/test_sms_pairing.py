#!/usr/bin/env python3
"""
Tests for the phone pairing page (SRV-4): `paynani sms pair --web`.
An assertion script, like the rest of this suite.

Levanta el servidor local del onboarding en modo "sms" con un estado temporal y
lo maneja por HTTP como lo haría un navegador: enlace con llave, sesión, CSRF,
generar código (el QR), emparejar de verdad por la pasarela, ver el teléfono y
revocarlo. La pasarela real se levanta en el mismo estado para que el código
del QR sirva de verdad.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import re
import sys
import tempfile
import threading
import urllib.parse
from http.server import HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import guard, i18n  # noqa: E402
from paynani_lib.server import make_handler  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import pairing, qr  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


# --- normalise_base / payload ---------------------------------------------------
check("base: https con puerto y barra final", "https://a.ngrok.io:8443", pairing.normalise_base(" https://a.ngrok.io:8443/ "))
check("base: http en la red local", "http://192.168.1.5:8765", pairing.normalise_base("http://192.168.1.5:8765"))
for bad in ("", "a.ngrok.io", "ftp://a.io", "https://", "https://a.io/ruta", "https://a.io?x=1", "https://u:p@a.io",
            "https://a io", "https://a.io:99999", "javascript:alert(1)"):
    check(f"base: se rechaza {bad!r}", None, pairing.normalise_base(bad))
check("payload: §1 de SMS_GATEWAY.md",
      {"v": 1, "pair": "https://a.io/sms/pair", "ws": "wss://a.io/sms/ws", "code": "K7QW2MXP"},
      pairing.payload("https://a.io", "K7QW2MXP"))

# --- servidor ------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
token = "pairing-test-token"
guard.token_path(state).write_text(token + "\n", encoding="utf-8")
httpd = HTTPServer(("127.0.0.1", 0), make_handler(state, None, page="sms"))
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)


def request(method, path, body=None, cookie=None):
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(body)
    conn.request(method, path, body=body, headers=headers)
    r = conn.getresponse()
    return r, r.read().decode("utf-8")


try:
    r, _ = request("GET", "/")
    check("sin llave: 403", 403, r.status)
    r, _ = request("GET", f"/?t={token}")
    cookie = r.getheader("Set-Cookie").split(";", 1)[0]
    check("con la llave: 303 y cookie de sesión", 303, r.status)

    r, page = request("GET", "/?lang=es-MX", cookie=cookie)
    csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)
    check("sin teléfono: la página pide la dirección del túnel, sin QR", (200, True, False),
          (r.status, 'name="url"' in page, "<svg" in page.split("<main>")[1].split("</div>", 1)[1]))
    check("la página dice que no hay teléfono emparejado", True, "ningún teléfono emparejado" in page)
    check("sin teléfono no hay botón de revocar", False, 'value="revoke"' in page)

    r, _ = request("POST", "/", {"action": "new_code", "csrf": "mal", "url": "https://a.io"}, cookie)
    check("CSRF equivocado: 400", 400, r.status)
    check("el CSRF equivocado no creó ningún código", False, (state / "sms" / "pairing.json").exists())

    r, page = request("POST", "/", {"action": "new_code", "csrf": csrf, "url": "a.ngrok.io"}, cookie)
    check("dirección sin https: error en la misma página, sin código", (200, True, False),
          (r.status, "empiece con https://" in page, (state / "sms" / "pairing.json").exists()))

    r, page = request("POST", "/", {"action": "new_code", "csrf": csrf, "url": "https://iris-demo.ngrok.io/"}, cookie)
    code = re.search(r'class="pairing-code">([A-Z2-9]{8})<', page).group(1)
    check("con una dirección válida: QR, dirección y código de 8 caracteres", (200, True, True, True),
          (r.status, "<svg" in page, "https://iris-demo.ngrok.io" in page, code != ""))
    check("la página se actualiza sola mientras espera", True, '<meta http-equiv="refresh" content="3">' in page)
    check("el código es el vigente del almacén (sólo su hash en disco)", True,
          code not in (state / "sms" / "pairing.json").read_text(encoding="utf-8"))
    r, again = request("GET", "/", cookie=cookie)
    check("al actualizar sigue el mismo código y no se genera otro", code, re.search(r'pairing-code">([A-Z2-9]{8})<', again).group(1))
    check("la página no deja guardar en caché (no-store)", True, "no-store" in (r.getheader("Cache-Control") or ""))

    # --- el código del QR de verdad empareja ---------------------------------------
    async def pair():
        g = gw.Gateway(state, state / "events.jsonl", tmp / "roster.md", public_url="https://iris-demo.ngrok.io")
        server = await gw.serve(g, "127.0.0.1", 0)
        gport = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", gport)
        body = json.dumps({"code": code, "device": {"model": "Pixel 6", "android": "16", "app_version": "1.0"}})
        writer.write((f"POST /sms/pair HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                      f"Content-Length: {len(body)}\r\n\r\n{body}").encode())
        data = await reader.read()
        writer.close()
        server.close()
        await server.wait_closed()
        return data.decode()

    reply = asyncio.run(pair())
    check("la pasarela acepta el código de la página: 201", True, reply.startswith("HTTP/1.1 201"))

    r, page = request("GET", "/", cookie=cookie)
    check("después de emparejar la página lo dice y lista el teléfono", (True, True, True, True),
          ("quedó emparejado" in page, "Pixel 6" in page, "Desconectado" in page, 'value="revoke"' in page))
    check("la página nunca muestra el token ni su hash", False,
          json.loads((state / "sms" / "device.json").read_text())["token_sha256"] in page)
    check("con teléfono emparejado no ofrece generar otro código (DEC-3)", False, 'value="new_code"' in page)
    check("ya no hay refresco automático", False, "http-equiv" in page)

    r, page = request("POST", "/", {"action": "new_code", "csrf": csrf, "url": "https://iris-demo.ngrok.io"}, cookie)
    check("pedir otro código con un teléfono emparejado se rechaza", (200, True),
          (r.status, "un solo teléfono" in page))

    r, _ = request("POST", "/", {"action": "revoke", "csrf": "mal"}, cookie)
    check("revocar con CSRF equivocado: 400 y el teléfono sigue", (400, True), (r.status, store_mod.Store(state).device() is not None))
    r, page = request("POST", "/", {"action": "revoke", "csrf": csrf}, cookie)
    check("revocar: el teléfono se va y la página lo dice", (200, None, True),
          (r.status, store_mod.Store(state).device(), "revocado" in page))
    check("después de revocar se puede generar un código otra vez", True, 'name="url"' in page)

    # --- otros idiomas y escapado ------------------------------------------------
    r, page = request("GET", "/?lang=en-US", cookie=cookie)
    check("en-US: la página sale en inglés", True, "Generate code" in page)
    r, page = request("POST", "/", {"action": "new_code", "csrf": csrf, "url": 'https://x.io"><script>alert(1)</script>'}, cookie)
    check("una dirección hostil se escapa y no genera código", (False, False),
          ("<script>alert(1)" in page, 'class="pairing-code"' in page))
finally:
    httpd.shutdown()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
