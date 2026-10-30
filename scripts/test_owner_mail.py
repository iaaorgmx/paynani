#!/usr/bin/env python3
"""
Tests for `paynani_lib/owner_mail.py`: mail the owner writes from PaynaniWeb (#591 N1).

Nothing is sent: himalaya is faked and writes down what it was given. What is
held in every case: a send needs a grant from `authorize()`, used once, within
60 s, for exactly what was authorized; `send.sh` still refuses anyone outside the
roster; and no record keeps the subject or the body.
"""

import atexit
import copy
import json
import os
import pathlib
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

passed = failed = 0


def check(desc, condition, detail=""):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}")
        if detail:
            print(f"     {detail}")
        failed += 1


TMP = pathlib.Path(tempfile.mkdtemp(prefix="paynani-owner-mail."))
atexit.register(shutil.rmtree, TMP, True)
(TMP / "bin").mkdir()
(TMP / "rosters").mkdir()
STATE = TMP / "state"
HLOG = TMP / "himalaya.log"
MSGS = TMP / "messages"
MSGS.mkdir()
ROSTER = TMP / "roster.md"
ROSTER.write_text("| Name | Email | Type |\n|---|---|---|\n"
                  "| Dueño | dueno@dominio.test | Human |\n"
                  "| Ana | Ana@Ejemplo.TEST | Human |\n")
(TMP / "rosters" / "ventas.md").write_text("| Name | Email | Type |\n|---|---|---|\n| Leo | leo@cliente.test | Human |\n")
ENV = TMP / ".env"
ENV.write_text("PAYNANI_EMAIL=agente@dominio.test\nPAYNANI_FROM_NAME=Agente Niño\n")
(TMP / "accounts.json").write_text(json.dumps({"version": 1, "accounts": [{
    "id": "ventas", "email": "ventas@dominio.test", "from_name": "Ventas",
    "imap": {"host": "mail.dominio.test", "port": 993}, "smtp": {"host": "mail.dominio.test", "port": 465},
    "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD", "roster": "rosters/ventas.md",
    "mailboxes": ["INBOX"], "enabled": True}]}))
HCONF = TMP / "himalaya.toml"
HCONF.write_text("[accounts.paynani.smtp]\nhost = \"smtp.dominio.test\"\n"
                 "[accounts.paynani-ventas.smtp]\nhost = \"smtp.dominio.test\"\n")
FAKE = TMP / "bin" / "himalaya"
FAKE.write_text(f"""#!/usr/bin/env bash
if [ "$1" = "--version" ]; then echo 'himalaya v2.1.0'; exit 0; fi
if [ -f {TMP}/himalaya.fail ]; then echo 'smtp: connection refused' >&2; exit 1; fi
printf '%s\\n' "$*" >> {HLOG}
cat > "$(mktemp {MSGS}/m.XXXXXX)"
exit 0
""")
FAKE.chmod(0o755)
os.environ.update(PATH=f"{TMP / 'bin'}:{os.environ['PATH']}", ROSTER=str(ROSTER), ENV_FILE=str(ENV),
                  PAYNANI_STATE=str(STATE), HIMALAYA_CONFIG=str(HCONF))

from paynani_lib import owner_mail as om  # noqa: E402

SUBJECT = "Asunto secreto 7Q"
BODY = "Cuerpo secreto 9Z\n"


def calls():
    return HLOG.read_text().splitlines() if HLOG.exists() else []


def reset():
    HLOG.unlink(missing_ok=True)
    for f in MSGS.iterdir():
        f.unlink()


def messages():
    return [f.read_text() for f in sorted(MSGS.iterdir(), key=lambda f: f.stat().st_mtime_ns)]


# --- canonical form -----------------------------------------------------------------
check("canonical: case, spaces, IDNA", om.canonical(" Ana@Ejemplo.TEST ") == "ana@ejemplo.test"
      and om.canonical("x@ñandú.test") == "x@xn--and-6ma2c.test")
for bad in ("", "a", "a@b", "a@@b.test", "a@b.test, c@d.test", "Ana <a@b.test>", "a@b.test\nBcc: x@y.test",
            "a@.test", "a@b.test.", "../a@b.test/../"):
    check(f"canonical refuses {bad!r}", not om.valid_address(bad))
check("outside_roster: roster address in another case is inside",
      om.outside_roster(None, ["ANA@ejemplo.test", "x@fuera.test", "X@Fuera.test"]) == ["x@fuera.test"])
