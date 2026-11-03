#!/usr/bin/env python3
"""
Tests for #670 FR-2 to FR-4: the paperclip in «Mensajes de WhatsApp». A real PaynaniWeb on
a free port talks to the real paynani-whatsapp service with the fake bridge (like
test_whatsapp_uploads.py), so the files go all the way: multipart POST → web_uploads.save
→ whatsapp.send with `uploads` → one bridge `send` per file → the thread → /whatsapp/media.
The cases follow test_web_telegram_flows.py (#666). An assertion script, like the rest of
this suite; at the end the real .env and Himalaya config must be untouched.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import http.client
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, auth, notify, users, whatsapp_source  # noqa: E402
from test_whatsapp_service import NUM, make, started, until  # noqa: E402

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


def real_env() -> Path:
    import paths
    try:
        return Path(paths.env_file())
    except Exception:  # noqa: BLE001
        return Path.home() / ".claude/workspace/.env"


REAL = [real_env(), Path.home() / ".config/himalaya/config.toml"]
BEFORE = [sha(p) for p in REAL]

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PASSWORD = "una-contraseña-larga"
HOST = "agente.test"

tmp = Path(tempfile.mkdtemp())
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()


def run(coro, timeout=20):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)


async def linked():
    svc = make(tmp, settings={"WHATSAPP_SEND_INTERVAL_S": "1"})
    await started(svc)
    await svc.sup.request("link", mode="qr")
    await svc.sup.request("fake.link_done", me="+15550009999")
    await svc.sup.request("fake.message", from_e164=NUM, text="hola", key_id="3EB0" + os.urandom(4).hex().upper())
    await until(lambda: NUM in svc.store.wrote_since_link())
    return svc


svc = run(linked())
state = tmp / "state"
wa_root = state / "whatsapp"
(tmp / "whatsapp.env").write_text("WHATSAPP_ENABLED=1\n", encoding="utf-8")
(tmp / "whatsapp.env").chmod(0o600)
src = whatsapp_source.ControlSocket(svc.socket_path, timeout=20)
uf = tmp / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, uf)
ctx = app.Context(uf, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", state_dir=state,
                  roster_path=tmp / "roster.md", whatsapp_source=src, whatsapp_root=tmp, telegram_root=tmp)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def multipart(fields: dict, files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = "----wauploads" + "5" * 16
    out = b""
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for name, data in files:
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + b"\r\n"
    return out + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def req(method, path, form=None, cookie="", files=None):
    from urllib.parse import urlencode
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.7"}
    body = None
    if cookie:
        h["Cookie"] = cookie
    if form is not None and files is not None:
        body, h["Content-Type"] = multipart(form, files)
        h["Origin"] = f"https://{HOST}"
    elif form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = f"https://{HOST}"
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    hdrs = {k.lower(): v for k, v in r.getheaders()}
    hdrs["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    c.close()
    return r.status, hdrs, data


def text(path, cookie):
    st, h, data = req("GET", path, cookie=cookie)
    return st, h, data.decode("utf-8", "replace")


def pending() -> list[str]:
    return sorted(p.name for p in (wa_root / "uploads").glob("up_*") if not p.name.endswith(".json"))


async def sends() -> list[dict]:
    return (await svc.sup.request("fake.sends"))["sends"]


i18n.set_current("es-MX")
th = i18n.th
VER = "/whatsapp/messages/ver?n=%2B15550001111&lang=es-MX"
try:
    _, h, _ = req("POST", "/login", {"email": "julian@example.com", "password": PASSWORD})
    ck = next(c for c in h["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]

    st, _, page = text(VER, ck)
    check("el servicio anuncia web_files y la barra trae el clip, multipart (FR-2)", (200, True, True, True, True),
          (st, src.status().get("web_files") is True, 'class="wc-adjuntar"' in page,
           'enctype="multipart/form-data"' in page, '<script src="/assets/adjuntos.js" defer></script>' in page))
    check("con el clip el cuadro no es required: se puede mandar sólo una foto", False,
          bool(re.search(r'<textarea id="wa-text"[^>]* required', page)))
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)

    before = len(run(sends()))
    st, h, _ = req("POST", "/whatsapp/messages/enviar", {"csrf": csrf, "n": NUM, "text": "La terraza y el menú"}, ck,
                   files=[("terraza.png", PNG), ("menu.pdf", PDF)])
    check("foto y PDF con texto → ok=sent (FR-3)", (303, True), (st, h.get("location", "").endswith("ok=sent#responder")))
    out = run(sends())[before:]
    check("dos send del puente, en orden, con el texto como pie del primero", (2, "La terraza y el menú", ""),
          (len(out), (out[0] if out else {}).get("text"), (out[1] if len(out) > 1 else {}).get("text")))
    check("los up_ se consumieron", [], pending())

    st, _, page = text(VER, ck)
    img = re.search(r'<img src="(/whatsapp/media\?id=wo_[0-9a-f]{32}&amp;i=0)"', page)
    check("en el hilo: la foto por /whatsapp/media con su índice y el PDF por su nombre (FR-4)", (True, True),
          (bool(img), '<span class="tg-archivo">' in page and "menu.pdf" in page))
    if img:
        st, hh, body = req("GET", img.group(1).replace("&amp;", "&"), cookie=ck)
        check("/whatsapp/media sirve la foto que mandó el dueño", (200, "image/png", PNG), (st, hh.get("content-type"), body))
        check("un índice que no existe: 404", 404, req("GET", img.group(1).replace("&amp;", "&").replace("i=0", "i=5"),
                                                    cookie=ck)[0])
    check("un id mal formado o un índice que no es número: 404", (404, 404),
          (req("GET", "/whatsapp/media?id=wo_" + "0" * 32 + "&i=x", cookie=ck)[0],
           req("GET", "/whatsapp/media?id=wo_123&i=0", cookie=ck)[0]))

    import time
    time.sleep(1.2)   # FR-21 en la prueba: 1 envío por segundo; el primero no espera, se rechaza
    st, h, _ = req("POST", "/whatsapp/messages/enviar", {"csrf": csrf, "n": NUM, "text": ""}, ck, files=[("sola.png", PNG)])
    check("sólo una foto, sin texto, también sale", (303, True), (st, h.get("location", "").endswith("ok=sent#responder")))

    st, _, page = req("POST", "/whatsapp/messages/enviar", {"csrf": csrf, "n": NUM, "text": "x"}, ck,
                      files=[("virus.exe", b"MZ\x90\x00" + b"\x00" * 64)])
    check("un tipo que no se acepta: 400 con su mensaje, sin dejar up_", (400, True, []),
          (st, th("web.wa.err.bad_type") in page.decode(), pending()))
    st, _, page = req("POST", "/whatsapp/messages/enviar", {"csrf": csrf, "n": NUM, "text": "x"}, ck,
                      files=[(f"f{i}.png", PNG) for i in range(11)])
    check("11 archivos: too_many antes de subir nada", (400, True, []),
          (st, th("web.wa.err.too_many") in page.decode(), pending()))

    real_slow = src.request_slow
    seen: list[str] = []

    def partial(kind, **fields):
        seen.extend(fields["uploads"])
        raise whatsapp_source.Failed("unavailable", sent_uploads=fields["uploads"][:1])

    src.request_slow = partial
    st, _, page = req("POST", "/whatsapp/messages/enviar", {"csrf": csrf, "n": NUM, "text": "x"}, ck,
                      files=[("salio.png", PNG), ("falto.pdf", PDF)])
    check("envío parcial: dice cuáles ya salieron", (503, True), (st, "Ya salieron: salio.png." in page.decode()))
    check("un fallo definitivo borra el up_ que no salió", False, (wa_root / "uploads" / seen[-1]).exists())

    def cut(kind, **fields):
        raise whatsapp_source.Failed("timeout")

    src.request_slow = cut
    left = pending()
    st, _, page = req("POST", "/whatsapp/messages/enviar", {"csrf": csrf, "n": NUM, "text": "x"}, ck,
                      files=[("tarde.png", PNG)])
    check("el servicio corta por tiempo: aviso de revisar el hilo, sin borrar el up_", (504, True, len(left) + 1),
          (st, th("web.wa.err.send_unknown") in page.decode(), len(pending())))
    src.request_slow = real_slow

    mudo = tmp / "mudo.sock"
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(mudo))
    s.listen(1)
    try:
        whatsapp_source.ControlSocket(mudo, timeout=0.3).request("whatsapp.status")
        timed = None
    except whatsapp_source.Failed as exc:
        timed = (exc.code, exc.fields.get("timed_out"))
    s.close()
    check("ControlSocket: un servicio que no contesta a tiempo es unavailable con timed_out", ("unavailable", True), timed)
    check("request_slow espera más que una consulta", True,
          whatsapp_source.ControlSocket(mudo).SLOW_TIMEOUT > whatsapp_source.ControlSocket(mudo).timeout)
finally:
    httpd.shutdown()
    run(svc.stop())

check("el .env y Himalaya de la instalación no cambiaron", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
