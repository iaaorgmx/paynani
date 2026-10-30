"""
Change the agent's main mailbox account from PaynaniWeb (#591, N2; W2 of #590
calls it after the owner confirms with the web password).

The [accounts.paynani] tables of himalaya keep their own copy of the address,
servers and logins; only the password is read from .env. So a change to the main
account has to land in both places at once, or the listener (which reads .env)
and send.sh (which sends through himalaya) end up on different mailboxes. This
module is that one operation. No CLI.

Under one lock, from the first read to the last rollback:

1. merge the changes over .env into a candidate, validate it, and probe IMAP and
   SMTP with it (no mail is sent); nothing is written if that fails;
2. keep what .env, the himalaya config and the listener's idle.json hold now
   in a 0600 snapshot under state/ (0700), until the change is committed or
   undone; a change cut off by a crash is undone by the next update() or by
   recover();
3. write .env (envfile's atomic, line-preserving write) and only the values of
   [accounts.paynani] that name the mailbox; the password is never copied there;
4. if the address changed, point the listener's cursor at the UIDNEXT the probe
   saw in the new INBOX: mail that lands after the probe is delivered, the
   mailbox's past is not;
5. restart the listener (listener_control) and wait for a heartbeat from a new
   process reading the expected address;
6. if a write, the restart or the wait fails, put the three files back, restart,
   and wait for the old address; Result.rollback says whether that worked.

The lock is an flock on a file in the state directory, so it holds across the
web's workers and any other process; update() validates and probes again under
it rather than trusting an earlier check().

roster.md is not touched: the roster belongs to the agent, not to a mailbox.
Result, the audit line and every message carry field names, never a password,
an address or any other value.
"""

from __future__ import annotations

import contextlib
import fcntl
import imaplib
import os
import json
import re
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import accounts, envfile, himalaya_config, listener_control, validate
from .accounts_cli import _REPO_ROOT, _write_himalaya, himalaya_config_path
from .probe import probe_imap, probe_smtp

FIELDS = envfile.ENV_FIELDS
HIMALAYA_NAME = "paynani"
MAILBOX = "INBOX"            # what idle_listener.py watches unless told otherwise
WAIT_S = 60

ACCOUNT = "AGENT_EMAIL_ACCOUNT"
PASSWORD = "AGENT_EMAIL_PASSWORD"
FROM_NAME = "AGENT_EMAIL_FROM_NAME"
IMAP_HOST, IMAP_PORT = "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST", "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT"
SMTP_HOST, SMTP_PORT = "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST", "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT"
# A change to any of these is a change of mailbox connection: probe and restart.
CONNECTION = (ACCOUNT, PASSWORD, IMAP_HOST, IMAP_PORT, SMTP_HOST, SMTP_PORT)


@dataclass
class Result:
    ok: bool
    code: str            # "checked" | "updated" | "unchanged" | "unknown_field" | "invalid"
                         # | "is_additional_account" | "probe_failed" | "busy" | "recovery_failed"
                         # | "write_failed" | "restart_failed" | "not_ready" | "commit_failed"
    changed: list = field(default_factory=list)
    field_errors: dict = field(default_factory=dict)
    probe: list = field(default_factory=list)
    restart: listener_control.Restart | None = None
    ready: str = ""
    rollback: str = "none"   # "none" | "ok" | "failed"
    detail: str = ""
    recovered: bool = False  # an earlier change cut off by a crash was undone first


@dataclass
class _Candidate:
    stored: dict
    merged: dict
    changed: list
    cursor: dict | None = None   # {"uidvalidity", "last_uid"} seen by the probe, if the address changed

    @property
    def address_changed(self) -> bool:
        return self.stored.get(ACCOUNT, "").strip().lower() != self.merged[ACCOUNT].strip().lower()


# --- candidate, validation and probe ------------------------------------------------

