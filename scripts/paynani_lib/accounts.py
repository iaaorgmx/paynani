"""
Additional mail accounts (#276, part 1: #279).

The agent's own account stays in `.env`, exactly as before. Every other
account a host watches -- `ventas@`, `soporte@` of a small business -- is one
entry in `accounts.json`, next to that `.env`:

    {
      "schema_version": 1,
      "accounts": [
        {"id": "ventas", "email": "ventas@dominio.com",
         "imap": {"host": "mail.dominio.com", "port": 993},
         "smtp": {"host": "mail.dominio.com", "port": 465},
         "password_env": "PAYNANI_ACCOUNT_VENTAS_PASSWORD",
         "roster": "rosters/ventas.md",
         "mailboxes": ["INBOX"], "enabled": true}
      ]
    }

The file never holds a password. `password_env` names a key in `.env`, so the
secret lives in the one file this project already protects, and himalaya reads
it through the same `env_secret.py` command it uses for the main account.

This module is the contract the other parts build on: the listener (#280), the
services (#281), `account add`/`remove` (#282), `send.sh --account` and
`event show` (#283), and `doctor` (#284). A malformed file is refused whole,
naming the account and the field, rather than half-used: a listener started on
an account that was only partly understood is a mailbox watched wrong.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))
from paths import env_file  # noqa: E402

FILENAME = "accounts.json"
SCHEMA_VERSION = 1
MAX_ACCOUNTS = 10
MAIN = "main"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
ENV_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
DEFAULT_MAILBOXES = ("INBOX",)


class AccountsError(ValueError):
    """accounts.json exists and cannot be used as written."""


def accounts_path(environ=None, home=None) -> Path:
    """`accounts.json` beside the `.env` this host resolves to."""
    return env_file(environ, home).parent / FILENAME


def password_key(account_id: str) -> str:
    """The `.env` key `account add` writes an account's password under."""
    return "PAYNANI_ACCOUNT_" + account_id.upper().replace("-", "_") + "_PASSWORD"


def _port(value, where):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 65536:
        raise AccountsError(f"{where}: port must be an integer between 1 and 65535")
    return value


def _inside(value, field, where, example):
    """`value` must be a relative path that stays inside the directory of accounts.json."""
    text = value.strip()
    if Path(text).is_absolute() or text.startswith("~") or ".." in Path(text).parts:
        raise AccountsError(
            f"{where}: `{field}` must be a relative path inside the directory of "
            f"accounts.json, e.g. {example}")


def _server(account, key, where, required):
    server = account.get(key)
    if server is None and not required:
        return None
    if not isinstance(server, dict) or not str(server.get("host") or "").strip():
        raise AccountsError(f"{where}: `{key}.host` is required")
    host = str(server["host"]).strip()
    if host.isdigit():
        raise AccountsError(f"{where}: `{key}.host` is {host!r}, which is a port, not a hostname")
    return {"host": host, "port": _port(server.get("port"), f"{where} {key}")}


def validate(data) -> list[dict]:
    """The accounts in a parsed `accounts.json`, normalised, or AccountsError."""
    if not isinstance(data, dict):
        raise AccountsError("the top level must be an object with an `accounts` list")
    version = data.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise AccountsError(f"schema_version {version!r} is not supported (expected {SCHEMA_VERSION})")
    raw = data.get("accounts", [])
    if not isinstance(raw, list):
        raise AccountsError("`accounts` must be a list")
    if len(raw) > MAX_ACCOUNTS:
        raise AccountsError(f"{len(raw)} accounts; the limit is {MAX_ACCOUNTS} per agent")
    seen = set()
    out = []
    for index, account in enumerate(raw):
        where = f"account #{index + 1}"
        if not isinstance(account, dict):
            raise AccountsError(f"{where}: must be an object")
        account_id = account.get("id")
        if not isinstance(account_id, str) or not ID_PATTERN.match(account_id):
            raise AccountsError(
                f"{where}: `id` must match {ID_PATTERN.pattern} (lowercase letters, digits, dashes)")
        where = f"account {account_id!r}"
        if account_id == MAIN:
            raise AccountsError(f"{where}: `main` is reserved for the account in .env")
        if account_id in seen:
            raise AccountsError(f"{where}: `id` is repeated")
        seen.add(account_id)
        address = str(account.get("email") or "").strip()
        if "@" not in address:
            raise AccountsError(f"{where}: `email` is required")
        password_env = account.get("password_env")
        if not isinstance(password_env, str) or not ENV_KEY_PATTERN.match(password_env):
            raise AccountsError(f"{where}: `password_env` must name a .env key, e.g. {password_key(account_id)}")
        mailboxes = account.get("mailboxes", list(DEFAULT_MAILBOXES))
        if (not isinstance(mailboxes, list) or not mailboxes
                or not all(isinstance(m, str) and m.strip() for m in mailboxes)):
            raise AccountsError(f"{where}: `mailboxes` must be a non-empty list of names")
        roster = account.get("roster", f"rosters/{account_id}.md")
        if not isinstance(roster, str) or not roster.strip():
            raise AccountsError(f"{where}: `roster` must be a path")
        # Relative, and inside the directory of accounts.json. This file decides
        # who an account may write to (#283) and `account remove` moves it
        # (#282); a roster at /etc/passwd or ../../x would put either somewhere
        # nobody meant. Iris's review of #285.
        _inside(roster, "roster", where, f"rosters/{account_id}.md")
        signature = account.get("signature_file")
        if signature is not None:
            if not isinstance(signature, str) or not signature.strip():
                raise AccountsError(f"{where}: `signature_file` must be a path")
            # Same rule as the roster: send.sh --account reads this file into every
            # message that leaves the account, so it stays inside the directory (#283).
            _inside(signature, "signature_file", where, f"signatures/{account_id}.txt")
        enabled = account.get("enabled", True)
        if not isinstance(enabled, bool):
            raise AccountsError(f"{where}: `enabled` must be true or false")
        out.append({
            "id": account_id,
            "email": address,
            "from_name": str(account.get("from_name") or "").strip(),
            "imap": _server(account, "imap", where, required=True),
            "smtp": _server(account, "smtp", where, required=False),
            "password_env": password_env,
            "roster": roster.strip(),
            "signature_file": signature.strip() if isinstance(signature, str) else None,
            "mailboxes": [m.strip() for m in mailboxes],
            "enabled": enabled,
        })
    return out


