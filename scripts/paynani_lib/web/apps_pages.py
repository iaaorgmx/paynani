"""
«Apps conectadas» (PaynaniWebMT#2 FR-A3; nueva UI en #742): los clientes web del dueño, como PaynaniWebMT.

- `/apps` es una tabla como la de Email: a todo lo ancho, con cabecera gris, cada fila un enlace
  con su chevron al final, y en el teléfono las filas apiladas. Sin campos de contraseña en las filas.
- `/apps/detail?id=<client_id>` muestra la app y «Revocar esta app» (POST `/apps/revoke`), que pide
  la contraseña de PaynaniWeb.
- `/apps/pair` pide la contraseña; POST `/apps/code` da la dirección del túnel y un código de un
  solo uso, como `scripts/paynani web pair`, cada uno con un icono de copiar (`assets/apps.js`),
  como Business Information de ServiceButtonWebApp. El código abre la administración completa.

Todo lo que se pone en el HTML pasa por `e()`.
"""
from __future__ import annotations

import datetime as dt
from urllib.parse import quote as urlquote

from .. import i18n
from ..i18n_data import CATALOGUES
from . import owner_clients, token_strings, when  # noqa: F401  (token_strings: web.tokens.rel.*)
from .shell import ROW_CHEVRON, e

KEYS = ["title", "empty", "name", "app", "paired", "last_used", "status", "active", "revoked", "never",
        "code", "password", "revoke", "address", "pair_code", "no_url", "revoked_ok", "missing",
        "pair_new", "count", "note", "id", "access", "full", "revoke_title", "revoke_hint", "pair_lead",
        "expires", "minutes", "copy", "copied", "once", "done", "revoked_at"]
