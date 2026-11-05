"""
La API del dueño, A4 (paynani#722, FR-A7 de iaaorgmx/PaynaniWebMT#2): Mensajes de texto,
WhatsApp, Telegram y Webchat.

Cada acción llama a lo mismo que la página de PaynaniWeb (FR-A6):

- SMS: `sms/owner.py` (#724) y las lecturas de `/api/agent`, que ya son las de la web.
- WhatsApp y Telegram: el `Source` del canal con `by: web`, como PaynaniWeb, y no `by: api`
  como `/api/agent`: el dueño ve sus conversaciones completas, igual que en la web (el
  servicio aplica sus reglas a cada `by`). Enviar es `channel_send` (#725), reaccionar
  `channel_react` (#726), las fotos y documentos `channel_media` (#728) y vincular
  `channel_link`.
- Webchat: el almacén `webchat/store.py`, con las mismas reglas de cita y archivos.

La contraseña de las acciones delicadas la pide PaynaniWebMT (FR-A10); aquí van con
`sensitive=True`, y los correos al dueño dicen `call.origin()`. El estado que en la web va
por sesión (la vinculación de WhatsApp, el `check` del token de Telegram) aquí va por
cliente: `owner:<client_id>`.
"""
from __future__ import annotations

import secrets

from .. import i18n
from . import api_actions, channel_link, channel_media, channel_react, channel_send, owner_api
from . import telegram_source, webchat_pages, webchat_source, whatsapp_source
from .api_actions import ApiError
from .owner_api import FileResult, OwnerCall

PAGE = api_actions.PAGE


def _key(call: OwnerCall) -> str:
    """La llave del estado en curso de este cliente (en la web es el `sid`)."""
    return "owner:" + call.client["client_id"]


def _flag(call: OwnerCall, name: str) -> bool:
    value = call.params.get(name, False)
    return value is True or value in ("1", "true", "on")


def _media_result(media: channel_media.Media, fallback: str) -> FileResult:
    """Una foto no trae nombre: se le pone uno con la extensión de su tipo, para que el
    cliente sepa qué es (FileResult sale como octet-stream, FR-A9)."""
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(media.mime)
    name = media.name or (f"{fallback}.{ext}" if ext else fallback)
    return FileResult(name, media.data)


def _media_error(exc: channel_media.MediaError, channel: str) -> ApiError:
    if exc.code == "unavailable":
        return ApiError(503, f"{channel}_unavailable", f"The {channel} service is not answering; try again.")
    return ApiError(404, "not_found", "No file with that reference.", field="ref")


# ==== Mensajes de texto ===================================================================

def _sms_store(call: OwnerCall):
    from ..sms import store as sms_store
    return sms_store.Store(call.ctx.state_dir())


def _sms_phone(call: OwnerCall, store=None) -> dict:
    """Lo que la pantalla de SMS necesita del teléfono (PRD #489 FR-6, FR-7, FR-14)."""
    from ..sms import config as sms_config
    from ..sms import owner as sms_owner
    store = store or _sms_store(call)
    state = sms_owner.phone_state(store)
    return {"state": state, "offline_ttl_min": sms_owner.offline_ttl(call.ctx.state_dir(), state),
            "agent_pause_min": sms_config.web_agent_pause_min(), "per_hour": sms_config.web_sms_per_hour()}


def _sms_number(call: OwnerCall, store) -> str:
    from ..sms import outgoing
    from ..sms import owner as sms_owner
    raw = call.required("number", 40).strip()
    try:
        return sms_owner.normalize(store, raw)
    except outgoing.Refused:
        raise ApiError(400, "invalid_number", "number is not a valid phone number.", field="number") from None


@owner_api.action("ListSmsConversations")
def list_sms_conversations(call: OwnerCall) -> dict:
    return {**api_actions.list_sms_conversations(call), "phone": _sms_phone(call)}


@owner_api.action("GetSmsThread")
def get_sms_thread(call: OwnerCall) -> dict:
    data = api_actions.get_sms_thread(call)
    # FR-3: fuera del roster, PaynaniWebMT pide su contraseña antes de mandar (FR-A10).
    return {**data, "in_roster": data["number"] in call.ctx.phone_names(), "phone": _sms_phone(call)}


