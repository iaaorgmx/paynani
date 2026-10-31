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


def notify_owner(username: str) -> None:
    """FR-10: un correo al dueño (la primera fila Human del roster) con el @usuario nuevo, sin el token."""
    import subprocess
    import tempfile

    from paynani_lib import roster_edit

    try:
        _, members = roster_edit.members(Path(paths.roster()).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return
    owner = next((m for m in members if m.get("owner") and m.get("email")), None)
    if not owner:
        return
    body = (f"El bot de Telegram de paynani cambió. Ahora recibe @{username}.\n\n"
            "Si tú no lo cambiaste, revisa «Bot de Telegram» en PaynaniWeb o corre\n"
            "paynani telegram status en la terminal.\n")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        name = fh.name
    try:
        subprocess.run([str(ROOT / "scripts" / "send.sh"), owner["email"],
                        "paynani: cambió el bot de Telegram", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        Path(name).unlink(missing_ok=True)


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
                              api_base=config.api_base(), settings=values, log=log,
                              notify_owner=notify_owner)
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
