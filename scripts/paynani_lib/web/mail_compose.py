"""
«New Email» de PaynaniWeb (#590 cambio 2): lo que la web revisa antes de mandar y la
puerta por la que manda.

El envío mismo es del núcleo (#591 N1, de Metis): `paynani_lib.owner_mail`, que sólo
llama PaynaniWeb. Aquí está la interfaz que usan las pantallas (`Mailer`), la de la
instalación (`CoreMailer`) y un `Fake` en memoria para las pruebas. `send.sh` no
cambia: el agente sigue limitado al roster.

Lo que la web hace antes de llamar al `Mailer`: separar y validar las direcciones de
Para, CC y CCO, y preguntar cuáles están fuera del roster de esa cuenta. Si hay alguna,
`app.py` pide la contraseña con el bloqueo de la entrada (Q5) antes de mandar.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import accounts

MAX_RECIPIENTS = 50
MAX_SUBJECT = 300
MAX_TEXT = 50_000
# Una sola dirección, sin nombre: lo que se escribe en Para, CC o CCO.
_ADDRESS = re.compile(r"[^\s@<>,;\"'()]+@[^\s@<>,;\"'()]+\.[^\s@<>,;\"'()]+")


class Refused(Exception):
    """El correo no sale. `code` es el motivo; `detail`, qué dirección o campo."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def split_addresses(raw: str) -> list[str]:
    """«a@x.mx, b@y.com; c@z.org» como lista, en minúsculas y sin repetir. Un salto de
    línea o algo que no es una dirección no pasa: no se puede colar un encabezado."""
    out: list[str] = []
    for part in re.split(r"[,;\s]+", raw or ""):
        part = part.strip()
        if not part:
            continue
        if not _ADDRESS.fullmatch(part):
            raise Refused("invalid_address", part[:80])
        low = part.lower()
        if low not in out:
            out.append(low)
    return out


def check(to: list[str], cc: list[str], bcc: list[str], subject: str, text: str) -> None:
    """La forma del correo, antes de pedir contraseña o mandar."""
    if not to:
        raise Refused("no_recipients")
    if len(to) + len(cc) + len(bcc) > MAX_RECIPIENTS:
        raise Refused("too_many", str(MAX_RECIPIENTS))
    subject = (subject or "").strip()
    if not subject or len(subject) > MAX_SUBJECT or "\r" in subject or "\n" in subject:
        raise Refused("subject")
    if not (text or "").strip() or len(text) > MAX_TEXT:
        raise Refused("text")


def roster_file(account_id: str, roster_path: Path, accounts_file: Path | None) -> Path:
    """El roster de la cuenta: `roster.md` para la del agente, `rosters/<id>.md` para las demás."""
    if account_id == accounts.MAIN:
        return Path(roster_path)
    return accounts.roster_path(accounts.get(account_id, accounts_file), accounts_file)


def address_book(path: Path) -> list[dict]:
    """Los contactos del roster con correo, para la libreta: `{name, email}` por nombre."""
    import roster as roster_mod
    try:
        entries = roster_mod.roster_entries(Path(path))
    except OSError:
        return []
    seen, out = set(), []
    for entry in entries:
        email = str(entry.get("address") or "").strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        out.append({"name": str(entry.get("name") or "").strip() or email, "email": email})
    return sorted(out, key=lambda c: c["name"].lower())


class Mailer:
    """La puerta del núcleo (#591 N1, `paynani_lib.owner_mail`), con sus mismas llamadas.

    - `outside_roster(account_id, addresses)`: las que no están en el roster de esa
      cuenta. Con eso la web decide si pide la contraseña (Q5).
    - `authorize(account_id, to, cc, bcc, by, owner_email, allow_outside)`: la web la llama
      en la misma petición; da un permiso de un solo uso ligado a esa cuenta, esos
      destinatarios y el dueño. `allow_outside` es verdadero sólo si la web revisó la
      contraseña (Q5). Si al mandar alguien quedó fuera del roster y el permiso no lo
      autorizó, `send()` responde `not_authorized` sin mandar (revisión de Ximena, #594).
    - `send(grant, subject, body)`: consume el permiso y manda. Devuelve un dict con
      `ok`, `code`, `message_id`, `sent_copy`, `outside_roster`, `notice` y `detail`,
      como el `Result` de N1."""

    def outside_roster(self, account_id: str, addresses: list[str]) -> list[str]:
        raise Refused("not_available")

    def authorize(self, account_id: str, to: list[str], cc: list[str], bcc: list[str], *, by: str,
                  owner_email: str, allow_outside: bool):
        raise Refused("not_available")

    def send(self, grant, subject: str, body: str) -> dict:
        raise Refused("not_available")