@owner_api.action("SendOwnerSms")
def send_owner_sms(call: OwnerCall) -> dict:
    """La orden del dueño (PRD #489 FR-1 a FR-4b), con `pause` («Pausar al agente»)."""
    from ..sms import outgoing
    from ..sms import owner as sms_owner
    store = _sms_store(call)
    number = _sms_number(call, store)
    text = call.text("text", limit=outgoing.MAX_TEXT + 1)
    try:
        order = sms_owner.send(store, number, text, pause=_flag(call, "pause"),
                               source=f"owner:{call.client['client_id']}:{call.ip}")
    except sms_owner.NotReady as exc:
        raise ApiError(409, "phone_not_ready", "The paired phone does not take owner messages.",
                       state=exc.state) from None
    except outgoing.Refused as exc:
        if exc.code == "rate_limited":
            raise ApiError(429, "rate_limited", "Too many texts this hour.", retry_at=exc.retry_at or "") from None
        raise ApiError(400, exc.code, str(exc)) from None
    return {"order_id": order["id"], "number": number, "status": "queued",
            "agent_pause_min": order.get("agent_pause_min", 0), "in_roster": number in call.ctx.phone_names()}


@owner_api.action("GetSmsStatuses")
def get_sms_statuses(call: OwnerCall) -> dict:
    """PRD #489 FR-5: el estado de cada mensaje de la web en la conversación."""
    from ..sms import owner as sms_owner
    return sms_owner.statuses(_sms_store(call), call.ctx.state_dir(), call.required("number", 40).strip())


@owner_api.action("ListOptOuts")
def list_opt_outs(call: OwnerCall) -> dict:
    from ..sms import api_replies
    return {"opt_outs": api_replies.listing(_sms_store(call))}


def _opt_out(call: OwnerCall, out: bool) -> dict:
    from ..sms import owner as sms_owner
    store = _sms_store(call)
    number = _sms_number(call, store)
    try:
        changed = sms_owner.set_opt_out(store, number, out, by=f"owner:{call.client['client_id']}")
    except (OSError, ValueError):
        raise ApiError(500, "internal_error", "The opt-out list could not be read.") from None
    if changed:
        try:
            call.ctx.api_security.record("opt_out" if out else "opt_in", call.request_id,
                                         call.client.get("prefix", ""), call.ip)
        except (OSError, ValueError):
            pass
    return {"number": number, "opted_out": out, "changed": changed}


@owner_api.action("SaveOptOut")
def save_opt_out(call: OwnerCall) -> dict:
    return _opt_out(call, True)


@owner_api.action("DeleteOptOut")
def delete_opt_out(call: OwnerCall) -> dict:
    return _opt_out(call, False)


# ==== WhatsApp y Telegram: lo común ===========================================================

CHANNELS = {
    "whatsapp": {"configured": "whatsapp_configured", "source": "whatsapp", "failed": whatsapp_source.Failed,
                 "send_codes": {"rate_limited": 429, "unavailable": 503, "not_connected": 409, "timeout": 504}},
    "telegram": {"configured": "telegram_configured", "source": "telegram", "failed": telegram_source.Failed,
                 "send_codes": {"rate_limited": 429, "unavailable": 503}},
}


def _source(call: OwnerCall, channel: str):
    spec = CHANNELS[channel]
    if not getattr(call.ctx, spec["configured"])():
        raise ApiError(503, f"{channel}_unavailable", f"{channel.title()} is not set up on this install.")
    return getattr(call.ctx, spec["source"])()


def _ask(call: OwnerCall, channel: str, kind: str, **fields) -> dict:
    """Un pedido al servicio con `by: web` (el que pone el `Source`), como PaynaniWeb."""
    try:
        return _source(call, channel).request(kind, **fields)
    except CHANNELS[channel]["failed"] as exc:
        if exc.code == "not_found":
            raise ApiError(404, "not_found", "No conversation with that reference.") from None
        if exc.code == "invalid":
            field = str(exc.fields.get("field") or "")
            raise ApiError(400, "invalid_parameter", f"{field or 'A parameter'} is not valid.", field=field) from None
        raise ApiError(503, f"{channel}_unavailable", f"The {channel} service is not answering; try again.") from None


