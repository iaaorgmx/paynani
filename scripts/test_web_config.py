#!/usr/bin/env python3
"""
Tests de «Configuración» de la cuenta principal en PaynaniWeb (#590 cambio 3): el botón
sólo en la lista de la cuenta principal, los datos actuales sin la contraseña, la
contraseña de la web con el bloqueo de la entrada antes de pedirle nada al núcleo (Q10),
sólo lo que cambió va al núcleo, la prueba contra el servidor se muestra, y el aviso al
dueño dice qué cambió sin la contraseña del buzón.

Un PaynaniWeb real en un puerto libre con `account_config.Fake`; nada sale de la máquina.
"""
from __future__ import annotations

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

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import account_config, app, auth, notify, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


PASSWORD = "una-contraseña-larga"
MAILBOX_SECRET = "s3cr3to-del-buzon"
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
(clone / "state").mkdir(parents=True)
(clone / "roster.md").write_text("| Name | Email |\n|---|---|\n| Julián Flores | julian@example.com |\n", encoding="utf-8")
accounts_file = clone / "accounts.json"
accounts_file.write_text(json.dumps({"accounts": [{
    "id": "ventas", "email": "ventas@example.com", "imap": {"host": "imap.example.com", "port": 993},
    "smtp": {"host": "smtp.example.com", "port": 465}, "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD"}]}),
    encoding="utf-8")
env_path = clone / ".env"
env_path.write_text(
    "AGENT_EMAIL_ACCOUNT=agente@example.com\n"
    f"AGENT_EMAIL_PASSWORD={MAILBOX_SECRET}\n"
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=imap.example.com\nAGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993\n"
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=smtp.example.com\nAGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465\n"
    "AGENT_EMAIL_FROM_NAME=Agente\n", encoding="utf-8")
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)
mail = []
updater = account_config.Fake()
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda to, s, b: mail.append((to, s, b)), log=lambda l: None),
                  agent_email="agente@example.com", accounts_file=accounts_file, state_dir=clone / "state",
                  roster_path=clone / "roster.md", env_path=env_path, updater=updater)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
HOST = "agente.ngrok.app"
IP = ["203.0.113.5"]


def req(method, path, *, form=None, cookie="", origin=True):
    h = {"Host": HOST, "X-Forwarded-For": IP[0]}
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
    return r.status, out, data


def login():
    _, hdrs, _ = req("POST", "/login", form={"email": "julian@example.com", "password": PASSWORD})
    return next(c for c in hdrs["set-cookie-all"] if c.startswith(auth.SESSION_COOKIE)).split(";", 1)[0]


th = i18n.th
cookie = login()
CURRENT = {"AGENT_EMAIL_ACCOUNT": "agente@example.com", "AGENT_EMAIL_FROM_NAME": "Agente",
           "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": "imap.example.com", "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT": "993",
           "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST": "smtp.example.com", "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT": "465"}
IMAP = "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"

status, _, page = req("GET", "/email/main?lang=es-MX", cookie=cookie)
check("«Configuración» en la lista de la cuenta principal", (200, True), (status, 'href="/email/main/configuracion"' in page))
status, _, page = req("GET", "/email/ventas?lang=es-MX", cookie=cookie)
check("y no en la de una cuenta adicional", False, 'href="/email/main/configuracion"' in page)
status, _, _ = req("GET", "/email/ventas/configuracion", cookie=cookie)
check("/email/ventas/configuracion no existe", 404, status)

status, hdrs, page = req("GET", "/email/main/configuracion?lang=es-MX", cookie=cookie)
check("la pantalla abre con los datos actuales", (200, True, True, True),
      (status, 'value="agente@example.com"' in page, 'value="imap.example.com"' in page, 'value="465"' in page))
check("la contraseña del buzón nunca se muestra", False, MAILBOX_SECRET in page)
check("sin atributos style", [], re.findall(r'\sstyle="', page))
check("no-store", True, "no-store" in hdrs.get("cache-control", ""))
csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
rev = re.search(r'name="rev" value="([^"]+)"', page).group(1)

# Q10: contraseña antes de pedirle nada al núcleo.
form = dict(CURRENT, csrf=csrf, rev=rev, **{IMAP: "mail.nuevo.mx"}, new_password="", password="")
status, _, page = req("POST", "/email/main/configuracion", form=form, cookie=cookie)
check("Q10: sin la contraseña de la web no llega al núcleo", (400, [], True),
      (status, updater.calls, th("web.cfg.err.password") in page))
check("y lo que escribió sigue en el formulario", True, 'value="mail.nuevo.mx"' in page)
status, _, _ = req("POST", "/email/main/configuracion", form=dict(form, password="mala"), cookie=cookie)
check("Q10: con la contraseña equivocada tampoco", (403, []), (status, updater.calls))
status, _, _ = req("POST", "/email/main/configuracion", form=dict(form, csrf="malo", password=PASSWORD), cookie=cookie)
check("sin CSRF, 403", (403, []), (status, updater.calls))
status, _, _ = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie, origin=False)
check("sin Origin, 403", (403, []), (status, updater.calls))

