"""
La configuración inicial de Telegram (PRD #609 FR-9; #635): la usan `paynani telegram setup`
y «Cuenta de Telegram» en PaynaniWeb.

`probe()` prueba el token con `getMe` y `getWebhookInfo`. `save()` borra el webhook si
hace falta y escribe `telegram.env` (0600). `initial()` hace las dos cosas de un jalón
para la web: compara el usuario del bot con el de `getMe` (Q282 = A) y exige la casilla
«sólo de esta instalación», que también autoriza borrar el webhook (Q283 = A).

La escritura va bajo un candado entre procesos (`.telegram-setup.lock`, junto a
telegram.env) y, sin `replace`, vuelve a comprobar dentro que no haya token: de dos
configuraciones a la vez, una gana y la otra recibe `already_configured` (Ximena en
#639). `getMe` y `getWebhookInfo` van antes del candado; `deleteWebhook` va dentro,
después de la segunda comprobación, para no borrar el webhook de un bot que no se guarda.

Nada de aquí imprime ni registra el token. Los errores son `SetupError(code)` con un
código fijo, sin el token ni partes de él.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
from pathlib import Path

from . import api as tg_api
from . import config

# Los códigos de error, para la CLI y la web.
NOT_A_TOKEN = "not_a_token"
ALREADY = "already_configured"
UNAUTHORIZED = "unauthorized"
UNREACHABLE = "unreachable"
USERNAME = "username_mismatch"
DEDICATED = "dedicated_required"
WEBHOOK = "webhook_not_deleted"
WRITE = "write_failed"

USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")


class SetupError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_username(value: str) -> str | None:
    """`@MiBot` o `MiBot` → `MiBot`; None si no tiene forma de usuario de Telegram."""
    match = USERNAME_RE.match((value or "").strip())
    return match.group(1) if match else None


def already_configured(env: Path | None = None) -> bool:
    """Hay un token en telegram.env, activado o no: la configuración inicial ya se hizo."""
    return bool(config.token(config.read(env)))


def probe(token: str, base: str | None = None) -> dict:
    """`{"bot_username", "webhook"}` del token, o SetupError. No escribe nada."""
    if not token or not config.TOKEN_RE.match(token):
        raise SetupError(NOT_A_TOKEN)
    bot = tg_api.BotAPI(token, base or config.api_base())
    try:
        me = bot.call("getMe")
        info = bot.call("getWebhookInfo")
    except tg_api.Unauthorized:
        raise SetupError(UNAUTHORIZED) from None
    except (tg_api.ApiError, tg_api.NetworkError):
        raise SetupError(UNREACHABLE) from None
    return {"bot_username": str((me or {}).get("username") or ""), "webhook": bool((info or {}).get("url"))}


@contextlib.contextmanager
def _locked(env: Path):
    """Candado exclusivo entre procesos para escribir telegram.env (flock, 0600)."""
    try:
        fd = os.open(env.parent / ".telegram-setup.lock", os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        raise SetupError(WRITE) from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def save(token: str, *, webhook: bool, env: Path | None = None, base: str | None = None,
         replace: bool = False) -> Path:
    """
    Escribe telegram.env (0600), con copia del anterior, bajo el candado. Sin `replace`,
    si otro proceso ya puso un token mientras tanto, `already_configured` y nada cambia.
    El webhook se borra sólo cuando la escritura ya es de este proceso.
    """
    env = config.env_path() if env is None else Path(env)
    with _locked(env):
        if not replace and already_configured(env):
            raise SetupError(ALREADY)
        if webhook:
            try:
                tg_api.BotAPI(token, base or config.api_base()).call("deleteWebhook", {"drop_pending_updates": False})
            except (tg_api.ApiError, tg_api.NetworkError):
                raise SetupError(WEBHOOK) from None
        current = config.read(env)
        try:
            if current:
                config.save_backup(env)
            config.write(config.with_token(current, token), env)
        except (OSError, ValueError):
            raise SetupError(WRITE) from None
    return env


def initial(token: str, username: str, *, dedicated: bool, env: Path | None = None,
            base: str | None = None) -> dict:
    """
    La configuración inicial desde la web (#635), en este orden: que no haya token, el
    formato, `getMe`, el usuario (Q282), la casilla (Q283) y `save()`, que vuelve a mirar
    que no haya token dentro del candado. Si algo falla no se escribe nada.
    `{"bot_username", "webhook_deleted"}`.
    """
    if already_configured(env):
        raise SetupError(ALREADY)
    found = probe(token, base)
    wanted = normalize_username(username)
    if not wanted or wanted.lower() != found["bot_username"].lower():
        raise SetupError(USERNAME)
    if not dedicated:
        raise SetupError(DEDICATED)
    save(token, webhook=found["webhook"], env=env, base=base)
    return {"bot_username": found["bot_username"], "webhook_deleted": found["webhook"]}