def _status(call: OwnerCall, channel: str) -> dict:
    """El estado del canal; sin configurar, `configured: false` (la web muestra su página)."""
    spec = CHANNELS[channel]
    if not getattr(call.ctx, spec["configured"])():
        return {"configured": False}
    return {"configured": True, **getattr(call.ctx, spec["source"])().status()}


def _send(call: OwnerCall, channel: str, target: dict) -> dict:
    source = _source(call, channel)
    spec = channel_send.whatsapp() if channel == "whatsapp" else channel_send.telegram()
    root = call.ctx.state_dir() / channel
    files = [{"name": f["name"], "data": f["data"]} for f in call.files]
    try:
        data = channel_send.send(spec, source, root, target, call.text("text", limit=spec.max_text + 1), files,
                                 call.text("reply_to", limit=130).strip())
    except channel_send.SendError as exc:
        extra = {"sent": exc.sent, **({"field": exc.fields["field"]} if "field" in exc.fields else {})}
        if exc.unknown:
            # Con archivos, un corte por tiempo no dice si salieron: revisar el hilo antes de repetir.
            raise ApiError(504, "send_unknown", "The send timed out; check the thread before sending again.",
                           **extra) from None
        status = CHANNELS[channel]["send_codes"].get(exc.code, 400)
        raise ApiError(status, exc.code, f"The message was not sent ({exc.code}).", **extra) from None
    return {"sent": True, **{k: v for k, v in data.items() if k in ("id", "ref", "message_id", "at")}}


def _react(call: OwnerCall, channel: str, source) -> dict:
    try:
        return {"reactions": channel_react.react(channel, source, call.required("ref", 130).strip(),
                                                 call.text("emoji", limit=16).strip())}
    except channel_react.ReactError as exc:
        if exc.kind == "invalid":
            raise ApiError(400, "invalid_parameter", "emoji is not one of the allowed reactions.",
                           field="emoji") from None
        if exc.kind == "not_allowed":
            raise ApiError(404, "not_found", "That message cannot take reactions.", field="ref") from None
        if exc.kind == "service" and exc.code == "not_found":
            # #707: un mensaje sin id en el canal no se puede reaccionar.
            raise ApiError(404, "message_too_old", "That message has no id in the channel.", field="ref") from None
        raise ApiError(429 if exc.code == "rate_limited" else 400, exc.code, "The reaction was not set.") from None


def _media(call: OwnerCall, channel: str) -> FileResult:
    source = _source(call, channel)
    ref = call.required("ref", 130).strip()
    kind = call.text("kind", limit=10).strip() or "image"
    try:
        if kind == "image":
            media = channel_media.image(channel, source, ref, call.text("index", limit=2).strip())
        elif kind == "file":
            media = channel_media.document(channel, source, ref)
        else:
            raise ApiError(400, "invalid_parameter", "kind must be image or file.", field="kind")
    except channel_media.MediaError as exc:
        raise _media_error(exc, channel) from None
    return _media_result(media, "foto")


# ==== WhatsApp ============================================================================

@owner_api.action("GetWhatsAppStatus")
def get_whatsapp_status(call: OwnerCall) -> dict:
    status = _status(call, "whatsapp")
    if status["configured"]:
        cur, ended = channel_link.wa_current(call.ctx, _key(call), call.ctx.whatsapp())
        status["link"] = cur
        status["link_ended"] = ended
    return status


@owner_api.action("ListWhatsAppConversations")
def list_whatsapp_conversations(call: OwnerCall) -> dict:
    data = _ask(call, "whatsapp", "whatsapp.threads", **api_actions._wa_page(call))
    return {"threads": data.get("threads") or [], "next_before": data.get("next_before")}


@owner_api.action("GetWhatsAppThread")
def get_whatsapp_thread(call: OwnerCall) -> dict:
    number = call.required("number", 40).strip()
    return _ask(call, "whatsapp", "whatsapp.thread", number=number, **api_actions._wa_page(call))


@owner_api.action("SendWhatsApp")
def send_whatsapp(call: OwnerCall) -> dict:
    return _send(call, "whatsapp", {"number": call.required("number", 40).strip()})


