"""
`paynani telegram setup|status|token` (PRD #609 FR-8 a FR-10; TELEGRAM.md §5).

El token sólo entra por stdin: nunca como argumento, porque un argumento queda en el
historial del shell y en la lista de procesos (FR-8). Nada de aquí lo imprime.

Códigos de salida: 0 bien, 1 el servicio no corre o Telegram no contestó, 2 el servicio
o Telegram dijeron que no, o el dueño no confirmó.
"""
from __future__ import annotations

import json
import secrets
import socket
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT / "scripts"), str(_ROOT / "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import paths  # noqa: E402

from . import api as tg_api  # noqa: E402
from . import config  # noqa: E402

DEDICATED_Q = ("¿Este token es sólo para esta instalación de paynani? Otro programa que lea el "
               "mismo bot se lleva los mensajes")


class ServiceDown(Exception):
    pass


def socket_path(state: Path | None = None) -> Path:
    return Path(state or paths.state_dir()) / "telegram" / "control.sock"


def ask(type_: str, state: Path | None = None, timeout: float = 90.0, **fields) -> dict:
    msg = {"type": type_, "id": "q_" + secrets.token_hex(16), "by": "terminal", **fields}
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(socket_path(state)))
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                raise ServiceDown("cerró la conexión")
            buf += chunk
    except (FileNotFoundError, ConnectionRefusedError, PermissionError, socket.timeout, OSError) as exc:
        raise ServiceDown(type(exc).__name__) from None
    finally:
        sock.close()
    return json.loads(buf.split(b"\n", 1)[0])


def read_token(stream=None) -> str | None:
    """La primera línea de stdin, sin espacios. Con stdin en una terminal, no se ve al escribir."""
    stream = stream or sys.stdin
    if stream.isatty():
        import getpass
        return getpass.getpass("Token del bot (no se ve al escribir): ").strip() or None
    return (stream.readline() or "").strip() or None


def confirm(question: str, flag: bool) -> bool:
    """Sí con la bandera; si no, pregunta en /dev/tty (stdin ya trae el token)."""
    if flag:
        return True
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(f"{question} [s/N] ")
            tty.flush()
            return tty.readline().strip().lower() in ("s", "si", "sí", "y", "yes")
    except OSError:
        return False


def _err(text: str) -> None:
    print(f"paynani telegram: {text}", file=sys.stderr)


def run_setup(args) -> int:
    """FR-9: token por stdin, getMe, webhook con confirmación, y telegram.env 0600."""
    env = config.env_path()
    current = config.read(env)
    if config.token(current) and not args.replace:
        _err("Telegram ya está configurado. Para cambiar de bot: paynani telegram token")
        return 2
    token = read_token()
    if not token or not config.TOKEN_RE.match(token):
        _err("eso no es un token de bot (se ve como 123456789:AA…, y lo da @BotFather)")
        return 2
    bot = tg_api.BotAPI(token, config.api_base())
    try:
        me = bot.call("getMe")
        info = bot.call("getWebhookInfo")
    except tg_api.Unauthorized:
        _err("Telegram no aceptó el token (401). Revisa que lo copiaste completo de @BotFather")
        return 2
    except (tg_api.ApiError, tg_api.NetworkError) as exc:
        _err(f"Telegram no contestó ({type(exc).__name__})")
        return 1
    print(f"bot: @{me.get('username')}")
    if (info or {}).get("url"):
        print("Este bot tiene un webhook: otra instalación o servicio puede estar recibiendo sus mensajes.")
        if not confirm("¿Lo borro para que paynani reciba con getUpdates?", args.delete_webhook):
            _err("no se escribió nada: el webhook sigue")
            return 2
    if not confirm(DEDICATED_Q, args.dedicated):
        _err("no se escribió nada: confirma que el token es sólo de esta instalación (--dedicated)")
        return 2
    if (info or {}).get("url"):
        try:
            bot.call("deleteWebhook", {"drop_pending_updates": False})
        except (tg_api.ApiError, tg_api.NetworkError) as exc:
            _err(f"no se pudo borrar el webhook ({type(exc).__name__}); no se escribió nada")
            return 1
    if current:
        config.save_backup(env)
    config.write(config.with_token(current, token), env)
    print(f"listo: {env.name} guardado (0600). Arranca o reinicia paynani-telegram para recibir.")
    return 0


def run_status(args) -> int:
    try:
        reply = ask("telegram.status", getattr(args, "state", None), timeout=10)
    except ServiceDown:
        if config.configured():
            data = {"state": "service_down"}
        else:
            print("estado: no configurado (paynani telegram setup)")
            return 1
    else:
        if reply.get("type") == "error":
            _err(reply.get("code", "error"))
            return 2
        data = reply.get("data") or {}
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data.get("state") != "service_down" else 1
    print(f"estado: {data.get('state')}" + (f" ({data['reason']})" if data.get("reason") else ""))
    if data.get("bot_username"):
        print(f"bot: @{data['bot_username']}")
    if data.get("since"):
        print(f"desde: {data['since']}")
    if data.get("last_poll_at"):
        print(f"última lectura: {data['last_poll_at']}")
    return 0 if data.get("state") != "service_down" else 1


def run_token(args) -> int:
    """FR-10 desde la terminal: token_check, confirmaciones y token_apply en el servicio."""
    token = read_token()
    if not token:
        _err("no llegó un token por stdin")
        return 2
    state = getattr(args, "state", None)
    try:
        reply = ask("telegram.token_check", state, timeout=30, token=token)
    except ServiceDown:
        _err("el servicio paynani-telegram no está corriendo; con el servicio parado usa "
             "paynani telegram setup --replace")
        return 1
    token = None
    if reply.get("type") == "error":
        _err({"invalid": "Telegram no aceptó el token"}.get(reply.get("code"), reply.get("code", "error")))
        return 2
    data = reply["data"]
    print(f"bot nuevo: @{data.get('bot_username')}")
    if data.get("same_token"):
        print("es el mismo token: no hay nada que cambiar")
        return 0
    if data.get("webhook"):
        print("Este bot tiene un webhook: otra instalación o servicio puede estar recibiendo sus mensajes.")
        if not confirm("¿Lo borro para que paynani reciba con getUpdates?", args.delete_webhook):
            _err("no se cambió nada: el webhook sigue")
            return 2
    if not confirm(DEDICATED_Q, args.dedicated):
        _err("no se cambió nada: confirma que el token es sólo de esta instalación (--dedicated)")
        return 2
    try:
        reply = ask("telegram.token_apply", state, timeout=120, check=data["check"],
                    confirm_dedicated=True, confirm_delete_webhook=bool(data.get("webhook")))
    except ServiceDown:
        _err("el servicio no contestó; revisa paynani telegram status")
        return 1
    if reply.get("type") == "error":
        _err(reply.get("code", "error"))
        return 2
    result = reply["data"]
    if result.get("result") == "applied":
        print(f"listo: ahora recibe @{result.get('bot_username')}")
        return 0
    if result.get("result") == "unchanged":
        print("es el mismo token: no hay nada que cambiar")
        return 0
    reasons = {"409": "otro programa está leyendo ese bot (409)",
               "not_ready": "el bot nuevo no quedó listo en 60 s",
               "getMe": "Telegram dejó de aceptar el token nuevo",
               "write": "no se pudo guardar telegram.env o su respaldo"}
    _err(f"se regresó al token anterior: {reasons.get(result.get('reason'), result.get('reason'))}")
    return 2
