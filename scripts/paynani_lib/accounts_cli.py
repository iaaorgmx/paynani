"""
`paynani account list|test|add|remove` (#279, #282).

`list` says what accounts.json holds without a secret in it, and `test` proves
one account can log in, open each mailbox it will watch, and IDLE there, which
is everything the listener (#280) will need from it. Those two only read.

`add` and `remove` (#282) are the writers, and they keep four files in step:
accounts.json, the .env (the password, under the name accounts.json gives it),
the account's roster, and himalaya's config (so `send.sh --account` can send
from it, #283). `add` proves the login before it writes any of them, and asks
for the password with getpass: a password on argv sits in shell history and in
`ps`. `remove` never deletes a roster; it moves it aside.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "harness"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from paths import env_file  # noqa: E402
import roster as roster_mod  # noqa: E402

from . import accounts, envfile, himalaya_config  # noqa: E402
from .probe import probe_imap  # noqa: E402

try:
    from . import account_service  # noqa: E402  (part 3, #281)
except ImportError:  # a checkout from before #281: add/remove say so instead of guessing
    account_service = None


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


# ---------------------------------------------------------------------------
# add / remove (#282)
# ---------------------------------------------------------------------------

_YES = ("y", "yes", "s", "si", "sí")


def stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def himalaya_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "himalaya" / "config.toml"


def _print_steps(label, steps) -> None:
    print(f"  {label}:")
    for s in steps:
        detail = f" -- {s['detail']}" if s.get("detail") else ""
        print(f"    {'ok  ' if s['ok'] else 'FAIL'} {s['text']}{detail}")


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        answer = input(f"{prompt} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in _YES


def _service(action: str, account_id: str) -> bool:
    """Start or stop the account's listener service (#281). False says why on stderr."""
    if account_service is None:
        print(f"Service control is not in this checkout yet (#281): {action} "
              f"paynani-idle@{account_id}.service by hand.", file=sys.stderr)
        return False
    try:
        result = getattr(account_service, action)(account_id)
    except Exception as exc:  # noqa: BLE001 - whatever the service layer raises is reported, not hidden
        print(f"Could not {action} the service for {account_id!r}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, str):
        # account_service reports the state it left the service in (#281):
        # enable succeeded only if it is running; disable, only if it no longer is.
        print(f"  service paynani-idle@{account_id}: {result}")
        return result == "active" if action == "enable" else result != "active"
    return bool(result)


def _read_raw(path: Path) -> dict:
    """accounts.json as written (defaults not filled in), or an empty one. Call after load()."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"schema_version": accounts.SCHEMA_VERSION, "accounts": []}


def _write_bytes(path: Path, data: bytes, mode: int) -> None:
    """Temp file next to the target, then rename: a crash leaves the old file or the new, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    os.chmod(path, mode)


def _write_accounts(path: Path, data: dict) -> None:
    _write_bytes(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), 0o600)


def _env_edit(key: str, value) -> tuple[bool, str]:
    """
    Set `key` in the .env (`value` a string) or drop it (`value` None), touching no other line.

    envfile.render_env only knows the mailbox keys, so this edits the file line
    by line the way it does: comments, order and the file's own line ending survive.
    """
    path = envfile.env_path()
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            existing = fh.read()
    except FileNotFoundError:
        existing = ""
    newline = "\r\n" if "\r\n" in existing else "\n"
    lines = re.split(r"\r\n|\n|\r", existing.rstrip("\r\n")) if existing.strip() else []
    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    out, written = [], False
    for line in lines:
        if pattern.match(line):
            if value is not None and not written:
                out.append(f"{key}={value}")
                written = True
            continue
        out.append(line)
    if value is not None and not written:
        out.append(f"{key}={value}")
    return envfile.write_env(newline.join(out) + newline if out else "")


def _himalaya_name(account_id: str) -> str:
    return f"paynani-{account_id}"


def _himalaya_block(entry: dict) -> str:
    """The [accounts.paynani-<id>] tables, in the shape INSTALL.md 4.3 gives for the main account."""
    secret = himalaya_config.secret_command(_REPO_ROOT / "scripts" / "env_secret.py",
                                            envfile.env_path(), entry["password_env"])
    return himalaya_config.account_block(_himalaya_name(entry["id"]), entry["email"],
                                         entry.get("imap"), entry.get("smtp"), secret)


def _has_himalaya_section(text: str, name: str) -> bool:
    return re.search(r"^\s*\[accounts\." + re.escape(name) + r"(\.[^\]]*)?\]\s*$", text, re.M) is not None


