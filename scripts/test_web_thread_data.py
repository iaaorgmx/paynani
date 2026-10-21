#!/usr/bin/env python3
"""
Tests for reading a whole mail thread in PaynaniWeb (PRD #455 4.3; T1 of #456).
An assertion script, like the rest of this suite.

`thread.load()` lee cada mensaje del hilo con una sola conexión por cuenta: los
recibidos de su buzón y los enviados de Enviados, de solo lectura y con
`BODY.PEEK[]`. Un mensaje que no se puede leer trae su razón y el resto sale igual.
Todo con un IMAP de prueba que anota lo que se le pidió.
"""
from __future__ import annotations

import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.web import mail, thread  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def raw(sender, mid, subject, text):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "agente@example.com"
    m["Subject"] = subject
    m["Message-ID"] = mid
    m["Date"] = "Tue, 20 Oct 2026 10:00:00 +0000"
    m.set_content(text)
    return m.as_bytes()


class FakeIMAP:
    """Buzones de prueba. Anota cada orden; `boxes` es {buzón: {uid: bytes}}."""
    log: list = []
    connections = 0
    boxes: dict = {}
    listing = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Otra"', b'(\\HasNoChildren \\Sent) "/" "Enviados"']
    fail_select: set = set()

    def __init__(self, env):
        FakeIMAP.connections += 1
        self.selected = None

    def list(self):
        FakeIMAP.log.append(("list",))
        return "OK", list(FakeIMAP.listing)

    def select(self, mailbox, readonly=False):
        FakeIMAP.log.append(("select", mailbox, readonly))
        if mailbox in FakeIMAP.fail_select:
            raise OSError("se cayó")
        name = mailbox.strip('"')
        if name not in FakeIMAP.boxes or not readonly:
            return "NO", [b""]
        self.selected = name
        return "OK", [b"1"]

    def uid(self, command, *args):
        FakeIMAP.log.append(("uid", command, *args))
        box = FakeIMAP.boxes.get(self.selected, {})
        if command == "search":
            mid = args[-1]
            hits = [u for u, data in box.items() if f"Message-ID: {mid}".encode() in data]
            return "OK", [" ".join(hits).encode()]
        if command == "fetch":
            uids, query = args
            out = []
            for u in uids.split(","):
                if u in box:
                    out += [(f"{len(out) + 1} (UID {u} BODY[] {{{len(box[u])}}}".encode(), box[u]), b")"]
            return "OK", out
        return "NO", [b""]

    def logout(self):
        FakeIMAP.log.append(("logout",))


def reset():
    FakeIMAP.log = []
    FakeIMAP.connections = 0
    FakeIMAP.fail_select = set()
    FakeIMAP.boxes = {
        "INBOX": {"1": raw("Ana <ana@example.com>", "<a1@example.com>", "Cotización", "¿Me cotizan 40 mesas?"),
                  "2": raw("Ana <ana@example.com>", "<a2@example.com>", "Re: Cotización", "¿Y 50?")},
        "Otra": {"5": raw("Ana <ana@example.com>", "<a5@example.com>", "Re: Cotización", "Desde otra carpeta")},
        "Enviados": {"9": raw("agente@example.com", "<r1@agente.example>", "Re: Cotización", "Sí, Ana: 40 mesas.")},
    }


ENV = {"AGENT_EMAIL_ACCOUNT": "agente@example.com", "AGENT_EMAIL_PASSWORD": "x",
       "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": "imap.example.com"}


def received(uid, mid, box="INBOX", validity="7", sender="ana@example.com", account="agente@example.com"):
    return {"kind": "in", "event_id": f"imap:{box}:{validity}:{uid}", "at": f"2026-10-20T10:0{uid}:00Z",
            "envelope": {"account": account, "mailbox": box, "uidvalidity": validity, "uid": uid,
                         "sender": {"address": sender}, "message_id": mid}}


def sent(mid):
    return {"kind": "out", "message_id": mid, "at": "2026-10-20T10:30:00Z"}


def validity(conn, box):
    return "7"


# --- un hilo de recibidos en dos buzones y enviados, con una sola conexión -------------------
reset()
convo = [received("1", "<a1@example.com>"), sent("<r1@agente.example>"), received("2", "<a2@example.com>"),
         received("5", "<a5@example.com>", box="Otra"), sent("<sin-copia@agente.example>")]
got = thread.load(ENV, convo, connect=FakeIMAP, uidvalidity=validity)
check("una sola conexión para los cinco", 1, FakeIMAP.connections)
check("un resultado por mensaje, con su clave", sorted(thread.key(r) for r in convo), sorted(got))
check("los recibidos traen su cuerpo completo", ("¿Me cotizan 40 mesas?", "¿Y 50?", "Desde otra carpeta"),
      tuple(got[thread.key(convo[i])]["message"]["text"].strip() for i in (0, 2, 3)))
check("el enviado con copia trae su cuerpo, de Enviados", "Sí, Ana: 40 mesas.",
      got["s:<r1@agente.example>"]["message"]["text"].strip())
check("el enviado sin copia trae su razón, no_copy", "no_copy", got["s:<sin-copia@agente.example>"]["error"].code)
selects = [e[1] for e in FakeIMAP.log if e[0] == "select"]
check("un SELECT por buzón: INBOX, Otra y Enviados", ["INBOX", "Otra", '"Enviados"'], selects)
check("todos de solo lectura", True, all(e[2] for e in FakeIMAP.log if e[0] == "select"))
fetches = [e for e in FakeIMAP.log if e[:2] == ("uid", "fetch")]
check("un UID FETCH por buzón, con los UID juntos", [("1,2", "(BODY.PEEK[])"), ("5", "(BODY.PEEK[])"), ("9", "(BODY.PEEK[])")],
      [e[2:] for e in fetches])
