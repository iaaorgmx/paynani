#!/usr/bin/env python3
"""
Tests for Webchat from PaynaniApp through the SMS gateway (SMS_GATEWAY.md §13, PRD #653
FR-1 to FR-6). An assertion script, like the rest of this suite.

Levanta una pasarela en un puerto libre con un usuario de PaynaniWeb falso, empareja un
teléfono y hace de app por WebSocket y por HTTP. El almacén es el real, en una carpeta
temporal. Nada sale de la máquina.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import gateway as gw  # noqa: E402
from paynani_lib.sms import store as store_mod  # noqa: E402
from paynani_lib.sms import webchat_api  # noqa: E402
from paynani_lib.webchat import store  # noqa: E402
from test_whatsapp_relay import SIM, connect, http, qid, until  # noqa: E402

WC_TYPES = ["webchat.thread", "webchat.send"]
OWNER = {"name": "Dueña Prueba", "email": "duena@example.com"}
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00"
       b"\x00\x00IEND\xaeB`\x82")

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


async def raw_http(port, method, path, *, token=None, body=b"", content_type=None, length=None):
    """(status, headers, cuerpo) de una petición HTTP cualquiera."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    head = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1",
            f"Content-Length: {len(body) if length is None else length}"]
    if token:
        head.append(f"Authorization: Bearer {token}")
    if content_type:
        head.append(f"Content-Type: {content_type}")
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    top, _, payload = raw.partition(b"\r\n\r\n")
    lines = top.decode("latin-1").split("\r\n")
    headers = {k.strip().lower(): v.strip() for k, v in (x.split(":", 1) for x in lines[1:] if ":" in x)}
    return int(lines[0].split(" ")[1]), headers, payload


def multipart(name: str, data: bytes, field: str = "file") -> tuple[bytes, str]:
    boundary = "----b" + secrets.token_hex(8)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


