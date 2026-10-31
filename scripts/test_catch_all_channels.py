#!/usr/bin/env python3
"""
Tests del Catch-All por canal (PRD #576, tarea 1): un archivo por canal (FR-1, FR-2),
nombres reservados (FR-3), la migración desde rules/catch-all.md (FR-4, FR-5), el
correo con el canal (FR-14), `channel` y un permiso por canal en la API (FR-12 a
FR-13a), y la redacción por canal de los avisos (FR-7). Un script de asserts, como el
resto de la suite. Nada sale de la máquina.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import event as ev  # noqa: E402
from paynani_lib import roster_edit  # noqa: E402
from paynani_lib import rules as rules_mod  # noqa: E402
from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.web import api_actions, api_tokens  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


ROSTER = """| Name | Email | Type | GitHub | Phone | Rules |
|---|---|---|---|---|---|
| Julián Flores | julian@example.com | Human | julianflores | +1XXXXXXXXXX |  |
"""
ON = "---\nversion: 1\nenabled: true\n---\nAvisa al dueño por Telegram.\n"
OFF = "---\nversion: 1\nenabled: false\n---\nAvisa al dueño por Telegram.\n"
WA = "---\nversion: 1\nenabled: true\n---\nSólo WhatsApp: guarda el número.\n"


def install():
    root = Path(tempfile.mkdtemp())
    (root / "roster.md").write_text(ROSTER, encoding="utf-8")
    (root / "state").mkdir()
    (root / "rules").mkdir(mode=0o700)
    return root


def put(root, name, text):
    (root / "rules" / f"{name}.md").write_text(text, encoding="utf-8")


# --- lectura por canal (FR-1, FR-2, FR-4, FR-6) ---------------------------------------
root = install()
check("sin archivos: ningún canal tiene Catch-All", (None, None),
      (rules_mod.catch_all_notice("sms", root), rules_mod.catch_all_notice("whatsapp", root)))
put(root, "catch-all-sms", ON)
check("FR-2: sólo el de SMS activo; WhatsApp no", ({"file": "rules/catch-all-sms.md", "status": "active"}, None),
      (rules_mod.catch_all_notice("sms", root), rules_mod.catch_all_notice("whatsapp", root)))
put(root, "catch-all-whatsapp", WA)
check("FR-1: cada canal lee sus instrucciones", (True, True),
      ("Telegram" in rules_mod.catch_all_instructions("sms", root),
       "guarda el número" in rules_mod.catch_all_instructions("whatsapp", root)))
put(root, "catch-all-sms", "---\nroto\n")
check("FR-2: un archivo roto de SMS no toca WhatsApp", ("invalid", "active"),
      (rules_mod.catch_all_notice("sms", root)["status"], rules_mod.catch_all_notice("whatsapp", root)["status"]))
check("FR-6: la etiqueta nombra el archivo del canal", "catch-all: rules/catch-all-whatsapp.md",
      rules_mod.catch_all_tag(rules_mod.catch_all_notice("whatsapp", root)))
check("#609 FR-17: Telegram sin su archivo no tiene Catch-All", None, rules_mod.catch_all_notice("telegram", root))
put(root, "catch-all-telegram", ON)
check("#609 FR-17: Telegram lee rules/catch-all-telegram.md", {"file": "rules/catch-all-telegram.md", "status": "active"},
      rules_mod.catch_all_notice("telegram", root))
try:
    rules_mod.catch_all_notice("fax", root)
    check("un canal que paynani no tiene es un error", "ValueError", None)
except ValueError:
    check("un canal que paynani no tiene es un error", True)

root = install()
put(root, "catch-all", ON)
check("FR-4: sin archivos por canal, los dos usan rules/catch-all.md",
      ({"file": "rules/catch-all.md", "status": "active"},) * 2,
      (rules_mod.catch_all_notice("sms", root), rules_mod.catch_all_notice("whatsapp", root)))
put(root, "catch-all-whatsapp", OFF)
check("FR-4: el archivo del canal manda sobre el viejo", ("active", None),
      (rules_mod.catch_all_notice("sms", root)["status"], rules_mod.catch_all_notice("whatsapp", root)))
check("catch_all_source: el del canal o el viejo", ("catch-all", "catch-all-whatsapp"),
      (rules_mod.catch_all_source("sms", root), rules_mod.catch_all_source("whatsapp", root)))
check("#609 FR-17: el viejo rules/catch-all.md no abre Telegram", (None, None, "catch-all-telegram"),
      (rules_mod.catch_all_notice("telegram", root), rules_mod.catch_all_instructions("telegram", root),
       rules_mod.catch_all_source("telegram", root)))

# --- nombres reservados (FR-3) ----------------------------------------------------------
check("FR-3: los cuatro nombres del Catch-All están reservados", True,
      all(n in rules_mod.RESERVED_IDS for n in ("catch-all", "catch-all-sms", "catch-all-whatsapp",
                                                "catch-all-telegram")))


# --- RosterService: channel y migración (FR-5, FR-12, FR-14) ------------------------------
def service_for(root):
    mail = []
    svc = roster_api.RosterService(root / "roster.md", root / "state", rules_root=root,
                                   notifier=lambda to, s, b: mail.append((to, s, b)), log=lambda line: None)
    counter = [0]

    def call(kind, device="web:203.0.113.9", **fields):
        counter[0] += 1
        res = svc.handle({"type": kind, "id": "q_" + f"{counter[0]:032x}", **fields}, device)
        for t in svc.notify_threads:
            t.join(5)
        return res
    return svc, call, mail


def text_of(root, name):
    path = root / "rules" / f"{name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


root = install()
svc, call, mail = service_for(root)
res = call("catchall.get", channel="fax")
check("un canal desconocido: invalid en channel", ("error", "invalid", "channel"),
      (res["type"], res.get("code"), res.get("field")))
res = call("catchall.get", channel="telegram")
check("#609: catchall.get acepta telegram", ("telegram", "rules/catch-all-telegram.md", False, ["sms", "whatsapp", "telegram"]),
      (res["data"]["channel"], res["data"]["file"], res["data"]["exists"], res["data"]["channels"]))
res = call("catchall.get")
check("FR-12: sin channel es SMS", ("sms", "rules/catch-all-sms.md"), (res["data"]["channel"], res["data"]["file"]))
res = call("catchall.save", channel="whatsapp", enabled=True, text="Guarda el número.\n", etag="")
check("sin archivo viejo: guardar WhatsApp no crea el de SMS", ("result", True, False),
      (res["type"], (root / "rules" / "catch-all-whatsapp.md").exists(), (root / "rules" / "catch-all-sms.md").exists()))
check("los canales nuevos empiezan apagados", (True, None),
      (rules_mod.catch_all_active("whatsapp", root), rules_mod.catch_all_notice("sms", root)))
check("FR-14: el correo dice el canal y no lleva las instrucciones", (1, True, False),
      (len(mail), "Catch-All de WhatsApp" in mail[0][1] and "Catch-All de WhatsApp" in mail[0][2],
       "Guarda el número" in mail[0][2]))

# Migración normal: el viejo activo, se apaga SMS; WhatsApp queda como estaba.
root = install()
put(root, "catch-all", ON)
svc, call, mail = service_for(root)
got = call("catchall.get", channel="sms")["data"]
check("FR-4: la pantalla muestra el viejo mientras el canal no tenga el suyo", ("rules/catch-all.md", True, "active"),
      (got["file"], got["enabled"], got["status"]))
res = call("catchall.save", channel="sms", enabled=False, text=got["text"], etag=got["etag"])
check("FR-5: el guardado sale bien", ("result", "rules/catch-all-sms.md", False),
      (res["type"], res["data"]["file"], res["data"]["enabled"]))
check("FR-5: WhatsApp quedó con el texto del viejo, tal cual; el viejo ya no está", (ON, False),
      (text_of(root, "catch-all-whatsapp"), (root / "rules" / "catch-all.md").exists()))
check("FR-5: apagar SMS no cambió WhatsApp", (None, "active"),
      (rules_mod.catch_all_notice("sms", root), rules_mod.catch_all_notice("whatsapp", root)["status"]))
history = sorted(p.name for p in (root / "state" / "history").iterdir())
check("FR-5: la copia del viejo quedó en state/history/", True,
      any(n.startswith("rules__catch-all.") and roster_edit.read_bytes(root / "state" / "history" / n) == ON.encode()
          for n in history))
check("FR-5: el archivo nuevo es 600", 0o600, (root / "rules" / "catch-all-whatsapp.md").stat().st_mode & 0o777)
changes = [json.loads(line) for line in (root / "state" / roster_api.CHANGES_LOG).read_text().splitlines()]
change = next(c for c in changes if c.get("action") == "catch_all")
check("el log dice el canal y la migración", ("sms", ["rules/catch-all-whatsapp.md"], True),
      (change["rules"]["channel"], change["rules"]["migrated"], change["rules"]["legacy_removed"]))
check("FR-14: el correo dice que hubo migración y qué canal cambió", (True, True, True),
      ("Catch-All de SMS" in mail[0][1], "rules/catch-all.md se separó" in mail[0][2],
       "rules/catch-all-whatsapp.md" in mail[0][2]))

check("#609 FR-17: la migración no crea rules/catch-all-telegram.md", False,
      (root / "rules" / "catch-all-telegram.md").exists())

# Telegram con el viejo presente: guarda sólo el suyo y no migra nada.
root = install()
put(root, "catch-all", ON)
svc, call, mail = service_for(root)
got = call("catchall.get", channel="telegram")["data"]
check("#609: Telegram no muestra el viejo", ("rules/catch-all-telegram.md", False, "off"),
      (got["file"], got["enabled"], got["status"]))
res = call("catchall.save", channel="telegram", enabled=True, text="Contesta sólo con el horario.\n", etag=got["etag"])
check("#609: guardar Telegram escribe sólo el suyo; el viejo y los demás siguen igual",
      ("result", "active", ON, None, None),
      (res["type"], rules_mod.catch_all_notice("telegram", root)["status"], text_of(root, "catch-all"),
       text_of(root, "catch-all-sms"), text_of(root, "catch-all-whatsapp")))
change = next(json.loads(line) for line in (root / "state" / roster_api.CHANGES_LOG).read_text().splitlines()
              if json.loads(line).get("action") == "catch_all")
check("#609: sin migración, y el correo dice Telegram", ("telegram", [], False, True),
      (change["rules"]["channel"], change["rules"]["migrated"], change["rules"]["legacy_removed"],
       "Catch-All de Telegram" in mail[0][1]))

# El viejo apagado: los dos canales quedan apagados; prender WhatsApp no prende SMS.
root = install()
put(root, "catch-all", OFF)
svc, call, mail = service_for(root)
got = call("catchall.get", channel="whatsapp")["data"]
res = call("catchall.save", channel="whatsapp", enabled=True, text="Guarda el número.\n", etag=got["etag"])
check("viejo apagado: WhatsApp prendido, SMS sigue apagado con su archivo", ("result", "active", None, OFF),
      (res["type"], res["data"]["status"], rules_mod.catch_all_notice("sms", root), text_of(root, "catch-all-sms")))

# Falla a la mitad: un etag viejo no deja nada a medias.
root = install()
put(root, "catch-all", ON)
svc, call, mail = service_for(root)
res = call("catchall.save", channel="sms", enabled=False, text="x\n", etag="0" * 64)
check("FR-5: con un etag viejo, conflicto y nada cambia", ("error", "conflict", ON, None, None, 0),
      (res["type"], res.get("code"), text_of(root, "catch-all"), text_of(root, "catch-all-sms"),
       text_of(root, "catch-all-whatsapp"), len(mail)))

# Falla al escribir el del canal: se quitan los archivos ya creados y el viejo se queda.
root = install()
put(root, "catch-all", ON)
svc, call, mail = service_for(root)
got = call("catchall.get", channel="sms")["data"]
original = roster_edit.apply_file


def broken(*a, **k):
    raise roster_api.EditError("write_failed", detail="disco lleno")


roster_api.roster_edit.apply_file = broken
try:
    res = call("catchall.save", channel="sms", enabled=False, text="x\n", etag=got["etag"])
finally:
    roster_api.roster_edit.apply_file = original
check("FR-5: falla a la mitad: error, el viejo intacto, sin archivos nuevos", ("error", ON, None, None),
      (res["type"], text_of(root, "catch-all"), text_of(root, "catch-all-sms"), text_of(root, "catch-all-whatsapp")))
check("FR-4: tras la falla los dos canales siguen leyendo el viejo", ("rules/catch-all.md",) * 2,
      (rules_mod.catch_all_notice("sms", root)["file"], rules_mod.catch_all_notice("whatsapp", root)["file"]))

# Falla al quitar el viejo (revisión de #585): se deshace todo y es un error.
real_unlink = Path.unlink


def refuse_legacy(self, *a, **k):
    if self.name == "catch-all.md":
        raise PermissionError("sin permiso")
    return real_unlink(self, *a, **k)


for label, sms_before in (("sin archivo del canal", None), ("con el del canal ya presente", OFF)):
    root = install()
    put(root, "catch-all", ON)
    if sms_before is not None:
        put(root, "catch-all-sms", sms_before)
    svc, call, mail = service_for(root)
    got = call("catchall.get", channel="sms")["data"]
    Path.unlink = refuse_legacy
    try:
        res = call("catchall.save", channel="sms", enabled=True, text="Nuevo.\n", etag=got["etag"])
    finally:
        Path.unlink = real_unlink
    changes_log = root / "state" / roster_api.CHANGES_LOG
    check(f"FR-5 ({label}): no se pudo quitar el viejo: write_failed y todo como antes",
          ("error", "write_failed", ON, sms_before, None, 0, False),
          (res["type"], res.get("code"), text_of(root, "catch-all"), text_of(root, "catch-all-sms"),
           text_of(root, "catch-all-whatsapp"), len(mail), changes_log.exists()))

# Archivos nuevos ya presentes: la migración no los pisa.
root = install()
put(root, "catch-all", ON)
put(root, "catch-all-whatsapp", WA)
svc, call, mail = service_for(root)
got = call("catchall.get", channel="sms")["data"]
res = call("catchall.save", channel="sms", enabled=False, text=got["text"], etag=got["etag"])
check("FR-5: el de WhatsApp que ya estaba no se toca; el viejo se quita", ("result", WA, False),
      (res["type"], text_of(root, "catch-all-whatsapp"), (root / "rules" / "catch-all.md").exists()))

# Un contacto que usa un nombre reservado nuevo bloquea el guardado.
root = install()
(root / "roster.md").write_text(ROSTER.replace("+1XXXXXXXXXX |  |", "+1XXXXXXXXXX | catch-all-whatsapp |"),
                                encoding="utf-8")
svc, call, mail = service_for(root)
res = call("catchall.save", channel="sms", enabled=False, text="", etag="")
check("FR-3: un contacto con rules catch-all-whatsapp bloquea el guardado", ("error", "reserved_in_use"),
      (res["type"], res.get("reason")))


# --- API: channel y un permiso por canal (FR-12, FR-13, FR-13a) ----------------------------
class Ctx:
    def __init__(self, svc):
        self.svc = svc

    def roster_service(self):
        return self.svc


root = install()
svc, call, mail = service_for(root)
ctx = Ctx(svc)


def api(perms, **params):
    try:
        return 200, api_actions.run(ctx, {"prefix": "pn_test1234", "permissions": perms}, "203.0.113.7", params)
    except api_actions.ApiError as exc:
        return exc.status, {"code": exc.code, **exc.extra}


status, body = api(["read"], action="GetCatchAll", channel="whatsapp")
check("GetCatchAll con read y channel", (200, "whatsapp"), (status, body.get("channel")))
status, body = api(["read"], action="GetCatchAll", channel="email")
check("channel desconocido: 400 invalid_parameter", (400, "invalid_parameter", "channel"),
      (status, body.get("code"), body.get("field")))
status, body = api(["catchall.sms.write"], action="SaveCatchAll", channel="whatsapp", enabled=False, text="", etag="")
check("FR-13: sms.write no alcanza para WhatsApp", (403, "forbidden", "catchall.whatsapp.write"),
      (status, body.get("code"), body.get("permission")))
status, body = api(["catchall.sms.write"], action="SaveCatchAll", channel="sms", enabled=False, text="", etag="")
check("FR-13: sms.write cambia el de SMS", (200, "sms"), (status, body.get("channel")))
status, body = api(["catchall.write"], action="SaveCatchAll", channel="whatsapp", enabled=False, text="", etag="")
check("FR-13a: el viejo catchall.write no alcanza para WhatsApp", (403, "catchall.whatsapp.write"),
      (status, body.get("permission")))
etag = svc.catchall_get({"channel": "sms"}, "x")["etag"]
status, body = api(["catchall.write"], action="SaveCatchAll", enabled=True, text="Guarda.\n", etag=etag)
check("FR-12, FR-13a: sin channel y con catchall.write, cambia el de SMS", (200, "sms", "active"),
      (status, body.get("channel"), body.get("status")))
status, body = api(["catchall.whatsapp.write"], action="SaveCatchAll", channel="whatsapp", enabled=True,
                   text="Guarda.\n", etag="")
check("FR-13: whatsapp.write cambia el de WhatsApp", (200, "active"), (status, body.get("status")))
check("los dos canales quedaron activos por separado", (True, True),
      (rules_mod.catch_all_active("sms", root), rules_mod.catch_all_active("whatsapp", root)))

# El archivo de tokens: catchall.write pasa a catchall.sms.write (FR-13a).
store = Path(tempfile.mkdtemp()) / "api_tokens.json"
api_tokens.create("viejo", permissions=["read", "catchall.write"], path=store)
api_tokens.create("otro", permissions=["read"], path=store)
api_tokens.create("ambos", permissions=["catchall.write", "catchall.sms.write"], path=store)
changed = api_tokens.migrate_catchall_write(path=store)
records = {r["name"]: r["permissions"] for r in json.loads(store.read_text())}
check("FR-13a: los tokens que cambiaron, para el correo", ["viejo", "ambos"], [c["name"] for c in changed])
check("FR-13a: catchall.write pasó a catchall.sms.write, sin duplicar",
      {"viejo": ["read", "catchall.sms.write"], "otro": ["read"], "ambos": ["catchall.sms.write"]}, records)
check("FR-13a: una segunda vez no cambia nada", [], api_tokens.migrate_catchall_write(path=store))

# --- redacción por canal (FR-7, #544) ------------------------------------------------------
cmd = "[scripts/paynani event show ev_1 --body]"
text = (f"[sms 10:00, catch-all: rules/catch-all-sms.md] +1XXXXXXXXXX: hola {cmd}\n"
        f"[whatsapp 10:01, catch-all: rules/catch-all-whatsapp.md] +1XXXXXXXXXX: hola wa {cmd}")
only_sms = ev.redact_catch_all(text, {"sms"})
check("FR-7: apagar SMS borra el extracto del SMS y deja el de WhatsApp", (False, True),
      ("hola " + cmd in only_sms.splitlines()[0], "hola wa" in only_sms))
check("has_catch_all por canal y con el archivo viejo", (True, True, True),
      (ev.has_catch_all(text, "sms"), ev.has_catch_all(text, "whatsapp"),
       ev.has_catch_all(f"[sms 10:00, catch-all: rules/catch-all.md] x: y {cmd}", "sms")))
check("sin canales, redacta todos (como antes)", False, "hola" in ev.redact_catch_all(text).replace("hola wa", ""))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
