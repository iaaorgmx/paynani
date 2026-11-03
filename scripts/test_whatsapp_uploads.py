#!/usr/bin/env python3
"""
Tests for #670 FR-5 to FR-8: the files the owner sends by WhatsApp from PaynaniWeb.
`web_uploads` saves them, `whatsapp.send` takes them in `uploads`, `whatsapp.thread`
lists them and `whatsapp.image` serves the photos. The fake bridge, through control.sock,
like test_whatsapp_service.py; the cases follow test_telegram_send.py (#665, #667).
An assertion script, like the rest of this suite.
"""
from __future__ import annotations

import asyncio
import base64
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import web_uploads  # noqa: E402
from paynani_lib.telegram import uploads as tg_uploads  # noqa: E402
from test_whatsapp_service import NUM, Client, check, make, started, until  # noqa: E402
import test_whatsapp_service as base  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


async def linked(tmp: Path, **settings):
    svc = make(tmp, settings={"WHATSAPP_SEND_INTERVAL_S": "1", **settings})
    await started(svc)
    await svc.sup.request("link", mode="qr")
    await svc.sup.request("fake.link_done", me="+15550009999")
    await svc.sup.request("fake.message", from_e164=NUM, text="hola", key_id="3EB0" + os.urandom(4).hex().upper())
    await until(lambda: NUM in svc.store.wrote_since_link())
    return svc


def up(svc, name: str, data: bytes) -> str:
    return web_uploads.save(svc.layout.root, name, data)["upload"]


async def sends(svc) -> list[dict]:
    return (await svc.sup.request("fake.sends"))["sends"]


async def scenario_shared_module(tmp: Path) -> None:
    check("telegram.uploads es el módulo común (FR-5)", True, tg_uploads.save is web_uploads.save)
    root = tmp / "whatsapp"
    root.mkdir(parents=True)
    r = web_uploads.save(root, "../../foto.jpg", JPEG)
    check("save: up_ y el nombre sin ruta", (True, "foto.jpg", "image"),
          (r["upload"].startswith("up_"), r["name"], r["kind"]))
    d = root / web_uploads.DIR
    check("uploads/ en 0700 y el archivo en 0600", (0o700, 0o600),
          (stat.S_IMODE(os.stat(d).st_mode), stat.S_IMODE(os.stat(d / r["upload"]).st_mode)))
    try:
        web_uploads.save(root, "foto.jpg", b"MZ\x90\x00 no es foto")
        check("tipo por los bytes: un .jpg que no es foto se rechaza", "bad_type", "aceptado")
    except web_uploads.Rejected as exc:
        check("tipo por los bytes: un .jpg que no es foto se rechaza", "bad_type", exc.code)


async def scenario_send(tmp: Path) -> None:
    svc = await linked(tmp)
    try:
        async with Client(svc.socket_path) as c:
            r = await c.ask("whatsapp.status", by="web")
            check("status anuncia web_files (FR-8)", True, r["data"].get("web_files"))

            foto, doc = up(svc, "foto.jpg", JPEG), up(svc, "menú.pdf", PDF)
            r = await c.ask("whatsapp.send", by="agent", number=NUM, text="x", uploads=[foto])
            check("uploads de alguien que no es el dueño: invalid", ("invalid", "uploads"),
                  (r.get("code"), r.get("field")))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="x", uploads=[foto],
                            file=str(svc.layout.outbox / "a.txt"))
            check("uploads junto con file: invalid", ("invalid", "uploads"), (r.get("code"), r.get("field")))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=["up_" + "0" * 32])
            check("un up_ que no existe: bad_upload", "bad_upload", r.get("code"))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=[foto, foto])
            check("el mismo up_ dos veces: bad_upload", "bad_upload", r.get("code"))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads="up_x")
            check("uploads que no es lista: bad_upload", "bad_upload", r.get("code"))

            t0 = time.monotonic()
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="el menú de hoy", uploads=[foto, doc])
            took = time.monotonic() - t0
            msg = (r.get("data") or {}).get("message") or {}
            check("foto y PDF con pie: sent", (True, "sent", "file"), (r.get("ok"), msg.get("status"), msg.get("kind")))
            check("entre un archivo y otro espera el intervalo (FR-21), no lo rechaza", True, took >= 0.9)
            out = (await sends(svc))[-2:]
            check("un send del puente por archivo, en orden", ["foto.jpg", "menú.pdf"],
                  [s["file"]["filename"] for s in out])
            check("el texto va de pie en el primero y no en los demás", ["el menú de hoy", ""],
                  [s["text"] for s in out])
            check("el tipo de cada uno, de sus bytes", ["image/jpeg", "application/pdf"],
                  [s["file"]["mime"] for s in out])
            check("los up_ se borran al salir (un solo uso)", (False, False),
                  ((svc.layout.root / "uploads" / foto).exists(), (svc.layout.root / "uploads" / doc).exists()))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=[foto])
            check("el mismo up_ otra vez: bad_upload", "bad_upload", r.get("code"))

            # FR-7: el hilo, sin rutas, y la foto por su índice
            r = await c.ask("whatsapp.thread", by="web", number=NUM)
            sent = next(m for m in r["data"]["messages"] if m.get("id") == msg["id"])
            files = sent.get("files") or []
            check("thread: files con nombre, tipo y tamaño", [("foto.jpg", "image", len(JPEG)),
                                                             ("menú.pdf", "document", len(PDF))],
                  [(f.get("name"), f.get("kind"), f.get("size")) for f in files])
            check("thread: la foto trae media, el PDF no", (True, False),
                  ("media" in files[0], "media" in files[1]))
            check("thread: ninguna ruta en disco", False, str(svc.layout.root) in str(r["data"]))
            r = await c.ask("whatsapp.image", by="web", message_id=msg["id"], index=0)
            check("image {id, index 0}: la foto enviada", (True, "image/jpeg", JPEG),
                  (r.get("ok"), r["data"]["mime"], base64.b64decode(r["data"]["data"])))
            for idx, label in ((1, "el PDF"), (2, "fuera de rango"), ("0", "índice que no es número")):
                r = await c.ask("whatsapp.image", by="web", message_id=msg["id"], index=idx)
                check(f"image con {label}: not_found", "not_found", r.get("code"))

            # sólo foto, sin texto
            await asyncio.sleep(1.1)
            foto2 = up(svc, "otra.png", PNG)
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=[foto2])
            check("sólo una foto, sin texto: sent", True, r.get("ok"))
            check("sin texto: el pie va vacío", "", (await sends(svc))[-1]["text"])

            # FR-21: dos envíos a la vez no pasan el intervalo y un up_ no sale dos veces
            await asyncio.sleep(1.1)
            a, b = up(svc, "a.jpg", JPEG), up(svc, "b.jpg", JPEG)
            async with Client(svc.socket_path) as c2:
                r1, r2 = await asyncio.gather(
                    c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=[a, b]),
                    c2.ask("whatsapp.send", by="web", number=NUM, text="", uploads=[b]))
            check("el mismo up_ en dos envíos a la vez: uno sale y el otro bad_upload",
                  {True, "bad_upload"}, {r1.get("ok") or r1.get("code"), r2.get("ok") or r2.get("code")})
    finally:
        await svc.stop()


