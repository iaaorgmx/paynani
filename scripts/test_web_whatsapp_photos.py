#!/usr/bin/env python3
"""
Tests for WhatsApp photos in PaynaniWeb (#573, PRD #550 FR-16a). An assertion script,
like the rest of this suite.

Un PaynaniWeb real con la sesión iniciada y el servicio paynani-whatsapp con el puente
falso, hablando por control.sock como en la instalación. Las fotos son archivos que el
propio test deja en state/whatsapp/media/, como los dejaría el puente.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import os
import re
import struct
import sys
import tempfile
import threading
import zlib
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import api_tokens, app, auth, notify, users, whatsapp_source  # noqa: E402
from paynani_lib.whatsapp import media as wa_store  # noqa: E402
from paynani_lib.whatsapp.service import WhatsAppService  # noqa: E402

FAKE = [sys.executable, str(ROOT / "scripts" / "whatsapp_bridge" / "fake_bridge.py")]
NUM = "+15550001111"      # en el roster
OTHER = "+15550002222"    # fuera del roster
PASSWORD = "una-contraseña-larga"
ROSTER = f"""# roster de prueba

# 1. Approved contacts

| Name | Email | Type | GitHub | Phone |
|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | {NUM} |
"""
FAST = dict(backoff_s=(0.05, 0.1, 0.2), stable_s=60, health_down_s=0.6, ping_every_s=0.3, reply_timeout_s=3.0)
HOST = "agente.ngrok.app"

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def png_bytes() -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 64 + b"\xff\xd9"
PNG = png_bytes()

tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
(clone / "rules").mkdir(parents=True)
roster = clone / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
state = clone / "state"
state.mkdir()
wa_root = tmp / "config"
wa_root.mkdir()
(wa_root / "whatsapp.env").write_text("WHATSAPP_ENABLED=1\n")
catch_all = clone / "rules" / "catch-all.md"

user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "accounts.json",
                  ledger_path=state / "lifecycle.jsonl", env_path=clone / "no.env", state_dir=state,
                  roster_path=roster, roster_notifier=lambda *a: None,
                  whatsapp_source=whatsapp_source.ControlSocket(state / "whatsapp" / "control.sock", timeout=5),
                  whatsapp_root=wa_root)
reader, _ = api_tokens.create("lector", permissions=["read"], path=api_tokens.path_for(user_file))
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def req(method, path, *, form=None, cookie="", raw=False):
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.5"}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = f"https://{HOST}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, (data if raw else data.decode("utf-8", "replace"))


def api(action, **params):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", "/api/agent", body=json.dumps({"action": action, **params}),
                 headers={"Host": HOST, "X-Forwarded-For": "203.0.113.9", "Authorization": "Bearer " + reader,
                          "Content-Type": "application/json"})
    r = conn.getresponse()
    out = r.read().decode()
    conn.close()
    return r.status, out


def login():
    _, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
    return next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


def media_file(body: bytes, ext: str) -> dict:
    """Un archivo en media/ como lo deja el puente: su sha256 como nombre."""
    sha = hashlib.sha256(body + os.urandom(8)).hexdigest()
    path = state / "whatsapp" / "media" / f"{sha}.{ext}"
    path.write_bytes(body)
    os.chmod(path, 0o600)
    return {"path": str(path), "mime": "image/jpeg" if ext == "jpg" else "image/png", "bytes": len(body),
            "sha256": sha}


def image_url(mid: str) -> str:
    return "/whatsapp/media?id=" + quote(mid, safe="")


async def main() -> None:
    svc = WhatsAppService(state, roster_path=roster, rules_root=clone, command=FAKE,
                          settings={"WHATSAPP_SEND_INTERVAL_S": "1"}, log=lambda line: None, supervisor_opts=FAST)
    await svc.start()
    await asyncio.wait_for(svc.sup.ready.wait(), 5)
    call = lambda *a, **k: asyncio.to_thread(req, *a, **k)  # noqa: E731
    try:
        await svc.sup.request("link", mode="qr")
        await svc.sup.request("fake.link_done", me="+15550009999")

        async def photo(sender, media, key, text=None):
            await svc.sup.request("fake.message", from_e164=sender, kind="image", text=text, media=media, key_id=key)
            for _ in range(100):
                for m in svc.store.received():
                    if m.get("key_id") == key:
                        return m["event_id"]
                await asyncio.sleep(0.05)
            raise AssertionError("no llegó " + key)

        roster_photo = await photo(NUM, media_file(JPEG, "jpg"), "3EB0F001", text="el ticket")
        roster_png = await photo(NUM, media_file(PNG, "png"), "3EB0F002")
        hidden_photo = await photo(OTHER, media_file(JPEG, "jpg"), "3EB0F003")
        catch_all.write_text("---\nversion: 1\nenabled: true\n---\n\nAvísale a Julián.\n")
        catch_photo = await photo(OTHER, media_file(JPEG, "jpg"), "3EB0F004")
        cookie = await asyncio.to_thread(login)

        # --- un contacto del roster ----------------------------------------------------
        status, hdrs, body = await call("GET", image_url(roster_photo), cookie=cookie, raw=True)
        check("foto del roster: 200 con los mismos bytes", (200, JPEG), (status, body))
        check("foto del roster: tipo por los primeros bytes", "image/jpeg", hdrs.get("content-type"))
        check("foto del roster: no-store, nosniff e inline",
              (True, "nosniff", "inline"),
              ("no-store" in hdrs.get("cache-control", ""), hdrs.get("x-content-type-options"),
               hdrs.get("content-disposition")))
        check("foto del roster: la respuesta no puede correr nada (CSP sandbox)", True,
              "sandbox" in hdrs.get("content-security-policy", ""))
        status, hdrs, body = await call("GET", image_url(roster_png), cookie=cookie, raw=True)
        check("un PNG sale como image/png", (200, "image/png"), (status, hdrs.get("content-type")))

        status, _, page = await call("GET", "/whatsapp/messages/ver?n=" + quote(NUM, safe=""), cookie=cookie)
        check("el hilo muestra la foto con la URL de su mensaje", True,
              f'src="{image_url(roster_photo)}"'.replace("&", "&amp;") in page)
        check("el hilo abre la foto completa en otra pestaña", True,
              re.search(r'<a class="wa-foto" href="[^"]+" target="_blank" rel="noopener">', page) is not None)
        check("el pie de la foto sigue debajo", True, '<span class="wa-pie">el ticket</span>' in page)
        check("el hilo no trae rutas ni nombres de archivo", (False, False),
              ("whatsapp/media/" in page.replace("/whatsapp/media?id=", ""), ".jpg" in page))

        # --- fuera del roster ------------------------------------------------------------
        nf_status, nf_hdrs, nf_body = await call("GET", image_url("wa:15550009999:" + "0" * 64), cookie=cookie,
                                                 raw=True)
        check("un id que no existe: 404", 404, nf_status)
        status, hdrs, body = await call("GET", image_url(hidden_photo), cookie=cookie, raw=True)
        check("fuera del roster sin Catch-All: el mismo 404 que uno inexistente", (404, nf_body, nf_hdrs.get(
            "content-type")), (status, body, hdrs.get("content-type")))
        status, _, body = await call("GET", image_url(catch_photo), cookie=cookie, raw=True)
        check("fuera del roster con el Catch-All activo: se sirve", (200, JPEG), (status, body))
        catch_all.unlink()
        status, _, body = await call("GET", image_url(catch_photo), cookie=cookie, raw=True)
        check("Catch-All apagado después: la misma URL ya no sirve la foto", (404, nf_body), (status, body))
        status, _, page = await call("GET", "/whatsapp/messages/ver?n=" + quote(OTHER, safe=""), cookie=cookie)
        check("el hilo de fuera del roster no trae ninguna foto", False, "/whatsapp/media?id=" in page)

        # --- la ruta guardada no se confía -------------------------------------------------
        outside = state / "whatsapp" / "outbox" / ("a" * 64 + ".jpg")
        outside.write_bytes(JPEG)
        outside_photo = await photo(NUM, {"path": str(outside), "mime": "image/jpeg", "bytes": len(JPEG)},
                                    "3EB0F005")
        status, _, body = await call("GET", image_url(outside_photo), cookie=cookie, raw=True)
        check("un archivo regular fuera de media/: el mismo 404", (404, nf_body), (status, body))

        target = tmp / "fuera.jpg"
        target.write_bytes(JPEG)
        link = state / "whatsapp" / "media" / ("b" * 64 + ".jpg")
        link.symlink_to(target)
        link_photo = await photo(NUM, {"path": str(link), "mime": "image/jpeg", "bytes": len(JPEG)}, "3EB0F006")
        status, _, body = await call("GET", image_url(link_photo), cookie=cookie, raw=True)
        check("un enlace simbólico dentro de media/: el mismo 404", (404, nf_body), (status, body))
        check("el destino del enlace no se toca", JPEG, target.read_bytes())

        fake_jpg = media_file(b"<html><script>alert(1)</script></html>", "jpg")
        fake_photo = await photo(NUM, fake_jpg, "3EB0F007")
        status, _, body = await call("GET", image_url(fake_photo), cookie=cookie, raw=True)
        check("un archivo que no es imagen aunque diga .jpg: el mismo 404", (404, nf_body), (status, body))

        gone = media_file(JPEG, "jpg")
        gone_photo = await photo(NUM, gone, "3EB0F008")
        os.unlink(gone["path"])
        status, _, body = await call("GET", image_url(gone_photo), cookie=cookie, raw=True)
        check("el archivo ya no está: el mismo 404", (404, nf_body), (status, body))

        big = media_file(b"\xff\xd8\xff" + b"\x00" * (wa_store.IMAGE_MAX_BYTES + 1), "jpg")
        big_photo = await photo(NUM, big, "3EB0F009")
        status, _, body = await call("GET", image_url(big_photo), cookie=cookie, raw=True)
        check("más grande que el tope: el mismo 404", (404, nf_body), (status, body))

        text_mid = None
        await svc.sup.request("fake.message", from_e164=NUM, text="sólo texto", key_id="3EB0F010")
        for _ in range(100):
            text_mid = next((m["event_id"] for m in svc.store.received() if m.get("key_id") == "3EB0F010"), None)
            if text_mid:
                break
            await asyncio.sleep(0.05)
        status, _, body = await call("GET", image_url(text_mid), cookie=cookie, raw=True)
        check("un mensaje que no es foto: el mismo 404", (404, nf_body), (status, body))

        for bad in ("", "../../etc/passwd", "wa:x:../" + "0" * 61, roster_photo + "/../x", "wa:1:" + "g" * 64):
            status, _, body = await call("GET", image_url(bad), cookie=cookie, raw=True)
            check(f"id inválido {bad[:24]!r}: el mismo 404", (404, nf_body), (status, body))

        roster.write_text(ROSTER.replace(f"| Julián Flores | julian@example.com | Human | julianflores | {NUM} |\n", ""),
                          encoding="utf-8")
        status, _, body = await call("GET", image_url(roster_photo), cookie=cookie, raw=True)
        check("el contacto sale del roster: la misma URL ya no sirve su foto", (404, nf_body), (status, body))
        roster.write_text(ROSTER, encoding="utf-8")
        status, _, body = await call("GET", image_url(roster_photo), cookie=cookie, raw=True)
        check("vuelve al roster: se sirve otra vez", (200, JPEG), (status, body))

        # --- sin sesión, sin WhatsApp, sin servicio ---------------------------------------
        status, _, body = await call("GET", image_url(roster_photo), raw=True)
        check("sin sesión: no se sirve la foto", (True, False), (status in (302, 303, 401, 403), body == JPEG))
        (wa_root / "whatsapp.env").write_text("WHATSAPP_ENABLED=0\n")
        status, _, body = await call("GET", image_url(roster_photo), cookie=cookie, raw=True)
        check("WhatsApp apagado: 404 y sin la foto", (404, False), (status, body == JPEG))
        (wa_root / "whatsapp.env").write_text("WHATSAPP_ENABLED=1\n")

        # --- la API no da archivos --------------------------------------------------------
        status, out = await asyncio.to_thread(api, "GetWhatsAppThread", number=NUM)
        msgs = json.loads(out).get("messages") or []
        leaked = [m for m in msgs if "data" in m or "path" in (m.get("media") or {}) or "data" in (m.get("media") or {})]
        check("GetWhatsAppThread sigue sin bytes ni rutas", (200, True, [], False),
              (status, len(msgs) > 0, leaked, "whatsapp/media/" in out))

        await svc.stop()
        status, _, body = await call("GET", image_url(roster_photo), cookie=cookie, raw=True)
        check("servicio caído: 503, sin la foto", (503, False), (status, body == JPEG))
    finally:
        await svc.stop()


check("image_mime: JPEG", "image/jpeg", wa_store.image_mime(JPEG[:16]))
check("image_mime: PNG", "image/png", wa_store.image_mime(PNG[:16]))
check("image_mime: WebP", "image/webp", wa_store.image_mime(b"RIFF\x24\x00\x00\x00WEBPVP8 "))
check("image_mime: GIF y texto no", (None, None), (wa_store.image_mime(b"GIF89a....."), wa_store.image_mime(b"hola")))

asyncio.run(main())
httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
