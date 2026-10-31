#!/usr/bin/env python3
"""
Regresión de PaynaniWeb contra el servicio de Telegram de verdad (TG-7 con TG-2; #615,
#617): «Bot de Telegram» por HTTP, con `telegram_source.ControlSocket` hablando con un
`TelegramService` real por su `control.sock`, y la Bot API de `FakeBotAPI` con tres bots
en una sola base (`add_bot`), como en producción, donde cambia el token y no la base.

Cubre: el estado, un token que Telegram rechaza, el mismo token (`unchanged`), un
`check` de un solo uso, un token distinto que sí sirve (`applied`, `telegram.env` cambia
sólo ahí), y uno cuyo `getUpdates` responde 409 (`rollback`, el bot anterior sigue
funcionando). Ningún token ni `check` sale en las páginas, y ningún token en el log del
servicio.

Todo en carpetas temporales: `telegram.env` va en una de ellas (`env_path` del servicio y
`telegram_root` de la web), nunca en el clon. Al final se comprueba que el sha256 del
`.env` y de la configuración de Himalaya de la instalación no cambiaron.
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
    """El `.env` de la instalación según `harness/paths.py` (en OpenClaw no es el de
    Claude Code; revisión de Ximena en #617)."""
    import paths
    try:
        return Path(paths.env_file())
    except Exception:  # noqa: BLE001 -- sin un .env resoluble, se vigila el de Claude Code
        return Path.home() / ".claude/workspace/.env"


REAL = [real_env(), Path.home() / ".config/himalaya/config.toml"]
BEFORE = [sha(p) for p in REAL]

# Tokens de prueba con la forma de config.TOKEN_RE; no son de ningún bot.
TOKEN = "424242:" + "k" * 30          # el bot con el que arranca
OTHER = "515151:" + "q" * 30          # uno que la Bot API no conoce: getMe → 401
NEWT = "616161:" + "n" * 30           # un segundo bot en la misma base: applied
BADT = "717171:" + "b" * 30           # un tercero cuyo getUpdates responde 409: rollback
TOKENS = (TOKEN, OTHER, NEWT, BADT)
PASSWORD = "una-contraseña-larga"

api = FakeBotAPI(token=TOKEN, bot_id=424242, username="IntegPaynaniBot").start()
api.add_bot(NEWT, 616161, "NuevoPaynaniBot")
bad = api.add_bot(BADT, 717171, "OcupadoPaynaniBot")
for _ in range(5):
    bad.fail_next("getUpdates", 409)

tmp = Path(tempfile.mkdtemp())
state = tmp / "state"
state.mkdir()
roster = tmp / "roster.md"
roster.write_text("| Name | Email |\n|---|---|\n| Julian Flores | julian@example.com |\n", encoding="utf-8")
cfg = tmp / "cfg"
cfg.mkdir()
envf = cfg / "telegram.env"
config.write({"TELEGRAM_ENABLED": "1", **config.with_token({}, TOKEN)}, envf)
before_env = envf.read_bytes()

# El servicio en su propio loop, en un hilo; la web le habla por control.sock.
logs: list[str] = []
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()
service = TelegramService(state, roster_path=roster, token=TOKEN, api_base=api.base_url, env_path=envf,
                          log=logs.append, poll_timeout=1, backoff=(0.05, 0.2), ready_timeout_s=3.0)
asyncio.run_coroutine_threadsafe(service.start(), loop).result(15)
src = telegram_source.ControlSocket(state / "telegram" / "control.sock", timeout=20)


def wait_status(cond, timeout=10.0) -> dict:
    end = time.monotonic() + timeout
    st = src.status()
    while time.monotonic() < end and not cond(st):
        time.sleep(0.1)
        st = src.status()
    return st


wait_status(lambda s: s.get("state") == "running")

uf = tmp / "web" / "user.json"
users.create("julian@example.com", "Julian Flores", PASSWORD, uf)
mails = []
(tmp / "webstate").mkdir()
ctx = app.Context(uf, notifier=notify.Notifier(send=lambda *a: mails.append(a), log=lambda l: None),
                  agent_email="agente@example.com", accounts_file=tmp / "accounts.json", state_dir=tmp / "webstate",
                  roster_path=roster, telegram_source=src, telegram_root=cfg, whatsapp_root=tmp)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
pages: list[str] = []


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
    pages.append(data)
    return r.status, hdrs, data


i18n.set_current("es-MX")
t = i18n.t
try:
    check("la web ve Telegram configurado con el telegram.env temporal", True, ctx.telegram_configured())
    _, h, _ = req("POST", "/login", {"email": "julian@example.com", "password": PASSWORD})
    ck = next(c for c in h["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]
    st, _, page = req("GET", "/telegram?lang=es-MX", cookie=ck)
    check("GET /telegram: el estado y el @usuario del servicio", (200, True, True),
          (st, t("web.tg.state.running") in page, "@IntegPaynaniBot" in page))
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)

    st, _, page = req("POST", "/telegram/token/check", {"csrf": csrf, "token": OTHER, "password": PASSWORD}, ck)
    check("un token que Telegram rechaza (getMe 401)", (400, True), (st, t("web.tg.err.token_rejected") in page))

    st, _, page = req("POST", "/telegram/token/check", {"csrf": csrf, "token": TOKEN, "password": PASSWORD}, ck)
    check("el mismo token: «es el mismo token»", (200, True), (st, t("web.tg.check_same") in page))
    st, h, _ = req("POST", "/telegram/token/apply", {"csrf": csrf, "confirm_dedicated": "1"}, ck)
    check("unchanged → /telegram?ok=unchanged", (303, "/telegram?ok=unchanged"), (st, h.get("location")))
    st, _, _ = req("POST", "/telegram/token/apply", {"csrf": csrf, "confirm_dedicated": "1"}, ck)
    check("el check es de un solo uso", 409, st)
    check("telegram.env no cambia con unchanged", before_env, envf.read_bytes())

    st, _, page = req("POST", "/telegram/token/check", {"csrf": csrf, "token": NEWT, "password": PASSWORD}, ck)
    check("token nuevo: la confirmación con @NuevoPaynaniBot", (200, True), (st, "@NuevoPaynaniBot" in page))
    st, h, _ = req("POST", "/telegram/token/apply", {"csrf": csrf, "confirm_dedicated": "1"}, ck)
    check("applied → /telegram?ok=applied", (303, "/telegram?ok=applied"), (st, h.get("location")))
    after_apply = envf.read_bytes()
    check("telegram.env cambia sólo en applied, con el token nuevo", (True, NEWT), (after_apply != before_env,
          config.token(config.read(envf))))
    st, _, page = req("GET", "/telegram?ok=applied&lang=es-MX", cookie=ck)
    check("la página dice el bot nuevo", True, t("web.tg.applied", bot="NuevoPaynaniBot") in page)
    check("al dueño le llega el aviso de la web con el bot nuevo y sin token", (True, False),
          (any("NuevoPaynaniBot" in str(m) for m in mails), any(x in str(m) for m in mails for x in TOKENS)))

    st, _, page = req("POST", "/telegram/token/check", {"csrf": csrf, "token": BADT, "password": PASSWORD}, ck)
    st, _, page = req("POST", "/telegram/token/apply", {"csrf": csrf, "confirm_dedicated": "1"}, ck)
    check("rollback por 409: 409 y «se quedó el anterior»", (409, True), (st, t("web.tg.rollback", reason="409") in page))
    check("telegram.env se queda con el token aplicado antes", after_apply, envf.read_bytes())
    final = wait_status(lambda s: s.get("state") == "running" and s.get("bot_username") == "NuevoPaynaniBot")
    check("tras el rollback, el bot anterior sigue funcionando", ("running", "NuevoPaynaniBot"),
          (final.get("state"), final.get("bot_username")))

    check("ninguna página trae un token", [], [x[:6] for x in TOKENS if any(x in p for p in pages)])
    check("ninguna página trae un check", False, any(re.search(r"c_[0-9a-f]{32}", p) for p in pages))
finally:
    httpd.shutdown()
    asyncio.run_coroutine_threadsafe(service.stop(), loop).result(15)

    async def _drain():
        # Lo que quede del loop (un getUpdates en vuelo) se cancela antes de pararlo.
        rest = [x for x in asyncio.all_tasks() if x is not asyncio.current_task()]
        for x in rest:
            x.cancel()
        await asyncio.gather(*rest, return_exceptions=True)

    asyncio.run_coroutine_threadsafe(_drain(), loop).result(15)
    loop.call_soon_threadsafe(loop.stop)
    api.stop()
log_text = "\n".join(logs)
check("el log del servicio no trae ningún token", [], [x[:6] for x in TOKENS if x in log_text])
check("ni ningún check (revisión de Ximena, #617)", False, bool(re.search(r"c_[0-9a-f]{32}", log_text)))
check("no se escribió telegram.env en el clon", False, (ROOT / "telegram.env").exists())
check("la configuración real no cambió (.env y Himalaya)", BEFORE, [sha(p) for p in REAL])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
