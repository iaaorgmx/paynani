#!/usr/bin/env python3
"""
Tests for web/channel_send.py: the owner's WhatsApp and Telegram send with quote and
files, shared by PaynaniWeb and the owner API (PaynaniWebMT PRD #2, FR-A6; paynani#722).
An assertion script, like the rest of this suite. The service and the uploads are fakes:
the real ones are covered by test_web_whatsapp_uploads.py and test_web_telegram*.py.
"""
from __future__ import annotations

import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import channel_send  # noqa: E402
from paynani_lib.web import app  # noqa: E402,F401 -- carga las expresiones de las citas
from paynani_lib.web import telegram_source, whatsapp_source  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


class Rejected(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def fake_uploads():
    """Un módulo de uploads de mentira: guarda en un dict y rechaza `malo.exe`."""
    up = types.SimpleNamespace(MAX_FILES=2, Rejected=Rejected, saved={}, dropped=[])
    n = [0]

    def save(root, name, data):
        if name == "malo.exe":
            raise Rejected("bad_type")
        n[0] += 1
        ref = f"up_{n[0]}"
        up.saved[ref] = name
        return {"upload": ref, "name": name}

    up.save = save
    up.drop = lambda root, ref: up.dropped.append(ref)
    return up


class Source:
    """El `Source` del canal: anota lo que se pidió y falla si se le dice."""

    def __init__(self, failed=None, replies=True):
        self.calls, self.failed, self.replies = [], failed, replies

    def status(self):
        return {"replies": self.replies}

    def request(self, kind, **fields):
        self.calls.append(("fast", kind, fields))
        if self.failed:
            raise self.failed

    def request_slow(self, kind, **fields):
        self.calls.append(("slow", kind, fields))
        if self.failed:
            raise self.failed


def wa(uploads):
    return channel_send.Channel("whatsapp.send", uploads, whatsapp_source.MAX_TEXT,
                                (app.WA_MESSAGE_ID, app.WA_SENT_ID), whatsapp_source.Failed, ("timeout",))


def tg(uploads):
    return channel_send.Channel("telegram.send", uploads, telegram_source.MAX_TEXT, (app.TG_ANY_REF,),
                                telegram_source.Failed)


def error_of(fn):
    try:
        fn()
    except channel_send.SendError as exc:
        return exc
    return None


root = Path(tempfile.mkdtemp())
WA_REF = "wo_" + "a" * 32
TG_REF = "tgo:" + "b" * 32
NUM = {"number": "+525511112222"}
THR = {"thread": "t_" + "c" * 32}
FILE = {"name": "foto.jpg", "data": b"x"}

# --- los canales de verdad --------------------------------------------------------------
check("whatsapp(): whatsapp.send con timeout como corte", ("whatsapp.send", ("timeout",)),
      (channel_send.whatsapp().kind, channel_send.whatsapp().timeout_codes))
check("telegram(): telegram.send sin códigos de corte", ("telegram.send", ()),
      (channel_send.telegram().kind, channel_send.telegram().timeout_codes))

# --- texto sin archivos -------------------------------------------------------------------
src, up = Source(), fake_uploads()
channel_send.send(wa(up), src, root, NUM, "hola\r\nAna", [])
check("sin archivos: request rápido, CRLF a LF", [("fast", "whatsapp.send", {**NUM, "text": "hola\nAna"})],
      src.calls)

# --- la cita --------------------------------------------------------------------------------
src = Source()
channel_send.send(wa(up), src, root, NUM, "sí", [], WA_REF)
check("cita con forma de WhatsApp y el servicio cita: va", WA_REF, src.calls[0][2].get("reply_to"))
src = Source(replies=False)
channel_send.send(wa(up), src, root, NUM, "sí", [], WA_REF)
check("el servicio no cita: no va", False, "reply_to" in src.calls[0][2])
src = Source()
channel_send.send(wa(up), src, root, NUM, "sí", [], TG_REF)
check("cita de otro canal: no va", False, "reply_to" in src.calls[0][2])
src = Source()
channel_send.send(tg(up), src, root, THR, "sí", [], TG_REF)
check("Telegram: su cita sí va", TG_REF, src.calls[0][2].get("reply_to"))

# --- validación ---------------------------------------------------------------------------
check("sin texto ni archivos: invalid", "invalid",
      getattr(error_of(lambda: channel_send.send(wa(up), Source(), root, NUM, "  ", [])), "code", None))
check("texto demasiado largo: invalid", "invalid",
      getattr(error_of(lambda: channel_send.send(wa(up), Source(), root, NUM,
                                                 "x" * (whatsapp_source.MAX_TEXT + 1), [])), "code", None))
src = Source()
channel_send.send(wa(up), src, root, NUM, "", [FILE])
check("sólo un archivo: vale, por request_slow", ("slow", ["up_1"]), (src.calls[0][0], src.calls[0][2]["uploads"]))

# --- archivos rechazados ------------------------------------------------------------------
up = fake_uploads()
err = error_of(lambda: channel_send.send(wa(up), Source(), root, NUM, "x", [FILE, FILE, FILE]))
check("más archivos que MAX_FILES: too_many, sin guardar nada", ("too_many", {}), (getattr(err, "code", None), up.saved))
up = fake_uploads()
err = error_of(lambda: channel_send.send(wa(up), Source(), root, NUM, "x", [FILE, {"name": "malo.exe", "data": b""}]))
check("uno rechazado: su código, y se borran los ya guardados", ("bad_type", ["up_1"]),
      (getattr(err, "code", None), up.dropped))

# --- fallos del servicio ------------------------------------------------------------------
up = fake_uploads()
src = Source(failed=whatsapp_source.Failed("rate_limited", sent_uploads=["up_1"]))
err = error_of(lambda: channel_send.send(wa(up), src, root, NUM, "x", [FILE, {"name": "b.pdf", "data": b"y"}]))
check("fallo definitivo parcial: código, salió uno, se borra el otro",
      ("rate_limited", ["foto.jpg"], False, ["up_2"]), (err.code, err.sent, err.unknown, up.dropped))
up = fake_uploads()
src = Source(failed=whatsapp_source.Failed("timeout"))
err = error_of(lambda: channel_send.send(wa(up), src, root, NUM, "x", [FILE]))
check("WhatsApp: timeout con archivos es desconocido y no borra", (True, []), (err.unknown, up.dropped))
up = fake_uploads()
src = Source(failed=telegram_source.Failed("timeout"))
err = error_of(lambda: channel_send.send(tg(up), src, root, THR, "x", [FILE]))
check("Telegram: un código timeout es definitivo (como antes) y borra", (False, ["up_1"]), (err.unknown, up.dropped))
up = fake_uploads()
src = Source(failed=telegram_source.Failed("unavailable", timed_out=True))
err = error_of(lambda: channel_send.send(tg(up), src, root, THR, "x", [FILE]))
check("timed_out con archivos: desconocido en cualquier canal", (True, []), (err.unknown, up.dropped))
src = Source(failed=whatsapp_source.Failed("timeout"))
err = error_of(lambda: channel_send.send(wa(fake_uploads()), src, root, NUM, "x", []))
check("sin archivos un timeout no es desconocido", False, err.unknown)
check("los campos del servicio llegan", {"sent_uploads": ["up_1"]},
      error_of(lambda: channel_send.send(wa(fake_uploads()), Source(failed=whatsapp_source.Failed(
          "unavailable", sent_uploads=["up_1"])), root, NUM, "x", [FILE])).fields)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
