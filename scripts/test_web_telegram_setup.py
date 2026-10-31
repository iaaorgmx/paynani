#!/usr/bin/env python3
"""
La configuración inicial de Telegram desde PaynaniWeb (#635; Q279 y Q281 a Q283).

Un PaynaniWeb real en un puerto libre contra la Bot API falsa (`fake_api.FakeBotAPI`), con
telegram.env en una carpeta temporal y el arranque del servicio reemplazado: nada sale de
la máquina ni toca el servicio del host. Cada caso de error termina sin telegram.env, y
el token no aparece en ninguna página ni en el correo al dueño.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import re
import stat
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.telegram import config, setup  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.web import app, auth, notify, telegram_source, users  # noqa: E402

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
TOKEN = "222222:fake_setup_token_for_web_tests"     # forma de BotFather, inventado
OTHER = "333333:fake_token_that_telegram_rejects"
api = FakeBotAPI(token=TOKEN, bot_id=900000002, username="NegocioBot").start()
os.environ[config.API_ENV] = api.base_url

# --- setup.initial, sin la web ------------------------------------------------------
d = Path(tempfile.mkdtemp())
env = d / "telegram.env"
for label, kw, code in (
        ("algo que no es token", dict(token="123:corto", username="NegocioBot", dedicated=True), setup.NOT_A_TOKEN),
        ("un token que Telegram rechaza", dict(token=OTHER, username="NegocioBot", dedicated=True), setup.UNAUTHORIZED),
        ("Q282: otro usuario", dict(token=TOKEN, username="@OtroBot", dedicated=True), setup.USERNAME),
        ("Q282: usuario vacío", dict(token=TOKEN, username="", dedicated=True), setup.USERNAME),
        ("Q283: sin la casilla", dict(token=TOKEN, username="NegocioBot", dedicated=False), setup.DEDICATED)):
    try:
        setup.initial(kw.pop("token"), kw.pop("username"), env=env, **kw)
        got = "ok"
    except setup.SetupError as exc:
        got = exc.code
    check(f"initial: {label} → {code}, sin telegram.env", (code, False), (got, env.exists()))
# Dos configuraciones a la vez (Ximena en #639): una gana y la otra es already_configured,
# en hilos y en procesos. La escritura se hace lenta para que se encimen sí o sí.
import subprocess  # noqa: E402
import threading as _th  # noqa: E402
import time as _time  # noqa: E402

race = d / "race"
race.mkdir()
race_env = race / "telegram.env"
real_write = config.write


def slow_write(values, path=None, environ=None):
    _time.sleep(0.3)
    return real_write(values, path, environ)


config.write = slow_write
results, gate = [], _th.Barrier(4)


def contender():
    gate.wait()
    try:
        setup.initial(TOKEN, "NegocioBot", dedicated=True, env=race_env)
        results.append("ok")
    except setup.SetupError as exc:
        results.append(exc.code)


threads = [_th.Thread(target=contender) for _ in range(4)]
for th in threads:
    th.start()
for th in threads:
    th.join()
config.write = real_write
check("4 hilos a la vez: exactamente un ok y tres already_configured",
      ["already_configured"] * 3 + ["ok"], sorted(results))

race_env.unlink()
child = (
    "import sys, time\n"
    f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); sys.path.insert(0, {str(ROOT / 'harness')!r})\n"
    "from pathlib import Path\n"
    "from paynani_lib.telegram import config, setup\n"
    "real = config.write\n"
    "config.write = lambda v, p=None, e=None: (time.sleep(0.3), real(v, p, e))[1]\n"
    "while time.time() < float(sys.argv[1]): time.sleep(0.005)\n"
    "try:\n"
    "    setup.initial(sys.argv[2], 'NegocioBot', dedicated=True, env=Path(sys.argv[3])); print('ok')\n"
    "except setup.SetupError as exc:\n"
    "    print(exc.code)\n")
start = str(_time.time() + 1.5)
procs = [subprocess.Popen([sys.executable, "-c", child, start, TOKEN, str(race_env)], stdout=subprocess.PIPE,
                          text=True, env=dict(os.environ)) for _ in range(3)]
outs = sorted(pr.communicate(timeout=60)[0].strip() for pr in procs)
check("3 procesos a la vez: exactamente un ok y dos already_configured",
      ["already_configured", "already_configured", "ok"], outs)
check("el token que quedó es el bueno y 0600", (TOKEN, 0o600),
      (config.token(config.read(race_env)), stat.S_IMODE(os.stat(race_env).st_mode)))
check("el candado no deja el token en su archivo", False,
      TOKEN in (race / ".telegram-setup.lock").read_text(encoding="utf-8", errors="replace"))

check("el usuario se compara sin @ y sin mayúsculas", "NegocioBot", setup.normalize_username(" @NegocioBot "))
check("un usuario con espacios no es usuario", None, setup.normalize_username("Negocio Bot"))

# --- PaynaniWeb -------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
(clone / "state").mkdir(parents=True)
(clone / "roster.md").write_text("| Name | Email |\n|---|---|\n| Julián Flores | julian@example.com |\n",
                                 encoding="utf-8")
tg_root = clone / "cfg"
tg_root.mkdir()
tg_env = tg_root / "telegram.env"
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
owner_mail = []


def tg_mail():
    """Los avisos de Telegram al dueño; el de la entrada desde una dirección nueva no cuenta."""
    return [m for m in owner_mail if "Telegram" in m[1]]


started = {"result": "started", "calls": 0}


class Ctx(app.Context):
    def telegram_start(self) -> str:   # nunca el servicio real del host
        started["calls"] += 1
        return started["result"]


ctx = Ctx(user_file, notifier=notify.Notifier(send=lambda to, s, b: owner_mail.append((to, s, b)),
                                              log=lambda line: None),
          agent_email="agente@example.com", accounts_file=clone / "no-accounts.json",
          state_dir=clone / "state", roster_path=clone / "roster.md",
          telegram_source=telegram_source.ControlSocket(clone / "state" / "telegram" / "control.sock"),
          telegram_root=tg_root, whatsapp_root=clone)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"
PAGES: list[str] = []


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
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode("utf-8", "replace")
    out = {k.lower(): v for k, v in r.getheaders()}
    out["set-cookie-all"] = r.headers.get_all("Set-Cookie") or []
    conn.close()
    PAGES.append(data)
    return r.status, out, data


def login():
    _, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
    return next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


i18n.set_current("es-MX")
cookie = login()
status, hdrs, page = req("GET", "/telegram?lang=es-MX", cookie=cookie)
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
check("GET /telegram sin bot: el formulario, 200 y no-store", (200, True, True),
      (status, 'action="/telegram/setup"' in page, "no-store" in (hdrs.get("cache-control") or "")))
check("el token va en type=password con autocomplete=off", True,
      bool(re.search(r'name="token" type="password" autocomplete="off"', page)))
check("el menú trae «Mensajes de Telegram» y el título es «Cuenta de Telegram»", (True, True),
      ('href="/telegram/messages"' in page, "Cuenta de Telegram" in page))


def post(**over):
    form = {"csrf": csrf, "token": TOKEN, "bot_username": "@NegocioBot", "confirm_dedicated": "1",
            "password": PASSWORD}
    form.update(over)
    form = {k: v for k, v in form.items() if v is not None}
    return req("POST", "/telegram/setup", form=form, cookie=cookie)


status, _, page = post(csrf="otro")
check("sin el CSRF bueno no se hace nada", (True, False), (status in (400, 403), tg_env.exists()))
status, _, page = post(password=None)
check("sin contraseña: 400 y nada escrito", (400, False), (status, tg_env.exists()))
status, _, page = post(password="no-es")
check("contraseña mala: 403 y nada escrito", (403, False), (status, tg_env.exists()))
status, _, page = post(token="123:corto")
check("token mal formado: 400, el aviso y nada escrito", (400, True, False),
      (status, "no parece un token" in page, tg_env.exists()))
status, _, page = post(token=OTHER)
check("token que Telegram rechaza: 400 y nada escrito", (400, True, False),
      (status, "no aceptó ese token" in page, tg_env.exists()))
status, _, page = post(bot_username="@OtroBot")
check("Q282: usuario de otro bot: 400, nada escrito y el usuario se queda en el campo", (400, True, False, True),
      (status, "no corresponde al bot" in page, tg_env.exists(), 'value="@OtroBot"' in page))
status, _, page = post(confirm_dedicated=None)
check("Q283: sin la casilla: 400 y nada escrito", (400, True, False),
      (status, "sólo de esta instalación" in page, tg_env.exists()))
check("ni un error arrancó el servicio ni mandó correo", (0, 0), (started["calls"], len(tg_mail())))

api.set_webhook("https://otra.invalid/hook")
status, hdrs, _ = post()
check("el caso bueno: 303 a /telegram?ok=setup_ok con el @usuario", (303, "/telegram?ok=setup_ok&bot=NegocioBot"),
      (status, hdrs.get("location")))
check("Q283: con la casilla, el webhook se borró", "", api.webhook_url or "")
check("telegram.env con el token, 0600 y configurado", (TOKEN, 0o600, True),
      (config.token(config.read(tg_env)), stat.S_IMODE(os.stat(tg_env).st_mode), telegram_source.configured(tg_root)))
check("arrancó el servicio una vez", 1, started["calls"])
check("el dueño recibió el aviso con @NegocioBot y sin el token", (1, True, False),
      (len(tg_mail()), "@NegocioBot" in tg_mail()[0][2] if tg_mail() else False,
       any(TOKEN in m[2] or TOKEN.split(":")[1] in m[2] for m in owner_mail)))
status, _, page = req("GET", "/telegram?ok=setup_ok&bot=NegocioBot", cookie=cookie)
check("después, /telegram es la cuenta con el aviso y sin formulario inicial", (200, True, False),
      (status, "quedó configurado con @NegocioBot" in page, 'action="/telegram/setup"' in page))
status, hdrs, _ = post()
check("con Telegram ya configurado, /telegram/setup no toca nada", (303, TOKEN),
      (status, config.token(config.read(tg_env))))

# Ya configurado pero desactivado: setup.initial se niega.
config.write(dict(config.read(tg_env), TELEGRAM_ENABLED="0"), tg_env)
status, _, page = post()
check("desactivado (ENABLED=0 con token): 409 y pide enable", (409, True),
      (status, "paynani telegram enable" in page))

# Sin el servicio instalado o si no arranca: queda guardado y la página lo dice.
for result, ok in (("not-installed", "setup_not_installed"), ("failed", "setup_failed")):
    tg_env.unlink()
    started["result"] = result
    status, hdrs, _ = post()
    check(f"servicio {result}: guardado y ok={ok}", (303, f"/telegram?ok={ok}&bot=NegocioBot", True),
          (status, hdrs.get("location"), tg_env.exists()))

check("el token nunca salió en una página", False,
      any(TOKEN in p or TOKEN.split(":")[1] in p for p in PAGES))
httpd.shutdown()
api.stop()
check("el .env y Himalaya de la instalación no cambiaron", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
