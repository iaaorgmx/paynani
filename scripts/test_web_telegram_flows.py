#!/usr/bin/env python3
"""
Regresión de PaynaniWeb contra el servicio de Telegram de verdad (TG-7 con TG-3 y TG-4;
#615, #618, #619): «Mensajes de Telegram» por HTTP, con `telegram_source.ControlSocket`
hablando con un `TelegramService` real por su `control.sock`, y la Bot API de
`FakeBotAPI`.

Cubre: un contacto del roster (columna `Telegram`) que escribe y se ve, contestarle
desde la web (sale un `sendMessage` y vuelve como del dueño), alguien fuera del roster
oculto y sin responder, «Agregar al roster» con la contraseña (FR-15: el id sólo en ese
formulario) y el Catch-All de Telegram en su propia página. Ningún token ni id de
Telegram sale en las páginas, salvo el del formulario de FR-15.

Todo en carpetas temporales: `telegram.env` y `rules/` en una de ellas, nunca en el
clon. Al final se comprueba que el sha256 del `.env` (de `paths.env_file()`) y de la
configuración de Himalaya de la instalación no cambiaron.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.telegram import config  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402
from paynani_lib.web import app, auth, notify, telegram_source, telegram_strings, users  # noqa: E402,F401

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

TOKEN = "424242:" + "k" * 30           # forma de config.TOKEN_RE; no es de ningún bot
ANA, PEDRO = 7000001, 7000099          # ids de Telegram inventados
PASSWORD = "una-contraseña-larga"

api = FakeBotAPI(token=TOKEN, bot_id=424242, username="FlujosPaynaniBot").start()
tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
(tmp / "rules").mkdir()
roster = tmp / "roster.md"
roster.write_text("| Name | Email | Type | Telegram |\n|---|---|---|---|\n"
                  "| Julian Flores | julian@example.com | Human |  |\n"
                  f"| Ana López | ana@example.com | Human | {ANA} |\n", encoding="utf-8")
cfg = tmp / "cfg"
cfg.mkdir()
envf = cfg / "telegram.env"
config.write({"TELEGRAM_ENABLED": "1", **config.with_token({}, TOKEN)}, envf)

logs: list[str] = []
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()
service = TelegramService(state, roster_path=roster, token=TOKEN, api_base=api.base_url, env_path=envf,
                          log=logs.append, mail_owner=lambda s, b: None, rules_root=tmp,
                          poll_timeout=1, backoff=(0.05, 0.2), ready_timeout_s=3.0)
asyncio.run_coroutine_threadsafe(service.start(), loop).result(15)
src = telegram_source.ControlSocket(state / "telegram" / "control.sock", timeout=20)

uf = tmp / "web" / "user.json"
users.create("julian@example.com", "Julian Flores", PASSWORD, uf)
ctx = app.Context(uf, notifier=notify.Notifier(send=lambda *a: None, log=lambda l: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", state_dir=state,
                  roster_path=roster, roster_notifier=lambda *a, **k: None, telegram_source=src,
                  telegram_root=cfg, whatsapp_root=tmp)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
pages: list[tuple[str, str]] = []


def req(method, path, form=None, cookie=""):
    h = {"Host": "agente.test", "X-Forwarded-For": "203.0.113.9"}
    body = None
    if cookie:
        h["Cookie"] = cookie
    if form is not None:
        body = urlencode(form)
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Origin"] = "https://agente.test"
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read().decode("utf-8", "replace")
    hdrs = {k.lower(): v for k, v in r.getheaders()}
    hdrs["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    c.close()
    pages.append((path, data))
    return r.status, hdrs, data


def until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = cond()
        if value:
            return value
        time.sleep(0.1)
    return cond()


def threads():
    try:
        return src.request("telegram.threads", limit=50, before=None).get("threads") or []
    except telegram_source.Failed:
        return []


i18n.set_current("es-MX")
th = i18n.th
try:
    until(lambda: src.status().get("state") == "running")
    api.private_message(ANA, "¿Tienen mesa a las 8?", first_name="Ana")
    api.private_message(PEDRO, "Hola, ¿hacen envíos?", first_name="Pedro")
    rows = until(lambda: (lambda t: t if len(t) >= 2 else None)(threads())) or []
    ana = next((t for t in rows if t.get("in_roster")), None)
    pedro = next((t for t in rows if not t.get("in_roster")), None)
    check("el servicio ve a Ana en el roster y a Pedro fuera", (True, True), (ana is not None, pedro is not None))

    _, h, _ = req("POST", "/login", {"email": "julian@example.com", "password": PASSWORD})
    ck = next(c for c in h["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
    st, _, page = req("GET", "/telegram/messages?lang=es-MX", cookie=ck)
    check("la lista con las dos conversaciones; lo de Pedro oculto", (200, 2, True, False),
          (st, page.count('href="/telegram/messages/ver?t='), th("web.tg.hidden_short") in page, "hacen envíos" in page))

    st, _, page = req("GET", f"/telegram/messages/ver?t={ana['thread']}&lang=es-MX", cookie=ck)
    check("el hilo de Ana con su mensaje y el cuadro de responder", (200, True, True),
          (st, "¿Tienen mesa a las 8?" in page, 'action="/telegram/messages/enviar"' in page))
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    st, h, _ = req("POST", "/telegram/messages/enviar", {"csrf": csrf, "t": ana["thread"], "text": "Sí, a las 8."}, ck)
    check("contestar → ok=sent", (303, True), (st, h.get("location", "").endswith("&ok=sent#responder")))
    check("salió un sendMessage a Telegram con el texto", True,
          until(lambda: any("Sí, a las 8." in str(s) for s in api.sent)) is True)
    st, _, page = req("GET", f"/telegram/messages/ver?t={ana['thread']}&lang=es-MX", cookie=ck)
    mine = page[page.index("Sí, a las 8.") - 400:page.index("Sí, a las 8.")] if "Sí, a las 8." in page else ""
    check("y vuelve en el hilo como del dueño", (True, True), ('class="sms sms-human"' in mine, th("web.tg.by_owner") in mine))

    st, _, page = req("GET", f"/telegram/messages/ver?t={pedro['thread']}&lang=es-MX", cookie=ck)
    check("Pedro: oculto, sin responder y con «Agregar al roster»", (200, True, False, True),
          (st, th("web.tg.hidden") in page, 'action="/telegram/messages/enviar"' in page, 'action="/telegram/roster"' in page))
    st, _, page = req("POST", "/telegram/messages/enviar", {"csrf": csrf, "t": pedro["thread"], "text": "hola"}, ck)
    check("FR-25: escribirle a Pedro lo rechaza el servicio", (400, True), (st, th("web.tg.err.not_allowed") in page))

    st, h, page = req("POST", "/telegram/roster", {"csrf": csrf, "t": pedro["thread"], "password": PASSWORD}, ck)
    check("FR-15: «Agregar al roster» trae el id de Pedro sólo en el formulario", (200, True, False),
          (st, f'value="{PEDRO}"' in page, "location" in h))

    st, _, page = req("GET", "/telegram/catch-all?lang=es-MX", cookie=ck)
    check("el Catch-All de Telegram abre en su página (catchall.get channel=telegram)", (200, True),
          (st, 'id="catchall-telegram"' in page))
    etag = re.search(r'name="etag" value="([^"]*)"', page).group(1)
    st, h, _ = req("POST", "/telegram/catch-all", {"csrf": csrf, "enabled": "1", "text": "Atiende pedidos.",
                                                  "etag": etag, "password": PASSWORD}, ck)
    check("activarlo guarda rules/catch-all-telegram.md y vuelve a su página", (303, "/telegram/catch-all?ok=on", True),
          (st, h.get("location"), (tmp / "rules" / "catch-all-telegram.md").exists()))

    # El token, el id de Ana y el bot_id no salen en ninguna página, tampoco en la de FR-15.
    # El id de Pedro sólo sale en esa respuesta, y sólo en su campo (revisión de Ximena, #621).
    field = f'name="telegram" maxlength="64" autocomplete="off" spellcheck="false" value="{PEDRO}"'
    leaks = [(p, x) for p, html in pages for x in (TOKEN, str(ANA), "424242") if x in html]
    leaks += [(p, str(PEDRO)) for p, html in pages
              if str(PEDRO) in (html.replace(field, "") if p == "/telegram/roster" else html)]
    check("ningún token ni id de Telegram en las páginas; el de Pedro sólo en el campo de FR-15", [], leaks)
    check("y la página de FR-15 trae ese campo exacto una vez", 1,
          sum(html.count(field) for p, html in pages if p == "/telegram/roster"))
finally:
    httpd.shutdown()
    asyncio.run_coroutine_threadsafe(service.stop(), loop).result(15)

    async def _drain():
        rest = [x for x in asyncio.all_tasks() if x is not asyncio.current_task()]
        for x in rest:
            x.cancel()
        await asyncio.gather(*rest, return_exceptions=True)

    asyncio.run_coroutine_threadsafe(_drain(), loop).result(15)
    loop.call_soon_threadsafe(loop.stop)
    api.stop()
log_text = "\n".join(logs)
check("el log del servicio no trae el token ni los ids", [], [x for x in (TOKEN, str(ANA), str(PEDRO)) if x in log_text])
check("no se escribió telegram.env en el clon", False, (ROOT / "telegram.env").exists())
check("la configuración real no cambió (.env y Himalaya)", BEFORE, [sha(p) for p in REAL])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
