"""
Acciones de la API del dueño para correo, roster, Dashboard, API Tokens y Agente
(A3, iaaorgmx/paynani#721; FR-A7 y FR-A10 de iaaorgmx/PaynaniWebMT#2).

Cada acción llama a lo mismo que la página de PaynaniWeb (FR-A6):
- las de `/api/agent` que sirven tal cual se registran con `owner_api.reuse`: el dueño no
  tiene permisos por token, puede todo;
- el resto usa los servicios del núcleo que usa la web: `CTX.mailer` y `mail_compose` para
  «Nuevo correo», `account_config` y `CTX.updater` para la configuración de la cuenta
  principal, `CTX.dashboard_model` y `CTX.agent_model`, `api_tokens` y
  `token_pages.create_from_values` para los tokens, y el servicio del roster (§11).

Las delicadas (`sensitive=True`) son las de FR-A10: paynani no pide la contraseña de
PaynaniWeb (la pide PaynaniWebMT con la suya) y el aviso al dueño dice `call.origin()`.
"""
from __future__ import annotations

import json
import re
import sys

from .. import i18n
from . import api_actions, api_tokens, account_config, config_pages, dashboard, mail, mail_compose, owner_api, token_pages
from .api_actions import ApiError

TOKEN_ID = re.compile(r"[a-f0-9]{64}")


