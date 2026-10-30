#!/usr/bin/env python3
"""
Tests de «Nuevo correo» en PaynaniWeb (#590 cambio 2): el botón en la lista de cada
cuenta, el formulario con Para, CC y CCO (Q6=B) y el roster de esa cuenta como libreta,
la cuenta de origen (Q7=A), la contraseña sólo cuando alguien está fuera del roster
(Q5), con el bloqueo de la entrada, CSRF y Origin, y que nada de esto le abre al
agente un camino fuera del roster: `send.sh` sigue rechazando y la API no manda correo.

Un PaynaniWeb real en un puerto libre con `mail_compose.Fake`; nada sale de la máquina.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib import i18n  # noqa: E402
from paynani_lib.web import api_actions, app, auth, mail_compose, notify, users  # noqa: E402

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
tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
(clone / "state").mkdir(parents=True)
(clone / "rosters").mkdir()
roster = clone / "roster.md"
roster.write_text("| Name | Email |\n|---|---|\n| Julián Flores | julian@example.com |\n| Ana López | ana@example.com |\n",
                  encoding="utf-8")
(clone / "rosters" / "ventas.md").write_text("| Name | Email |\n|---|---|\n| Cliente Uno | cliente@example.org |\n",
                                             encoding="utf-8")
accounts_file = clone / "accounts.json"
accounts_file.write_text(json.dumps({"accounts": [{
    "id": "ventas", "email": "ventas@example.com", "from_name": "Ventas", "enabled": True,
    "imap": {"host": "imap.example.com", "port": 993}, "smtp": {"host": "smtp.example.com", "port": 465},
    "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD", "roster": "rosters/ventas.md"}]}), encoding="utf-8")
env_path = clone / ".env"
env_path.write_text("AGENT_EMAIL_ACCOUNT=agente@example.com\nPAYNANI_FROM_NAME=Agente\n", encoding="utf-8")
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", PASSWORD, user_file)

mailer = mail_compose.Fake(book={"main": ["julian@example.com", "ana@example.com"],
                                 "ventas": ["cliente@example.org"]})
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=accounts_file, state_dir=clone / "state",
                  roster_path=roster, env_path=env_path, mailer=mailer)
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


def csrf_of(page):
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


th = i18n.th
cookie = login()

# ---- El botón y el formulario ----------------------------------------------------------
for account_id in ("main", "ventas"):
    status, _, page = req("GET", f"/email/{account_id}?lang=es-MX", cookie=cookie)
    check(f"/email/{account_id}: «Nuevo correo» en la lista, como Catch-All en Mensajes", (200, True),
          (status, f'href="/email/{account_id}/nuevo"' in page))
status, hdrs, page = req("GET", "/email/main/nuevo?lang=es-MX", cookie=cookie)
check("el formulario abre", (200, True), (status, th("web.compose.title") in page))
check("Q6=B: Para, CC y CCO, asunto y mensaje", [True] * 5,
      [f'name="{n}"' in page for n in ("to", "cc", "bcc", "subject", "text")])
check("Q7=A: dice desde qué cuenta sale", True, "agente@example.com" in page)
check("la libreta es el roster de esa cuenta", (True, True, False),
      ("ana@example.com" in page, "Ana López" in page, "cliente@example.org" in page))
check("y carga compose.js; sin atributos style", (True, []),
      ('src="/assets/compose.js"' in page, re.findall(r'\sstyle="', page)))
status, _, page = req("GET", "/email/ventas/nuevo?lang=es-MX", cookie=cookie)
check("en una cuenta adicional, su dirección y su roster", (True, True, False),
      ("ventas@example.com" in page, "cliente@example.org" in page, "ana@example.com" in page))
status, _, _ = req("GET", "/email/no-existe/nuevo", cookie=cookie)
check("una cuenta que no existe: 404", 404, status)
status, _, _ = req("GET", "/email/main/nuevo")
check("sin sesión, a la entrada", 303, status)
status, _, js = req("GET", "/assets/compose.js")
check("compose.js se sirve", (200, True), (status, "data-libreta" in js))
csrf = csrf_of(req("GET", "/email/main/nuevo", cookie=cookie)[2])

# ---- Dentro del roster: sin contraseña ---------------------------------------------------
status, hdrs, _ = req("POST", "/email/main/enviar", form={
    "csrf": csrf, "to": "Ana@Example.com", "cc": "", "bcc": "", "subject": "Hola", "text": "¿Cómo vas?"}, cookie=cookie)
check("al roster no pide contraseña y vuelve a la lista con el aviso", (303, "/email/main?enviado=1&fuera=0"),
      (status, hdrs.get("location")))
check("se pidió al núcleo con la cuenta, las direcciones normalizadas, quién y el correo del dueño",
      ("main", ["ana@example.com"], "¿Cómo vas?", "web:203.0.113.5", "julian@example.com"),
      (mailer.sent[-1]["account_id"], mailer.sent[-1]["to"], mailer.sent[-1]["body"], mailer.sent[-1]["by"],
       mailer.sent[-1]["owner_email"]))
check("cada envío usa su propio permiso de un solo uso, y se consume", {}, mailer.grants)
check("Q5: sin nadie fuera, el permiso no autoriza fuera del roster", False, mailer.sent[-1]["allow_outside"])
status, _, page = req("GET", "/email/main?enviado=1&fuera=0&lang=es-MX", cookie=cookie)
check("la lista dice que se envió", True, th("web.compose.sent_ok") in page)

# ---- Fuera del roster: la contraseña (Q5) -------------------------------------------------
before = len(mailer.sent)
form = {"csrf": csrf, "to": "ana@example.com", "cc": "externo@otro.mx", "bcc": "oculto@otro.mx",
        "subject": "Propuesta", "text": "Te mando la propuesta."}
status, _, page = req("POST", "/email/main/enviar", form=form, cookie=cookie)
check("Q5: con alguien fuera del roster y sin contraseña, no sale y dice quiénes", (400, before, True, True),
      (status, len(mailer.sent), "externo@otro.mx" in page and "oculto@otro.mx" in page,
       th("web.compose.err.password", list="externo@otro.mx, oculto@otro.mx").split(" (")[0] in page))
check("y lo que escribió sigue en el formulario", True, "Te mando la propuesta." in page and "Propuesta" in page)
status, _, page = req("POST", "/email/main/enviar", form=dict(form, password="mala"), cookie=cookie)
check("Q5: con la contraseña equivocada tampoco", (403, before), (status, len(mailer.sent)))
status, hdrs, _ = req("POST", "/email/main/enviar", form=dict(form, password=PASSWORD), cookie=cookie)
check("Q5: con la contraseña sale; el aviso dice cuántos estaban fuera, sin las direcciones",
      (303, "/email/main?enviado=1&fuera=2"), (status, hdrs.get("location")))
check("Q5: con la contraseña revisada, el permiso sí autoriza fuera del roster", True, mailer.sent[-1]["allow_outside"])
check("Q6=B: Para, CC y CCO llegan separados al núcleo", (["ana@example.com"], ["externo@otro.mx"], ["oculto@otro.mx"]),
      (mailer.sent[-1]["to"], mailer.sent[-1]["cc"], mailer.sent[-1]["bcc"]))
status, _, page = req("GET", "/email/main?enviado=1&fuera=2&lang=es-MX", cookie=cookie)
check("la lista dice cuántos estaban fuera del roster", True, th("web.compose.sent_outside", n=2) in page)

# El roster es el de esa cuenta: Ana está en el de main, no en el de ventas.
csrf_v = csrf_of(req("GET", "/email/ventas/nuevo", cookie=cookie)[2])
status, _, page = req("POST", "/email/ventas/enviar", form={
    "csrf": csrf_v, "to": "ana@example.com", "subject": "Hola", "text": "Desde ventas"}, cookie=cookie)
check("Q7=A: desde ventas, Ana está fuera del roster de ventas y pide contraseña", (400, True),
      (status, "ana@example.com" in page))
status, hdrs, _ = req("POST", "/email/ventas/enviar", form={
    "csrf": csrf_v, "to": "cliente@example.org", "subject": "Hola", "text": "Desde ventas"}, cookie=cookie)
check("y al roster de ventas sale sin contraseña, desde ventas", (303, "ventas"),
      (status, mailer.sent[-1]["account_id"]))
check("la regla de «fuera del roster» la da el núcleo (outside_roster), con la cuenta", ("ventas", ["cliente@example.org"]),
      mailer.asked[-2] if mailer.asked[-1][0] == "ventas" else mailer.asked[-1])

# ---- Validación antes de pedir nada ---------------------------------------------------------
cases = [
    ({"to": "", "subject": "x", "text": "y"}, "err.no_recipients"),
    ({"to": "no-es-correo", "subject": "x", "text": "y"}, "err.invalid_address"),
    ({"to": "a@b.mx\r\nBcc: espia@malo.com", "subject": "x", "text": "y"}, "err.invalid_address"),
    ({"to": "ana@example.com", "subject": "", "text": "y"}, "err.subject"),
    ({"to": "ana@example.com", "subject": "Hola\r\nBcc: espia@malo.com", "text": "y"}, "err.subject"),
    ({"to": "ana@example.com", "subject": "x", "text": "   "}, "err.text"),
    ({"to": ", ".join(f"p{i}@example.com" for i in range(51)), "subject": "x", "text": "y"}, "err.too_many"),
]
for fields, key in cases:
    before = len(mailer.sent)
    status, _, page = req("POST", "/email/main/enviar", form=dict({"csrf": csrf, "cc": "", "bcc": ""}, **fields),
                          cookie=cookie)
    detail = "50" if key == "err.too_many" else ""
    expected_text = i18n.th("web.compose." + key, detail=detail, list="", code="").split(":")[0]
    check(f"{key}: no sale y lo dice", (400, before, True), (status, len(mailer.sent), expected_text in page))
check("un salto de línea no cuela un encabezado: nada llegó con «espia»", False,
      any("espia@malo.com" in json.dumps(m) for m in mailer.sent))

# ---- CSRF, Origin y el bloqueo de la entrada ---------------------------------------------------
before = len(mailer.sent)
status, _, _ = req("POST", "/email/main/enviar", form={"csrf": "malo", "to": "ana@example.com", "subject": "x",
                                                       "text": "y"}, cookie=cookie)
check("sin el token CSRF, 403", (403, before), (status, len(mailer.sent)))
status, _, _ = req("POST", "/email/main/enviar", form={"csrf": csrf, "to": "ana@example.com", "subject": "x",
                                                       "text": "y"}, cookie=cookie, origin=False)
check("sin Origin, 403", (403, before), (status, len(mailer.sent)))
IP[0] = "198.51.100.40"
cookie2 = login()
csrf2 = csrf_of(req("GET", "/email/main/nuevo", cookie=cookie2)[2])
for _ in range(7):
    req("POST", "/email/main/enviar", form=dict(form, csrf=csrf2, password="mala"), cookie=cookie2)
status, _, _ = req("POST", "/email/main/enviar", form=dict(form, csrf=csrf2, password=PASSWORD), cookie=cookie2)
check("tras varios fallos, ni la buena contraseña manda fuera del roster (bloqueo de la entrada)",
      (403, before), (status, len(mailer.sent)))
IP[0] = "203.0.113.5"

# ---- Q5 sellada en el permiso: el roster cambia entre la consulta y el envío (revisión de #594) ----
mailer.after_authorize = lambda: mailer.book["main"].remove("ana@example.com")
before = len(mailer.sent)
status, _, page = req("POST", "/email/main/enviar", form={"csrf": csrf, "to": "ana@example.com", "subject": "x",
                                                          "text": "y"}, cookie=cookie)
check("Q5: si alguien queda fuera del roster después de consultar, no sale sin contraseña", (400, before, True),
      (status, len(mailer.sent), th("web.compose.err.not_authorized").split(".")[0] in page))
check("y no se reintenta: sólo hubo un permiso y se consumió", {}, mailer.grants)
mailer.after_authorize = None
mailer.book["main"].append("ana@example.com")

# ---- Estados independientes después de mandar (revisión de #594) ----------------------------------
mailer.sent_copy, mailer.notice = "failed", "failed"
status, hdrs, _ = req("POST", "/email/main/enviar", form=dict(form, password=PASSWORD), cookie=cookie)
check("fuera del roster, sin copia y sin aviso: la URL lleva los tres estados y ninguna dirección",
      (303, "/email/main?enviado=1&fuera=2&copia=failed&aviso=failed", False),
      (status, hdrs.get("location"), "@" in (hdrs.get("location") or "")))
status, _, page = req("GET", hdrs.get("location") + "&lang=es-MX", cookie=cookie)
check("la lista dice las tres cosas a la vez", (True, True, True),
      (th("web.compose.sent_outside", n=2) in page, th("web.compose.sent_no_copy") in page,
       th("web.compose.notice_failed") in page))
mailer.sent_copy, mailer.notice = "saved", "failed"
status, hdrs, _ = req("POST", "/email/main/enviar", form=dict(form, password=PASSWORD), cookie=cookie)
check("fuera del roster y sin aviso, con copia", "/email/main?enviado=1&fuera=2&aviso=failed", hdrs.get("location"))
mailer.sent_copy, mailer.notice = "saved", None

# Una excepción inesperada del núcleo después de mandar: no se invita a reenviar.
real_send = mailer.send
mailer.send = lambda grant, subject, body: (_ for _ in ()).throw(OSError("unlink failed"))
status, _, page = req("POST", "/email/main/enviar", form={"csrf": csrf, "to": "ana@example.com", "subject": "x",
                                                          "text": "y"}, cookie=cookie)
check("si el núcleo falla sin Result, la página dice que no se sabe si salió (no invita a reenviar)", (502, True),
      (status, th("web.compose.err.unknown_outcome").split(".")[0] in page))
mailer.send = real_send

# ---- El núcleo dice que no -----------------------------------------------------------------------
mailer.fail = "send_failed"
status, _, page = req("POST", "/email/main/enviar", form={"csrf": csrf, "to": "ana@example.com", "subject": "x",
                                                          "text": "y"}, cookie=cookie)
check("si el núcleo no pudo mandar, la página lo dice y conserva el texto", (502, True, True),
      (status, "smtp said no" in page, 'value="x"' in page))
mailer.fail = ""

# N1 ya está en main: la firma real de owner_mail es la que llama CoreMailer.
import inspect  # noqa: E402
from paynani_lib import owner_mail as real_core  # noqa: E402
check("owner_mail real: authorize(account, to, cc, bcc, *, by, owner_email, allow_outside) y send(grant, subject, body)",
      (["account", "to", "cc", "bcc", "by", "owner_email", "allow_outside"], ["grant", "subject", "body"]),
      ([n for n in inspect.signature(real_core.authorize).parameters][:7],
       [n for n in inspect.signature(real_core.send).parameters][:3]))
check("owner_mail real: outside_roster(account, addresses) y las excepciones que traduce CoreMailer", (
      ["account", "addresses"], True, True),
      ([n for n in inspect.signature(real_core.outside_roster).parameters],
       issubclass(real_core.InvalidAddress, Exception), issubclass(real_core.UnknownAccount, Exception)))

# El adaptador real con un owner_mail de prueba que tiene la interfaz final de N1 (#591).
import types  # noqa: E402

calls = []


class _Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


fake_core = types.ModuleType("paynani_lib.owner_mail")
fake_core.InvalidAddress = type("InvalidAddress", (ValueError,), {})
fake_core.UnknownAccount = type("UnknownAccount", (LookupError,), {})


def _outside(account, addresses):
    calls.append(("outside_roster", account, list(addresses)))
    if "bad@" in " ".join(addresses):
        raise fake_core.InvalidAddress("bad@")
    return [a for a in addresses if a != "ana@example.com"]


fake_core.outside_roster = _outside
fake_core.authorize = lambda account, to, cc, bcc, *, by, owner_email, allow_outside: calls.append(
    ("authorize", account, to, cc, bcc, by, owner_email, allow_outside)) or "GRANT"
fake_core.send = lambda grant, subject, body: calls.append(("send", grant, subject, body)) or _Result(
    ok=True, code="sent", message_id="<m@x>", sent_copy="saved", outside_roster=["x@y.mx"], notice="sent", detail="")
sys.modules["paynani_lib.owner_mail"] = fake_core
import paynani_lib  # noqa: E402
paynani_lib.owner_mail = fake_core
real = mail_compose.CoreMailer()
check("CoreMailer: main va como None a N1, una cuenta adicional con su id",
      (["x@y.mx"], ("outside_roster", None, ["ana@example.com", "x@y.mx"])),
      (real.outside_roster("main", ["ana@example.com", "x@y.mx"]), calls[-1]))
grant = real.authorize("ventas", ["a@b.mx"], [], ["c@d.mx"], by="web:1.2.3.4", owner_email="julian@example.com",
                       allow_outside=True)
res = real.send(grant, "Asunto", "Texto")
check("CoreMailer: authorize con by, owner_email y allow_outside, luego send con el permiso, sin contraseñas",
      [("authorize", "ventas", ["a@b.mx"], [], ["c@d.mx"], "web:1.2.3.4", "julian@example.com", True),
       ("send", "GRANT", "Asunto", "Texto")], calls[-2:])
check("CoreMailer: el Result de N1 como dict", ("sent", "<m@x>", "saved", "sent"),
      (res["code"], res["message_id"], res["sent_copy"], res["notice"]))
try:
    real.outside_roster("main", ["bad@"])
    check("CoreMailer: InvalidAddress de N1 → Refused(invalid_address)", "invalid_address", "none")
except mail_compose.Refused as exc:
    check("CoreMailer: InvalidAddress de N1 → Refused(invalid_address)", "invalid_address", exc.code)
del sys.modules["paynani_lib.owner_mail"]
del paynani_lib.owner_mail

# Un permiso que ya se usó: not_authorized, sin reintentar.
used = mailer.authorize("main", ["ana@example.com"], [], [], by="t", owner_email="j@x.mx", allow_outside=False)
mailer.send(used, "a", "b")
again = mailer.send(used, "a", "b")
check("un permiso de un solo uso no sirve dos veces", (False, "invalid_grant"), (again["ok"], again["code"]))

# ---- Ningún camino nuevo para el agente ----------------------------------------------------------
check("la API no tiene una acción para mandar correo", [], [a for a in dir(api_actions)
                                                            if "mail" in a.lower() and "send" in a.lower()])
send = subprocess.run(["bash", str(ROOT / "scripts" / "send.sh"), "--dry-run", "externo@otro.mx", "Hola", str(env_path)],
                      capture_output=True, text=True, env=dict(os.environ, ROSTER=str(roster), ENV_FILE=str(env_path)))
check("send.sh sigue rechazando con exit 2 una dirección fuera del roster", 2, send.returncode)

# ---- Cinco idiomas --------------------------------------------------------------------------------
keys = [k for k in i18n.CATALOGUES["es-MX"] if k.startswith("web.compose.")]
missing = {lang: [k for k in keys if k not in i18n.CATALOGUES[lang]] for lang in ("en-US", "es-ES", "fr-FR", "pt-BR")}
check("las cadenas web.compose.* en los cinco idiomas", {lang: [] for lang in missing}, missing)
status, _, page = req("GET", "/email/main?lang=en-US", cookie=cookie)
check("en-US: «New Email»", True, ">New Email<" in page)

httpd.shutdown()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
