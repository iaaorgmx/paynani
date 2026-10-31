#!/usr/bin/env python3
"""
Tests de Telegram en PaynaniWeb (PRD #609 FR-10, FR-15, FR-25, FR-28; TG-7 de #612):
el menú sólo con Telegram configurado, «Bot de Telegram» con el cambio de token en dos
pasos (contraseña, CSRF, el token sólo en `token_check` y el `check` sólo en memoria),
«Mensajes de Telegram» con lo de fuera del roster oculto y responder sólo donde se
puede, «Agregar al roster» con la contraseña, el Catch-All propio y que ni el token ni
los ids de Telegram salgan en las páginas, salvo el id en el formulario de FR-15.

Un PaynaniWeb real en un puerto libre con la fuente de demostración
(`telegram_source.Demo`); nada sale de la máquina. Al final se comprueba que el sha256
del `.env` y de la configuración de Himalaya de la instalación no cambiaron.
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

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import app, auth, notify, telegram_pages, telegram_source, users  # noqa: E402

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

PASSWORD = "una-contraseña-larga"
NEW_TOKEN = "987654321:" + "Zq" * 18          # forma de BotFather, inventado
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
(clone / "state").mkdir(parents=True)
(clone / "roster.md").write_text("| Name | Email |\n|---|---|\n| Julián Flores | julian@example.com |\n",
                                 encoding="utf-8")
tg_root = clone / "cfg"
tg_root.mkdir()
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
owner_mail = []
demo = telegram_source.Demo()
DEMO_TOKEN = demo.token
TG_IDS = [t["tg"] for t in demo.threads]
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda to, s, b: owner_mail.append((to, s, b)),
                                                      log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "no-accounts.json",
                  state_dir=clone / "state", roster_path=clone / "roster.md",
                  telegram_source=demo, telegram_root=tg_root, whatsapp_root=clone)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"
PAGES: list[tuple[str, str]] = []      # (ruta, html) de todo lo que devolvió la web


def req(method, path, *, form=None, cookie="", origin=True):
    h = {"Host": HOST, "X-Forwarded-For": "203.0.113.5"}
    if cookie:
        h["Cookie"] = cookie
    body = None
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        if origin:
            h["Origin"] = f"https://{HOST}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    PAGES.append((path, data))
    return r.status, out, data


def login():
    _, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
    return next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


def acts() -> list:
    """Lo que la web le pidió al servicio, sin las lecturas de estado de cada página."""
    return [c for c in demo.calls if c[0] != "telegram.status"]


def csrf_of(page: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


i18n.set_current("es-MX")
th = i18n.th
cookie = login()

# ---- Sin Telegram configurado ------------------------------------------------------
status, _, page = req("GET", "/?lang=es-MX", cookie=cookie)
check("sin telegram.env no hay «Mensajes de Telegram» en el menú", False, 'href="/telegram/messages"' in page)
for path in ("/telegram", "/telegram/messages", "/telegram/catch-all"):
    status, _, _ = req("GET", path, cookie=cookie)
    check(f"sin Telegram, {path} es 404", 404, status)
(tg_root / "telegram.env").write_text("TELEGRAM_ENABLED=1\n", encoding="utf-8")
check("§4: sin TELEGRAM_TOKEN no cuenta como configurado", False, telegram_source.configured(tg_root))
(tg_root / "telegram.env").write_text(f"TELEGRAM_ENABLED=1\nTELEGRAM_TOKEN={DEMO_TOKEN}\n", encoding="utf-8")
(tg_root / "telegram.env").chmod(0o600)
check("§4: con TELEGRAM_ENABLED=1 y el token, sí", True, telegram_source.configured(tg_root))

# ---- Menú y «Bot de Telegram» ------------------------------------------------------
status, _, page = req("GET", "/?lang=es-MX", cookie=cookie)
check("FR-28: el menú agrega «Mensajes de Telegram»", True,
      'href="/telegram/messages"' in page and th("web.tg.nav") in page)
status, hdrs, page = req("GET", "/telegram?lang=es-MX", cookie=cookie)
check("«Bot de Telegram»: estado y @usuario", (200, True, True),
      (status, th("web.tg.state.running") in page, "@PruebaPaynaniBot" in page))
check("no-store", True, "no-store" in hdrs.get("cache-control", ""))
check("§7: el campo del token es type=password con autocomplete=off", True,
      bool(re.search(r'<input id="tg-token" name="token" type="password" autocomplete="off"', page)))
check("el token actual nunca sale", False, DEMO_TOKEN in page or DEMO_TOKEN.split(":")[1][:8] in page)
check("sin atributos style", [], re.findall(r'\sstyle="', page))
csrf = csrf_of(page)

calls = len(acts())
status, _, page = req("POST", "/telegram/token/check", form={"csrf": csrf, "token": NEW_TOKEN, "password": ""},
                      cookie=cookie)
check("FR-10: sin la contraseña no llega al servicio", (400, calls, True),
      (status, len(acts()), th("web.tg.err.password") in page))
status, _, page = req("POST", "/telegram/token/check", form={"csrf": csrf, "token": NEW_TOKEN, "password": "mala"},
                      cookie=cookie)
check("FR-10: con la contraseña equivocada tampoco", (403, calls), (status, len(acts())))
check("y la página no devuelve el token escrito", False, NEW_TOKEN in page)
status, _, page = req("POST", "/telegram/token/check", form={"csrf": "malo", "token": NEW_TOKEN, "password": PASSWORD},
                      cookie=cookie)
check("sin el CSRF, 403 y nada al servicio", (403, calls), (status, len(acts())))
status, _, page = req("POST", "/telegram/token/check", form={"csrf": csrf, "token": "no-es-un-token",
                                                             "password": PASSWORD}, cookie=cookie)
check("un token con otra forma no llega al servicio", (400, calls, True),
      (status, len(acts()), th("web.tg.err.token_format") in page))
status, _, page = req("POST", "/telegram/token/check", form={"csrf": csrf, "token": NEW_TOKEN, "password": PASSWORD},
                      cookie=cookie)
check("FR-10 paso 1: token_check y la confirmación con el bot nuevo", (200, True, True),
      (status, acts()[-1][0] == "telegram.token_check", "@NuevoPaynaniBot" in page))
check("el servicio no queda con el token en su registro de llamadas de la web", "…", acts()[-1][1]["token"])
check("la confirmación no trae el token ni el check", (False, False),
      (NEW_TOKEN in page, bool(re.search(r"c_[0-9a-f]{32}", page))))
check("confirm_dedicated es obligatorio en el formulario", True,
      'name="confirm_dedicated" value="1" required' in page)
status, _, page = req("POST", "/telegram/token/apply", form={"csrf": csrf}, cookie=cookie)
check("sin confirmar que el token es sólo de aquí, no se aplica", (400, "telegram.token_check"),
      (status, acts()[-1][0]))
status, hdrs, _ = req("POST", "/telegram/token/apply", form={"csrf": csrf, "confirm_dedicated": "1"}, cookie=cookie)
check("FR-10: aplicado → /telegram?ok=applied", (303, "/telegram?ok=applied"), (status, hdrs.get("location")))
check("el servicio recibió token_apply con el check de la sesión, no del formulario", True,
      acts()[-1][0] == "telegram.token_apply" and acts()[-1][1]["check"].startswith("c_")
      and acts()[-1][1]["confirm_dedicated"] is True)
token_mail = [m for m in owner_mail if m[1] == i18n.t("web.tg.mail_subject")]
check("al dueño le llega un aviso sin el token", (1, False, True),
      (len(token_mail), NEW_TOKEN in token_mail[-1][2], "@NuevoPaynaniBot" in token_mail[-1][2]))
status, _, page = req("GET", "/telegram?ok=applied&lang=es-MX", cookie=cookie)
check("y la página lo dice", True, i18n.t("web.tg.applied", bot="NuevoPaynaniBot") in page)
status, _, page = req("POST", "/telegram/token/apply", form={"csrf": csrf, "confirm_dedicated": "1"}, cookie=cookie)
check("§4: el check es de un solo uso", (409, True), (status, th("web.tg.check_expired") in page))

demo.webhook = True
demo.apply_result = "rollback"
req("POST", "/telegram/token/check", form={"csrf": csrf, "token": "111111:" + "w" * 35, "password": PASSWORD},
    cookie=cookie)
status, _, page = req("POST", "/telegram/token/apply", form={"csrf": csrf, "confirm_dedicated": "1"}, cookie=cookie)
check("con webhook, también hay que confirmar que se borra", (400, True),
      (status, 'name="confirm_webhook" value="1" required' in page))
status, _, page = req("POST", "/telegram/token/apply", form={"csrf": csrf, "confirm_dedicated": "1",
                                                             "confirm_webhook": "1"}, cookie=cookie)
check("FR-10: un rollback se dice y se queda el anterior", (409, True, True),
      (status, i18n.t("web.tg.rollback", reason="409") in page, acts()[-1][1]["confirm_delete_webhook"]))
req("POST", "/telegram/token/check", form={"csrf": csrf, "token": "222222:" + "v" * 35, "password": PASSWORD},
    cookie=cookie)
status, hdrs, _ = req("POST", "/telegram/token/cancel", form={"csrf": csrf}, cookie=cookie)
check("cancelar olvida el check", (303, None), (status, ctx.tg_check(next(iter(ctx._tg_checks), "x"))))
demo.webhook, demo.apply_result = False, "applied"

other = login()
status, _, page = req("POST", "/telegram/token/check", form={"csrf": csrf, "token": NEW_TOKEN, "password": PASSWORD},
                      cookie=cookie)
status, _, page = req("GET", "/telegram?lang=es-MX", cookie=other)
csrf2 = csrf_of(page)
status, _, page = req("POST", "/telegram/token/apply", form={"csrf": csrf2, "confirm_dedicated": "1"}, cookie=other)
check("el check de una sesión no lo usa otra", (409, True), (status, th("web.tg.check_expired") in page))
req("POST", "/telegram/token/cancel", form={"csrf": csrf}, cookie=cookie)

# ---- Mensajes de Telegram ----------------------------------------------------------
status, _, page = req("GET", "/telegram/messages?lang=es-MX", cookie=cookie)
roster_thread = next(t for t in demo.threads if t["in_roster"] and t["name"] == "Ana López")
outside = next(t for t in demo.threads if not t["in_roster"])
check("la lista con las tres conversaciones y los enlaces a Bot y Catch-All", (200, 3, True, True),
      (status, page.count('href="/telegram/messages/ver?t='), 'href="/telegram"' in page,
       'href="/telegram/catch-all"' in page))
check("FR-28: sin «nuevo mensaje»", False, "/telegram/messages/nuevo" in page)
check("lo de fuera del roster va oculto y «no verificado»", (True, False, True),
      (th("web.tg.hidden_short") in page, "hacen envíos" in page, "Pedro (no verificado)" in page))
check("los hilos se nombran por su id opaco", True, f'?t={roster_thread["thread"]}' in page)

status, _, page = req("GET", f"/telegram/messages/ver?t={roster_thread['thread']}&lang=es-MX", cookie=cookie)
check("un hilo del roster: mensajes en orden de hora y el cuadro de responder", (200, True, True),
      (status, page.index("¿Tienen mesa a las 8?") < page.index("Somos 4. Gracias."),
       'action="/telegram/messages/enviar"' in page))
check("un mensaje editado lo dice", True, f'({th("web.tg.edited")})' in page)
check("la foto se pide por su referencia opaca", True, 'src="/telegram/media?ref=tg%3Ademo02"' in page)
check("sin «Agregar al roster» en un contacto del roster", False, 'action="/telegram/roster"' in page)
csrf = csrf_of(page)
status, hdrs, _ = req("POST", "/telegram/messages/enviar", form={"csrf": csrf, "t": roster_thread["thread"],
                                                                 "text": "Los esperamos."}, cookie=cookie)
check("contestar → el hilo con ok=sent", (303, True),
      (status, hdrs.get("location", "").endswith("&ok=sent#responder")))
status, _, page = req("GET", f"/telegram/messages/ver?t={roster_thread['thread']}&lang=es-MX", cookie=cookie)
mine = page[page.index("Los esperamos.") - 400:page.index("Los esperamos.")]
check("#615: lo que mandó esta web vuelve como by=owner y se dibuja como del dueño",
      (True, True), ('class="sms sms-human"' in mine, th("web.tg.by_owner") in mine))
synthetic = {"thread": "t_" + "0" * 32, "name": "Ana", "in_roster": True, "can_reply": True, "messages": [
    {"ref": "tgo:a", "dir": "out", "at": "2026-11-02T19:00:00Z", "kind": "text", "text": "desde-web", "by": "web"},
    {"ref": "tgo:b", "dir": "out", "at": "2026-11-02T19:01:00Z", "kind": "text", "text": "desde-app", "by": "phone:d_x1"},
    {"ref": "tgo:c", "dir": "out", "at": "2026-11-02T19:02:00Z", "kind": "text", "text": "desde-agente", "by": "agent"}]}
html = telegram_pages.thread_body(synthetic, "")
def bubble(text):
    return html[html.rindex("<li", 0, html.index(text)):html.index(text)]
check("#615: si llegaran sin convertir, by=web y by=phone:* también son del dueño (revisión de Ximena)",
      ["sms-human", "sms-human", "sms-agent"],
      [("sms-human" if "sms-human" in bubble(t) else "sms-agent") for t in ("desde-web", "desde-app", "desde-agente")])
check("y el device_id no se muestra", False, "d_x1" in html)
check("sender(): web y phone:* → dueño; agent y terminal → agente; api; otro → \"\"",
      ["owner", "owner", "owner", "agent", "agent", "api", ""],
      [telegram_pages.sender(b) for b in ("web", "phone:d_x", "owner", "agent", "terminal", "api", "raro")])
check("el servicio recibió el texto, sin archivo", ("telegram.send", "Los esperamos.", False),
      next((c[0], c[1]["text"], "file" in c[1]) for c in reversed(acts()) if c[0] == "telegram.send"))

status, _, page = req("GET", f"/telegram/messages/ver?t={outside['thread']}&lang=es-MX", cookie=cookie)
check("fuera del roster: oculto, sin responder y con «Agregar al roster»", (200, True, False, True),
      (status, th("web.tg.hidden") in page, 'action="/telegram/messages/enviar"' in page,
       'action="/telegram/roster"' in page))
check("y el id de Telegram no está en la página", False, outside["tg"] in page)
status, _, page = req("POST", "/telegram/messages/enviar", form={"csrf": csrf, "t": outside["thread"], "text": "hola"},
                      cookie=cookie)
check("FR-25: escribirle a alguien fuera del roster lo rechaza el servicio", (400, True),
      (status, th("web.tg.err.not_allowed") in page))
status, _, _ = req("GET", "/telegram/messages/ver?t=123456789", cookie=cookie)
check("un hilo que no es t_… es 404 y no llega al servicio", 404, status)
status, _, _ = req("GET", "/telegram/media?ref=/etc/passwd", cookie=cookie)
check("/telegram/media con una referencia rara: 404", 404, status)
status, _, _ = req("GET", "/telegram/media?ref=tg:demo02", cookie=cookie)
check("/telegram/media sin archivo: el mismo 404", 404, status)

# ---- Agregar al roster (FR-15) -----------------------------------------------------
calls = len(acts())
status, _, page = req("POST", "/telegram/roster", form={"csrf": csrf, "t": outside["thread"], "password": ""},
                      cookie=cookie)
check("FR-15: sin la contraseña no pide el id", (400, False, True),
      (status, any(c[0] == "telegram.roster_candidate" for c in acts()[calls:]), th("web.tg.err.password") in page))
status, _, page = req("POST", "/telegram/roster", form={"csrf": csrf, "t": outside["thread"], "password": "mala"},
                      cookie=cookie)
check("con la contraseña equivocada tampoco", (403, False), (status, outside["tg"] in page))
status, hdrs, page = req("POST", "/telegram/roster", form={"csrf": csrf, "t": outside["thread"], "password": PASSWORD},
                         cookie=cookie)
check("FR-15: con la contraseña, el formulario de la fila nueva con el id y el nombre", (200, True, True, True),
      (status, f'name="telegram" maxlength="64" autocomplete="off" spellcheck="false" value="{outside["tg"]}"' in page,
       'value="Pedro"' in page, 'action="/roster/guardar"' in page))
check("respondido con no-store y sin el id en la URL", (True, False),
      ("no-store" in hdrs.get("cache-control", ""), "location" in hdrs))

# ---- Catch-All de Telegram ---------------------------------------------------------
status, _, page = req("GET", "/telegram/catch-all?lang=es-MX", cookie=cookie)
check("#613: /telegram/catch-all es su propia página, con la sección de Telegram", (True, True, True),
      (status in (200, 500), 'id="catchall-telegram"' in page, 'action="/telegram/catch-all"' in page))

# ---- El servicio caído ----------------------------------------------------------------
demo.state = "service_down"
status, _, page = req("GET", "/telegram?lang=es-MX", cookie=cookie)
check("servicio caído: el estado lo dice y no ofrece cambiar el token", (200, True, False),
      (status, th("web.tg.state.service_down") in page, 'name="token"' in page))
status, _, _ = req("GET", "/telegram/messages", cookie=cookie)
check("y «Mensajes de Telegram» responde 503", 503, status)
demo.state = "running"

# ---- Ningún secreto en las páginas -------------------------------------------------
leaks = []
for path, html in PAGES:
    if path == "/telegram/roster":
        continue          # FR-15: la única respuesta con un id de Telegram
    for secret in [DEMO_TOKEN, NEW_TOKEN, *TG_IDS]:
        if secret in html:
            leaks.append((path, secret[:6]))
check("§8: ni el token ni los ids de Telegram salen en ninguna otra página", [], leaks)
log = (clone / "state" / "web.log")
log_text = log.read_text(encoding="utf-8") if log.exists() else ""
check("§8: ni en el log de la web", [], [s[:6] for s in [DEMO_TOKEN, NEW_TOKEN, *TG_IDS] if s in log_text])

httpd.shutdown()
check("la configuración real no cambió (.env y Himalaya)", BEFORE, [sha(p) for p in REAL])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