def _without_himalaya_section(text: str, name: str) -> str:
    skip, out = False, []
    for line in text.splitlines(keepends=True):
        match = re.match(r"^\s*\[([^\]]+)\]\s*$", line.rstrip("\r\n"))
        if match:
            table = match.group(1).strip()
            skip = table == f"accounts.{name}" or table.startswith(f"accounts.{name}.")
        if not skip:
            out.append(line)
    return "".join(out)


def _write_himalaya(path: Path, text: str) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o600
    _write_bytes(path, text.encode("utf-8"), mode)


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


class _Undo:
    """What add must put back if a later write fails, so a half-added account is not left behind."""

    def __init__(self):
        self.files = {}      # path -> original bytes, or None when it did not exist
        self.created = []    # directories to drop again if empty

    def remember(self, path: Path) -> None:
        if path not in self.files:
            try:
                self.files[path] = path.read_bytes()
            except FileNotFoundError:
                self.files[path] = None

    def restore(self) -> None:
        for path, original in self.files.items():
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    _write_bytes(path, original, path.stat().st_mode & 0o777 if path.exists() else 0o600)
            except OSError:
                pass
        for directory in self.created:
            try:
                directory.rmdir()
            except OSError:
                pass


def run_add(args) -> int:
    account_id = str(args.id or "")
    if account_id == accounts.MAIN or not accounts.ID_PATTERN.match(account_id):
        print(f"Not added: {account_id!r} is not a usable id. Use lowercase letters, digits and dashes "
              f"({accounts.ID_PATTERN.pattern}); `{accounts.MAIN}` is the account in .env.", file=sys.stderr)
        return 1
    path = accounts.accounts_path()
    try:
        existing = accounts.load(path)
    except accounts.AccountsError as exc:
        print(f"Not added: accounts.json is not usable: {exc}", file=sys.stderr)
        return 1
    if any(account["id"] == account_id for account in existing):
        print(f"Not added: account {account_id!r} already exists. `paynani account remove {account_id}` first.",
              file=sys.stderr)
        return 1
    if len(existing) >= accounts.MAX_ACCOUNTS:
        print(f"Not added: there are already {len(existing)} additional accounts, and the limit is "
              f"{accounts.MAX_ACCOUNTS} per agent.", file=sys.stderr)
        return 1

    try:
        imap_port = int(args.imap_port or 993)
        smtp_port = int(args.smtp_port or 465)
    except (TypeError, ValueError):
        print("Not added: a port must be a number.", file=sys.stderr)
        return 1
    entry = {"id": account_id, "email": str(args.email or "").strip()}
    if str(getattr(args, "from_name", "") or "").strip():
        entry["from_name"] = args.from_name.strip()
    entry["imap"] = {"host": str(args.imap_host or "").strip(), "port": imap_port}
    if str(getattr(args, "smtp_host", "") or "").strip():
        entry["smtp"] = {"host": args.smtp_host.strip(), "port": smtp_port}
    entry["password_env"] = accounts.password_key(account_id)
    entry["roster"] = f"rosters/{account_id}.md"
    entry["mailboxes"] = list(getattr(args, "mailbox", None) or accounts.DEFAULT_MAILBOXES)
    entry["enabled"] = True
    if len(entry["mailboxes"]) > 1:
        # accounts.json allows a list (PRD, Q9), but idle_listener.py --account refuses more
        # than one (#280) rather than watching some of them: do not write what it will refuse.
        print("Not added: the listener watches one mailbox per account for now (#280). "
              "Give --mailbox once.", file=sys.stderr)
        return 1

    raw = _read_raw(path)
    candidate = dict(raw)
    candidate["accounts"] = list(raw.get("accounts", [])) + [entry]
    try:
        accounts.validate(candidate)
    except accounts.AccountsError as exc:
        print(f"Not added: {exc}", file=sys.stderr)
        return 1

    himalaya = himalaya_config_path()
    himalaya_text = _read_text(himalaya)
    if himalaya_text is not None and _has_himalaya_section(himalaya_text, _himalaya_name(account_id)):
        print(f"Not added: {himalaya} already has [accounts.{_himalaya_name(account_id)}].", file=sys.stderr)
        return 1

    if not stdin_is_tty():
        print("Not added: the password is asked for on a terminal, hidden, and this is not one. "
              "It is never taken from an argument or from a pipe.", file=sys.stderr)
        return 1
    password = getpass.getpass(f"Password for {entry['email']} (hidden): ").strip("\r\n")
    if not password:
        print("Not added: no password given.", file=sys.stderr)
        return 1

    result = probe_imap(entry["imap"]["host"], entry["imap"]["port"], entry["email"], password)
    _print_steps("IMAP", result["steps"])
    if not result["ok"]:
        print("\nNot added: the login above failed, and nothing was written.", file=sys.stderr)
        return 1

    undo = _Undo()
    roster = accounts.roster_path(entry, path)
    try:
        undo.remember(envfile.env_path())
        ok, where = _env_edit(entry["password_env"], password)
        if not ok:
            raise OSError(where)
        undo.remember(path)
        raw = dict(raw)
        raw["accounts"] = candidate["accounts"]
        raw.setdefault("schema_version", accounts.SCHEMA_VERSION)
        _write_accounts(path, raw)
        if not roster.exists():
            undo.remember(roster)
            if not roster.parent.exists():
                undo.created.append(roster.parent)
            roster.parent.mkdir(parents=True, exist_ok=True)
            template = _REPO_ROOT / "roster.md.example"
            roster.write_text(template.read_text(encoding="utf-8") if template.is_file() else "", encoding="utf-8")
        undo.remember(himalaya)
        block = _himalaya_block(entry)
        _write_himalaya(himalaya, (himalaya_text.rstrip("\n") + "\n\n" if himalaya_text else "") + block)
    except OSError as exc:
        undo.restore()
        print(f"Not added: could not write ({exc}). Everything written so far was put back.", file=sys.stderr)
        return 1

    print(f"Added account {account_id!r} ({entry['email']}).")
    print(f"  password   {entry['password_env']} in {envfile.env_path()}")
    print(f"  config     {path}")
    print(f"  roster     {roster}")
    print(f"  himalaya   [accounts.{_himalaya_name(account_id)}] in {himalaya}")
    if not _service("enable", account_id):
        print(f"\nThe account is saved, but its service did not start. Once it can: "
              f"`systemctl --user enable --now paynani-idle@{account_id}.service`.", file=sys.stderr)
        return 1
    print(f"\nNext: add the people who may give this account instructions to its own roster:\n"
          f"  paynani roster add NAME ADDRESS --roster {entry['roster']}")
    return 0