def _candidate(changes: dict) -> tuple[_Candidate | None, Result | None]:
    unknown = sorted(k for k in changes if k not in FIELDS)
    if unknown:
        return None, Result(False, "unknown_field", detail="not a main account setting: " + ", ".join(unknown))
    stored = envfile.read_env()
    merged = dict(stored)
    for key, value in changes.items():
        merged[key] = value if key == PASSWORD else envfile.sanitise_value(str(value))
    changed = [k for k in FIELDS if k in changes and merged.get(k, "") != stored.get(k, "")]
    if not changed:
        return None, Result(True, "unchanged")
    errors = {k: v for k, v in validate.validate_env(merged).items()}
    if errors:
        return None, Result(False, "invalid", changed, field_errors=errors, detail="some fields are not valid")
    if ACCOUNT in changed and merged[ACCOUNT].strip().lower() in _additional_addresses():
        return None, Result(False, "is_additional_account", changed,
                            detail="that address is already an additional account")
    return _Candidate(stored, merged, changed), None


def _additional_addresses() -> set:
    try:
        return {a["email"].strip().lower() for a in accounts.load() if a.get("email")}
    except (accounts.AccountsError, OSError):
        return set()


def _probe(probe, host, port, user, password) -> dict:
    """
    A probe that raises becomes a failed step, not an error page (a dropped
    connection mid-login, say). The exception text is left out: it can quote the
    server's reply or part of the password.
    """
    try:
        return probe(host, port, user, password)
    except Exception as exc:  # noqa: BLE001 -- any probe failure is a failed check, never a crash
        return {"ok": False, "steps": [{"ok": False, "text": "connection", "detail": type(exc).__name__}]}


def _uidnext(merged: dict) -> dict | None:
    """UIDNEXT and UIDVALIDITY of the candidate INBOX, or None if the server will not say."""
    try:
        conn = imaplib.IMAP4_SSL(merged[IMAP_HOST], int(merged[IMAP_PORT]),
                                 ssl_context=ssl.create_default_context(), timeout=30)
        try:
            conn.login(merged[ACCOUNT], merged[PASSWORD])
            typ, data = conn.status(MAILBOX, "(UIDNEXT UIDVALIDITY)")
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        return None
    if typ != "OK" or not data or not data[0]:
        return None
    raw = data[0].decode("utf-8", "replace") if isinstance(data[0], bytes) else str(data[0])
    nxt, validity = re.search(r"UIDNEXT\s+(\d+)", raw), re.search(r"UIDVALIDITY\s+(\d+)", raw)
    if not (nxt and validity):
        return None
    return {"uidvalidity": validity.group(1), "last_uid": max(0, int(nxt.group(1)) - 1)}


def _check(candidate: _Candidate) -> Result:
    if not any(k in CONNECTION for k in candidate.changed):
        return Result(True, "checked", candidate.changed)
    m = candidate.merged
    imap = _probe(probe_imap, m[IMAP_HOST], int(m[IMAP_PORT]), m[ACCOUNT], m[PASSWORD])
    smtp = _probe(probe_smtp, m[SMTP_HOST], int(m[SMTP_PORT]), m[ACCOUNT], m[PASSWORD])
    steps = [dict(s, protocol="imap") for s in imap["steps"]] + [dict(s, protocol="smtp") for s in smtp["steps"]]
    if not (imap["ok"] and smtp["ok"]):
        return Result(False, "probe_failed", candidate.changed, probe=steps,
                      detail="the IMAP and SMTP checks did not pass")
    if candidate.address_changed:
        candidate.cursor = _uidnext(m)
        if candidate.cursor is None:
            return Result(False, "probe_failed", candidate.changed, probe=steps,
                          detail="the new INBOX did not report UIDNEXT, so where to start reading is unknown")
    return Result(True, "checked", candidate.changed, probe=steps)


def check(changes: dict) -> Result:
    """Validate and probe the candidate without writing anything."""
    candidate, early = _candidate(changes)
    return early or _check(candidate)


# --- himalaya ----------------------------------------------------------------------

def _server(value: str, host: str, port) -> str:
    """Keep the scheme the table already uses (imaps, smtps, smtp); change host and port."""
    match = re.match(r"^([a-z]+)://", value)
    return f"{match.group(1)}://{host}:{port}" if match else value