check("outside_roster: account roster, not roster.md",
      om.outside_roster("ventas", ["leo@cliente.test", "ana@ejemplo.test"]) == ["ana@ejemplo.test"])
try:
    om.authorize("nadie", ["ana@ejemplo.test"], [], [], by="t")
    check("authorize: unknown account raises", False)
except om.UnknownAccount:
    check("authorize: unknown account raises", True)

# --- a send inside the roster ----------------------------------------------------------
reset()
g = om.authorize(None, ["ana@ejemplo.test"], ["dueno@dominio.test"], ["Ana@Ejemplo.test", "x@fuera.test"], by="web:t",
                 owner_email="Dueno@Dominio.test", allow_outside=True)
check("authorize: repeats removed across To/Cc/Bcc", g.to == ("ana@ejemplo.test",) and g.cc == ("dueno@dominio.test",)
      and g.bcc == ("x@fuera.test",))
r = om.send(g, SUBJECT, BODY)
check("send: ok with outside address", r.ok and r.code == "sent" and r.outside_roster == ["x@fuera.test"], r)
c = calls()
check("send: envelope has everyone, from the agent", c and "-a paynani smtp send --mail-from agente@dominio.test" in c[0]
      and all(f"--rcpt-to {a}" in c[0] for a in ("ana@ejemplo.test", "dueno@dominio.test", "x@fuera.test")), c)
m = messages()
check("send: Bcc not in the headers", m and "x@fuera.test" not in m[0].split("\n\n", 1)[0], m[:1])
check("send: From name encoded, plain subject kept", m and "From: =?utf-8?" in m[0] and f"Subject: {SUBJECT}" in m[0]
      and BODY in m[0], m[:1])
check("send: notice went to the owner through send.sh", r.notice == "sent" and len(c) == 2
      and "--rcpt-to dueno@dominio.test" in c[1], c)
check("notice: no subject or body", len(m) == 2 and "secreto" not in m[1] and "x@fuera.test" in m[1], m[1:])
check("send: sent copy skipped without IMAP", r.sent_copy == "skipped", r)
sent = (STATE / "sent.log").read_text().splitlines()
check("send: sent.log line with the Message-ID", any(r.message_id in l for l in sent), sent)

# --- the grant -----------------------------------------------------------------------
reset()
r2 = om.send(g, SUBJECT, BODY)
check("replay: second use refused, nothing sent", not r2.ok and r2.code == "not_authorized" and not calls(), r2)

g = om.authorize(None, ["ana@ejemplo.test"], [], [], by="t", now=1000.0)
r = om.send(g, SUBJECT, BODY, now=1000.0 + om.GRANT_TTL + 1)
check("expired grant refused", r.code == "not_authorized" and "expired" in r.detail and not calls(), r)

g = om.authorize(None, ["ana@ejemplo.test"], [], [], by="t")
try:
    g.bcc = ("x@fuera.test",)
    check("grant cannot be changed", False)
except AttributeError:
    check("grant cannot be changed", True)
for name, attempt in (("pickled", lambda: pickle.dumps(g)), ("copied", lambda: copy.copy(g)),
                      ("deep-copied", lambda: copy.deepcopy(g))):
    try:
        attempt()
        check(f"grant cannot be {name}", False)
    except TypeError:
        check(f"grant cannot be {name}", True)
check("grant repr shows no addresses or token", "ana@" not in repr(g) and g._token not in repr(g))
object.__setattr__(g, "bcc", ("x@fuera.test",))
r = om.send(g, SUBJECT, BODY)
check("grant forced to other recipients refused", r.code == "not_authorized" and not calls(), r)
object.__setattr__(g, "bcc", ())
r = om.send(g, SUBJECT, BODY)
check("...and the tampered try used it up", r.code == "not_authorized" and not calls(), r)

g = om.authorize(None, ["ana@ejemplo.test"], [], [], by="t")
object.__setattr__(g, "account", "ventas")
r = om.send(g, SUBJECT, BODY)
check("grant forced to another account refused", r.code == "not_authorized" and not calls(), r)

g = om.authorize(None, ["ana@ejemplo.test"], [], [], by="t", owner_email="dueno@dominio.test")
object.__setattr__(g, "owner_email", "otro@fuera.test")
r = om.send(g, SUBJECT, BODY)
check("grant forced to another notice address refused", r.code == "not_authorized" and not calls(), r)