def _unused_name(directory: Path, account_id: str) -> Path:
    candidate = directory / f"{account_id}.md"
    number = 2
    while candidate.exists():
        candidate = directory / f"{account_id}-{number}.md"
        number += 1
    return candidate


def run_remove(args) -> int:
    account_id = str(args.id or "")
    path = accounts.accounts_path()
    try:
        existing = accounts.load(path)
    except accounts.AccountsError as exc:
        print(f"Not removed: accounts.json is not usable: {exc}", file=sys.stderr)
        return 1
    entry = next((account for account in existing if account["id"] == account_id), None)
    if entry is None:
        print(f"Not removed: there is no additional account {account_id!r}. "
              "(The account in .env is not managed here.)", file=sys.stderr)
        return 1
    if not _confirm(f"Remove account {account_id!r} ({entry['email']})? Its service stops and its "
                    "password leaves the .env; its roster is kept.", getattr(args, "yes", False)):
        print("Nothing changed.", file=sys.stderr)
        return 1
    if not _service("disable", account_id):
        print("Not removed: the service could not be stopped, so nothing was changed.", file=sys.stderr)
        return 1

    raw = _read_raw(path)
    raw["accounts"] = [a for a in raw.get("accounts", []) if a.get("id") != account_id]
    _write_accounts(path, raw)

    still_used = {a["password_env"] for a in existing if a["id"] != account_id}
    if entry["password_env"] not in still_used:
        _env_edit(entry["password_env"], None)

    himalaya = himalaya_config_path()
    text = _read_text(himalaya)
    if text is not None:
        trimmed = _without_himalaya_section(text, _himalaya_name(account_id))
        if trimmed != text:
            _write_himalaya(himalaya, trimmed)

    kept = None
    roster = accounts.roster_path(entry, path)
    if roster.is_file():
        base = path.parent.resolve()
        if roster.resolve().is_relative_to(base):
            aside = base / "rosters" / "removed"
            aside.mkdir(parents=True, exist_ok=True)
            kept = _unused_name(aside, account_id)
            shutil.move(str(roster), str(kept))
        else:
            print(f"Its roster is outside {base}, so it was left where it is: {roster}", file=sys.stderr)

    print(f"Removed account {account_id!r}.")
    if kept:
        print(f"  roster kept at {kept}")
    print("  the mail history in the journal and ledger was not touched")
    return 0