def rewrite_main_block(text: str, merged: dict) -> str | None:
    """
    The config with [accounts.paynani] pointing at the merged settings, or None
    if there is no [accounts.paynani*] table at all. Only the values that name
    the mailbox are touched: email, the two servers, the two logins, and
    display-name, which follows AGENT_EMAIL_FROM_NAME (set: written; empty: the
    line goes). A value that is missing is added inside its table, and a missing
    table is added at the end; nothing else is removed. Every other line in those
    tables (folder aliases, a signature, password.cmd) and every other account
    survives, including on a block someone left incomplete.
    """
    prefix = f"accounts.{HIMALAYA_NAME}"
    if not any(t == prefix or t.startswith(prefix + ".") for t in _tables(text)):
        return None
    email, name = merged[ACCOUNT], merged.get(FROM_NAME, "")
    servers = {"imap": ("imaps", merged[IMAP_HOST], merged[IMAP_PORT]),
               "smtp": ("smtps", merged[SMTP_HOST], merged[SMTP_PORT])}
    table, out = None, []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        ending = line[len(bare):]
        header = re.match(r"^\s*\[([^\]]+)\]\s*$", bare)
        if header:
            table = header.group(1).strip()
            out.append(line)
            continue
        kv = re.match(r"^(\s*)([A-Za-z0-9_.\-]+)(\s*=\s*)(.*)$", bare)
        if not kv or table is None or not (table == prefix or table.startswith(prefix + ".")):
            out.append(line)
            continue
        indent, key, eq, value = kv.groups()
        new = None
        if table == prefix and key == "email":
            new = email
        elif table == prefix and key == "display-name":
            if not name:
                continue
            new = name
        elif key == "server" and table in (f"{prefix}.imap", f"{prefix}.smtp"):
            try:
                current = json.loads(value)
            except ValueError:
                current = value.strip('"')
            _, host, port = servers[table.rsplit(".", 1)[1]]
            new = _server(current, host, port)
        elif key == "authcid" and table in (f"{prefix}.imap.sasl.plain", f"{prefix}.smtp.sasl.plain"):
            new = email
        out.append(f"{indent}{key}{eq}{himalaya_config.toml_string(new)}{ending}" if new is not None else line)
    return _add_missing("".join(out), merged)


def _required(merged: dict) -> list:
    """(table, key, value) for every value [accounts.paynani] needs, in the order account_block writes them."""
    prefix = f"accounts.{HIMALAYA_NAME}"
    email, name = merged[ACCOUNT], merged.get(FROM_NAME, "")
    secret = himalaya_config.secret_command(_REPO_ROOT / "scripts" / "env_secret.py", envfile.env_path(), PASSWORD)
    rows = [(prefix, "email", email)]
    if name:
        rows.append((prefix, "display-name", name))
    for protocol, scheme, host, port in (("imap", "imaps", merged[IMAP_HOST], merged[IMAP_PORT]),
                                         ("smtp", "smtps", merged[SMTP_HOST], merged[SMTP_PORT])):
        rows += [(f"{prefix}.{protocol}", "server", f"{scheme}://{host}:{port}"),
                 (f"{prefix}.{protocol}.sasl.plain", "authcid", email),
                 (f"{prefix}.{protocol}.sasl.plain", "password.cmd", secret)]
    return rows


