#!/usr/bin/env python3
"""
PaynaniWeb, la aplicación web para administrar paynani (PRD #434).

    python3 scripts/paynani_web.py [--host 127.0.0.1] [--port 8771]

Escucha sólo en loopback. Desde fuera se llega por la pasarela SMS, que le
reenvía lo que no es de /sms/ (FR-1), así que comparte el dominio del túnel. El
puerto sale de PAYNANI_WEB_PORT (sms.env), el mismo que lee la pasarela.

Mientras no exista el usuario, toda página dice cómo crearlo:
`scripts/paynani web user add` (FR-4). stderr lleva una línea por petición, con
el método y la ruta, nunca la consulta ni el cuerpo.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import config as sms_config  # noqa: E402
from paynani_lib.web import app, users  # noqa: E402

SMS_DEFAULT_PORT = 8770


def main(argv=None) -> int:
    sms_config.load_sms_env()  # PAYNANI_WEB_PORT y PAYNANI_SMS_PORT, como la pasarela
    parser = argparse.ArgumentParser(description="PaynaniWeb")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None,
                        help=f"default PAYNANI_WEB_PORT, or {sms_config.WEB_PORT}")
    args = parser.parse_args(argv)

    gateway_port = int(os.environ.get("PAYNANI_SMS_PORT", SMS_DEFAULT_PORT) or SMS_DEFAULT_PORT)
    port, problem = sms_config.web_port(args.port, gateway_port)
    if problem:
        print(f"paynani-web: {problem}", file=sys.stderr)
    if not port:
        print("paynani-web: no port to listen on (PAYNANI_WEB_PORT is 0 or the gateway's own port)",
              file=sys.stderr)
        return 2
    try:
        httpd = app.serve(args.host, port)
    except ValueError as exc:
        print(f"paynani-web: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"paynani-web: cannot listen on {args.host}:{port}: {exc}", file=sys.stderr)
        return 1

    stop = threading.Event()

    def handle(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)
    worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
    worker.start()
    state = "ready" if users.exists() else "waiting for `scripts/paynani web user add`"
    print(f"paynani-web: listening on {args.host}:{port} ({state})", flush=True)
    while not stop.wait(1):
        pass
    httpd.shutdown()
    httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