@owner_api.action("ReactWhatsApp")
def react_whatsapp(call: OwnerCall) -> dict:
    return _react(call, "whatsapp", _source(call, "whatsapp"))


@owner_api.action("GetWhatsAppMedia")
def get_whatsapp_media(call: OwnerCall) -> FileResult:
    return _media(call, "whatsapp")


def _link_error(exc: channel_link.LinkError) -> ApiError:
    status = {"already_linked": 409, "unavailable": 503, "invalid_number": 400, "invalid": 400}.get(exc.code, 400)
    extra = {"field": exc.fields["field"]} if "field" in exc.fields else {}
    return ApiError(status, exc.code, f"WhatsApp link failed ({exc.code}).", **extra)


@owner_api.action("LinkWhatsApp", sensitive=True)
def link_whatsapp(call: OwnerCall) -> dict:
    """`mode` `qr` (el QR sale en GetWhatsAppLinkCode) o `code` con `number` (el código sólo
    viaja en esta respuesta, §11)."""
    source = _source(call, "whatsapp")
    try:
        data = channel_link.wa_link(call.ctx, _key(call), source, call.text("mode", limit=8).strip() or "qr",
                                    call.text("number", limit=40))
    except channel_link.LinkError as exc:
        raise _link_error(exc) from None
    return {k: v for k, v in data.items() if k in ("link_id", "code", "expires_at", "state", "mode")}


@owner_api.action("GetWhatsAppLinkCode")
def get_whatsapp_link_code(call: OwnerCall) -> dict:
    """La vinculación en curso de este cliente (el QR mientras dura), o `link: null` con la
    razón con que terminó."""
    cur, ended = channel_link.wa_current(call.ctx, _key(call), _source(call, "whatsapp"))
    return {"link": cur, "ended": ended}


@owner_api.action("CancelWhatsAppLink", sensitive=True)
def cancel_whatsapp_link(call: OwnerCall) -> dict:
    try:
        channel_link.wa_cancel(call.ctx, _key(call), _source(call, "whatsapp"))
    except channel_link.LinkError as exc:
        raise ApiError(503, exc.code, "The link could not be canceled.") from None
    return {"canceled": True}


@owner_api.action("UnlinkWhatsApp", sensitive=True)
def unlink_whatsapp(call: OwnerCall) -> dict:
    if not _flag(call, "confirm"):
        raise ApiError(400, "confirm_required", "Send confirm: true to unlink WhatsApp.", field="confirm")
    try:
        data = channel_link.wa_unlink(call.ctx, _key(call), _source(call, "whatsapp"))
    except channel_link.LinkError as exc:
        raise ApiError(503, exc.code, "WhatsApp could not be unlinked.") from None
    return {"unlinked": True, "remote": bool(data.get("remote"))}


# ==== Telegram ============================================================================

@owner_api.action("GetTelegramStatus")
def get_telegram_status(call: OwnerCall) -> dict:
    status = _status(call, "telegram")
    if status["configured"]:
        status["check"] = channel_link.tg_pending(call.ctx, _key(call))
    else:
        # La configuración inicial muestra el Telegram del dueño si ya está en su fila (#682).
        member, _ = channel_link.tg_owner_row(_rq(call), call.ctx.user())
        status["owner_telegram"] = (member or {}).get("telegram", "")
    return status


@owner_api.action("ListTelegramConversations")
def list_telegram_conversations(call: OwnerCall) -> dict:
    data = _ask(call, "telegram", "telegram.threads", **api_actions._wa_page(call))
    return {"threads": data.get("threads") or [], "next_before": data.get("next_before")}


@owner_api.action("GetTelegramThread")
def get_telegram_thread(call: OwnerCall) -> dict:
    thread = call.required("thread", 80).strip()
    if not api_actions._TG_THREAD.match(thread):
        raise ApiError(400, "invalid_parameter", "thread must be a thread from ListTelegramConversations.",
                       field="thread")
    return _ask(call, "telegram", "telegram.thread", thread=thread, **api_actions._wa_page(call))


@owner_api.action("SendTelegram")
def send_telegram(call: OwnerCall) -> dict:
    thread = call.required("thread", 80).strip()
    if not api_actions._TG_THREAD.match(thread):
        raise ApiError(404, "not_found", "No Telegram conversation with that thread.", field="thread")
    return _send(call, "telegram", {"thread": thread})


