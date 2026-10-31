"""
Roster (PRD #434 FR-20, FR-9): lo mismo que la pantalla «Roster» de PaynaniApp,
con el mismo servicio (sms/roster_api.RosterService) y por lo tanto las mismas
validaciones, el `etag`, la copia en `state/history/`, el log de cambios y el
correo al dueño. La web arma los pedidos de §11 de SMS_GATEWAY.md como si fuera la
app, con `device_id` `web:<dirección>`.

Las pantallas:

- `/roster?cuenta=<id>`: el selector de cuenta (la del agente y las de
  accounts.json), la lista y los botones.
- `/roster/editar?cuenta=&fila=` (o sin fila para un alta): el formulario.
- `/roster/quitar?cuenta=&fila=`: la confirmación de la baja.
- `/roster/reglas?cuenta=&fila=` (o `?general=1`): el editor de instrucciones, con
  la vista previa de la regla efectiva.

Todo lo que viene del roster o de las reglas pasa por `e()`.
"""
from __future__ import annotations

from urllib.parse import quote, urlencode

from .. import i18n
from .shell import e

NEW_RULES = "---\nversion: 1\nenabled: true\n---\n\n## General\n\n"
TYPES = ("Human", "AI Agent")


def q(**params) -> str:
    return urlencode({k: v for k, v in params.items() if v is not None and v != ""})


def _acct(account) -> str:
    return account or "main"


def error_box(error: dict | None) -> str:
    if not error:
        return ""
    th = i18n.th
    code = str(error.get("code") or "write_failed")
    text = i18n.t(f"web.roster.err.{code}")
    if text.startswith("web."):
        text = i18n.t("web.roster.err.write_failed")
    field = error.get("field")
    extra = f" ({e(field)})" if field else ""
    detail = error.get("detail")
    more = f'<p class="quiet">{e(detail)}</p>' if detail else ""
    return f'<div class="error-caja" role="alert"><b>{th("web.roster.err_h")}</b><p>{e(text)}{extra}</p>{more}</div>'


def notice_box(ok: str) -> str:
    if not ok:
        return ""
    text = i18n.t(f"web.roster.ok.{ok}")
    if text.startswith("web."):
        return ""
    return f'<p class="aviso-ok" role="status">{e(text)}</p>'


def account_picker(accounts: list[dict], current) -> str:
    th = i18n.th
    items = []
    for a in accounts:
        acc = _acct(a["account"])
        label = e(a["email"] or a["roster"])
        count = th("web.roster.members_n", n=a.get("members", 0))
        status = "" if a.get("status") == "ok" else f' · {th("web.roster.status." + str(a.get("status")))}'
        cls = ' class="activo"' if acc == _acct(current) else ""
        current_attr = ' aria-current="page"' if acc == _acct(current) else ""
        items.append(f'<a{cls}{current_attr} href="/roster?{e(q(cuenta=acc))}">{label}<small>{count}{status}</small></a>')
    # Un <div> y no un <nav>: las reglas del menú lateral (`.web-shell nav …`) no le aplican.
    return f'<div class="cuentas-roster" role="navigation" aria-label="{th("web.roster.accounts")}">{"".join(items)}</div>'


def list_body(accounts: list[dict], listing: dict, csrf: str, ok: str = "", error=None) -> str:
    th = i18n.th
    acc = _acct(listing.get("account"))
    out = [account_picker(accounts, listing.get("account")), notice_box(ok), error_box(error)]
    out.append(f'<p class="acciones"><a class="primario" href="/roster/editar?{e(q(cuenta=acc))}">{th("web.roster.add")}</a>'
               f' <a class="secundario" href="/roster/reglas?{e(q(general=1))}">{th("web.roster.default_rules")}</a></p>')
    members = listing.get("members") or []
    if not members:
        out.append(f'<p class="lead">{th("web.roster.empty")}</p>')
        return "\n".join(out) + "\n"
    out.append('<ul class="contactos">')
    for m in members:
        badges = []
        if m.get("owner"):
            badges.append(f'<span class="marca-roster">{th("web.roster.owner")}</span>')
        if m.get("has_rules"):
            key = "web.roster.rules_on" if m.get("rules_enabled") else "web.roster.rules_off"
            badges.append(f'<span class="estado">{th(key)}</span>')
        contact = " · ".join(e(x) for x in [m.get("email")] + list(m.get("phones") or []) if x)
        github = f' · GitHub {e(m["github"])}' if m.get("github") else ""
        row = m["row"]
        actions = [f'<a href="/roster/editar?{e(q(cuenta=acc, fila=row))}">{th("web.roster.edit")}</a>',
                   f'<a href="/roster/reglas?{e(q(cuenta=acc, fila=row))}">{th("web.roster.rules")}</a>']
        if not m.get("owner"):
            actions.append(f'<a class="peligro" href="/roster/quitar?{e(q(cuenta=acc, fila=row))}">{th("web.roster.remove")}</a>')
        out.append(f"""<li>
  <div class="contacto"><b>{e(m.get('name') or '—')}</b> <span class="quiet">{e(m.get('type') or '')}</span> {' '.join(badges)}
  <div class="quiet">{contact}{github}</div></div>
  <div class="acciones-fila">{' · '.join(actions)}</div>
</li>""")
    out.append("</ul>")
    out.append(f'<p class="quiet">{th("web.roster.note")}</p>')
    return "\n".join(out) + "\n"


