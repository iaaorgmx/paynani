#!/usr/bin/env python3
"""
Pasarela SMS de paynani (SMS_GATEWAY.md, SRV-1).

    python3 scripts/sms_gateway.py [--host 127.0.0.1] [--port 8770] [--web-port 8771]

Escucha sólo en loopback; el teléfono llega por el túnel (DEC-2). La dirección
pública que va en el QR sale de PAYNANI_SMS_PUBLIC_URL (por ejemplo
https://metis-grill.ngrok.io), o del Host de la petición si no está.

stdout es para el operador: una línea por SMS o llamada (la misma que llega al
agente) y los cambios de conexión. Nunca el texto completo de un SMS, tokens ni
códigos.

Lo que no es de /sms/ se reenvía a PaynaniWeb en 127.0.0.1:--web-port
(PAYNANI_WEB_PORT, 8771 por omisión; PRD #434 FR-1). `--web-port 0` lo apaga.
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
from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.sms import telegram_api, whatsapp_api  # noqa: E402

DEFAULT_PORT = 8770  # 8765 es del onboarding y de `sms pair --web`, que corren a la vez


def roster_service(state: Path, roster: Path) -> roster_api.RosterService:
    """
    La pantalla «Roster» de la instalación (SMS_GATEWAY.md §11): el roster del
    agente, las cuentas de accounts.json y el correo al humano por send.sh. De .env
    sólo se lee la dirección del agente, para mostrarla; nunca la contraseña.
    """
    from paynani_lib import accounts, envfile

    agent_email = ""
    try:
        agent_email = envfile.read_env().get("AGENT_EMAIL_ACCOUNT", "")
    except Exception as exc:  # noqa: BLE001 -- sólo es para mostrar
        gw.log(f"roster: no se leyó la dirección del agente ({type(exc).__name__})")
    # rules/ junto al roster del agente (#418): en una instalación es el clon, y una
    # pasarela de prueba con --roster en otra carpeta no mezcla sus reglas con las de él.
    return roster_api.RosterService(roster, state, accounts_file=accounts.accounts_path(),
                                    agent_email=agent_email, notifier=roster_api.send_sh_notifier,
                                    log=gw.log, rules_root=roster.parent)


def whatsapp_relay(state: Path, roster: roster_api.RosterService) -> whatsapp_api.WhatsAppRelay:
    """
    WhatsApp desde PaynaniApp (SMS_GATEWAY.md §12): el servicio paynani-whatsapp por
    state/whatsapp/control.sock, `whatsapp.env` para saber si está configurado, y el
    aviso al dueño por send.sh, como los cambios del roster.
    """
    return whatsapp_api.WhatsAppRelay(state, notifier=roster_api.send_sh_notifier,
                                      owner_email=roster.owner_email, log=gw.log)


def api_tokens_path() -> Path | None:
    """web/api_tokens.json de PaynaniWeb (PRD #491), para la opción «el agente contesta» (FR-12)."""
    try:
        from paynani_lib.web import api_tokens
        return api_tokens.path_for()
    except Exception as exc:  # noqa: BLE001 -- sin la web, el agente simplemente no contesta
        gw.log(f"no se encontró api_tokens.json ({type(exc).__name__}); las respuestas a la API no las contesta el agente")
        return None


def main(argv=None) -> int:
    sms_config.load_sms_env()  # antes de leer los valores por omisión de argparse
    parser = argparse.ArgumentParser(description="Pasarela SMS de paynani")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PAYNANI_SMS_PORT", DEFAULT_PORT)))
    parser.add_argument("--state", default=str(paths.state_dir()))
    parser.add_argument("--roster", default=str(paths.roster()))
    parser.add_argument("--public-url", default=os.environ.get("PAYNANI_SMS_PUBLIC_URL", ""))
    parser.add_argument("--web-port", type=int, default=None,
                        help=f"PaynaniWeb (PAYNANI_WEB_PORT, {gw.WEB_PORT} por omisión); 0 apaga el reenvío")
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "::1", "localhost"):
        print("La pasarela sólo escucha en loopback; el teléfono llega por el túnel.", file=sys.stderr)
        return 2

    web_port, web_problem = sms_config.web_port(args.web_port, args.port)
    if web_problem:
        gw.log(web_problem)
    gw.log(f"fuera de /sms/: reenvío a PaynaniWeb en 127.0.0.1:{web_port}" if web_port
           else "fuera de /sms/: 404 (reenvío a PaynaniWeb apagado)")

    state = Path(args.state)
    problems = []
    warn, critical = sms_config.battery_thresholds(problems=problems)
    for problem in problems:
        gw.log(f"sms.env: {problem}")
    gw.log(f"avisos de batería: warn bajo {warn} %, critical bajo {critical} %")
    roster = roster_service(state, Path(args.roster))
    gateway = gw.Gateway(state, state / "events.jsonl", Path(args.roster), public_url=args.public_url,
                         battery_warn_pct=warn, battery_critical_pct=critical,
                         roster_service=roster, web_port=web_port,
                         api_tokens_path=api_tokens_path(), whatsapp=whatsapp_relay(state, roster),
                         # TELEGRAM.md §6: telegram.env dice si está configurado.
                         telegram=telegram_api.TelegramRelay(state, log=gw.log))

    async def run():
        server = await gw.serve(gateway, args.host, args.port)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()
        server.close()
        await gateway.shutdown()
        try:
            await asyncio.wait_for(server.wait_closed(), 5)
        except asyncio.TimeoutError:
            pass

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
