"""
Profile (PRD #434 FR-21), como la pantalla Profile del `/dash` de Service Button
(`show_profile()` en tpl_contactcenter-configuration.php): arriba el avatar con
iniciales, el nombre, «Owner» y el último ingreso; abajo, sólo dos opciones
(Julian en #433, Q25): Personal Info y Account Password.

- **Personal Info:** el nombre y el correo del dueño. El correo es con el que se
  entra y al que llegan los avisos (FR-9), así que cambiarlo pide la contraseña.
- **Account Password:** la actual y la nueva dos veces, de al menos 12 caracteres.
  Al cambiarla se cierran las otras sesiones; la de quien la cambió sigue.
"""
from __future__ import annotations

from .. import i18n
from . import users
from .shell import e, icon, initials


def _when(stamp: str) -> str:
    if len(stamp) >= 16 and "T" in stamp:
        return stamp[:10] + " " + stamp[11:16] + " UTC"
    return stamp or "—"


def _box(kind: str, text: str) -> str:
    if not text:
        return ""
    cls = "aviso-ok" if kind == "ok" else "error-caja"
    role = "status" if kind == "ok" else "alert"
    return f'<p class="{cls}" role="{role}">{text}</p>'


def main_body(user: dict, ok: str = "") -> str:
    th = i18n.th
    notice = th(f"web.profile.ok.{ok}") if ok in ("info", "password") else ""
    return f"""{_box('ok', notice)}
<section class="perfil">
  <div class="avatar-grande">{e(initials(user.get('name', '')))}</div>
  <h2>{e(user.get('name', ''))}</h2>
  <p class="puesto">{th('web.profile.owner')}</p>
  <p class="quiet">{th('web.profile.last_login', when=_when(user.get('last_login_at', '')))}</p>
</section>
<ul class="opciones-perfil">
  <li><a href="/profile/info">{icon('profile')}<span>{th('web.profile.info')}</span>{icon('chevron', 'flecha-der')}</a></li>
  <li><a href="/profile/password">{icon('lock')}<span>{th('web.profile.password')}</span>{icon('chevron', 'flecha-der')}</a></li>
</ul>
"""


def info_body(user: dict, csrf: str, error: str = "", values: dict | None = None) -> str:
    th = i18n.th
    v = values or user
    return f"""<p class="volver"><a href="/profile">← {th('web.profile.back')}</a></p>
<h2 class="asunto-correo">{th('web.profile.info')}</h2>
{_box('err', error)}
<form method="post" action="/profile/info" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <label for="name">{th('web.roster.f.name')}</label>
  <input id="name" name="name" required maxlength="200" value="{e(v.get('name', ''))}" autocomplete="name">
  <label for="email">{th('web.profile.email')}</label>
  <input id="email" name="email" type="email" required maxlength="320" value="{e(v.get('email', ''))}" autocomplete="email">
  <p class="hint">{th('web.profile.email_hint')}</p>
  <label for="current">{th('web.profile.current')}</label>
  <input id="current" name="current" type="password" autocomplete="current-password">
  <p class="hint">{th('web.profile.current_hint')}</p>
  <button type="submit" class="primario">{th('web.roster.save')}</button>
</form>
"""


def password_body(csrf: str, error: str = "") -> str:
    th = i18n.th
    return f"""<p class="volver"><a href="/profile">← {th('web.profile.back')}</a></p>
<h2 class="asunto-correo">{th('web.profile.password')}</h2>
{_box('err', error)}
<form method="post" action="/profile/password" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <label for="current">{th('web.profile.current')}</label>
  <input id="current" name="current" type="password" required autocomplete="current-password">
  <label for="new">{th('web.profile.new')}</label>
  <input id="new" name="new" type="password" required minlength="{users.MIN_PASSWORD}" autocomplete="new-password">
  <label for="again">{th('web.profile.again')}</label>
  <input id="again" name="again" type="password" required minlength="{users.MIN_PASSWORD}" autocomplete="new-password">
  <p class="hint">{th('web.profile.password_hint', min=users.MIN_PASSWORD)}</p>
  <button type="submit" class="primario">{th('web.profile.change')}</button>
</form>
"""
