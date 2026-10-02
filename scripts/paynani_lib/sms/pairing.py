"""
Emparejar el teléfono desde el navegador (SRV-4): `paynani sms pair --web`.

La misma página local del onboarding (server.py: sólo loopback, enlace con llave,
CSRF), con otro contenido: un QR con la dirección de la pasarela y un código de un
solo uso, y el teléfono emparejado con la opción de revocarlo. Los tokens no pasan
por aquí: el almacén sólo guarda su SHA-256 (store.py) y esta página nunca lo lee.

El código y el QR viven en la sesión del navegador (memoria del proceso) mientras
duran sus 10 minutos, para que la página se pueda actualizar sola esperando al
teléfono sin generar otro código en cada vuelta. Nada de eso va a disco ni a logs.
"""
from __future__ import annotations

import html
import json
import os
import time
from urllib.parse import urlparse

from .. import i18n
from . import qr
from .store import CODE_TTL_S

URL_ENV = "PAYNANI_SMS_PUBLIC_URL"
REFRESH_S = 3


def normalise_base(text: str) -> str | None:
    """`https://host[:puerto]` sin barra final, o None si no es una dirección usable."""
    text = (text or "").strip().rstrip("/")
    if not text or any(c.isspace() for c in text):
        return None
    try:
        parsed = urlparse(text)
        parsed.port  # noqa: B018 -- lanza ValueError si el puerto no es un número
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def ws_url(base: str) -> str:
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/sms/ws"


def payload(base: str, code: str) -> dict:
    """Lo que lleva el QR (SMS_GATEWAY.md §1)."""
    return {"v": 1, "pair": base + "/sms/pair", "ws": ws_url(base), "code": code}


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _device_html(device: dict, csrf: str) -> str:
    th = i18n.th
    state = th("sms.state_on") if device.get("connected") else th("sms.state_off")
    rows = [
        ("sms.dev_id", device.get("device_id")),
        ("sms.dev_model", device.get("model") or "-"),
        ("sms.dev_android", device.get("android") or "-"),
        ("sms.dev_app", device.get("app_version") or "-"),
        ("sms.dev_paired", device.get("paired_at") or "-"),
        ("sms.dev_seen", device.get("last_seen") or i18n.t("sms.never")),
    ]
    items = "".join(f"<dt>{th(key)}</dt><dd>{_e(value)}</dd>" for key, value in rows)
    return f"""
<h2>{th('sms.devices_h2')}</h2>
<dl class="device">{items}<dt>{th('sms.dev_state')}</dt><dd>{state}</dd></dl>
<p class="hint">{th('sms.one_phone')}</p>
<form method="post" action="/">
  <input type="hidden" name="csrf" value="{_e(csrf)}">
  <div class="actions compact">
    <button type="submit" name="action" value="revoke" class="secondary">{th('sms.revoke')}</button>
  </div>
</form>"""


def _code_html(pair: dict) -> str:
    th = i18n.th
    minutes = CODE_TTL_S // 60
    return f"""
<div class="panel">
  <h2>{th('sms.code_h2')}</h2>
  <div class="qr">{pair['svg']}</div>
  <p>{th('sms.code_p', minutes=minutes)}</p>
  <p><strong>{th('sms.addr_label')}:</strong> <code>{_e(pair['base'])}</code><br>
     <strong>{th('sms.code_label')}:</strong> <code class="pairing-code">{_e(pair['code'])}</code></p>
  <p class="hint" role="status">{th('sms.waiting')}</p>
</div>"""


def _form_html(csrf: str, url: str, error: str) -> str:
    th = i18n.th
    err = f'<p class="err">{error}</p>' if error else ""
    return f"""
<p class="hint">{th('sms.gateway_hint')}</p>
<form method="post" action="/" autocomplete="off">
  <input type="hidden" name="csrf" value="{_e(csrf)}">
  <label for="smsurl">{th('sms.url_label')}</label>
  <input type="url" id="smsurl" name="url" required value="{_e(url)}" placeholder="{th('sms.url_ph')}">
  {err}
  <p class="hint">{th('sms.url_hint')}</p>
  <div class="actions">
    <button type="submit" name="action" value="new_code" class="primary">{th('sms.generate')}</button>
  </div>
</form>"""


def build(session: dict, post: dict, action: str, store, *, now: float | None = None) -> tuple[str, bool]:
    """
    El cuerpo de la página y si debe actualizarse sola. Aplica `revoke` y
    `new_code` (el servidor ya comprobó el CSRF de cualquier acción).
    """
    th = i18n.th
    now = time.time() if now is None else now
    notices: list[str] = []
    error = ""

    if action == "revoke":
        gone = store.revoke()
        session.pop("pair", None)
        if gone:
            notices.append(("ok", th("sms.revoked", device=gone.get("device_id", ""))))
    elif action == "new_code":
        base = normalise_base(post.get("url", ""))
        session["sms_url"] = post.get("url", "").strip()
        if store.device():
            notices.append(("warn", th("sms.one_phone")))
        elif base is None:
            error = th("sms.err_url")
        else:
            code = store.new_code()
            text = json.dumps(payload(base, code), separators=(",", ":"), ensure_ascii=False)
            session["pair"] = {"base": base, "code": code, "issued": now,
                               "svg": qr.to_svg(qr.encode(text), label=i18n.t("sms.code_h2"))}

    device = store.device()
    pair = session.get("pair")
    if pair and device:
        notices.append(("ok", th("sms.paired_ok", device=device.get("device_id", ""))))
        session.pop("pair", None)
        pair = None
    elif pair and now > pair["issued"] + CODE_TTL_S:
        notices.append(("warn", th("sms.expired")))
        session.pop("pair", None)
        pair = None

    csrf = session["csrf"]
    out = "".join(f'<div class="panel {cls}"><p>{msg}</p></div>' for cls, msg in notices)
    if device:
        out += _device_html(device, csrf)
    else:
        out += f'<p>{th("sms.devices_none")}</p>'
        if pair:
            out += _code_html(pair)
        else:
            out += _form_html(csrf, session.get("sms_url") or os.environ.get(URL_ENV, ""), error)
    return out, bool(pair)
