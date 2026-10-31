#!/usr/bin/env python3
"""
Pruebas de TG-4 (#612, PRD #609 FR-20 a FR-27): send, archivos, límites, 429,
«escribiendo…», draft, --stream, hilos, telegram.image, watch y la CLI, contra el
servidor falso de la Bot API.
"""

import asyncio
import json
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import ledger  # noqa: E402
from paynani_lib.telegram import outbound  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402

passed = failed = 0
TOKEN = "123456:fake_token_only_for_tests_x"
BOT_ID = 987654321
ANA = 7771234501
PEDRO = 7771234503
IDS = [str(x) for x in (BOT_ID, ANA, PEDRO)]
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200

ROSTER = """\
| Name | Email | Telegram | Type |
|---|---|---|---|
| Ana López | ana@example.com | %d | Human |
| Beto Ruiz | beto@example.com | @beto_ruiz | Human |
""" % ANA


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"ok    {name}")
    else:
        failed += 1
        print(f"FAIL  {name} {detail}")


async def until(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


_n = [0]


def q():
    _n[0] += 1
    return "q_%032x" % _n[0]


async def call(s, kind, by="terminal", **fields):
    msg = {"type": kind, "id": q(), **fields}
    if by is not None:
        msg["by"] = by
    reader, writer = await asyncio.open_unix_connection(str(s.socket_path))
    writer.write((json.dumps(msg) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


async def cli(env, *argv, stdin=None):
    """La CLI en otro proceso, sin detener el loop donde corre el servicio."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(ROOT / "scripts" / "paynani"), "telegram", *argv, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin else b""), 60)
    return proc.returncode, out.decode(), err.decode()


def methods(api, name):
    return [x["params"] for x in api.sent if x["method"] == name]


async def service(state, api, logs, **settings):
    (state / "roster.md").write_text(ROSTER, encoding="utf-8")
    opts = {"TELEGRAM_SEND_PER_DAY": "50"}
    opts.update(settings)
    s = TelegramService(state, roster_path=state / "roster.md", token=TOKEN, api_base=api.base_url,
                        log=logs.append, poll_timeout=1, backoff=(0.05, 0.2), rules_root=state, settings=opts)
    await s.start()
    await until(lambda: s.state == "running")
    return s


async def main_tests():
    state = pathlib.Path(tempfile.mkdtemp())
    api = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot").start()
    logs = []
    s = await service(state, api, logs)
    try:
        # --- FR-25: sólo a quien ya escribió y está en el roster ------------------------
        r = await call(s, "telegram.send", contact="Ana López", text="hola")
        check("FR-25: Ana no ha escrito: not_started", r.get("code") == "not_started", str(r))
        r = await call(s, "telegram.send", contact="Nadie", text="hola")
        check("FR-25: alguien que no está en el roster: not_allowed", r.get("code") == "not_allowed", str(r))
        r = await call(s, "telegram.send", contact="Ana López", thread="t_" + "0" * 32, text="x")
        check("thread y contact a la vez: missing_field", r.get("code") == "missing_field", str(r))

        # --- FR-21: «escribiendo…» ------------------------------------------------------
        api.private_message(ANA, "¿Tienen mesa a las 8?", first_name="Ana")
        await until(lambda: methods(api, "sendChatAction"))
        typing = methods(api, "sendChatAction")
        check("FR-21: llega el mensaje de un contacto y sale «escribiendo…»",
              typing and typing[0].get("action") == "typing", str(typing))
        api.private_message(PEDRO, "hola, soy Pedro", first_name="Pedro")
        await asyncio.sleep(0.5)
        check("FR-21: alguien fuera del roster no recibe «escribiendo…»",
              all(int(p["chat_id"]) == ANA for p in methods(api, "sendChatAction")))

        # --- send ---------------------------------------------------------------------
        r = await call(s, "telegram.send", by="agent", contact="ana@example.com", text="Sí, a las 8 tenemos lugar.")
        check("send por el correo del roster", r.get("ok") and r["data"]["status"] == "sent"
              and r["data"]["ref"].startswith("tgo:"), str(r))
        sm = methods(api, "sendMessage")
        check("send: un sendMessage al chat de Ana", len(sm) == 1 and sm[0]["text"] == "Sí, a las 8 tenemos lugar.")
        n = len(methods(api, "sendChatAction"))
        await asyncio.sleep(outbound.TYPING_EVERY_S + 0.5)
        check("FR-21: al mandar se apaga «escribiendo…»", len(methods(api, "sendChatAction")) == n)
        pedro_thread = next(t for t, i in s.store.threads().items() if i["user"] == PEDRO)
        r = await call(s, "telegram.send", thread=pedro_thread, text="hola")
        check("FR-25: el hilo de alguien fuera del roster: not_allowed", r.get("code") == "not_allowed", str(r))

        # --- FR-21: se apaga cuando el agente cierra el evento ----------------------------
        api.private_message(ANA, "otra pregunta", first_name="Ana")
        await until(lambda: len(methods(api, "sendChatAction")) > n)
        ref = [e for e in s.store.received() if e.get("text") == "otra pregunta"][0]["ref"]
        ledger.transition(s.ledger_path, ref, "handled")
        n = len(methods(api, "sendChatAction"))
        await asyncio.sleep(outbound.TYPING_EVERY_S + 0.5)
        check("FR-21: evento cerrado, ya no sale «escribiendo…»", len(methods(api, "sendChatAction")) <= n + 1,
              str(len(methods(api, "sendChatAction")) - n))

        # --- 4096 y el ritmo de 1 por segundo (FR-26) -----------------------------------
        long_text = ("palabra " * 700).strip()          # 5599 caracteres
        before = len(methods(api, "sendMessage"))
        t0 = time.monotonic()
        r = await call(s, "telegram.send", contact="Ana López", text=long_text)
        parts = methods(api, "sendMessage")[before:]
        check("más de 4096: se parte en dos mensajes", r.get("ok") and len(parts) == 2
              and all(len(p["text"]) <= 4096 for p in parts) and " ".join(p["text"] for p in parts) == long_text,
              str([len(p["text"]) for p in parts]))
        check("FR-26: un mensaje por segundo por chat", time.monotonic() - t0 >= 0.9)

        # --- 429 (FR-26) -----------------------------------------------------------------
        api.fail_next("sendMessage", 429, retry_after=1)
        r = await call(s, "telegram.send", contact="Ana López", text="después de esperar")
        check("FR-26: un 429 espera y reintenta", r.get("ok") is True, str(r))
        api.fail_next("sendMessage", 429, retry_after=1)
        api.fail_next("sendMessage", 429, retry_after=1)
        r = await call(s, "telegram.send", contact="Ana López", text="no sale")
        check("FR-26: dos 429 seguidos: rate_limited con retry_after_s",
              r.get("code") == "rate_limited" and r.get("retry_after_s") == 1, str(r))

        # --- archivos (FR-20) --------------------------------------------------------------
        outbox = state / "telegram" / "outbox"
        outbox.mkdir(mode=0o700, exist_ok=True)
        (outbox / "menu.jpg").write_bytes(JPEG)
        r = await call(s, "telegram.send", by="agent", contact="Ana López", text="el menú", file=str(outbox / "menu.jpg"))
        photos = methods(api, "sendPhoto")
        check("FR-20: un JPEG de outbox/ sale con sendPhoto y su texto", r.get("ok") and len(photos) == 1
              and photos[0].get("caption") == "el menú" and photos[0].get("photo", {}).get("file_bytes") == len(JPEG),
              str(r))
        other = pathlib.Path(tempfile.mkdtemp()) / "secreto.txt"
        other.write_text("x")
        r = await call(s, "telegram.send", by="agent", contact="Ana López", text="x", file=str(other))
        check("FR-20: fuera de outbox/: not_allowed", r.get("code") == "not_allowed" and r.get("reason") == "file_dir")
        (outbox / "enlace.jpg").symlink_to(other)
        r = await call(s, "telegram.send", by="agent", contact="Ana López", text="x", file=str(outbox / "enlace.jpg"))
        check("FR-20: un enlace simbólico: not_allowed", r.get("code") == "not_allowed", str(r))
        r = await call(s, "telegram.send", by="web", contact="Ana López", text="x", file=str(outbox / "menu.jpg"))
        check("§4: la web nunca manda archivos", r.get("code") == "invalid" and r.get("field") == "file")

        # --- draft (FR-24) ------------------------------------------------------------------
        r = await call(s, "telegram.draft", contact="Ana López", text="Revisando tu pedido…")
        drafts = methods(api, "sendMessageDraft")
        check("FR-24: draft con sendMessageDraft", r.get("ok") and r["data"]["transport"] == "draft"
              and drafts and drafts[-1]["text"] == "Revisando tu pedido…" and int(drafts[-1]["draft_id"]) > 0, str(r))
        before = len(methods(api, "sendMessage"))
        await call(s, "telegram.send", contact="Ana López", text="Listo, tu pedido sale a las 9.")
        check("FR-24: el siguiente send manda el mensaje normal", len(methods(api, "sendMessage")) == before + 1)

        # --- stream (FR-22) -------------------------------------------------------------------
        r = await call(s, "telegram.stream_open", contact="Ana López")
        sid = r["data"]["stream"]
        d0 = len(methods(api, "sendMessageDraft"))
        for piece in ["Sí, ", "a las 8 tenemos lugar ", "para cuatro personas, ", "en la terraza."]:
            await call(s, "telegram.stream_append", by=None, stream=sid, text=piece)
            await asyncio.sleep(0.6)
        await asyncio.sleep(1.1)
        mid = methods(api, "sendMessageDraft")[d0:]
        check("FR-22: el texto se ve mientras se escribe (sendMessageDraft)", len(mid) >= 2
              and mid[-1]["text"] == "Sí, a las 8 tenemos lugar para cuatro personas, en la terraza.",
              str([m["text"] for m in mid]))
        before = len(methods(api, "sendMessage"))
        r = await call(s, "telegram.stream_close", by=None, stream=sid)
        final = methods(api, "sendMessage")[before:]
        check("FR-22: al cerrar queda como mensaje normal", r.get("ok") and r["data"]["transport"] == "draft"
              and len(final) == 1 and final[0]["text"].endswith("en la terraza."), str(r))
        r = await call(s, "telegram.stream_append", by=None, stream=sid, text="más")
        check("un stream cerrado: not_found", r.get("code") == "not_found")
        r = await call(s, "telegram.stream_open", contact="Ana López")
        sid = r["data"]["stream"]
        before = len(methods(api, "sendMessage"))
        await call(s, "telegram.stream_append", by=None, stream=sid, text="x" * 5000)
        await call(s, "telegram.stream_close", by=None, stream=sid)
        final = methods(api, "sendMessage")[before:]
        check("FR-22: más de 4096 en un stream sigue en un mensaje nuevo",
              [len(m["text"]) for m in final] == [4096, 904], str([len(m["text"]) for m in final]))

        # --- hilos (§4) -------------------------------------------------------------------------
        await call(s, "telegram.send", by="web", contact="Ana López", text="De parte del dueño")
        r = await call(s, "telegram.threads", by="web")
        rows = r["data"]["threads"]
        ana = next(x for x in rows if x["name"] == "Ana López")
        pedro = next(x for x in rows if x["in_roster"] is False)
        check("threads: Ana con su último mensaje y can_reply", ana["can_reply"] and ana["last_dir"] == "out"
              and ana["last_excerpt"] == "De parte del dueño", str(ana))
        check("threads: Pedro no verificado, oculto y sin extracto", pedro["hidden"] is True
              and pedro["last_excerpt"] is None and pedro["name"] == "Pedro (no verificado)", str(pedro))
        r = await call(s, "telegram.thread", by="web", thread=ana["thread"], limit=3)
        msgs = r["data"]["messages"]
        check("thread: del más reciente al más viejo, con next_before", len(msgs) == 3
              and msgs[0]["text"] == "De parte del dueño" and r["data"]["next_before"] == msgs[-1]["at"], str(msgs[:1]))
        check("thread: by es owner desde la web y agent desde la terminal",
              msgs[0]["by"] == "owner" and any(m.get("by") == "agent" for m in msgs[1:]))
        r = await call(s, "telegram.thread", by="web", thread=pedro["thread"])
        check("thread: fuera del roster sin Catch-All, vacío y hidden", r["data"]["messages"] == []
              and r["data"]["hidden"] is True)
        r = await call(s, "telegram.thread", by="web", contact="Ana López")
        check("thread por contact sólo desde la terminal o el agente", r.get("code") == "invalid")

        # --- telegram.image y watch ---------------------------------------------------------------
        reader, writer = await asyncio.open_unix_connection(str(s.socket_path))
        writer.write((json.dumps({"type": "telegram.watch", "id": q(), "by": "web"}) + "\n").encode())
        await writer.drain()
        first = json.loads(await reader.readline())
        api.private_message(ANA, None, first_name="Ana", photo=JPEG, caption="mi foto")
        changed = json.loads(await asyncio.wait_for(reader.readline(), 8))
        check("watch: result y luego telegram.changed sin datos", first.get("type") == "result"
              and changed == {"type": "telegram.changed", "what": "threads"}, str(changed))
        writer.close()
        await until(lambda: any(m.get("kind") == "image" for m in s.store.received()))
        img = next(m for m in s.store.received() if m.get("kind") == "image")
        r = await call(s, "telegram.image", by="web", ref=img["ref"])
        check("telegram.image: la foto de Ana", r.get("ok") and r["data"]["mime"] == "image/jpeg"
              and r["data"]["bytes"] == len(JPEG), str(r)[:200])
        r = await call(s, "telegram.image", by="web", ref="tg:" + "0" * 32)
        check("telegram.image: lo que no existe es not_found", r.get("code") == "not_found")

        # --- status y CLI ----------------------------------------------------------------------------
        st = s.status()["counters"]
        check("status: sent_today cuenta los mensajes finales", st["sent_today"] >= 8 and st["send_limit_day"] == 50,
              str(st))
        env = dict(os.environ, PAYNANI_STATE=str(state))
        before = len(methods(api, "sendMessage"))
        rc, out, err = await cli(env, "send", "Ana López", "desde", "la", "terminal")
        check("CLI: paynani telegram send", rc == 0 and "\tsent" in out
              and methods(api, "sendMessage")[before:][0]["text"] == "desde la terminal", err)
        before_photo = len(methods(api, "sendPhoto"))
        rc, out, err = await cli(env, "send", "Ana López", "--file", str(state / "telegram" / "outbox" / "menu.jpg"),
                                 "el", "menú")
        check("CLI: --file después del contacto y el texto después (hallazgo de TG-9)", rc == 0
              and methods(api, "sendPhoto")[before_photo:][0].get("caption") == "el menú", out + err)
        rc, out, err = await cli(env, "send", "Ana López", "hola", "--nada")
        check("CLI: una opción desconocida después del texto sigue siendo un error", rc == 2
              and "unrecognized arguments: --nada" in err, out + err)
        rc, out, err = await cli(env, "send", "Ana López", "--stream", stdin="hola por partes")
        check("CLI: send --stream lee stdin", rc == 0 and "\tdraft" in out, out + err)
        rc, out, err = await cli(env, "send", "Beto Ruiz", "hola")
        check("CLI: a quien no ha escrito sale con 2 y lo dice", rc == 2 and "not_started" in err, err)
        rc, out, err = await cli(env, "threads")
        check("CLI: threads lista a Ana y a Pedro oculto", rc == 0 and "Ana López" in out
              and "(oculto: fuera del roster)" in out, out + err)
        rc, out, err = await cli(env, "thread", "Ana López")
        check("CLI: thread muestra la conversación", rc == 0 and "desde la terminal" in out, err)

        # --- nada de ids ------------------------------------------------------------------------------
        r = await call(s, "telegram.threads", by="web")
        text = "\n".join(logs) + json.dumps(r) + json.dumps(s.status())
        check("ni ids ni token en el log, threads ni status", not any(i in text for i in IDS) and TOKEN not in text)
    finally:
        await s.stop()
        api.stop()


async def fallback_and_limit_tests():
    # Un chat que no acepta sendMessageDraft: el borrador y el stream editan un mensaje.
    state = pathlib.Path(tempfile.mkdtemp())
    api = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot", drafts=False).start()
    s = await service(state, api, [], TELEGRAM_SEND_PER_DAY="3")
    try:
        api.private_message(ANA, "hola", first_name="Ana")
        await until(lambda: s.store and s.store.threads())
        r = await call(s, "telegram.draft", contact="Ana López", text="Revisando…")
        first = methods(api, "sendMessage")
        check("FR-24 sin borradores: un mensaje que se edita", r.get("ok") and r["data"]["transport"] == "edit"
              and len(first) == 1 and first[0]["text"] == "Revisando…", str(r))
        await call(s, "telegram.send", contact="Ana López", text="Listo.")
        edits = methods(api, "editMessageText")
        check("FR-24 sin borradores: el send reemplaza ese mensaje", len(methods(api, "sendMessage")) == 1
              and edits and edits[-1]["text"] == "Listo.", str(edits))
        r = await call(s, "telegram.stream_open", contact="Ana López")
        sid = r["data"]["stream"]
        await call(s, "telegram.stream_append", by=None, stream=sid, text="Primera parte de la respuesta, ")
        await asyncio.sleep(1.3)
        await call(s, "telegram.stream_append", by=None, stream=sid, text="y la segunda.")
        r = await call(s, "telegram.stream_close", by=None, stream=sid)
        edits = methods(api, "editMessageText")
        check("FR-22 sin borradores: transport edit y el texto completo al final",
              r.get("ok") and r["data"]["transport"] == "edit"
              and edits[-1]["text"] == "Primera parte de la respuesta, y la segunda.", str(r))
        r = await call(s, "telegram.send", contact="Ana López", text="uno más")
        check("FR-26: el límite del día (3) incluye send y el final del stream", r.get("ok") is True, str(r))
        r = await call(s, "telegram.send", contact="Ana López", text="ya no")
        check("FR-26: pasando el límite del día: rate_limited con retry_after_s", r.get("code") == "rate_limited"
              and 0 < r.get("retry_after_s", 0) <= 86400, str(r))
        r = await call(s, "telegram.draft", contact="Ana López", text="un borrador sí")
        check("FR-24: un borrador no cuenta contra el límite", r.get("ok") is True, str(r))
    finally:
        await s.stop()
        api.stop()


ALEX1, ALEX2 = 7771234601, 7771234602
ROSTER_ALEX = """\
| Name | Email | Telegram | Type |
|---|---|---|---|
| Alex | alex.uno@example.com | %d | Human |
| Alex | alex.dos@example.com | %d | Human |
""" % (ALEX1, ALEX2)


async def review_619_tests():
    """Revisión de Ximena en #619: el cupo sólo cuenta lo que quedó en el chat, y un nombre repetido no manda."""
    state = pathlib.Path(tempfile.mkdtemp())
    api = FakeBotAPI(token=TOKEN, bot_id=BOT_ID, username="NegocioBot").start()
    s = await service(state, api, [], TELEGRAM_SEND_PER_DAY="3")
    (state / "roster.md").write_text(ROSTER_ALEX, encoding="utf-8")
    try:
        api.private_message(ALEX1, "hola, soy Alex uno", first_name="Alex")
        api.private_message(ALEX2, "hola, soy Alex dos", first_name="Alex")
        await until(lambda: s.store and len(s.store.threads()) == 2)
        before = len(methods(api, "sendMessage"))
        r = await call(s, "telegram.send", contact="Alex", text="¿cuál Alex?")
        check("#619: un nombre de dos filas no manda nada y pide el correo", r.get("code") == "conflict"
              and r.get("field") == "contact" and len(methods(api, "sendMessage")) == before, str(r))
        api.fail_next("sendMessage", 429, retry_after=1)
        api.fail_next("sendMessage", 429, retry_after=1)
        r = await call(s, "telegram.send", contact="alex.dos@example.com", text="no sale")
        check("#619: fallo total: rate_limited y el cupo no se gasta", r.get("code") == "rate_limited"
              and s.status()["counters"]["sent_today"] == 0, str(s.status()["counters"]))
        r = await call(s, "telegram.send", contact="alex.dos@example.com", text="para Alex dos")
        sm = methods(api, "sendMessage")
        check("#619: el correo desambigua y llega al Alex correcto", r.get("ok") and int(sm[-1]["chat_id"]) == ALEX2
              and sm[-1]["text"] == "para Alex dos", str(r))
        outbox = state / "telegram" / "outbox"
        outbox.mkdir(mode=0o700, exist_ok=True)
        (outbox / "foto.jpg").write_bytes(JPEG)
        api.fail_next("sendMessage", 429, retry_after=1)
        api.fail_next("sendMessage", 429, retry_after=1)
        r = await call(s, "telegram.send", by="agent", contact="alex.uno@example.com", text="t" * 1500,
                       file=str(outbox / "foto.jpg"))
        check("#619: fallo parcial: sólo cuenta el archivo que sí salió", r.get("code") == "rate_limited"
              and len(methods(api, "sendPhoto")) == 1 and s.status()["counters"]["sent_today"] == 2,
              str(s.status()["counters"]))
        partial = [x for x in s.store.sent() if x.get("status") == "partial"]
        check("#619: el envío queda como partial, con lo que salió", len(partial) == 1
              and partial[0]["delivered"] == 1 and partial[0]["parts"] == 2, str(partial))

        # Medianoche UTC: A reserva el día 1, B el día 2, A devuelve tarde; B sigue contado.
        real_today = outbound._today
        day = ["2026-10-31"]
        outbound._today = lambda: day[0]
        try:
            (state / "telegram" / "rate.json").unlink(missing_ok=True)
            a_day = await s._reserve(1)
            day[0] = "2026-11-01"
            b_day = await s._reserve(1)
            await s._release(1, a_day)
            check("#619: la devolución de una reserva de ayer no resta del cupo de hoy",
                  (a_day, b_day, s._sent_today()) == ("2026-10-31", "2026-11-01", 1), str(s._sent_today()))
            await s._release(1, b_day)
            check("#619: la devolución del mismo día sí resta", s._sent_today() == 0)
        finally:
            outbound._today = real_today
    finally:
        await s.stop()
        api.stop()


def unit_tests():
    parts = outbound.split_text("a" * 5000)
    check("split_text: 4096 + resto", [len(p) for p in parts] == [4096, 904])
    parts = outbound.split_text("uno dos\n" * 600)
    check("split_text: corta en salto de línea", all(len(p) <= 4096 for p in parts) and parts[0].endswith("dos"))
    check("author: web y teléfono son owner; api es api",
          (outbound.author("web"), outbound.author("phone:d_1"), outbound.author("api"), outbound.author("terminal"))
          == ("owner", "owner", "api", "agent"))


def main():
    unit_tests()
    asyncio.run(main_tests())
    asyncio.run(fallback_and_limit_tests())
    asyncio.run(review_619_tests())
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
