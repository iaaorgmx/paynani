#!/usr/bin/env python3
"""
Las reacciones en las conversaciones de PaynaniWeb (PRD #685, F3: FR-10 a FR-13), la parte web.

El núcleo que reacciona es de Metis (contrato de FR-14 en #685). Aquí se prueba contra la
demostración de Telegram y con las funciones de las páginas:
- sin `reactions` en el estado del canal, la página no trae la fila y la ruta responde 404;
- con la lista del bot, la página la lleva en la `<ol>`; la ruta pasa `ref` y `emoji` al servicio
  y responde JSON con las reacciones; «» quita la nuestra;
- un emoji o un ref sin forma no llegan al servicio;
- las reacciones bajo el globo se dibujan escapadas, con la nuestra resaltada;
- WhatsApp fuera del roster no trae reacciones; Webchat sólo con un almacén que reacciona.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
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

# ---- msgmenu ----------------------------------------------------------------------------------
check("ROW: las 7 de Telegram Web, en orden (FR-10)", ("👍", "👌", "❤️", "👀", "🔥", "😭", "👎"), msgmenu.ROW)
check("valid_emoji: emojis y «» sí; letras, espacios y HTML no", [True, True, True, False, False, False],
      [msgmenu.valid_emoji(x) for x in ("👍", "❤️", "", "a", "👍 ", "<b>")])
check("reactions_allowed: any, una lista limpia, o None", ("any", ["👍"], None, None),
      (msgmenu.reactions_allowed("any"), msgmenu.reactions_allowed(["👍", "x", 3]), msgmenu.reactions_allowed(None),
       msgmenu.reactions_allowed([])))
chips = msgmenu.reactions([{"emoji": "👍", "count": 2, "mine": True}, {"emoji": "❤️", "count": 1, "mine": False},
                           {"emoji": "<script>", "count": 9}])
check("reactions: la nuestra resaltada con aria-pressed, el conteo si es más de una, y nada inválido", True,
      'class="reac reac-mia" data-emoji="👍" aria-pressed="true">👍<small>2</small>' in chips
      and 'aria-pressed="false">❤️</button>' in chips and "script" not in chips)
check("reactions: sin reacciones, nada", ["", ""], [msgmenu.reactions(None), msgmenu.reactions([])])
attrs = msgmenu.list_attrs(reactions=["👍", "❤️"], react_url="/telegram/messages/reaccionar", csrf="c1")
check("list_attrs: la lista, la ruta, el csrf y la nota de Telegram", True,
      all(x in attrs for x in ('data-msgmenu-react="[&quot;👍&quot;, &quot;❤️&quot;]"',
                                'data-msgmenu-react-url="/telegram/messages/reaccionar"', 'data-msgmenu-csrf="c1"',
                                'data-msgmenu-tgnote="Un bot de Telegram solo puede usar estas."')))
check("list_attrs: sin reactions o sin ruta, nada de reacciones", (False, False),
      ("data-msgmenu-react=" in msgmenu.list_attrs(react_url="/x"), "data-msgmenu-react=" in msgmenu.list_attrs(reactions="any")))

# ---- Telegram, con la demostración ------------------------------------------------------------
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
ref = next(m["ref"] for m in thread["messages"] if m["dir"] == "in")
_, _, page = req("GET", f"/telegram/messages/ver?t={tid}&lang=es-MX", cookie=cookie)
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
URL = "/telegram/messages/reaccionar"


def reacts():
    return [f for k, f in demo.calls if k == "telegram.react"]


check("sin reactions: el hilo no trae la fila", False, "data-msgmenu-react=" in page)
status, _, body = req("POST", URL, cookie=cookie, form={"csrf": csrf, "ref": ref, "emoji": "👍"})
check("sin reactions: la ruta responde 404 y no llega al servicio", (404, 0), (status, len(reacts())))

demo.reactions = ["👍", "❤️", "🎉"]
_, _, page = req("GET", f"/telegram/messages/ver?t={tid}&lang=es-MX", cookie=cookie)
check("con reactions: la lista del bot y la ruta en la lista del hilo", (True, True),
      ('data-msgmenu-react="[&quot;👍&quot;, &quot;❤️&quot;, &quot;🎉&quot;]"' in page, f'data-msgmenu-react-url="{URL}"' in page))
status, hdrs, body = req("POST", URL, cookie=cookie, form={"csrf": csrf, "ref": ref, "emoji": "👍"})
data = json.loads(body)
check("poner 👍: 200 JSON con la nuestra, y el servicio recibió ref y emoji", (200, True, [{"emoji": "👍", "count": 1, "mine": True}], {"ref": ref, "emoji": "👍"}),
      (status, hdrs.get("content-type", "").startswith("application/json"), data.get("reactions"), reacts()[-1]))
_, _, page = req("GET", f"/telegram/messages/ver?t={tid}&lang=es-MX", cookie=cookie)
check("la página dibuja la reacción bajo el globo, resaltada", True, 'class="reac reac-mia" data-emoji="👍"' in page)
status, _, body = req("POST", URL, cookie=cookie, form={"csrf": csrf, "ref": ref, "emoji": ""})
check("«» quita la nuestra (FR-11)", (200, []), (status, json.loads(body).get("reactions")))
status, _, body = req("POST", URL, cookie=cookie, form={"csrf": csrf, "ref": "tgo:noexiste", "emoji": "👍"})
check("#707: un mensaje sin id en el canal (not_found): el aviso dice que es anterior, no «inténtalo otra vez»",
      (400, "not_found", True), (status, json.loads(body).get("code"), "anterior a las reacciones" in json.loads(body).get("error", "")))
status, _, body = req("POST", URL, cookie=cookie, form={"csrf": csrf, "ref": ref, "emoji": "🤡"})
check("una que el bot no acepta: 400 con el aviso, y el código del servicio", (400, "invalid", True),
      (status, json.loads(body).get("code"), "No se pudo poner la reacción" in json.loads(body).get("error", "")))
n = len(reacts())
for bad_ref, bad_emoji in (("x:1", "👍"), (ref, "ok"), (ref, "<img>"), ("tg:../x", "👍")):
    status, _, _ = req("POST", URL, cookie=cookie, form={"csrf": csrf, "ref": bad_ref, "emoji": bad_emoji})
    check(f"ref {bad_ref[:8]!r} / emoji {bad_emoji!r} sin forma: no llega al servicio", (True, n), (status in (400, 404), len(reacts())))
status, _, _ = req("POST", URL, cookie=cookie, form={"csrf": "otro", "ref": ref, "emoji": "👍"})
check("sin el CSRF bueno: 403 y nada al servicio", (403, n), (status, len(reacts())))
# ---- En vivo en Telegram: /telegram/messages/reacciones (sin WebSocket, msgmenu.js consulta) -----
check("el hilo lleva la ruta de consulta de reacciones", True,
      f'data-msgmenu-poll="/telegram/messages/reacciones?t={tid}"' in req("GET", f"/telegram/messages/ver?t={tid}", cookie=cookie)[2])
target = next(m for m in thread["messages"] if m["ref"] == ref)
target["reactions"] = [{"emoji": "🔥", "count": 1, "mine": False}]   # la del contacto, como la deja el núcleo
status, hdrs, body = req("GET", f"/telegram/messages/reacciones?t={tid}", cookie=cookie)
data = json.loads(body)
check("consulta: 200 JSON con las reacciones por ref, la del contacto incluida", (200, True, [{"emoji": "🔥", "count": 1, "mine": False}]),
      (status, hdrs.get("content-type", "").startswith("application/json"), data["items"].get(ref)))
check("consulta: un hilo sin forma da 404", 404, req("GET", "/telegram/messages/reacciones?t=x", cookie=cookie)[0])
check("consulta: sin sesión no da reacciones", True, req("GET", f"/telegram/messages/reacciones?t={tid}")[0] in (302, 303, 401, 403))
demo.reactions = None
check("consulta: con un canal que no reacciona, 404", 404, req("GET", f"/telegram/messages/reacciones?t={tid}", cookie=cookie)[0])
httpd.shutdown()

# ---- WhatsApp y Webchat --------------------------------------------------------------------------
WA = {"number": "+525511112222", "name": "Beto", "in_roster": True, "can_reply": True, "messages": [
    {"dir": "in", "at": "2026-11-03T14:00:00Z", "text": "hola", "id": "wa:x",
     "reactions": [{"emoji": "❤️", "count": 1, "mine": False}]}]}
page = whatsapp_pages.thread_body(WA, "", reactions="any", csrf="c")
check("WhatsApp con reactions any: la fila sin lista fija y la reacción de Beto", (True, True),
      ('data-msgmenu-react="&quot;any&quot;"' in page, 'data-emoji="❤️" aria-pressed="false"' in page))
check("WhatsApp: la ruta de consulta lleva el número", True, 'data-msgmenu-poll="/whatsapp/messages/reacciones?n=%2B525511112222"' in page)
page = whatsapp_pages.thread_body(dict(WA, in_roster=False), "", reactions="any", csrf="c")
check("WhatsApp fuera del roster: ni fila ni reacciones (FR-17)", (False, False),
      ("data-msgmenu-react=" in page, "reacciones" in page))


class Store:
    def append(self, *a, **k):
        return {}

    def react(self, ref, emoji, by="owner"):
        return {"reactions": []}


check("Webchat: reacts() sólo con un almacén que tiene react()", (False, True, False),
      (webchat_pages.reacts(object()), webchat_pages.reacts(Store()), webchat_pages.reacts(None)))
html = webchat_pages.bubbles([{"id": "w_" + "1" * 32, "by": "agent", "at": "2026-11-03T08:00:00Z", "text": "listo",
                               "reactions": [{"emoji": "👍", "count": 1, "mine": True}]}],
                             dt.datetime(2026, 11, 3, 9, tzinfo=dt.timezone.utc), "Iris")
check("Webchat: la reacción del dueño bajo el globo del agente", True, 'class="reac reac-mia" data-emoji="👍"' in html)

js = (ROOT / "scripts" / "paynani_lib" / "assets" / "msgmenu.js").read_text(encoding="utf-8")
check("msgmenu.js consulta cada 15 s sólo con la pestaña a la vista, y redibuja sólo lo que cambió", True,
      all(x in js for x in ("data-msgmenu-poll", "POLL_MS = 15000", 'visibilityState !== "visible"', "want !== shown(row)",
                            "seq !== reactSeq")))
check("msgmenu.js: la fila, el selector con buscador en «any», la misma la quita y las de abajo son botones", True,
      all(x in js for x in ("reactionRow", "selector-buscar", 'bare(mine) === bare(emoji) ? ""', ".reacciones .reac")))
# ---- Webchat en vivo: una reacción del agente a un mensaje viejo, sin recargar --------------------
from paynani_lib.web import webchat_ws  # noqa: E402


class Rooted:
    def __init__(self, r):
        self._r = r

    def root(self):
        return self._r


wr = Path(tempfile.mkdtemp()) / "webchat"
wr.mkdir()
sig0 = webchat_ws.signature(Rooted(wr))
(wr / "reactions.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
check("signature() cambia cuando cambia reactions.jsonl (se vuelve a leer)", True, webchat_ws.signature(Rooted(wr)) != sig0)
check("webchat.js pasa las reacciones del WebSocket a msgmenu.js, y msgmenu.js las dibuja", (True, True),
      ('"msgmenu:reactions"' in (ROOT / "scripts/paynani_lib/assets/webchat.js").read_text(),
       'addEventListener("msgmenu:reactions"' in js))
# serve() de punta a punta con el almacén del núcleo (Metis en #703): un Conn falso y un reloj que
# avanza en cada recv, sobre un PAYNANI_STATE temporal. Sin store.react (antes de #702), no aplica.
import os  # noqa: E402

os.environ["PAYNANI_STATE"] = str(Path(tempfile.mkdtemp()) / "state")
Path(os.environ["PAYNANI_STATE"]).mkdir()
from paynani_lib.webchat import store as wc_store  # noqa: E402
from paynani_lib.web import websocket as wsmod  # noqa: E402

if callable(getattr(wc_store, "react", None)):
    first = wc_store.append("owner", "¿Ya quedó?", [], owner={"name": "Julián", "email": "julian@example.com"})
    sent: list[dict] = []
    t = [0.0]
    steps = [lambda: None, lambda: None,
             lambda: wc_store.react(first["id"], "👍", by="agent"), lambda: None, lambda: None,
             lambda: wc_store.react(first["id"], "", by="agent"), lambda: None, lambda: None]

    class FakeConn:
        def __init__(self):
            self.hello = True

        def recv(self, timeout):
            if self.hello:
                self.hello = False
                return (wsmod.TEXT, json.dumps({"type": "connect", "csrf": "ok", "after": first["id"]}))
            t[0] += 5.0
            if not steps:
                raise wsmod.Closed()
            steps.pop(0)()
            return None

        def send_text(self, text):
            sent.append(json.loads(text))

        def send(self, opcode, payload=b""):
            pass

        def close(self, code=1000):
            pass

    webchat_ws.serve(FakeConn(), wc_store, csrf_ok=lambda tok: tok == "ok", owner={"name": "Julián"},
                     render=lambda new, day: ("", day), texts={}, clock=lambda: t[0])
    got = [m for m in sent if m.get("type") == "reactions"]
    check("serve(): la primera vuelta no manda reactions; después, el 👍 del agente y luego []",
          [{first["id"]: [{"emoji": "👍", "count": 1, "mine": False}]}, {first["id"]: []}],
          [m.get("items") for m in got])
else:
    check("serve() con reacciones: el almacén todavía no tiene react (antes de #702), no aplica", True, True)

check("el .env y Himalaya de la instalación no cambiaron", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