def _add_missing(text: str, merged: dict) -> str:
    """Put each required value that is not there into its table, or the table at the end if it is missing."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    appended: dict = {}
    for table, key, value in _required(merged):
        if key in _keys_of("".join(lines), table):
            continue
        row = f"{key} = {himalaya_config.toml_string(value)}\n"
        at = _header_index(lines, table)
        if at is None:
            appended.setdefault(table, []).append(row)
            continue
        after = at + 1
        if key == "display-name":
            # Right after email, where account_block and a hand-written block put it.
            for i in range(at + 1, len(lines)):
                if re.match(r"^\s*\[", lines[i]):
                    break
                if re.match(r"^\s*email\s*=", lines[i]):
                    after = i + 1
                    break
        lines.insert(after, row)
    for table, rows in appended.items():
        lines += ["\n", f"[{table}]\n"] + rows
    return "".join(lines)


def _tables(text: str) -> list:
    return [m.group(1).strip() for m in re.finditer(r"^\s*\[([^\]]+)\]\s*$", text, re.M)]


def _header_index(lines: list, table_name: str) -> int | None:
    for i, line in enumerate(lines):
        header = re.match(r"^\s*\[([^\]]+)\]\s*$", line.rstrip("\r\n"))
        if header and header.group(1).strip() == table_name:
            return i
    return None


def _keys_of(text: str, table_name: str) -> set:
    """The keys of one TOML table, read the same line-by-line way as above."""
    keys, table = set(), None
    for line in text.splitlines():
        header = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if header:
            table = header.group(1).strip()
            continue
        kv = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*=", line)
        if kv and table == table_name:
            keys.add(kv.group(1))
    return keys


def _main_block(merged: dict) -> str:
    secret = himalaya_config.secret_command(_REPO_ROOT / "scripts" / "env_secret.py", envfile.env_path(), PASSWORD)
    block = himalaya_config.account_block(
        HIMALAYA_NAME, merged[ACCOUNT],
        {"host": merged[IMAP_HOST], "port": merged[IMAP_PORT]},
        {"host": merged[SMTP_HOST], "port": merged[SMTP_PORT]},
        secret, default=True)
    if merged.get(FROM_NAME):
        email_line = f"email = {himalaya_config.toml_string(merged[ACCOUNT])}\n"
        block = block.replace(email_line, email_line + f"display-name = {himalaya_config.toml_string(merged[FROM_NAME])}\n", 1)
    return block


def _with_main_block(text: str, merged: dict) -> str:
    """text with [accounts.paynani] pointing at merged: edited and completed in place, or added if absent."""
    rewritten = rewrite_main_block(text, merged)
    if rewritten is not None:
        return rewritten
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + _main_block(merged)


# --- the transaction: a protected snapshot on disk ----------------------------------

TXN_DIR = "main_account.txn"
TXN_FILE = "snapshot.json"


def _read(path: Path) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _fsync_dir(path: Path) -> None:
    """Make a rename or unlink in path durable. Raises OSError if it cannot be confirmed."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_private(path: Path, text: str) -> None:
    """0600, written beside the target and renamed over it, synced, never following a link."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _write_state(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _txn_path() -> Path:
    return listener_control.state_dir() / TXN_DIR / TXN_FILE


class _Unreadable(Exception):
    """A snapshot is there but cannot be trusted: a symlink, or not the JSON this module writes."""


class _Snapshot:
    """
    What the three files held before the change, on disk from before the first
    write until the change is committed or undone, with the phase it reached:
    "prepared" (undo it) or "committed" (keep it, only clean up). It holds the
    old .env, password included, so it lives in a 0700 directory as a 0600 file,
    is synced before anything is written, is never followed through a symlink,
    and is deleted as soon as it is not needed.
    """

    def __init__(self, data: dict):
        self.data = data
        self.phase = data.get("phase", "prepared")
        self.env_path = Path(data["env_path"])
        self.himalaya_path = Path(data["himalaya_path"])
        self.state_path = Path(data["state_path"])
        self.env, self.himalaya, self.state = data["env"], data["himalaya"], data["state"]
        self.reconnect = data.get("reconnect", True)
        self.address = data.get("address", "")

    @classmethod
    def take(cls, *, reconnect: bool, address: str) -> "_Snapshot":
        """Raises OSError if the snapshot cannot be made durable; nothing has been written then."""
        himalaya_path, state_path = himalaya_config_path(), listener_control.state_path()
        data = {"phase": "prepared", "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "env_path": str(envfile.env_path()), "himalaya_path": str(himalaya_path),
                "state_path": str(state_path), "env": _read(envfile.env_path()),
                "himalaya": _read(himalaya_path), "state": _read(state_path),
                "reconnect": reconnect, "address": address}
        directory = _txn_path().parent
        if directory.is_symlink():
            raise OSError(f"{directory} is a symlink")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        _fsync_dir(directory.parent)
        _write_private(_txn_path(), json.dumps(data))
        return cls(data)

    @classmethod
    def pending(cls) -> "_Snapshot | None":
        """The snapshot left behind, None if there is none; raises _Unreadable rather than guess."""
        path = _txn_path()
        if path.parent.is_symlink() or path.is_symlink():
            raise _Unreadable(f"{path} is a symlink")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data)
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise _Unreadable(f"{path} cannot be read ({type(exc).__name__})") from exc

    def commit(self) -> None:
        """Record that the change took; raises OSError if that cannot be made durable."""
        self.data["phase"] = self.phase = "committed"
        try:
            _write_private(_txn_path(), json.dumps(self.data))
        except OSError:
            # The rename may have landed without its directory sync. Put "prepared"
            # back, as far as the disk lets us, so a later recover() undoes rather
            # than keeps a change this call is about to undo.
            self.data["phase"] = self.phase = "prepared"
            try:
                _write_private(_txn_path(), json.dumps(self.data))
            except OSError:
                pass
            raise

    def restore(self) -> bool:
        ok = True
        if self.env is not None:
            saved = envfile.env_path
            envfile.env_path = lambda: self.env_path
            try:
                ok = envfile.write_env(self.env)[0] and ok
            finally:
                envfile.env_path = saved
        try:
            if self.himalaya is None:
                self.himalaya_path.unlink(missing_ok=True)
            else:
                _write_himalaya(self.himalaya_path, self.himalaya)
        except OSError:
            ok = False
        try:
            if self.state is None:
                self.state_path.unlink(missing_ok=True)
            else:
                _write_state(self.state_path, self.state)
        except OSError:
            ok = False
        return ok

    @staticmethod
    def discard() -> bool:
        """Delete it. A failed directory sync is tolerated: a committed snapshot that comes back is only cleaned up."""
        path = _txn_path()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return False
        try:
            _fsync_dir(path.parent)
        except OSError:
            pass
        return True


def _back_on(address: str, timeout_s: float) -> str:
    """Restart the listener and wait for address; the state it ends in."""
    back = listener_control.restart()
    if not back.ok:
        return "waiting"
    return listener_control.wait(back.requested_at, timeout_s=timeout_s, expect=address or None,
                                 previous_pid=back.previous_pid).state


@dataclass
class Recovery:
    found: bool            # a snapshot was there
    ok: bool = True        # nothing is left to undo: no snapshot, or it was undone and proven back
    restored: bool = False
    ready: str = ""
    detail: str = ""


def _recover(timeout_s: float) -> Recovery:
    """
    Undo what a crashed change left behind. A snapshot that cannot be read, files
    that cannot be restored or an old listener that does not come back all fail
    closed: the snapshot stays, ok is False, and update() writes nothing.
    """
    try:
        snapshot = _Snapshot.pending()
    except _Unreadable as exc:
        _audit("recover", [], "snapshot_unreadable", "failed")
        return Recovery(True, False, detail=f"{exc}; it was kept, and nothing will change until someone looks at it")
    if snapshot is None:
        return Recovery(False)
    if snapshot.phase == "committed":
        _Snapshot.discard()
        _audit("recover", [], "committed_cleanup", "none")
        return Recovery(True, True, detail="a change that had already taken was only cleaned up")
    if not snapshot.restore():
        _audit("recover", [], "recover_failed", "failed")
        return Recovery(True, False, detail="the settings from before an interrupted change could not be restored")
    ready = _back_on(snapshot.address, timeout_s) if snapshot.reconnect else ""
    if snapshot.reconnect and ready != "connected":
        _audit("recover", [], "recover_failed", "failed")
        return Recovery(True, False, True, ready,
                        "the settings from before an interrupted change were restored, "
                        "but the listener did not come back on them")
    _Snapshot.discard()
    _audit("recover", [], "recovered", "ok")
    return Recovery(True, True, True, ready, "an interrupted change was undone")


def recover(timeout_s: float = WAIT_S) -> Recovery:
    """
    Undo a change that was cut off (a crash, a kill) before it was committed or
    rolled back. update() does this first on its own; PaynaniWeb can also call it
    when it starts. Busy while an update() runs: that one owns the snapshot.
    """
    with _locked() as held:
        if not held:
            return Recovery(False, detail="a change to the main account is running")
        return _recover(timeout_s)


def _set_cursor(path: Path, address: str, cursor: dict) -> None:
    """The listener resumes from here: same mailbox, same UIDVALIDITY, same address (#591, N3)."""
    try:
        state = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    state.update({"mailbox": MAILBOX, "uidvalidity": cursor["uidvalidity"],
                  "last_uid": cursor["last_uid"], "account": address})
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_state(path, json.dumps(state))


def _audit(by: str, fields: list, code: str, rollback: str) -> None:
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "by": by,
            "fields": fields, "result": code, "rollback": rollback}
    path = listener_control.state_dir() / "main_account_changes.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        pass


