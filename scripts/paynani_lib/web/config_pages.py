"""
«Configuración» de la cuenta principal (#590 cambio 3), dentro del marco de shell.py.

- El botón va en la lista de la cuenta principal (`/email/main`), junto a «Nuevo
  correo», como «Catch-All» en «Mensajes de texto». Las cuentas adicionales tienen su propio
  alta y baja en «Agregar cuenta».
- `/email/main/configuracion`: el correo, el nombre, los servidores IMAP y SMTP con sus
  puertos y una contraseña nueva opcional; la actual nunca se muestra. Guardar pide la
  contraseña de PaynaniWeb (Q10) y muestra la prueba contra el servidor.
"""
from __future__ import annotations

from .. import i18n
from .shell import e


def _th(key: str, **kw) -> str:
    return i18n.th("web.cfg." + key, **kw)


def link() -> str:
    return f'<a class="secundario" href="/email/main/configuracion">{_th("link")}</a>'


def error_text(code: str, detail: str = "") -> str:
    key = "web.cfg.err." + code
    text = i18n.t(key, detail=detail, code=code)
    return i18n.t("web.cfg.err.other", code=code) if text == key else text


LABELS = {
    "AGENT_EMAIL_ACCOUNT": "email",
    "AGENT_EMAIL_FROM_NAME": "from_name",
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": "imap_host",
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT": "imap_port",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST": "smtp_host",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT": "smtp_port",
    "AGENT_EMAIL_PASSWORD": "new_password",
}


def label(key: str) -> str:
    """El nombre en pantalla de una clave del núcleo (sólo la etiqueta; la lista es de N2)."""
    name = LABELS.get(key)
    return i18n.t("web.cfg." + name) if name else key


def _probe(probe: list | None) -> str:
    rows = []
    for step in probe or []:
        mark = "✓" if step.get("ok") else "✗"
        detail = f' <span class="quiet">{e(step.get("detail") or "")}</span>' if step.get("detail") else ""
        cls = "paso-ok" if step.get("ok") else "paso-mal"
        rows.append(f'<li class="{cls}"><b>{mark} {e(str(step.get("protocol") or "").upper())}</b> '
                    f'{e(step.get("text") or "")}{detail}</li>')
    if not rows:
        return ""
    return f'<section class="prueba"><h3>{_th("probe_h")}</h3><ul class="pasos">{"".join(rows)}</ul></section>'


def _field_errors(errors: dict | None) -> str:
    if not errors:
        return ""
    items = "".join(f"<li><b>{e(label(k))}:</b> {e(v)}</li>" for k, v in errors.items())
    return f'<ul class="errores-campo">{items}</ul>'


def body(values: dict, csrf: str, *, rev: str = "", notice: str = "", error: str = "", probe: list | None = None,
         field_errors: dict | None = None) -> str:
    out = [f'<p class="volver"><a href="/email/main">← {_th("back")}</a></p>',
           f'<p class="lead">{_th("lead")}</p>',
           f'<p class="aviso-ok" role="status">{e(notice)}</p>' if notice else "",
           (f'<div class="error-caja" role="alert"><p>{e(error)}</p>{_field_errors(field_errors)}</div>'
            if error else ""),
           _probe(probe)]

    def field(key: str, kind: str = "text", extra: str = "") -> str:
        name = LABELS[key]
        return (f'<label for="cfg-{name}">{_th(name)}</label>'
                f'<input id="cfg-{name}" name="{e(key)}" type="{kind}" maxlength="320" spellcheck="false"'
                f' value="{e(values.get(key, ""))}"{extra}>')

    out.append(f"""<form method="post" action="/email/main/configuracion" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  <input type="hidden" name="rev" value="{e(rev)}">
  {field("AGENT_EMAIL_ACCOUNT", "email", " required")}
  <p class="hint">{_th("switch")}</p>
  {field("AGENT_EMAIL_FROM_NAME")}
  {field("AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST", extra=" required")}
  {field("AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT", extra=' inputmode="numeric" required')}
  {field("AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST", extra=" required")}
  {field("AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT", extra=' inputmode="numeric" required')}
  <label for="cfg-new_password">{_th("new_password")}</label>
  <input id="cfg-new_password" name="new_password" type="password" autocomplete="new-password">
  <p class="hint">{_th("new_password_hint")}</p>
  <label for="cfg-password">{_th("password")}</label>
  <input id="cfg-password" name="password" type="password" autocomplete="current-password" required>
  <p class="hint">{_th("password_hint")}</p>
  <button type="submit" class="primario">{_th("save")}</button>
</form>""")
    return "\n".join(x for x in out if x) + "\n"