g = om.authorize(None, ["ana@ejemplo.test"], [], [], by="t")
twin = om.Grant(g._token, g.account, g.to, g.cc, g.bcc, g.by, g.owner_email, g._expires)
r = om.send(twin, SUBJECT, BODY)
check("look-alike grant with the right token refused", r.code == "not_authorized" and not calls(), r)

g = om.authorize(None, ["x@fuera.test"], [], [], by="t")
object.__setattr__(g, "allow_outside", True)
r = om.send(g, SUBJECT, BODY)
check("grant forced to allow outside refused", r.code == "not_authorized" and not calls(), r)

forged = om.Grant("0" * 64, "main", ("x@fuera.test",), (), (), "t", None, 9e12)
r = om.send(forged, SUBJECT, BODY)
check("made-up grant refused", r.code == "not_authorized" and not calls(), r)
r = om.send({"token": "x"}, SUBJECT, BODY)
check("not a grant refused", r.code == "not_authorized" and not calls(), r)

reset()
g = om.authorize(None, ["ana@ejemplo.test"], [], [], by="t")
results = []
threads = [threading.Thread(target=lambda: results.append(om.send(g, SUBJECT, BODY))) for _ in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("race: eight senders, one send", sum(r.ok for r in results) == 1 and len(calls()) == 1,
      [r.code for r in results])

# --- the password decision (Q5) ---------------------------------------------------------
reset()
r = om.send(om.authorize(None, ["x@fuera.test"], [], [], by="t"), SUBJECT, BODY)
check("outside without allow_outside: refused before SMTP", r.code == "not_authorized" and not calls()
      and r.outside_roster == ["x@fuera.test"], r)

reset()
original = ROSTER.read_text()
g = om.authorize(None, ["ana@ejemplo.test"], [], [], by="t")
ROSTER.write_text(original.replace("| Ana | Ana@Ejemplo.TEST | Human |\n", ""))
r = om.send(g, SUBJECT, BODY)
ROSTER.write_text(original)
check("inside at authorize, outside at send, no password: refused before SMTP",
      r.code == "not_authorized" and not calls(), r)

reset()
ROSTER.write_text(original + "| Nuevo | nuevo@fuera.test | Human |\n")
g = om.authorize(None, ["nuevo@fuera.test"], [], [], by="t", allow_outside=True)
ROSTER.write_text(original)
r = om.send(g, SUBJECT, BODY)
check("outside at send with the password: sent", r.ok and r.outside_roster == ["nuevo@fuera.test"], r)

reset()
ROSTER.write_text(original + "| X | x@fuera.test | Human |\n")
g = om.authorize(None, ["x@fuera.test"], [], [], by="t")
r = om.send(g, SUBJECT, BODY)
ROSTER.write_text(original)
check("outside at authorize, inside at send: sent", r.ok and r.outside_roster == [], r)

# --- additional account ------------------------------------------------------------------
reset()
r = om.send(om.authorize("ventas", ["leo@cliente.test"], [], [], by="t"), SUBJECT, BODY)
c = calls()
check("account: from ventas, its himalaya account", r.ok and r.outside_roster == [] and c
      and "-a paynani-ventas smtp send --mail-from ventas@dominio.test" in c[0], (r, c))
check("account: sent.log says the account", "account=ventas" in (STATE / "sent.log").read_text().splitlines()[-1])

# --- failures ------------------------------------------------------------------------------
reset()
(TMP / "himalaya.fail").touch()
r = om.send(om.authorize(None, ["ana@ejemplo.test"], [], [], by="t"), SUBJECT, BODY)
(TMP / "himalaya.fail").unlink()
check("SMTP failure: send_failed with himalaya's reason", r.code == "send_failed" and "refused" in r.detail, r)

reset()
saved = om.SENT_COPY
fake_copy = TMP / "copy.py"
fake_copy.write_text("print('failed no Sent folder')\n")
om.SENT_COPY = fake_copy
r = om.send(om.authorize(None, ["ana@ejemplo.test"], [], [], by="t"), SUBJECT, BODY)
om.SENT_COPY = saved
check("Sent copy failure: still sent", r.ok and r.sent_copy == "failed", r)

reset()
r = om.send(om.authorize(None, ["x@fuera.test"], [], [], by="t", owner_email="nadie@fuera.test",
                         allow_outside=True), SUBJECT, BODY)
check("notice refused by send.sh: message still sent, notice failed", r.ok and r.notice == "failed", r)

reset()
real_ntf = om.tempfile.NamedTemporaryFile


def broken(*a, **k):
    raise OSError("no temp space")


before = len((STATE / om.SENDS_LOG).read_text().splitlines())
om.tempfile.NamedTemporaryFile = broken
try:
    r = om.send(om.authorize(None, ["x@fuera.test"], [], [], by="t", owner_email="dueno@dominio.test",
                             allow_outside=True), SUBJECT, BODY)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = exc
om.tempfile.NamedTemporaryFile = real_ntf
check("notice cannot make its temp file: no exception, sent, notice failed",
      raised is None and r.ok and r.notice == "failed" and len(calls()) == 1, raised or r)
check("...and the send is still recorded",
      len((STATE / om.SENDS_LOG).read_text().splitlines()) == before + 1)

real_unlink = om.Path.unlink


def bad_unlink(self, *a, **k):
    if self.name.endswith(".txt"):
        raise OSError("cannot remove")
    return real_unlink(self, *a, **k)


om.Path.unlink = bad_unlink
try:
    r = om.send(om.authorize(None, ["x@fuera.test"], [], [], by="t", owner_email="dueno@dominio.test",
                             allow_outside=True), SUBJECT, BODY)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = exc
om.Path.unlink = real_unlink
check("notice temp file cannot be removed: no exception, sent", raised is None and r.ok, raised or r)

reset()


def bad_main_unlink(self, *a, **k):
    if self.name.startswith("paynani-owner-send."):
        raise OSError("cannot remove")
    return real_unlink(self, *a, **k)


before = len((STATE / om.SENDS_LOG).read_text().splitlines())
om.Path.unlink = bad_main_unlink
try:
    r = om.send(om.authorize(None, ["ana@ejemplo.test"], [], [], by="t"), SUBJECT, BODY)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = exc
om.Path.unlink = real_unlink
check("message temp file cannot be removed after SMTP: no exception, ok, one SMTP call, recorded",
      raised is None and r.ok and len(calls()) == 1
      and len((STATE / om.SENDS_LOG).read_text().splitlines()) == before + 1, raised or r)

reset()
real_sent_log = om._sent_log
om._sent_log = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    r = om.send(om.authorize(None, ["ana@ejemplo.test"], [], [], by="t"), SUBJECT, BODY)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = exc
om._sent_log = real_sent_log
check("sent.log write raises after SMTP: no exception, ok", raised is None and r.ok and len(calls()) == 1,
      raised or r)

reset()
real_tmp = om.tempfile.mkstemp
om.tempfile.mkstemp = lambda *a, **k: (_ for _ in ()).throw(OSError("no temp space"))
try:
    r = om.send(om.authorize(None, ["ana@ejemplo.test"], [], [], by="t"), SUBJECT, BODY)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = exc
om.tempfile.mkstemp = real_tmp
check("message temp file cannot be made: send_failed, nothing sent", raised is None and r.code == "send_failed"
      and not calls(), raised or r)

blocked = TMP / "blocked"
blocked.write_text("a file where the state folder should be")
r = om.send(om.authorize(None, ["ana@ejemplo.test"], [], [], by="t"), SUBJECT, BODY, state_dir=blocked)
check("record cannot be written: the send result is still returned", r.ok, r)

# --- records ---------------------------------------------------------------------------------
lines = (STATE / om.SENDS_LOG).read_text().splitlines()
entries = [json.loads(l) for l in lines]
check("owner_sends.jsonl: one line per call", len(entries) >= 12, len(entries))
check("owner_sends.jsonl: never the subject or the body", not any("secreto" in l for l in lines))
check("owner_sends.jsonl: outside addresses recorded",
      any(e["outside_roster"] == ["x@fuera.test"] and e["ok"] for e in entries))
check("owner_sends.jsonl: failed notice recorded", any(e["notice"] == "failed" and e["ok"] for e in entries))
check("results: no subject or body in detail", all("secreto" not in r.detail for r in results))

# --- send.sh is unchanged for everyone else ----------------------------------------------------
body = TMP / "body.txt"
body.write_text("hola\n")
done = subprocess.run(["bash", str(ROOT / "scripts" / "send.sh"), "x@fuera.test", "s", str(body)],
                      capture_output=True, text=True)
check("send.sh still refuses outside the roster", done.returncode == 2 and "REFUSED" in done.stderr, done.stderr)
done = subprocess.run(["bash", str(ROOT / "scripts" / "send.sh"), "--owner-order", "x", "x@fuera.test", "s",
                       str(body)], capture_output=True, text=True)
check("send.sh has no owner flag", done.returncode != 0)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