# --- update -------------------------------------------------------------------------

@contextlib.contextmanager
def _locked():
    """An flock on a file in the state directory: one change at a time, across processes."""
    lock_path = listener_control.state_dir() / "main_account.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def update(changes: dict, *, by: str, timeout_s: float = WAIT_S) -> Result:
    """
    One change at a time: a second call while one is running gets "busy". It
    validates and probes again under the lock; a check() from before proves
    nothing about what is on disk now.
    """
    with _locked() as held:
        if not held:
            return Result(False, "busy", detail="another change to the main account is running")
        recovered = _recover(timeout_s)
        if not recovered.ok:
            return Result(False, "recovery_failed", rollback="failed", detail=recovered.detail, recovered=True)
        result = _update(changes, by=by, timeout_s=timeout_s)
        result.recovered = recovered.found
        return result


def _update(changes: dict, *, by: str, timeout_s: float) -> Result:
    candidate, early = _candidate(changes)
    if early:
        return early
    checked = _check(candidate)
    if not checked.ok:
        return checked
    merged, changed = candidate.merged, candidate.changed
    reconnect = any(k in CONNECTION for k in changed)
    try:
        snapshot = _Snapshot.take(reconnect=reconnect, address=candidate.stored.get(ACCOUNT, ""))
    except OSError:
        _audit(by, changed, "write_failed", "none")
        return Result(False, "write_failed", changed, probe=checked.probe,
                      detail="could not keep a copy of the current settings, so nothing was changed")

    def undo(code: str, detail: str, restart=None, ready="") -> Result:
        """Put the old settings back and prove the listener is on them; the snapshot stays until then."""
        restored = snapshot.restore()
        back_ok = restored and (not reconnect
                                or _back_on(candidate.stored.get(ACCOUNT, ""), timeout_s) == "connected")
        if back_ok:
            _Snapshot.discard()
        rollback = "ok" if back_ok else "failed"
        _audit(by, changed, code, rollback)
        return Result(False, code, changed, probe=checked.probe, restart=restart, ready=ready,
                      rollback=rollback, detail=detail)

    ok, _ = envfile.write_env(envfile.render_env(merged))
    if not ok:
        return undo("write_failed", "could not write .env")

    try:
        _write_himalaya(snapshot.himalaya_path, _with_main_block(snapshot.himalaya or "", merged))
        if candidate.address_changed:
            _set_cursor(snapshot.state_path, merged[ACCOUNT], candidate.cursor)
    except OSError:
        return undo("write_failed", "could not write the himalaya configuration or the listener state")

    if not reconnect:
        return _committed(snapshot, by, changed, Result(True, "updated", changed), undo)

    restart = listener_control.restart()
    if not restart.ok:
        return undo("restart_failed", f"the listener did not restart ({restart.code})", restart=restart)
    status = listener_control.wait(restart.requested_at, timeout_s=timeout_s, expect=merged[ACCOUNT],
                                   previous_pid=restart.previous_pid)
    if status.state != "connected":
        reason = "the server refused the login" if "login rejected" in status.last_error else \
            "the listener did not come back on the new settings in time"
        return undo("not_ready", reason, restart=restart, ready=status.state)

    return _committed(snapshot, by, changed,
                      Result(True, "updated", changed, probe=checked.probe, restart=restart, ready=status.state), undo)


def _committed(snapshot: _Snapshot, by: str, changed: list, result: Result, undo) -> Result:
    """
    The change took. Record "committed" durably before deleting the snapshot, so
    a crash in between is cleaned up by recover() and not undone. If that record
    cannot be made durable, the change is not reported as done: the snapshot is
    still "prepared", so it is undone like any other failure, and the result
    says whether the old settings were proven back.
    """
    try:
        snapshot.commit()
    except OSError:
        return undo("commit_failed", "the change could not be recorded as done, so it was undone",
                    restart=result.restart, ready=result.ready)
    if not _Snapshot.discard():
        result.detail = "the change took; its committed snapshot is left behind and will be cleaned up"
    _audit(by, changed, "updated", "none")
    return result
