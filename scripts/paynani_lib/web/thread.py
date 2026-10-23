"""
Lo recibido y lo enviado de una cuenta, y la conversación de un correo, en
PaynaniWeb (PRD #434 FR-13 y FR-14; #435, decisión de Julian sobre Q44/Q-T5-1).

Como un webmail: una sola lista por cuenta y, al abrir un correo, solo su hilo.

- **Lo enviado** sale de `state/sent.log`, la única huella de cada envío de
  `send.sh` (#117: no deja copia en Enviados): a quién, Cc, Bcc, cuándo, el asunto,
  su Message-ID y la cuenta (`account=`, vacío para la del agente). `send.sh` no
  cambia (#442 cerrado), así que no hay `In-Reply-To` que seguir.
- **La conversación** de un correo son los correos de la misma cuenta, recibidos o
  enviados, con el mismo asunto normalizado (sin `Re:`/`Fw:` ni mayúsculas) y la
  misma otra persona: el remitente de un recibido, o un destinatario o Cc de un
  enviado. Sin contar la dirección de la propia cuenta. En orden de hora.
- **El texto de un enviado** se pide a IMAP, en Enviados, por su Message-ID, cuando
  el servidor guardó una copia (Gmail lo hace con lo que sale por su SMTP). Si no
  hay copia, la web lo dice. Nada se guarda en paynani.
"""
from __future__ import annotations

import email
import email.policy
import re
from email.utils import getaddresses
from pathlib import Path

from . import mail

FIELDS = ("to", "cc", "bcc", "subject", "message-id", "account")
SENT_NAMES = ("Sent", "Sent Items", "Sent Messages", "Enviados", "Elementos enviados", "[Gmail]/Sent Mail",
              "[Gmail]/Enviados", "INBOX.Sent", "INBOX/Sent")
MAX_THREAD = 50
MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s@]+>")


def parse_sent_log(path: Path) -> list[dict]:
    """Cada línea de sent.log como `{at, to, cc, bcc, subject, message-id, account}`."""
    out = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rec = {"at": parts[0]}
        for part in parts[1:]:
            key, sep, value = part.partition("=")
            if sep and key in FIELDS:
                rec[key] = value
        if rec.get("message-id"):
            out.append(rec)
    return out


def sent_log_paths(path: Path) -> list[Path]:
    """`sent.log` y sus copias rotadas, de la más vieja a la actual: `sent.log.N` …
    `sent.log.1` y después `sent.log`. `harness/rotate_logs.py` rota cada semana y
    guarda varias copias; sin ellas, lo enviado antes de la rotación desaparecía de
    Email Accounts (#470). Las copias se buscan por nombre, no por un número fijo."""
    path = Path(path)
    rotated = []
    for p in path.parent.glob(path.name + ".*"):
        suffix = p.name[len(path.name) + 1:]
        if suffix.isdigit():
            rotated.append((int(suffix), p))
    return [p for _, p in sorted(rotated, reverse=True)] + [path]


def parse_sent_logs(path: Path) -> list[dict]:
    """Todos los envíos de `sent.log` y de sus copias rotadas, en orden, sin repetir un
    Message-ID (#470)."""
    out, seen = [], set()
    for p in sent_log_paths(path):
        for rec in parse_sent_log(p):
            mid = rec["message-id"]
            if mid in seen:
                continue
            seen.add(mid)
            out.append(rec)
    return out


def norm_subject(subject: str) -> str:
    s = (subject or "").strip().lower()
    while True:
        new = re.sub(r"^(re|fw|fwd|rv|res)\s*:\s*", "", s)
        if new == s:
            return re.sub(r"\s+", " ", s)
        s = new


def _addresses(value: str) -> set[str]:
    return {a.strip().lower() for _, a in getaddresses([value or ""]) if a}


def sent_rows(sent: list[dict], account_id: str) -> list[dict]:
    """Los envíos de una cuenta como filas de la lista, junto a las de mail.mail_events."""
    account = "" if account_id == mail.accounts.MAIN else account_id
    out, seen = [], set()
    for rec in sent:
        mid = rec.get("message-id", "")
        if rec.get("account", "") != account or mid in seen:
            continue
        seen.add(mid)
        out.append({"kind": "out", "message_id": mid, "to": rec.get("to", ""), "cc": rec.get("cc", ""),
                    "bcc": rec.get("bcc", ""), "subject": rec.get("subject", ""), "at": rec.get("at", "")})
    return out


def mailbox(received: list[dict], sent: list[dict]) -> list[dict]:
    """Lo recibido (mail.mail_events) y lo enviado (sent_rows), el más reciente primero."""
    rows = [dict(r, kind="in", at=r["observed_at"]) for r in received] + list(sent)
    rows.sort(key=lambda r: (r["at"], r.get("event_id") or r.get("message_id", "")), reverse=True)
    return rows


