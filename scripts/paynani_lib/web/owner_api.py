"""
La API del dueño: `POST /api/owner` (FR-A5 a FR-A9 de iaaorgmx/PaynaniWebMT#2, A2 #720).

La usa PaynaniWebMT, emparejada con `POST /api/owner/pair` (A1 #719). Entra con
`Authorization: Bearer pw_…`, nunca con un token de agente, y responde como
`/api/agent`: JSON con `result` y `request_id`, y los mismos códigos de error.
La autenticación, los topes y la bitácora viven en `app.py`; aquí sólo las acciones.

Cómo agrega acciones A3 y A4 (FR-A6). Cada acción llama a la misma función que usa la
página de PaynaniWeb; si esa lógica está mezclada con el HTML, primero se separa en un
servicio (como `sms/owner.py`, #724). Luego se registra:

    from . import owner_api

    @owner_api.action("SendWhatsApp", sensitive=False)
    def send_whatsapp(call: owner_api.OwnerCall) -> dict:
        ...
        return {"message_id": ...}

- `call.params`, `call.text()`, `call.number()`, `call.required()` y `call.roster()`
  funcionan como en `api_actions.Call`, así que las acciones de `/api/agent` que ya
  existen se pueden registrar tal cual (`owner_api.reuse(...)`).
- `call.client` es el registro del cliente web (`client_id`, `name`, `app_name`…), sin
  el hash del token. Úsalo como llave del estado que antes iba por sesión web.
- `call.files` son los archivos de una subida `multipart/form-data`: una lista de
  `{"field", "name", "mime", "data"}` en memoria (20 MB cada uno, 25 MB por mensaje).
- Para bajar un archivo, la acción devuelve `FileResult(name, data)`: sale como
  `application/octet-stream` con `Content-Disposition`, no en JSON (FR-A9).
- `sensitive=True` marca las acciones de FR-A10. paynani no pide la contraseña de
  PaynaniWeb (la pide PaynaniWebMT); queda en la bitácora como `owner_sensitive`, y
  los correos al dueño dicen `call.origin()`: «desde PaynaniWebMT (<nombre>)».
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .. import i18n
from . import api_actions, owner_changes, owner_clients
from .api_actions import ApiError

RATE_PER_MINUTE = 120        # el doble que un token de agente, por el polling (FR-A5)


@dataclass
class FileResult:
    """Una respuesta de archivo, no JSON (FR-A9)."""
    name: str
    data: bytes


class OwnerCall(api_actions.Call):
    def __init__(self, ctx, client: dict, ip: str, params: dict, request_id: str = "", files=None):
        super().__init__(ctx, client, ip, params, request_id)
        self.client = owner_clients.public(client)
        self.files = list(files or [])

    def origin(self) -> str:
        """Para los correos y la bitácora de las acciones delicadas (FR-A10)."""
        return f"desde {self.client.get('app_name') or 'PaynaniWebMT'} ({self.client.get('name') or ''})"


ACTIONS: dict[str, tuple[bool, object]] = {}


def action(name: str, *, sensitive: bool = False):
    def register(handler):
        if name in ACTIONS:
            raise ValueError(f"duplicate owner action {name}")
        ACTIONS[name] = (sensitive, handler)
        return handler
    return register


def reuse(name: str, handler, *, sensitive: bool = False) -> None:
    """Registra una acción de `/api/agent` sin cambiarla (FR-A6)."""
    action(name, sensitive=sensitive)(handler)


def is_sensitive(name) -> bool:
    return isinstance(name, str) and name in ACTIONS and ACTIONS[name][0]


def run(ctx, client: dict, ip: str, params: dict, request_id: str = "", files=None):
    """El dict de la respuesta (sin `result` ni `request_id`), un FileResult, o ApiError."""
    name = params.get("action")
    if not isinstance(name, str) or name not in ACTIONS:
        raise ApiError(400, "invalid_action", "Unknown API action.")
    _, handler = ACTIONS[name]
    return handler(OwnerCall(ctx, client, ip, params, request_id, files))


# ---- Instancia (FR-A7) --------------------------------------------------------------------

@action("GetInstance")
def get_instance(call: OwnerCall) -> dict:
    """Lo que PaynaniWebMT necesita para dibujar el marco: versión, agente, canales e idiomas."""
    version, commit = call.ctx.version
    summary = call.ctx.agent_summary() or {}
    user = call.ctx.user() or {}
    return {
        "paynani": {"version": version, "commit": commit},
        "agent": {"name": summary.get("name", ""), "email": call.ctx.agent_email(),
                  "runtime": summary.get("runtime", ""), "runtime_label": summary.get("runtime_label", ""),
                  "status": summary.get("status", "")},
        "owner": {"name": user.get("name", ""), "email": user.get("email", "")},
        "channels": {"mail": True, "sms": (call.ctx.state_dir() / "sms").is_dir(),
                     "whatsapp": bool(call.ctx.whatsapp_configured()),
                     "telegram": bool(call.ctx.telegram_configured()),
                     # Webchat existe en cuanto hay usuario de PaynaniWeb (§13), y sin él no hay API.
                     "webchat": bool(user)},
        "languages": sorted(i18n.LANGUAGES),
        "client": call.client,
        "now": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@action("GetChanges")
def get_changes(call: OwnerCall) -> dict:
    """FR-A8: qué áreas cambiaron desde `cursor`. Sin cursor, todas, con `reset: true`."""
    cursor = call.text("cursor", limit=8192)
    summary = call.ctx.agent_summary() or {}
    return owner_changes.changes(call.ctx.state_dir(), call.ctx.roster_path(), cursor,
                                 agent_status=str(summary.get("status", "")))


@action("Disconnect")
def disconnect(call: OwnerCall) -> dict:
    """El cliente se revoca a sí mismo (por ejemplo, «Desconectar» en PaynaniWebMT)."""
    record = owner_clients.revoke(call.client["client_id"],
                                  path=owner_clients.clients_path(call.ctx.user_path()))
    if record is None:
        raise ApiError(401, "token_revoked", "This client was already revoked.")
    call.ctx.notifier.owner(
        call.ctx.user(), "Paynani: app desconectada",
        f"«{record['name']}» ({record['client_id']}) se desconectó de tu paynani {call.origin()}. "
        "Su token ya no abre la API del dueño.")
    return {"client_id": record["client_id"], "revoked_at": record["revoked_at"]}


# Las acciones de A4 (#722) se registran al importarse.
from . import owner_channels  # noqa: E402,F401
