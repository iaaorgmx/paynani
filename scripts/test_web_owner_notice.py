#!/usr/bin/env python3
"""
El formato de los avisos al dueño de «Apps conectadas» (`web/owner_notice.py`): la
conclusión primero, los datos en renglones y qué hacer si no fue él, en texto plano y en
HTML. Y el camino de la parte HTML: `Notifier.owner(..., html=)` y `send_sh_notifier`,
que la pasa a `send.sh --html`. Aquí no sale ningún correo: `subprocess.run` es de mentira.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.web import notify, owner_notice  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     esperado: {expected!r}\n     obtenido: {actual!r}")


RECORD = {"client_id": "w_485b9501", "prefix": "pw_abcdefgh", "sha256": "0" * 64,
          "name": "Iris Claude-Tob", "app_name": "PaynaniWebMT", "app_version": "0.1.0-dev",
          "paired_at": "2026-11-05T19:48:10Z", "paired_ip": "192.0.2.7", "last_used_at": None,
          "revoked_at": None}

# --- una app nueva: el texto plano -----------------------------------------------------------------
notice = owner_notice.app_connected(RECORD, "192.0.2.7")
text = notice.text()
lines = text.split("\n")
check("la primera línea es la conclusión",
      "Se conectó «Iris Claude-Tob» a tu paynani. Ahora puede administrar esta instalación.", lines[0])
check("después, una línea en blanco y los datos", "", lines[1])
rows = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip() for line in lines[2:8]}
check("un renglón por dato, en este orden", ["App", "Nombre", "Dirección", "Cuándo", "Cómo", "Id"], list(rows))
check("la app con su versión", "PaynaniWebMT 0.1.0-dev", rows["App"])
check("la dirección", "192.0.2.7", rows["Dirección"])
check("cómo se conectó", "con un código de emparejamiento", rows["Cómo"])
check("el id del cliente", "w_485b9501", rows["Id"])
check("los valores quedan alineados", 1, len({line.index(value) for line, value in zip(lines[2:8], rows.values())}))
check("la hora sale completa, con el día y el año", (True, True), ("2026" in rows["Cuándo"], "noviembre" in rows["Cuándo"]))
check("la hora no es el sello ISO", False, "T19:48:10Z" in text)
check("al final, qué hacer si no fue él", True, "Si no fuiste tú, revócala:" in lines)
check("el paso de PaynaniWeb", True, "  - En PaynaniWeb, «Apps conectadas»." in lines)
check("el comando, con el id", True,
      "  - O en la terminal: `scripts/paynani web clients revoke w_485b9501`" in lines)
check("ningún renglón pasa de 100 caracteres", True, all(len(line) <= 100 for line in lines))
check("termina con un solo salto de línea", (True, False), (text.endswith("\n"), text.endswith("\n\n")))
check("no lleva el prefijo ni el hash del token", (False, False), ("pw_abcdefgh" in text, "0" * 64 in text))

# --- una app nueva: el HTML ------------------------------------------------------------------------
page = notice.html()
check("es un documento completo", (True, True), (page.startswith("<!DOCTYPE html>"), page.rstrip().endswith("</html>")))
check("adaptable al teléfono: viewport y ancho máximo", (True, True),
      ('name="viewport"' in page, "max-width:560px" in page))
check("el encabezado dice qué pasó", True, ">Nueva app conectada</h1>" in page)
check("la conclusión va antes que los datos", True, page.index("Ahora puede administrar") < page.index(">App</td>"))
check("cada dato en su renglón", 6, page.count("white-space:nowrap"))
check("el comando va en monoespaciado, sin los acentos graves", (True, False),
      ("scripts/paynani web clients revoke w_485b9501</code>" in page, "`" in page))
check("sin imágenes, hojas de estilo ni scripts de fuera", (False, False, False, False),
      ("<img" in page, "<link" in page, "<script" in page, "http" in page))
check("no lleva el prefijo ni el hash del token", (False, False), ("pw_abcdefgh" in page, "0" * 64 in page))
check("dice lo mismo que el texto plano", True,
      all(value in page for value in ("PaynaniWebMT 0.1.0-dev", "192.0.2.7", "w_485b9501", rows["Cuándo"])))

# El nombre lo escribe quien empareja: no puede meter HTML en el correo.
evil = dict(RECORD, name='<img src=x onerror=alert(1)>"&', app_name="<b>MT</b>", app_version="`1`")
page = owner_notice.app_connected(evil, "192.0.2.7").html()
check("el nombre y la app salen escapados", (False, False, True, True),
      ("<img" in page, "<b>" in page, "&lt;img src=x onerror=alert(1)&gt;&quot;&amp;" in page,
       "&lt;b&gt;MT&lt;/b&gt;" in page))
check("un acento grave en un dato no abre un comando", True, "&lt;b&gt;MT&lt;/b&gt; `1`" in page)

# Sin nombre de app ni versión, y con un sello que no se entiende.
bare = dict(RECORD, app_name="", app_version="", paired_at="ayer")
text = owner_notice.app_connected(bare, "").text()
check("sin nombre de app dice «app»", True, "  App:     app" in text)
check("un dato vacío no deja su renglón", False, "Dirección" in text)
check("un sello que no se entiende sale tal cual", True, "  Cuándo:  ayer" in text)

# --- se desconectó y se revocó ---------------------------------------------------------------------
gone = dict(RECORD, revoked_at="2026-11-05T20:10:00Z")
notice = owner_notice.app_disconnected(gone, "192.0.2.7")
text = notice.text()
check("desconectada: la conclusión", True, text.startswith(
    "«Iris Claude-Tob» se desconectó de tu paynani. Su token ya no abre la API del dueño.\n"))
check("desconectada: cómo, y cómo volver", (True, True),
      ("  Cómo:       desde la propia app" in text,
       "Para volver a conectarla hace falta un código de emparejamiento nuevo." in text))
check("desconectada: no hay «si no fuiste tú»", False, "Si no fuiste tú" in text + notice.html())
check("desconectada: el HTML", (True, True), (">App desconectada</h1>" in notice.html(), "w_485b9501" in notice.html()))

notice = owner_notice.app_revoked(gone, "198.51.100.4")
text = notice.text()
check("revocada: la conclusión", True, text.startswith(
    "Se revocó «Iris Claude-Tob» desde PaynaniWeb. Su token ya no abre la API del dueño.\n"))
check("revocada: desde qué dirección se revocó", True, "  Dirección:  198.51.100.4" in text)
check("revocada: qué hacer si no fue él", (True, True),
      ("Si no fuiste tú:" in text, "`scripts/paynani web passwd`" in text))
check("revocada: el HTML", (True, True),
      (">App revocada</h1>" in notice.html(), "scripts/paynani web passwd</code>" in notice.html()))

# --- Notifier: la parte HTML es opcional -----------------------------------------------------------
got = []
n = notify.Notifier(send=lambda *a: got.append(a), log=lambda line: None)
n.owner({"email": "ana@example.com"}, "Asunto", "texto")
n.wait()
check("un aviso sin HTML sale con tres argumentos, como siempre", [("ana@example.com", "Asunto", "texto")], got)
got.clear()
n.owner({"email": "ana@example.com"}, "Asunto", "texto", "<p>texto</p>")
n.wait()
check("con HTML, la parte va de cuarto argumento", [("ana@example.com", "Asunto", "texto", "<p>texto</p>")], got)

# --- send_sh_notifier: --html y los temporales -----------------------------------------------------
calls = []


def fake_run(argv, **kwargs):
    files = {arg: Path(arg).read_text(encoding="utf-8") for arg in argv if arg.endswith((".txt", ".html"))}
    calls.append((argv, files))


real_run = roster_api.subprocess.run
roster_api.subprocess.run = fake_run
try:
    roster_api.send_sh_notifier("ana@example.com", "Asunto", "texto ñ")
    roster_api.send_sh_notifier("ana@example.com", "Asunto", "texto ñ", "<p>texto ñ</p>")
finally:
    roster_api.subprocess.run = real_run

argv, files = calls[0]
check("sin HTML: send.sh <a> <asunto> <cuerpo>, como siempre", ("send.sh", ["ana@example.com", "Asunto"], 1),
      (Path(argv[1]).name, argv[2:4], len(files)))
check("sin HTML: no lleva --html", False, "--html" in argv)
argv, files = calls[1]
check("con HTML: --html <archivo> antes del destinatario", ("--html", ["ana@example.com", "Asunto"]),
      (argv[2], argv[4:6]))
check("con HTML: cada parte en su archivo", ("<p>texto ñ</p>", "texto ñ"), (files[argv[3]], files[argv[6]]))
check("los temporales se borran", [], [path for _, used in calls for path in used if Path(path).exists()])

print(f"\n{passed} ok, {failed} fail")
sys.exit(1 if failed else 0)
