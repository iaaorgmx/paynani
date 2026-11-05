#!/usr/bin/env python3
"""
Tests for web/channel_react.py: the owner's reactions in WhatsApp, Telegram and Webchat,
shared by PaynaniWeb and the owner API (PaynaniWebMT PRD #2, FR-A6; paynani#722). An
assertion script, like the rest of this suite. The services and the Webchat store are
fakes: the real ones are covered by test_web_reactions.py and test_*_react.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import app  # noqa: E402,F401 -- carga las expresiones de los ref
from paynani_lib.web import channel_react  # noqa: E402
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


def error_of(fn):
    try:
        fn()
    except channel_react.ReactError as exc:
        return (exc.kind, exc.code)
    return None


class Source:
    def __init__(self, reactions=True, failed=None, messages=None, status_failed=None):
        self.calls, self.reactions, self.failed = [], reactions, failed
        self.messages, self.status_failed = messages or [], status_failed

    def status(self):
        if self.status_failed:
            raise self.status_failed
        return {"reactions": ["👍", "❤️"] if self.reactions else None}

    def request(self, kind, **fields):
        self.calls.append((kind, fields))
        if self.failed:
            raise self.failed
        if kind.endswith(".react"):
            return {"reactions": [{"emoji": fields["emoji"], "mine": True}, "basura"]}
        return {"messages": self.messages}


class Store:
    """El almacén de Webchat: reacciona si tiene `react` y `replies`, como el de verdad."""

    def __init__(self, rejected=None):
        self.rejected, self.calls = rejected, []

    def react(self, ref, emoji, *, by, owner=None):
        self.calls.append((ref, emoji, by))
        if self.rejected:
            raise self.rejected
        return {"reactions": [{"emoji": emoji, "mine": True}]}


WA_REF = "wo_" + "a" * 32
TG_REF = "tgo:" + "b" * 32
WC_REF = "w_" + "c" * 32
THREAD = "t_" + "d" * 32

# --- react: WhatsApp y Telegram -------------------------------------------------------------
src = Source()
check("WhatsApp: pone la reacción y limpia lo que no es dict", [{"emoji": "👍", "mine": True}],
      channel_react.react("whatsapp", src, WA_REF, "👍"))
check("WhatsApp: pide whatsapp.react con ref y emoji", ("whatsapp.react", {"ref": WA_REF, "emoji": "👍"}), src.calls[0])
src = Source()
channel_react.react("telegram", src, TG_REF, "")
check("Telegram: «» quita, por telegram.react", ("telegram.react", {"ref": TG_REF, "emoji": ""}), src.calls[0])
check("emoji que no es de la lista de forma: invalid", ("invalid", "invalid_emoji"),
      error_of(lambda: channel_react.react("whatsapp", Source(), WA_REF, "no es emoji")))
check("canal sin configurar (None): not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.react("telegram", None, TG_REF, "👍")))
check("emoji inválido gana a canal sin configurar (como antes)", ("invalid", "invalid_emoji"),
      error_of(lambda: channel_react.react("telegram", None, TG_REF, "xx")))
check("ref de otro canal: not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.react("whatsapp", Source(), TG_REF, "👍")))
check("el canal no reacciona: not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.react("whatsapp", Source(reactions=False), WA_REF, "👍")))
check("el servicio dice que no: service con su código", ("service", "not_found"),
      error_of(lambda: channel_react.react("telegram", Source(failed=telegram_source.Failed("not_found")),
                                           TG_REF, "👍")))
check("el estado falla: service", ("service", "unavailable"),
      error_of(lambda: channel_react.react("whatsapp", Source(status_failed=whatsapp_source.Failed("unavailable")),
                                           WA_REF, "👍")))

# --- react: Webchat -------------------------------------------------------------------------
store = Store()
store.replies = True
original = channel_react.webchat_pages.reacts
channel_react.webchat_pages.reacts = lambda s: s is not None and hasattr(s, "react")
try:
    check("Webchat: reacciona por el almacén", [{"emoji": "👍", "mine": True}],
          channel_react.react("webchat", store, WC_REF, "👍"))
    check("Webchat: como el dueño", (WC_REF, "👍", "owner"), store.calls[0])
    check("Webchat sin almacén: not_allowed", ("not_allowed", "not_allowed"),
          error_of(lambda: channel_react.react("webchat", None, WC_REF, "👍")))
    check("Webchat con ref que no es w_: not_allowed", ("not_allowed", "not_allowed"),
          error_of(lambda: channel_react.react("webchat", Store(), WA_REF, "👍")))

    class Rejected(Exception):
        code = "not_found"

    kind, _ = error_of(lambda: channel_react.react("webchat", Store(rejected=Rejected()), WC_REF, "👍"))
    check("Webchat: un rechazo del almacén es store", "store", kind)
finally:
    channel_react.webchat_pages.reacts = original

# --- thread_reactions -----------------------------------------------------------------------
msgs = [{"id": "wa:1", "reactions": [{"emoji": "👍"}]}, {"id": "wa:2", "hidden": True, "reactions": ["x"]},
        {"id": "", "reactions": []}, {"id": "wa:3"}]
src = Source(messages=msgs)
check("WhatsApp: las reacciones por id, sin ocultos ni sin id", {"wa:1": [{"emoji": "👍"}], "wa:3": []},
      channel_react.thread_reactions("whatsapp", src, "+525511112222"))
check("WhatsApp: whatsapp.thread con número y página", "whatsapp.thread", src.calls[0][0])
src = Source(messages=[{"ref": "tg:1", "reactions": [{"emoji": "❤️"}]}])
check("Telegram: por ref", {"tg:1": [{"emoji": "❤️"}]}, channel_react.thread_reactions("telegram", src, THREAD))
check("Telegram: hilo que no es t_: not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.thread_reactions("telegram", Source(), "+5255")))
check("WhatsApp sin número: not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.thread_reactions("whatsapp", Source(), "")))
check("sin configurar: not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.thread_reactions("whatsapp", None, "+5255")))
check("el canal no reacciona: not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.thread_reactions("whatsapp", Source(reactions=False), "+5255")))
check("el servicio falla: not_allowed", ("not_allowed", "not_allowed"),
      error_of(lambda: channel_react.thread_reactions("telegram", Source(failed=telegram_source.Failed("x")), THREAD)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
