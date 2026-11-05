"""
Vincular WhatsApp y el bot de Telegram: lo que hacían los handlers de PaynaniWeb, sin
HTML (PaynaniWebMT PRD #2, FR-A6 y FR-A10; paynani#722).

PaynaniWeb y la API del dueño llaman a estas funciones. El estado en curso (la vinculación
de WhatsApp, el `check` de un token de Telegram) vive en la memoria del servidor bajo una
`key`: el `sid` de la sesión web en PaynaniWeb, `owner:<client_id>` en la API del dueño.
Quien llama se queda con lo suyo: la contraseña de PaynaniWeb (la API no la pide, FR-A10),
los textos, los códigos HTTP y el correo al dueño.

Todo rechazo es `LinkError(code, **fields)`:

- WhatsApp: `invalid_number`, `invalid` (`field`), o el código del servicio
  (`already_linked`, `unavailable`, …).
- Token de Telegram: `token_format`, `token_rejected`, `check_expired`, `missing_field`
  (`field`: `confirm_dedicated` o `confirm_webhook`), `rollback` (`reason`), o el código
  del servicio.
- Configuración inicial de Telegram: `owner_invalid`, `owner_row`, `owner_taken` (`name`),
  o el `code` de `telegram.setup.SetupError`.
"""
from __future__ import annotations

import re

from . import telegram_source, whatsapp_source

WA_NUMBER = re.compile(r"\+[1-9]\d{6,14}")


class LinkError(Exception):
    def __init__(self, code: str, **fields):
        super().__init__(code)
        self.code = code
        self.fields = fields


# ---- WhatsApp (PRD #550 FR-7, FR-24; WA-5 #557) -------------------------------------------

def wa_link(ctx, key: str, source, mode: str, number: str = "") -> dict:
    """Empieza a vincular: `qr`, o `code` con el número en E.164. Guarda el `link_id` bajo
    `key`. Devuelve lo del servicio; con `code`, el código sólo viaja aquí (§11)."""
    fields = {"mode": mode}
    if mode == "code":
        clean = re.sub(r"[\s().-]", "", number)
        if not WA_NUMBER.fullmatch(clean):
            raise LinkError("invalid_number")
        fields["number"] = clean
    elif mode != "qr":
        raise LinkError("invalid", field="mode")
    try:
        data = source.request("whatsapp.link", **fields)
    except whatsapp_source.Failed as exc:
        raise LinkError(exc.code, **exc.fields) from None
    ctx.wa_link_set(key, str(data.get("link_id", "")), mode)
    return data


def wa_current(ctx, key: str, source) -> tuple[dict | None, str]:
    """(la vinculación en curso de `key` por `link_current`, con su `mode`; la razón con que
    terminó). Si el servicio no contesta, `state: retry`. Al terminar, el `link_id` se
    olvida y la razón se devuelve una vez."""
    link = ctx.wa_link(key)
    if link is None:
        return None, ""
    try:
        cur = source.request("whatsapp.link_current", link_id=link["link_id"])
    except whatsapp_source.Failed as exc:
        if exc.code != "not_found":
            return {"state": "retry", "mode": link["mode"]}, ""
        cur = {"state": "ended", "reason": "gone"}
    if cur.get("state") == "ended":
        reason = str(cur.get("reason") or "gone")
        ctx.wa_link_drop(key, reason)
        return None, reason
    return dict(cur, mode=link["mode"]), ""


def wa_cancel(ctx, key: str, source) -> None:
    try:
        source.request("whatsapp.link_cancel")
    except whatsapp_source.Failed as exc:
        raise LinkError(exc.code, **exc.fields) from None
    ctx.wa_link_drop(key)


def wa_unlink(ctx, key: str, source) -> dict:
    """Desvincula. `remote` dice si WhatsApp también lo supo."""
    try:
        data = source.request("whatsapp.unlink")
    except whatsapp_source.Failed as exc:
        raise LinkError(exc.code, **exc.fields) from None
    ctx.wa_link_drop(key)
    return data


# ---- El token de Telegram (FR-10) -----------------------------------------------------------

def tg_check(ctx, key: str, source, token: str) -> dict:
    """Revisa un token nuevo con el servicio y guarda el `check` bajo `key` (vence en
    `CHECK_TTL_S`). Devuelve `{check, bot_username, same_token, webhook}`. El token no se
    guarda en ningún lado."""
    if not telegram_source.TOKEN_RE.match(token):
        raise LinkError("token_format")
    try:
        data = source.request("telegram.token_check", token=token)
    except telegram_source.Failed as exc:
        raise LinkError("token_rejected" if exc.code == "invalid" else exc.code, **exc.fields) from None
    check = {"check": str(data.get("check") or ""), "bot_username": str(data.get("bot_username") or ""),
             "same_token": bool(data.get("same_token")), "webhook": bool(data.get("webhook"))}
    ctx.tg_check_set(key, check)
    return check


