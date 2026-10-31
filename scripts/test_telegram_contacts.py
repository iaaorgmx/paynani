#!/usr/bin/env python3
"""
Pruebas de TG-3 (#612, PRD #609 FR-11 a FR-18): la columna Telegram en doctor, el
@usuario fijado a un id, las reglas del contacto, el Catch-All de Telegram,
«Agregar al roster», `event show --body` y la multimedia, contra el servidor falso.
"""

import asyncio
import contextlib
import io
import json
import pathlib
import stat
import sys
import tempfile
import time
import zipfile
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import roster as roster_mod  # noqa: E402
from paynani_lib import diagnostics, event_cli  # noqa: E402
from paynani_lib.telegram import contacts, media as tg_media  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402

passed = failed = 0
TOKEN = "123456:fake_token_only_for_tests_x"
BOT_ID = 987654321
ANA = 7771234501          # en el roster por id, con reglas
BETO = 7771234502         # en el roster por @usuario
OTRO = 7771234504         # otra cuenta que usa el @usuario de Beto
PEDRO = 7771234503        # fuera del roster
IDS = [str(x) for x in (BOT_ID, ANA, BETO, OTRO, PEDRO)]


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"ok    {name}")
    else:
        failed += 1
        print(f"FAIL  {name} {detail}")


ROSTER = """\
| Name | Email | Telegram | Type | Rules |
|---|---|---|---|---|
| Dueña Prueba | duena@example.com |  | Human |  |
| Ana López | ana@example.com | %d | Human | ana-lopez |
| Beto Ruiz | beto@example.com | @Beto_Ruiz | Human |  |
| Doble Uno | d1@example.com | @doble_x | Human |  |
| Doble Dos | d2@example.com | @doble_x | Human |  |
| Mal Valor | m@example.com | @ab | Human |  |
""" % ANA
RULES_ON = "---\nversion: 1\nenabled: true\n---\nTrátala de usted.\n"
CATCH_ON = "---\nversion: 1\nenabled: true\n---\nContesta sólo con el horario.\n"
CATCH_OFF = "---\nversion: 1\nenabled: false\n---\nContesta sólo con el horario.\n"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
PDF = b"%PDF-1.7\n" + b"x" * 200
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200


def ooxml(kind="docx", macro=False, bomb=False):
    part, ctype = {"docx": ("word/document.xml", "wordprocessingml.document.main+xml"),
                   "xlsx": ("xl/workbook.xml", "spreadsheetml.sheet.main+xml")}[kind]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<Types><Override PartName="/%s" ContentType="application/'
                    'vnd.openxmlformats-officedocument.%s"/></Types>' % (part, ctype))
        zf.writestr(part, "<x/>")
        if macro:
            zf.writestr("word/vbaProject.bin", b"\x00" * 10)
        if bomb:
            zf.writestr("xl/big.xml", b"\x00" * (3 * 1024 * 1024))
    return buf.getvalue()