def edit_body(account, listing: dict, member: dict | None, csrf: str, error=None, values: dict | None = None,
              telegram: bool = False, lead: str = "") -> str:
    """El formulario de una fila. `telegram` agrega el campo Telegram (PRD #609 FR-13 y
    FR-15), que también sale si la fila ya trae uno. «Agregar al roster» desde un hilo de
    Telegram llega aquí con `values` llenos y `lead`."""
    th = i18n.th
    acc = _acct(account)
    m = values or member or {}
    row = (member or {}).get("row")
    title = th("web.roster.edit_h", name=(member or {}).get("name", "")) if member else th("web.roster.add_h")
    phones = m.get("phones")
    phones = ", ".join(phones) if isinstance(phones, list) else (phones or "")
    options = "".join(f'<option value="{t}"{" selected" if (m.get("type") or "Human") == t else ""}>{t}</option>'
                      for t in TYPES)
    owner_note = f'<p class="quiet">{th("web.roster.owner_note")}</p>' if (member or {}).get("owner") else ""
    tg_value = str(m.get("telegram") or "")
    tg_field = (f'''<label for="telegram">Telegram <span class="opt">{th('web.roster.optional')}</span></label>
  <input id="telegram" name="telegram" maxlength="64" autocomplete="off" spellcheck="false" value="{e(tg_value)}">
  ''' if telegram or tg_value else "")
    lead_html = f'<p class="lead">{e(lead)}</p>' if lead else ""
    return f"""<p class="volver"><a href="/roster?{e(q(cuenta=acc))}">← {th('web.roster.back')}</a></p>
<h2 class="asunto-correo">{title}</h2>
{lead_html}{error_box(error)}{owner_note}
<form method="post" action="/roster/guardar" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="cuenta" value="{e(acc)}">
  <input type="hidden" name="fila" value="{e(row or '')}">
  <input type="hidden" name="etag" value="{e(listing.get('etag', ''))}">
  <label for="name">{th('web.roster.f.name')}</label>
  <input id="name" name="name" required maxlength="200" value="{e(m.get('name', ''))}">
  <label for="email">{th('web.roster.f.email')}</label>
  <input id="email" name="email" type="email" maxlength="320" value="{e(m.get('email', ''))}">
  <label for="type">{th('web.roster.f.type')}</label>
  <span class="combo"><select id="type" name="type">{options}</select></span>
  <label for="github">{th('web.roster.f.github')} <span class="opt">{th('web.roster.optional')}</span></label>
  <input id="github" name="github" maxlength="100" value="{e(m.get('github', ''))}">
  <label for="phones">{th('web.roster.f.phones')} <span class="opt">{th('web.roster.optional')}</span></label>
  <input id="phones" name="phones" maxlength="300" value="{e(phones)}">
  <p class="hint">{th('web.roster.phones_hint')}</p>
  {tg_field}<button type="submit" class="primario">{th('web.roster.save')}</button>
</form>
"""


def remove_body(account, listing: dict, member: dict, csrf: str, error=None) -> str:
    th = i18n.th
    acc = _acct(account)
    return f"""<p class="volver"><a href="/roster?{e(q(cuenta=acc))}">← {th('web.roster.back')}</a></p>
<h2 class="asunto-correo">{th('web.roster.remove_h', name=member.get('name', ''))}</h2>
{error_box(error)}
<p>{th('web.roster.remove_lead')}</p>
<form method="post" action="/roster/quitar">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="cuenta" value="{e(acc)}">
  <input type="hidden" name="fila" value="{e(member['row'])}">
  <input type="hidden" name="etag" value="{e(listing.get('etag', ''))}">
  <button type="submit" class="peligro">{th('web.roster.remove_confirm')}</button>
  <a class="secundario" href="/roster?{e(q(cuenta=acc))}">{th('web.roster.cancel')}</a>
</form>
"""


def rules_body(account, *, general: bool, member: dict | None, data: dict, csrf: str, text: str,
               effective: str, roster_etag: str = "", error=None, ok: str = "") -> str:
    th = i18n.th
    acc = _acct(account)
    back = f"/roster?{e(q(cuenta=acc))}"
    if general:
        h2, lead = th("web.roster.default_rules"), th("web.roster.default_lead")
    else:
        h2, lead = th("web.roster.rules_h", name=(member or {}).get("name", "")), th("web.roster.rules_lead")
    missing = "" if data.get("exists") else f'<p class="quiet">{th("web.roster.rules_new" if not general else "web.roster.default_new")}</p>'
    return f"""<p class="volver"><a href="{back}">← {th('web.roster.back')}</a></p>
<h2 class="asunto-correo">{h2}</h2>
<p class="lead">{lead}</p>
{notice_box(ok)}{error_box(error)}{missing}
<form method="post" action="/roster/reglas" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="cuenta" value="{e(acc)}">
  <input type="hidden" name="general" value="{'1' if general else ''}">
  <input type="hidden" name="fila" value="{e((member or {}).get('row', ''))}">
  <input type="hidden" name="etag" value="{e(data.get('etag', ''))}">
  <input type="hidden" name="roster_etag" value="{e(roster_etag)}">
  <label for="text">{th('web.roster.rules_text')}</label>
  <textarea id="text" name="text" rows="18" spellcheck="true" maxlength="32768">{e(text)}</textarea>
  <p class="hint">{th('web.roster.rules_hint')}</p>
  <div class="botones">
    <button type="submit" name="accion" value="vista" class="secundario">{th('web.roster.preview')}</button>
    <button type="submit" name="accion" value="guardar" class="primario">{th('web.roster.save')}</button>
  </div>
</form>
<h3>{th('web.roster.effective')}</h3>
<p class="quiet">{th('web.roster.effective_lead')}</p>
<pre class="cuerpo">{e(effective) or e(i18n.t('web.roster.effective_empty'))}</pre>
"""
