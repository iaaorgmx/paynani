"""
The himalaya v2 account tables, in the shape INSTALL.md 4.3 gives.

One generator for both writers: `paynani account add` (an extra mailbox,
[accounts.paynani-<id>]) and the sudo installer's user half (the main mailbox,
[accounts.paynani]). The only difference between the two outputs is the account
name and `default = true` on the main one; everything else, including the
`mailbox.alias.inbox` line that v2 will not work without, is written once here.
"""

from __future__ import annotations

import json
import shlex


def toml_string(value: str) -> str:
    """A TOML basic string is a JSON string for the text used here."""
    return json.dumps(value)


def secret_command(env_secret_script, env_file, key: str) -> str:
    """The command himalaya runs to read the password: a 600 file read by
    `env_secret.py`, never the keyring (INSTALL.md 4.3). Absolute paths only."""
    return ("python3 " + shlex.quote(str(env_secret_script)) + " "
            + shlex.quote(str(env_file)) + " " + key)


def account_block(name: str, email: str, imap: dict | None, smtp: dict | None,
                  secret: str, default: bool = False) -> str:
    """
    The [accounts.<name>] tables. `imap` and `smtp` are {"host": ..., "port": ...}
    or empty; a protocol without a server is left out, as it always was.
    """
    lines = [f"[accounts.{name}]", f"email = {toml_string(email)}"]
    if default:
        lines.append("default = true")
    lines += ['mailbox.alias.inbox = "INBOX"', ""]
    for protocol, scheme, default_port, server in (("imap", "imaps", 993, imap),
                                                    ("smtp", "smtps", 465, smtp)):
        if not server:
            continue
        url = f"{scheme}://{server['host']}:{server.get('port') or default_port}"
        lines += [
            f"[accounts.{name}.{protocol}]",
            f"server = {toml_string(url)}",
            f"[accounts.{name}.{protocol}.sasl.plain]",
            f"authcid = {toml_string(email)}",
            f"password.cmd = {toml_string(secret)}",
            "",
        ]
    return "\n".join(lines)
