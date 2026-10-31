#!/usr/bin/env python3
"""
Servicio paynani-telegram (PRD #609 FR-1 a FR-7, FR-19; TELEGRAM.md).

    python3 scripts/telegram_service.py [--state DIR] [--roster roster.md]

Recibe los mensajes privados del bot con getUpdates y espera larga y los escribe en
events.jsonl; contesta telegram.status en state/telegram/control.sock.

stdout es para el operador: cambios de estado y avisos, nunca el token, una URL de la
Bot API, un id de Telegram ni el texto de un mensaje fuera del roster.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import paths  # noqa: E402
from paynani_lib.telegram import config  # noqa: E402
from paynani_lib.telegram.service import StartError, TelegramService  # noqa: E402


def log(line: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} telegram: {line}", flush=True)


async def main_async(args: argparse.Namespace) -> int:
    values = config.read()
    token = config.token(values)
    if not (values and values.get(config.ENABLED) == "1" and token):
        log("Telegram no está activado (telegram.env sin TELEGRAM_ENABLED=1 y un token): paynani telegram setup")
        return 2
    state = Path(args.state) if args.state else Path(paths.state_dir())
    service = TelegramService(state, roster_path=Path(args.roster), token=token,
                              api_base=config.api_base(), settings=values, log=log)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await service.start()
    except StartError as exc:
        log(f"no arranca: {exc}")
        await service.stop()
        return 1
    log("arranca")
    await stop.wait()
    await service.stop()
    log("detenido")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", help="carpeta de estado (por omisión, la del clon)")
    parser.add_argument("--roster", default=str(paths.roster()), help="roster.md (por omisión el del clon)")
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
