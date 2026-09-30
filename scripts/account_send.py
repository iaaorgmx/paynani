#!/usr/bin/env python3
"""
What `send.sh --account <id>` needs to know about an additional account (#283).

    account_send.py ENV_FILE ACCOUNT_ID

prints four lines -- the account's address, its display name (possibly empty),
the absolute path of its roster, and the path of its own signature file (empty
when it has none) -- and exits 0. Anything that means the
message must not go out (no such account, no SMTP server, an address that is not
one) says why on stderr and exits 2, the same code send.sh uses for a refusal.

It reads accounts.json from the directory of ENV_FILE, which is where
`paynani account add` wrote it, so a host that points send.sh at its .env with
ENV_FILE finds its accounts beside it. send.sh is bash and has no business
parsing JSON or deciding what a valid account is: accounts.py already does.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paynani_lib import accounts  # noqa: E402


def refuse(message: str) -> int:
    print(f"REFUSED: {message}", file=sys.stderr)
    print("Nothing was sent.", file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: account_send.py ENV_FILE ACCOUNT_ID", file=sys.stderr)
        return 2
    env_file, account_id = argv
    path = Path(env_file).expanduser().parent / accounts.FILENAME
    try:
        account = accounts.get(account_id, path)
    except accounts.AccountsError as exc:
        return refuse(str(exc))
    if not account.get("smtp"):
        return refuse(
            f"account {account_id!r} has no smtp server in {path}, so nothing can be sent from it. "
            "Add one with `paynani account remove` and `paynani account add … --smtp-host …`."
        )
    address = account["email"]
    if any(ch.isspace() for ch in address):
        return refuse(f"account {account_id!r} has an address with whitespace in it")
    # A display name lands in a header: a newline in it would start another one.
    from_name = " ".join(str(account.get("from_name") or "").split())
    signature = accounts.signature_path(account, path)
    print(address)
    print(from_name)
    print(accounts.roster_path(account, path))
    print(signature if signature else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