WORDS = {
    "es-MX": ["Apps conectadas", "Todavía no hay apps conectadas.", "Nombre", "App", "Emparejada", "Último uso",
              "Estado", "Activa", "Revocada", "Nunca", "Generar código", "Contraseña de PaynaniWeb", "Revocar",
              "Dirección del gateway", "Código de emparejamiento",
              "Falta la dirección pública (PAYNANI_SMS_PUBLIC_URL en sms.env).",
              "App revocada: su token ya no abre la API.", "No existe esa app o ya estaba revocada.",
              "Emparejar app", "{n} apps · {m} activas",
              "Apps como PaynaniWebMT que administran esta instalación a distancia. No ocupan el lugar del teléfono. Abre una para ver sus datos o revocarla.",
              "Id", "Acceso", "Administración completa de esta instalación", "Revocar esta app",
              "La app de ese dispositivo deja de funcionar en ese momento. Después puedes emparejarla otra vez con un código nuevo.",
              "Recibirás la dirección del gateway y un código de un solo uso para escribirlos en la app, en «Conectar paynani».",
              "Vence en", "{min} min", "Copiar", "Copiado",
              "El código sirve una sola vez. No se lo des a nadie más: abre la administración completa de tu paynani.",
              "Listo", "Revocada"],
    "en-US": ["Connected apps", "No apps are connected yet.", "Name", "App", "Paired", "Last used",
              "Status", "Active", "Revoked", "Never", "Generate code", "PaynaniWeb password", "Revoke",
              "Gateway address", "Pairing code",
              "The public address is missing (PAYNANI_SMS_PUBLIC_URL in sms.env).",
              "App revoked: its token no longer opens the API.", "That app does not exist or was already revoked.",
              "Pair new app", "{n} apps · {m} active",
              "Apps such as PaynaniWebMT that manage this install remotely. They do not take the phone's place. Open one to see its details or revoke it.",
              "Id", "Access", "Full control of this install", "Revoke this app",
              "The app on that device stops working right away. You can pair it again later with a new code.",
              "You will get the gateway address and a one-time code to type in the app, under “Connect paynani”.",
              "Expires in", "{min} min", "Copy", "Copied",
              "The code works once. Do not give it to anyone else: it opens full control of your paynani.",
              "Done", "Revoked"],
    "es-ES": ["Apps conectadas", "Todavía no hay apps conectadas.", "Nombre", "App", "Emparejada", "Último uso",
              "Estado", "Activa", "Revocada", "Nunca", "Generar código", "Contraseña de PaynaniWeb", "Revocar",
              "Dirección del gateway", "Código de emparejamiento",
              "Falta la dirección pública (PAYNANI_SMS_PUBLIC_URL en sms.env).",
              "App revocada: su token ya no abre la API.", "Esa app no existe o ya estaba revocada.",
              "Emparejar app", "{n} apps · {m} activas",
              "Apps como PaynaniWebMT que administran esta instalación a distancia. No ocupan el lugar del teléfono. Abre una para ver sus datos o revocarla.",
              "Id", "Acceso", "Administración completa de esta instalación", "Revocar esta app",
              "La app de ese dispositivo deja de funcionar en ese momento. Después puedes emparejarla otra vez con un código nuevo.",
              "Recibirás la dirección del gateway y un código de un solo uso para escribirlos en la app, en «Conectar paynani».",
              "Caduca en", "{min} min", "Copiar", "Copiado",
              "El código sirve una sola vez. No se lo des a nadie más: abre la administración completa de tu paynani.",
              "Listo", "Revocada"],
    "fr-FR": ["Apps connectées", "Aucune app connectée pour l’instant.", "Nom", "App", "Appairée",
              "Dernière utilisation", "Statut", "Active", "Révoquée", "Jamais", "Générer un code",
              "Mot de passe PaynaniWeb", "Révoquer", "Adresse de la passerelle", "Code d’appairage",
              "L’adresse publique manque (PAYNANI_SMS_PUBLIC_URL dans sms.env).",
              "App révoquée : son jeton n’ouvre plus l’API.", "Cette app n’existe pas ou était déjà révoquée.",
              "Appairer une app", "{n} apps · {m} actives",
              "Des apps comme PaynaniWebMT qui gèrent cette installation à distance. Elles ne prennent pas la place du téléphone. Ouvrez-en une pour voir ses détails ou la révoquer.",
              "Id", "Accès", "Contrôle complet de cette installation", "Révoquer cette app",
              "L’app de cet appareil cesse de fonctionner tout de suite. Vous pourrez l’appairer de nouveau plus tard avec un nouveau code.",
              "Vous recevrez l’adresse de la passerelle et un code à usage unique à saisir dans l’app, sous « Connecter paynani ».",
              "Expire dans", "{min} min", "Copier", "Copié",
              "Le code ne sert qu’une fois. Ne le donnez à personne d’autre : il ouvre le contrôle complet de votre paynani.",
              "Terminé", "Révoquée"],
    "pt-BR": ["Apps conectados", "Ainda não há apps conectados.", "Nome", "App", "Pareado", "Último uso",
              "Status", "Ativo", "Revogado", "Nunca", "Gerar código", "Senha do PaynaniWeb", "Revogar",
              "Endereço do gateway", "Código de pareamento",
              "Falta o endereço público (PAYNANI_SMS_PUBLIC_URL em sms.env).",
              "App revogado: o token dele não abre mais a API.", "Esse app não existe ou já estava revogado.",
              "Parear novo app", "{n} apps · {m} ativos",
              "Apps como o PaynaniWebMT que administram esta instalação à distância. Eles não ocupam o lugar do telefone. Abra um para ver os detalhes ou revogá-lo.",
              "Id", "Acesso", "Controle completo desta instalação", "Revogar este app",
              "O app desse dispositivo para de funcionar na hora. Depois você pode pareá-lo de novo com um código novo.",
              "Você vai receber o endereço do gateway e um código de uso único para digitar no app, em “Conectar paynani”.",
              "Expira em", "{min} min", "Copiar", "Copiado",
              "O código vale uma única vez. Não o dê a mais ninguém: ele abre o controle completo do seu paynani.",
              "Concluir", "Revogado"],
}
# El detalle nuevo y «Borrar esta app» (#769, mockup aprobado por Julian, Iris[Q74]=B).
KEYS += ["sec_details", "line_revoked", "line_used", "line_unused", "delete_title", "delete_hint", "delete", "deleted",
         "delete_active"]