# Sólo lo que cambió va al núcleo; la contraseña del buzón sólo si se escribió.
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("con la contraseña, al núcleo va sólo lo que cambió", (200, {"AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": "mail.nuevo.mx"}),
      (status, updater.calls[-1][0]))
check("con quién lo pidió", "web:203.0.113.5", updater.calls[-1][1])
check("la página dice que se guardó y muestra la prueba", (True, True),
      (th("web.cfg.ok") in page, "IMAP login" in page))
ctx.notifier.wait()
check("Q10: el dueño recibe un aviso con lo que cambió", ("julian@example.com", i18n.t("web.cfg.mail_subject"), True),
      (mail[-1][0], mail[-1][1], i18n.t("web.cfg.imap_host") in mail[-1][2]))

req("POST", "/email/main/configuracion", form=dict(form, **{IMAP: "imap.example.com"}, new_password=MAILBOX_SECRET + "2",
                                                   password=PASSWORD), cookie=cookie)
check("una contraseña nueva del buzón va al núcleo", {"AGENT_EMAIL_PASSWORD": MAILBOX_SECRET + "2"}, updater.calls[-1][0])
ctx.notifier.wait()
check("y el aviso dice que cambió, sin ponerla", (True, False),
      (i18n.t("web.cfg.new_password") in mail[-1][2], MAILBOX_SECRET in mail[-1][2]))

before = len(updater.calls)
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, **{IMAP: "imap.example.com"},
                                                                    password=PASSWORD), cookie=cookie)
check("sin cambios no se llama al núcleo y lo dice", (200, before, True),
      (status, len(updater.calls), th("web.cfg.nothing") in page))

status, _, page = req("POST", "/email/main/configuracion", form=dict(form, AGENT_EMAIL_FROM_NAME="Agente\r\nX=1", password=PASSWORD),
                      cookie=cookie)
check("un salto de línea en un campo no pasa (no agrega claves al .env)", (400, before), (status, len(updater.calls)))

# El núcleo dice que no.
updater.result = {"ok": False, "code": "probe_failed",
                  "probe": [{"protocol": "imap", "ok": False, "text": "IMAP login", "detail": "authentication failed"}]}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("si la prueba falla no se guarda y muestra el paso que falló", (400, True, True),
      (status, th("web.cfg.err.probe_failed") in page, "authentication failed" in page))
updater.result = {"ok": False, "code": "not_ready", "rollback": "ok"}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("si el listener no volvió, dice que se restauró lo anterior", (502, True), (status, th("web.cfg.err.rolled_back") in page))
updater.result = {"ok": False, "code": "restart_failed", "rollback": "failed"}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("si tampoco pudo volver a lo anterior, lo dice", (502, True), (status, th("web.cfg.err.rollback_failed") in page))
updater.result = {"ok": False, "code": "busy"}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("si hay otro cambio en curso (busy): 409 y lo dice", (409, True), (status, th("web.cfg.err.busy") in page))
updater.result = {"ok": False, "code": "invalid", "field_errors": {IMAP: "not a host name"}}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("los errores por campo del núcleo se muestran con su etiqueta", (400, True, True),
      (status, "not a host name" in page, i18n.t("web.cfg.imap_host") in page))
updater.result = {"ok": True, "code": "updated", "ready": "waiting"}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("guardado pero el listener todavía no confirma: lo dice", (200, True), (status, th("web.cfg.ok_waiting") in page))
updater.result = {"ok": True, "code": "updated", "ready": "connected", "recovered": True}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("si N2 deshizo antes un cambio a medias, lo dice junto con el resultado", (200, True, True),
      (status, th("web.cfg.recovered") in page, th("web.cfg.ok") in page))
updater.result = {"ok": True, "code": "unchanged"}
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("unchanged del núcleo: dice que no cambió nada", (200, True), (status, th("web.cfg.nothing") in page))
updater.result = None

# Una página abierta antes de otro cambio no manda valores viejos (revisión de #597).
env_before = env_path.read_text(encoding="utf-8")
env_path.write_text(env_before.replace("imap.example.com", "imap.otro.mx"), encoding="utf-8")
before = len(updater.calls)
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, **{IMAP: "imap.example.com"},
                                                                    AGENT_EMAIL_FROM_NAME="Otro nombre",
                                                                    password=PASSWORD), cookie=cookie)
check("página obsoleta: 409, no llega nada al núcleo y muestra lo actual", (409, before, True, True),
      (status, len(updater.calls), th("web.cfg.err.stale") in page, 'value="imap.otro.mx"' in page))
