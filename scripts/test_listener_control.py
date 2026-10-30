#!/usr/bin/env python3
"""
#591 N3: restarting a listener from PaynaniWeb and knowing when it is back,
plus what the listener now records for that: the address its cursor belongs to
and a refused login, without touching the heartbeat.
"""

from __future__ import annotations

import imaplib
import json
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import idle_listener  # noqa: E402
from paynani_lib import listener_control as lc  # noqa: E402

passed = failed = 0


def check(desc, condition, detail=""):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}" + (f"\n       {detail}" if detail else ""))
        failed += 1


def stamp(offset=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


def write_state(path, **fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields))


class Runs:
    """Stands in for subprocess: records argv, answers with a fixed result."""

    def __init__(self, returncode=0, stderr="", raises=None):
        self.calls, self.returncode, self.stderr, self.raises = [], returncode, stderr, raises

    def __call__(self, argv):
        self.calls.append(argv)
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / "state"
    saved = (lc.state_dir, lc._run, lc._platform, lc.accounts.load)
    try:
        lc.state_dir = lambda: state
        configured = [{"id": "ventas", "enabled": True}, {"id": "archivo", "enabled": False}]
        lc.accounts.load = lambda path=None: configured

        # --- restart: only the listener, by a fixed name -------------------------------
        lc._platform = lambda: "linux"
        write_state(state / "idle.json", pid=4242, heartbeat_at=stamp(-60))
        runs = Runs()
        lc._run = runs
        r = lc.restart()
        check("the main listener restarts with systemctl --user",
              runs.calls == [["systemctl", "--user", "restart", "paynani-idle.service"]], runs.calls)
        check("a requested restart says so", r.ok and r.code == "requested", r)
        check("requested_at is a UTC timestamp", lc._seconds(r.requested_at) is not None, r.requested_at)
        check("the previous pid comes from idle.json", r.previous_pid == 4242, r)

        runs = Runs()
        lc._run = runs
        r = lc.restart("ventas")
        check("an additional account restarts its own instance unit",
              runs.calls == [["systemctl", "--user", "restart", "paynani-idle@ventas.service"]], runs.calls)

        runs = Runs()
        lc._run = runs
        for bad in ("../ventas", "main", "ventas; rm -rf ~", "", "not-configured", "archivo"):
            r = lc.restart(bad)
            check(f"an account id like {bad!r} is refused before running anything",
                  not r.ok and r.code == "unknown_account" and runs.calls == [], (r, runs.calls))

        lc._platform = lambda: "macos"
        runs = Runs()
        lc._run = runs
        lc.restart()
        check("on macOS the main LaunchAgent is kickstarted",
              len(runs.calls) == 1 and runs.calls[0][:3] == ["launchctl", "kickstart", "-k"]
              and runs.calls[0][3].endswith("/com.paynani.idle"), runs.calls)
        runs = Runs()
        lc._run = runs
        lc.restart("ventas")
        check("on macOS an account's LaunchAgent is kickstarted",
              runs.calls[0][3].endswith("/com.paynani.idle.ventas"), runs.calls)

        lc._platform = lambda: "unknown"
        r = lc.restart()
        check("no service manager is reported, not guessed", not r.ok and r.code == "no_service_manager", r)

        lc._platform = lambda: "linux"
        lc._run = Runs(returncode=5, stderr="Failed to restart paynani-idle.service: Unit not found.")
        r = lc.restart()
        check("a failed restart carries the manager's last line",
              not r.ok and r.code == "failed" and "Unit not found" in r.detail, r)
        lc._run = Runs(raises=FileNotFoundError("systemctl"))
        r = lc.restart()
        check("a missing systemctl is no_service_manager", not r.ok and r.code == "no_service_manager", r)

        # --- status(since=...): back means a fresh heartbeat from the new process -------
        since = stamp(-5)
        (state / "idle.json").unlink()
        check("no state yet is waiting", lc.status(since=since).state == "waiting")

        write_state(state / "idle.json", pid=4242, heartbeat_at=stamp(-120), mailbox="INBOX",
                    account="agente@example.org")
        check("a heartbeat from before the restart is still waiting",
              lc.status(since=since).state == "waiting")

        write_state(state / "idle.json", pid=5151, heartbeat_at=stamp(), mailbox="INBOX",
                    account="agente@example.org")
        s = lc.status(since=since, expect="Agente@Example.org", previous_pid=4242)
        check("a fresh heartbeat from a new process and the expected address is connected",
              s.state == "connected" and s.account == "agente@example.org" and s.pid == 5151, s)
        check("the same pid as before the restart is not back yet",
              lc.status(since=since, previous_pid=5151).state == "waiting")
        s = lc.status(since=since, expect="nuevo@example.org")
        check("a heartbeat for another address is not back",
              s.state == "waiting" and "nuevo@example.org" in s.detail, s)

        write_state(state / "idle.json", pid=4242, heartbeat_at=stamp(-120), account="agente@example.org",
                    imap_last_login_error_at=stamp(), imap_last_login_error="login rejected by imap.example.org")
        s = lc.status(since=since)
        check("a refused login after the restart is reported in last_error",
              s.state == "waiting" and "login rejected" in s.last_error, s)

        write_state(state / "idle.json", pid=6000, heartbeat_at=stamp(), account="agente@example.org",
                    imap_last_disconnect_at=stamp(-3), imap_last_disconnect_error="connection lost (EOF)")
        s = lc.status(since=since)
        check("an error followed by a newer heartbeat is back", s.state == "connected", s)

        check("a since that is not a timestamp is unknown", lc.status(since="ayer").state == "unknown")

        # --- status() without since: is the heartbeat recent ----------------------------
        write_state(state / "idle.json", pid=1, heartbeat_at=stamp(-60))
        check("a recent heartbeat is connected", lc.status().state == "connected")
        write_state(state / "idle.json", pid=1, heartbeat_at=stamp(-lc.STALE_S - 60))
        check("an old heartbeat is stale", lc.status().state == "stale")
        write_state(state / "accounts" / "ventas" / "idle.json", pid=2, heartbeat_at=stamp(-30))
        check("an additional account reads its own idle.json", lc.status("ventas").state == "connected")
        check("status of an account that is not in accounts.json is unknown",
              lc.status("not-configured").state == "unknown")
        check("status of a disabled account is unknown", lc.status("archivo", since=stamp()).state == "unknown")

        # --- the new process can be back before the restart command returns ------------
        write_state(state / "idle.json", pid=100, heartbeat_at=stamp(-120), account="agente@example.org")

        class FastStart:
            """systemctl that returns a second after the new listener wrote its heartbeat."""

            def __call__(self, argv):
                time.sleep(1.1)
                write_state(state / "idle.json", pid=200, heartbeat_at=stamp(), account="agente@example.org")
                time.sleep(1.1)
                return subprocess.CompletedProcess(argv, 0, "", "")
        lc._run = FastStart()
        r = lc.restart()
        s = lc.status(since=r.requested_at, expect="agente@example.org", previous_pid=r.previous_pid)
        check("a heartbeat written before systemctl returns still counts as back",
              r.ok and s.state == "connected" and s.pid == 200, (r, s))

        # --- wait ------------------------------------------------------------------------
        write_state(state / "idle.json", pid=1, heartbeat_at=stamp(-300))
        ticks = [0.0]
        s = lc.wait(stamp(-1), timeout_s=3, sleep=lambda _: ticks.__setitem__(0, ticks[0] + 1),
                    clock=lambda: ticks[0])
        check("wait gives up after timeout_s and says it is still waiting",
              s.state == "waiting" and ticks[0] >= 3, (s, ticks))
        write_state(state / "idle.json", pid=9, heartbeat_at=stamp())
        s = lc.wait(stamp(-1), timeout_s=3, sleep=lambda _: None, clock=lambda: 0.0)
        check("wait returns as soon as the listener is back", s.state == "connected", s)
    finally:
        lc.state_dir, lc._run, lc._platform, lc.accounts.load = saved


