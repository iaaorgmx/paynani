#!/usr/bin/env python3
"""
Pasarela SMS de paynani (SMS_GATEWAY.md, SRV-1).

    python3 scripts/sms_gateway.py [--host 127.0.0.1] [--port 8765]

Escucha sólo en loopback; el teléfono llega por el túnel (DEC-2). La dirección
pública que va en el QR sale de PAYNANI_SMS_PUBLIC_URL (por ejemplo
https://metis-grill.ngrok.io), o del Host de la petición si no está.

stdout es para el operador: una línea por SMS o llamada (la misma que llega al
agente) y los cambios de conexión. Nunca el texto completo de un SMS, tokens ni
códigos.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import paths  # noqa: E402
from paynani_lib.sms import config as sms_config  # noqa: E402
from paynani_lib.sms import gateway as gw  # noqa: E402

DEFAULT_PORT = 8765


def main(argv=None) -> int:
    sms_config.load_sms_env()  # antes de leer los valores por omisión de argparse
    parser = argparse.ArgumentParser(description="Pasarela SMS de paynani")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PAYNANI_SMS_PORT", DEFAULT_PORT)))
    parser.add_argument("--state", default=str(paths.state_dir()))
    parser.add_argument("--roster", default=str(paths.roster()))
    parser.add_argument("--public-url", default=os.environ.get("PAYNANI_SMS_PUBLIC_URL", ""))
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "::1", "localhost"):
        print("La pasarela sólo escucha en loopback; el teléfono llega por el túnel.", file=sys.stderr)
        return 2

    state = Path(args.state)
    gateway = gw.Gateway(state, state / "events.jsonl", Path(args.roster), public_url=args.public_url)

    async def run():
        server = await gw.serve(gateway, args.host, args.port)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()
        if gateway.conn is not None:
            await gateway.conn.close(1001, "la pasarela se apaga")
        server.close()
        await server.wait_closed()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
