"""
The onboarding HTTP server: the page, the report, and the confirmation. Port
of webapp/index.php plus webapp/lib/guard.php's request handling, onto
http.server (standard library only).

Deliberately single-threaded (http.server.HTTPServer, not the Threading
variant): this serves one person filling in one form, and single-threaded
means "the current language for the duration of this request" (see i18n.py)
is unambiguous with no lock needed around the in-memory session store below.
"""

from __future__ import annotations

import html
import sys
from http import cookies
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))
from paths import repo_root  # noqa: E402

from . import guard, i18n
from .brand import brand_svg
from .envfile import ENV_FIELDS, read_env, render_env, write_env
from .probe import probe_imap, probe_smtp
from .validate import validate

PORT_HINTS = {
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT": "993",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT": "465",
}

COOKIE_NAME = "paynani_psid"
MAX_BODY_BYTES = 64 * 1024  # generous for 8 short fields; anything past it isn't this form

# Process-lifetime only: this server exists for one onboarding run and exits
# once the .env changes (see onboard.py), so there is nothing to persist
# beyond that and nothing to clean up on disk when it doesn't.
SESSIONS: dict[str, dict] = {}


def e(value) -> str:
    """htmlspecialchars, but short enough to use everywhere it is needed."""
    return html.escape("" if value is None else str(value), quote=True)


def _get_or_create_csrf(session: dict) -> str:
    if "csrf" not in session:
        session["csrf"] = guard.new_csrf_token()
    return session["csrf"]


def _resolve_lang(session: dict, post: dict, query: dict) -> str:
    asked = (post.get("lang") or (query.get("lang", [""])[0])).strip()
    if asked and i18n.lang_is_known(asked):
        session["lang"] = asked
        return asked
    held = session.get("lang", "")
    if held and i18n.lang_is_known(held):
        return held
    return i18n.LANG_DEFAULT


