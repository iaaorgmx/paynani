"""
`paynani telegram setup|status|token|send|draft|thread` (PRD #609 FR-8 a FR-10, FR-20 a
FR-27; TELEGRAM.md §5).

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
    print(f"listo: {env.name} guardado (0600).")
    _say_started(service_control("start"))
    return 0


# --- el servicio y `enable`/`disable` (TG-6) ---------------------------------------------------
UNIT = "paynani-telegram.service"
LABEL = "com.paynani.telegram"


def _service_installed() -> bool:
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()
    return (Path.home() / ".config" / "systemd" / "user" / UNIT).exists()


def service_control(action: str) -> str:
    """
    Arranca (`start`) o detiene (`stop`) el servicio que puso el instalador (`--with-telegram`).
    `not-installed`, `started`, `stopped` o `failed`. Ni el token ni ids pasan por aquí.
    """
    import os
    import subprocess

    if not _service_installed():
        return "not-installed"
    if sys.platform == "darwin":
        target = f"gui/{os.getuid()}/{LABEL}"
        # Detenido con TERM, el servicio sale con 0 y KeepAlive (SuccessfulExit=false) no lo
        # vuelve a arrancar; tampoco al iniciar sesión, porque telegram.env ya dice que no.
        cmd = ["launchctl", "kill", "TERM", target] if action == "stop" else ["launchctl", "kickstart", "-k", target]
    else:
        cmd = ["systemctl", "--user", "stop" if action == "stop" else "restart", UNIT]
    try:
        rc = subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode
    except (OSError, subprocess.SubprocessError):
        return "failed"
    if rc != 0:
        return "failed"
    return "stopped" if action == "stop" else "started"


def _say_started(result: str) -> None:
    if result == "started":
        print("paynani-telegram arrancó. Revisa con: paynani telegram status")
    elif result == "not-installed":
        print("El servicio paynani-telegram no está instalado. Instálalo con el instalador y --with-telegram "
              "(INSTALL.md, «Telegram»); arranca solo con este telegram.env.")
    else:
        print("No pude arrancar paynani-telegram: arráncalo o reinícialo a mano (INSTALL.md, «Telegram»).")


def run_disable(args) -> int:
    """
    Apaga Telegram: `TELEGRAM_ENABLED=0` en telegram.env y detiene el servicio. El token se
    queda en el archivo (0600) para `paynani telegram enable`. La pasarela y PaynaniWeb dejan de
    mostrar Telegram en cuanto ven el cambio.
    """
    env = config.env_path()
    values = config.read(env)
    if values is None:
        print("Telegram no está configurado: no hay nada que desactivar.")
        return 0
    if values.get(config.ENABLED) != "0":
        config.write(dict(values, **{config.ENABLED: "0"}), env)
        print(f"Telegram desactivado ({config.ENABLED}=0 en {env.name}). El token se queda en el archivo.")
    else:
        print("Telegram ya estaba desactivado.")
    result = service_control("stop")
    if result == "stopped":
        print("paynani-telegram detenido.")
    elif result == "failed":
        _err("no pude detener paynani-telegram: detenlo a mano (al arrancar ya no recibe)")
        return 1
    print("Para volver a activarlo: paynani telegram enable")
    return 0


def run_enable(args) -> int:
    """Vuelve a encender Telegram con el token que ya está en telegram.env y arranca el servicio."""
    env = config.env_path()
    values = config.read(env)
    if not config.token(values):
        _err("no hay un token en telegram.env: usa paynani telegram setup")
        return 2
    if values.get(config.ENABLED) != "1":
        config.write(dict(values, **{config.ENABLED: "1"}), env)
        print(f"Telegram activado ({config.ENABLED}=1 en {env.name}).")
    else:
        print("Telegram ya estaba activado.")
    _say_started(service_control("start"))
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


# --- mandar (TG-4: FR-20, FR-22, FR-24, FR-27) ---------------------------------------------

def _refused(reply: dict) -> int:
    code = reply.get("code", "error")
    detail = reply.get("detail")
    extra = f" (espera {reply['retry_after_s']} s)" if reply.get("retry_after_s") else ""
    _err(f"{code}{': ' + detail if detail else ''}{extra}")
    return 1 if code == "unavailable" else 2


def _ask(args, type_: str, timeout: float = 120, **fields):
    try:
        reply = ask(type_, getattr(args, "state", None), timeout=timeout, **fields)
    except ServiceDown:
        _err("el servicio paynani-telegram no está corriendo (paynani telegram status)")
        return None, 1
    if reply.get("type") == "error":
        return None, _refused(reply)
    return reply.get("data") or {}, 0


def run_send(args) -> int:
    if args.stream:
        if args.text or args.file:
            _err("--stream lee el texto de stdin: sin texto ni --file")
            return 2
        return _run_stream(args)
    text = " ".join(args.text or [])
    if not text and not args.file and not sys.stdin.isatty():
        text = sys.stdin.read()
    fields = {"contact": args.contact, "text": text}
    if args.file:
        fields["file"] = str(Path(args.file).expanduser().absolute())
    data, rc = _ask(args, "telegram.send", **fields)
    if rc:
        return rc
    print(f"{data.get('ref')}\t{data.get('status')}")
    return 0


def _run_stream(args) -> int:
    import codecs
    import os

    data, rc = _ask(args, "telegram.stream_open", contact=args.contact)
    if rc:
        return rc
    sid = data["stream"]
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    while True:
        chunk = os.read(sys.stdin.fileno(), 4096)
        text = decoder.decode(chunk, final=not chunk)
        if text:
            _, rc = _ask(args, "telegram.stream_append", stream=sid, text=text)
            if rc:
                return rc
        if not chunk:
            break
    data, rc = _ask(args, "telegram.stream_close", stream=sid)
    if rc:
        return rc
    print(f"{data.get('ref')}\t{data.get('status')}\t{data.get('transport')}")
    return 0


def run_draft(args) -> int:
    data, rc = _ask(args, "telegram.draft", contact=args.contact, text=" ".join(args.text))
    if rc:
        return rc
    print(f"borrador\t{data.get('transport')}")
    return 0


def run_thread(args) -> int:
    data, rc = _ask(args, "telegram.thread", timeout=30, contact=args.contact, limit=args.limit)
    if rc:
        return rc
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(data.get("name") or "")
    for m in reversed(data.get("messages") or []):
        arrow = "←" if m.get("dir") == "in" else "→"
        extra = f" [{m['status']}]" if m.get("status") else (" (editado)" if m.get("edited") else "")
        print(f"{m.get('at')} {arrow} {m.get('text') or '[' + str(m.get('kind')) + ']'}{extra}")
    return 0


def run_threads(args) -> int:
    data, rc = _ask(args, "telegram.threads", timeout=30, limit=args.limit)
    if rc:
        return rc
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    for t in data.get("threads") or []:
        arrow = "←" if t.get("last_dir") == "in" else "→"
        excerpt = t.get("last_excerpt") or ("(oculto: fuera del roster)" if t.get("hidden") else "")
        print(f"{t.get('last_at')}  {t.get('name')}  {arrow} {excerpt}")
    return 0
