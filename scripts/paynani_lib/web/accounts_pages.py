"""
Agregar y quitar cuentas de correo desde PaynaniWeb (PRD #434 FR-16; #435 Q23).

Las reglas de Q23:

- antes de agregar o quitar se vuelve a pedir la contraseña de la web;
- al agregar, se prueba el login IMAP (y SMTP, si se dio un servidor de salida)
  antes de guardar, y se escribe con lo mismo que `paynani account add`
  (`accounts_cli.prepare_add` / `commit_add`), y el servicio con `account_service`;
- la contraseña del correo va al `.env`, como hoy, y nunca se vuelve a mostrar: el
  formulario que vuelve con un error no la trae;
- quitar una cuenta no borra su buzón ni su roster, sólo deja de vigilarla
  (`accounts_cli.remove_account`). La cuenta del agente no se quita;
- se le avisa al dueño por correo.
"""
from __future__ import annotations

from .. import i18n
from .shell import e

MAX_FIELD = 320


def _steps(label: str, steps: list[dict]) -> str:
    rows = "".join(
        f'<li class="{"bien" if s.get("ok") else "mal"}">{e(s.get("text", ""))}'
        + (f'<div class="detalle">{e(s.get("detail", ""))}</div>' if s.get("detail") else "") + "</li>"
        for s in steps)
    return f'<div class="prueba"><b>{e(label)}</b><ul class="pasos">{rows}</ul></div>'


def add_body(csrf: str, values: dict | None = None, error: str = "", steps: list | None = None) -> str:
    th = i18n.th
    v = values or {}
    probes = "".join(_steps(label, s) for label, s in (steps or []))
    err = f'<div class="error-caja" role="alert"><b>{th("web.acct.not_added")}</b><p>{e(error)}</p></div>' if error else ""

    def field(name, label, *, kind="text", required=False, default="", hint="", auto="off"):
        req = " required" if required else ""
        hint_html = f'<p class="hint">{hint}</p>' if hint else ""
        return (f'<label for="{name}">{label}</label>'
                f'<input id="{name}" name="{name}" type="{kind}" maxlength="{MAX_FIELD}" autocomplete="{auto}"'
                f' value="{e(v.get(name, default))}"{req}>{hint_html}')

    return f"""<p class="volver"><a href="/email/main">← {th('web.acct.back')}</a></p>
<h2 class="asunto-correo">{th('web.acct.add_h')}</h2>
<p class="lead">{th('web.acct.add_lead')}</p>
{err}{probes}
<form method="post" action="/cuentas/nueva" class="formulario" autocomplete="off">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  {field('id', th('web.acct.f.id'), required=True, hint=th('web.acct.f.id_hint'))}
  {field('email', th('web.acct.f.email'), kind='email', required=True)}
  {field('from_name', th('web.acct.f.from_name'))}
  {field('imap_host', th('web.acct.f.imap_host'), required=True)}
  {field('imap_port', th('web.acct.f.imap_port'), default='993')}
  {field('smtp_host', th('web.acct.f.smtp_host'), hint=th('web.acct.f.smtp_hint'))}
  {field('smtp_port', th('web.acct.f.smtp_port'), default='465')}
  {field('mailbox', th('web.acct.f.mailbox'), default='INBOX')}
  <label for="account_password">{th('web.acct.f.password')}</label>
  <input id="account_password" name="account_password" type="password" required maxlength="1024" autocomplete="new-password">
  <p class="hint">{th('web.acct.f.password_hint')}</p>
  <label for="current">{th('web.acct.f.web_password')}</label>
  <input id="current" name="current" type="password" required autocomplete="current-password">
  <button type="submit" class="primario">{th('web.acct.add_submit')}</button>
</form>
"""


def remove_body(csrf: str, account: dict, error: str = "") -> str:
    th = i18n.th
    err = f'<div class="error-caja" role="alert"><b>{th("web.acct.not_removed")}</b><p>{e(error)}</p></div>' if error else ""
    return f"""<p class="volver"><a href="/email/{e(account['id'])}">← {th('web.acct.back_account')}</a></p>
<h2 class="asunto-correo">{th('web.acct.remove_h', email=account['email'])}</h2>
{err}
<p>{th('web.acct.remove_lead')}</p>
<form method="post" action="/cuentas/{e(account['id'])}/quitar" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <label for="current">{th('web.acct.f.web_password')}</label>
  <input id="current" name="current" type="password" required autocomplete="current-password">
  <div class="botones">
    <button type="submit" class="peligro">{th('web.acct.remove_confirm')}</button>
    <a class="secundario" href="/email/{e(account['id'])}">{th('web.roster.cancel')}</a>
  </div>
</form>
"""
