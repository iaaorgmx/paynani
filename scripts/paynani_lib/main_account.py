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
2. keep in memory what .env, the himalaya config and the listener's idle.json
   hold now;
3. write .env (envfile's atomic, line-preserving write) and only the values of
   [accounts.paynani] that name the mailbox; the password is never copied there;
4. if the address changed, point the listener's cursor at the UIDNEXT the probe
   saw in the new INBOX: mail that lands after the probe is delivered, the
   mailbox's past is not;
5. restart the listener (listener_control) and wait for a heartbeat from a new
   process reading the expected address;
6. if a write, the restart or the wait fails, put the three files back, restart,
   and wait for the old address; Result.rollback says whether that worked.

roster.md is not touched: the roster belongs to the agent, not to a mailbox.
Result, the audit line and every message carry field names, never a password,
an address or any other value.
"""

from __future__ import annotations

import fcntl
import imaplib
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
                         # | "is_additional_account" | "probe_failed" | "busy"
                         # | "write_failed" | "restart_failed" | "not_ready"
    changed: list = field(default_factory=list)
    field_errors: dict = field(default_factory=dict)
    probe: list = field(default_factory=list)
    restart: listener_control.Restart | None = None
    ready: str = ""
    rollback: str = "none"   # "none" | "ok" | "failed"
    detail: str = ""


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
    if those tables are not there. Edits only the values that name the mailbox:
    email, display-name when present, the two servers and the two logins. Other
    lines in those tables (folder aliases, password.cmd, a signature) and every
    other account survive.
    """
    prefix = f"accounts.{HIMALAYA_NAME}"
    servers = {"imap": (merged[IMAP_HOST], merged[IMAP_PORT]), "smtp": (merged[SMTP_HOST], merged[SMTP_PORT])}
    seen, table, out = set(), None, []
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
            new = merged[ACCOUNT]
            seen.add("email")
        elif table == prefix and key == "display-name" and merged.get(FROM_NAME):
            new = merged[FROM_NAME]
        elif key == "server" and table in (f"{prefix}.imap", f"{prefix}.smtp"):
            try:
                current = json.loads(value)
            except ValueError:
                current = value.strip('"')
            new = _server(current, *servers[table.rsplit(".", 1)[1]])
        elif key == "authcid" and table.endswith(".sasl.plain"):
            new = merged[ACCOUNT]
        out.append(f"{indent}{key}{eq}{himalaya_config.toml_string(new)}{ending}" if new is not None else line)
    return "".join(out) if "email" in seen else None


def _main_block(merged: dict) -> str:
    secret = himalaya_config.secret_command(_REPO_ROOT / "scripts" / "env_secret.py", envfile.env_path(), PASSWORD)
    return himalaya_config.account_block(
        HIMALAYA_NAME, merged[ACCOUNT],
        {"host": merged[IMAP_HOST], "port": merged[IMAP_PORT]},
        {"host": merged[SMTP_HOST], "port": merged[SMTP_PORT]},
        secret, default=True)


# --- the files, kept in memory only --------------------------------------------------

def _read(path: Path) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _write_state(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class _Snapshot:
    """What the three files hold before anything is written. Never written to disk."""

    def __init__(self):
        self.himalaya_path = himalaya_config_path()
        self.state_path = listener_control.state_path()
        self.env = _read(envfile.env_path())
        self.himalaya = _read(self.himalaya_path)
        self.state = _read(self.state_path)

    def restore(self) -> bool:
        ok = True
        if self.env is not None:
            ok = envfile.write_env(self.env)[0] and ok
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

def update(changes: dict, *, by: str, timeout_s: float = WAIT_S) -> Result:
    """One change at a time: a second call while one is running gets "busy"."""
    lock_path = listener_control.state_dir() / "main_account.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return Result(False, "busy", detail="another change to the main account is running")
        return _update(changes, by=by, timeout_s=timeout_s)


def _update(changes: dict, *, by: str, timeout_s: float) -> Result:
    candidate, early = _candidate(changes)
    if early:
        return early
    checked = _check(candidate)
    if not checked.ok:
        return checked
    merged, changed = candidate.merged, candidate.changed
    reconnect = any(k in CONNECTION for k in changed)
    snapshot = _Snapshot()

    def undo(code: str, detail: str, restart=None, ready="") -> Result:
        restored = snapshot.restore()
        back_ok = True
        if reconnect:
            back = listener_control.restart()
            back_ok = back.ok and listener_control.wait(
                back.requested_at, timeout_s=timeout_s, expect=candidate.stored.get(ACCOUNT) or None,
                previous_pid=back.previous_pid).state == "connected"
        rollback = "ok" if restored and back_ok else "failed"
        _audit(by, changed, code, rollback)
        return Result(False, code, changed, probe=checked.probe, restart=restart, ready=ready,
                      rollback=rollback, detail=detail)

    ok, _ = envfile.write_env(envfile.render_env(merged))
    if not ok:
        _audit(by, changed, "write_failed", "none")
        return Result(False, "write_failed", changed, probe=checked.probe, detail="could not write .env")

    text = snapshot.himalaya or ""
    rewritten = rewrite_main_block(text, merged)
    if rewritten is None:
        rewritten = (text.rstrip("\n") + "\n\n" if text.strip() else "") + _main_block(merged)
    try:
        _write_himalaya(snapshot.himalaya_path, rewritten)
        if candidate.address_changed:
            _set_cursor(snapshot.state_path, merged[ACCOUNT], candidate.cursor)
    except OSError:
        return undo("write_failed", "could not write the himalaya configuration or the listener state")

    if not reconnect:
        _audit(by, changed, "updated", "none")
        return Result(True, "updated", changed)

    restart = listener_control.restart()
    if not restart.ok:
        return undo("restart_failed", f"the listener did not restart ({restart.code})", restart=restart)
    status = listener_control.wait(restart.requested_at, timeout_s=timeout_s, expect=merged[ACCOUNT],
                                   previous_pid=restart.previous_pid)
    if status.state != "connected":
        reason = "the server refused the login" if "login rejected" in status.last_error else \
            "the listener did not come back on the new settings in time"
        return undo("not_ready", reason, restart=restart, ready=status.state)

    _audit(by, changed, "updated", "none")
    return Result(True, "updated", changed, probe=checked.probe, restart=restart, ready=status.state)
