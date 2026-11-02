#!/usr/bin/env python3
"""
Tests de Webchat en PaynaniWeb (#648): la página pide sesión; «Webchat» va en la sección
«AI Agent» debajo del agente; los mensajes y adjuntos van con multipart, CSRF y los
límites del contrato; `/webchat/updates` trae lo nuevo ya dibujado y «escribiendo…»; los
adjuntos salen por `/webchat/file?ref=f_…` (las fotos inline y lo demás como descarga,
siempre en sandbox); sin el almacén del núcleo la página lo dice. Y el lector de
multipart por sí solo.

Todo con `webchat_source.Fake` y un `dashboard.Fake`; al final se comprueba el sha256 del
`.env` y de Himalaya de la instalación.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import secrets
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, auth, dashboard, multipart, notify, users, webchat_source, webchat_strings  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


REAL = [Path.home() / ".claude/workspace/.env", Path.home() / ".config/himalaya/config.toml"]
BEFORE = [sha(p) for p in REAL]
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def form(fields: dict, files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    """Un cuerpo multipart/form-data: `files` es `[(campo, nombre, mime, bytes)]`."""
    boundary = "----paynani" + secrets.token_hex(8)
    out = b""
    for name, value in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n").encode() + value.encode() + b"\r\n"
    for field, name, mime, data in files:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{name}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


# ---- El lector de multipart --------------------------------------------------------
raw, ctype = form({"csrf": "abc", "text": "Hola ñ"},
                  [("files", "../../carpeta/menú.png", "image/png", PNG), ("files", "", "application/octet-stream", b"")])
fields, files = multipart.parse(raw, ctype)
check("multipart: los campos de texto, en UTF-8", {"csrf": "abc", "text": "Hola ñ"}, fields)
check("multipart: el archivo con sus bytes y sólo el último tramo del nombre; el input vacío no cuenta",
      [("menú.png", "image/png", PNG)], [(f["name"], f["mime"], f["data"]) for f in files])
for bad in ("text/plain", "multipart/form-data"):
    try:
        multipart.parse(raw, bad)
        check(f"multipart: {bad} sin boundary se rechaza", True, False)
    except multipart.Malformed:
        check(f"multipart: {bad} sin boundary se rechaza", True)

# ---- La web --------------------------------------------------------------------------
PASSWORD = "una-contraseña-larga"
tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
user_file = tmp / "web" / "user.json"
users.create("julian@example.com", "Julián <Flores>", PASSWORD, user_file)
store = webchat_source.Fake()
STORE = {"now": store}
agent_src = dashboard.Fake(agent={"name": "Iris", "email": "iris@example.com", "runtime": "claudecode"})


class Switch:
    """Deja cambiar el almacén a media prueba (o quitarlo)."""
    def __getattr__(self, name):
        return getattr(STORE["now"], name)


ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda l: None),
                  agent_email="iris@example.com", accounts_file=tmp / "accounts.json", state_dir=tmp / "state",
                  roster_path=tmp / "roster.md", dashboard_source=agent_src, webchat_store=Switch())
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, body=None, ctype=None, cookie="", origin=True, length=None):
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.5"}
    if cookie:
        h["Cookie"] = cookie
    if body is not None:
        h["Content-Type"] = ctype or "application/x-www-form-urlencoded"
        if origin:
            h["Origin"] = f"https://{HOST}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    if length is not None:
        conn.putrequest(method, path)
        for k, v in h.items():
            conn.putheader(k, v)
        conn.putheader("Content-Length", str(length))
        conn.endheaders()
    else:
        conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


def text(path, cookie):
    status, hdrs, data = req("GET", path, cookie=cookie)
    return status, hdrs, data.decode("utf-8", "replace")


for path in ("/webchat", "/webchat/updates?after=", "/webchat/file?ref=f_" + "0" * 32):
    status, hdrs, _ = req("GET", path)
    check(f"sin sesión, {path.split('?')[0]} va a la entrada", (303, True), (status, hdrs.get("location", "").startswith("/login")))
_, hdrs, _ = req("POST", "/login", body=urlencode({"email": "julian@example.com", "password": PASSWORD}))
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]

status, _, page = text("/webchat?lang=en-US", cookie)
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
side = page.split('<aside class="lateral"', 1)[1].split("</aside>", 1)[0]
order = [side.find(m) for m in ('<div class="grupo">AI Agent</div>', 'class="agente-entrada"', 'href="/webchat"',
                                '<div class="grupo">Management</div>')]
check("«Webchat» va en la sección «AI Agent», debajo del agente y arriba de Management", True,
      -1 not in order and order == sorted(order))
check("en /webchat la entrada está activa y la del agente no", (True, False),
      ('<a href="/webchat" class="activo" aria-current="page">' in side, "agente-entrada activo" in side))
check("/webchat: 200, título, sin mensajes todavía, el formulario multipart", (200, True, True, True),
      (status, "<h1>Webchat</h1>" in page, "No messages yet" in page, 'enctype="multipart/form-data"' in page))
check("el script de la página se carga con defer y se sirve", (True, 200),
      ('<script src="/assets/webchat.js" defer></script>' in page, req("GET", "/assets/webchat.js")[0]))
check("sin atributos style", [], re.findall(r'\sstyle="', page))
check("Q321: una sola barra; el clip abre «Photo» y «File», dos inputs de archivos", (True, 2, True, True),
      ('<details class="wc-adjuntar">' in page, page.count('name="files" class="wc-archivos"'),
       'accept="image/jpeg,image/png,image/webp,image/gif"' in page, '<span>File</span>' in page))
check("los límites se ven dentro del menú del clip (en el celular no hay hover)", True,
      '<p class="wc-menu-nota">Files and photos up to 20 MB per message.' in page)
check("Q321: el cuadro empieza en una línea y «Send» es un botón redondo con su nombre", (True, True),
      ('<textarea name="text" rows="1"' in page, 'class="wc-enviar" aria-label="Send"' in page))


def send(fields, files=(), origin=True):
    body, ct = form(fields, list(files))
    return req("POST", "/webchat/enviar?lang=en-US", body=body, ctype=ct, cookie=cookie, origin=origin)


status, _, _ = send({"csrf": "malo", "text": "hola"})
check("CSRF malo: 403 y no se guarda nada", (403, 0), (status, len(store.items)))
status, _, _ = send({"csrf": csrf, "text": "hola"}, origin=False)
check("sin Origin: 403", 403, status)
status, hdrs, _ = send({"csrf": csrf, "text": "  Revisa <esto>  "},
                       [("files", "menu.png", "image/png", PNG), ("files", "lista.pdf", "application/pdf", b"%PDF-1.4 x")])
msg = store.items[-1] if store.items else {}
check("texto con una foto y un PDF: 303 a /webchat y queda guardado como del dueño", (303, "/webchat", "owner", "Revisa <esto>"),
      (status, hdrs.get("location"), msg.get("by"), msg.get("text")))
check("los adjuntos: foto como image y PDF como document", [("menu.png", "image"), ("lista.pdf", "document")],
      [(f["name"], f["kind"]) for f in msg.get("files", [])])
check("el evento lleva al dueño de la sesión", {"name": "Julián <Flores>", "email": "julian@example.com"},
      store.events[-1]["owner"] if store.events else None)
status, _, _ = req("POST", "/webchat/enviar", body=urlencode({"csrf": csrf, "text": "sin archivos"}), cookie=cookie)
check("un formulario normal (sin multipart) también manda texto", (303, "sin archivos"), (status, store.items[-1]["text"]))

for label, fields, files, code, err in (
        ("vacío", {"csrf": csrf, "text": "   "}, [], 400, "Write a message or attach a file."),
        ("texto de más de 4000", {"csrf": csrf, "text": "x" * 4001}, [], 400, "The message is too big"),
        ("tipo no aceptado", {"csrf": csrf, "text": "a"}, [("files", "a.exe", "application/octet-stream", b"MZ\x90\x00\xff\xfe")],
         400, "That kind of file cannot be sent")):
    n = len(store.items)
    status, _, data = send(fields, files)
    body = data.decode()
    check(f"{label}: {code}, el error y nada guardado", (code, True, n), (status, err in body, len(store.items)))
status, _, data = req("POST", "/webchat/enviar", body=b"--x\r\nbasura", ctype="multipart/form-data; boundary=y", cookie=cookie)
check("multipart roto: 400 o 403, nada guardado", True, status in (400, 403))
status, _, _ = req("POST", "/webchat/enviar", body=b"", ctype="multipart/form-data; boundary=x", cookie=cookie,
                   length=app.WEBCHAT_BODY_BYTES + 1)
check("un cuerpo más grande que el límite: 413 antes de leerlo", 413, status)

# ---- Lo nuevo sin recargar ----------------------------------------------------------
last = store.items[-1]["id"]
status, hdrs, data = req("GET", f"/webchat/updates?after={last}&day=2026-11-01", cookie=cookie)
upd = json.loads(data)
check("updates sin nada nuevo: html vacío, el mismo after y JSON", (200, "", last, True),
      (status, upd["html"], upd["after"], hdrs.get("content-type", "").startswith("application/json")))
store.typing(60)
check("updates con el agente escribiendo: typing", True, json.loads(req("GET", f"/webchat/updates?after={last}", cookie=cookie)[2])["typing"])
reply = store.append("agent", "Listo <ok>", [("corregida.pdf", b"%PDF-1.4 y")])
upd = json.loads(req("GET", f"/webchat/updates?after={last}", cookie=cookie)[2])
check("updates trae la respuesta ya dibujada, escapada, con su tarjeta, y quita «escribiendo»",
      (True, True, True, reply["id"], False),
      ('class="wc wc-agente"' in upd["html"], "Listo &lt;ok&gt;" in upd["html"], "corregida.pdf" in upd["html"],
       upd["after"], upd["typing"]))
check("updates con un after que no tiene forma de id: nada", "",
      json.loads(req("GET", "/webchat/updates?after=../../x", cookie=cookie)[2])["html"])
status, _, page = text("/webchat?lang=en-US", cookie)
check("la página muestra la conversación: el texto escapado y el nombre del agente", (True, True, True),
      ("Revisa &lt;esto&gt;" in page, '<div class="de">Iris</div>' in page, 'data-after="' + reply["id"] in page))

# ---- Los adjuntos ------------------------------------------------------------------
photo, pdf = msg["files"][0]["ref"], msg["files"][1]["ref"]
status, hdrs, data = req("GET", f"/webchat/file?ref={photo}", cookie=cookie)
check("la foto: inline como image/png, en sandbox y sin caché", (200, "image/png", True, True, PNG),
      (status, hdrs.get("content-type"), hdrs.get("content-disposition", "").startswith("inline"),
       "sandbox" in hdrs.get("content-security-policy", ""), data))
check("con nosniff", "nosniff", hdrs.get("x-content-type-options"))
status, hdrs, _ = req("GET", f"/webchat/file?ref={pdf}", cookie=cookie)
check("el PDF: como descarga (attachment) y octet-stream, con su nombre", (200, "application/octet-stream", True),
      (status, hdrs.get("content-type"), hdrs.get("content-disposition", "").startswith("attachment; filename*=UTF-8''lista.pdf")))
for bad in ("../../etc/passwd", "f_123", "f_" + "a" * 32):
    check(f"un ref inválido o desconocido ({bad[:12]}…): 404", 404, req("GET", f"/webchat/file?ref={bad}", cookie=cookie)[0])

# ---- /webchat/ws (Q309 = A) -----------------------------------------------------------
import base64 as _b64
import os as _os
import socket as _socket
import struct as _struct
import time as _time
from paynani_lib.web import websocket as wsmod  # noqa: E402


def ws_open(cookie_value=cookie, origin=f"https://{HOST}", key=None, version="13"):
    """Abre /webchat/ws a mano. Devuelve (status, headers, socket) del handshake."""
    key = key if key is not None else _b64.b64encode(_os.urandom(16)).decode()
    sock = _socket.create_connection(("127.0.0.1", port), timeout=5)
    lines = ["GET /webchat/ws HTTP/1.1", f"Host: {HOST}", "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Key: {key}", f"Sec-WebSocket-Version: {version}", "X-Forwarded-For: 203.0.113.5"]
    if cookie_value:
        lines.append(f"Cookie: {cookie_value}")
    if origin:
        lines.append(f"Origin: {origin}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(1)
        if not chunk:
            break
        head += chunk
    first, *rest = head.decode("latin-1").split("\r\n")
    hdrs = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in rest if ":" in l}
    return int(first.split()[1]) if first else 0, hdrs, sock, key


def ws_send(sock, obj, op=1):
    payload = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
    mask = _os.urandom(4)
    n = len(payload)
    head = bytes([0x80 | op]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + _struct.pack("!H", n))
    sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def ws_read(sock, seconds=3.0):
    """Los frames del servidor que lleguen en `seconds`: [(opcode, dict|bytes)]."""
    out, buf, end = [], b"", _time.time() + seconds
    sock.settimeout(0.2)
    while _time.time() < end:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        except _socket.timeout:
            pass
        while len(buf) >= 2:
            op, n, i = buf[0] & 0x0F, buf[1] & 0x7F, 2
            if n == 126:
                n, i = _struct.unpack("!H", buf[2:4])[0], 4
            if len(buf) < i + n:
                break
            data, buf = buf[i:i + n], buf[i + n:]
            out.append((op, json.loads(data) if op == 1 else data))
    return out


def types(frames):
    return [f[1].get("type") for f in frames if f[0] == 1]


# Un frame a medias (revisión de Metis en #650): `Closed`, nunca TypeError ni None.
for label, partial in (("la longitud de 16 bits", bytes([0x81, 0xFE])), ("la máscara", bytes([0x81, 0x85, 1, 2])),
                       ("los datos", bytes([0x81, 0x85]) + b"\x00\x00\x00\x00" + b"ab")):
    a, b = _socket.socketpair()
    conn = wsmod.Conn(a)
    b.sendall(partial)
    t0 = _time.time()
    try:
        conn.recv(1.0)
        result = "sin error"
    except wsmod.Closed:
        result = "Closed"
    except Exception as exc:  # noqa: BLE001
        result = type(exc).__name__
    check(f"frame cortado en {label}: Closed", "Closed", result)
    a.close(); b.close()
a, b = _socket.socketpair()
conn = wsmod.Conn(a)
mask = b"\x00\x00\x00\x00"
b.sendall(bytes([0x01, 0x82]) + mask + b"ho")          # primer fragmento, sin FIN, y nada más
try:
    conn.recv(1.0)
    result = "sin error"
except wsmod.Closed:
    result = "Closed"
check("un mensaje partido que no termina: Closed (no se pierden partes en silencio)", "Closed", result)
a.close(); b.close()
a, b = _socket.socketpair()
conn = wsmod.Conn(a)
check("sin bytes en el plazo, entre mensajes: None (no es un error)", None, conn.recv(0.2))
a.close(); b.close()

from paynani_lib.web import webchat_ws  # noqa: E402
sig_root = Path(tempfile.mkdtemp()) / "webchat"
sig_root.mkdir()
sig_store = type("S", (), {"root": staticmethod(lambda: sig_root)})()
first = webchat_ws.signature(sig_store)
check("la firma no cambia si nada cambió", first, webchat_ws.signature(sig_store))
(sig_root / "messages.jsonl").write_text("{}\n")
check("y cambia cuando cambia messages.jsonl", True, webchat_ws.signature(sig_store) != first)
check("un almacén sin root(): sin firma (se relee siempre)", None, webchat_ws.signature(webchat_source.Fake()))

status, _, s1, _ = ws_open(cookie_value="")
check("WebSocket sin sesión: no hay 101 (va a la entrada)", True, status != 101)
s1.close()
status, _, s1, _ = ws_open(origin="https://otro.example")
check("WebSocket desde otro Origin: 403", 403, status)
s1.close()
status, _, s1, _ = ws_open(key="corta")
check("WebSocket con una llave inválida: 400", 400, status)
s1.close()
status, hdrs, sock, key = ws_open()
check("handshake: 101 con el Sec-WebSocket-Accept del RFC", (101, wsmod.accept_key(key)),
      (status, hdrs.get("sec-websocket-accept")))
ws_send(sock, {"type": "connect", "csrf": "malo"})
frames = ws_read(sock, 1.0)
check("connect con un CSRF malo: el servidor cierra (1008)", True, any(op == 8 for op, _ in frames))
sock.close()

status, _, sock, _ = ws_open()
last = store.items[-1]["id"]
ws_send(sock, {"type": "connect", "csrf": csrf, "after": last, "day": "2026-11-01"})
frames = ws_read(sock, 1.5)
check("connect bueno: connected y el estado de typing", ["connected", "typing"], types(frames)[:2])
n = len(store.items)
ws_send(sock, {"type": "message.create", "request_id": "r1", "content": "  Hola <ws>  "})
frames = ws_read(sock, 2.0)
acc = [f[1] for f in frames if f[0] == 1 and f[1].get("type") == "message.accepted"]
msgs = [f[1] for f in frames if f[0] == 1 and f[1].get("type") == "messages"]
check("message.create: se guarda una vez como del dueño, con accepted y su burbuja empujada", (n + 1, "owner", "Hola <ws>", True, True),
      (len(store.items), store.items[-1]["by"], store.items[-1]["text"], bool(acc) and acc[0]["message_id"] == store.items[-1]["id"],
       bool(msgs) and "Hola &lt;ws&gt;" in msgs[0]["html"]))
ws_send(sock, {"type": "message.create", "request_id": "r1", "content": "Hola <ws>"})
frames = ws_read(sock, 1.0)
check("el mismo request_id otra vez: accepted con el mismo id y nada nuevo guardado", (n + 1, ["message.accepted"]),
      (len(store.items), types(frames)))
ws_send(sock, {"type": "message.create", "request_id": "r2", "content": "   "})
err = [f[1] for f in ws_read(sock, 1.0) if f[0] == 1 and f[1].get("type") == "error"]
check("vacío: error EMPTY, no reintentable", ("EMPTY", False), (err[0]["code"], err[0]["retryable"]) if err else None)
ws_send(sock, b"no es json")
err = [f[1] for f in ws_read(sock, 1.0) if f[0] == 1 and f[1].get("type") == "error"]
check("un frame que no es JSON: INVALID_JSON", "INVALID_JSON", err[0]["code"] if err else None)
ws_send(sock, {"type": "ping"})
check("ping de la aplicación: pong", True, "pong" in types(ws_read(sock, 1.0)))
store.draft_set("Voy a<")
frames = ws_read(sock, 2.0)
check("el borrador del agente llega como message.delta (texto plano, el navegador lo pone con textContent)",
      True, any(f[1].get("type") == "message.delta" and f[1].get("text") == "Voy a<" for f in frames if f[0] == 1))
store.append("agent", "Voy a revisar", [])
frames = ws_read(sock, 2.0)
check("la respuesta final: messages con la burbuja y el borrador se quita (delta null)", (True, True),
      (any(f[1].get("type") == "messages" and "Voy a revisar" in f[1]["html"] for f in frames if f[0] == 1),
       any(f[1].get("type") == "message.delta" and f[1].get("text") is None for f in frames if f[0] == 1)))
for i in range(25):
    ws_send(sock, {"type": "message.create", "request_id": f"rate{i}", "content": f"m{i}"})
frames = ws_read(sock, 3.0)
check("más de 20 mensajes en un minuto: RATE_LIMITED, reintentable", True,
      any(f[1].get("code") == "RATE_LIMITED" and f[1].get("retryable") for f in frames if f[0] == 1))
ws_send(sock, b"", op=8)
sock.close()

# ---- Sin el almacén del núcleo --------------------------------------------------------
STORE["now"] = None
ctx.webchat = None
status, _, page = text("/webchat?lang=en-US", cookie)
check("sin el almacén: la página lo dice y no ofrece escribir", (200, True, False),
      (status, "Webchat is not available on this install yet" in page, "wc-escribir" in page))
check("sin el almacén: updates y file dan 404", (404, 404),
      (req("GET", "/webchat/updates?after=", cookie=cookie)[0], req("GET", f"/webchat/file?ref={photo}", cookie=cookie)[0]))
ctx.webchat = Switch()
STORE["now"] = store

for lang in webchat_strings.STRINGS:
    status, _, page = text(f"/webchat?lang={lang}", cookie)
    check(f"{lang}: sin claves sin traducir", (200, []), (status, re.findall(r"web\.(?:wc|agent)\.[a-z_.]+", page)))
i18n.set_current("es-MX")

httpd.shutdown()
check("el .env y Himalaya de la instalación no cambiaron", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