@owner_api.action("ReactTelegram")
def react_telegram(call: OwnerCall) -> dict:
    return _react(call, "telegram", _source(call, "telegram"))


@owner_api.action("GetTelegramMedia")
def get_telegram_media(call: OwnerCall) -> FileResult:
    return _media(call, "telegram")


def _rq(call: OwnerCall):
    """Un pedido de §11 al roster con la respuesta cruda, como `_rq` de la web."""
    def rq(kind: str, **fields) -> dict:
        msg = {"type": kind, "id": "q_" + secrets.token_hex(16), **fields}
        return call.ctx.roster_service().handle(msg, f"owner:{call.client['client_id']}:{call.ip}")
    return rq


def _tg_error(exc: channel_link.LinkError) -> ApiError:
    from ..telegram import setup as tg_setup
    status = {"check_expired": 409, "rollback": 409, "unavailable": 503,
              tg_setup.UNREACHABLE: 502, tg_setup.ALREADY: 409}.get(exc.code, 400)
    extra = {k: exc.fields[k] for k in ("field", "reason", "name") if k in exc.fields}
    return ApiError(status, exc.code, f"Telegram: {exc.code}.", **extra)


@owner_api.action("SetupTelegram", sensitive=True)
def setup_telegram(call: OwnerCall) -> dict:
    """La configuración inicial (#635, #682), como `paynani telegram setup`."""
    if call.ctx.telegram_configured():
        raise ApiError(409, "already_configured", "Telegram is already set up; use CheckTelegramToken.")
    owner_tg = call.text("owner_telegram", limit=64).strip()
    token = call.text("token", limit=200).strip()
    try:
        done = channel_link.tg_setup(call.ctx, _rq(call), call.ctx.user(), token=token,
                                     username=call.text("bot_username", limit=40).strip(),
                                     owner_telegram=owner_tg, dedicated=_flag(call, "confirm_dedicated"))
    except channel_link.LinkError as exc:
        raise _tg_error(exc) from None
    finally:
        token = ""
        call.params.pop("token", None)
    bot = done["bot_username"]
    body = i18n.t("web.tg.setup.mail_body", ip=call.origin(), bot=bot)
    body += "\n\n" + i18n.t("web.tg.setup.mail_owner" if done["saved"] else "web.tg.setup.mail_owner_failed",
                            bot=bot, owner=owner_tg)
    call.ctx.notifier.owner(call.ctx.user(), i18n.t("web.tg.setup.mail_subject"), body)
    return {"bot_username": bot, "owner_saved": done["saved"], "started": done["started"]}


@owner_api.action("CheckTelegramToken", sensitive=True)
def check_telegram_token(call: OwnerCall) -> dict:
    """FR-10: revisa un token nuevo. El `check` se queda en paynani, nunca en el cliente."""
    token = call.text("token", limit=200).strip()
    try:
        check = channel_link.tg_check(call.ctx, _key(call), _source(call, "telegram"), token)
    except channel_link.LinkError as exc:
        raise _tg_error(exc) from None
    finally:
        token = ""
        call.params.pop("token", None)
    return {k: check[k] for k in ("bot_username", "same_token", "webhook")}


@owner_api.action("ApplyTelegramToken", sensitive=True)
def apply_telegram_token(call: OwnerCall) -> dict:
    try:
        data = channel_link.tg_apply(call.ctx, _key(call), _source(call, "telegram"),
                                     confirm_dedicated=_flag(call, "confirm_dedicated"),
                                     confirm_webhook=_flag(call, "confirm_webhook"))
    except channel_link.LinkError as exc:
        raise _tg_error(exc) from None
    call.ctx.notifier.owner(call.ctx.user(), i18n.t("web.tg.mail_subject"),
                            i18n.t("web.tg.mail_body", ip=call.origin(), bot=data.get("bot_username") or "?"))
    return {"result": data["result"], "bot_username": data.get("bot_username") or ""}


@owner_api.action("CancelTelegramToken")
def cancel_telegram_token(call: OwnerCall) -> dict:
    channel_link.tg_cancel(call.ctx, _key(call))
    return {"canceled": True}


