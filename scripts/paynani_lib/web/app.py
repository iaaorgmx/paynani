"""
El servidor HTTP de PaynaniWeb (PRD #434 FR-3, FR-4, FR-11).

`http.server` de la biblioteca estándar, un hilo por petición: abrir un correo
pide su hilo a IMAP (FR-14), y eso no debe detener al resto de la página. El
idioma va por hilo (i18n.py).

Mientras no exista el usuario (`paynani web user add`), toda ruta que no sea un
recurso estático responde la página «crea tu usuario» y nada más (FR-4). Es lo
primero que ve quien abre la dirección del túnel después de instalar.

Escucha sólo en loopback: desde fuera se llega por la pasarela SMS (FR-1), que es
la que da la cara al túnel. Como todo llega desde 127.0.0.1, la dirección del
cliente no dice nada aquí; el bloqueo por IP (T3) lee el `X-Forwarded-For` que
pone el túnel.
"""
from __future__ import annotations

import html
import json
import sys
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import guard, i18n
from ..brand import brand_svg
from . import strings  # noqa: F401 -- suma las claves web.* a los catálogos
from . import users

ASSETS = Path(__file__).resolve().parents[1] / "assets"
STATIC = {
    "/assets/app.css": (ASSETS / "app.css", "text/css; charset=UTF-8"),
    "/assets/web.css": (ASSETS / "web.css", "text/css; charset=UTF-8"),
    "/assets/lang.js": (ASSETS / "lang.js", "application/javascript; charset=UTF-8"),
}
LANG_COOKIE = "paynani_web_lang"
MAX_BODY_BYTES = 64 * 1024
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
SERVER_NAME = "paynani-web"


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def negotiate_lang(query: dict, cookie_header: str, accept_language: str) -> tuple[str, bool]:
    """
    (idioma, hay_que_recordarlo). `?lang=` gana y se recuerda en una cookie; si
    no, la cookie; si no, la primera etiqueta de `Accept-Language` que coincida
    con un idioma conocido (exacta, o por su idioma: `pt` es pt-BR); si no,
    es-MX.
    """
    asked = (query.get("lang", [""])[0] or "").strip()
    if asked and i18n.lang_is_known(asked):
        return asked, True
    held = ""
    try:
        jar = cookies.SimpleCookie(cookie_header or "")
        morsel = jar.get(LANG_COOKIE)
        held = morsel.value if morsel is not None else ""
    except cookies.CookieError:
        held = ""
    if held and i18n.lang_is_known(held):
        return held, False
    known = list(i18n.LANGUAGES)
    for part in (accept_language or "").split(","):
        tag = part.split(";", 1)[0].strip()
        if not tag:
            continue
        for lang in known:
            if lang.lower() == tag.lower():
                return lang, False
        base = tag.split("-", 1)[0].lower()
        for lang in known:
            if lang.split("-", 1)[0].lower() == base:
                return lang, False
    return i18n.LANG_DEFAULT, False


def _lang_options(current: str) -> str:
    return "\n".join(
        f'<option value="{e(tag)}"{" selected" if tag == current else ""}>{e(name)}</option>'
        for tag, name in i18n.LANGUAGES.items())


def document(lang: str, title: str, body: str) -> str:
    """El marco de las páginas sin sesión: la marca arriba y el selector de idioma."""
    th = i18n.th
    logo = brand_svg("paynani-horizontal.svg")
    return f"""<!doctype html>
<html lang="{e(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="stylesheet" href="/assets/app.css">
<link rel="stylesheet" href="/assets/web.css">
<script src="/assets/lang.js" defer></script>
</head>
<body class="web-solo">
<main>
<div class="topbar">
  <div class="marca">{logo}</div>
  <form method="get" action="" class="langpick">
    <span class="combo">
      <select id="lang" name="lang" aria-label="{th('web.lang.label')}">
        {_lang_options(lang)}
      </select>
    </span>
    <button type="submit" id="langgo">{th('web.lang.apply')}</button>
  </form>
</div>
{body}
</main>
</body>
</html>
"""


def setup_page(lang: str) -> str:
    th = i18n.th
    body = f"""
<h1>{th('web.setup.h1')}</h1>
<p class="lead">{th('web.setup.lead')}</p>
<p>{th('web.setup.step1')}</p>
<pre><code>scripts/paynani web user add \\
    --email {th('web.setup.ph_email')} \\
    --name "{th('web.setup.ph_name')}"</code></pre>
<p>{th('web.setup.step2', min=users.MIN_PASSWORD)}</p>
<p class="quiet">{th('web.setup.only')}</p>
"""
    return document(lang, i18n.t("web.setup.title"), body)