# --- the listener side -------------------------------------------------------------------

class FakeImap:
    """What run() touches between connecting and the first IDLE."""

    capabilities = ("IMAP4REV1", "IDLE")

    def __init__(self, uids, validity="7"):
        self.uids, self.validity = uids, validity

    def select(self, mailbox):
        return "OK", [b"0"]

    def status(self, mailbox, what):
        return "OK", [f'"{mailbox}" (UIDVALIDITY {self.validity})'.encode()]

    def uid(self, command, *args):
        if command == "search":
            return "OK", [" ".join(str(u) for u in self.uids).encode()]
        return "OK", [None]

    def logout(self):
        pass


def run_once(td, state_fields, uids, account="nuevo@example.org"):
    """One pass of run() up to its first IDLE, which stops it."""
    tdp = pathlib.Path(td)
    state_path = tdp / "idle.json"
    if state_fields is not None:
        state_path.write_text(json.dumps(state_fields))
    saved = (idle_listener.connect, idle_listener.idle, idle_listener._stop)
    try:
        idle_listener._stop = False
        idle_listener.connect = lambda env: FakeImap(uids)

        def stop(conn, timeout):
            idle_listener._stop = True
        idle_listener.idle = stop
        idle_listener.run(tdp / "mail.env", "INBOX", False, state_path, tdp / "roster.md",
                          tdp / "events.jsonl", env={"AGENT_EMAIL_ACCOUNT": account})
    finally:
        idle_listener.connect, idle_listener.idle, idle_listener._stop = saved
    return json.loads(state_path.read_text())


