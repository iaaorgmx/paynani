"""
«Configuración» de la cuenta principal (#590 cambio 3), dentro del marco de shell.py.

- El botón va en la lista de la cuenta principal (`/email/main`), junto a «Nuevo
  correo», como «Catch-All» en «Mensajes». Las cuentas adicionales tienen su propio
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


def _probe(probe: dict | None) -> str:
    if not probe:
        return ""
    rows = []
    for proto in ("imap", "smtp"):
        for step in probe.get(proto) or []:
            mark = "✓" if step.get("ok") else "✗"
            detail = f' <span class="quiet">{e(step.get("detail") or "")}</span>' if step.get("detail") else ""
            cls = "paso-ok" if step.get("ok") else "paso-mal"
            rows.append(f'<li class="{cls}"><b>{mark} {e(proto.upper())}</b> {e(step.get("text") or "")}{detail}</li>')
    if not rows:
        return ""
    return f'<section class="prueba"><h3>{_th("probe_h")}</h3><ul class="pasos">{"".join(rows)}</ul></section>'


def body(values: dict, csrf: str, *, notice: str = "", error: str = "", probe: dict | None = None) -> str:
    out = [f'<p class="volver"><a href="/email/main">← {_th("back")}</a></p>',
           f'<p class="lead">{_th("lead")}</p>',
           f'<p class="aviso-ok" role="status">{e(notice)}</p>' if notice else "",
           f'<div class="error-caja" role="alert"><p>{e(error)}</p></div>' if error else "",
           _probe(probe)]

    def field(name: str, kind: str = "text", extra: str = "") -> str:
        return (f'<label for="cfg-{name}">{_th(name)}</label>'
                f'<input id="cfg-{name}" name="{name}" type="{kind}" maxlength="320" spellcheck="false"'
                f' value="{e(values.get(name, ""))}"{extra}>')

    out.append(f"""<form method="post" action="/email/main/configuracion" class="formulario">
  <input type="hidden" name="csrf" value="{e(csrf)}">
  {field("email", "email", " required")}
  <p class="hint">{_th("switch")}</p>
  {field("from_name")}
  {field("imap_host", extra=" required")}
  {field("imap_port", extra=' inputmode="numeric" required')}
  {field("smtp_host", extra=" required")}
  {field("smtp_port", extra=' inputmode="numeric" required')}
  <label for="cfg-new_password">{_th("new_password")}</label>
  <input id="cfg-new_password" name="new_password" type="password" autocomplete="new-password">
  <p class="hint">{_th("new_password_hint")}</p>
  <label for="cfg-password">{_th("password")}</label>
  <input id="cfg-password" name="password" type="password" autocomplete="current-password" required>
  <p class="hint">{_th("password_hint")}</p>
  <button type="submit" class="primario">{_th("save")}</button>
</form>""")
    return "\n".join(x for x in out if x) + "\n"
