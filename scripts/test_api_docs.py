"""
Tests for the API documentation (A8 #500 of PRD #491, FR-22). An assertion
script, like the rest of this suite.

`/api/agents.md` se sirve sin usuario, sin sesión y sin token. La guía del agente
y PAYNANI_API.md nombran cada acción de `api_actions.ACTIONS` y cada código de
error que la API puede responder, así que una acción o un error nuevo sin
documentar hace fallar esta prueba.
"""
from __future__ import annotations

import http.client
import re
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.web import api_actions, app, notify, users  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


GUIDE = ROOT / "scripts" / "paynani_lib" / "assets" / "api_agents.md"
OWNER = ROOT / "PAYNANI_API.md"
guide = GUIDE.read_text(encoding="utf-8")
owner = OWNER.read_text(encoding="utf-8")


def get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    res = conn.getresponse()
    body = res.read()
    conn.close()
    return res.status, res.getheader("Content-Type", ""), body


def serve(user_file):
    ctx = app.Context(user_file, notifier=notify.Notifier(send=lambda *a: None, log=lambda line: None),
                      agent_email="agente@example.com", accounts_file=user_file.parent / "no-accounts.json",
                      state_dir=user_file.parent / "state")
    httpd = app.serve("127.0.0.1", 0, ctx=ctx)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# --- FR-22: /api/agents.md sin autenticación ------------------------------------------
tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
user_file = tmp / "web" / "user.json"
httpd = serve(user_file)
port = httpd.server_address[1]
status, kind, body = get(port, "/api/agents.md")
check("sin usuario creado: /api/agents.md responde 200 con la guía", (200, True),
      (status, body == GUIDE.read_bytes()))
check("…como Markdown en UTF-8", "text/markdown; charset=UTF-8", kind)
users.create("dueno@example.com", "Dueño", "una-contraseña-larga", user_file)
status, kind, body = get(port, "/api/agents.md")
check("con usuario y sin sesión: 200 con la guía, no la página de entrada", (200, True),
      (status, body == GUIDE.read_bytes()))
status, _, _ = get(port, "/api/agents.md?api_token=pn_x")
check("una consulta en la URL no cambia nada", 200, status)
check("la guía no lleva datos de la instalación", False,
      any(s in body.decode("utf-8") for s in ("dueno@example.com", "agente@example.com", str(tmp))))
httpd.shutdown()

# --- Cada acción y cada error, en las dos guías ----------------------------------------
for name, text in (("api_agents.md", guide), ("PAYNANI_API.md", owner)):
    missing = sorted(a for a in api_actions.ACTIONS if f"`{a}`" not in text)
    check(f"{name}: nombra cada acción de ACTIONS", [], missing)

codes = set()
for path in (ROOT / "scripts/paynani_lib/web/api_actions.py", ROOT / "scripts/paynani_lib/web/app.py"):
    source = path.read_text(encoding="utf-8")
    codes |= set(re.findall(r'ApiError\(\d+, "([a-z_]+)"', source))
    codes |= set(re.findall(r'_api_reply\(\d+, [^)]*?code="([a-z_]+)"', source, re.S))
# Los que pasan tal cual de outgoing.queue() (SendSms) y del servicio del roster.
codes |= {"invalid_number", "empty_text", "text_too_long", "rate_limited", "busy"}
codes |= set(roster_api.FINAL_ERRORS)
check("se encontraron los códigos de la API", True, len(codes) > 20)
for name, text in (("api_agents.md", guide), ("PAYNANI_API.md", owner)):
    missing = sorted(c for c in codes if f"`{c}`" not in text)
    check(f"{name}: nombra cada código de error", [], missing)

# Cada fila de la tabla de permisos lista exactamente las acciones de ese permiso
# (revisión de #525: «read» decía «todo List… y Get…», y GetSmsStatus pide sms.send).
for name, text in (("api_agents.md", guide), ("PAYNANI_API.md", owner)):
    for perm in sorted({p for p, _ in api_actions.ACTIONS.values() if p is not None}):
        row = re.search(rf"^\| `{re.escape(perm)}` \| (.+) \|$", text, re.M)
        listed = set(re.findall(r"`([A-Z][A-Za-z]+)`", row.group(1))) if row else None
        expected = {a for a, (p, _) in api_actions.ACTIONS.items() if p == perm}
        check(f"{name}: la fila de {perm} lista exactamente sus acciones", sorted(expected),
              sorted(listed) if listed is not None else None)
    unrestricted = {a for a, (p, _) in api_actions.ACTIONS.items() if p is None}
    check(f"{name}: nombra las acciones sin permiso adicional", True,
          all(f"`{action}`" in text for action in unrestricted))

# Los números que la guía promete son los del código.
from paynani_lib.sms import outgoing  # noqa: E402
check("1,000 caracteres y 15 minutos, como outgoing", (1000, 15), (outgoing.MAX_TEXT, outgoing.DEFAULT_TTL_MIN))
for name, text in (("api_agents.md", guide), ("PAYNANI_API.md", owner)):
    check(f"{name}: dice los topes y el límite de Android", True,
          all(s in text for s in ("60", "30", "200", "1,000")) and "Android" in text)
check("PAYNANI_API.md enlaza la guía del agente", True, "/api/agents.md" in owner)
check("README enlaza PAYNANI_API.md", True, "(PAYNANI_API.md)" in (ROOT / "README.md").read_text(encoding="utf-8"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
