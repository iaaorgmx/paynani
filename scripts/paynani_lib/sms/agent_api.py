"""
El agente de IA para PaynaniApp (#692, SMS_GATEWAY.md §13).

La app dibuja en su menú el renglón «AI Agent» con el estado del agente y, al tocarlo, la
pantalla «Agente» (PaynaniApp#11). Los datos son los mismos de `/agent` en PaynaniWeb:
`web/agent.py` (`summary` y `build`), que sólo leen lo que ya existe.

- `agent.get` llega por el WebSocket del teléfono y responde el modelo de la página.
- `watch` revisa el estado cada `WATCH_S` y avisa `agent.changed` sólo cuando cambia.
- Va con las mismas condiciones y el mismo `grant` que Webchat (`webchat.owner`): el
  teléfono emparejado del dueño.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Awaitable, Callable

from . import webchat_api

TYPES = ("agent.get",)
GRANT = webchat_api.GRANT
ID_RE = re.compile(r"^q_[0-9a-f]{32}$")
WATCH_S = 30.0
DROP = ("now",)                 # la app usa `server_time` del welcome
DROP_ACTIVITY = ("href",)       # en la app no se abren


def jsonable(value):
    """Las fechas en ISO UTC; lo demás igual. Recorre dicts y listas."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def payload(model: dict) -> dict:
    out = {k: v for k, v in model.items() if k not in DROP}
    out["activity"] = [{k: v for k, v in item.items() if k not in DROP_ACTIVITY}
                       for item in model.get("activity") or []]
    return jsonable(out)


class AgentRelay:
    """
    `model()` es `web/agent.build(...)` y `status()` es el `status` de `summary(...)`, o
    None si no se puede saber. Las pruebas pasan los suyos.
    """

    def __init__(self, *, model: Callable[[], dict] | None = None,
                 status: Callable[[], str | None] | None = None, log=None, watch_s: float = WATCH_S):
        self._model = model
        self._status = status or (lambda: None)
        self.log = log or (lambda line: None)
        self.watch_s = watch_s

    def accepts(self, available: bool) -> list[str]:
        return list(TYPES) if available and self._model is not None else []

    async def handle(self, msg: dict, *, grants: list) -> dict:
        rid = msg.get("id")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            return {"type": "error", "code": "missing_field", "ref": str(rid or "")[:80], "field": "id",
                    "detail": "id es q_ y 32 hex"}
        if GRANT not in (grants or []):
            return {"type": "error", "ref": rid, "code": "forbidden"}
        if self._model is None:
            return {"type": "error", "ref": rid, "code": "unavailable"}
        try:
            model = await asyncio.to_thread(self._model)
        except Exception as exc:  # noqa: BLE001 - un archivo a medias no tumba la conexión
            self.log(f"agent.get: no se pudo armar el modelo ({type(exc).__name__})")
            return {"type": "error", "ref": rid, "code": "unavailable"}
        return {"type": "result", "ref": rid, "ok": True, "data": payload(model)}

    def _read_status(self) -> str | None:
        try:
            return self._status()
        except Exception as exc:  # noqa: BLE001
            self.log(f"agent.changed: no se pudo leer el estado ({type(exc).__name__})")
            return None

    async def watch(self, on_change: Callable[[str], Awaitable[None]]) -> None:
        """Para siempre: `on_change(status)` cuando el estado cambia. Una lectura que falla
        no cuenta como cambio."""
        last = await asyncio.to_thread(self._read_status)
        while True:
            await asyncio.sleep(self.watch_s)
            now = await asyncio.to_thread(self._read_status)
            if now is None:
                continue
            if last is not None and now != last:
                await on_change(now)
            last = now