check("solo BODY.PEEK[]: nada queda leído", True, all(e[3] == "(BODY.PEEK[])" for e in fetches))
check("ni STORE, ni COPY, ni MOVE, ni EXPUNGE", [], [e for e in FakeIMAP.log if e[0] == "uid" and e[1] not in ("fetch", "search")])
check("y cierra la sesión", ("logout",), FakeIMAP.log[-1])

# --- uno que no se puede leer no tumba el resto -----------------------------------------------
reset()
convo = [received("1", "<a1@example.com>"), received("2", "<a2@example.com>", validity="8"),
         received("3", "<a3@example.com>"), received("1", "<a1@example.com>", sender="otro@example.com"),
         received("x", "<ax@example.com>"), received("2", "<a2@example.com>", account="otra@example.com")]
convo[3]["event_id"] += ":otro"
convo[5]["event_id"] += ":cuenta"
got = thread.load(ENV, convo, connect=FakeIMAP, uidvalidity=validity)
check("cada uno con su razón: uidvalidity, gone (ya no está), from, nouid, account",
      ["uidvalidity", "gone", "from", "nouid", "account"],
      [got[thread.key(convo[i])]["error"].code for i in (1, 2, 3, 4, 5)])
check("... y el bueno sale igual", "¿Me cotizan 40 mesas?", got[thread.key(convo[0])]["message"]["text"].strip())
check("el que trae otro Message-ID que el del sobre: mid", "mid",
      thread.load(ENV, [received("1", "<otro@example.com>")], connect=FakeIMAP, uidvalidity=validity)
      ["imap:INBOX:7:1"]["error"].code)

reset()
FakeIMAP.boxes.pop("Otra")
got = thread.load(ENV, [received("5", "<a5@example.com>", box="Otra"), received("1", "<a1@example.com>")],
                  connect=FakeIMAP, uidvalidity=validity)
check("un buzón que ya no existe: mailbox, y el otro buzón sale", ("mailbox", True),
      (got["imap:Otra:7:5"]["error"].code, "message" in got["imap:INBOX:7:1"]))

reset()
FakeIMAP.listing = [b'(\\HasNoChildren) "/" "INBOX"']
got = thread.load(ENV, [sent("<r1@agente.example>"), received("1", "<a1@example.com>")], connect=FakeIMAP, uidvalidity=validity)
check("sin carpeta de Enviados: no_sent en el enviado, el recibido sale", ("no_sent", True),
      (got["s:<r1@agente.example>"]["error"].code, "message" in got["imap:INBOX:7:1"]))
FakeIMAP.listing = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Otra"', b'(\\HasNoChildren \\Sent) "/" "Enviados"']

reset()
FakeIMAP.fail_select = {'"Enviados"'}
got = thread.load(ENV, [received("1", "<a1@example.com>"), sent("<r1@agente.example>")], connect=FakeIMAP, uidvalidity=validity)
check("si el servidor se cae a mitad: lo leído se queda, lo demás trae connect", (True, "connect"),
      ("message" in got["imap:INBOX:7:1"], got["s:<r1@agente.example>"]["error"].code))
check("... y aun así cierra la sesión", ("logout",), FakeIMAP.log[-1])


def no_network(env):
    raise OSError("sin red")


def bad_login(env):
    raise SystemExit(2)


convo = [received("1", "<a1@example.com>"), sent("<r1@agente.example>")]
check("sin red: todos con connect y el tipo de error", [("connect", "OSError")] * 2,
      [(v["error"].code, v["error"].detail) for v in thread.load(ENV, convo, connect=no_network, uidvalidity=validity).values()])
check("con el login rechazado: todos con login", ["login", "login"],
      [v["error"].code for v in thread.load(ENV, convo, connect=bad_login, uidvalidity=validity).values()])
reset()
check("un hilo vacío no conecta", ({}, 0), (thread.load(ENV, [], connect=FakeIMAP, uidvalidity=validity), FakeIMAP.connections))

# --- 50 mensajes: los mismos viajes que con 5 ---------------------------------------------------
reset()
FakeIMAP.boxes["INBOX"] = {str(u): raw("Ana <ana@example.com>", f"<m{u}@example.com>", "Re: Cotización", f"mensaje {u}")
                           for u in range(1, 46)}
FakeIMAP.boxes["Enviados"] = {str(u): raw("agente@example.com", f"<s{u}@agente.example>", "Re: Cotización", f"envío {u}")
                              for u in range(1, 6)}
convo = [received(str(u), f"<m{u}@example.com>") for u in range(1, 46)] + [sent(f"<s{u}@agente.example>") for u in range(1, 6)]
got = thread.load(ENV, convo, connect=FakeIMAP, uidvalidity=validity)
check("50 mensajes: los 50 con cuerpo", 50, sum("message" in v for v in got.values()))
check("... una conexión, dos SELECT y dos UID FETCH", (1, 2, 2),
      (FakeIMAP.connections, sum(e[0] == "select" for e in FakeIMAP.log), sum(e[:2] == ("uid", "fetch") for e in FakeIMAP.log)))
check("... y un SEARCH por cada enviado, nada más", 5, sum(e[:2] == ("uid", "search") for e in FakeIMAP.log))

# --- mail.fetch sigue igual (verify y message_dict son las mismas piezas) -----------------
reset()
one = mail.fetch(received("1", "<a1@example.com>")["envelope"], ENV, connect=FakeIMAP, uidvalidity=validity)
check("mail.fetch: el mismo cuerpo y Message-ID", ("¿Me cotizan 40 mesas?", "<a1@example.com>"),
      (one["text"].strip(), one["message_id"]))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