def events(state):
    try:
        lines = (state / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [json.loads(x) for x in lines if x.strip()]


def tg(state):
    return [e for e in events(state) if e.get("channel") == "telegram"]


async def until(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


async def socket_call(path, obj):
    reader, writer = await asyncio.open_unix_connection(str(path))
    writer.write((json.dumps(obj) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


def show(state, eid, body):
    """`event show` en el mismo proceso, con el estado y el roster de la prueba."""
    event_cli.state_dir = lambda: state
    event_cli.roster_file = lambda: state / "roster.md"
    event_cli._find = lambda e, journal=None: next((x for x in events(state) if x["event_id"] == e), None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = event_cli.run_show(SimpleNamespace(event_id=eid, body=body))
    return code, out.getvalue(), err.getvalue()


def unit_tests():
    known = roster_mod._telegram_from_text(ROSTER)
    check("FR-11: un @usuario se normaliza; la fila trae sus reglas",
          known["usernames"].get("beto_ruiz", {}).get("name") == "Beto Ruiz"
          and known["ids"][str(ANA)]["rules"] == "ana-lopez")
    probs = sorted((p["name"], p["problem"]) for p in known["problems"])
    check("FR-11/FR-11a: inválido y repetidos, por fila", probs == [
        ("Doble Dos", "duplicate"), ("Doble Uno", "duplicate"), ("Mal Valor", "invalid")], str(probs))
    doc = diagnostics._telegram_roster_check({"telegram_problems": known["problems"]})
    check("doctor: un warning que nombra las filas", bool(doc) and doc["name"] == "roster:telegram"
          and "Doble Uno" in doc["summary"] and "Mal Valor" in doc["summary"] and "error" in doc["summary"])
    check("doctor: sin el valor de la columna", "doble_x" not in json.dumps(doc) and "@ab" not in json.dumps(doc))
    check("doctor: sin problemas, sin check", diagnostics._telegram_roster_check({"telegram_problems": []}) is None)

    d = contacts.decide(known, {}, BETO, "Beto_Ruiz")
    check("decide: primer mensaje del @usuario lo fija", d["pin"] == "beto_ruiz" and d["entry"]["name"] == "Beto Ruiz")
    links = {"beto_ruiz": {"id": BETO}}
    d = contacts.decide(known, links, BETO, "otro_nombre")
    check("decide: fijado, se reconoce por id aunque cambie de @usuario",
          d["entry"]["name"] == "Beto Ruiz" and d["pin"] is None)
    d = contacts.decide(known, links, OTRO, "beto_ruiz")
    check("decide: otro id con el mismo @usuario no se reconoce", d["entry"] is None and d["conflict"] == "beto_ruiz")
    d = contacts.decide(known, {"viejo_nombre": {"id": BETO}}, BETO, None)
    check("decide: un vínculo cuyo @usuario ya no está se borra", d["drop"] == ["viejo_nombre"] and d["entry"] is None)
    d = contacts.decide(known, {}, PEDRO, "doble_x")
    check("decide: un @usuario repetido no reconoce a nadie", d["entry"] is None and d["pin"] is None)
    check("recognized_now: no fija nada", contacts.recognized_now(known, {}, BETO) is None
          and contacts.recognized_now(known, links, BETO)["name"] == "Beto Ruiz")

    tmp = pathlib.Path(tempfile.mkdtemp())
    cases = [("jpeg", JPEG, "image", "jpeg"), ("png como foto", PNG, "image", "png"),
             ("pdf", PDF, "pdf", "pdf"), ("docx", ooxml(), "docx", "docx"), ("xlsx", ooxml("xlsx"), "xlsx", "xlsx"),
             ("png declarado pdf", PNG, "pdf", None), ("OLE .doc", OLE, "docx", None),
             ("docx con macros", ooxml(macro=True), "docx", None),
             ("xlsx con bomba de compresión", ooxml("xlsx", bomb=True), "xlsx", None),
             ("docx declarado xlsx", ooxml(), "xlsx", None),
             ("zip cualquiera", b"PK\x03\x04" + b"\x00" * 50, "docx", None)]
    for label, data, category, want in cases:
        f = tmp / "f"
        f.write_bytes(data)
        check(f"FR-18 tipo real: {label}", tg_media.accept(f, category) == want, str(tg_media.sniff(f)))
    check("FR-18 declarado: MIME manda; sin MIME, la extensión",
          (tg_media.declared("document", "application/pdf", "x.exe"), tg_media.declared("document", None, "a.docx"),
           tg_media.declared("document", "application/msword", "a.doc"), tg_media.declared("image", None, None))
          == ("pdf", "docx", None, "image"))


async def service_tests():
    state = pathlib.Path(tempfile.mkdtemp())
    (state / "roster.md").write_text(ROSTER, encoding="utf-8")
    rules = state / "rules"
    rules.mkdir(mode=0o700)
    (rules / "ana-lopez.md").write_text(RULES_ON, encoding="utf-8")
    api = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot").start()
    logs, mails = [], []
    s = TelegramService(state, roster_path=state / "roster.md", token=TOKEN, api_base=api.base_url,
                        log=logs.append, poll_timeout=1, backoff=(0.05, 0.2), rules_root=state,
                        mail_owner=lambda subj, body: mails.append((subj, body)),
                        settings={"TELEGRAM_MAX_MEDIA_MB": "1"})
    await s.start()
    try:
        await until(lambda: s.state == "running")

        # --- FR-13: el @usuario se fija con el primer mensaje -------------------------
        api.private_message(BETO, "hola, soy Beto", first_name="Beto", username="beto_ruiz")
        await until(lambda: len(tg(state)) == 1 and len(mails) == 1)
        e = tg(state)[-1]
        check("FR-13: Beto reconocido por su @usuario",
              e["roster_match"] is True and "Beto Ruiz" in e["notification_text"])
        check("FR-13: el dueño recibe «@usuario quedó vinculado a <contacto>»",
              len(mails) == 1 and "@beto_ruiz quedó vinculado a Beto Ruiz" in mails[0][0], str(mails))
        lf = s.store.root / "links.json"
        check("FR-13: links.json 0600 con el id fijado", stat.S_IMODE(lf.stat().st_mode) == 0o600
              and json.loads(lf.read_text())["usernames"]["beto_ruiz"]["id"] == BETO)
        api.private_message(BETO, "ya cambié mi @", first_name="Beto", username="beto_nuevo")
        await until(lambda: len(tg(state)) == 2)
        check("FR-13: después se reconoce sólo por el id, aunque cambie su @usuario",
              tg(state)[-1]["roster_match"] is True and len(mails) == 1)
        api.private_message(OTRO, "soy Beto, en serio", first_name="Falso", username="beto_ruiz")
        api.private_message(OTRO, "otra vez", first_name="Falso", username="beto_ruiz")
        await until(lambda: len(tg(state)) == 4 and len(mails) == 2)
        impostor = tg(state)[-2:]
        check("FR-13: otro id con el @usuario fijado no se reconoce",
              all(x["roster_match"] is False for x in impostor)
              and "soy Beto" not in json.dumps(impostor, ensure_ascii=False))
        await asyncio.sleep(0.3)
        check("FR-13: el dueño recibe un aviso, una vez por id", len(mails) == 2
              and "otra cuenta de Telegram escribió como @beto_ruiz" in mails[1][0], str([m[0] for m in mails]))

        # --- reglas del contacto -------------------------------------------------------
        api.private_message(ANA, "¿Tienen mesa?", first_name="Ana")
        await until(lambda: len(tg(state)) == 5)
        e = tg(state)[-1]
        check("A-1: el aviso de Ana nombra sus reglas",
              e.get("rules") == {"file": "rules/ana-lopez.md", "status": "active"}
              and "reglas: rules/ana-lopez.md" in e["notification_text"], e["notification_text"])
        code, out, _ = show(state, e["event_id"], True)
        check("event show --body: Ana del roster ve el texto", code == 0 and "¿Tienen mesa?" in out
              and "authorized: the Telegram account is on roster.md" in out, out[-300:])
        check("event show: sin ids de Telegram", not any(i in out for i in IDS))

        # --- FR-17: fuera del roster, con y sin Catch-All ----------------------------------
        api.private_message(PEDRO, "texto privado de Pedro", first_name="Pedro")
        await until(lambda: len(tg(state)) == 6)
        hidden = tg(state)[-1]
        check("FR-17: sin Catch-All, sin texto y sin catch_all", "privado" not in hidden["notification_text"]
              and "catch_all" not in hidden and "(no verificado)" in hidden["notification_text"])
        code, _, err = show(state, hidden["event_id"], True)
        check("FR-17: sin Catch-All, --body se niega", code == 2 and "refused" in err)
        (rules / "catch-all.md").write_text(CATCH_ON, encoding="utf-8")
        api.private_message(PEDRO, "sigue sin Catch-All de Telegram", first_name="Pedro")
        await until(lambda: len(tg(state)) == 7)
        check("FR-17: el viejo rules/catch-all.md no abre Telegram", "catch_all" not in tg(state)[-1]
              and "sigue sin" not in tg(state)[-1]["notification_text"])
        (rules / "catch-all-telegram.md").write_text(CATCH_ON, encoding="utf-8")
        api.private_message(PEDRO, None, first_name="Pedro", photo=JPEG, caption="¿a qué hora abren?")
        await until(lambda: len(tg(state)) == 8)
        caught = tg(state)[-1]
        check("FR-17: con el Catch-All de Telegram, el aviso trae el extracto",
              caught.get("catch_all") == {"file": "rules/catch-all-telegram.md", "status": "active"}
              and "¿a qué hora abren?" in caught["notification_text"]
              and "catch-all: rules/catch-all-telegram.md" in caught["notification_text"], caught["notification_text"])
        code, out, _ = show(state, caught["event_id"], True)
        check("FR-17: --body da las instrucciones del dueño, el texto y la foto", code == 0
              and "Contesta sólo con el horario" in out and "¿a qué hora abren?" in out
              and "attachment: image/jpeg" in out, out[-400:])
        (rules / "catch-all-telegram.md").write_text(CATCH_OFF, encoding="utf-8")
        code, out, err = show(state, caught["event_id"], True)
        check("#544: apagado, --body se niega y el sobre va sin extracto", code == 2
              and "catch-all is off now" in err and "¿a qué hora" not in out and "catch-all apagado" in out)

        # --- FR-15: «Agregar al roster» -----------------------------------------------------
        thread = s.store.inbox(hidden["event_id"])["thread"]
        rid = iter("q_%032x" % n for n in range(1, 100))
        r = await socket_call(s.socket_path, {"type": "telegram.roster_candidate", "id": next(rid),
                                              "by": "web", "thread": thread})
        check("FR-15: la web recibe el id y el nombre de Telegram", r.get("ok") is True
              and r["data"] == {"telegram": str(PEDRO), "display_name": "Pedro"}, str(r))
        r = await socket_call(s.socket_path, {"type": "telegram.roster_candidate", "id": next(rid),
                                              "by": "agent", "thread": thread})
        check("FR-15: sólo la web", r.get("code") == "not_allowed", str(r))
        ana_thread = s.store.inbox(tg(state)[4]["event_id"])["thread"]
        r = await socket_call(s.socket_path, {"type": "telegram.roster_candidate", "id": next(rid),
                                              "by": "web", "thread": ana_thread})
        check("FR-15: alguien del roster no es candidato", r.get("code") == "conflict", str(r))
        r = await socket_call(s.socket_path, {"type": "telegram.roster_candidate", "id": next(rid),
                                              "by": "web", "thread": "t_" + "0" * 32})
        check("FR-15: un hilo que no existe", r.get("code") == "not_found", str(r))

        # --- FR-18: multimedia ------------------------------------------------------------
        before = len(tg(state))

        def gets():
            return len(api.file_requests)
        g0 = gets()
        api.private_message(ANA, None, first_name="Ana", document=(PDF, "menú.pdf", "application/pdf"))
        api.private_message(ANA, None, first_name="Ana", document=(PNG, "factura.pdf", "application/pdf"))
        api.private_message(ANA, None, first_name="Ana", document=(OLE, "viejo.doc", "application/msword"))
        api.private_message(ANA, None, first_name="Ana", document=(PDF, "grande.pdf", "application/pdf"),
                            declared_size=2 * 1024 * 1024)
        api.private_message(ANA, None, first_name="Ana",
                            document=(b"%PDF-" + b"x" * (1024 * 1024 + 10), "miente.pdf", "application/pdf"),
                            declared_size=100)
        api.private_message(ANA, None, first_name="Ana", caption="el contrato",
                            document=(ooxml(), "contrato.docx",
                                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        await until(lambda: len(tg(state)) == before + 6, timeout=15)
        batch = tg(state)[before:]
        saved = [s.store.inbox(x["event_id"])["media"] for x in batch]
        check("FR-18: el PDF de verdad se guarda", (saved[0] or {}).get("type") == "pdf", str(saved[0]))
        check("FR-18: un PNG declarado PDF se rechaza por tipo", saved[1] == {"rejected": "type"}
              and batch[1].get("media_rejected") == "type"
              and "rechazado: tipo" in batch[1]["notification_text"], batch[1]["notification_text"])
        check("FR-18: OLE .doc rechazado sin bajarlo", saved[2] == {"rejected": "type"})
        check("FR-18: tamaño declarado mayor al límite: no se baja", saved[3] == {"rejected": "size"})
        check("FR-18: se corta al pasar el límite aunque declare menos", saved[4] == {"rejected": "size"},
              str(saved[4]))
        check("FR-18: sólo se pidió getFile para los que podían pasar", gets() - g0 == 4, str(gets() - g0))
        check("FR-18: el .docx sin macros se guarda", (saved[5] or {}).get("type") == "docx", str(saved[5]))
        mdir = state / "telegram" / "media"
        files = sorted(p.name for p in mdir.iterdir())
        check("FR-18: media/ 0700, archivos 0600, nada a medias", stat.S_IMODE(mdir.stat().st_mode) == 0o700
              and all(stat.S_IMODE((mdir / f).stat().st_mode) == 0o600 for f in files)
              and not any(f.startswith(".part-") for f in files), str(files))
        check("FR-18: nombres aleatorios con la extensión del tipo real",
              all(len(f.split(".")[0]) == 32 for f in files)
              and {f.split(".")[1] for f in files} == {"jpg", "pdf", "docx"}, str(files))
        check("FR-18: lo rechazado no queda en disco", len(files) == 3, str(files))
        check("FR-18: media_rejected cuenta los cuatro", s.counters["media_rejected"] == 4, str(s.counters))
        code, out, _ = show(state, batch[1]["event_id"], True)
        check("event show: el rechazado lo dice y no da ruta", code == 0 and "attachment rejected (type)" in out
              and str(mdir) not in out)
        g1 = gets()
        api.private_message(PEDRO, None, first_name="Pedro", document=(PDF, "x.pdf", "application/pdf"))
        await until(lambda: len(tg(state)) == before + 7)
        check("FR-17/18: fuera del roster sin Catch-All no se baja nada", gets() == g1
              and s.store.inbox(tg(state)[-1]["event_id"])["media"] is None)

        # --- FR-13: el dueño cambia la columna: el vínculo se borra ------------------------
        (state / "roster.md").write_text(ROSTER.replace("@Beto_Ruiz", "@beto_otro"), encoding="utf-8")
        api.private_message(BETO, "¿sigo en el roster?", first_name="Beto", username="beto_nuevo")
        await until(lambda: len(tg(state)) == before + 8)
        check("FR-13: cambió la columna: el vínculo anterior se borra y ya no se reconoce",
              tg(state)[-1]["roster_match"] is False
              and "beto_ruiz" not in json.loads((s.store.root / "links.json").read_text())["usernames"])
        code, _, err = show(state, tg(state)[1]["event_id"], True)
        check("event show: quien dejó de estar en el roster ya no da el texto", code == 2 and "no longer" in err, err)

        # --- nada de ids en lo que sale ------------------------------------------------------
        outputs = {"events": (state / "events.jsonl").read_text(encoding="utf-8"), "log": "\n".join(logs),
                   "status": json.dumps(s.status()), "mails": json.dumps(mails, ensure_ascii=False)}
        leaks = [(n, i) for n, t in outputs.items() for i in IDS if i in t]
        check("ni ids ni token en eventos, log, status ni correos",
              leaks == [] and not any(TOKEN in t for t in outputs.values()), str(leaks))
        check("ningún @usuario de personas en eventos ni log",
              not any(u in outputs["events"] + outputs["log"] for u in ("beto_ruiz", "beto_nuevo", "Beto_Ruiz")))
    finally:
        await s.stop()
        api.stop()


def harness_tests():
    import event as ev
    import session_start
    line = ("[telegram 19:10:02, catch-all: rules/catch-all-telegram.md] Pedro (no verificado): "
            "hola qué tal [scripts/paynani event show tg:%s]" % ("a" * 32))
    red = ev.redact_catch_all(line, {"telegram"})
    check("#544: el aviso de Telegram apagado pierde el extracto", "hola" not in red
          and "catch-all apagado" in red and "mensaje de alguien fuera del roster" in red, red)
    check("#576 FR-7: apagar SMS no toca el de Telegram", ev.redact_catch_all(line, {"sms"}) == line)
    check("session_start: el canal de un evento de Telegram",
          session_start._catch_all_channel({"event_type": "telegram.received"}) == "telegram"
          and session_start._catch_all_channel({"event_type": "sms.received"}) == "sms")


def main():
    unit_tests()
    harness_tests()
    asyncio.run(service_tests())
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