def ready_page(lang: str) -> str:
    th = i18n.th
    body = f"""
<h1>{th('web.ready.h1')}</h1>
<p class="lead">{th('web.ready.lead')}</p>
"""
    return document(lang, i18n.t("web.ready.title"), body)


def message_page(lang: str, title_key: str, h1_key: str) -> str:
    return document(lang, i18n.t(title_key), f"<h1>{i18n.th(h1_key)}</h1>\n")


def make_handler(user_file: Path | None = None):
    """Un handler atado a un archivo de usuario (las pruebas pasan uno temporal)."""

    class Handler(BaseHTTPRequestHandler):
        USER_FILE = user_file
        protocol_version = "HTTP/1.1"

        def version_string(self):
            # Sin la versión de Python: no le dice nada útil al dueño y sí a quien
            # busca qué atacar.
            return SERVER_NAME

        def log_message(self, fmt, *args):  # noqa: A003
            # Sólo el método y la ruta: nunca la consulta ni el cuerpo, que pueden
            # llevar datos de un correo o de un contacto (PRD #434 §5).
            path = self.path.split("?", 1)[0]
            sys.stderr.write(f"{self.command} {path} {args[1] if len(args) > 1 else ''}\n")

        def _send(self, code: int, content_type: str, body: bytes, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in guard.SECURITY_HEADERS:
                self.send_header(name, value)
            for name, value in extra or ():
                self.send_header(name, value)
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _html(self, code: int, page: str, set_lang: str = ""):
            extra = [("Content-Security-Policy", guard.CSP)]
            if set_lang:
                cookie = cookies.SimpleCookie()
                cookie[LANG_COOKIE] = set_lang
                cookie[LANG_COOKIE]["path"] = "/"
                cookie[LANG_COOKIE]["samesite"] = "Strict"
                cookie[LANG_COOKIE]["httponly"] = True
                cookie[LANG_COOKIE]["max-age"] = 365 * 86400
                if self.headers.get("X-Forwarded-Proto", "") == "https":
                    cookie[LANG_COOKIE]["secure"] = True
                extra.append(("Set-Cookie", cookie[LANG_COOKIE].OutputString()))
            self._send(code, "text/html; charset=UTF-8", page.encode("utf-8"), extra)

        def _lang(self, query: dict) -> tuple[str, str]:
            lang, remember = negotiate_lang(query, self.headers.get("Cookie", ""),
                                            self.headers.get("Accept-Language", ""))
            i18n.set_current(lang)
            return lang, (lang if remember else "")

        def _static(self, path: str) -> bool:
            entry = STATIC.get(path)
            if entry is None:
                return False
            file, kind = entry
            try:
                data = file.read_bytes()
            except OSError:
                self._send(404, "text/plain; charset=UTF-8", b"")
                return True
            self._send(200, kind, data)
            return True

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if self._static(parsed.path):
                return
            if parsed.path == "/_health":
                body = json.dumps({"ok": True, "configured": users.exists(self.USER_FILE)}).encode("utf-8")
                self._send(200, "application/json; charset=UTF-8", body)
                return
            query = parse_qs(parsed.query)
            lang, set_lang = self._lang(query)
            # FR-4: sin usuario, cualquier ruta es «crea tu usuario».
            if not users.exists(self.USER_FILE):
                self._html(200, setup_page(lang), set_lang)
                return
            if parsed.path == "/":
                self._html(200, ready_page(lang), set_lang)
                return
            self._html(404, message_page(lang, "web.notfound.title", "web.notfound.h1"), set_lang)

        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def do_POST(self):  # noqa: N802
            # Ningún formulario escribe todavía (el acceso es T3). El cuerpo se lee
            # y se descarta, hasta MAX_BODY_BYTES, para cerrar limpio.
            try:
                length = max(0, min(int(self.headers.get("Content-Length", "0") or "0"), MAX_BODY_BYTES))
            except ValueError:
                length = 0
            if length:
                self.rfile.read(length)
            lang, _ = self._lang({})
            if not users.exists(self.USER_FILE):
                self._html(200, setup_page(lang))
                return
            self._html(405, message_page(lang, "web.title", "web.method.h1"))

    return Handler


class Server(ThreadingHTTPServer):
    """Sin la búsqueda de DNS inversa de server_bind(), como onboard.py."""
    daemon_threads = True

    def server_bind(self):
        import socketserver
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def serve(host: str = "127.0.0.1", port: int = 8771, user_file: Path | None = None) -> Server:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("PaynaniWeb only listens on loopback; it is reached through the SMS gateway")
    return Server((host, port), make_handler(user_file))
