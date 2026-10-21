#!/usr/bin/env python3
"""
Tests for the gateway's forward to PaynaniWeb (PRD #434 FR-1, FR-2; T1 of #435).
An assertion script, like the rest of this suite.

Levanta la pasarela y, en otro puerto de 127.0.0.1, una «web» falsa que anota lo
que le llega y contesta. Comprueba que lo de /sms/ sigue siendo de la pasarela,
que lo demás llega a la web tal cual (sin los encabezados de un solo salto), que
sin web se contesta 503 y que el teléfono se sigue conectando. Nada sale de la
máquina.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import config as sms_config  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import websocket as wsm  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """# roster de prueba

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Ana López | ana@example.com | Human |  | +52 1 55 1111 2222 |
"""


class FakeWeb:
    """Una web mínima: guarda la cabecera y el cuerpo de cada petición y contesta."""

    def __init__(self, mode="ok"):
        self.mode = mode          # ok | silent (cierra sin responder)
        self.requests = []
        self.server = None

    async def handle(self, reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        text = head.decode("latin-1")
        length = 0
        for line in text.split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1])
        body = await reader.readexactly(length) if length else b""
        self.requests.append({"head": text, "body": body})
        if self.mode == "silent":
            writer.close()
            return
        payload = json.dumps({"path": text.split(" ", 2)[1], "body_len": len(body)}).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: s=1; HttpOnly\r\n"
                     + f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode() + payload)
        await writer.drain()
        writer.close()

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]


async def raw_http(port, head_lines, body=b""):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(("\r\n".join(head_lines) + "\r\n\r\n").encode("latin-1") + body)
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), 10)
    writer.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, head.decode("latin-1"), payload


def headers_of(head_text):
    out = {}
    for line in head_text.split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            out.setdefault(k.strip().lower(), []).append(v.strip())
    return out


async def free_port():
    probe = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = probe.sockets[0].getsockname()[1]
    probe.close()
    await probe.wait_closed()
    return port


async def main():
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text(ROSTER, encoding="utf-8")

    web = FakeWeb()
    web_port = await web.start()
    g = gw.Gateway(state, state / "events.jsonl", roster, public_url="https://ejemplo.ngrok.io", web_port=web_port)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    # --- lo de /sms/ sigue en la pasarela ---------------------------------------
    status, _, payload = await raw_http(port, ["GET /sms/health HTTP/1.1", "Host: x"])
    check("/sms/health lo contesta la pasarela", (200, True), (status, json.loads(payload).get("ok")))
    for path in ("/sms/otra", "/sms", "/sms/ws/x"):
        status, _, payload = await raw_http(port, [f"GET {path} HTTP/1.1", "Host: x"])
        check(f"{path} es de la pasarela: 404, no va a la web", (404, "not_found"), (status, json.loads(payload).get("error")))
    status, _, payload = await raw_http(port, ["POST /sms/pair HTTP/1.1", "Host: x", "Content-Length: 2"], b"{}")
    check("POST /sms/pair sigue en la pasarela (cuerpo sin código: 400 de la pasarela)", (400, True),
          (status, "error" in json.loads(payload)))
    check("nada de /sms/ llegó a la web", [], web.requests)

    # --- lo demás va a la web ---------------------------------------------------
    status, head, payload = await raw_http(port, [
        "GET /email/accounts?id=ventas HTTP/1.1", "Host: agente.ngrok.app",
        "X-Forwarded-For: 203.0.113.7", "X-Forwarded-Proto: https",
        "Cookie: paynani_web=abc", "Connection: keep-alive", "Keep-Alive: timeout=5",
        "Upgrade: h2c", "TE: trailers"])
    check("GET fuera de /sms/ -> respuesta de la web", (200, "/email/accounts?id=ventas"),
          (status, json.loads(payload).get("path")))
    check("la cabecera de la web llega al navegador (Set-Cookie)", ["s=1; HttpOnly"], headers_of(head).get("set-cookie"))
    sent = headers_of(web.requests[-1]["head"])
    check("la web recibe la línea de petición tal cual", "GET /email/accounts?id=ventas HTTP/1.1",
          web.requests[-1]["head"].split("\r\n", 1)[0])
    check("pasan Host, X-Forwarded-For, X-Forwarded-Proto y Cookie",
          (["agente.ngrok.app"], ["203.0.113.7"], ["https"], ["paynani_web=abc"]),
          (sent.get("host"), sent.get("x-forwarded-for"), sent.get("x-forwarded-proto"), sent.get("cookie")))
    check("no pasan Keep-Alive, Upgrade ni TE", (None, None, None),
          (sent.get("keep-alive"), sent.get("upgrade"), sent.get("te")))
    check("Connection: close, una sola vez", ["close"], sent.get("connection"))

    body = b"usuario=duena&clave=" + b"x" * 200_000
    status, _, payload = await raw_http(port, [
        "POST /login HTTP/1.1", "Host: x", "Content-Type: application/x-www-form-urlencoded",
        f"Content-Length: {len(body)}"], body)
    check("POST con cuerpo de 200 KB llega completo a la web", (200, len(body)),
          (status, json.loads(payload).get("body_len")))
    check("y byte por byte", body, web.requests[-1]["body"])

    status, _, payload = await raw_http(port, ["GET / HTTP/1.1", "Host: x"])
    check("/ va a la web", (200, "/"), (status, json.loads(payload).get("path")))
    status, _, payload = await raw_http(port, ["GET /smsx HTTP/1.1", "Host: x"])
    check("/smsx no es /sms/: va a la web", (200, "/smsx"), (status, json.loads(payload).get("path")))

    # --- el teléfono se sigue conectando -----------------------------------------
    st = store_mod.Store(state)
    code = st.new_code()
    pair_body = json.dumps({"code": code, "device": {"model": "Pixel", "android": "16", "app_version": "1.0"},
                            "sims": [{"slot": 0, "number": None}]}).encode()
    status, _, payload = await raw_http(port, ["POST /sms/pair HTTP/1.1", "Host: x",
                                               f"Content-Length: {len(pair_body)}"], pair_body)
    token = json.loads(payload).get("token", "")
    check("emparejar sigue funcionando con la web detrás", (201, True), (status, bool(token)))
    ws, ws_status = await wsm.connect("127.0.0.1", port, "/sms/ws", headers={"Authorization": f"Bearer {token}"},
                                      protocol="paynani-sms.v1")
    check("el WebSocket responde 101", 101, ws_status)
    await ws.send_text(json.dumps({"type": "hello", "protocol": 1, "device_id": json.loads(payload).get("device_id"),
                                   "app_version": "1.0"}))
    welcome = json.loads(await asyncio.wait_for(ws.recv(), 5))
    check("el WebSocket del teléfono no pasa por la web (welcome de la pasarela)", "welcome", welcome.get("type"))
    requests_before = len(web.requests)
    await ws.close()
    check("y la web no vio el WebSocket", requests_before, len(web.requests))

    # --- la web cierra sin responder: 502 ----------------------------------------
    web.mode = "silent"
    status, head, payload = await raw_http(port, ["GET /x HTTP/1.1", "Host: x"])
    check("la web acepta y cierra sin responder -> 502 en HTML", (502, True),
          (status, "text/html" in (headers_of(head).get("content-type") or [""])[0]))
    web.mode = "ok"

    # --- sin web: 503, y los SMS siguen ---------------------------------------------
    web.server.close()
    await web.server.wait_closed()
    status, head, payload = await raw_http(port, ["GET /roster HTTP/1.1", "Host: x"])
    check("sin web -> 503", 503, status)
    check("en HTML, sin nada de fuera", (True, False, False),
          ("text/html" in headers_of(head).get("content-type", [""])[0],
           b"http://" in payload or b"https://" in payload, b"<script" in payload))
    check("dice que los SMS siguen", True, "Los SMS y las llamadas".encode() in payload)
    check("con Cache-Control: no-store", ["no-store"], headers_of(head).get("cache-control"))
    check("la pasarela anota que la web cayó (para decirlo una vez en el log)", True, g.web_down)
    status, _, payload = await raw_http(port, ["GET /sms/health HTTP/1.1", "Host: x"])
    check("sin web, /sms/health sigue en 200", 200, status)

    # --- la web vuelve ----------------------------------------------------------------
    back = FakeWeb()
    back.server = await asyncio.start_server(back.handle, "127.0.0.1", web_port)
    status, _, payload = await raw_http(port, ["GET /vuelta HTTP/1.1", "Host: x"])
    check("la web vuelve: se reenvía de nuevo", (200, "/vuelta"), (status, json.loads(payload).get("path")))
    check("y web_down se apaga", False, g.web_down)
    back.server.close()

    server.close()
    await g.shutdown()

    # --- web_port=0: como antes de #434 ---------------------------------------------
    g0 = gw.Gateway(state, state / "events.jsonl", roster, web_port=0)
    server0 = await gw.serve(g0, "127.0.0.1", 0)
    port0 = server0.sockets[0].getsockname()[1]
    status, _, payload = await raw_http(port0, ["GET / HTTP/1.1", "Host: x"])
    check("web_port=0 -> 404 fuera de /sms/, como antes", (404, "not_found"), (status, json.loads(payload).get("error")))
    server0.close()
    await g0.shutdown()

    # --- el puerto se decide en un solo lugar --------------------------------------
    check("por omisión 8771", (8771, ""), sms_config.web_port(None, 8770, {}))
    check("PAYNANI_WEB_PORT del entorno", (9100, ""), sms_config.web_port(None, 8770, {"PAYNANI_WEB_PORT": "9100"}))
    check("--web-port gana al entorno", (9200, ""), sms_config.web_port(9200, 8770, {"PAYNANI_WEB_PORT": "9100"}))
    check("0 apaga", (0, ""), sms_config.web_port("0", 8770, {}))
    port_x, problem = sms_config.web_port("abc", 8770, {})
    check("un valor que no es número vuelve a 8771 y lo dice", (8771, True), (port_x, "no es un número" in problem))
    port_x, problem = sms_config.web_port("70000", 8770, {})
    check("fuera de rango vuelve a 8771 y lo dice", (8771, True), (port_x, "no es un puerto" in problem))
    port_x, problem = sms_config.web_port(None, 8771, {})
    check("la pasarela en 8771 (PAYNANI_SMS_PORT=8771) no se reenvía a sí misma", (0, True),
          (port_x, "mismo puerto" in problem))
    check("PAYNANI_WEB_PORT se lee de sms.env", True, "PAYNANI_WEB_PORT" in sms_config.KEYS)

    # --- y en el proceso real ----------------------------------------------------
    same = await free_port()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "scripts" / "sms_gateway.py"), "--port", str(same), "--web-port", str(same),
        "--state", str(state), "--roster", str(roster),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    lines = []
    try:
        while len(lines) < 20:
            line = await asyncio.wait_for(proc.stdout.readline(), 10)
            if not line:
                break
            lines.append(line.decode("utf-8", "replace"))
            if "escuchando en" in lines[-1]:
                break
        status, _, payload = await raw_http(same, ["GET / HTTP/1.1", "Host: x"])
        check("sms_gateway.py con --web-port igual a --port: 404, sin ciclo", 404, status)
        check("y lo dice en el log", True, any("mismo puerto" in line for line in lines))
    finally:
        proc.terminate()
        await proc.wait()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
