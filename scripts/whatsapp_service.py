#!/usr/bin/env python3
"""
Servicio paynani-whatsapp (PRD #550 FR-1, FR-2, FR-5; WHATSAPP_BRIDGE.md).

    python3 scripts/whatsapp_service.py [--bridge-cmd "python3 fake_bridge.py"]

Arranca el puente de Baileys como proceso hijo, por stdin/stdout y sin puertos, y lo
mantiene vivo. Las llaves viven en state/whatsapp/auth/ (0700/0600, FR-10).

Esta es la base de WA-1: lleva el puente y registra su estado. Los eventos del
diario, `paynani whatsapp link/send` y el roster llegan con WA-2 (#554).

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
from paynani_lib.whatsapp import bridge  # noqa: E402

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
    layout = bridge.Layout(state / "whatsapp")
    command = shlex.split(args.bridge_cmd) if args.bridge_cmd else bridge.default_command()
    if not args.bridge_cmd:
        problem = check_node()
        if problem:
            log(problem)
            return 2

    def on_health(kind: str, reason: str | None) -> None:
        # WA-2 lo escribe como evento whatsapp.health en el diario.
        log(f"salud: {kind}" + (f" ({reason})" if reason else ""))

    sup = bridge.BridgeSupervisor(layout=layout, command=command, on_health=on_health,
                                  log=lambda line: log(line.removeprefix("whatsapp: ")))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(sup.stop()))
    log(f"arranca ({' '.join(Path(c).name for c in command[:2])})")
    await sup.run()
    log("detenido")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--state", help="carpeta state/ (por omisión la de la instalación)")
    ap.add_argument("--bridge-cmd", help="otro puente, para pruebas (por ejemplo el falso)")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
