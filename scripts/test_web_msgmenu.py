#!/usr/bin/env python3
"""
El menú al tocar un mensaje de PaynaniWeb (PRD #685, F1: «Copiar»).

Revisa lo que dibuja cada página de conversación (WhatsApp, Telegram, SMS y Webchat):
- qué renglones llevan `data-menu` (FR-3, FR-4: ni los ocultos, ni los que se están enviando o
  fallaron);
- que sean enfocables y lo anuncien (FR-1);
- que la lista traiga los textos del menú en el idioma de la página;
- que cargue `assets/msgmenu.js`.

El comportamiento en el navegador (tocar, clic derecho, Enter, Escape y copiar) se probó en
Chromium a 390 y 1280 px (PR). Aquí sólo se revisa que el script tenga esas piezas.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, msgmenu, msgmenu_strings  # noqa: E402,F401
from paynani_lib.web import messages_pages, telegram_pages, webchat_pages, whatsapp_pages  # noqa: E402

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


import paths  # noqa: E402

# El .env de esta instalación, donde sea que esté (Metis en #696), y la configuración de Himalaya.
REAL = [paths.env_file(), Path.home() / ".config/himalaya/config.toml"]
BEFORE = [sha(p) for p in REAL]


def rows(html: str) -> list[tuple[str, bool]]:
    """(texto, con menú) de cada renglón con globo, en orden."""
    out = []
    for li in re.findall(r"<li class=\"(?:sms|wc) [^\"]*\"[^>]*>.*?</li>", html, re.S):
        text = re.search(r'<div class="texto">(.*?)</div>', li, re.S)
        out.append((re.sub(r"<[^>]+>", "", text.group(1)) if text else "", " data-menu " in li.split(">", 1)[0] + " "))
    return out


i18n.set_current("es-MX")

# --- msgmenu.py ------------------------------------------------------------------------------
check("item(True): data-menu, tabindex y aria-haspopup", ' data-menu tabindex="0" aria-haspopup="menu"', msgmenu.item(True))
check("item(False): nada", "", msgmenu.item(False))
check("has_menu: oculto no", False, msgmenu.has_menu("telegram", {"hidden": True, "text": "x"}))
check("has_menu: Telegram enviando y fallado no; enviado sí", [False, False, True],
      [msgmenu.has_menu("telegram", {"status": s}) for s in ("sending", "failed", "sent")])
check("has_menu: WhatsApp entregado y leído sí; enviando no", [True, True, False],
      [msgmenu.has_menu("whatsapp", {"status": s}) for s in ("delivered", "read", "sending")])
check("has_menu: SMS en cola, aceptado, fallado, rechazado y vencido no", [False] * 5,
      [msgmenu.has_menu("sms", {"status": s}) for s in ("queued", "accepted", "failed", "rejected", "expired")])
check("has_menu: SMS recibido (sin estado), enviado y entregado sí", [True, True, True],
      [msgmenu.has_menu("sms", {"status": s}) for s in ("", "sent", "delivered")])
attrs = msgmenu.list_attrs()
check("list_attrs: los cuatro textos en es-MX", True, all(x in attrs for x in (
    'data-msgmenu-label="Opciones del mensaje"', 'data-msgmenu-copy="Copiar"', 'data-msgmenu-copied="Copiado"',
    'data-msgmenu-failed="No se pudo copiar.')))
for lang in msgmenu_strings.STRINGS:
    i18n.set_current(lang)
    check(f"{lang}: sin claves sin traducir", [], re.findall(r"web\.msgmenu\.[a-z_]+", msgmenu.list_attrs()))
i18n.set_current("es-MX")

# --- Telegram ---------------------------------------------------------------------------------
TG = {"thread": "t_" + "a" * 32, "name": "Ana", "in_roster": True, "can_reply": True, "messages": [
    {"dir": "in", "at": "2026-11-03T14:00:00Z", "text": "hola", "ref": "tg:1"},
    {"dir": "out", "by": "agent", "at": "2026-11-03T14:01:00Z", "text": "enviado", "ref": "tgo:1", "status": "sent"},
    {"dir": "out", "by": "owner", "at": "2026-11-03T14:02:00Z", "text": "enviando", "ref": "tgo:2", "status": "sending"},
    {"dir": "out", "by": "owner", "at": "2026-11-03T14:03:00Z", "text": "fallado", "ref": "tgo:3", "status": "failed"},
    {"dir": "in", "at": "2026-11-03T14:04:00Z", "text": "", "ref": "tg:2", "hidden": True}]}
html = telegram_pages.thread_body(TG, "")
check("Telegram: menú en el recibido y el enviado; no en enviando, fallado ni oculto",
      [True, True, False, False, False], [m for _, m in rows(html)])
check("Telegram: la lista lleva los textos y la página carga msgmenu.js", (True, True),
      ('<ol class="hilo" data-msgmenu-label=' in html, msgmenu.SCRIPT in html))

# --- WhatsApp ---------------------------------------------------------------------------------
WA = {"thread": "t_" + "b" * 32, "number": "+525511112222", "name": "Beto", "in_roster": True, "can_reply": True, "messages": [
    {"dir": "in", "at": "2026-11-03T14:00:00Z", "text": "hola", "id": "wa:1"},
    {"dir": "out", "by": "agent", "at": "2026-11-03T14:01:00Z", "text": "leído", "id": "wo_1", "status": "read"},
    {"dir": "out", "by": "owner", "at": "2026-11-03T14:02:00Z", "text": "enviando", "id": "wo_2", "status": "sending"},
    {"dir": "in", "at": "2026-11-03T14:03:00Z", "text": "", "id": "wa:2", "hidden": True}]}
html = whatsapp_pages.thread_body(WA, "")
# whatsapp.thread llega del más reciente al más viejo y la página lo dibuja así: se compara por texto.
got = dict(rows(html))
check("WhatsApp: menú en el recibido y el leído; no en enviando ni oculto", (True, True, False, 4),
      (got.get("hola"), got.get("leído"), got.get("enviando"), len(rows(html))))
check("WhatsApp: el oculto no lleva menú", 1, sum(1 for t, m in rows(html) if not m and t != "enviando"))
check("WhatsApp: textos y msgmenu.js", (True, True), ('<ol class="hilo" data-msgmenu-label=' in html, msgmenu.SCRIPT in html))

# --- SMS (Iris[Q28] = A: sólo Copiar) ------------------------------------------------------------
items = [
    {"kind": "received", "local": "2026-11-03T08:00:00", "text": "hola", "status": ""},
    {"kind": "agent", "local": "2026-11-03T08:01:00", "text": "entregado", "status": "delivered", "id": "a_1"},
    {"kind": "human", "local": "2026-11-03T08:02:00", "text": "en cola", "status": "queued", "id": "w_1", "via": "web"},
    {"kind": "human", "local": "2026-11-03T08:03:00", "text": "fallado", "status": "failed", "id": "w_2", "via": "web"},
    {"kind": "call_missed", "local": "2026-11-03T08:04:00", "status": ""}]
html = messages_pages.thread_body("+525511112222", "Ana", items, 0, None)
check("SMS: menú en el recibido y el entregado; no en cola ni fallado", [True, True, False, False],
      [m for _, m in rows(html)])
check("SMS: la llamada perdida no lleva menú", False, bool(re.search(r'<li class="llamada"[^>]*data-menu', html)))
check("SMS: textos y msgmenu.js", (True, True), ('<ol class="hilo" data-msgmenu-label=' in html, msgmenu.SCRIPT in html))

# --- Webchat ----------------------------------------------------------------------------------
now = dt.datetime(2026, 11, 3, 9, 0, tzinfo=dt.timezone.utc)
msgs = [{"id": "w_" + "1" * 32, "by": "owner", "at": "2026-11-03T08:00:00Z", "text": "hola"},
        {"id": "w_" + "2" * 32, "by": "agent", "at": "2026-11-03T08:01:00Z", "text": "qué tal"}]
html = webchat_pages.bubbles(msgs, now, "Iris")
check("Webchat: los mensajes guardados llevan menú", [True, True], [m for _, m in rows(html)])
check("Webchat: «escribiendo…» y el borrador no", (False, False),
      ("data-menu" in webchat_pages.typing_row("Iris", True), "data-menu" in webchat_pages.draft_row("Iris")))

# --- El script --------------------------------------------------------------------------------
check("msgmenu.js está en STATIC como JavaScript", True,
      app.STATIC.get("/assets/msgmenu.js", (None, ""))[1].startswith("application/javascript"))
js = (ROOT / "scripts" / "paynani_lib" / "assets" / "msgmenu.js").read_text(encoding="utf-8")
check("msgmenu.js: tocar, clic derecho y teclado (FR-1)", True,
      all(x in js for x in ('addEventListener("click"', 'addEventListener("contextmenu"', '"Escape"', '"Enter"')))
check("msgmenu.js: no abre sobre un enlace, una foto o un botón, ni al seleccionar texto (FR-1)", True,
      all(x in js for x in ("a, button, img", "getSelection")))
check("msgmenu.js: copia con el portapapeles y, si no, con execCommand; avisa con role=status (FR-5)", True,
      all(x in js for x in ("navigator.clipboard", 'execCommand("copy")', '"role", "status"')))
check("msgmenu.js: sin innerHTML con texto del mensaje (el SVG es fijo)", False, "innerHTML = text" in js)
check("el .env y Himalaya de la instalación no cambiaron", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
