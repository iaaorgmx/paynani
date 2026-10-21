#!/usr/bin/env python3
"""
A qué correo responde un envío: el valor de `send.sh --in-reply-to` (#435, Q-T5-1).

    python3 scripts/paynani_lib/reply_ref.py <event_id | <Message-ID>>

Imprime una línea, `<Message-ID>\\t<cuenta>`, y sale con 0. La cuenta es la que
recibió el correo (`main` para la del agente) cuando se dio un id de evento, y
vacía cuando se dio un Message-ID a mano. Con un valor que no sirve, lo dice en
stderr y sale con 2: send.sh no manda nada.

El id de evento es lo cómodo para el agente, que lo tiene en el aviso. El
Message-ID se toma del sobre que guardó el listener, nunca de algo que el correo
diga de sí mismo en el cuerpo. Sólo se aceptan Message-ID con la forma `<a@b>` y
sin espacios ni saltos de línea: van a un encabezado.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

MESSAGE_ID = re.compile(r"^<[^<>\s@]+@[^<>\s@]+>$")


def resolve(value: str) -> tuple[str, str]:
    """(Message-ID, cuenta). ValueError con la razón si no sirve."""
    value = (value or "").strip()
    if not value:
        raise ValueError("--in-reply-to needs an event id or a Message-ID")
    if value.startswith("<"):
        if not MESSAGE_ID.match(value):
            raise ValueError(f"{value!r} is not a Message-ID of the form <id@domain>")
        return value, ""
    if not value.startswith("imap:"):
        raise ValueError(f"{value!r} is neither an email event id (imap:…) nor a Message-ID (<id@domain>)")
    from paynani_lib import accounts, event_cli
    record = event_cli._find(value)
    if record is None:
        raise ValueError(f"event {value} is not in the journal or the ledger")
    message_id = str(record.get("message_id") or "").strip()
    if not MESSAGE_ID.match(message_id):
        raise ValueError(f"event {value} has no usable Message-ID")
    account_id = str(record.get("account_id") or "").strip()
    if not account_id:
        try:
            known = {a["id"] for a in accounts.load(event_cli._accounts_file())}
        except accounts.AccountsError:
            known = set()
        account_id = accounts.parse_event_id(value, known_ids=known)[0]
    return message_id, account_id or accounts.MAIN


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: reply_ref.py <event_id | <Message-ID>>", file=sys.stderr)
        return 2
    try:
        message_id, account_id = resolve(argv[0])
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"{message_id}\t{account_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