# ==== Webchat =============================================================================
WEBCHAT_FIELDS = ("id", "dir", "by", "at", "text", "reply_to", "reactions")


def _webchat(call: OwnerCall):
    store = call.ctx.webchat
    if store is None:
        raise ApiError(503, "webchat_unavailable", "Webchat is not available on this install.")
    return store


def _webchat_message(m: dict) -> dict:
    out = {k: m[k] for k in WEBCHAT_FIELDS if k in m}
    out["files"] = [{k: f[k] for k in ("n", "name", "kind", "size", "ref") if k in f} for f in m.get("files", [])]
    return out


@owner_api.action("GetWebchatThread")
def get_webchat_thread(call: OwnerCall) -> dict:
    """Los mensajes; con `since` (el último `w_…` que tiene el cliente), sólo los nuevos, y
    con `before`, la página anterior. También `typing`, el borrador y si el almacén cita y
    reacciona."""
    from .app import WC_ID
    store = _webchat(call)
    since = call.text("since", limit=40).strip() or None
    before = call.text("before", limit=40).strip() or None
    for name, value in (("since", since), ("before", before)):
        if value is not None and not WC_ID.match(value):
            raise ApiError(400, "invalid_parameter", f"{name} must be a message id (w_…).", field=name)
    if since and before:
        raise ApiError(400, "invalid_parameter", "Use since or before, not both.", field="before")
    limit = call.number("limit", webchat_pages.PAGE)
    if not 1 <= limit <= 100:
        raise ApiError(400, "invalid_parameter", "limit must be from 1 to 100.", field="limit")
    if since:
        rows = store.messages(after=since, limit=limit)
    elif before:
        rows = store.messages(before=before, limit=limit + 1)
    else:
        rows = store.messages(limit=limit + 1)
    more = not since and len(rows) > limit
    rows = rows[-limit:] if not since else rows
    draft = store.draft() if hasattr(store, "draft") else None
    return {"messages": [_webchat_message(m) for m in rows],
            "next_before": rows[0]["id"] if more and rows else None,
            "typing": bool(store.is_typing()), "draft": draft,
            "replies": webchat_pages.replies(store), "reactions": webchat_pages.reacts(store)}


@owner_api.action("SendWebchat")
def send_webchat(call: OwnerCall) -> dict:
    """El mensaje del dueño, con cita (`reply_to`) y archivos (#648), como PaynaniWeb."""
    from .app import WC_ID
    store = _webchat(call)
    text = call.text("text", limit=webchat_source.MAX_TEXT + 1)
    files = [(f["name"][:200], f["data"]) for f in call.files[:webchat_pages.MAX_FILES]]
    user = call.ctx.user() or {}
    owner = {"name": str(user.get("name") or ""), "email": str(user.get("email") or "")}
    reply_to = call.text("reply_to", limit=40).strip()
    extra = {"reply_to": reply_to} if webchat_pages.replies(store) and WC_ID.match(reply_to) else {}
    try:
        message = store.append("owner", text.strip(), files, owner=owner, **extra)
    except Exception as exc:  # noqa: BLE001 -- el Rejected del almacén, o un fallo al guardar
        code = webchat_source.rejected_code(exc)
        if code:
            raise ApiError(400, {"too_long": "too_big"}.get(code, code), "The message was not saved.") from None
        raise ApiError(500, "internal_error", "The message could not be saved.") from None
    return {"message": _webchat_message(message or {})}


@owner_api.action("ReactWebchat")
def react_webchat(call: OwnerCall) -> dict:
    return _react(call, "webchat", call.ctx.webchat)


@owner_api.action("GetWebchatFile")
def get_webchat_file(call: OwnerCall) -> FileResult:
    try:
        media = channel_media.webchat_file(call.ctx.webchat, call.required("ref", 40).strip())
    except channel_media.MediaError as exc:
        raise _media_error(exc, "webchat") from None
    return _media_result(media, "archivo")


@owner_api.action("GetAgentTyping")
def get_agent_typing(call: OwnerCall) -> dict:
    """«escribiendo…» y el borrador del agente (WEBCHAT.md §4), sin traer los mensajes."""
    store = _webchat(call)
    return {"typing": bool(store.is_typing()), "draft": store.draft() if hasattr(store, "draft") else None}
