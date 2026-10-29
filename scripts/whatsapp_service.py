#!/usr/bin/env python3
"""
Servicio paynani-whatsapp (PRD #550 FR-1, FR-2, FR-5; WHATSAPP_BRIDGE.md).

    python3 scripts/whatsapp_service.py [--bridge-cmd "python3 fake_bridge.py"]

Arranca el puente de Baileys como proceso hijo, por stdin/stdout y sin puertos, y lo
mantiene vivo. Las llaves viven en state/whatsapp/auth/ (0700/0600, FR-10).

Lo que llega va al diario (whatsapp.received, call.*, whatsapp.health) y la CLI,
la pasarela SMS y PaynaniWeb le hablan por state/whatsapp/control.sock
(WHATSAPP_BRIDGE.md §11).

stdout es para el operador: cambios de estado y avisos, nunca el texto de un
mensaje, un QR ni un código de vinculación.
"""
from __future__ import annotations

import argparse
import asyncio
import shlex
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

import paths  # noqa: E402
from paynani_lib.whatsapp import bridge, config  # noqa: E402
from paynani_lib.whatsapp.service import WhatsAppService  # noqa: E402

MIN_NODE = 20


def log(line: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} whatsapp: {line}", flush=True)


def check_node() -> str | None:
    """None si Node sirve; si no, por qué (FR-3b)."""
    major = bridge.node_major()
    if major is None:
        return "no está Node: instálalo (20 o más nuevo) y corre npm ci en scripts/whatsapp_bridge"
    if major < MIN_NODE:
        return f"Node {major} es viejo: Baileys pide {MIN_NODE} o más nuevo"
    if not (bridge.BRIDGE_DIR / "node_modules" / "baileys").is_dir():
        return "faltan las dependencias del puente: corre npm ci en scripts/whatsapp_bridge"
    return None


async def main_async(args: argparse.Namespace) -> int:
    state = Path(args.state) if args.state else Path(paths.state_dir())
    command = shlex.split(args.bridge_cmd) if args.bridge_cmd else bridge.default_command()
    if not args.bridge_cmd:
        if not config.configured():
            log("WhatsApp no está activado (whatsapp.env sin WHATSAPP_ENABLED=1): paynani whatsapp enable")
            return 2
        problem = check_node()
        if problem:
            log(problem)
            return 2
    service = WhatsAppService(state, roster_path=Path(args.roster), command=command,
                              settings=config.read() or {},
                              log=lambda line: log(line.removeprefix("whatsapp: ")))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log(f"arranca ({' '.join(Path(c).name for c in command[:2])})")
    try:
        await service.start()
    except bridge.UnsafePath as exc:
        log(f"no arranca: {exc}")
        return 4
    runner = service._tasks[0]
    waiter = asyncio.create_task(stop.wait())
    await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
    await service.stop()
    waiter.cancel()
    if runner.done() and not runner.cancelled() and isinstance(runner.exception(), bridge.UnsafePath):
        return 4
    log("detenido")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--state", help="carpeta state/ (por omisión la de la instalación)")
    ap.add_argument("--roster", default=str(paths.roster()), help="roster.md (por omisión el del clon)")
    ap.add_argument("--bridge-cmd", help="otro puente, para pruebas (por ejemplo el falso)")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
