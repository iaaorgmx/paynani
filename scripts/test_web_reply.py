#!/usr/bin/env python3
"""
«Responder» en las conversaciones de PaynaniWeb (PRD #685, F2: FR-6 a FR-9), la parte web.

El núcleo que cita es de Metis (contrato de FR-14 en #685). Aquí se prueba contra la
demostración de Telegram (`telegram_source.Demo`) y con las funciones de las páginas:
- sin `replies` en el estado del canal, la página no ofrece «Responder» ni el campo;
- con él, sí, y el envío le pasa `reply_to` al servicio sólo con forma de mensaje;
- la cita se dibuja en el globo: escapada, oculta si el original lo está, y sin enlace si el
  original es anterior a paynani;
- WhatsApp fuera del roster no cita nada;
- Webchat la ofrece sólo si su almacén ya guarda `reply_to`.
"""
from __future__ import annotations

import hashlib
import http.client
import re
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import paths  # noqa: E402
from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, auth, msgmenu, notify, telegram_source, users  # noqa: E402
from paynani_lib.web import webchat_pages, whatsapp_pages  # noqa: E402

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


REAL = [paths.env_file(), Path.home() / ".config/himalaya/config.toml"]
BEFORE = [sha(p) for p in REAL]
i18n.set_current("es-MX")

# ---- msgmenu.quote y reply_field ---------------------------------------------------------------
q = msgmenu.quote({"ref": "tg:1", "name": "Ana <b>", "excerpt": "hola\n  <script>x</script>", "missing": False})
check("quote: enlace al original con data-cita y el texto escapado en una línea", True,
      q.startswith('<a class="cita" href="#" data-cita="tg:1">') and "&lt;script&gt;" in q and "<script>" not in q
      and "Ana &lt;b&gt;" in q and "\n" not in q)
check("quote: el original oculto no deja ver su texto (FR-17)", True,
      "Mensaje oculto" in msgmenu.quote({"ref": "tg:2", "name": None, "excerpt": None}))
check("quote: sin ref (anterior a paynani) no lleva a ningún lado (FR-9)", True,
      msgmenu.quote({"ref": None, "name": "Ana", "excerpt": "viejo"}).startswith('<span class="cita">'))
check("quote: missing dice que salió sin cita (FR-7)", True,
      "Se mandó sin cita" in msgmenu.quote({"ref": "tg:3", "name": "Ana", "excerpt": "x", "missing": True}))
check("quote: un mensaje que no es respuesta, nada", ["", ""], [msgmenu.quote(None), msgmenu.quote("tg:1")])
check("quote: el extracto se corta en 100", True,
      len(re.search(r"<span>(.*?)</span>", msgmenu.quote({"ref": "tg:1", "name": "A", "excerpt": "x" * 300})).group(1)) == 100)
check("reply_field: sólo con el canal que cita, y con el valor escapado", ("", '<input type="hidden" name="reply_to" value="a&quot;b">'),
      (msgmenu.reply_field(False, "x"), msgmenu.reply_field(True, 'a"b')))
check("list_attrs: «Responder» sólo con reply=True", (False, True),
      ("data-msgmenu-reply=" in msgmenu.list_attrs(), 'data-msgmenu-reply="Responder"' in msgmenu.list_attrs(reply=True)))
check("item: data-ref siempre (para saltar a él) y data-name sólo con menú", (' data-ref="tg:9"', True),
      (msgmenu.item(False, "tg:9", "Ana"), 'data-name="Ana"' in msgmenu.item(True, "tg:9", "Ana")))

# ---- Telegram, de punta a punta con la demostración -------------------------------------------
PASSWORD = "una-contraseña-larga"
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
(clone / "state").mkdir(parents=True)
(clone / "roster.md").write_text("| Name | Email |\n|---|---|\n| Julián Flores | julian@example.com |\n", encoding="utf-8")
tg_root = clone / "cfg"
tg_root.mkdir()
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
demo = telegram_source.Demo()
(tg_root / "telegram.env").write_text(f"TELEGRAM_ENABLED=1\nTELEGRAM_TOKEN={demo.token}\n", encoding="utf-8")
(tg_root / "telegram.env").chmod(0o600)
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda to, s, b: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "no-accounts.json",
                  state_dir=clone / "state", roster_path=clone / "roster.md",
                  telegram_source=demo, telegram_root=tg_root, whatsapp_root=clone)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"


def req(method, path, *, form=None, cookie=""):
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
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    return r.status, out, data


_, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
cookie = next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
thread = next(t for t in demo.threads if t["in_roster"] and any(m["dir"] == "in" for m in t["messages"]))
tid = thread["thread"]
incoming = next(m["ref"] for m in thread["messages"] if m["dir"] == "in")


def thread_page():
    status, _, page = req("GET", f"/telegram/messages/ver?t={tid}&lang=es-MX", cookie=cookie)
    return status, page


def sends():
    return [f for k, f in demo.calls if k == "telegram.send"]


status, page = thread_page()
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
check("sin replies: el hilo no ofrece «Responder» ni el campo reply_to", (200, False, False),
      (status, "data-msgmenu-reply=" in page, 'name="reply_to"' in page))