def _plain(value):
    """Lo que arman el Dashboard y el Agente, como JSON: fechas y rutas como texto."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _bool(call: owner_api.OwnerCall, key: str, default: bool = False) -> bool:
    value = call.params.get(key, default)
    if not isinstance(value, bool):
        raise ApiError(400, "invalid_parameter", f"{key} must be true or false.", field=key)
    return value


# ---- Correo ------------------------------------------------------------------------------

owner_api.reuse("ListMail", api_actions.list_mail)
owner_api.reuse("AddAccount", api_actions.add_account, sensitive=True)
owner_api.reuse("RemoveAccount", api_actions.remove_account, sensitive=True)


@owner_api.action("ListAccounts")
def list_accounts(call: owner_api.OwnerCall) -> dict:
    """
    Como la de `/api/agent`, más lo que muestran las pantallas de correo de PaynaniWeb:
    `from_name`, el nombre con que escribe la cuenta (el del hilo), y `signed`, si tiene firma
    («Nuevo correo» lo dice debajo del mensaje).
    """
    out = api_actions.list_accounts(call)
    for account in out["accounts"]:
        account["from_name"] = mail.sender_name(account["id"], call.ctx.accounts_file, call.ctx.env_path())
        account["signed"] = mail.has_signature(account["id"], call.ctx.accounts_file, call.ctx.env_path())
    return out


@owner_api.action("GetMailThread")
def get_mail_thread(call: owner_api.OwnerCall) -> dict:
    """Como la de `/api/agent`, y un mensaje que no se pudo leer trae `error_detail`: el dato
    sin secretos que PaynaniWeb pone en «No se pudo conectar al servidor de correo (…)»."""
    return api_actions.get_mail_thread(call, error_detail=True)


@owner_api.action("SendOwnerMail", sensitive=True)
def send_owner_mail(call: owner_api.OwnerCall) -> dict:
    """
    «Nuevo correo» de PaynaniWeb (#590 cambio 2, #591 N1). Si alguien está fuera del roster
    de la cuenta, responde 409 `outside_roster` con la lista y no manda nada hasta que la app
    vuelva a llamar con `confirm_outside: true` (la app pidió antes su contraseña).
    """
    account = api_actions._mail_account(call)
    values = {k: call.text(k, limit=mail_compose.MAX_TEXT) for k in ("to", "cc", "bcc", "subject", "text")}
    values["text"] = values["text"].replace("\r\n", "\n")
    confirm = _bool(call, "confirm_outside")
    mailer = call.ctx.mailer
    try:
        to, cc, bcc = (mail_compose.split_addresses(values[k]) for k in ("to", "cc", "bcc"))
        mail_compose.check(to, cc, bcc, values["subject"], values["text"])
        outside = mailer.outside_roster(account["id"], list(dict.fromkeys(to + cc + bcc)))
        if outside and not confirm:
            raise ApiError(409, "outside_roster", "Some recipients are not on this account's roster; "
                           "call again with confirm_outside: true to send anyway.", outside=outside)
        user = call.ctx.user() or {}
        grant = mailer.authorize(account["id"], to, cc, bcc, by=f"owner:{call.client['client_id']}:{call.ip}",
                                 owner_email=str(user.get("email") or ""), allow_outside=bool(outside))
        try:
            res = mailer.send(grant, values["subject"].strip(), values["text"])
        except mail_compose.Refused:
            raise
        except Exception as exc:  # noqa: BLE001 -- pudo haber salido: no se invita a reenviar
            sys.stderr.write(f"paynani-web: SendOwnerMail terminó con {type(exc).__name__}\n")
            raise ApiError(502, "unknown_outcome", "The mail may or may not have been sent; check Sent "
                           "before trying again.") from None
    except mail_compose.Refused as exc:
        status = 503 if exc.code == "not_available" else 400
        raise ApiError(status, exc.code, str(exc.detail or exc.code), detail=str(exc.detail or "")) from None
    if not res.get("ok"):
        code = str(res.get("code") or "send_failed")
        raise ApiError(502 if code == "send_failed" else 400, code, str(res.get("detail") or code),
                       detail=str(res.get("detail") or ""))
    return {"account": account["id"], "sent": True, "message_id": res.get("message_id", ""),
            "outside_roster": res.get("outside_roster") or outside,
            "sent_copy": res.get("sent_copy", ""), "notice": res.get("notice", "")}


def _config_now(call: owner_api.OwnerCall) -> dict:
    import idle_listener
    try:
        return account_config.current(idle_listener.load_env(call.ctx.env_path()))
    except OSError:
        return account_config.current({})


@owner_api.action("GetMainAccountConfig")
def get_main_account_config(call: owner_api.OwnerCall) -> dict:
    """La configuración de la cuenta del agente, sin la contraseña, y su `rev` para guardar."""
    now = _config_now(call)
    return {"config": now, "rev": account_config.revision(now), "fields": list(account_config.SHOWN)}


@owner_api.action("SaveMainAccountConfig", sensitive=True)
def save_main_account_config(call: owner_api.OwnerCall) -> dict:
    """
    Como «Configuración» de la cuenta principal (#590 cambio 3): `rev` de GetMainAccountConfig
    (si cambió, 409 `stale`), los campos de `fields` y, si se cambia, `new_password`. El
    núcleo prueba, guarda y reinicia el listener; un correo al dueño dice qué cambió.
    """
    before = _config_now(call)
    if call.text("rev") != account_config.revision(before):
        raise ApiError(409, "stale", "The configuration changed since it was read; read it again.", field="rev")
    form = {key: call.text(key, str(before.get(key, "")), limit=320) for key in account_config.SHOWN}
    form["new_password"] = call.text("new_password", limit=1024)
    try:
        changes = account_config.changes(before, form)
    except account_config.Refused as exc:
        raise ApiError(400, exc.code, config_pages.error_text(exc.code, exc.detail), detail=str(exc.detail or "")) from None
    if not changes:
        return {"changed": [], "ready": ""}
    try:
        res = call.ctx.updater.update(changes, by=f"owner:{call.client['client_id']}:{call.ip}")
    except account_config.Refused as exc:
        raise ApiError(503 if exc.code == "not_available" else 400, exc.code,
                       config_pages.error_text(exc.code, exc.detail), detail=str(exc.detail or "")) from None
    except Exception as exc:  # noqa: BLE001 -- pudo haber escrito: no se invita a reintentar a ciegas
        sys.stderr.write(f"paynani-web: SaveMainAccountConfig terminó con {type(exc).__name__}\n")
        raise ApiError(502, "unknown_outcome", "The change may or may not have been saved; read the "
                       "configuration again.") from None
    code = str(res.get("code"))
    if code == "unchanged":
        return {"changed": [], "ready": ""}
    if not res.get("ok"):
        status = 400 if code in ("invalid", "probe_failed", "unknown_field") else 409 if code == "busy" else 502
        raise ApiError(status, code, str(res.get("detail") or code), detail=str(res.get("detail") or ""),
                       rollback=res.get("rollback", ""),
                       probe=res.get("probe"), field_errors=res.get("field_errors"))
    changed = list(res.get("changed") or list(changes))
    fields = ", ".join(config_pages.label(k) for k in changed)
    user = call.ctx.user()
    if user:
        call.ctx.notifier.owner(user, i18n.t("web.cfg.mail_subject"),
                                i18n.t("web.cfg.mail_body", ip=call.ip, fields=fields) + f" ({call.origin()})")
    return {"changed": changed, "ready": res.get("ready") or "", "recovered": bool(res.get("recovered")),
            "probe": res.get("probe")}


# ---- Roster y reglas --------------------------------------------------------------------

owner_api.reuse("ListRoster", api_actions.list_roster)
owner_api.reuse("SaveRosterContact", api_actions.save_roster_contact)
owner_api.reuse("DeleteRosterContact", api_actions.delete_roster_contact)
owner_api.reuse("GetRules", api_actions.get_rules)
owner_api.reuse("SaveRules", api_actions.save_rules)
owner_api.reuse("GetDefaultRules", api_actions.get_default_rules)
owner_api.reuse("SaveDefaultRules", api_actions.save_default_rules)
owner_api.reuse("GetCatchAll", api_actions.get_catch_all)


@owner_api.action("SaveCatchAll")
def save_catch_all(call: owner_api.OwnerCall) -> dict:
    """Los tres canales, sin el permiso por canal del token de agente: el dueño puede todo."""
    return api_actions.catch_all_save(call, api_actions._catch_all_channel(call))


@owner_api.action("PreviewRules")
def preview_rules(call: owner_api.OwnerCall) -> dict:
    """
    Cómo quedan las reglas de un contacto con las generales, sin guardar (la vista previa de
    PaynaniWeb). Con `general: true`, las generales solas.
    """
    text = call.text("text", limit=20000).replace("\r\n", "\n")
    if _bool(call, "general"):
        from .. import rules as rules_mod
        from ..roster_edit import EditError
        try:
            rules_mod.parse(text)
        except EditError as exc:
            err = exc.as_error()
            raise ApiError(400, str(err.get("code") or "invalid"), str(err.get("detail") or "invalid"),
                           **{k: err[k] for k in ("field", "reason") if k in err}) from None
        return {"effective": rules_mod.effective(text, None)}
    data = call.roster("rules.preview", account=api_actions._account_value(call.text("account").strip()),
                       row=api_actions._rules_row(call), text=text, roster_etag=call.text("roster_etag"))
    return {"effective": data.get("effective", "")}


# ---- Dashboard y Agente -------------------------------------------------------------------

@owner_api.action("GetDashboard")
def get_dashboard(call: owner_api.OwnerCall) -> dict:
    """Lo que arma `dashboard.build` para la página de inicio (con la caché de 60 s de la web)."""
    model = call.ctx.dashboard_model(call.text("account", limit=64).strip())
    return {"dashboard": _plain(model), "numbers": _plain(dashboard.numbers(model))}


@owner_api.action("GetAgent")
def get_agent(call: owner_api.OwnerCall) -> dict:
    """La página del agente (#644): estado, harness, actividad y canales."""
    return {"agent": _plain(call.ctx.agent_model())}


# ---- API Tokens -----------------------------------------------------------------------------

def _tokens_path(call: owner_api.OwnerCall):
    return api_tokens.path_for(call.ctx.user_path())


def _token_view(record: dict) -> dict:
    """Un token sin su hash: el `id` es el que usa la web en sus URLs (el SHA-256)."""
    out = {k: v for k, v in record.items() if k != "sha256"}
    out["id"] = record["sha256"]
    out["status"] = token_pages.status(record)
    return out


def _token_id(call: owner_api.OwnerCall) -> str:
    digest = call.required("id", limit=64)
    if not TOKEN_ID.fullmatch(digest):
        raise ApiError(400, "invalid_parameter", "id must be a token id from ListApiTokens.", field="id")
    return digest


@owner_api.action("ListApiTokens")
def list_api_tokens(call: owner_api.OwnerCall) -> dict:
    try:
        records = api_tokens.list_records(path=_tokens_path(call))
    except (OSError, ValueError):
        raise ApiError(500, "internal_error", "The API tokens could not be read.") from None
    return {"tokens": [_token_view(r) for r in records]}


@owner_api.action("GetApiToken")
def get_api_token(call: owner_api.OwnerCall) -> dict:
    digest = _token_id(call)
    record = api_tokens.get_record(digest, path=_tokens_path(call))
    if record is None:
        raise ApiError(404, "not_found", "No such API token.", field="id")
    view = _token_view(record)
    view["sms_today"] = token_pages.usage_today(call.ctx.state_dir(), record.get("prefix", ""))
    return {"token": view}


@owner_api.action("CreateApiToken", sensitive=True)
def create_api_token(call: owner_api.OwnerCall) -> dict:
    """
    Como «Crear token» de PaynaniWeb: `name`, `expiry` (5m, 1h, 1d, 7d, never o custom con
    `custom`), `permissions` (lista), `sms_per_hour`, `sms_per_day` y `agent_replies`.
    El token sólo sale en esta respuesta.
    """
    permissions = call.params.get("permissions", [])
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        raise ApiError(400, "invalid_parameter", "permissions must be a list of permission names.",
                       field="permissions")
    values = {"name": call.text("name", limit=200), "expiry": call.text("expiry"), "custom": call.text("custom"),
              "permissions": permissions, "sms_per_hour": call.text("sms_per_hour", "60"),
              "sms_per_day": call.text("sms_per_day", "500"), "agent_replies": _bool(call, "agent_replies")}
    try:
        secret, record = token_pages.create_from_values(values, path=_tokens_path(call))
    except ValueError:
        raise ApiError(400, "invalid_token_values", "Check the name, the permissions "
                       f"({', '.join(token_pages.PERMISSIONS)}), the limits (1 to 100000) and the expiry.") from None
    except OSError:
        raise ApiError(500, "internal_error", "The token could not be saved.") from None
    return {"token": _token_view(record), "secret": secret}


def _token_update(call: owner_api.OwnerCall, **change) -> dict:
    digest = _token_id(call)
    try:
        record = api_tokens.update(digest, path=_tokens_path(call), **change)
    except (OSError, ValueError):
        raise ApiError(500, "internal_error", "The token could not be saved.") from None
    if record is None:   # no existe, o ya estaba revocado: igual que «missing» en la web
        raise ApiError(404, "not_found", "No such active API token.", field="id")
    return record


@owner_api.action("RevokeApiToken", sensitive=True)
def revoke_api_token(call: owner_api.OwnerCall) -> dict:
    return {"token": _token_view(_token_update(call, revoke=True))}


@owner_api.action("SetApiTokenAgentReplies")
def set_api_token_agent_replies(call: owner_api.OwnerCall) -> dict:
    """Si el agente contesta las respuestas a los SMS que mandó ese token (#651)."""
    return {"token": _token_view(_token_update(call, agent_replies=_bool(call, "agent_replies")))}
