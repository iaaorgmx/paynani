#!/usr/bin/env python3
"""
Tests del Catch-All por el canal compartido y la API (PRD #535 FR-0a, FR-0b, FR-10,
FR-P1 a FR-P5): `catchall.get`/`catchall.save` en RosterService (etag, validación,
nombre reservado, log y correo al dueño, sin las instrucciones), `GetCatchAll` con
`read`, `SaveCatchAll` sólo con `catchall.write`, la marca `catch_all` en los
mensajes de un hilo y la casilla del permiso en «API Tokens». Un script de asserts,
como el resto de la suite. Nada sale de la máquina.
"""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import event as ev  # noqa: E402
from paynani_lib import i18n  # noqa: E402
from paynani_lib import rules as rules_mod  # noqa: E402
from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.sms import store as sms_store  # noqa: E402
from paynani_lib.sms import thread as sms_thread  # noqa: E402
from paynani_lib.web import api_tokens, app, notify, token_pages, users  # noqa: E402

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
| Julián Flores | julian@example.com | Human | julianflores | +525511112222 |  |
| Ana | ana@example.com | Human |  | +525511113333 |  |
"""
INSTRUCTIONS = "Avisa a Julián por Telegram con el número y el texto completo.\n"

tmp = Path(tempfile.mkdtemp())
clone = tmp / "clone"
clone.mkdir()
roster = clone / "roster.md"
roster.write_text(ROSTER, encoding="utf-8")
state = clone / "state"
state.mkdir()
catch_file = clone / "rules" / "catch-all-sms.md"
mail = []

# --- RosterService (FR-0a, FR-0b) ----------------------------------------------------
service = roster_api.RosterService(roster, state, rules_root=clone,
                                   notifier=lambda to, s, b: mail.append((to, s, b)), log=lambda line: None)
n = 0


def call(kind, device="web:203.0.113.9", **fields):
    global n
    n += 1
    res = service.handle({"type": kind, "id": "q_" + f"{n:032x}", **fields}, device)
    for t in service.notify_threads:
        t.join(5)
    return res


check("catchall.get y catchall.save van en TYPES; save en WRITES", (True, True, True, False),
      ("catchall.get" in roster_api.TYPES, "catchall.save" in roster_api.TYPES,
       "catchall.save" in roster_api.WRITES, "catchall.get" in roster_api.WRITES))
res = call("catchall.get")
check("sin archivo: apagado, sin etag", (False, False, "off", ""),
      (res["data"]["exists"], res["data"]["enabled"], res["data"]["status"], res["data"]["etag"]))
res = call("catchall.save", enabled=True, text="   \n", etag="")
check("FR-5: activo con instrucciones vacías no se guarda", ("error", "invalid", "text", False),
      (res["type"], res.get("code"), res.get("field"), catch_file.exists()))
res = call("catchall.save", enabled="sí", text=INSTRUCTIONS, etag="")
check("enabled que no es booleano: invalid", ("error", "enabled"), (res["type"], res.get("field")))
res = call("catchall.save", enabled=True, text="x" * (rules_mod.MAX_BYTES + 1), etag="")
check("FR-6: más de 32 KB no se guarda", ("error", False), (res["type"], catch_file.exists()))
res = call("catchall.save", enabled=True, text=INSTRUCTIONS, etag="")
check("activarlo desde la web", ("result", True, "active"),
      (res["type"], res["data"]["enabled"], res["data"]["status"]))
etag = res["data"]["etag"]
check("FR-9: el archivo tiene la cabecera de rules.py y las instrucciones", (True, True, INSTRUCTIONS.strip()),
      (rules_mod.catch_all_notice("sms", clone) == {"file": "rules/catch-all-sms.md", "status": "active"},
       "updated_by: PaynaniWeb 203.0.113.9" in catch_file.read_text(encoding="utf-8"),
       rules_mod.catch_all_instructions("sms", clone).strip()))
res = call("catchall.get")
check("catchall.get: activo, quién lo cambió y el etag", (True, "PaynaniWeb 203.0.113.9", etag, True),
      (res["data"]["enabled"], res["data"]["updated_by"], res["data"]["etag"], bool(res["data"]["updated_at"])))
res = call("catchall.save", enabled=False, text=INSTRUCTIONS, etag="viejo")
check("etag viejo: conflict, y el archivo no cambia", ("error", "conflict", True),
      (res["type"], res.get("code"), rules_mod.catch_all_notice("sms", clone) is not None))

log = [json.loads(line) for line in (state / roster_api.CHANGES_LOG).read_text(encoding="utf-8").splitlines()]
changes = [e for e in log if e.get("action") == "catch_all"]
check("FR-0b: el cambio queda en roster_changes.jsonl", (1, "rules/catch-all-sms.md", True),
      (len(changes), changes[0]["rules"]["file"], changes[0]["rules"]["enabled"]))
check("el log no lleva las instrucciones", False, "Telegram" in json.dumps(log))
check("FR-0b: el correo al dueño dice qué cambió y desde dónde, sin las instrucciones",
      (1, "julian@example.com", True, True, False),
      (len(mail), mail[0][0], "Catch-All" in mail[0][1], "PaynaniWeb (dirección 203.0.113.9)" in mail[0][2],
       "Telegram" in mail[0][2]))
check("el aviso salió (línea notify del log)", True,
      any(e.get("type") == "notify" and e.get("for") == changes[0]["change"] and e.get("notified") for e in log))

res = call("catchall.save", device="d_fb89b8", enabled=False, text=INSTRUCTIONS, etag=etag)
check("apagarlo desde el teléfono", ("result", False, "off", "phone d_fb89b8"),
      (res["type"], res["data"]["enabled"], res["data"]["status"], res["data"]["updated_by"]))
check("apagado: el aviso al agente ya no lo usa", None, rules_mod.catch_all_notice("sms", clone))
etag = res["data"]["etag"]
res = call("catchall.save", device="api:pk_ABCDEFG:198.51.100.7", enabled=True, text=INSTRUCTIONS, etag=etag)
check("por la API: updated_by nombra el prefijo del token, nunca el token", "API token pk_ABCDEFG",
      res["data"]["updated_by"])
check("y el correo dice que fue por la API con ese token y cómo revocarlo", (True, True),
      ("Desde la API con el token pk_ABCDEFG (dirección 198.51.100.7)" in mail[-1][2], "API Tokens" in mail[-1][2]))
etag = res["data"]["etag"]

# Archivo roto a mano: get lo dice y deja corregirlo.
catch_file.write_text("---\nversion: uno\n", encoding="utf-8")
res = call("catchall.get")
check("archivo inválido: status invalid y el texto entero para corregirlo", ("invalid", True),
      (res["data"]["status"], "version: uno" in res["data"]["text"]))
res = call("catchall.save", enabled=True, text=INSTRUCTIONS, etag=res["data"]["etag"])
check("y se puede guardar encima con su etag", ("result", "active"), (res["type"], res["data"]["status"]))
etag = res["data"]["etag"]

# FR-10: un contacto que ya usa el nombre reservado.
roster.write_text(ROSTER.replace("| +525511113333 |  |", "| +525511113333 | catch-all |"), encoding="utf-8")
res = call("catchall.save", enabled=False, text=INSTRUCTIONS, etag=etag)
check("FR-10: con un contacto que usa rules/catch-all.md no se guarda", ("error", "reserved_in_use"),
      (res["type"], res.get("reason")))
listing = call("roster.list")["data"]
ana = next(m for m in listing["members"] if m["name"] == "Ana")
res = call("rules.save", account=None, row=ana["row"], roster_etag=listing["etag"], etag=etag,
           text="---\nversion: 1\nenabled: false\n---\n\nOtra cosa.\n")
check("las reglas de ese contacto no pueden escribir rules/catch-all.md", ("error", "reserved", True),
      (res["type"], res.get("reason"), rules_mod.catch_all_notice("sms", clone) is not None))
roster.write_text(ROSTER, encoding="utf-8")

# --- la marca en el hilo (FR-P4) -----------------------------------------------------
journal = state / "events.jsonl"
st = sms_store.Store(state)
for mid, number, caught in (("1" * 64, "+525599990000", True), ("2" * 64, "+525599990000", False)):
    record = {"event_type": ev.SMS_RECEIVED, "event_id": f"sms:d_1:{mid}", "provider_id": f"sms:{mid}",
              "sender": {"name": "", "address": number}, "sent_at": "2026-10-25T23:00:00Z",
              "observed_at": "2026-10-25T23:00:01Z", "roster_match": False}
    if caught:
        record["catch_all"] = {"file": "rules/catch-all.md", "status": "active"}
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    st.save_inbox(mid, {"text": "hola " + mid[0]})
items = sms_thread.items(st, journal)
check("FR-P4: sólo el SMS que llegó con el Catch-All lleva catch_all: true", [True, None],
      [i.get("catch_all") for i in items])

# --- la API (FR-P1, FR-P2) -----------------------------------------------------------
user_file = clone / "web" / "user.json"
users.create("julian@example.com", "Julián Flores", "una-contraseña-larga", user_file)
api_mail = []
ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda to, s, b: None, log=lambda line: None),
                  agent_email="agente@example.com", accounts_file=clone / "accounts.json",
                  ledger_path=state / "lifecycle.jsonl", env_path=clone / "no.env", state_dir=state,
                  roster_path=roster, roster_notifier=lambda to, s, b: api_mail.append((to, s, b)))
store_path = api_tokens.path_for(user_file)
reader, _ = api_tokens.create("lector", permissions=["read"], path=store_path)
roster_writer, _ = api_tokens.create("roster", permissions=["read", "roster.write"], path=store_path)
catcher, catcher_rec = api_tokens.create("catchall", permissions=["read", "catchall.write"], path=store_path)
httpd = app.serve("127.0.0.1", 0, ctx=ctx)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def api(token, action, **params):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("POST", "/api/agent", body=json.dumps({"action": action, **params}),
                 headers={"Host": "agente.ngrok.app", "X-Forwarded-For": "203.0.113.9",
                          "Authorization": "Bearer " + token, "Content-Type": "application/json"})
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


status, body = api(reader, "GetCatchAll")
check("FR-P1: GetCatchAll con read", (200, "success", True), (status, body["result"], body.get("enabled")))
etag = body.get("etag", "")
status, body = api(reader, "SaveCatchAll", enabled=False, text="", etag=etag)
check("#576 FR-13: SaveCatchAll sin catchall.sms.write: forbidden", (403, "forbidden", "catchall.sms.write"),
      (status, body.get("code"), body.get("permission")))
status, body = api(roster_writer, "SaveCatchAll", enabled=False, text="", etag=etag)
check("FR-P2: roster.write no alcanza", (403, "catchall.sms.write"), (status, body.get("permission")))
status, body = api(catcher, "SaveCatchAll", enabled="true", text=INSTRUCTIONS, etag=etag)
check("enabled como texto: 400 invalid_parameter", (400, "invalid_parameter", "enabled"),
      (status, body.get("code"), body.get("field")))
status, body = api(catcher, "SaveCatchAll", enabled=True, text="", etag=etag)
check("FR-5 por la API: activo sin instrucciones, 400", (400, "invalid"), (status, body.get("code")))
status, body = api(catcher, "SaveCatchAll", enabled=False, text=INSTRUCTIONS, etag=etag)
check("#576 FR-13a: un token con el viejo catchall.write guarda el de SMS", (200, "success", False, "off"),
      (status, body["result"], body.get("enabled"), body.get("status")))
check("updated_by nombra el prefijo del token", f"API token {catcher_rec['prefix']}", body.get("updated_by"))
status, again = api(catcher, "SaveCatchAll", enabled=True, text=INSTRUCTIONS, etag=etag)
check("con el etag viejo: 409 conflict", (409, "conflict"), (status, again.get("code")))
check("el dueño recibió el correo del cambio por la API", True,
      any("Catch-All" in s and catcher_rec["prefix"] in b for _, s, b in api_mail))
httpd.shutdown()

# --- «API Tokens» (FR-P3) ------------------------------------------------------------
check("#576 FR-13b: un permiso por canal en la pantalla, sin el viejo", (True, True, False),
      tuple(p in token_pages.PERMISSIONS for p in ("catchall.sms.write", "catchall.whatsapp.write", "catchall.write")))
tokens = json.loads(store_path.read_text())
check("#576 FR-13a: al arrancar la web, catchall.write pasó a catchall.sms.write (sólo el que lo tenía)",
      (["catchall"], []),
      ([r["name"] for r in tokens if "catchall.sms.write" in r.get("permissions", [])],
       [r["name"] for r in tokens if "catchall.write" in r.get("permissions", [])]))
missing = [lang for lang in ("es-MX", "en-US", "es-ES", "fr-FR", "pt-BR")
           if not all(p in i18n.CATALOGUES[lang].get("web.tokens.catchall_hint", "")
                      for p in ("catchall.sms.write", "catchall.whatsapp.write"))]
check("la explicación del permiso está en los cinco idiomas", [], missing)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