WORDS["es-MX"] += ["Detalles", "Revocada el {when} · {rel}", "{app} · último uso {rel}", "{app} · todavía sin usar",
                   "Borrar esta app",
                   "Su token ya no abre la API. Borrarla la quita de esta lista para siempre. La bitácora de la API conserva el prefijo de su token y lo que hizo.",
                   "Borrar app", "App borrada.", "Esta app sigue activa: primero revócala."]
WORDS["en-US"] += ["Details", "Revoked {when} · {rel}", "{app} · last used {rel}", "{app} · not used yet",
                   "Delete this app",
                   "Its token no longer opens the API. Deleting removes it from this list for good. The API log keeps its token prefix and what it did.",
                   "Delete app", "App deleted.", "This app is still active: revoke it first."]
WORDS["es-ES"] += ["Detalles", "Revocada el {when} · {rel}", "{app} · último uso {rel}", "{app} · todavía sin usar",
                   "Borrar esta app",
                   "Su token ya no abre la API. Borrarla la quita de esta lista para siempre. El registro de la API conserva el prefijo de su token y lo que hizo.",
                   "Borrar app", "App borrada.", "Esta app sigue activa: primero revócala."]
WORDS["fr-FR"] += ["Détails", "Révoquée le {when} · {rel}", "{app} · dernière utilisation {rel}", "{app} · pas encore utilisée",
                   "Supprimer cette app",
                   "Son jeton n’ouvre plus l’API. La supprimer la retire de cette liste pour de bon. Le journal de l’API garde le préfixe de son jeton et ce qu’elle a fait.",
                   "Supprimer l’app", "App supprimée.", "Cette app est encore active : révoquez-la d’abord."]
WORDS["pt-BR"] += ["Detalhes", "Revogado em {when} · {rel}", "{app} · último uso {rel}", "{app} · ainda não usado",
                   "Apagar este app",
                   "O token dele não abre mais a API. Apagar tira o app desta lista para sempre. O registro da API guarda o prefixo do token e o que ele fez.",
                   "Apagar app", "App apagado.", "Este app ainda está ativo: revogue-o primeiro."]
# «Revocar esta app» avisa que después se puede borrar.
for _language, _more in {"es-MX": " Una app revocada se puede borrar después.", "en-US": " A revoked app can then be deleted.",
                         "es-ES": " Una app revocada se puede borrar después.",
                         "fr-FR": " Une app révoquée peut ensuite être supprimée.",
                         "pt-BR": " Um app revogado pode ser apagado depois."}.items():
    WORDS[_language][KEYS.index("revoke_hint")] += _more
for _language, _words in WORDS.items():
    assert len(KEYS) == len(_words), _language
    CATALOGUES[_language].update({"web.apps." + key: value for key, value in zip(KEYS, _words)})

# El icono de copiar: dos hojas encimadas, como en ServiceButtonWebApp.
COPY_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/>'
             '<path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>')


def _th(key: str, **kw) -> str:
    return i18n.th("web.apps." + key, **kw)


def _time(stamp: str | None, *, short: bool) -> str:
    """Una fecha como en las listas de Email: `<time>` que `time.js` pasa a la zona del navegador."""
    if not stamp:
        return _th("never")
    iso, shown, title = when.render(stamp, i18n.current_lang(), short=short)
    if not iso:
        return e(shown)
    return f'<time datetime="{e(iso)}" title="{e(title)}"{" data-corto" if short else ""}>{e(shown)}</time>'


def _app(record: dict) -> str:
    name, version = record.get("app_name") or "", record.get("app_version") or ""
    if not name and not version:
        return "—"
    shown = e(name)
    if version:
        shown += f' <span class="app-version">v{e(version)}</span>'
    return shown


def _state(record: dict) -> str:
    if record.get("revoked_at"):
        return f'<span class="estado estado-app-revoked">{_th("revoked")}</span>'
    return f'<span class="estado estado-app-active">{_th("active")}</span>'


def detail_href(record: dict) -> str:
    return "/apps/detail?id=" + urlquote(str(record.get("client_id") or ""), safe="")


