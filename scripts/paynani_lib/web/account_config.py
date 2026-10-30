"""
«Configuración» de la cuenta principal en PaynaniWeb (#590 cambio 3): qué se muestra y
la puerta por la que se guarda.

Guardar es del núcleo (#591 N2 y N3): probar IMAP y SMTP con los datos combinados,
escribir juntos el `.env` y la cuenta `paynani` de Himalaya (que guarda su propia copia
del servidor, del puerto y del nombre), con respaldo y vuelta atrás, y reiniciar el
listener esperando su latido. Aquí está la interfaz que usa la pantalla (`Updater`),
la de la instalación (`CoreUpdater`, que se conecta cuando N2 entre a main) y un
`Fake` para las pruebas.

La contraseña del buzón nunca se muestra ni vuelve a la página: el campo está vacío y
vacío quiere decir «no cambia».
"""
from __future__ import annotations

FIELDS = (
    ("AGENT_EMAIL_ACCOUNT", "email"),
    ("AGENT_EMAIL_FROM_NAME", "from_name"),
    ("AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST", "imap_host"),
    ("AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT", "imap_port"),
    ("AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST", "smtp_host"),
    ("AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT", "smtp_port"),
)
PASSWORD_KEY = "AGENT_EMAIL_PASSWORD"
# Lo que se lee del .env con los nombres viejos o los de PAYNANI_*, como send.sh.
ALIASES = {
    "AGENT_EMAIL_ACCOUNT": ("PAYNANI_EMAIL",),
    "AGENT_EMAIL_FROM_NAME": ("PAYNANI_FROM_NAME",),
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST": ("PAYNANI_IMAP_HOST",),
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT": ("PAYNANI_IMAP_PORT",),
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST": ("PAYNANI_SMTP_HOST",),
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT": ("PAYNANI_SMTP_PORT",),
}


class Refused(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def current(env: dict) -> dict:
    """Los datos que se muestran, sin la contraseña: `{campo: valor}`."""
    out = {}
    for key, name in FIELDS:
        value = env.get(key, "")
        for alias in ALIASES.get(key, ()):
            value = value or env.get(alias, "")
        out[name] = str(value or "").strip()
    return out


def changes(before: dict, form: dict) -> dict:
    """Las claves del `.env` que cambian. La contraseña sólo si se escribió una nueva.
    Un salto de línea no se acepta en ningún campo: no puede agregar otra clave."""
    out = {}
    for key, name in FIELDS:
        value = str(form.get(name, "")).strip()
        if "\r" in value or "\n" in value:
            raise Refused("invalid", name)
        if value != before.get(name, ""):
            out[key] = value
    new_password = str(form.get("new_password", ""))
    if "\r" in new_password or "\n" in new_password:
        raise Refused("invalid", "new_password")
    if new_password:
        out[PASSWORD_KEY] = new_password
    return out


def shown(changed: dict) -> list[str]:
    """Para el aviso y la página: los nombres de lo que cambió, nunca la contraseña."""
    names = dict(FIELDS)
    return [names.get(k, "new_password") for k in changed]


class Updater:
    """La puerta del núcleo (#591 N2/N3). `update(changes, by)` devuelve un dict con
    `ok`, `code`, `changed` (nombres de claves), `probe` (pasos de IMAP y SMTP:
    `{"imap": [...], "smtp": [...]}`, cada paso `{ok, text, detail}`), `restart`
    (`back`, `timeout` o `skipped`) y `detail`, sin valores ni secretos."""

    def update(self, changes: dict, *, by: str) -> dict:
        raise Refused("not_available")


class CoreUpdater(Updater):
    """La de la instalación. Se conecta a la función de N2 (#591) cuando entre a main;
    mientras tanto no escribe nada y la pantalla lo dice."""


class Fake(Updater):
    """En memoria, para las pruebas: guarda lo que se le pidió y responde lo que se le diga."""

    def __init__(self, result: dict | None = None):
        self.calls: list[tuple[dict, str]] = []
        self.result = result

    def update(self, changes, *, by):
        self.calls.append((dict(changes), by))
        if self.result is not None:
            return dict(self.result, changed=list(changes))
        return {"ok": True, "code": "saved", "changed": list(changes),
                "probe": {"imap": [{"ok": True, "text": "IMAP login", "detail": ""}],
                          "smtp": [{"ok": True, "text": "SMTP login", "detail": ""}]},
                "restart": "back", "detail": ""}
