"""
Run the onboarding flow end to end. Port of scripts/setup_web.sh's lifecycle
onto Python's own http.server, so this needs nothing scripts/setup_web.sh's
PHP path does: no `php` binary, no `apt-get install`, no `sudo`.
"""

from __future__ import annotations

import getpass
import hashlib
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


def _fingerprint(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return "absent"
    return hashlib.sha256(data).hexdigest()


def run(port: int = 8765) -> int:
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    try:
        state.chmod(0o700)
    except OSError:
        pass

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

    try:
        httpd = HTTPServer(("127.0.0.1", port), handler_cls)
    except OSError as exc:
        print(f"The server did not start on port {port}: {exc}", file=sys.stderr)
        print(f"Try:  scripts/paynani onboard --port {port + 1}", file=sys.stderr)
        token_path.unlink(missing_ok=True)
        return 1

    server_thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True
    )
    server_thread.start()

    url = f"http://127.0.0.1:{port}/?t={token}"
    host = socket.getfqdn() or socket.gethostname()
    print()
    print("  paynani — mailbox setup")
    print("  " + "─" * 60)
    print()
    print("  Send this link to whoever is setting up the mailbox:")
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

    return 0