async def scenario_partial(tmp: Path) -> None:
    svc = await linked(tmp)
    try:
        async with Client(svc.socket_path) as c:
            ups = [up(svc, f"f{i}.jpg", JPEG) for i in range(3)]
            await svc.sup.request("fake.fail_after", n=1)
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="tres", uploads=ups)
            check("falla el segundo: el error del puente con sent_uploads del que salió",
                  ("send_failed", [ups[0]]), (r.get("code"), r.get("sent_uploads")))
            check("el que salió se borra; los otros quedan para reintentar", [False, True, True],
                  [(svc.layout.root / "uploads" / u).exists() for u in ups])
            r = await c.ask("whatsapp.thread", by="web", number=NUM)
            last = next(m for m in r["data"]["messages"] if m["dir"] == "out")
            check("el hilo lo marca partial", "partial", last.get("status"))
            await asyncio.sleep(0.3)   # el recibo «server» del que salió llega después
            r = await c.ask("whatsapp.thread", by="web", number=NUM)
            last = next(m for m in r["data"]["messages"] if m["dir"] == "out")
            check("el recibo del que salió no tapa el partial", "partial", last.get("status"))
            await svc.sup.request("fake.fail_after")
            await asyncio.sleep(1.1)
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=ups[1:])
            check("reintentar con los que faltan: sent", True, r.get("ok"))

            await svc.sup.request("fake.fail_after", n=0)
            await asyncio.sleep(1.1)
            one = up(svc, "uno.jpg", JPEG)
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=[one])
            check("falla el primero: sin sent_uploads y el up_ queda", (False, None, True),
                  (r.get("ok", False), r.get("sent_uploads"), (svc.layout.root / "uploads" / one).exists()))
            await svc.sup.request("fake.fail_after")
    finally:
        await svc.stop()


async def scenario_limits(tmp: Path) -> None:
    svc = await linked(tmp, WHATSAPP_SEND_PER_DAY="3")
    try:
        async with Client(svc.socket_path) as c:
            many = [up(svc, f"m{i}.jpg", JPEG) for i in range(11)]
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=many)
            check("11 archivos: too_many", "too_many", r.get("code"))
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=many[:4])
            check("4 archivos con 3 envíos al día: rate_limited y no sale ninguno", ("rate_limited", 0),
                  (r.get("code"), len(await sends(svc))))
            for u in many:
                web_uploads.drop(svc.layout.root, u)
            big = [up(svc, f"g{i}.jpg", JPEG + b"\0" * (11 * 1024 * 1024)) for i in range(2)]
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=big)
            check("más de 20 MB entre todos: too_big", "too_big", r.get("code"))
    finally:
        await svc.stop()


async def scenario_hidden(tmp: Path) -> None:
    """La foto enviada se deja de servir si el contacto sale del roster (como #573)."""
    svc = await linked(tmp)
    try:
        async with Client(svc.socket_path) as c:
            r = await c.ask("whatsapp.send", by="web", number=NUM, text="", uploads=[up(svc, "f.jpg", JPEG)])
            mid = r["data"]["message"]["id"]
            (tmp / "roster.md").write_text(base.ROSTER.replace(NUM, ""))
            r = await c.ask("whatsapp.image", by="web", message_id=mid, index=0)
            check("contacto fuera del roster: la foto enviada da not_found", "not_found", r.get("code"))
    finally:
        await svc.stop()


async def main_async() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        await scenario_shared_module(tmp / "shared")
        await scenario_send(tmp / "send")
        await scenario_partial(tmp / "partial")
        await scenario_limits(tmp / "limits")
        await scenario_hidden(tmp / "hidden")


if __name__ == "__main__":
    asyncio.run(main_async())
    print(f"\n{base.passed} passed, {base.failed} failed")
    sys.exit(1 if base.failed else 0)