def _flash(error: str, notice: str) -> str:
    if error:
        return f'<p class="error" role="alert">{e(error)}</p>'
    if notice:
        return f'<p class="ok" role="status">{e(notice)}</p>'
    return ""


def list_body(records: list[dict], csrf: str = "", *, error: str = "", notice: str = "") -> str:
    """La lista (#742 §1). `csrf` ya no se usa aquí: las filas no tienen formularios."""
    ordered = sorted(records, key=lambda r: r.get("paired_at") or "", reverse=True)
    active = sum(1 for r in ordered if not r.get("revoked_at"))
    bar = (f'<div class="apps-barra"><p class="quiet resumen">{_th("count", n=len(ordered), m=active)}</p>'
           f'<p class="acciones"><a class="secundario" href="/apps/pair">{_th("pair_new")}</a></p></div>')
    if not ordered:
        return (f'{_flash(error, notice)}{bar}<p class="lead">{_th("empty")}</p>'
                f'<p class="quiet apps-nota">{_th("note")}</p>')
    rows = [f'<li class="correos-cabecera" aria-hidden="true"><span>{_th("name")}</span><span>{_th("app")}</span>'
            f'<span>{_th("paired")}</span><span>{_th("last_used")}</span><span>{_th("status")}</span><span></span></li>']
    for record in ordered:
        revoked = " app-revocada" if record.get("revoked_at") else ""
        rows.append(
            f'<li class="app-fila{revoked}"><a href="{detail_href(record)}">'
            f'<span class="quien">{e(record.get("name"))}<code class="app-id">{e(record.get("client_id"))}</code></span>'
            f'<span class="asunto app-cel">{_app(record)}</span>'
            f'<span class="cuando app-pareada">{_time(record.get("paired_at"), short=True)}</span>'
            f'<span class="cuando">{_time(record.get("last_used_at"), short=True)}</span>'
            f'<span class="estado-celda">{_state(record)}</span>{ROW_CHEVRON}</a></li>')
    return (f'{_flash(error, notice)}{bar}<ul class="correos apps">{"".join(rows)}</ul>'
            f'<p class="quiet apps-nota">{_th("note")}</p>')


def _password_form(action: str, csrf: str, button: str, button_class: str, extra: str = "") -> str:
    return (f'<form method="post" action="{action}" class="formulario-fila">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}">{extra}'
            f'<label>{_th("password")}<input type="password" name="password" required '
            f'autocomplete="current-password"></label>'
            f'<button class="{button_class}" type="submit">{button}</button></form>')