with tempfile.TemporaryDirectory() as td:
    s = run_once(td, {"mailbox": "INBOX", "uidvalidity": "7", "last_uid": 3, "account": "viejo@example.org"},
                 uids=[1, 2, 3, 40, 41])
    check("a cursor saved for another address is not reused: the new mailbox starts at its newest message",
          s["last_uid"] == 41 and s["account"] == "nuevo@example.org", s)
    check("nothing from the new mailbox's past reached the journal",
          not (pathlib.Path(td) / "events.jsonl").exists() or not (pathlib.Path(td) / "events.jsonl").read_text())

with tempfile.TemporaryDirectory() as td:
    s = run_once(td, {"mailbox": "INBOX", "uidvalidity": "7", "last_uid": 41, "account": "nuevo@example.org"},
                 uids=[1, 41])
    check("the same address resumes from its cursor", s["last_uid"] == 41 and s["account"] == "nuevo@example.org", s)

with tempfile.TemporaryDirectory() as td:
    s = run_once(td, {"mailbox": "INBOX", "uidvalidity": "7", "last_uid": 41}, uids=[1, 41])
    check("a state file from before #591, with no address, is kept and gains one",
          s["last_uid"] == 41 and s["account"] == "nuevo@example.org", s)

check("save_state leaves the address out when it does not know it",
      "account" not in idle_listener.save_state("none", "INBOX", "7", 1))

with tempfile.TemporaryDirectory() as td:
    path = pathlib.Path(td) / "idle.json"
    before = stamp(-600)
    path.write_text(json.dumps({"heartbeat_at": before, "pid": 77, "last_uid": 9}))
    saved = idle_listener.connect

    def refuse(env):
        raise idle_listener.LoginRejected("login rejected by imap.example.org for x@example.org: AUTHENTICATIONFAILED")
    idle_listener.connect = refuse
    try:
        code = None
        try:
            idle_listener.run(pathlib.Path(td) / "mail.env", "INBOX", False, path, pathlib.Path(td) / "roster.md",
                              pathlib.Path(td) / "events.jsonl", env={"AGENT_EMAIL_ACCOUNT": "x@example.org"})
        except SystemExit as exc:
            code = exc.code
    finally:
        idle_listener.connect = saved
    s = json.loads(path.read_text())
    check("a refused login still exits 1", code == 1, code)
    check("a refused login is recorded with its reason",
          "AUTHENTICATIONFAILED" in s.get("imap_last_login_error", "") and s.get("imap_last_login_error_at"), s)
    check("a refused login leaves the heartbeat and cursor alone",
          s["heartbeat_at"] == before and s["pid"] == 77 and s["last_uid"] == 9, s)
    check("connect's refusal is still a SystemExit", issubclass(idle_listener.LoginRejected, SystemExit))
    check("LoginRejected keeps imaplib's error out of the exit code",
          idle_listener.LoginRejected("x").code == 1 and not issubclass(idle_listener.LoginRejected, imaplib.IMAP4.error))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
