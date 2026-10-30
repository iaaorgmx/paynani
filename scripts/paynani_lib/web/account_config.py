"""
«Configuración» de la cuenta principal en PaynaniWeb (#590 cambio 3): qué se muestra y
la puerta por la que se guarda.

Guardar es del núcleo (#591 N2, `paynani_lib.main_account.update`): prueba IMAP y SMTP
con los datos combinados, escribe juntos el `.env` y la cuenta `paynani` de Himalaya,
reinicia el listener con N3 y deshace todo si no vuelve. Aquí está la interfaz que usa
la pantalla (`Updater`), la de la instalación (`CoreUpdater`) y un `Fake` para las
pruebas.

Los nombres de los campos son los del núcleo (`envfile.ENV_FIELDS`, que es
`main_account.FIELDS`): la web no tiene otra lista. La contraseña del buzón nunca se
muestra ni vuelve a la página: el campo está vacío y vacío quiere decir «no cambia».
"""
from __future__ import annotations

from .. import envfile

PASSWORD_KEY = "AGENT_EMAIL_PASSWORD"
# Los que se muestran y se pueden cambiar en el formulario, en el orden del núcleo.
SHOWN = [k for k in envfile.ENV_FIELDS if k != PASSWORD_KEY]


class Refused(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def current(env: dict) -> dict:
    """Los datos que se muestran, sin la contraseña: `{clave: valor}`."""
    return {k: str(env.get(k, "") or "").strip() for k in SHOWN}


def changes(before: dict, form: dict) -> dict:
    """Las claves del `.env` que cambian. La contraseña sólo si se escribió una nueva.
    Un salto de línea no se acepta en ningún campo: no puede agregar otra clave."""
    out = {}
    for key in SHOWN:
        value = str(form.get(key, "")).strip()
        if "\r" in value or "\n" in value:
            raise Refused("invalid", key)
        if value != before.get(key, ""):
            out[key] = value
    new_password = str(form.get("new_password", ""))
    if "\r" in new_password or "\n" in new_password:
        raise Refused("invalid", "new_password")
    if new_password:
        out[PASSWORD_KEY] = new_password
    return out


class Updater:
    """La puerta del núcleo (#591 N2). `update(changes, by)` devuelve un dict como el
    `Result` de N2: `ok`, `code`, `changed` (nombres de claves), `field_errors`,
    `probe` (pasos `{protocol, ok, text, detail}`), `ready`, `rollback` y `detail`, sin
    valores ni secretos."""

    def update(self, changes: dict, *, by: str) -> dict:
        raise Refused("not_available")


class CoreUpdater(Updater):
    """La de la instalación: `paynani_lib.main_account.update` (#591 N2). Mientras N2 no
    esté en main no escribe nada, y la pantalla dice que todavía no se puede."""

    def update(self, changes, *, by):
        try:
            from .. import main_account
        except ImportError:
            raise Refused("not_available") from None
        res = main_account.update(changes, by=by)
        return {"ok": bool(res.ok), "code": str(res.code), "changed": list(res.changed or []),
                "field_errors": dict(res.field_errors or {}), "probe": list(res.probe or []),
                "ready": str(res.ready or ""), "rollback": str(res.rollback or "none"),
                "recovered": bool(getattr(res, "recovered", False)), "detail": str(res.detail or "")}


class Fake(Updater):
    """En memoria, para las pruebas: guarda lo que se le pidió y responde lo que se le diga."""

    def __init__(self, result: dict | None = None):
        self.calls: list[tuple[dict, str]] = []
        self.result = result

    def update(self, changes, *, by):
        self.calls.append((dict(changes), by))
        if self.result is not None:
            return dict({"changed": list(changes), "field_errors": {}, "probe": [], "ready": "",
                         "rollback": "none", "detail": ""}, **self.result)
        return {"ok": True, "code": "updated", "changed": list(changes), "field_errors": {},
                "probe": [{"protocol": "imap", "ok": True, "text": "IMAP login", "detail": ""},
                          {"protocol": "smtp", "ok": True, "text": "SMTP login", "detail": ""}],
                "ready": "connected", "rollback": "none", "detail": ""}