def tg_pending(ctx, key: str) -> dict | None:
    """El `check` vigente de `key`, o None."""
    return ctx.tg_check(key)


def tg_apply(ctx, key: str, source, *, confirm_dedicated: bool, confirm_webhook: bool) -> dict:
    """Aplica el `check` de `key` con las confirmaciones de FR-10. El `check` sale de la
    memoria del servidor, nunca de quien llama. Devuelve lo del servicio (`result`
    `applied` o `unchanged`, `bot_username`)."""
    pending = ctx.tg_check(key)
    if pending is None:
        raise LinkError("check_expired")
    if not confirm_dedicated:
        raise LinkError("missing_field", field="confirm_dedicated", check=pending)
    if pending["webhook"] and not confirm_webhook:
        raise LinkError("missing_field", field="confirm_webhook", check=pending)
    ctx.tg_check(key, pop=True)
    try:
        data = source.request("telegram.token_apply", check=pending["check"], confirm_dedicated=True,
                              confirm_delete_webhook=bool(pending["webhook"]))
    except telegram_source.Failed as exc:
        raise LinkError("check_expired" if exc.code == "not_found" else exc.code, **exc.fields) from None
    if str(data.get("result") or "") not in ("applied", "unchanged"):
        raise LinkError("rollback", reason=str(data.get("reason") or "?"))
    return data


def tg_cancel(ctx, key: str) -> None:
    ctx.tg_check(key, pop=True)


# ---- La configuración inicial de Telegram (#635, #682) --------------------------------------
# `rq(kind, **fields)` es un pedido de §11 al servicio del roster que devuelve la respuesta
# cruda (`{"type": "result", "data": …}` o un error), como `_rq` de la web.

def tg_owner_row(rq, user: dict | None) -> tuple[dict | None, str]:
    """(la fila del dueño en el roster principal, su `etag`). La del correo de la cuenta de
    la web; si no está, la del dueño (la primera Human). None si no hay."""
    import roster as roster_mod
    data = rq("roster.list", account=None).get("data") or {}
    members = data.get("members") or []
    mine = roster_mod.normalise(str((user or {}).get("email") or ""))
    member = (next((m for m in members if mine and roster_mod.normalise(m.get("email", "")) == mine), None)
              or next((m for m in members if m.get("owner")), None))
    return member, str(data.get("etag") or "")


def tg_owner_problem(rq, value: str, member: dict | None) -> LinkError | None:
    """Por qué no se puede guardar `value` en la fila del dueño (#682), o None. Se revisa
    antes de `setup.initial` para que, si falla, no se escriba nada."""
    import roster as roster_mod
    wanted = roster_mod.telegram_value(value)
    if wanted is None:
        return LinkError("owner_invalid")
    if member is None:
        return LinkError("owner_row")
    for other in (rq("roster.list", account=None).get("data") or {}).get("members") or []:
        if other["row"] != member["row"] and roster_mod.telegram_value(other.get("telegram", "")) == wanted:
            return LinkError("owner_taken", name=other.get("name") or "?")
    return None


def tg_owner_save(rq, value: str, member: dict, etag: str) -> bool:
    """Guarda `value` en la columna Telegram de la fila del dueño, con `roster.save` como la
    página del roster (crea la columna si falta, Q269). Si ya lo tenía, nada."""
    import roster as roster_mod
    if roster_mod.telegram_value(member.get("telegram", "")) == roster_mod.telegram_value(value):
        return True
    fields = {"name": member.get("name", ""), "email": member.get("email", ""), "type": member.get("type", ""),
              "github": member.get("github", ""), "phones": list(member.get("phones") or []), "telegram": value}
    return rq("roster.save", account=None, row=member["row"], member=fields, etag=etag).get("type") == "result"


def tg_setup(ctx, rq, user: dict | None, *, token: str, username: str, owner_telegram: str,
             dedicated: bool) -> dict:
    """Lo mismo que `paynani telegram setup` (`setup.initial`): el token con getMe, el
    usuario del bot contra getMe (Q282), la casilla «sólo de esta instalación» (Q283) y
    telegram.env 0600; luego el Telegram del dueño en su fila (#682) y arranca el servicio.
    Si algo falla antes del bot, no se escribe nada. Devuelve `{bot_username, saved,
    started}`; el correo al dueño lo manda quien llama."""
    from ..telegram import setup as tg_setup_mod
    member, etag = tg_owner_row(rq, user)
    problem = tg_owner_problem(rq, owner_telegram, member)
    if problem:
        raise problem
    try:
        done = tg_setup_mod.initial(token, username, dedicated=dedicated, env=ctx.telegram_env())
    except tg_setup_mod.SetupError as exc:
        raise LinkError(exc.code) from None
    # El bot ya quedó: si el roster cambió entretanto o no se pudo escribir, se dice y se
    # agrega desde Roster.
    saved = tg_owner_save(rq, owner_telegram, member, etag)
    return {"bot_username": done["bot_username"] or "?", "saved": saved, "started": ctx.telegram_start()}