def people(row: dict, own: str = "") -> set[str]:
    """La otra persona del correo: el remitente de un recibido; los de Para y Cc de un enviado."""
    if row["kind"] == "in":
        found = {(row.get("sender_address") or "").strip().lower()} - {""}
    else:
        found = _addresses(row.get("to", "")) | _addresses(row.get("cc", ""))
    return found - {(own or "").strip().lower()}


def conversation(rows: list[dict], row: dict, own: str = "") -> list[dict]:
    """
    El hilo de `row` dentro de `rows` (una cuenta, de mailbox()): mismo asunto
    normalizado y alguien en común, en orden de hora. Un correo sin asunto o sin
    otra persona es un hilo de uno.
    """
    subject, who = norm_subject(row.get("subject", "")), people(row, own)
    if not subject or not who:
        return [row]
    out = [r for r in rows if r is row or (norm_subject(r.get("subject", "")) == subject and people(r, own) & who)]
    out.sort(key=lambda r: (r["at"], r.get("event_id") or r.get("message_id", "")))
    if len(out) > MAX_THREAD:
        # Los más cercanos al que se abrió, sin dejarlo fuera.
        i = out.index(row)
        start = max(0, min(i - MAX_THREAD // 2, len(out) - MAX_THREAD))
        out = out[start:start + MAX_THREAD]
    return out


def _sent_folder(conn) -> str | None:
    """Enviados: el que se marca `\\Sent` (RFC 6154), o uno con un nombre conocido."""
    try:
        typ, data = conn.list()
    except Exception:  # noqa: BLE001
        return None
    if typ != "OK":
        return None
    names = []
    for raw in data or []:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        m = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if not m:
            continue
        name = m.group("name").strip().strip('"')
        if "\\sent" in m.group("flags").lower():
            return name
        names.append(name)
    lowered = {n.lower(): n for n in names}
    for candidate in SENT_NAMES:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def key(row: dict) -> str:
    """El id de un correo de la conversación: su evento si se recibió, `s:<Message-ID>` si se envió."""
    return row["event_id"] if row["kind"] == "in" else "s:" + row["message_id"]


def _by_uid(payload) -> dict:
    """`{UID: bytes}` de la respuesta a un `UID FETCH` de varios: cada parte trae su UID en la meta."""
    out = {}
    for part in payload or []:
        if not isinstance(part, tuple) or len(part) < 2:
            continue
        meta = part[0] if isinstance(part[0], bytes) else str(part[0]).encode()
        m = re.search(rb"\bUID\s+([0-9]+)", meta)
        if m:
            out[m.group(1).decode("ascii")] = part[1]
    return out


def _received(conn, rows: list[dict], env: dict, uidvalidity, out: dict) -> None:
    """Los recibidos, agrupados por buzón: un SELECT de solo lectura y un solo UID FETCH por buzón."""
    import idle_listener
    configured = (idle_listener.lookup(env, "user", default="") or "").strip().lower()
    boxes: dict[str, list[dict]] = {}
    for row in rows:
        envelope = row["envelope"]
        if configured != str(envelope.get("account") or "").strip().lower():
            out[key(row)] = {"error": mail.MailError("account")}
        elif not str(envelope.get("uid") or "").isdigit():
            out[key(row)] = {"error": mail.MailError("nouid")}
        else:
            boxes.setdefault(str(envelope.get("mailbox") or "INBOX"), []).append(row)
    for box, items in boxes.items():
        typ, _ = conn.select(box, readonly=True)
        if typ != "OK":
            for row in items:
                out[key(row)] = {"error": mail.MailError("mailbox", box)}
            continue
        current = str(uidvalidity(conn, box) or "")
        wanted = []
        for row in items:
            if current != str(row["envelope"].get("uidvalidity") or ""):
                out[key(row)] = {"error": mail.MailError("uidvalidity")}
            else:
                wanted.append(row)
        if not wanted:
            continue
        typ, payload = conn.uid("fetch", ",".join(str(r["envelope"]["uid"]) for r in wanted), "(BODY.PEEK[])")
        found = _by_uid(payload) if typ == "OK" else {}
        for row in wanted:
            raw = found.get(str(row["envelope"]["uid"]))
            if raw is None:
                out[key(row)] = {"error": mail.MailError("gone")}
                continue
            message = email.message_from_bytes(raw, policy=email.policy.compat32)
            try:
                mail.verify(message, row["envelope"])
            except mail.MailError as exc:
                out[key(row)] = {"error": exc}
                continue
            out[key(row)] = {"message": mail.message_dict(message)}


def _sent(conn, rows: list[dict], out: dict) -> None:
    """Los enviados, de Enviados por su Message-ID: un SEARCH por cada uno y un solo UID FETCH."""
    def all_fail(code):
        for row in rows:
            out[key(row)] = {"error": mail.MailError(code)}
    folder = _sent_folder(conn)
    if not folder:
        return all_fail("no_sent")
    quoted = '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
    typ, _ = conn.select(quoted, readonly=True)
    if typ != "OK":
        return all_fail("no_sent")
    uids = {}
    for row in rows:
        mid = row["message_id"]
        if not MESSAGE_ID.fullmatch(mid or ""):
            out[key(row)] = {"error": mail.MailError("no_copy")}
            continue
        typ, data = conn.uid("search", None, "HEADER", "Message-ID", mid)
        if typ == "OK" and data and data[0]:
            uids[key(row)] = data[0].split()[-1].decode("ascii", "replace")
        else:
            out[key(row)] = {"error": mail.MailError("no_copy")}
    if not uids:
        return
    typ, payload = conn.uid("fetch", ",".join(uids.values()), "(BODY.PEEK[])")
    found = _by_uid(payload) if typ == "OK" else {}
    for row in rows:
        uid = uids.get(key(row))
        if uid is None:
            continue
        raw = found.get(uid)
        message = email.message_from_bytes(raw, policy=email.policy.compat32) if raw is not None else None
        if message is None or (message.get("Message-ID") or "").strip().lower() != row["message_id"].lower():
            out[key(row)] = {"error": mail.MailError("no_copy")}
            continue
        out[key(row)] = {"message": mail.message_dict(message)}


def load(env: dict, convo: list[dict], *, connect=None, uidvalidity=None) -> dict:
    """
    Todo el hilo de una cuenta con una sola conexión (PRD #455, 4.3): `{key(row): {"message":
    dict}}` para cada mensaje que se pudo leer y `{key(row): {"error": MailError}}` para el
    que no, con su razón, sin tumbar el resto. Los recibidos se leen del INBOX y los
    enviados de Enviados, siempre de solo lectura y con `BODY.PEEK[]`: nada queda leído ni
    se mueve, y nada se guarda.
    """
    if connect is None or uidvalidity is None:
        import idle_listener
        connect = connect or idle_listener.connect
        uidvalidity = uidvalidity or idle_listener.uidvalidity
    out: dict = {}
    if not convo:
        return out
    try:
        conn = connect(env)
    except SystemExit:
        return {key(r): {"error": mail.MailError("login")} for r in convo}
    except Exception as exc:  # noqa: BLE001 -- red, TLS, DNS: se dice cuál
        return {key(r): {"error": mail.MailError("connect", type(exc).__name__)} for r in convo}
    try:
        received = [r for r in convo if r["kind"] == "in"]
        sent = [r for r in convo if r["kind"] == "out"]
        if received:
            _received(conn, received, env, uidvalidity, out)
        if sent:
            _sent(conn, sent, out)
    except Exception as exc:  # noqa: BLE001 -- lo que falte lleva la razón; lo leído se queda
        for r in convo:
            out.setdefault(key(r), {"error": mail.MailError("connect", type(exc).__name__)})
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def fetch_texts(env: dict, message_ids: list[str], *, connect=None) -> dict:
    """
    `{Message-ID: texto}` de las copias que el servidor guardó en Enviados. Una que
    no está no sale en el resultado. Cualquier falla del servidor deja el resultado
    vacío: la web dice que no hay copia, no se cae.
    """
    ids = [m for m in message_ids if MESSAGE_ID.fullmatch(m or "")]
    if not ids:
        return {}
    if connect is None:
        import idle_listener
        connect = idle_listener.connect
    try:
        conn = connect(env)
    except (SystemExit, Exception):  # noqa: BLE001
        return {}
    out = {}
    try:
        folder = _sent_folder(conn)
        if not folder:
            return {}
        quoted = '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'
        typ, _ = conn.select(quoted, readonly=True)
        if typ != "OK":
            return {}
        for mid in ids:
            typ, data = conn.uid("search", None, "HEADER", "Message-ID", mid)
            if typ != "OK" or not data or not data[0]:
                continue
            uid = data[0].split()[-1].decode("ascii", "replace")
            typ, payload = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            message = email.message_from_bytes(payload[0][1], policy=email.policy.compat32)
            if (message.get("Message-ID") or "").strip().lower() != mid.lower():
                continue
            text, _ = mail.body_text(message)
            out[mid] = text[:mail.MAX_TEXT]
    except Exception:  # noqa: BLE001
        return out
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return out
