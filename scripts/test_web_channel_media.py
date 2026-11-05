#!/usr/bin/env python3
"""
Tests for web/channel_media.py: the photos and documents of WhatsApp, Telegram and
Webchat, shared by PaynaniWeb and the owner API (PaynaniWebMT PRD #2, FR-A6 and FR-A9;
paynani#722). An assertion script, like the rest of this suite. The services and the
Webchat store are fakes: the real routes are covered by test_web_whatsapp_photos.py,
test_web_telegram*.py and test_web_webchat.py.
"""
from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import app  # noqa: E402,F401 -- carga las expresiones de los ref
from paynani_lib.web import channel_media, downloads  # noqa: E402
from paynani_lib.web import telegram_source, whatsapp_source  # noqa: E402
from paynani_lib.whatsapp import media as wa_media  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def code_of(fn):
    try:
        fn()
    except channel_media.MediaError as exc:
        return exc.code
    return None


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class Source:
    def __init__(self, data=None, failed=None):
        self.data, self.failed, self.calls = data or {}, failed, []

    def request(self, kind, **fields):
        self.calls.append((kind, fields))
        if self.failed:
            raise self.failed
        return self.data


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


WA_IN = "wa:5215511112222:" + "a" * 64
WA_OUT = "wo_" + "b" * 32
TG_IN = "tg:123:456"
TG_OUT = "tgo:" + "c" * 32

# --- image ----------------------------------------------------------------------------------
src = Source({"data": b64(PNG)})
m = channel_media.image("whatsapp", src, WA_IN)
check("WhatsApp recibida: la foto con su tipo, inline", ("image/png", PNG, True), (m.mime, m.data, m.inline))
check("WhatsApp recibida: whatsapp.image sin índice", ("whatsapp.image", {"message_id": WA_IN}), src.calls[0])
src = Source({"data": b64(PNG)})
channel_media.image("whatsapp", src, WA_OUT, "2")
check("WhatsApp mandada: con su índice", {"message_id": WA_OUT, "index": 2}, src.calls[0][1])
src = Source({"data": b64(PNG)})
channel_media.image("telegram", src, TG_OUT, "0")
check("Telegram mandada: telegram.image con ref e índice", ("telegram.image", {"ref": TG_OUT, "index": 0}), src.calls[0])
check("recibida con índice: not_found", "not_found",
      code_of(lambda: channel_media.image("whatsapp", Source({"data": b64(PNG)}), WA_IN, "1")))
check("mandada sin índice: not_found", "not_found",
      code_of(lambda: channel_media.image("telegram", Source({"data": b64(PNG)}), TG_OUT)))
check("ref de otro canal: not_found sin preguntar", "not_found",
      code_of(lambda: channel_media.image("whatsapp", Source(), TG_IN)))
check("no es foto por los bytes: not_found", "not_found",
      code_of(lambda: channel_media.image("whatsapp", Source({"data": b64(b"%PDF-1.4 hola")}), WA_IN)))
check("base64 roto: not_found", "not_found",
      code_of(lambda: channel_media.image("telegram", Source({"data": "@@@"}), TG_IN)))
big = PNG + b"\x00" * wa_media.IMAGE_MAX_BYTES
check("más grande que el tope: not_found", "not_found",
      code_of(lambda: channel_media.image("whatsapp", Source({"data": b64(big)}), WA_IN)))
check("WhatsApp service_down: unavailable", "unavailable",
      code_of(lambda: channel_media.image("whatsapp", Source(failed=whatsapp_source.Failed("service_down")), WA_IN)))
check("Telegram service_down en fotos: not_found (como antes)", "not_found",
      code_of(lambda: channel_media.image("telegram", Source(failed=telegram_source.Failed("service_down")), TG_IN)))
check("Telegram unavailable: unavailable", "unavailable",
      code_of(lambda: channel_media.image("telegram", Source(failed=telegram_source.Failed("unavailable")), TG_IN)))
check("otro error del servicio: not_found", "not_found",
      code_of(lambda: channel_media.image("whatsapp", Source(failed=whatsapp_source.Failed("forbidden")), WA_IN)))

# --- document -------------------------------------------------------------------------------
src = Source({"data": b64(b"%PDF-1.4 hola"), "name": "factura.pdf"})
m = channel_media.document("whatsapp", src, WA_IN)
check("WhatsApp: el documento como descarga, con su nombre",
      ("application/octet-stream", "factura.pdf", False), (m.mime, m.name, m.inline))
check("WhatsApp: whatsapp.file", ("whatsapp.file", {"message_id": WA_IN}), src.calls[0])
src = Source({"data": b64(b"x")})
check("Telegram: sin nombre, vacío", "", channel_media.document("telegram", src, TG_IN).name)
check("Telegram: telegram.file", ("telegram.file", {"ref": TG_IN}), src.calls[0])
check("sólo recibidos: un wo_ es not_found", "not_found",
      code_of(lambda: channel_media.document("whatsapp", Source(), WA_OUT)))
check("vacío: not_found", "not_found",
      code_of(lambda: channel_media.document("telegram", Source({"data": ""}), TG_IN)))
check("más grande que FILE_MAX_BYTES: not_found", "not_found",
      code_of(lambda: channel_media.document("whatsapp", Source(
          {"data": b64(b"x" * (downloads.FILE_MAX_BYTES + 1))}), WA_IN)))
check("Telegram service_down en documentos: unavailable (como antes)", "unavailable",
      code_of(lambda: channel_media.document("telegram", Source(failed=telegram_source.Failed("service_down")), TG_IN)))

# --- webchat_file ---------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
(tmp / "foto").write_bytes(PNG)
(tmp / "doc").write_bytes(b"%PDF")


class Store:
    def file_path(self, ref):
        return {"f_" + "1" * 32: (tmp / "foto", "image/png", "foto.png"),
                "f_" + "2" * 32: (tmp / "doc", "application/pdf", ""),
                "f_" + "3" * 32: (tmp / "no-existe", "image/png", "x.png")}.get(ref)


m = channel_media.webchat_file(Store(), "f_" + "1" * 32)
check("Webchat foto: inline con su tipo y nombre", ("image/png", "foto.png", True, PNG), (m.mime, m.name, m.inline, m.data))
m = channel_media.webchat_file(Store(), "f_" + "2" * 32)
check("Webchat documento: descarga, nombre por omisión", ("application/octet-stream", "archivo", False),
      (m.mime, m.name, m.inline))
check("Webchat ref que no es f_: not_found", "not_found", code_of(lambda: channel_media.webchat_file(Store(), "w_1")))
check("Webchat archivo que no está en disco: not_found", "not_found",
      code_of(lambda: channel_media.webchat_file(Store(), "f_" + "3" * 32)))
check("Webchat sin almacén: not_found", "not_found",
      code_of(lambda: channel_media.webchat_file(None, "f_" + "1" * 32)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