def load(path: Path | None = None) -> list[dict]:
    """Every configured account. No file means none; a bad file is an error."""
    path = accounts_path() if path is None else Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise AccountsError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AccountsError(f"{path} is not valid JSON: {exc}") from exc
    try:
        return validate(data)
    except AccountsError as exc:
        raise AccountsError(f"{path}: {exc}") from exc


def get(account_id: str, path: Path | None = None) -> dict:
    for account in load(path):
        if account["id"] == account_id:
            return account
    raise AccountsError(f"no account {account_id!r} in {accounts_path() if path is None else path}")


def roster_path(account: dict, path: Path | None = None) -> Path:
    """The account's roster, inside the directory of accounts.json (validate() checked)."""
    base = (accounts_path() if path is None else Path(path)).parent
    return base / account["roster"]


def signature_path(account: dict, path: Path | None = None) -> Path | None:
    """The account's own signature file, inside the directory of accounts.json, or None.

    An additional account never borrows the agent's signature (PAYNANI_SIGNATURE_FILE):
    a message from `ventas@` is not signed by the agent (#283)."""
    if not account.get("signature_file"):
        return None
    base = (accounts_path() if path is None else Path(path)).parent
    return base / account["signature_file"]


def password(account: dict, env: dict) -> str:
    """The account's password from the parsed .env. Never print this."""
    value = str(env.get(account["password_env"]) or "").strip()
    if not value:
        raise AccountsError(
            f"account {account['id']!r}: {account['password_env']} is not set in the env file")
    return value


def mailboxes(account: dict) -> list[str]:
    return list(account.get("mailboxes") or DEFAULT_MAILBOXES)


def env_for(account: dict, env: dict) -> dict:
    """
    The account as the keys `idle_listener.connect()` reads, so every part logs
    in through the one function that already knows the traps (the legacy
    schema, a port where a host should be, a rejected login).
    """
    imap = account["imap"]
    return {
        "PAYNANI_IMAP_HOST": imap["host"],
        "PAYNANI_IMAP_PORT": str(imap.get("port") or 993),
        "PAYNANI_EMAIL": account["email"],
        "PAYNANI_PASSWORD": password(account, env),
    }


def event_id(account_id: str, mailbox: str, uidvalidity, uid) -> str:
    """
    `imap:<id>:<mailbox>:<uidvalidity>:<uid>` for an additional account.

    The main account keeps `imap:<mailbox>:<uidvalidity>:<uid>` (harness/event.py),
    so no ledger written before this has to change.
    """
    if account_id == MAIN:
        return f"imap:{mailbox}:{uidvalidity}:{uid}"
    if not ID_PATTERN.match(account_id or ""):
        raise AccountsError(f"{account_id!r} is not a valid account id")
    return f"imap:{account_id}:{mailbox}:{uidvalidity}:{uid}"


def parse_event_id(value: str, known_ids=None) -> tuple[str, str, str, str]:
    """
    (account_id, mailbox, uidvalidity, uid) from either form; account_id is
    `main` for the old four-part one. The last two fields are taken from the
    right because a mailbox name may itself contain `:`.

    That same freedom makes one case ambiguous: an old-format id whose mailbox
    is `lower:rest` reads like account `lower`. Pass `known_ids`, the ids in
    accounts.json, wherever they are at hand (`event show` has them), and a
    first field that is not a configured account stays part of the mailbox.
    """
    parts = str(value or "").split(":")
    if len(parts) < 4 or parts[0] != "imap":
        raise AccountsError(f"{value!r} is not an IMAP event id")
    uidvalidity, uid = parts[-2], parts[-1]
    middle = parts[1:-2]
    first = middle[0]
    if (len(middle) >= 2 and first != MAIN and ID_PATTERN.match(first)
            and (known_ids is None or first in known_ids)):
        return first, ":".join(middle[1:]), uidvalidity, uid
    return MAIN, ":".join(middle), uidvalidity, uid
