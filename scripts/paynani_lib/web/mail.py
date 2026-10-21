"""
Email Accounts (PRD #434 FR-13 a FR-15): los correos que recibió cada cuenta, y
uno abierto.

- **La lista** (FR-13) sale del ledger (`state/lifecycle.jsonl`), que guarda de cada
  aviso el sobre (remitente, asunto, hora, si el remitente está en el roster) y sus
  estados, nunca el cuerpo. Una entrada por evento, la más reciente primero, de 50
  en 50.
- **Abrir uno** (FR-14) pide ese correo a IMAP en ese momento, con el login de su
  cuenta, y no guarda nada. Se verifica igual que `fetch_verified` (`event_cli.py`):
  el mismo buzón y `UIDVALIDITY`, el UID exacto, y que `From` y `Message-ID`
  coincidan con el sobre. Sin la barrera del roster, que es del agente: aquí lo lee
  el dueño. Se muestra como texto: del HTML sólo queda el texto, sin imágenes ni
  enlaces activos.
- **Sólo muestra** (FR-15): nada aquí cambia un estado ni contesta.
"""
from __future__ import annotations

import email
import email.policy
import re
import sys
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
for _p in (str(_REPO / "harness"), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import event as event_mod  # noqa: E402
import ledger  # noqa: E402

from .. import accounts  # noqa: E402

PAGE = 50
MAX_TEXT = 200_000   # caracteres que se muestran de un cuerpo; el resto se avisa


class MailError(RuntimeError):
    """Por qué no se pudo abrir el correo. `code` es la clave `web.mail.err.<code>`
    del texto que ve el dueño; `detail`, un dato sin secretos (el tipo de error)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def mail_events(ledger_path: Path, account_id: str, known_ids: set[str]) -> list[dict]:
    """
    Los correos de una cuenta, el más reciente primero: el sobre que el listener
    guardó al verlo y el último estado. `account_id` es `main` para la del agente.
    """
    envelopes: dict[str, dict] = {}
    state: dict[str, tuple[str, str]] = {}
    for record in ledger.records(ledger_path):
        event_id = str(record.get("event_id") or "")
        if not event_id.startswith("imap:"):
            continue
        envelope = record.get("envelope")
        if isinstance(envelope, dict) and event_id not in envelopes \
                and envelope.get("event_type", event_mod.MAIL_RECEIVED) == event_mod.MAIL_RECEIVED:
            envelopes[event_id] = envelope
        state[event_id] = (str(record.get("state") or ""), str(record.get("at") or ""))
    out = []
    for event_id, envelope in envelopes.items():
        try:
            owner = str(envelope.get("account_id") or "") or accounts.parse_event_id(event_id, known_ids=known_ids)[0]
        except accounts.AccountsError:
            continue
        if owner != account_id:
            continue
        sender = envelope.get("sender") or {}
        last, last_at = state.get(event_id, ("", ""))
        out.append({
            "event_id": event_id,
            "sender_name": str(sender.get("name") or ""),
            "sender_address": str(sender.get("address") or ""),
            "subject": str(envelope.get("subject") or ""),
            "observed_at": str(envelope.get("observed_at") or ""),
            "sent_at": str(envelope.get("sent_at") or ""),
            "roster": bool(envelope.get("roster_match")),
            "state": last,
            "state_at": last_at,
            "envelope": envelope,
        })
    out.sort(key=lambda r: (r["observed_at"], r["event_id"]), reverse=True)
    return out


def page_of(rows: list[dict], offset: int, size: int = PAGE) -> tuple[list[dict], int | None]:
    """(filas, siguiente offset o None)."""
    offset = max(0, offset)
    chunk = rows[offset:offset + size]
    nxt = offset + size if offset + size < len(rows) else None
    return chunk, nxt


class _Text(HTMLParser):
    """El texto de un HTML: sin scripts, estilos, imágenes ni enlaces activos. Un
    enlace deja su texto y, entre paréntesis, la dirección, para que se vea a dónde
    iba sin que se pueda abrir con un clic."""

    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "hr", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.href: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")
        if tag == "a":
            self.href.append(dict(attrs).get("href") or "")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        if tag == "a" and self.href:
            href = self.href.pop()
            if href and href.startswith(("http://", "https://", "mailto:")):
                self.parts.append(f" ({href})")
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _Text()
    parser.feed(markup or "")
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def body_text(message) -> tuple[str, str]:
    """(texto, de dónde salió: «plain», «html» o «none»). La primera parte
    text/plain que no sea adjunto; si no hay, la primera text/html como texto."""
    html_part = None
    for part in message.walk() if message.is_multipart() else [message]:
        kind = part.get_content_type()
        if "attachment" in (part.get("Content-Disposition") or "").lower():
            continue
        if kind == "text/plain":
            return _decode(part), "plain"
        if kind == "text/html" and html_part is None:
            html_part = part
    if html_part is not None:
        return html_to_text(_decode(html_part)), "html"
    return "", "none"


def _decode(part) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def attachments(message) -> list[str]:
    names = []
    for part in message.walk():
        if "attachment" in (part.get("Content-Disposition") or "").lower() or \
                (part.get_filename() and part.get_content_maintype() != "text"):
            names.append(str(part.get_filename() or part.get_content_type()))
    return names


def _norm(address: str) -> str:
    return (address or "").strip().lower()


def fetch(envelope: dict, env: dict, *, connect=None, uidvalidity=None) -> dict:
    """
    El correo de `envelope`, leído de IMAP con `env` (el login de su cuenta). Lanza
    MailError con la razón si no es exactamente ese correo. `connect` y
    `uidvalidity` son los de idle_listener; las pruebas pasan otros.
    """
    if connect is None or uidvalidity is None:
        import idle_listener
        connect = connect or idle_listener.connect
        uidvalidity = uidvalidity or idle_listener.uidvalidity
    import idle_listener
    configured = _norm(idle_listener.lookup(env, "user", default=""))
    if configured != _norm(str(envelope.get("account") or "")):
        raise MailError("account")
    try:
        conn = connect(env)
    except SystemExit as exc:
        raise MailError("login") from exc
    except Exception as exc:  # noqa: BLE001 -- red, TLS, DNS: se dice cuál
        raise MailError("connect", type(exc).__name__) from exc
    try:
        mailbox = str(envelope.get("mailbox") or "INBOX")
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            raise MailError("mailbox", mailbox)
        if str(uidvalidity(conn, mailbox) or "") != str(envelope.get("uidvalidity") or ""):
            raise MailError("uidvalidity")
        uid = str(envelope.get("uid") or "")
        if not uid.isdigit():
            raise MailError("nouid")
        typ, payload = conn.uid("fetch", uid, "(BODY.PEEK[])")
        if typ != "OK" or not payload or not isinstance(payload[0], tuple):
            raise MailError("gone")
        meta = payload[0][0]
        if isinstance(meta, bytes) and not re.search(rb"\bUID\s+" + uid.encode("ascii") + rb"\b", meta):
            raise MailError("uid")
        message = email.message_from_bytes(payload[0][1], policy=email.policy.compat32)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass

    verify(message, envelope)
    return message_dict(message)


def verify(message, envelope: dict) -> None:
    """Que el mensaje leído sea el del sobre: el mismo `From` y, si el sobre lo trae, el
    mismo `Message-ID`. Lanza MailError si no."""
    import idle_listener
    senders = getaddresses([message.get("From", "")])
    actual = _norm(senders[0][1]) if senders else ""
    if actual != _norm((envelope.get("sender") or {}).get("address", "")):
        raise MailError("from")
    expected_mid = _norm(str(envelope.get("message_id") or ""))
    actual_mid = _norm(idle_listener.decode_hdr(message.get("Message-ID")))
    if expected_mid and actual_mid != expected_mid:
        raise MailError("mid")


def message_dict(message) -> dict:
    """Lo que la página muestra de un mensaje ya verificado: cabeceras, texto y adjuntos."""
    import idle_listener
    text, source = body_text(message)
    truncated = len(text) > MAX_TEXT
    try:
        date = parsedate_to_datetime(message.get("Date")).isoformat() if message.get("Date") else ""
    except (TypeError, ValueError):
        date = ""
    return {
        "from": idle_listener.decode_hdr(message.get("From")),
        "to": idle_listener.decode_hdr(message.get("To")),
        "cc": idle_listener.decode_hdr(message.get("Cc")),
        "subject": idle_listener.decode_hdr(message.get("Subject")),
        "date": date,
        "message_id": _norm(idle_listener.decode_hdr(message.get("Message-ID"))),
        "text": text[:MAX_TEXT],
        "truncated": truncated,
        "source": source,
        "attachments": attachments(message),
    }


def env_for(account_id: str, accounts_file: Path | None, env_path: Path) -> dict:
    """El login de la cuenta: el del .env para `main`, o el de accounts.json con la
    contraseña que nombra en el .env. Nunca el del agente para otra cuenta."""
    import idle_listener
    try:
        env = idle_listener.load_env(env_path)
    except OSError as exc:
        raise MailError("env", type(exc).__name__) from exc
    if account_id == accounts.MAIN:
        return env
    try:
        return accounts.env_for(accounts.get(account_id, accounts_file), env)
    except (accounts.AccountsError, KeyError, ValueError) as exc:
        raise MailError("account_gone", type(exc).__name__) from exc