async def upload(port, token, name, data):
    body, ctype = multipart(name, data)
    status, _h, payload = await raw_http(port, "POST", "/sms/webchat/upload", token=token, body=body,
                                         content_type=ctype)
    return status, json.loads(payload or b"{}")


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    roster = tmp / "roster.md"
    roster.write_text("# roster\n", encoding="utf-8")
    logged: list[str] = []
    gw.log = logged.append

    owner = [None]
    clock = [1_000_000.0]
    relay = webchat_api.WebchatRelay(state, owner=lambda: owner[0], agent_name=lambda: "Metis",
                                     log=gw.log, clock=lambda: clock[0], watch_s=0.05)
    g = gw.Gateway(state, state / "events.jsonl", roster, public_url="https://ejemplo.ngrok.io",
                   heartbeat_s=30, whatsapp_check_s=0.1, webchat=relay)
    server = await gw.serve(g, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    code = store_mod.Store(state).new_code()
    status, body = await http(port, "POST", "/sms/pair", {"code": code, "device": {"model": "Pixel"},
                                                          "sims": [{"slot": 0, "number": SIM}]})
    check("pair -> 201", 201, status)
    token, device_id = body["token"], body["device_id"]
    try:
        # --- FR-1: sin usuario de PaynaniWeb no se anuncia ------------------------------
        app, welcome = await connect(port, token, device_id)
        check("sin usuario: sin tipos webchat.*", [], [t for t in welcome.get("accepts", []) if t.startswith("webchat.")])
        check("sin usuario: sin webchat.owner", False, "webchat.owner" in (welcome.get("grants") or []))
        r = await app.ask("webchat.thread")
        check("sin usuario: webchat.thread -> forbidden", "forbidden", r.get("code"))
        status, _h, _b = await raw_http(port, "GET", "/sms/webchat/file?ref=f_" + "0" * 32, token=token)
        check("sin usuario: GET file -> 403", 403, status)

        owner[0] = OWNER
        check("al crear el usuario la pasarela cierra con 1012", True,
              await until(lambda: app.closed_code == 1012, timeout=3))
        app, welcome = await connect(port, token, device_id)
        check("con usuario: los dos tipos en accepts", True, all(t in welcome.get("accepts", []) for t in WC_TYPES))
        check("con usuario: el grant webchat.owner", True, "webchat.owner" in (welcome.get("grants") or []))

        # --- FR-3: la conversación vacía --------------------------------------------------
        r = await app.ask("webchat.thread")
        data = r.get("data") or {}
        check("thread vacío: result, sin mensajes, agente Metis", ("result", [], "Metis", None, False, None),
              (r.get("type"), data.get("messages"), data.get("agent"), data.get("next_before"),
               data.get("typing"), data.get("draft")))

        # --- FR-2 y FR-4: mandar texto -------------------------------------------------------
        events_before = len((state / "events.jsonl").read_text().splitlines()) if (state / "events.jsonl").exists() else 0
        send_id = qid()
        r = await app.ask("webchat.send", rid=send_id, text="  Hola desde el teléfono  ")
        msg = (r.get("data") or {}).get("message") or {}
        check("send: result con el mensaje del dueño", ("result", "in", "owner", "Hola desde el teléfono"),
              (r.get("type"), msg.get("dir"), msg.get("by"), msg.get("text")))
        check("send: sin event_id ni campos internos", False, "event_id" in msg)
        lines = (state / "events.jsonl").read_text().splitlines()
        envelope = json.loads(lines[-1]) if len(lines) > events_before else {}
        check("send: escribe webchat.received", "webchat.received", envelope.get("event_type"))
        check("el aviso dice (PaynaniApp)", True, "(PaynaniApp)" in envelope.get("notification_text", ""))
        check("con el nombre del dueño", True, "Dueña Prueba" in envelope.get("notification_text", ""))
        r2 = await app.ask("webchat.send", rid=send_id, text="  Hola desde el teléfono  ")
        check("reenvío con el mismo id: mismo result, replayed", ("result", True, msg.get("id")),
              (r2.get("type"), r2.get("replayed"), ((r2.get("data") or {}).get("message") or {}).get("id")))
        check("el reenvío no guarda otro", 1, len(store.messages(limit=100, state_dir=state)))
        r3 = await app.ask("webchat.send", rid=send_id, text="otro")
        check("mismo id con otro cuerpo: invalid id_reused", ("invalid", "id_reused"), (r3.get("code"), r3.get("reason")))
        r = await app.ask("webchat.send", text="   ")
        check("vacío: empty", "empty", r.get("code"))
        r = await app.ask("webchat.send", text="x" * 4001)
        check("4001 caracteres: too_long", "too_long", r.get("code"))
        store.append("owner", "desde la web", [], owner=OWNER, state_dir=state)
        last = json.loads((state / "events.jsonl").read_text().splitlines()[-1])
        check("la web sigue diciendo (PaynaniWeb)", True, "(PaynaniWeb)" in last.get("notification_text", ""))

        # --- FR-6: avisos sin pedir thread -------------------------------------------------
        app.notices.clear()
        store.append("agent", "Te contesto", [], state_dir=state)
        n = await app.notice("webchat.changed")
        check("respuesta del agente: webchat.changed messages, sin contenido", {"type": "webchat.changed", "what": "messages"}, n)
        store.typing(30, state_dir=state)
        n = await app.notice("webchat.changed")
        check("typing: el aviso con typing true", ("typing", True), ((n or {}).get("what"), (n or {}).get("typing")))
        app.notices.clear()
        store.draft_set("Voy escribiendo", state_dir=state)
        n = None
        for _ in range(3):
            n = await app.notice("webchat.changed")
            if (n or {}).get("what") == "draft":
                break
        check("draft: el aviso trae el texto", "Voy escribiendo", ((n or {}).get("draft") or {}).get("text"))
        r = await app.ask("webchat.thread")
        check("thread trae el borrador y typing", ("Voy escribiendo", True),
              (((r.get("data") or {}).get("draft") or {}).get("text"), (r.get("data") or {}).get("typing")))
        store.draft_clear(state_dir=state)
        store.typing_off(state_dir=state)

        # --- FR-3: paginación --------------------------------------------------------------
        for i in range(5):
            store.append("agent", f"m{i}", [], state_dir=state)
        allm = store.messages(limit=100, state_dir=state)
        r = await app.ask("webchat.thread", limit=3)
        page = (r.get("data") or {}).get("messages") or []
        check("limit 3: los 3 últimos, del más viejo al más nuevo", ["m2", "m3", "m4"], [m["text"] for m in page])
        nb = (r.get("data") or {}).get("next_before")
        check("next_before es el primero de la página", page[0]["id"] if page else None, nb)
        r = await app.ask("webchat.thread", limit=100, before=nb)
        older = (r.get("data") or {}).get("messages") or []
        check("before: los anteriores, sin más páginas", (len(allm) - 3, None),
              (len(older), (r.get("data") or {}).get("next_before")))
        r = await app.ask("webchat.thread", after=allm[-3]["id"])
        check("after: sólo los posteriores", ["m3", "m4"], [m["text"] for m in (r.get("data") or {}).get("messages") or []])
        r = await app.ask("webchat.thread", after="w_" + "0" * 32)
        check("after desconocido: not_found", "not_found", r.get("code"))
        r = await app.ask("webchat.thread", after=allm[0]["id"], before=allm[1]["id"])
        check("before y after juntos: invalid", "invalid", r.get("code"))
        r = await app.ask("webchat.thread", limit=0)
        check("limit 0: invalid", ("invalid", "limit"), (r.get("code"), r.get("field")))

        # --- FR-5: subir y mandar archivos ----------------------------------------------------
        status, up = await upload(port, token, "foto.png", PNG)
        check("upload: 201, up_ y kind image", (201, True, "image", len(PNG)),
              (status, str(up.get("upload", "")).startswith("up_"), up.get("kind"), up.get("size")))
        check("la subida vive en uploads/, fuera de files/", True,
              (store.root(state) / "uploads" / up["upload"]).is_file())
        status, _h, _b = await raw_http(port, "GET", "/sms/webchat/file?ref=" + up["upload"], token=token)
        check("un up_ no se puede descargar", 404, status)
        status, bad = await upload(port, token, "mentira.pdf", PNG)
        check("upload de un PNG llamado .pdf: 400 bad_type", (400, "bad_type"), (status, bad.get("error")))
        status, _h, _b = await raw_http(port, "POST", "/sms/webchat/upload", token="otro", body=b"x",
                                        content_type="multipart/form-data; boundary=x")
        check("upload con otro token: 401", 401, status)
        status, _h, _b = await raw_http(port, "POST", "/sms/webchat/upload", token=token, length=30 * 1024 * 1024,
                                        content_type="multipart/form-data; boundary=x")
        check("upload de más de 20 MB: 413 sin leer el cuerpo", 413, status)

        r = await app.ask("webchat.send", text="la foto", uploads=[up["upload"]])
        msg = (r.get("data") or {}).get("message") or {}
        files = msg.get("files") or []
        check("send con upload: el archivo en el mensaje", ("result", ["foto.png"], True),
              (r.get("type"), [f.get("name") for f in files], str(files[0].get("ref", "")).startswith("f_") if files else False))
        check("el up_ se consumió", False, (store.root(state) / "uploads" / up["upload"]).exists())
        r = await app.ask("webchat.send", text="otra vez", uploads=[up["upload"]])
        check("el mismo up_ en otro mensaje: bad_upload", "bad_upload", r.get("code"))

        status, headers, payload = await raw_http(port, "GET", "/sms/webchat/file?ref=" + files[0]["ref"], token=token)
        check("GET file: 200 y los bytes", (200, PNG), (status, payload))
        check("GET file: tipo, nosniff y no-store", ("image/png", "nosniff", "private, no-store"),
              (headers.get("content-type"), headers.get("x-content-type-options"), headers.get("cache-control")))
        check("GET file: la foto inline", True, headers.get("content-disposition", "").startswith("inline"))
        check("GET file: CSP sandbox", True, "sandbox" in headers.get("content-security-policy", ""))
        status, _h, _b = await raw_http(port, "GET", "/sms/webchat/file?ref=" + files[0]["ref"])
        check("GET file sin token: 401", 401, status)
        status, _h, _b = await raw_http(port, "GET", "/sms/webchat/file?ref=../device.json", token=token)
        check("GET file con un ref inválido: 404", 404, status)

        # Un documento se descarga como octet-stream.
        status, upd = await upload(port, token, "lista.txt", b"pan\nleche\n")
        r = await app.ask("webchat.send", text="", uploads=[upd["upload"]])
        doc = (((r.get("data") or {}).get("message") or {}).get("files") or [{}])[0]
        status, headers, payload = await raw_http(port, "GET", "/sms/webchat/file?ref=" + doc.get("ref", ""), token=token)
        check("documento: octet-stream y attachment", (200, "application/octet-stream", True),
              (status, headers.get("content-type"), headers.get("content-disposition", "").startswith("attachment")))

        # Dos envíos a la vez con el mismo up_ y distinto id: sólo uno lo usa.
        status, upr = await upload(port, token, "carrera.png", PNG)
        ra, rb = await asyncio.gather(app.ask("webchat.send", text="a", uploads=[upr["upload"]]),
                                      app.ask("webchat.send", text="b", uploads=[upr["upload"]]))
        check("mismo up_ a la vez: uno result y otro bad_upload", ["bad_upload", "result"],
              sorted([ra.get("type") if ra.get("type") == "result" else ra.get("code"),
                      rb.get("type") if rb.get("type") == "result" else rb.get("code")]))

        # Un up_ que falla al mandar sigue vigente; uno vencido ya no.
        status, up2 = await upload(port, token, "nota.txt", b"hola")
        r = await app.ask("webchat.send", text="x" * 4001, uploads=[up2["upload"]])
        check("send que falla (too_long) no consume el up_", ("too_long", True),
              (r.get("code"), (store.root(state) / "uploads" / up2["upload"]).is_file()))
        clock[0] += webchat_api.UPLOAD_TTL_S + 1
        r = await app.ask("webchat.send", text="ya", uploads=[up2["upload"]])
        check("un up_ vencido: bad_upload", "bad_upload", r.get("code"))
        check("sweep lo borra", (1, False), (relay.sweep(), (store.root(state) / "uploads" / up2["upload"]).exists()))

        # --- tope por minuto ----------------------------------------------------------------
        clock[0] += 120
        codes = []
        for i in range(webchat_api.RATE_MAX + 1):
            r = await app.ask("webchat.send", text=f"r{i}")
            codes.append(r.get("type") if r.get("type") == "result" else r.get("code"))
        check("20 por minuto y el 21 rate_limited con retry_after_s", (["result"] * 20, "rate_limited"),
              (codes[:20], codes[20]))
        clock[0] += 61
        r = await app.ask("webchat.send", text="después del minuto")
        check("pasado el minuto vuelve a guardar", "result", r.get("type"))

        # --- el log no lleva textos ----------------------------------------------------------
        joined = "\n".join(logged)
        check("el log no trae el texto ni el nombre del archivo", (False, False),
              ("Hola desde el teléfono" in joined, "foto.png" in joined))

        owner[0] = None
        check("al borrar el usuario la pasarela cierra con 1012", True,
              await until(lambda: app.closed_code == 1012, timeout=3))
    finally:
        await g.shutdown()
        server.close()


asyncio.run(main())
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
