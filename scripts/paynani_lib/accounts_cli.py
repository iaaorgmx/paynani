"""
`paynani account list` and `paynani account test <id>` (#279).

`add` and `remove` are #282. These two only read: `list` says what
accounts.json holds without a secret in it, and `test` proves one account can
log in, open each mailbox it will watch, and IDLE there, which is everything
the listener (#280) will need from it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "harness"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from paths import env_file  # noqa: E402
import roster as roster_mod  # noqa: E402

from . import accounts  # noqa: E402


def run_list(args) -> int:
    path = accounts.accounts_path()
    try:
        configured = accounts.load(path)
    except accounts.AccountsError as exc:
        print(f"accounts.json is not usable: {exc}", file=sys.stderr)
        return 1
    if not configured:
        print(f"no additional accounts (no {path.name} at {path.parent}, or it lists none)")
        return 0
    print(f"{len(configured)} additional account(s) in {path}  (limit {accounts.MAX_ACCOUNTS})")
    for account in configured:
        roster = accounts.roster_path(account, path)
        if roster.is_file():
            contacts = f"{len(roster_mod.roster_entries(roster))} contact(s)"
        else:
            contacts = "MISSING"
        state = "enabled" if account["enabled"] else "disabled"
        print(f"  {account['id']:<12} {account['email']:<32} {state:<9} "
              f"roster {account['roster']} ({contacts})")
    return 0


def _step(label, ok, detail=""):
    print(f"{'ok' if ok else 'FAIL':<5} {label}" + (f": {detail}" if detail else ""))
    return ok


def run_test(args, connect=None, load_env=None) -> int:
    import idle_listener  # the listener's own login, not a second copy of it

    connect = connect or idle_listener.connect
    load_env = load_env or idle_listener.load_env
    try:
        account = accounts.get(args.account_id)
    except accounts.AccountsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        env = accounts.env_for(account, load_env(env_file()))
    except (accounts.AccountsError, OSError) as exc:
        _step("credentials", False, str(exc))
        return 1
    imap = account["imap"]
    target = f"{account['email']} at {imap['host']}:{imap.get('port') or 993}"
    try:
        conn = connect(env)
    except SystemExit:
        # connect() has already said why on stderr (rejected login, a port
        # where the host should be); it exits rather than raises by design.
        _step("login", False, f"{target} (see the line above)")
        return 1
    except Exception as exc:  # network, TLS, DNS: say which, literally
        _step("login", False, f"{target}: {type(exc).__name__}: {exc}")
        return 1
    _step("login", True, target)
    ok = True
    try:
        for mailbox in accounts.mailboxes(account):
            typ, data = conn.select(mailbox, readonly=True)
            detail = (data[0].decode("utf-8", "replace") if data and isinstance(data[0], bytes)
                      else str(data))
            ok &= _step(f"select {mailbox}", typ == "OK",
                        f"{detail} message(s)" if typ == "OK" else detail)
        ok &= _step("IDLE", "IDLE" in conn.capabilities,
                    "" if "IDLE" in conn.capabilities else "server does not advertise IDLE")
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return 0 if ok else 1