class CoreMailer(Mailer):
    """La de la instalación: `paynani_lib.owner_mail` (#591 N1). Mientras N1 no esté en
    main no manda nada, y la pantalla dice que todavía no se puede."""

    @staticmethod
    def _core():
        try:
            from .. import owner_mail
        except ImportError:
            raise Refused("not_available") from None
        return owner_mail

    @staticmethod
    def _account(account_id: str):
        return None if account_id == accounts.MAIN else account_id

    def _call(self, fn, *args, **kw):
        core = self._core()
        try:
            return fn(core)(*args, **kw)
        except getattr(core, "InvalidAddress", ()) as exc:
            raise Refused("invalid_address", str(exc)[:80]) from None
        except getattr(core, "UnknownAccount", ()) as exc:
            raise Refused("unknown_account", str(exc)[:80]) from None

    def outside_roster(self, account_id, addresses):
        return list(self._call(lambda c: c.outside_roster, self._account(account_id), addresses))

    def authorize(self, account_id, to, cc, bcc, *, by, owner_email, allow_outside):
        return self._call(lambda c: c.authorize, self._account(account_id), to, cc, bcc, by=by,
                          owner_email=owner_email, allow_outside=bool(allow_outside))

    def send(self, grant, subject, body):
        res = self._call(lambda c: c.send, grant, subject, body)
        return {"ok": bool(res.ok), "code": str(res.code), "message_id": str(res.message_id or ""),
                "sent_copy": str(res.sent_copy or ""), "outside_roster": list(res.outside_roster or []),
                "notice": str(getattr(res, "notice", "") or ""), "detail": str(res.detail or "")}


class Fake(Mailer):
    """En memoria, para las pruebas y la demostración. `book` es `{cuenta: [direcciones]}`:
    el roster de cada cuenta. Los permisos son de un solo uso, como en N1."""

    def __init__(self, book: dict[str, list[str]] | None = None, fail: str = ""):
        self.book = {k: [a.lower() for a in v] for k, v in (book or {}).items()}
        self.sent: list[dict] = []
        self.asked: list[tuple[str, list[str]]] = []
        self.grants: dict[int, dict] = {}
        self.fail = fail
        # Las pruebas lo usan para cambiar el roster entre authorize() y send().
        self.after_authorize = None
        # Lo que N1 devuelve después de mandar: la copia en Enviados y el aviso al dueño.
        self.sent_copy = "saved"
        self.notice = None

    def outside_roster(self, account_id, addresses):
        self.asked.append((account_id, list(addresses)))
        known = set(self.book.get(account_id, []))
        return [a for a in addresses if a.lower() not in known]

    def authorize(self, account_id, to, cc, bcc, *, by, owner_email, allow_outside):
        grant = len(self.grants) + 1
        self.grants[grant] = {"account_id": account_id, "to": list(to), "cc": list(cc), "bcc": list(bcc), "by": by,
                              "owner_email": owner_email, "allow_outside": bool(allow_outside)}
        if self.after_authorize:
            self.after_authorize()
        return grant

    def send(self, grant, subject, body):
        order = self.grants.pop(grant, None)
        if order is None:
            return {"ok": False, "code": "invalid_grant", "message_id": "", "sent_copy": "", "outside_roster": [],
                    "notice": "skipped", "detail": "grant used or unknown"}
        out = self.outside_roster(order["account_id"], list(dict.fromkeys(order["to"] + order["cc"] + order["bcc"])))
        if out and not order["allow_outside"]:
            return {"ok": False, "code": "not_authorized", "message_id": "", "sent_copy": "", "outside_roster": out,
                    "notice": "skipped", "detail": "outside the roster without the password"}
        if self.fail:
            return {"ok": False, "code": self.fail, "message_id": "", "sent_copy": "", "outside_roster": out,
                    "notice": "skipped", "detail": "smtp said no"}
        msgid = f"<web-{len(self.sent) + 1}@example.com>"
        self.sent.append(dict(order, subject=subject, body=body, message_id=msgid))
        notice = self.notice or ("sent" if out else "skipped")
        return {"ok": True, "code": "sent", "message_id": msgid, "sent_copy": self.sent_copy, "outside_roster": out,
                "notice": notice, "detail": ""}
