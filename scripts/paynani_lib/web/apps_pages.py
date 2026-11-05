"""
«Apps conectadas» (PaynaniWebMT#2 FR-A3): los clientes web del dueño, como PaynaniWebMT.

- `/apps` lista cada cliente con su app, cuándo se emparejó, su último uso y su estado.
- «Generar código» (POST `/apps/code`) da la dirección del túnel y un código de un solo
  uso, como `scripts/paynani web pair`. Pide la contraseña de PaynaniWeb: el código abre
  la administración completa de la instalación.
- «Revocar» (POST `/apps/revoke`) también pide la contraseña.

Todo lo que se pone en el HTML pasa por `e()`.
"""
from __future__ import annotations

import html

from .. import i18n
from ..i18n_data import CATALOGUES
from . import owner_clients

WORDS = {
    "es-MX": ["Apps conectadas", "Apps como PaynaniWebMT que administran esta instalación a distancia, con la dirección del túnel y un código de emparejamiento. No ocupan el lugar del teléfono.", "Todavía no hay apps conectadas.", "Nombre", "App", "Emparejada", "Último uso", "Estado", "Activa", "Revocada", "Nunca", "Generar código", "Contraseña de PaynaniWeb", "Revocar", "Dirección del gateway", "Código de emparejamiento", "Escribe los dos en la app, en «Conectar paynani». El código sirve una sola vez y vence en {min} minutos. No se lo des a nadie más: abre la administración completa de tu paynani.", "Falta la dirección pública (PAYNANI_SMS_PUBLIC_URL en sms.env).", "App revocada: su token ya no abre la API.", "No existe esa app o ya estaba revocada.", "Volver a la lista"],
    "en-US": ["Connected apps", "Apps such as PaynaniWebMT that manage this install remotely, with the tunnel address and a pairing code. They do not take the phone's place.", "No apps are connected yet.", "Name", "App", "Paired", "Last used", "Status", "Active", "Revoked", "Never", "Generate code", "PaynaniWeb password", "Revoke", "Gateway address", "Pairing code", "Type both in the app, under “Connect paynani”. The code works once and expires in {min} minutes. Do not give it to anyone else: it opens full control of your paynani.", "The public address is missing (PAYNANI_SMS_PUBLIC_URL in sms.env).", "App revoked: its token no longer opens the API.", "That app does not exist or was already revoked.", "Back to the list"],
    "es-ES": ["Apps conectadas", "Apps como PaynaniWebMT que administran esta instalación a distancia, con la dirección del túnel y un código de emparejamiento. No ocupan el lugar del teléfono.", "Todavía no hay apps conectadas.", "Nombre", "App", "Emparejada", "Último uso", "Estado", "Activa", "Revocada", "Nunca", "Generar código", "Contraseña de PaynaniWeb", "Revocar", "Dirección del gateway", "Código de emparejamiento", "Escribe los dos en la app, en «Conectar paynani». El código sirve una sola vez y caduca en {min} minutos. No se lo des a nadie más: abre la administración completa de tu paynani.", "Falta la dirección pública (PAYNANI_SMS_PUBLIC_URL en sms.env).", "App revocada: su token ya no abre la API.", "Esa app no existe o ya estaba revocada.", "Volver a la lista"],
    "fr-FR": ["Apps connectées", "Des apps comme PaynaniWebMT qui gèrent cette installation à distance, avec l’adresse du tunnel et un code d’appairage. Elles ne prennent pas la place du téléphone.", "Aucune app connectée pour l’instant.", "Nom", "App", "Appairée", "Dernière utilisation", "Statut", "Active", "Révoquée", "Jamais", "Générer un code", "Mot de passe PaynaniWeb", "Révoquer", "Adresse de la passerelle", "Code d’appairage", "Saisissez les deux dans l’app, sous « Connecter paynani ». Le code ne sert qu’une fois et expire dans {min} minutes. Ne le donnez à personne d’autre : il ouvre le contrôle complet de votre paynani.", "L’adresse publique manque (PAYNANI_SMS_PUBLIC_URL dans sms.env).", "App révoquée : son jeton n’ouvre plus l’API.", "Cette app n’existe pas ou était déjà révoquée.", "Retour à la liste"],
    "pt-BR": ["Apps conectados", "Apps como o PaynaniWebMT que administram esta instalação à distância, com o endereço do túnel e um código de pareamento. Eles não ocupam o lugar do telefone.", "Ainda não há apps conectados.", "Nome", "App", "Pareado", "Último uso", "Status", "Ativo", "Revogado", "Nunca", "Gerar código", "Senha do PaynaniWeb", "Revogar", "Endereço do gateway", "Código de pareamento", "Digite os dois no app, em “Conectar paynani”. O código vale uma única vez e expira em {min} minutos. Não o dê a mais ninguém: ele abre o controle completo do seu paynani.", "Falta o endereço público (PAYNANI_SMS_PUBLIC_URL em sms.env).", "App revogado: o token dele não abre mais a API.", "Esse app não existe ou já estava revogado.", "Voltar à lista"],
}
KEYS = ["title", "lead", "empty", "name", "app", "paired", "last_used", "status", "active", "revoked", "never",
        "code", "password", "revoke", "address", "pair_code", "pair_hint", "no_url", "revoked_ok", "missing", "back"]