def make_handler(state_dir: Path):
    """A BaseHTTPRequestHandler bound to one state directory (where the
    one-time token lives). A factory rather than a module-level class because
    http.server.HTTPServer instantiates the handler itself, with no way to
    pass extra constructor arguments through."""

    class Handler(BaseHTTPRequestHandler):
        STATE_DIR = state_dir
        server_version = "paynani-onboard/1.0"

        # ---- plumbing -----------------------------------------------------

        def log_message(self, fmt, *args):  # noqa: A003
            # The default logs the full request line, including a query
            # string carrying the one-time token on the very first hit. Log
            # only the method and path, never the query, so the token never
            # reaches this process's stderr.
            path = self.path.split("?", 1)[0]
            sys.stderr.write(f"{self.address_string()} \"{self.command} {path}\"\n")

        def _client_ip(self) -> str:
            return self.client_address[0]

        def _session(self):
            jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
            morsel = jar.get(COOKIE_NAME)
            if morsel is not None and morsel.value in SESSIONS:
                return morsel.value, SESSIONS[morsel.value]
            return None, None

        def _new_session(self):
            sid = guard.new_session_id()
            SESSIONS[sid] = {}
            return sid, SESSIONS[sid]

        def _send(self, code: int, content_type: str, body: bytes, set_cookie: str | None = None, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in guard.SECURITY_HEADERS:
                self.send_header(name, value)
            if extra:
                for name, value in extra:
                    self.send_header(name, value)
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _plain(self, code: int, text: str):
            self._send(code, "text/plain; charset=UTF-8", text.encode("utf-8"))

        def _html(self, code: int, body: str, set_cookie: str | None = None):
            self._send(
                code,
                "text/html; charset=UTF-8",
                body.encode("utf-8"),
                set_cookie=set_cookie,
                extra=[("Content-Security-Policy", guard.CSP)],
            )

        def _redirect(self, location: str, set_cookie: str | None = None):
            # The redirect itself is the point: the token that got us here
            # lives in the query string, and this is what keeps it from being
            # carried into every later request and every later log line.
            self._send(
                303,
                "text/plain; charset=UTF-8",
                b"",
                set_cookie=set_cookie,
                extra=[("Location", location)],
            )

        def _refuse_loopback(self):
            self._plain(
                403,
                i18n.t("g.loopback_1") + "\n\n" + i18n.t("g.loopback_2") + "\n"
                "  ssh -L 8765:127.0.0.1:8765 tu-usuario@ese-host\n",
            )

        def _refuse_token(self):
            self._plain(403, i18n.t("g.token_1") + "\n\n" + i18n.t("g.token_2") + "\n")

        def _refuse_csrf(self):
            self._plain(400, i18n.t("g.csrf") + "\n")

        def _serve_static(self, rel_path: str, content_type: str) -> bool:
            asset_map = {
                "/assets/app.css": repo_root() / "webapp" / "assets" / "app.css",
                "/assets/lang.js": repo_root() / "webapp" / "assets" / "lang.js",
            }
            file = asset_map.get(rel_path)
            if file is None:
                return False
            try:
                data = file.read_bytes()
            except OSError:
                self.send_response(404)
                self.end_headers()
                return True
            self._send(200, content_type, data)
            return True

        # ---- verbs ----------------------------------------------------------

        def do_GET(self):  # noqa: N802
            # Loopback first, before anything else responds — including the
            # static assets below. Serving them to a non-loopback request
            # would not leak a credential, but it would break the one
            # invariant this guard promises ("even bound to 0.0.0.0 by
            # mistake, an off-machine request gets 403 and nothing else") and
            # would announce paynani to whoever reached the port.
            if not guard.is_loopback(self._client_ip()):
                self._refuse_loopback()
                return

            parsed = urlparse(self.path)
            if self._serve_static(parsed.path, self._static_content_type(parsed.path)):
                return
            if parsed.path != "/":
                self.send_response(404)
                self.end_headers()
                return

            query = parse_qs(parsed.query)
            sid, session = self._session()

            if session is None or not session.get("authenticated"):
                given = query.get("t", [""])[0]
                if guard.check_token(self.STATE_DIR, given):
                    sid, session = self._new_session()
                    session["authenticated"] = True
                    cookie = cookies.SimpleCookie()
                    cookie[COOKIE_NAME] = sid
                    cookie[COOKIE_NAME]["httponly"] = True
                    cookie[COOKIE_NAME]["samesite"] = "Strict"
                    cookie[COOKIE_NAME]["path"] = "/"
                    self._redirect("/", set_cookie=cookie[COOKIE_NAME].OutputString())
                    return
                self._refuse_token()
                return

            self._render(session, method="GET", post={}, query=query)

        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            if not guard.is_loopback(self._client_ip()):
                self._refuse_loopback()
                return

            sid, session = self._session()
            if session is None or not session.get("authenticated"):
                self._refuse_token()
                return

            # A malformed header must not raise (int() on garbage) and a huge
            # one must not be read in full: eight short fields never come
            # close to this, so a request that does is not this form.
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                length = 0
            length = max(0, min(length, MAX_BODY_BYTES))
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            post = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

            action = post.get("action", "")
            if action != "" and not guard.check_csrf(session, post.get("csrf", "")):
                self._refuse_csrf()
                return

            self._render(session, method="POST", post=post, query={})

        @staticmethod
        def _static_content_type(path: str) -> str:
            if path.endswith(".css"):
                return "text/css; charset=UTF-8"
            if path.endswith(".js"):
                return "application/javascript; charset=UTF-8"
            return "application/octet-stream"

        # ---- the form itself ------------------------------------------------

        def _render(self, session: dict, method: str, post: dict, query: dict):
            lang = _resolve_lang(session, post, query)
            i18n.set_current(lang)

            action = post.get("action", "") if method == "POST" else ""

            stored = read_env()
            stored_password = stored.get("AGENT_EMAIL_PASSWORD", "")

            values = dict(session.get("values", {}))
            for key in ENV_FIELDS:
                posted_now = action != "" and key in post
                if posted_now:
                    posted = post[key].strip()
                    if key != "AGENT_EMAIL_PASSWORD" or posted != "":
                        values[key] = posted

                # A blank box that was not just typed means "whatever is on
                # disk" — never for the password, which goes nowhere near
                # anything this page renders.
                if key != "AGENT_EMAIL_PASSWORD" and not posted_now and values.get(key, "") == "":
                    values[key] = stored.get(key, "")
                if values.get(key, "") == "":
                    values[key] = "" if key == "AGENT_EMAIL_PASSWORD" else PORT_HINTS.get(key, "")
                values.setdefault(key, "")

            effective = dict(values)
            if effective["AGENT_EMAIL_PASSWORD"] == "":
                effective["AGENT_EMAIL_PASSWORD"] = stored_password
            has_password = effective["AGENT_EMAIL_PASSWORD"] != ""

            errors: dict = {}
            report = None
            saved = None
            notice = None

            if action != "":
                if action != "lang":
                    errors = validate(effective)
                session["values"] = values

            if action == "setup" and not errors:
                imap = probe_imap(
                    values["AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST"],
                    int(values["AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT"]),
                    effective["AGENT_EMAIL_ACCOUNT"],
                    effective["AGENT_EMAIL_PASSWORD"],
                )
                smtp = probe_smtp(
                    values["AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST"],
                    int(values["AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT"]),
                    effective["AGENT_EMAIL_ACCOUNT"],
                    effective["AGENT_EMAIL_PASSWORD"],
                )
                report = {"imap": imap, "smtp": smtp, "ok": imap["ok"] and smtp["ok"]}

                if report["ok"]:
                    ok, where = write_env(render_env(effective))
                    if ok:
                        saved = where
                        session.pop("values", None)
                    else:
                        notice = where

            body = _page(
                lang=lang,
                saved=saved,
                notice=notice,
                report=report,
                errors=errors,
                values=values,
                has_password=has_password,
                csrf=_get_or_create_csrf(session),
            )
            self._html(200, body)

    return Handler


def _lang_options(current: str) -> str:
    out = []
    for tag, name in i18n.LANGUAGES.items():
        selected = " selected" if tag == current else ""
        out.append(f'<option value="{e(tag)}"{selected}>{e(name)}</option>')
    return "\n".join(out)


def _field_error(errors: dict, key: str) -> str:
    if key not in errors:
        return ""
    return f'<p class="err">{e(errors[key])}</p>'


def _steps_html(steps: list) -> str:
    out = []
    for s in steps:
        cls = "good" if s["ok"] else "fail"
        detail = f'<span class="detail">{e(s["detail"])}</span>' if s["detail"] else ""
        out.append(f'<li class="{cls}">{e(s["text"])}{detail}</li>')
    return "\n".join(out)


def _page(*, lang, saved, notice, report, errors, values, has_password, csrf) -> str:
    t, th = i18n.t, i18n.th
    logo = brand_svg("paynani-horizontal.svg")

    if saved is not None:
        body = f"""
<div class="topbar">
  <h1>{th('saved.h1')}</h1>
  <form method="get" action="/" class="langpick">
    <span class="combo">
      <select id="lang" name="lang" aria-label="{th('lang.label')}">
        {_lang_options(lang)}
      </select>
    </span>
    <button type="submit" id="langgo">{th('lang.apply')}</button>
  </form>
</div>

<p class="lead">{th('saved.lead')}</p>

<div class="panel ok">
  <p>{th('saved.where', path=saved)}</p>
</div>

<h2>{th('saved.next_h2')}</h2>
<p>{th('saved.next_p1')}</p>
<p>{th('saved.next_p2')}</p>

<p class="quiet">{th('saved.forgot')}</p>
"""
    else:
        notice_html = f'<div class="panel warn"><p>{e(notice)}</p></div>' if notice is not None else ""
        report_html = ""
        if report is not None:
            report_html = f"""
    <div class="panel bad">
      <h2>{th('report.h2')}</h2>
      <h3>{th('report.imap_h3')}</h3>
      <ul class="steps">
        {_steps_html(report['imap']['steps'])}
      </ul>
      <h3>{th('report.smtp_h3')}</h3>
      <ul class="steps">
        {_steps_html(report['smtp']['steps'])}
      </ul>
    </div>
"""
        body = f"""
<div class="topbar">
  <h1>{th('page.h1')}</h1>
  <div class="langpick">
    <span class="combo">
      <select id="lang" name="lang" form="setup" aria-label="{th('lang.label')}">
        {_lang_options(lang)}
      </select>
    </span>
    <button type="submit" name="action" value="lang" form="setup" formnovalidate id="langgo">{th('lang.apply')}</button>
  </div>
</div>

<p class="lead">{th('page.lead')}</p>

<details class="help">
  <summary>{th('help.summary')}</summary>

  <h3>{th('help.cpanel_h3')}</h3>
  <p>{th('help.cpanel_p')}</p>
  <ol>
    <li>{th('help.cpanel_li1')}</li>
    <li>{th('help.cpanel_li2')}</li>
    <li>{th('help.cpanel_li3')}</li>
    <li>{th('help.cpanel_li4')}</li>
  </ol>
  <p>{th('help.cpanel_after')}</p>

  <h3>{th('help.gmail_h3')}</h3>
  <p>{th('help.gmail_p1')}</p>
  <p>{th('help.gmail_p2')}</p>
  <p>{th('help.gmail_p3')}</p>

  <h3>{th('help.ms_h3')}</h3>
  <p>{th('help.ms_p1')}</p>
  <p>{th('help.ms_p2')}</p>

  <h3>{th('help.zoho_h3')}</h3>
  <p>{th('help.zoho_p')}</p>

  <h3>{th('help.fastmail_h3')}</h3>
  <p>{th('help.fastmail_p')}</p>

  <h3>{th('help.other_h3')}</h3>
  <p>{th('help.other_p1')}</p>
  <p>{th('help.other_p2')}</p>
</details>

{notice_html}

<form method="post" action="/" id="setup" autocomplete="off">
  <input type="hidden" name="csrf" value="{e(csrf)}">

  <fieldset>
    <legend>{th('form.account_legend')}</legend>

    <label for="account">{th('form.account_label')}</label>
    <input type="email" id="account" name="AGENT_EMAIL_ACCOUNT" required
           value="{e(values['AGENT_EMAIL_ACCOUNT'])}"
           placeholder="{th('form.account_ph')}">
    {_field_error(errors, 'AGENT_EMAIL_ACCOUNT')}
    <p class="hint">{th('form.account_hint')}</p>

    <label for="password">{th('form.password_label')}</label>
    <input type="password" id="password" name="AGENT_EMAIL_PASSWORD"
           {'' if has_password else 'required'}
           autocomplete="new-password"
           placeholder="{th('form.password_kept') if has_password else ''}">
    {_field_error(errors, 'AGENT_EMAIL_PASSWORD')}
    <p class="hint">{th('form.password_hint')}</p>

    <label for="fromname">{th('form.fromname_label')} <span class="opt">{th('form.optional')}</span></label>
    <input type="text" id="fromname" name="AGENT_EMAIL_FROM_NAME"
           value="{e(values['AGENT_EMAIL_FROM_NAME'])}" placeholder="{th('form.fromname_ph')}">
    {_field_error(errors, 'AGENT_EMAIL_FROM_NAME')}
    <p class="hint">{th('form.fromname_hint')}</p>
  </fieldset>

  <fieldset>
    <legend>{th('form.imap_legend')}</legend>
    <div class="row">
      <div class="grow">
        <label for="imaphost">{th('form.server')}</label>
        <input type="text" id="imaphost" name="AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST" required
               value="{e(values['AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST'])}"
               placeholder="{th('form.imap_host_ph')}">
      </div>
      <div class="narrow">
        <label for="imapport">{th('form.port')}</label>
        <input type="text" id="imapport" name="AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT" required
               inputmode="numeric" value="{e(values['AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT'])}">
      </div>
    </div>
    {_field_error(errors, 'AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST')}
    {_field_error(errors, 'AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT')}
    <p class="hint">{th('form.imap_hint')}</p>
  </fieldset>

  <fieldset>
    <legend>{th('form.smtp_legend')}</legend>
    <div class="row">
      <div class="grow">
        <label for="smtphost">{th('form.server')}</label>
        <input type="text" id="smtphost" name="AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST" required
               value="{e(values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST'])}"
               placeholder="{th('form.smtp_host_ph')}">
      </div>
      <div class="narrow">
        <label for="smtpport">{th('form.port')}</label>
        <input type="text" id="smtpport" name="AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT" required
               inputmode="numeric" value="{e(values['AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT'])}">
      </div>
    </div>
    {_field_error(errors, 'AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST')}
    {_field_error(errors, 'AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT')}
    <p class="hint">{th('form.smtp_hint')}</p>
  </fieldset>

  {report_html}

  <div class="actions">
    <button type="submit" name="action" value="setup" class="primary">{th('form.submit')}</button>
  </div>

  <p class="quiet">{th('form.footnote')}</p>
</form>
"""

    return f"""<!doctype html>
<html lang="{e(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{th('page.title')}</title>
<link rel="stylesheet" href="/assets/app.css">
<script src="/assets/lang.js" defer></script>
</head>
<body>
<main>

<div class="marca">{logo}</div>

{body}

</main>
</body>
</html>
"""
