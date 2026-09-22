"""
Run the onboarding flow end to end. Port of scripts/setup_web.sh's lifecycle
onto Python's own http.server, so this needs nothing scripts/setup_web.sh's
PHP path does: no `php` binary, no `apt-get install`, no `sudo`.

`setup` (#232) is the discoverable name for this; `onboard` is kept working
forever as an alias -- it is written into INSTALL.md, MAILBOX_SETUP.md and
several fleet agents' own persistent notes, and breaking it to gain a nicer
name would bill ten hosts for a rename none of them asked for. `config web`
(also #232) is the same server and the same form -- read_env() in server.py
already prefills every field except the password from whatever is on disk,
so this doubles as an editor, not only a first-run wizard -- with a shorter
banner appropriate to editing an install that already works.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import secrets
import signal
import socket
import sys
import threading
import time
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))
from paths import env_file, state_dir  # noqa: E402

from . import guard
from .server import make_handler

SERVER_MARKER_NAME = "setup.server.json"


def _fingerprint(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return "absent"
    return hashlib.sha256(data).hexdigest()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    return True


def _port_open(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def find_live_server(state: Path) -> dict | None:
    """
    A setup/config-web server this same install already has running, or
    None.

    Two servers on one .env is a cheap way to lose configuration: whichever
    saves last wins silently, and the human filling in the first form has no
    idea a second one exists. The marker this checks is written by the
    process that started the server and removed when it stops, so a stale
    marker (process gone, or something else now holding the port) is treated
    the same as no server at all rather than trusted blindly.
    """
    marker = state / SERVER_MARKER_NAME
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid, port = info.get("pid"), info.get("port")
    if not isinstance(pid, int) or not isinstance(port, int):
        marker.unlink(missing_ok=True)
        return None
    if _pid_alive(pid) and _port_open(port):
        return info
    marker.unlink(missing_ok=True)
    return None


def run(port: int = 8765, mode: str = "setup") -> int:
    """mode is "setup" (first-run wizard, printed by `setup`/`onboard`) or
    "config_web" (editing an install that already works, printed by
    `config web`) -- same server, same form, different banner."""
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    try:
        state.chmod(0o700)
    except OSError:
        pass

    live = find_live_server(state)
    if live is not None:
        print()
        print(f"  A setup server for this install is already running: {live['url']}")
        print("  Open that link rather than starting a second one -- two servers")
        print("  writing the same .env is how configuration gets lost.")
        print()
        return 0

    # A new key every run. An old link stops working the moment this
    # restarts, which is the behaviour you want from something that writes a
    # password to disk.
    token = secrets.token_hex(24)
    token_path = guard.token_path(state)
    old_umask = os.umask(0o077)
    try:
        token_path.write_text(token + "\n", encoding="utf-8")
    finally:
        os.umask(old_umask)
    try:
        token_path.chmod(0o600)
    except OSError:
        pass

    target = env_file()
    saved_event = threading.Event()
    handler_cls = make_handler(state, saved_event)

    # A plain `kill` (SIGTERM, no signal named) used to skip the `finally`
    # below entirely -- Python does not treat SIGTERM as KeyboardInterrupt on
    # its own, so the token file survived a process nothing gave a graceful
    # way to stop. Routing it through the same exception the Ctrl-C path
    # already handles means one cleanup path covers both.
    def _handle_sigterm(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    command = "onboard" if mode == "setup" else "config web"
    try:
        httpd = HTTPServer(("127.0.0.1", port), handler_cls)
    except OSError as exc:
        print(f"The server did not start on port {port}: {exc}", file=sys.stderr)
        print(f"Try:  scripts/paynani {command} --port {port + 1}", file=sys.stderr)
        token_path.unlink(missing_ok=True)
        return 1

    server_thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True
    )
    server_thread.start()

    url = f"http://127.0.0.1:{port}/?t={token}"
    marker_path = state / SERVER_MARKER_NAME
    marker_old_umask = os.umask(0o077)
    try:
        marker_path.write_text(json.dumps({
            "pid": os.getpid(), "port": port, "url": url,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }), encoding="utf-8")
    finally:
        os.umask(marker_old_umask)
    try:
        marker_path.chmod(0o600)
    except OSError:
        pass

    host = socket.getfqdn() or socket.gethostname()
    print()
    if mode == "setup":
        print("  paynani — mailbox setup")
        print("  " + "─" * 60)
        print()
        print("  Send this link to whoever is setting up the mailbox:")
    else:
        print("  paynani — edit configuration")
        print("  " + "─" * 60)
        print()
        print("  Open this link to change what's in .env:")
    print()
    print(f"      {url}")
    print()
    print("  If they are not sitting at this machine, they run this first,")
    print("  on their own computer, and then open the same link there:")
    print()
    print(f"      ssh -L {port}:127.0.0.1:{port} {getpass.getuser()}@{host}")
    print()
    print("  (that host name is this machine's idea of itself — replace it")
    print("   with whatever you normally ssh to, if they differ)")
    print()
    print("  The link works once, until this stops. Ctrl-C when finished.")
    print()

    # Stop the moment a save actually succeeds. server.py sets saved_event
    # from inside the request that just wrote the file, once the response
    # carrying the confirmation page is already on the wire -- so this does
    # not need to guess *whether* something changed the way polling a
    # fingerprint would, only wait to be told. The fingerprint check survives
    # as a fallback for the one thing the event cannot see: something other
    # than this server's own save path replacing the file underneath it.
    before = _fingerprint(target)
    try:
        while server_thread.is_alive():
            fired = saved_event.wait(timeout=1)
            if fired or _fingerprint(target) != before:
                print(f"  Settings saved to {target} — stopping.")
                print()
                break
    except KeyboardInterrupt:
        print()
    finally:
        httpd.shutdown()
        server_thread.join(timeout=5)
        token_path.unlink(missing_ok=True)
        marker_path.unlink(missing_ok=True)

    return 0