for _language, _words in WORDS.items():
    assert len(KEYS) == len(_words)
    CATALOGUES[_language].update({"web.apps." + key: value for key, value in zip(KEYS, _words)})


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _th(key: str, **kw) -> str:
    return i18n.th("web.apps." + key, **kw)


def _password(csrf: str, label: str) -> str:
    return (f'<input type="hidden" name="csrf" value="{e(csrf)}">'
            f'<label>{_th("password")} <input type="password" name="password" required '
            f'autocomplete="current-password"></label> <button type="submit">{label}</button>')


def list_body(records: list[dict], csrf: str, *, error: str = "", notice: str = "") -> str:
    rows = []
    for record in sorted(records, key=lambda r: r.get("paired_at") or "", reverse=True):
        revoked = bool(record.get("revoked_at"))
        app = " ".join(part for part in (record.get("app_name"), record.get("app_version")) if part) or "—"
        action = "" if revoked else (
            f'<form method="post" action="/apps/revoke" class="apps-revocar">'
            f'<input type="hidden" name="id" value="{e(record.get("client_id"))}">'
            f'{_password(csrf, _th("revoke"))}</form>')
        rows.append(
            f'<tr><td>{e(record.get("name"))}<br><code>{e(record.get("client_id"))}</code></td><td>{e(app)}</td>'
            f'<td><time datetime="{e(record.get("paired_at"))}">{e(record.get("paired_at"))}</time></td>'
            f'<td>{e(record.get("last_used_at") or _th("never"))}</td>'
            f'<td>{_th("revoked") if revoked else _th("active")}</td><td>{action}</td></tr>')
    table = (f'<table class="token-table"><thead><tr><th>{_th("name")}</th><th>{_th("app")}</th>'
             f'<th>{_th("paired")}</th><th>{_th("last_used")}</th><th>{_th("status")}</th><th></th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>') if rows else f'<p>{_th("empty")}</p>'
    flash = (f'<p class="error" role="alert">{e(error)}</p>' if error else
             f'<p class="ok" role="status">{e(notice)}</p>' if notice else "")
    return (f'{flash}<p>{_th("lead")}</p>'
            f'<form method="post" action="/apps/code" class="apps-codigo">{_password(csrf, _th("code"))}</form>'
            f'{table}')


def code_body(base: str, code: str) -> str:
    return (f'<dl class="apps-par"><dt>{_th("address")}</dt><dd><code>{e(base)}</code></dd>'
            f'<dt>{_th("pair_code")}</dt><dd><code class="apps-code">{e(code)}</code></dd></dl>'
            f'<p>{_th("pair_hint", min=owner_clients.CODE_TTL_S // 60)}</p>'
            f'<p><a href="/apps">{_th("back")}</a></p>')
