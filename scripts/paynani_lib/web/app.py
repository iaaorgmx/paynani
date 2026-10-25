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
import re
import secrets
import sys
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .. import guard, i18n
from ..brand import brand_svg
from . import strings, token_strings  # noqa: F401 -- suma las claves web.* a los catálogos
from . import (accounts_pages, api_actions, api_auth, api_security, api_tokens, auth, mail, mail_pages, messages_pages, notify, profile_pages, roster_pages, shell, token_pages,
               thread, users)

ASSETS = Path(__file__).resolve().parents[1] / "assets"
FAVICON = Path(__file__).resolve().parents[3] / "brand" / "favicon.svg"
STATIC = {
    "/assets/app.css": (ASSETS / "app.css", "text/css; charset=UTF-8"),
    "/assets/web.css": (ASSETS / "web.css", "text/css; charset=UTF-8"),
    "/assets/lang.js": (ASSETS / "lang.js", "application/javascript; charset=UTF-8"),
    "/assets/time.js": (ASSETS / "time.js", "application/javascript; charset=UTF-8"),
    "/assets/nav.js": (ASSETS / "nav.js", "application/javascript; charset=UTF-8"),
    "/assets/sms.js": (ASSETS / "sms.js", "application/javascript; charset=UTF-8"),
    "/assets/api_tokens.js": (ASSETS / "api_tokens.js", "application/javascript; charset=UTF-8"),
    # PRD #491 FR-22: la guía de la API para agentes, sin autenticación.
    "/api/agents.md": (ASSETS / "api_agents.md", "text/markdown; charset=UTF-8"),
    # The brand favicon, from brand/ so there is one copy. /favicon.ico is what a
    # browser asks for on its own; without it that request ended in the login page.
    "/assets/favicon.svg": (FAVICON, "image/svg+xml"),
    "/favicon.ico": (FAVICON, "image/svg+xml"),
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
{shell.FAVICON_LINK}
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


VOLUTA = ('<svg class="marca-agua" viewBox="0 0 64 64" fill="none" aria-hidden="true">'
          '<path d="M50 15C30 11 12 23 14 38c2 12 16 16 24 10 8-6 6-16-2-17-6-1-10 4-7 8" '
          'stroke="#8f2d2b" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def login_page(lang: str, *, email: str = "", notice: str = "", error: str = "", next_path: str = "/") -> str:
    """PDSL-100: la tarjeta a la izquierda y el lema a la derecha, sin «Sign up»
    ni Google ni teléfono (FR-5)."""
    th = i18n.th
    logo = brand_svg("paynani-horizontal.svg")
    note = f'<p class="aviso" role="status">{notice}</p>' if notice else ""
    err = f'<p class="error" role="alert">{error}</p>' if error else ""
    return f"""<!doctype html>
<html lang="{e(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(i18n.t('web.login.title'))}</title>
{shell.FAVICON_LINK}
<link rel="stylesheet" href="/assets/app.css">
<link rel="stylesheet" href="/assets/web.css">
<script src="/assets/lang.js" defer></script>
</head>
<body class="web-login">
{VOLUTA}
<main class="tarjeta">
  <div class="marca">{logo}</div>
  <h1>{th('web.login.h1')}</h1>
  <p class="sub">{th('web.login.lead')}</p>
  {note}{err}
  <form method="post" action="/login" autocomplete="on">
    <input type="hidden" name="next" value="{e(next_path)}">
    <label for="email">{th('web.login.email')}</label>
    <input id="email" name="email" type="email" required autocomplete="username" value="{e(email)}"{'' if email else ' autofocus'}>
    <label for="password">{th('web.login.password')}</label>
    <input id="password" name="password" type="password" required autocomplete="current-password"{' autofocus' if email else ''}>
    <button type="submit" class="continuar">{th('web.login.submit')}</button>
  </form>
  <p class="legal">{i18n.t('web.login.forgot')}</p>
  <form method="get" action="/login" class="langpick">
    <span class="combo">
      <select id="lang" name="lang" aria-label="{th('web.lang.label')}">
        {_lang_options(lang)}
      </select>
    </span>
    <button type="submit" id="langgo">{th('web.lang.apply')}</button>
  </form>
</main>
<section class="lema">
  <h2>{th('web.lema.h2')}</h2>
  <p>{th('web.lema.p')}</p>
</section>
</body>
</html>
"""


def home_body(user: dict) -> str:
    th = i18n.th
    return f"""
<h2>{th('web.home.hello', name=user.get('name', ''))}</h2>
<p class="lead">{th('web.home.lead')}</p>
"""


def soon_body() -> str:
    return f'<p class="lead">{i18n.th("web.soon")}</p>\n'


def message_page(lang: str, title_key: str, h1_key: str, lead_key: str = "") -> str:
    lead = f'<p class="lead">{i18n.th(lead_key)}</p>\n' if lead_key else ""
    return document(lang, i18n.t(title_key), f"<h1>{i18n.th(h1_key)}</h1>\n{lead}")


def safe_next(value: str) -> str:
    """Una ruta de esta misma web, o "/": nunca otro sitio (`//x`, `/\\x`, `http:`)."""
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value or value.startswith("/login") \
            or any(ord(c) < 32 for c in value):
        return "/"
    return value


def form_fields(raw: bytes) -> dict:
    text = raw.decode("utf-8", errors="replace")
    return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()}


class Context:
    """Lo que comparten todas las peticiones de un servidor."""

    def __init__(self, user_file: Path | None = None, notifier: notify.Notifier | None = None, clock=time.time,
                 agent_email=None, accounts_file: Path | None = None, ledger_path: Path | None = None,
                 env_path: Path | None = None, imap_connect=None, imap_uidvalidity=None,
                 state_dir: Path | None = None, roster_path: Path | None = None, roster_notifier=None):
        self.user_file = user_file
        self.sessions = auth.Sessions(clock)
        self.lockout = auth.Lockout(clock)
        self.api_limits = api_auth.Limits(clock)
        if state_dir is not None:
            audit_dir = Path(state_dir)
        elif user_file is not None:
            audit_dir = Path(user_file).parent.parent / "state"
        else:
            import paths
            audit_dir = paths.state_dir()
        self.api_security = api_security.Journal(audit_dir, clock)
        self.notifier = notifier or notify.Notifier()
        # La cuenta del agente y las de accounts.json, para el menú (FR-10). Las
        # pruebas pasan las suyas; sin ellas, las de la instalación. Del .env sólo
        # se lee la dirección, nunca la contraseña.
        self._agent_email = agent_email
        self.accounts_file = accounts_file
        # Email Accounts (FR-13, FR-14): el ledger y el login de cada cuenta. Las
        # pruebas pasan los suyos, y un IMAP de prueba.
        self._ledger_path = ledger_path
        self._env_path = env_path
        self.imap_connect = imap_connect
        self.imap_uidvalidity = imap_uidvalidity
        # Messages (FR-17): el diario y el store de la pasarela, y los nombres del
        # roster del agente por teléfono.
        self._state_dir = state_dir
        self._roster_path = roster_path
        # Roster (FR-20): el mismo servicio que la pantalla de PaynaniApp. Uno por
        # proceso, como en la pasarela: guarda el candado y los pedidos ya hechos.
        self._roster_notifier = roster_notifier
        self._roster_service = None
        # Agregar y quitar cuentas (FR-16): accounts_cli y probe, los de `paynani
        # account add`; las pruebas los cambian.
        from .. import accounts_cli
        from .. import probe as probe_mod
        self.account_ops = accounts_cli
        self.probe_imap = probe_mod.probe_imap
        self.probe_smtp = probe_mod.probe_smtp

    def state_dir(self) -> Path:
        if self._state_dir is not None:
            return Path(self._state_dir)
        import paths
        return paths.state_dir()

    def roster_path(self) -> Path:
        if self._roster_path is not None:
            return Path(self._roster_path)
        import paths
        return paths.roster()

    def roster_service(self):
        if self._roster_service is None:
            from ..sms import roster_api
            notifier = self._roster_notifier if self._roster_notifier is not None else roster_api.send_sh_notifier
            roster = self.roster_path()
            accounts_file = self.accounts_file
            if accounts_file is None:
                from .. import accounts as accounts_mod
                accounts_file = accounts_mod.accounts_path()
            self._roster_service = roster_api.RosterService(
                roster, self.state_dir(), accounts_file=accounts_file, agent_email=self.agent_email(),
                notifier=notifier, log=lambda line: sys.stderr.write(f"paynani-web: {line}\n"),
                rules_root=roster.parent)
        return self._roster_service

    def phone_names(self) -> dict:
        import roster as roster_mod
        try:
            return {entry["phone"]: entry.get("name", "") or entry["phone"]
                    for entry in roster_mod.roster_phone_entries(self.roster_path())}
        except OSError:
            return {}

    def ledger_path(self) -> Path:
        if self._ledger_path is not None:
            return Path(self._ledger_path)
        import paths
        return paths.state_dir() / "lifecycle.jsonl"

    def env_path(self) -> Path:
        if self._env_path is not None:
            return Path(self._env_path)
        import paths
        return paths.env_file()

    def known_ids(self) -> set[str]:
        from .. import accounts as accounts_mod
        try:
            return {a["id"] for a in accounts_mod.load(self.accounts_file)}
        except accounts_mod.AccountsError:
            return set()

    def agent_email(self) -> str:
        if self._agent_email is not None:
            return self._agent_email() if callable(self._agent_email) else self._agent_email
        from .. import envfile
        try:
            return envfile.read_env().get("AGENT_EMAIL_ACCOUNT", "")
        except Exception:  # noqa: BLE001 -- sólo es para mostrar
            return ""

    def mail_accounts(self) -> tuple[list[dict], str]:
        """(cuentas, error). Un accounts.json que no se lee no tumba la página:
        queda la cuenta del agente y el menú lo dice."""
        from .. import accounts as accounts_mod
        error = ""
        try:
            additional = accounts_mod.load(self.accounts_file)
        except accounts_mod.AccountsError as exc:
            additional, error = [], str(exc)
        return shell.mail_accounts(self.agent_email(), additional), error

    def user(self) -> dict | None:
        return users.load(self.user_file)

    def user_path(self) -> Path:
        return Path(self.user_file) if self.user_file else users.user_path()


def make_handler(ctx: Context):
    """Un handler atado a un Context (las pruebas pasan uno con archivo temporal)."""

    class Handler(BaseHTTPRequestHandler):
        CTX = ctx
        protocol_version = "HTTP/1.1"

        def version_string(self):
            # Sin la versión de Python: no le dice nada útil al dueño y sí a quien
            # busca qué atacar.
            return SERVER_NAME

        def log_message(self, fmt, *args):  # noqa: A003
            # Sólo el método y la ruta: nunca la consulta ni el cuerpo, que pueden
            # llevar datos de un correo o de un contacto (PRD #434 §5).
            # A stdout, que el servicio manda a state/web.log (logrotate lo rota);
            # stderr queda para los errores del proceso.
            path = self.path.split("?", 1)[0]
            sys.stdout.write(f"{self.log_date_time_string()} {self.command} {path} "
                             f"{args[1] if len(args) > 1 else ''}\n")
            sys.stdout.flush()

        # ---- respuesta ------------------------------------------------------
        def _send(self, code: int, content_type: str, body: bytes, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in guard.SECURITY_HEADERS:
                if name == "Referrer-Policy":
                    # `no-referrer` (el de server.py) hace que el navegador mande
                    # `Origin: null` en un POST de la misma página, y entonces
                    # _same_origin() no puede saber de dónde vino. `same-origin`
                    # sigue sin dar nada a otros sitios.
                    value = "same-origin"
                self.send_header(name, value)
            for name, value in extra or ():
                self.send_header(name, value)
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _cookie(self, name: str, value: str, max_age: int | None) -> str:
            cookie = cookies.SimpleCookie()
            cookie[name] = value
            cookie[name]["path"] = "/"
            cookie[name]["samesite"] = "Strict"
            cookie[name]["httponly"] = True
            # FR-8: Secure siempre. Los navegadores la aceptan también en
            # http://127.0.0.1 y localhost (ssh -L), que cuentan como contexto seguro.
            cookie[name]["secure"] = True
            if max_age is not None:
                cookie[name]["max-age"] = max_age
            return cookie[name].OutputString()

        def _html(self, code: int, page: str, cookies_out=()):
            extra = [("Content-Security-Policy", guard.CSP)]
            if self.set_lang:
                extra.append(("Set-Cookie", self._cookie(LANG_COOKIE, self.set_lang, 365 * 86400)))
            extra.extend(("Set-Cookie", c) for c in cookies_out)
            self._send(code, "text/html; charset=UTF-8", page.encode("utf-8"), extra)

        def _redirect(self, location: str, cookies_out=()):
            extra = [("Location", location)] + [("Set-Cookie", c) for c in cookies_out]
            if self.set_lang:
                extra.append(("Set-Cookie", self._cookie(LANG_COOKIE, self.set_lang, 365 * 86400)))
            self._send(303, "text/plain; charset=UTF-8", b"", extra)

        def _api_reply(self, status: int, request_id: str, *, code: str = "", message: str = "",
                       retry_after: int = 0):
            result = {"result": "error", "code": code, "message": message, "request_id": request_id}
            if retry_after:
                result["retry_after"] = retry_after
            self._send(status, "application/json; charset=UTF-8", json.dumps(result).encode("utf-8"),
                       [("X-Request-Id", request_id), ("Cache-Control", "no-store")])

        def _api_audit(self, kind: str, request_id: str, prefix: str, address: str) -> None:
            try:
                self.CTX.api_security.record(kind, request_id, prefix, address)
            except (OSError, ValueError):
                sys.stderr.write(f"paynani-web: API audit unavailable for {request_id}\n")

        def _api_auth_failure(self, request_id: str, prefix: str, address: str,
                              kind: str = "invalid_token") -> None:
            self._api_audit(kind, request_id, prefix, address)
            if self.CTX.api_limits.fail(address):
                self._api_audit("too_many_attempts", request_id, prefix, address)
                self.CTX.notifier.owner(self.CTX.user(), "Paynani API: 10 fallos de autenticación",
                                        f"Se bloquearon los intentos de autenticación de API desde {address} "
                                        "durante 15 minutos tras 10 fallos consecutivos. "
                                        "Revisa state/api_security.jsonl para los request_id.")

        def _api_post(self, raw: bytes):
            request_id = secrets.token_hex(8)
            address = auth.client_ip(self.headers, self.client_address[0])
            remaining = self.CTX.api_limits.blocked_for(address)
            if remaining:
                self._api_audit("too_many_attempts", request_id, "", address)
                self._api_reply(429, request_id, code="too_many_attempts",
                                message="Too many failed authentication attempts.", retry_after=remaining)
                return
            query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            if "api_token" in query or "token" in query:
                self._api_auth_failure(request_id, "", address)
                self._api_reply(401, request_id, code="invalid_token", message="API token cannot be in the URL.")
                return
            kind = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            try:
                if kind == "application/json":
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("expected a JSON object")
                elif kind == "application/x-www-form-urlencoded":
                    data = form_fields(raw)
                else:
                    self._api_reply(415, request_id, code="invalid_content_type",
                                    message="Use JSON or form data.")
                    return
            except (UnicodeError, ValueError):
                self._api_reply(400, request_id, code="invalid_body", message="Invalid request body.")
                return
            header = self.headers.get("Authorization", "")
            if header:
                scheme, _, value = header.partition(" ")
                token = value.strip() if scheme.lower() == "bearer" else ""
            else:
                token = data.get("api_token", "")
            try:
                outcome, record = api_tokens.lookup(token, path=api_tokens.path_for(self.CTX.user_path()))
            except (OSError, ValueError):
                self._api_audit("internal_error", request_id, api_security.safe_prefix(token), address)
                self._api_reply(500, request_id, code="internal_error", message="Token store unavailable.")
                return
            if outcome != "ok":
                prefix = record.get("prefix", "") if record else api_security.safe_prefix(token)
                self._api_auth_failure(request_id, prefix, address, kind=outcome)
                messages = {"invalid_token": "API token invalid.",
                            "token_revoked": "API token was revoked.",
                            "token_expired": "API token expired."}
                self._api_reply(401, request_id, code=outcome, message=messages[outcome])
                return
            self.CTX.api_limits.success(address)
            remaining = self.CTX.api_limits.admit_call(record["sha256"])
            if remaining:
                self._api_audit("rate_limited", request_id, record.get("prefix", ""), address)
                self._api_reply(429, request_id, code="rate_limited",
                                message="Too many requests for this token.", retry_after=remaining)
                return
            self._api_audit("call", request_id, record.get("prefix", ""), address)
            try:
                api_tokens.touch(record["sha256"], path=api_tokens.path_for(self.CTX.user_path()))
            except (OSError, ValueError):
                self._api_audit("internal_error", request_id, record.get("prefix", ""), address)
                self._api_reply(500, request_id, code="internal_error", message="Token store unavailable.")
                return
            # A3 #495: la acción, con su permiso (FR-5). Las demás tareas suman las suyas
            # en api_actions.ACTIONS sin tocar la autenticación de arriba.
            try:
                result = api_actions.run(self.CTX, record, address, data, request_id=request_id)
            except api_actions.ApiError as exc:
                if exc.code in ("quota_exceeded", "opted_out", "forbidden", "internal_error", "rate_limited"):
                    self._api_audit(exc.code, request_id, record.get("prefix", ""), address)
                self._api_error(exc, request_id)
                return
            except Exception as exc:  # noqa: BLE001 -- un error interno no deja la conexión sin respuesta
                sys.stderr.write(f"paynani-web: api {data.get('action')!r} {request_id}: {type(exc).__name__}\n")
                self._api_audit("internal_error", request_id, record.get("prefix", ""), address)
                self._api_reply(500, request_id, code="internal_error", message="Internal error.")
                return
            body = {"result": "success", **result, "request_id": request_id}
            self._send(200, "application/json; charset=UTF-8", json.dumps(body, ensure_ascii=False).encode("utf-8"),
                       [("X-Request-Id", request_id), ("Cache-Control", "no-store")])

        def _api_error(self, exc, request_id: str):
            result = {"result": "error", "code": exc.code, "message": exc.message, **exc.extra,
                      "request_id": request_id}
            self._send(exc.status, "application/json; charset=UTF-8",
                       json.dumps(result, ensure_ascii=False).encode("utf-8"),
                       [("X-Request-Id", request_id), ("Cache-Control", "no-store")])

        # ---- contexto de la petición -----------------------------------------
        def _begin(self):
            parsed = urlparse(self.path)
            self.route = parsed.path
            self.query = parse_qs(parsed.query)
            lang, remember = negotiate_lang(self.query, self.headers.get("Cookie", ""),
                                            self.headers.get("Accept-Language", ""))
            i18n.set_current(lang)
            self.lang, self.set_lang = lang, (lang if remember else "")
            self.ip = auth.client_ip(self.headers, self.client_address[0])
            self.user = self.CTX.user()
            sid = ""
            try:
                morsel = cookies.SimpleCookie(self.headers.get("Cookie", "")).get(auth.SESSION_COOKIE)
                sid = morsel.value if morsel is not None else ""
            except cookies.CookieError:
                sid = ""
            self.sid = sid
            self.session = self.CTX.sessions.get(sid, self.user)

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

        def _same_origin(self) -> bool:
            """Un POST trae Origin (o Referer) de esta misma dirección. Junto con
            SameSite=Strict y el token de cada formulario, cierra el paso a un
            formulario de otro sitio."""
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
            if not host:
                return False
            origin = self.headers.get("Origin", "")
            if origin:
                return urlparse(origin).netloc == host
            referer = self.headers.get("Referer", "")
            return bool(referer) and urlparse(referer).netloc == host

        def _to_login(self, notice: str = ""):
            target = "/login"
            params = []
            if self.route not in ("/", "") and self.command == "GET":
                params.append("next=" + quote(self.path, safe="/"))
            if notice:
                params.append("msg=" + notice)
            self._redirect(target + ("?" + "&".join(params) if params else ""))

        # ---- verbos ------------------------------------------------------------
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/agent":
                self._api_reply(405, secrets.token_hex(8), code="method_not_allowed", message="Use POST.")
                return
            if self._static(parsed.path):
                return
            if parsed.path == "/_health":
                body = json.dumps({"ok": True, "configured": users.exists(self.CTX.user_file)}).encode("utf-8")
                self._send(200, "application/json; charset=UTF-8", body)
                return
            self._begin()
            # FR-4: sin usuario, cualquier ruta es «crea tu usuario».
            if self.user is None:
                self._html(200, setup_page(self.lang))
                return
            if self.route == "/login":
                if self.session:
                    self._redirect(safe_next(self.query.get("next", ["/"])[0]))
                    return
                msg = self.query.get("msg", [""])[0]
                notice = {"out": i18n.th("web.login.out"), "expired": i18n.th("web.login.expired")}.get(msg, "")
                self._html(200, login_page(self.lang, notice=notice,
                                           next_path=safe_next(self.query.get("next", ["/"])[0])))
                return
            if not self.session:
                # Una cookie de sesión que ya no sirve (venció, o cambió la contraseña).
                self._to_login("expired" if self.sid else "")
                return
            self.dispatch_get()

        def _page(self, code: int, *, title: str, body: str, **kw):
            accounts, error = self.CTX.mail_accounts()
            self._html(code, shell.page(self.lang, self.user, self.session["csrf"], title=title, body=body,
                                        accounts=accounts, accounts_error=error,
                                        collapsed=shell.nav_collapsed(self.headers.get("Cookie", "")), **kw))

        def dispatch_get(self):
            t = i18n.t
            if self.route == "/":
                self._page(200, title=t("web.home.title"), body=home_body(self.user), icon_name="home")
                return
            if self.route.startswith("/email/"):
                self._email()
                return
            if self.route == "/cuentas/nueva" or (self.route.startswith("/cuentas/") and self.route.endswith("/quitar")):
                self._accounts_get()
                return
            if self.route in ("/messages", "/messages/ver", "/messages/nuevo"):
                self._messages()
                return
            if self.route == "/messages/bajas":
                self._sms_optout()
                return
            if self.route == "/messages/estados":
                self._sms_statuses()
                return
            if self.route in ("/roster", "/roster/editar", "/roster/quitar", "/roster/reglas"):
                self._roster_get()
                return
            if self.route in ("/profile", "/profile/info", "/profile/password"):
                self._profile_get()
                return
            if self.route in ("/api-tokens", "/api-tokens/new", "/api-tokens/detail"):
                self._tokens_get()
                return
            self._page(404, title=t("web.notfound.h1"), body="", icon_name="warn")

        def _tokens_get(self):
            t = i18n.t
            path = api_tokens.path_for(self.CTX.user_path())
            try:
                records = api_tokens.list_records(path=path)
            except (OSError, ValueError):
                self._page(500, title=t("web.tokens.title"), body=f'<p class="error">{i18n.th("web.tokens.invalid")}</p>', active="api_tokens")
                return
            if self.route == "/api-tokens/new":
                self._page(200, title=t("web.tokens.create"), body=token_pages.new_body(self.session["csrf"]),
                           active="api_tokens", back="/api-tokens")
            elif self.route == "/api-tokens/detail":
                digest = self.query.get("id", [""])[0]
                record = next((r for r in records if r["sha256"] == digest), None)
                if record is None:
                    self._page(404, title=t("web.tokens.title"), body=f'<p>{i18n.th("web.tokens.missing")}</p>',
                               active="api_tokens", back="/api-tokens")
                else:
                    self._page(200, title=record.get("name", ""), body=token_pages.detail_body(
                        record, self.session["csrf"], self.CTX.state_dir(), ok=self.query.get("ok", [""])[0]),
                        active="api_tokens", back="/api-tokens")
            else:
                query = self.query.get("q", [""])[0][:100].strip()
                selected = self.query.get("status", [""])[0]
                if selected not in ("", "active", "expired", "revoked"):
                    selected = ""
                self._page(200, title=t("web.tokens.title"), body=token_pages.list_body(records, query, selected),
                           active="api_tokens", wide=True)

        def _tokens_post(self, post: dict):
            t = i18n.t
            path = api_tokens.path_for(self.CTX.user_path())
            csrf = self.session["csrf"]
            if self.route == "/api-tokens/new":
                values = {key: post.get(key, "") for key in ("name", "expiry", "custom", "sms_per_hour", "sms_per_day")}
                values["permissions"] = [p for p in token_pages.PERMISSIONS if post.get("permission_" + p) == "1"]
                values["agent_replies"] = post.get("agent_replies") == "1"
                error = self._check_current(post.get("password", "")[:users.MAX_PASSWORD])
                if not error:
                    try:
                        name = values["name"].strip()
                        if not name or len(name) > 100 or not values["permissions"]:
                            raise ValueError("invalid name or permissions")
                        hour, day = int(values["sms_per_hour"]), int(values["sms_per_day"])
                        if not (1 <= hour <= 100000 and 1 <= day <= 100000):
                            raise ValueError("invalid limits")
                        expiry = token_pages.expiry_from_form(values["expiry"], values["custom"])
                        secret, record = api_tokens.create(name, expires_at=expiry,
                            permissions=values["permissions"], limits={"sms_per_hour": hour, "sms_per_day": day},
                            agent_replies=values["agent_replies"], path=path)
                    except (ValueError, OSError):
                        error = i18n.th("web.tokens.invalid")
                if error:
                    self._page(400, title=t("web.tokens.create"), body=token_pages.new_body(csrf, error=error, values=values),
                               active="api_tokens", back="/api-tokens")
                    return
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
                host = host if re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", host) else "localhost"
                scheme = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"
                url = f"{scheme}://{host}/api/agents.md"
                self._page(200, title=t("web.tokens.created_ok"), body=token_pages.created_body(secret, record, url),
                           active="api_tokens", back="/api-tokens")
                return
            digest = post.get("id", "")
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                self._page(404, title=t("web.tokens.title"), body=f'<p>{i18n.th("web.tokens.missing")}</p>', active="api_tokens")
                return
            error = self._check_current(post.get("password", "")[:users.MAX_PASSWORD])
            if not error:
                try:
                    changed = api_tokens.update(digest, path=path, revoke=self.route == "/api-tokens/revoke",
                        agent_replies=post.get("agent_replies") == "1" if self.route == "/api-tokens/agent-replies" else None)
                    if changed is None:
                        error = i18n.th("web.tokens.missing")
                except (OSError, ValueError):
                    error = i18n.th("web.tokens.invalid")
            if error:
                records = api_tokens.list_records(path=path)
                record = next((r for r in records if r["sha256"] == digest), None)
                body = token_pages.detail_body(record, csrf, self.CTX.state_dir(), error=error) if record else f'<p class="error">{token_pages.e(error)}</p>'
                self._page(400, title=t("web.tokens.title"), body=body, active="api_tokens", back="/api-tokens")
                return
            self._redirect("/api-tokens/detail?id=" + digest + "&ok=1")

        def _email(self):
            """FR-13 y FR-14: /email/<cuenta> es la lista de recibidos y enviados; /email/<cuenta>/ver?e=<evento>
            o ?s=<Message-ID>, uno con su conversación."""
            t = i18n.t
            rest = self.route[len("/email/"):]
            account_id, _, view = rest.partition("/")
            accounts, _ = self.CTX.mail_accounts()
            match = next((a for a in accounts if a["id"] == account_id), None)
            if match is None or view not in ("", "ver"):
                self._page(404, title=t("web.notfound.h1"), body="", icon_name="warn")
                return
            received = mail.mail_events(self.CTX.ledger_path(), account_id, self.CTX.known_ids())
            sent = thread.sent_rows(thread.parse_sent_logs(self.CTX.state_dir() / "sent.log"), account_id)
            rows = thread.mailbox(received, sent)
            kw = dict(active="email", active_account=account_id)
            if view == "":
                try:
                    offset = int(self.query.get("desde", ["0"])[0])
                except ValueError:
                    offset = 0
                chunk, nxt = mail.page_of(rows, offset)
                head = mail_pages.account_head(account_id, removable=not match["agent"],
                                               ok=self.query.get("ok", [""])[0])
                self._page(200, title=match["email"], icon_name="mail",
                           body=head + mail_pages.list_body(account_id, chunk, len(rows), offset, nxt), wide=True, **kw)
                return
            # FR-14: un recibido por su evento (?e=), un enviado por su Message-ID (?s=).
            event_id, sent_id = self.query.get("e", [""])[0], self.query.get("s", [""])[0]
            if sent_id:
                row = next((r for r in rows if r["kind"] == "out" and r["message_id"] == sent_id), None)
            else:
                row = next((r for r in rows if r["kind"] == "in" and r["event_id"] == event_id), None)
            if row is None:
                self._page(404, title=match["email"], icon_name="mail", back=f"/email/{account_id}",
                           body=f'<p class="lead">{i18n.th("web.mail.not_found")}</p>', **kw)
                return
            # PRD #455: todo el hilo, completo, con una sola conexión de la cuenta.
            convo = thread.conversation(rows, row, own=match["email"])
            try:
                env = mail.env_for(account_id, self.CTX.accounts_file, self.CTX.env_path())
                loaded = thread.load(env, convo, connect=self.CTX.imap_connect, uidvalidity=self.CTX.imap_uidvalidity)
            except mail.MailError as exc:
                loaded = {thread.key(r): {"error": exc} for r in convo}
            mine = loaded.get(thread.key(row), {})
            # Un recibido que no se pudo leer es un 502, como antes; un enviado sin copia es normal.
            failed = row["kind"] == "in" and "message" not in mine
            if failed:
                code = getattr(mine.get("error"), "code", "gone")
                sys.stderr.write(f"paynani-web: no se abrió {event_id}: {code}\n")
            self._page(502 if failed else 200, title=match["email"], icon_name="mail", back=f"/email/{account_id}",
                       body=mail_pages.thread_page(account_id, row, convo, loaded, own=match["email"],
                                                   own_name=mail.sender_name(account_id, self.CTX.accounts_file,
                                                                             self.CTX.env_path())), **kw)

        def _offset(self) -> int:
            try:
                return max(0, int(self.query.get("desde", ["0"])[0]))
            except ValueError:
                return 0

        def _sms_state(self, store) -> str:
            """FR-6: ¿el teléfono emparejado acepta órdenes del dueño?"""
            if not store.device():
                return messages_pages.PHONE_NONE
            return messages_pages.PHONE_OK if store.accepts("owner") else messages_pages.PHONE_OLD

        def _sms_region(self, store) -> str | None:
            """La región del teléfono emparejado (FR-2), o la de la instalación."""
            import re as _re
            import phone as phone_mod
            for sim in (store.device() or {}).get("sims") or []:
                country = str((sim or {}).get("country") or "").strip().upper()
                if _re.fullmatch(r"[A-Z]{2}", country):
                    return country
            return phone_mod.default_region()

        def _sms_offline_ttl(self, state: str) -> int:
            """FR-7: con el teléfono emparejado pero desconectado, los minutos en que vence
            una orden; 0 si está conectado (o no hay a quién mandar)."""
            from ..sms import health, outgoing
            if state != messages_pages.PHONE_OK:
                return 0
            facts = health.phone_facts(self.CTX.state_dir())
            return 0 if facts and facts["online"] else outgoing.DEFAULT_TTL_MIN

        def _sms_optout(self, notice: str = "", error: str = "", value: str = "", code: int = 200):
            """GET /messages/bajas (PRD #491 FR-13): la lista de bajas de la API."""
            from ..sms import api_replies
            from ..sms import store as sms_store
            store = sms_store.Store(self.CTX.state_dir())
            try:
                rows = api_replies.listing(store)
            except (OSError, ValueError):
                rows, error, code = [], error or i18n.t("web.sms.optout.err.unreadable"), 500
            if not notice:
                done = self.query.get("ok", [""])[0]
                notice = i18n.t(f"web.sms.optout.ok_{done}") if done in ("added", "removed") else ""
            self._page(code, title=i18n.t("web.sms.optout.title"), back="/messages",
                       body=messages_pages.optout_body(rows, self.session["csrf"], notice, error, value),
                       active="messages", icon_name="inbox")

        def _sms_optout_post(self, post: dict):
            """POST /messages/bajas: `accion=agregar|quitar` y `n`. CSRF y Origin, como todo POST."""
            from ..sms import api_replies, outgoing
            from ..sms import store as sms_store
            store = sms_store.Store(self.CTX.state_dir())
            raw = post.get("n", "").strip()[:40]
            action = post.get("accion", "")
            if action not in ("agregar", "quitar"):
                self._sms_optout(error=i18n.t("web.sms.optout.err.action"), value=raw, code=400)
                return
            try:
                number = outgoing.normalize(raw, self._sms_region(store))
            except outgoing.Refused:
                self._sms_optout(error=i18n.t("web.sms.err.invalid_number"), value=raw, code=400)
                return
            try:
                changed = api_replies.set_opt_out(store, number, action == "agregar", by=f"web:{self.ip}")
            except (OSError, ValueError):
                self._sms_optout(error=i18n.t("web.sms.optout.err.unreadable"), value=raw, code=500)
                return
            if changed:
                self._api_audit("opt_out" if action == "agregar" else "opt_in", secrets.token_hex(8), "", self.ip)
            self._redirect("/messages/bajas?ok=" + ("added" if action == "agregar" else "removed"))

        def _sms_statuses(self):
            """GET /messages/estados?n=<número> (PRD #489 FR-5): el estado de cada mensaje
            de la web en la conversación, para que sms.js los actualice sin recargar."""
            from ..sms import store as sms_store
            from ..sms import thread as sms_thread
            store = sms_store.Store(self.CTX.state_dir())
            number = self.query.get("n", [""])[0]
            items = [i for i in sms_thread.items(store, self.CTX.state_dir() / "events.jsonl", calls=True)
                     if number and i["number"] == number]
            body = {"count": len(items),
                    "offline": bool(self._sms_offline_ttl(self._sms_state(store))),
                    "items": [{"id": i["id"], "status": i["status"],
                               "label": messages_pages.status_label(i["status"], i.get("error", ""))}
                              for i in items if i.get("id", "").startswith("w_")]}
            self._send(200, "application/json; charset=UTF-8", json.dumps(body, ensure_ascii=False).encode("utf-8"),
                       [("Cache-Control", "no-store")])

        def _messages(self, values: dict | None = None, error: str = "", code: int = 200):
            """FR-17 y FR-18: /messages, las conversaciones; /messages/ver?n=<número>, una;
            /messages/nuevo, «Nuevo SMS» (PRD #489 FR-2). `values` y `error` vuelven a
            pintar un envío que no salió."""
            from ..sms import cli as sms_cli
            from ..sms import config as sms_config
            from ..sms import store as sms_store
            from ..sms import thread as sms_thread
            t = i18n.t
            store = sms_store.Store(self.CTX.state_dir())
            names = self.CTX.phone_names()
            state = self._sms_state(store)
            pause_min = sms_config.web_agent_pause_min()
            csrf = self.session["csrf"]
            kw = dict(active="messages", icon_name="inbox")
            if self.route == "/messages/nuevo" or (values is not None and not values.get("desde_hilo")):
                self._page(code, title=t("web.sms.new"), back="/messages",
                           body=messages_pages.new_body(csrf, state, pause_min, names, values, error), **kw)
                return
            items = sms_thread.items(store, self.CTX.state_dir() / "events.jsonl", calls=True)
            if self.route == "/messages":
                convs = sms_thread.conversations(items)
                offset = self._offset()
                chunk = convs[offset:offset + messages_pages.PAGE]
                nxt = offset + messages_pages.PAGE if offset + messages_pages.PAGE < len(convs) else None
                self._page(200, title=t("web.nav.messages"),
                           body=messages_pages.list_body(chunk, names, offset, nxt, len(convs), state), wide=True, **kw)
                return
            number = (values or {}).get("n") or self.query.get("n", [""])[0]
            mine = [i for i in items if i["number"] == number]
            if not number or (not mine and values is None):
                self._page(404, title=t("web.nav.messages"), back="/messages",
                           body=f'<p class="lead">{i18n.th("web.sms.thread_empty")}</p>', **kw)
                return
            who = names.get(number) or next((i["name"] for i in mine if i["name"]), "") or number
            reply = messages_pages.reply_box(number, csrf, state, pause_min, number in names, values, error)
            notice = t("web.sms.queued_ok") if self.query.get("ok", [""])[0] == "queued" and values is None else ""
            self._page(code, title=t("web.nav.messages"), back="/messages",
                       body=messages_pages.thread_body(number, who, mine, self._offset(),
                                                       sms_cli.human_pause(store, number), reply, notice,
                                                       self._sms_offline_ttl(state)), **kw)

        def _sms_send(self, post: dict):
            """POST /messages/enviar (PRD #489 FR-1 a FR-4b, FR-8, FR-9): la orden del dueño.
            El CSRF y el Origin ya los revisó do_POST, como en todo PaynaniWeb."""
            from urllib.parse import quote as _quote
            from ..sms import config as sms_config
            from ..sms import outgoing
            from ..sms import store as sms_store
            th = i18n.th
            store = sms_store.Store(self.CTX.state_dir())
            values = {"n": post.get("n", "").strip()[:40], "text": post.get("text", "")[:outgoing.MAX_TEXT + 1],
                      "pause": post.get("pause") == "1", "desde_hilo": post.get("desde_hilo") == "1"}
            if self._sms_state(store) != messages_pages.PHONE_OK:
                self._messages(values, "", 409)
                return
            try:
                number = outgoing.normalize(values["n"], self._sms_region(store))
            except outgoing.Refused:
                self._messages(values, th("web.sms.err.invalid_number"), 400)
                return
            if values["desde_hilo"]:
                values["n"] = number
            # FR-3: fuera del roster pide la contraseña de la web, con el bloqueo de la entrada.
            if number not in self.CTX.phone_names():
                error = self._check_current(post.get("current", "")[:users.MAX_PASSWORD])
                if error:
                    self._messages(values, error, 403)
                    return
            pause = sms_config.web_agent_pause_min() if values["pause"] else 0
            try:
                outgoing.queue(store, to=number, text=values["text"].replace("\r\n", "\n"), origin="owner",
                               source=self.ip, agent_pause_min=pause, per_hour=sms_config.web_sms_per_hour())
            except outgoing.Refused as exc:
                if exc.code == "rate_limited":
                    message = th("web.sms.err.rate_limited", n=sms_config.web_sms_per_hour(),
                                 when=messages_pages.local_time(exc.retry_at or ""))
                elif exc.code in ("empty_text", "text_too_long", "invalid_number"):
                    message = th(f"web.sms.err.{exc.code}", n=outgoing.MAX_TEXT)
                else:
                    message = str(exc)
                self._messages(values, message, 429 if exc.code == "rate_limited" else 400)
                return
            self._redirect(f"/messages/ver?n={_quote(number, safe='')}&ok=queued#responder")

        # ---- Agregar y quitar cuentas (FR-16, Q23) --------------------------------
        def _accounts_page(self, code: int, body: str, active_account: str = ""):
            self._page(code, title=i18n.t("web.nav.email"), body=body, active="email",
                       active_account=active_account, icon_name="mail", back="/email/main")

        def _removable(self, account_id: str) -> dict | None:
            accounts, _ = self.CTX.mail_accounts()
            return next((a for a in accounts if a["id"] == account_id and not a["agent"]), None)

        def _accounts_get(self):
            csrf = self.session["csrf"]
            if self.route == "/cuentas/nueva":
                self._accounts_page(200, accounts_pages.add_body(csrf))
                return
            account_id = self.route[len("/cuentas/"):-len("/quitar")]
            account = self._removable(account_id)
            if account is None:
                self._accounts_page(404, f'<p class="lead">{i18n.th("web.acct.agent_fixed")}</p>')
                return
            self._accounts_page(200, accounts_pages.remove_body(csrf, account), account_id)

        def _account_notice(self, kind: str, account_id: str, email: str):
            when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
            what = i18n.t(f"web.acctmail.what_{kind}", email=email, id=account_id)
            self.CTX.notifier.owner(self.user, i18n.t(f"web.acctmail.{kind}", email=email),
                                    i18n.t("web.acctmail.body", ip=self.ip, when=when, what=what))

        def _accounts_post(self, post: dict):
            from .. import accounts_cli
            th = i18n.th
            csrf = self.session["csrf"]
            # Q23: la contraseña de la web antes de agregar o quitar, con el bloqueo de T3.
            web_error = self._check_current(post.get("current", "")[:users.MAX_PASSWORD])
            if self.route == "/cuentas/nueva":
                values = {k: post.get(k, "")[:accounts_pages.MAX_FIELD]
                          for k in ("id", "email", "from_name", "imap_host", "imap_port", "smtp_host", "smtp_port", "mailbox")}
                password = post.get("account_password", "")[:1024].strip("\r\n")

                def again(code, error, steps=None):
                    # Nunca vuelve la contraseña de la cuenta en el formulario.
                    self._accounts_page(code, accounts_pages.add_body(csrf, values, error, steps))

                if web_error:
                    again(403, web_error.replace(i18n.th("web.profile.err.current"), th("web.acct.web_password_bad")))
                    return
                if not password:
                    again(400, th("web.acct.no_password"))
                    return
                if any(c in password for c in "\r\n\0"):
                    # Antes de probar o escribir: va a una línea del .env (revisión de #446).
                    again(400, th("web.acct.password_newline"))
                    return
                try:
                    prep = self.CTX.account_ops.prepare_add(
                        values["id"].strip(), values["email"], values["imap_host"], values["imap_port"] or 993,
                        values["smtp_host"], values["smtp_port"] or 465, values["from_name"],
                        [values["mailbox"].strip()] if values["mailbox"].strip() else None)
                except accounts_cli.AccountOpError as exc:
                    again(400, str(exc))
                    return
                entry = prep["entry"]
                steps = []
                imap = self.CTX.probe_imap(entry["imap"]["host"], entry["imap"]["port"], entry["email"], password)
                steps.append((i18n.t("web.acct.probe_imap"), imap["steps"]))
                ok = imap["ok"]
                if ok and entry.get("smtp"):
                    smtp = self.CTX.probe_smtp(entry["smtp"]["host"], entry["smtp"]["port"], entry["email"], password)
                    steps.append((i18n.t("web.acct.probe_smtp"), smtp["steps"]))
                    ok = smtp["ok"]
                if not ok:
                    again(400, th("web.acct.probe_failed"), steps)
                    return
                try:
                    self.CTX.account_ops.commit_add(prep, password)
                except accounts_cli.AccountOpError as exc:
                    again(500, str(exc), steps)
                    return
                started = self.CTX.account_ops._service("enable", entry["id"])
                self._account_notice("added", entry["id"], entry["email"])
                self._redirect(f"/email/{entry['id']}?ok={'added' if started else 'added_noservice'}")
                return
            account_id = self.route[len("/cuentas/"):-len("/quitar")]
            account = self._removable(account_id)
            if account is None:
                self._accounts_page(404, f'<p class="lead">{th("web.acct.agent_fixed")}</p>')
                return
            if web_error:
                self._accounts_page(403, accounts_pages.remove_body(
                    csrf, account, web_error.replace(i18n.th("web.profile.err.current"), th("web.acct.web_password_bad"))),
                    account_id)
                return
            try:
                self.CTX.account_ops.remove_account(account_id)
            except accounts_cli.AccountOpError as exc:
                self._accounts_page(400, accounts_pages.remove_body(csrf, account, str(exc)), account_id)
                return
            self._account_notice("removed", account_id, account["email"])
            self._redirect("/email/main?ok=removed")

        # ---- Profile (FR-21) -------------------------------------------------------
        def _profile_page(self, code: int, body: str):
            self._page(code, title=i18n.t("web.nav.profile"), body=body, icon_name="profile",
                       back="/" if self.route == "/profile" else "/profile")

        def _profile_get(self):
            csrf = self.session["csrf"]
            if self.route == "/profile/info":
                self._profile_page(200, profile_pages.info_body(self.user, csrf))
            elif self.route == "/profile/password":
                self._profile_page(200, profile_pages.password_body(csrf))
            else:
                self._profile_page(200, profile_pages.main_body(self.user, self.query.get("ok", [""])[0]))

        def _check_current(self, password: str) -> str:
            """"" si la contraseña actual es buena; si no, el texto del error. Cuenta como
            un intento de entrada: el bloqueo de T3 vale también aquí."""
            left = self.CTX.lockout.admit(self.ip)
            if left:
                return i18n.th("web.profile.err.locked", min=max(1, (left + 59) // 60))
            if not users.verify_password(password, self.user["password"]):
                return i18n.th("web.profile.err.current")
            self.CTX.lockout.success(self.ip)
            return ""

        def _profile_post(self, post: dict):
            th = i18n.th
            csrf = self.session["csrf"]
            path = self.CTX.user_path()
            if self.route == "/profile/info":
                name = post.get("name", "").strip()
                email = post.get("email", "").strip()
                values = {"name": name, "email": email}
                if email.lower() != str(self.user.get("email", "")).lower():
                    error = self._check_current(post.get("current", "")[:users.MAX_PASSWORD])
                    if error:
                        self._profile_page(400, profile_pages.info_body(self.user, csrf, error, values))
                        return
                try:
                    users.update(path, name=name, email=email)
                except users.UserError:
                    self._profile_page(400, profile_pages.info_body(self.user, csrf, th("web.profile.err.invalid"), values))
                    return
                self._redirect("/profile?ok=info")
                return
            current = post.get("current", "")[:users.MAX_PASSWORD]
            new = post.get("new", "")[:users.MAX_PASSWORD + 1]
            again = post.get("again", "")[:users.MAX_PASSWORD + 1]
            error = self._check_current(current)
            if not error and new != again:
                error = th("web.profile.err.mismatch")
            if not error and users.password_problem(new):
                error = th("web.profile.err.short", min=users.MIN_PASSWORD)
            if not error and new == current:
                error = th("web.profile.err.same")
            if error:
                self._profile_page(400, profile_pages.password_body(csrf, error))
                return
            updated = users.set_password(new, path)
            # FR-21: las otras sesiones se cierran; la de quien la cambió sigue.
            self.CTX.sessions.rebind(self.session["sid"], updated)
            self.CTX.sessions.drop_others(self.session["sid"])
            self._redirect("/profile?ok=password")

        # ---- Roster (FR-20) -----------------------------------------------------
        def _rq(self, kind: str, **fields) -> dict:
            """Un pedido de §11 al servicio del roster, como lo haría PaynaniApp."""
            import secrets as _secrets
            msg = {"type": kind, "id": "q_" + _secrets.token_hex(16), **fields}
            return self.CTX.roster_service().handle(msg, f"web:{self.ip}")

        @staticmethod
        def _account(value: str):
            return None if value in ("", "main") else value

        def _roster_page(self, code: int, body: str):
            self._page(code, title=i18n.t("web.nav.roster"), body=body, active="roster", icon_name="roster",
                       back="/roster" if self.route != "/roster" else "")

        def _roster_get(self):
            th = i18n.th
            account = self._account(self.query.get("cuenta", [""])[0])
            accounts = self._rq("roster.accounts")
            acc_list = (accounts.get("data") or {}).get("accounts", []) if accounts["type"] == "result" else []
            if self.route == "/roster/reglas" and self.query.get("general", [""])[0] == "1":
                res = self._rq("rules.get_default")
                if res["type"] != "result":
                    self._roster_page(502, roster_pages.error_box(res))
                    return
                data = res["data"]
                self._roster_page(200, roster_pages.rules_body(
                    account, general=True, member=None, data=data, csrf=self.session["csrf"],
                    text=data["text"] or roster_pages.NEW_RULES, effective=data["effective"],
                    ok=self.query.get("ok", [""])[0]))
                return
            listing = self._rq("roster.list", account=account)
            if listing["type"] != "result":
                code = 404 if listing.get("code") == "not_found" else 502
                self._roster_page(code, roster_pages.account_picker(acc_list, account) + roster_pages.error_box(listing))
                return
            data = listing["data"]
            if self.route == "/roster":
                self._roster_page(200, roster_pages.list_body(acc_list, data, self.session["csrf"],
                                                              ok=self.query.get("ok", [""])[0]))
                return
            row_raw = self.query.get("fila", [""])[0]
            member = None
            if row_raw:
                member = next((m for m in data["members"] if str(m["row"]) == row_raw), None)
                if member is None:
                    self._roster_page(404, roster_pages.error_box({"code": "not_found", "field": "row"}))
                    return
            if self.route == "/roster/editar":
                self._roster_page(200, roster_pages.edit_body(account, data, member, self.session["csrf"]))
                return
            if member is None:
                self._roster_page(404, roster_pages.error_box({"code": "not_found", "field": "row"}))
                return
            if self.route == "/roster/quitar":
                if member.get("owner"):
                    self._roster_page(403, roster_pages.error_box({"code": "owner_row"}))
                    return
                self._roster_page(200, roster_pages.remove_body(account, data, member, self.session["csrf"]))
                return
            res = self._rq("rules.get", account=account, row=member["row"], roster_etag=data["etag"])
            if res["type"] != "result":
                self._roster_page(502, roster_pages.error_box(res))
                return
            rd = res["data"]
            self._roster_page(200, roster_pages.rules_body(
                account, general=False, member=member, data=rd, csrf=self.session["csrf"],
                text=rd["text"] or roster_pages.NEW_RULES, effective=rd["effective"], roster_etag=data["etag"],
                ok=self.query.get("ok", [""])[0]))

        def _roster_post(self, post: dict):
            from urllib.parse import urlencode
            acc_value = post.get("cuenta", "")
            account = self._account(acc_value)
            back = "/roster?" + urlencode({"cuenta": acc_value or "main"})
            try:
                row = int(post["fila"]) if post.get("fila") else None
            except ValueError:
                row = None
            if self.route == "/roster/guardar":
                # Como PaynaniApp: el número se normaliza a E.164 antes de mandarlo, con la
                # región de la instalación (PAYNANI_SMS_DEFAULT_REGION, MX si no). Uno que no
                # se puede normalizar va tal cual y el servicio lo rechaza con su campo.
                import phone as phone_mod
                region = phone_mod.default_region()
                phones = [phone_mod.to_e164(p.strip(), region) or p.strip()
                          for p in post.get("phones", "").split(",") if p.strip()]
                member = {"name": post.get("name", "").strip(), "email": post.get("email", "").strip(),
                          "type": post.get("type", "").strip(), "github": post.get("github", "").strip(),
                          "phones": phones}
                res = self._rq("roster.save", account=account, row=row, member=member, etag=post.get("etag", ""))
                if res["type"] == "result":
                    self._redirect(back + "&ok=saved")
                    return
                listing = self._rq("roster.list", account=account)
                data = listing.get("data") or {"etag": post.get("etag", ""), "members": []}
                current = next((m for m in data.get("members", []) if m["row"] == row), None) if row else None
                self._roster_page(409 if res.get("code") == "conflict" else 400, roster_pages.edit_body(
                    account, data, current, self.session["csrf"], error=res, values=member))
                return
            if self.route == "/roster/quitar":
                res = self._rq("roster.delete", account=account, row=row, etag=post.get("etag", ""))
                if res["type"] == "result":
                    self._redirect(back + "&ok=removed")
                    return
                self._roster_page(409 if res.get("code") == "conflict" else 400,
                                  roster_pages.error_box(res) + f'<p><a href="{back}">{i18n.th("web.roster.back")}</a></p>')
                return
            # /roster/reglas: vista previa o guardar.
            general = post.get("general") == "1"
            text = post.get("text", "").replace("\r\n", "\n")
            action = post.get("accion", "vista")
            member = None
            if not general:
                listing = self._rq("roster.list", account=account)
                members = (listing.get("data") or {}).get("members", [])
                member = next((m for m in members if m["row"] == row), None)
                if member is None:
                    self._roster_page(404, roster_pages.error_box({"code": "not_found", "field": "row"}))
                    return
            if action == "guardar":
                if general:
                    res = self._rq("rules.save_default", text=text, etag=post.get("etag", ""))
                else:
                    res = self._rq("rules.save", account=account, row=row, text=text, etag=post.get("etag", ""),
                                   roster_etag=post.get("roster_etag", ""))
                if res["type"] == "result":
                    params = {"general": 1} if general else {"cuenta": acc_value or "main", "fila": row}
                    self._redirect("/roster/reglas?" + urlencode({**params, "ok": "rules_saved"}))
                    return
                error, effective = res, ""
            else:
                if general:
                    from .. import rules as rules_mod
                    from ..roster_edit import EditError
                    try:
                        rules_mod.parse(text)
                        error, effective = None, rules_mod.effective(text, None)
                    except EditError as exc:
                        error, effective = {"type": "error", **exc.as_error()}, ""
                else:
                    res = self._rq("rules.preview", account=account, row=row, text=text,
                                   roster_etag=post.get("roster_etag", ""))
                    error = None if res["type"] == "result" else res
                    effective = (res.get("data") or {}).get("effective", "") if error is None else ""
            data = {"exists": True, "etag": post.get("etag", "")}
            self._roster_page(200 if error is None else 400, roster_pages.rules_body(
                account, general=general, member=member, data=data, csrf=self.session["csrf"], text=text,
                effective=effective, roster_etag=post.get("roster_etag", ""), error=error))

        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def do_POST(self):  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                if urlparse(self.path).path == "/api/agent":
                    self._api_reply(413, secrets.token_hex(8), code="body_too_large",
                                    message="Request body is too large.")
                else:
                    self._send(413, "text/plain; charset=UTF-8", b"")
                return
            raw = self.rfile.read(length) if length else b""
            self._begin()
            if self.route == "/api/agent":
                self._api_post(raw)
                return
            if self.user is None:
                self._html(200, setup_page(self.lang))
                return
            if not self._same_origin():
                self._html(403, message_page(self.lang, "web.title", "web.forbidden.h1", "web.forbidden.lead"))
                return
            post = form_fields(raw)
            if self.route == "/login":
                self._login(post)
                return
            if not self.session:
                self._to_login("expired" if self.sid else "")
                return
            if not auth.check_csrf(self.session, post.get("csrf", "")):
                self._html(403, message_page(self.lang, "web.title", "web.forbidden.h1", "web.forbidden.lead"))
                return
            if self.route == "/logout":
                self.CTX.sessions.drop(self.session["sid"])
                self._redirect("/login?msg=out", [self._cookie(auth.SESSION_COOKIE, "", 0)])
                return
            self.dispatch_post(post)

        def dispatch_post(self, post: dict):
            if self.route in ("/api-tokens/new", "/api-tokens/revoke", "/api-tokens/agent-replies"):
                self._tokens_post(post)
                return
            if self.route == "/messages/enviar":
                self._sms_send(post)
                return
            if self.route == "/messages/bajas":
                self._sms_optout_post(post)
                return
            if self.route in ("/roster/guardar", "/roster/quitar", "/roster/reglas"):
                self._roster_post(post)
                return
            if self.route in ("/profile/info", "/profile/password"):
                self._profile_post(post)
                return
            if self.route == "/cuentas/nueva" or (self.route.startswith("/cuentas/") and self.route.endswith("/quitar")):
                self._accounts_post(post)
                return
            self._html(405, message_page(self.lang, "web.title", "web.method.h1"))

        def _login(self, post: dict):
            email = post.get("email", "")[:320]
            next_path = safe_next(post.get("next", "/"))
            # El intento se reserva antes de verificar (revisión de Metis en #439).
            left = self.CTX.lockout.admit(self.ip)
            if left:
                minutes = max(1, (left + 59) // 60)
                self._html(429, login_page(self.lang, email=email, next_path=next_path,
                                           error=i18n.th("web.login.locked", min=minutes)))
                return
            password = post.get("password", "")[:users.MAX_PASSWORD]
            if not auth.verify_login(self.user, email, password):
                # admit() ya lo contó: no se cuenta dos veces.
                self._html(401, login_page(self.lang, email=email, next_path=next_path,
                                           error=i18n.th("web.login.bad")))
                return
            self.CTX.lockout.success(self.ip)
            if self.sid:
                self.CTX.sessions.drop(self.sid)  # una sesión nueva en cada entrada
            agent = self.headers.get("User-Agent", "")
            sid = self.CTX.sessions.create(self.ip, self.user, agent)
            # «Último ingreso» de Profile (FR-21), como el /dash.
            try:
                users.update(self.CTX.user_path(), last_login_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                             last_login_ip=self.ip)
            except (users.UserError, OSError):
                pass
            if auth.remember_ip(self.CTX.user_path(), self.ip):
                when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
                self.CTX.notifier.owner(self.user, i18n.t("web.mail.newip.subject"),
                                        i18n.t("web.mail.newip.body", name=self.user.get("name", ""), when=when,
                                               ip=self.ip, agent=agent[:200] or "-"))
            self._redirect(next_path, [self._cookie(auth.SESSION_COOKIE, sid, None)])

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


def serve(host: str = "127.0.0.1", port: int = 8771, user_file: Path | None = None,
          ctx: Context | None = None) -> Server:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("PaynaniWeb only listens on loopback; it is reached through the SMS gateway")
    ctx = ctx or Context(user_file)
    server = Server((host, port), make_handler(ctx))
    server.ctx = ctx
    return server
