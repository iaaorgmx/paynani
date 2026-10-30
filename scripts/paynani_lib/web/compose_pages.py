"""
«Nuevo correo» (#590 cambio 2), dentro del marco de shell.py.

- El botón «Nuevo correo» va en la lista de cada cuenta (`/email/<cuenta>`), junto a
  sus acciones, como «Catch-All» en «Mensajes».
- `/email/<cuenta>/nuevo`: De (la cuenta de esa lista, Q7=A), Para, CC y CCO (Q6=B),
  asunto, mensaje y la contraseña, que sólo se pide si alguien está fuera del roster
  de esa cuenta (Q5). La libreta es el roster de esa cuenta; `compose.js` agrega el
  contacto elegido al campo donde estaba el cursor. Sin JavaScript, la libreta se ve
  igual y las direcciones se copian a mano.
- Manda a `POST /email/<cuenta>/enviar`.
"""
from __future__ import annotations

from urllib.parse import quote as urlquote

from .. import i18n
from .shell import e


def _th(key: str, **kw) -> str:
    return i18n.th("web.compose." + key, **kw)


def new_button(account_id: str) -> str:
    return (f'<a class="secundario" href="/email/{urlquote(account_id)}/nuevo">{_th("new")}</a>')


def notice(sent: bool, outside_n: int = 0, *, copy_failed: bool = False, notice_failed: bool = False) -> str:
    """El aviso al volver a la lista después de mandar. Cada estado por separado: que se
    envió, cuántos estaban fuera del roster, si no se guardó la copia en Enviados y si no
    salió el aviso al dueño (revisión de Ximena, #594)."""
    if not sent:
        return ""
    out = [f'<p class="aviso-ok" role="status">'
           f'{_th("sent_outside", n=outside_n) if outside_n > 0 else _th("sent_ok")}</p>']
    if copy_failed:
        out.append(f'<p class="aviso-caja" role="status">{_th("sent_no_copy")}</p>')
    if notice_failed:
        out.append(f'<p class="aviso-caja" role="status">{_th("notice_failed")}</p>')
    return "\n".join(out) + "\n"


def error_text(code: str, *, detail: str = "", outside: list[str] | None = None) -> str:
    key = "web.compose.err." + code
    text = i18n.t(key, detail=detail, list=", ".join(outside or []), code=code)
    return i18n.t("web.compose.err.other", code=code) if text == key else text


def body(account_id: str, account_email: str, csrf: str, book: list[dict], *, values: dict | None = None,
         error: str = "", signed: bool = False) -> str:
    th = i18n.th
    values = values or {}
    back = f'<p class="volver"><a href="/email/{e(urlquote(account_id))}">← {_th("back")}</a></p>'
    err = f'<div class="error-caja" role="alert"><p>{e(error)}</p></div>' if error else ""
    contacts = "".join(
        f'<li><button type="button" class="contacto-libreta" data-email="{e(c["email"])}">'
        f'<b>{e(c["name"])}</b> <span class="quiet">{e(c["email"])}</span></button></li>' for c in book)
    options = "".join(f'<option value="{e(c["email"])}">{e(c["name"])}</option>' for c in book)
    libreta = (f"""<details class="libreta" open>
  <summary>{_th("book")}</summary>
  <ul class="libreta-lista">{contacts}</ul>
</details>""" if book else "")
    signature = f'<p class="hint">{_th("signature")}</p>' if signed else ""

    def field(name: str, label_key: str, required: bool = False) -> str:
        req = " required" if required else ""
        return (f'<label for="mail-{name}">{_th(label_key)}</label>'
                f'<input id="mail-{name}" name="{name}" type="text" list="mail-book" autocomplete="off"'
                f' spellcheck="false" maxlength="4000" data-libreta value="{e(values.get(name, ""))}"{req}>')

    return f"""{back}{err}
<form method="post" action="/email/{e(urlquote(account_id))}/enviar" class="formulario correo-nuevo">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <p class="quiet"><b>{_th("from")}:</b> {e(account_email)}</p>
  {field("to", "to", required=True)}
  {field("cc", "cc")}
  {field("bcc", "bcc")}
  <datalist id="mail-book">{options}</datalist>
  <p class="hint">{_th("book_hint")}</p>
  {libreta}
  <label for="mail-subject">{_th("subject")}</label>
  <input id="mail-subject" name="subject" maxlength="300" required value="{e(values.get("subject", ""))}">
  <label for="mail-text">{_th("text")}</label>
  <textarea id="mail-text" name="text" rows="12" required>{e(values.get("text", ""))}</textarea>
  {signature}
  <label for="mail-password">{_th("password")}</label>
  <input id="mail-password" name="password" type="password" autocomplete="current-password">
  <p class="hint">{_th("password_hint")}</p>
  <button type="submit" class="primario">{_th("send")}</button>
</form>
<script src="/assets/compose.js" defer></script>
"""