def _ago(stamp: str | None, now: dt.datetime) -> str:
    """«hace 12 minutos», «ayer», «hace 2 días»: texto plano, se escapa al usarlo."""
    moment = when.parse(stamp or "")
    if moment is None:
        return ""
    seconds = (now - moment).total_seconds()
    if seconds < 86400:
        return when.ago(seconds)
    days = int(seconds // 86400)
    return i18n.t("web.tokens.rel.day_ago") if days == 1 else i18n.t("web.tokens.rel.days_ago", n=days)


def _app_text(record: dict) -> str:
    name, version = record.get("app_name") or "", record.get("app_version") or ""
    return (name + (f" v{version}" if version else "")).strip() or "—"


def _row(label: str, value: str, small: str = "") -> str:
    note = f"<small>{small}</small>" if small else ""
    return f'<div class="tok-fila"><dt>{label}</dt><dd>{value}{note}</dd></div>'


def _when_row(key: str, stamp: str | None, now: dt.datetime) -> str:
    # Corta: de hoy sólo la hora, porque «hace …» ya va debajo.
    return _row(_th(key), _time(stamp, short=True), e(_ago(stamp, now)) if stamp else "")


def detail_body(record: dict, csrf: str, *, error: str = "", now: dt.datetime | None = None) -> str:
    """
    El detalle de una app (#769, mockup aprobado por Julian, Iris[Q74]=B), como el de un token
    (#760): la cabecera con el id, el estado y cuándo se revocó o se usó, «Details», y al final
    «Revocar esta app» (activa) o «Borrar esta app» (revocada). `error` ya viene escapado.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    revoked, last = record.get("revoked_at"), record.get("last_used_at")
    # La línea lleva un `<time>`: el texto del catálogo se escapa entero y luego entra la etiqueta.
    slot = "\x00when\x00"
    if revoked:
        line = e(i18n.t("web.apps.line_revoked", when=slot, rel=_ago(revoked, now))).replace(e(slot), _time(revoked, short=True))
    elif last:
        line = _th("line_used", app=_app_text(record), rel=_ago(last, now))
    else:
        line = _th("line_unused", app=_app_text(record))
    head = (f'<div class="tok-cabeza"><div><h2>{e(record.get("name"))}</h2>'
            f'<code class="tok-prefijo">{e(record.get("client_id"))}</code>'
            f'<span class="tok-vence">{line}</span></div>{_state(record)}</div>')
    details = (f'<section class="tok-tarjeta"><h3>{_th("sec_details")}</h3><dl>'
               + _row(_th("app"), _app(record))
               + _when_row("paired", record.get("paired_at"), now)
               + _when_row("last_used", last, now)
               + (_when_row("revoked_at", revoked, now) if revoked else "")
               + _row(_th("access"), _th("full"))
               + "</dl></section>")
    hidden = f'<input type="hidden" name="id" value="{e(record.get("client_id"))}">'
    if revoked:
        danger = (f'<section class="zona-peligro zona-borrar"><h2>{_th("delete_title")}</h2><p>{_th("delete_hint")}</p>'
                  f'{_password_form("/apps/delete", csrf, _th("delete"), "peligro", hidden)}</section>')
    else:
        danger = (f'<section class="zona-peligro"><h2>{_th("revoke_title")}</h2><p>{_th("revoke_hint")}</p>'
                  f'{_password_form("/apps/revoke", csrf, _th("revoke"), "peligro", hidden)}</section>')
    error_notice = f'<p class="error" role="alert">{error}</p>' if error else ""
    crumb = f'<p class="migas"><a href="/apps">← {_th("title")}</a></p>'
    return f'{crumb}{error_notice}<div class="tok">{head}{details}{danger}</div>'


def pair_body(csrf: str, *, error: str = "") -> str:
    """«Emparejar app» (#742 §3): pide la contraseña antes de generar el código."""
    return (f'{_flash(error, "")}<p class="app-detalle">{_th("pair_lead")}</p>'
            f'{_password_form("/apps/code", csrf, _th("code"), "primario")}')


def _copy_field(label: str, value: str, text: str) -> str:
    """Una fila con su etiqueta, el valor debajo y el icono de copiar a la derecha. Sin script el
    icono no se muestra (`hidden`) y el valor se puede seleccionar."""
    return (f'<div class="campo"><div><div class="campo-etq">{label}</div><div class="campo-val">{value}</div></div>'
            f'<button type="button" class="icono-copiar" hidden data-copiar="{e(text)}" aria-label="{_th("copy")}" '
            f'data-copied="{_th("copied")}">{COPY_ICON}<span class="tip" aria-hidden="true">{_th("copy")}</span></button></div>')


def code_body(base: str, code: str) -> str:
    """La dirección y el código (#742 §4), con iconos de copiar en lugar de botones."""
    minutes = owner_clients.CODE_TTL_S // 60
    # Sin barras invertidas dentro de las llaves de un f-string: es SyntaxError antes de Python 3.12 (PEP 701).
    base_html = f"<code>{e(base)}</code>"
    code_html = f'<code class="apps-code">{e(code)}</code>'
    expires = (f'<div class="campo"><div><div class="campo-etq">{_th("expires")}</div>'
               f'<div class="campo-val"><span class="apps-vence" data-segundos="{owner_clients.CODE_TTL_S}">'
               f'{_th("minutes", min=minutes)}</span></div></div></div>')
    return (f'<div class="codigo-caja">'
            f'{_copy_field(_th("address"), base_html, base)}'
            f'{_copy_field(_th("pair_code"), code_html, code)}'
            f'{expires}</div>'
            f'<p class="aviso-codigo">{_th("once")}</p>'
            f'<p class="acciones"><a class="secundario" href="/apps">{_th("done")}</a></p>'
            f'<script src="/assets/apps.js" defer></script>')