new_rev = re.search(r'name="rev" value="([^"]+)"', page).group(1)
status, _, _ = req("POST", "/email/main/configuracion", form=dict(form, rev=new_rev, **{IMAP: "imap.otro.mx"},
                                                                 AGENT_EMAIL_FROM_NAME="Otro nombre",
                                                                 password=PASSWORD), cookie=cookie)
check("con la página recargada, sólo va el nombre (no el host viejo)", (200, {"AGENT_EMAIL_FROM_NAME": "Otro nombre"}),
      (status, updater.calls[-1][0]))
env_path.write_text(env_before, encoding="utf-8")

# Una excepción ordinaria del núcleo: resultado desconocido, sin invitar a reintentar.
real_update = updater.update
updater.update = lambda changes, *, by: (_ for _ in ()).throw(RuntimeError("boom"))
status, _, page = req("POST", "/email/main/configuracion", form=dict(form, password=PASSWORD), cookie=cookie)
check("si el núcleo termina con una excepción, la página dice que no se sabe y no invita a reintentar", (502, True),
      (status, th("web.cfg.err.unknown_outcome").split(".")[0] in page))
updater.update = real_update

# N2 ya está en main. Esta prueba NUNCA llama al main_account real: escribiría el .env
# y la cuenta de Himalaya de la instalación donde corre. Sólo compara su firma.
import dataclasses  # noqa: E402
import inspect  # noqa: E402
from paynani_lib import main_account as real_n2  # noqa: E402
check("main_account real: update(changes, *, by, ...) y el Result con lo que lee CoreUpdater",
      (["changes", "by"], True),
      ([n for n in inspect.signature(real_n2.update).parameters][:2],
       {"ok", "code", "changed", "field_errors", "probe", "ready", "rollback", "recovered", "detail"}
       <= {f.name for f in dataclasses.fields(real_n2.Result)}))
check("el .env no lo tocó la web", True, f"AGENT_EMAIL_PASSWORD={MAILBOX_SECRET}\n" in env_path.read_text(encoding="utf-8")
      and "mail.nuevo.mx" not in env_path.read_text(encoding="utf-8"))

# El adaptador real con un main_account de prueba que tiene la interfaz final de N2 (#591).
import types  # noqa: E402

seen = []


class _R:
    def __init__(self, **kw):
        self.__dict__.update(kw)


fake_core = types.ModuleType("paynani_lib.main_account")
fake_core.update = lambda changes, *, by: seen.append((changes, by)) or _R(
    ok=True, code="updated", changed=list(changes), field_errors={}, ready="connected", rollback="none", detail="",
    probe=[{"protocol": "imap", "ok": True, "text": "login", "detail": ""}], restart=None)
sys.modules["paynani_lib.main_account"] = fake_core
import paynani_lib  # noqa: E402
paynani_lib.main_account = fake_core
res = account_config.CoreUpdater().update({IMAP: "mail.nuevo.mx"}, by="web:1.2.3.4")
check("CoreUpdater: llama a main_account.update con los cambios y quién, y devuelve el Result como dict",
      ([({IMAP: "mail.nuevo.mx"}, "web:1.2.3.4")], "updated", [IMAP], "connected", "none"),
      (seen, res["code"], res["changed"], res["ready"], res["rollback"]))
del sys.modules["paynani_lib.main_account"]
del paynani_lib.main_account
check("los campos son los del núcleo (envfile.ENV_FIELDS), sin otra lista", True,
      set(account_config.SHOWN) | {"AGENT_EMAIL_PASSWORD"} == set(__import__("paynani_lib.envfile", fromlist=["x"]).ENV_FIELDS))

# El bloqueo de la entrada.
IP[0] = "198.51.100.60"
cookie2 = login()
page2 = req("GET", "/email/main/configuracion", cookie=cookie2)[2]
csrf2 = re.search(r'name="csrf" value="([^"]+)"', page2).group(1)
for _ in range(7):
    req("POST", "/email/main/configuracion", form=dict(form, csrf=csrf2, rev=re.search(r'name="rev" value="([^"]+)"', page2).group(1), password="mala"), cookie=cookie2)
before = len(updater.calls)
status, _, _ = req("POST", "/email/main/configuracion", form=dict(form, csrf=csrf2, rev=re.search(r'name="rev" value="([^"]+)"', page2).group(1), password=PASSWORD), cookie=cookie2)
check("tras varios fallos, ni la buena guarda (bloqueo de la entrada)", (403, before), (status, len(updater.calls)))
IP[0] = "203.0.113.5"

keys = [k for k in i18n.CATALOGUES["es-MX"] if k.startswith("web.cfg.")]
missing = {lang: [k for k in keys if k not in i18n.CATALOGUES[lang]] for lang in ("en-US", "es-ES", "fr-FR", "pt-BR")}
check("las cadenas web.cfg.* en los cinco idiomas", {lang: [] for lang in missing}, missing)

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