check("sin replies: los renglones igual llevan data-ref (para saltar a una cita)", True, f'data-ref="{incoming}"' in page)
status, _, _ = req("POST", "/telegram/messages/enviar", cookie=cookie,
                   form={"csrf": csrf, "t": tid, "text": "hola", "reply_to": incoming})
check("sin replies: un reply_to del formulario no llega al servicio", (303, False), (status, "reply_to" in sends()[-1]))

demo.replies = True
status, page = thread_page()
check("con replies: «Responder» en el menú y el campo vacío en el formulario", (True, True),
      ('data-msgmenu-reply="Responder"' in page, '<input type="hidden" name="reply_to" value="">' in page))
check("con replies: el renglón dice quién lo escribió (data-name), para la barra", True,
      re.search(rf'data-ref="{re.escape(incoming)}" data-menu [^>]*data-name="[^"]+"', page) is not None)
status, _, _ = req("POST", "/telegram/messages/enviar", cookie=cookie,
                   form={"csrf": csrf, "t": tid, "text": "Sí, a las 8", "reply_to": incoming})
check("con replies: el envío le pasa reply_to al servicio", (303, incoming), (status, sends()[-1].get("reply_to")))
status, page = thread_page()
check("la respuesta se dibuja con la cita del original, enlazada a él", True,
      f'<a class="cita" href="#" data-cita="{incoming}">' in page)
for bad in ("tg:", "x:1", "tg:../../etc", "tgo:" + "a" * 200):
    req("POST", "/telegram/messages/enviar", cookie=cookie, form={"csrf": csrf, "t": tid, "text": "x", "reply_to": bad})
    check(f"un reply_to sin forma de mensaje ({bad[:14]}) no llega al servicio", False, "reply_to" in sends()[-1])
status, _, page = req("POST", "/telegram/messages/enviar", cookie=cookie,
                      form={"csrf": csrf, "t": tid, "text": "y", "reply_to": "tg:noexiste"})
check("un original que el servicio no encuentra: error, y el formulario vuelve con la cita", (400, True),
      (status, '<input type="hidden" name="reply_to" value="tg:noexiste">' in page))
httpd.shutdown()

# ---- WhatsApp: fuera del roster no se cita -----------------------------------------------------
WA = {"number": "+525511112222", "name": "Beto", "in_roster": True, "can_reply": True, "messages": [
    {"dir": "out", "by": "owner", "at": "2026-11-03T14:01:00Z", "text": "ok", "id": "wo_" + "1" * 32, "status": "read",
     "reply_to": {"ref": "wa:x", "name": "Beto", "excerpt": "hola", "missing": False}},
    {"dir": "in", "at": "2026-11-03T14:00:00Z", "text": "hola", "id": "wa:x"}]}
page = whatsapp_pages.thread_body(WA, whatsapp_pages.reply_box(WA, "c", True, replies=True), replies=True)
check("WhatsApp con replies: «Responder», el campo y la cita", (True, True, True),
      ('data-msgmenu-reply=' in page, 'name="reply_to"' in page, 'data-cita="wa:x"' in page))
fuera = dict(WA, in_roster=False)
page = whatsapp_pages.thread_body(fuera, "", replies=True)
check("WhatsApp fuera del roster: sin «Responder», sin cita y sin menú (FR-17)", (False, False, False),
      ('data-msgmenu-reply=' in page, "cita" in page, " data-menu " in page))

# ---- Webchat: sólo si el almacén guarda reply_to -----------------------------------------------


class OldStore:
    def append(self, by, text, files, *, owner=None):
        return {}


class NewStore:
    def append(self, by, text, files, *, owner=None, reply_to=None):
        return {}


check("Webchat: replies() mira si el almacén acepta reply_to", (False, True, False),
      (webchat_pages.replies(OldStore()), webchat_pages.replies(NewStore()), webchat_pages.replies(None)))
import datetime as dt  # noqa: E402
html = webchat_pages.bubbles([{"id": "w_" + "2" * 32, "by": "agent", "at": "2026-11-03T08:01:00Z", "text": "sí",
                               "reply_to": {"ref": "w_" + "1" * 32, "name": "Tú", "excerpt": "¿puedes?", "missing": False}}],
                             dt.datetime(2026, 11, 3, 9, tzinfo=dt.timezone.utc), "Iris")
check("Webchat: la cita en el globo del agente, y el renglón con su ref y nombre", (True, True),
      ('data-cita="w_' + "1" * 32 + '"' in html, 'data-name="Iris"' in html))

js = (ROOT / "scripts" / "paynani_lib" / "assets" / "msgmenu.js").read_text(encoding="utf-8")
check("msgmenu.js: Responder, la barra con su ✕, el salto con «Mensajes anteriores» hasta 5 veces", True,
      all(x in js for x in ("startReply", "cita-barra", "cita-quitar", "tries >= 5", "msj-resaltado")))
check("webchat.js manda reply_to por el WebSocket y avisa para quitar la barra", True,
      all(x in (ROOT / "scripts/paynani_lib/assets/webchat.js").read_text() for x in ("packet.reply_to", "msgmenu:sent")))
check("el .env y Himalaya de la instalación no cambiaron", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
