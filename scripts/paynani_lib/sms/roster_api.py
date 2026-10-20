"""
La pantalla «Roster» de PaynaniApp del lado de la pasarela (R2 de #410,
SMS_GATEWAY.md §11): `roster.accounts`, `roster.list`, `roster.save` y
`roster.delete`.

Sólo llega aquí lo que manda el teléfono emparejado por su WebSocket autenticado
(gateway._dispatch). Un SMS o un correo no tiene camino hasta este módulo: lo que
dicen nunca cambia un roster (Q5).

El trabajo con el archivo está en roster_edit.py. Aquí van el protocolo (el `id`
de cada pedido, el reenvío seguro, `result`/`error`), el log de cambios y el correo
al humano.
"""
from __future__ import annotations

import calendar
import collections
import hashlib
import json
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from paynani_lib import roster_edit  # noqa: E402
from paynani_lib import rules as rules_mod  # noqa: E402
from paynani_lib.roster_edit import EditError  # noqa: E402

TYPES = ("roster.accounts", "roster.list", "roster.save", "roster.delete",
         "rules.get", "rules.preview", "rules.save", "rules.get_default", "rules.save_default")
WRITES = {"roster.save", "roster.delete", "rules.save", "rules.save_default"}
ID_RE = re.compile(r"^q_[0-9a-f]{32}$")
ACCOUNT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
REPLAY_MAX = 64
REPLAY_TTL_S = 600
CHANGES_LOG = "roster_changes.jsonl"
# Los errores que se guardan para el reenvío: los que darían lo mismo otra vez. Uno
# pasajero (`write_failed` porque el bloqueo no llegó, `unreadable`) no: el reenvío
# del mismo `id` lo vuelve a intentar.
FINAL_ERRORS = {"invalid", "conflict", "not_found", "owner_row", "missing_field"}
# Un cambio sin la línea de su aviso después de esto cuenta como no avisado
# (el proceso pudo morir antes de mandarlo).
NOTIFY_GRACE_S = 300
NOTIFY_WINDOW_S = 24 * 3600


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _digest(msg: dict) -> str:
    """El SHA-256 del pedido sin su `id`, para reconocer un `id` reutilizado."""
    body = {k: v for k, v in msg.items() if k != "id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def send_sh_notifier(to: str, subject: str, body: str) -> None:
    """El correo al humano con scripts/send.sh, que lo vuelve a comprobar contra roster.md."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
        fh.write(body)
        path = fh.name
    try:
        subprocess.run(["bash", str(_REPO_ROOT / "scripts" / "send.sh"), to, subject, path],
                       capture_output=True, text=True, timeout=120, check=True)
    finally:
        Path(path).unlink(missing_ok=True)


class RosterService:
    """
    `agent_roster` es el roster.md de la cuenta del agente; `accounts_file`, el
    accounts.json de la instalación (None: sin cuentas adicionales). `notifier(to,
    subject, body)` manda el correo al humano; None no manda nada (las pruebas).
    """

    def __init__(self, agent_roster: Path, state_dir: Path, *, accounts_file: Path | None = None,
                 agent_email: str = "", notifier=None, template: Path = roster_edit.TEMPLATE,
                 log=None, rules_root: Path | None = None):
        self.agent_roster = Path(agent_roster)
        self.state_dir = Path(state_dir)
        self.accounts_file = Path(accounts_file) if accounts_file else None
        self.agent_email = agent_email
        self.notifier = notifier
        self.template = template
        # La carpeta de la instalación donde vive rules/ (el clon, junto a roster.md).
        self.rules_root = rules_root
        self.log = log or (lambda line: None)
        self.replays: collections.OrderedDict = collections.OrderedDict()
        self.lock = threading.Lock()
        self.notify_threads: list[threading.Thread] = []

    # --- cuentas -----------------------------------------------------------
    def _additional(self) -> list[dict]:
        if self.accounts_file is None or not self.accounts_file.exists():
            return []
        from paynani_lib import accounts

        try:
            return accounts.load(self.accounts_file)
        except accounts.AccountsError as exc:
            raise EditError("unreadable", field="account", detail=f"accounts.json: {exc}") from exc

    def _target(self, account) -> tuple[Path, str, str]:
        """`(ruta, ruta para mostrar, correo)` de `account` (None = la cuenta del agente)."""
        if account is None:
            return self.agent_roster, self.agent_roster.name, self.agent_email
        if not isinstance(account, str) or not ACCOUNT_RE.match(account):
            raise EditError("not_found", field="account", detail="account no es un id válido")
        from paynani_lib import accounts

        for item in self._additional():
            if item["id"] == account:
                return accounts.roster_path(item, self.accounts_file), item["roster"], item["email"]
        raise EditError("not_found", field="account", detail=f"no hay cuenta {account!r}")

    def _read(self, path: Path) -> tuple[bytes | None, str]:
        """`(bytes, texto)`; un archivo que falta se lee como la plantilla y da `etag` ""."""
        try:
            data = roster_edit.read_bytes(path)
            text = data.decode("utf-8") if data is not None else self.template.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise EditError("unreadable", detail=str(exc)) from exc
        return data, text

    def _listing(self, path: Path, account, data, text) -> dict:
        cols, rows = roster_edit.members(text)
        for m in rows:
            m.update(self._rules_flags(m["rules"]))
        out = {"account": account, "etag": roster_edit.etag_of(data), "columns": cols, "members": rows}
        out.update(self._listing_extra())
        return out

    def _rules_path(self, rules_id: str) -> Path:
        return rules_mod.path_for(rules_id, self.rules_root)

    def _rules_text(self, rules_id) -> str | None:
        """El archivo de reglas como texto, o None si no hay id o no existe."""
        if not rules_id:
            return None
        try:
            data = roster_edit.read_bytes(self._rules_path(rules_id))
        except EditError:
            return None
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EditError("unreadable", detail=f"rules/{rules_id}.md: {exc}") from exc

    def _rules_flags(self, rules_id) -> dict:
        """`has_rules` (existe rules/<id>.md) y `rules_enabled` (además es válido y está activo)."""
        try:
            text = self._rules_text(rules_id)
        except EditError:
            return {"has_rules": True, "rules_enabled": False}
        return {"has_rules": text is not None, "rules_enabled": rules_mod._active(text) is not None}

    def _listing_extra(self) -> dict:
        return {"default_rules": self._rules_path(rules_mod.DEFAULT_ID).exists()}

    # --- mensajes ----------------------------------------------------------
    def roster_accounts(self, msg: dict, device_id: str) -> dict:
        targets = [(None, self.agent_roster, self.agent_roster.name, self.agent_email)]
        from paynani_lib import accounts

        for item in self._additional():
            targets.append((item["id"], accounts.roster_path(item, self.accounts_file), item["roster"],
                            item["email"]))
        out = []
        for account, path, shown, email in targets:
            entry = {"account": account, "email": email, "roster": shown, "members": 0}
            try:
                data = roster_edit.read_bytes(path)
                if data is None:
                    entry["status"] = "missing"
                else:
                    entry["members"] = len(roster_edit.members(data.decode("utf-8"))[1])
                    entry["status"] = "ok"
            except (OSError, UnicodeDecodeError):
                entry["status"] = "unreadable"
            out.append(entry)
        return {"accounts": out}

    def roster_list(self, msg: dict, device_id: str) -> dict:
        account = msg.get("account")
        path, _, _ = self._target(account)
        data, text = self._read(path)
        return self._listing(path, account, data, text)

    def roster_save(self, msg: dict, device_id: str) -> dict:
        account = msg.get("account")
        path, shown, _ = self._target(account)
        row = msg.get("row")
        if row is not None and (not isinstance(row, int) or isinstance(row, bool)):
            raise EditError("invalid", field="row", reason="row", detail="row es un número o null")
        member = msg.get("member")
        if not isinstance(member, dict):
            raise EditError("missing_field", field="member", detail="falta member")
        before: dict = {}

        def transform(text):
            nonlocal before
            if row is not None:
                _, current = roster_edit.members(text)
                if 1 <= row <= len(current):
                    before = current[row - 1]
            new_text, saved_row, clean = roster_edit.save_text(text, row, member)
            return new_text, {"row": saved_row, "member": clean}

        done = roster_edit.apply(path, msg.get("etag"), transform, state_dir=self.state_dir,
                                 label=self._label(account), template=self.template)
        info = done["info"]
        action = "add" if row is None else "edit"
        changed = sorted(k for k in ("name", "email", "type", "github", "phones")
                         if before.get(k) != info["member"][k]) if before else []
        self._changed(device_id, msg["type"], account, shown, info["row"], info["member"]["name"],
                      done, action=action, fields=changed, member=info["member"], before=before)
        listing = self._listing(path, account, roster_edit.read_bytes(path), done["text"])
        return {"row": info["row"], **listing}

    def roster_delete(self, msg: dict, device_id: str) -> dict:
        account = msg.get("account")
        path, shown, _ = self._target(account)
        row = msg.get("row")

        def transform(text):
            new_text, gone = roster_edit.delete_text(text, row)
            return new_text, {"member": gone}

        done = roster_edit.apply(path, msg.get("etag"), transform, state_dir=self.state_dir,
                                 label=self._label(account), template=self.template)
        gone = done["info"]["member"]
        self._after_delete(gone)
        self._changed(device_id, msg["type"], account, shown, row, gone["name"], done, action="delete",
                      member=gone)
        return self._listing(path, account, roster_edit.read_bytes(path), done["text"])

    def _after_delete(self, gone: dict) -> None:
        """
        Las reglas del contacto que se fue no se borran: `rules/<id>.md` pasa a
        `rules/<id>.removed-<fecha>.md`, salvo que otra fila, de cualquier roster,
        tenga el mismo `Rules` (una edición a mano).
        """
        rules_id = gone.get("rules")
        if not rules_id or rules_id in self._all_rules_ids():
            return
        try:
            path = self._rules_path(rules_id)
        except EditError:
            return
        if not path.exists():
            return
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        with roster_edit.locked(path, self.state_dir):
            if path.exists():
                path.rename(path.with_name(rules_mod.removed_name(rules_id, stamp)))
        self.log(f"roster: las reglas {rules_id} pasaron a {rules_mod.removed_name(rules_id, stamp)}")

    def _all_rules_ids(self) -> set:
        """Los `Rules` de todas las filas de todos los rosters de la instalación."""
        ids = set()
        targets = [self.agent_roster]
        from paynani_lib import accounts

        try:
            targets += [accounts.roster_path(a, self.accounts_file) for a in self._additional()]
        except EditError:
            pass
        for path in targets:
            try:
                data = roster_edit.read_bytes(path)
            except OSError:
                continue
            if data is not None:
                ids |= {m["rules"] for m in roster_edit.members(data.decode("utf-8", "replace"))[1] if m["rules"]}
        return ids

    # --- reglas ------------------------------------------------------------
    def _member_at(self, msg: dict) -> tuple[Path, str, bytes | None, str, dict]:
        """`(ruta, ruta para mostrar, bytes, texto, contacto)` de la fila, con `roster_etag` comprobado."""
        account = msg.get("account")
        path, shown, _ = self._target(account)
        data, text = self._read(path)
        expected = msg.get("roster_etag")
        if not isinstance(expected, str):
            raise EditError("missing_field", field="roster_etag", detail="falta roster_etag")
        if expected != roster_edit.etag_of(data):
            raise EditError("conflict", field="roster_etag", detail="el roster cambió",
                            etag=roster_edit.etag_of(data))
        row = msg.get("row")
        _, current = roster_edit.members(text)
        if not isinstance(row, int) or isinstance(row, bool) or not 1 <= row <= len(current):
            raise EditError("not_found", field="row", detail=f"no hay fila {row!r}")
        return path, shown, data, text, current[row - 1]

    def _default_text(self) -> str | None:
        return self._rules_text(rules_mod.DEFAULT_ID)

    def _rules_reply(self, member: dict, contact_text: str | None) -> dict:
        return {"row": member["row"], "name": member["name"], "email": member["email"]}

    def rules_get(self, msg: dict, device_id: str) -> dict:
        _, _, _, _, member = self._member_at(msg)
        text = self._rules_text(member["rules"])
        return {**self._rules_reply(member, text), "rules": member["rules"], "exists": text is not None,
                "etag": roster_edit.etag_of(text.encode("utf-8")) if text is not None else "",
                "text": text or "", "effective": rules_mod.effective(self._default_text(), text)}

    def rules_preview(self, msg: dict, device_id: str) -> dict:
        _, _, _, _, member = self._member_at(msg)
        text = msg.get("text")
        rules_mod.parse(text)
        return {**self._rules_reply(member, text),
                "effective": rules_mod.effective(self._default_text(), text)}

    def _rendered(self, text, device_id: str) -> tuple[str, dict]:
        parsed = rules_mod.parse(text)
        return rules_mod.render(parsed, updated_at=_now_iso(), updated_by=f"phone {device_id}"), parsed

    def rules_save(self, msg: dict, device_id: str) -> dict:
        new_text, parsed = self._rendered(msg.get("text"), device_id)
        account = msg.get("account")
        path, shown, data, text, member = self._member_at(msg)
        roster_etag = roster_edit.etag_of(data)
        rules_id = member["rules"]
        if not rules_id:
            # La primera vez: un id nuevo en la columna Rules de esa fila (I-1), con el
            # mismo paso único del roster, que vuelve a comprobar roster_etag.
            # `taken` incluye los archivos que ya hay en rules/ (también los .removed-…): un
            # archivo huérfano con el mismo id no puede volverse del contacto nuevo (#421).
            on_disk = {f.name.split(".", 1)[0] for f in rules_mod.rules_dir(self.rules_root).glob("*.md")}
            rules_id = rules_mod.new_id(member["name"], self._all_rules_ids() | on_disk)
            row = member["row"]
            done = roster_edit.apply(path, msg["roster_etag"],
                                     lambda t: (roster_edit.set_rules_text(t, row, rules_id), {}),
                                     state_dir=self.state_dir, label=self._label(account), template=self.template)
            roster_etag = done["etag"]
        target = self._rules_path(rules_id)
        done = roster_edit.apply_file(target, msg.get("etag"), new_text, state_dir=self.state_dir,
                                      label=f"rules__{rules_id}")
        self._changed(device_id, msg["type"], account, shown, member["row"], member["name"], done,
                      action="rules", rules=self._rules_summary(rules_id, parsed, new_text))
        return {"rules": rules_id, "etag": done["etag"], "roster_etag": roster_etag,
                "effective": rules_mod.effective(self._default_text(), new_text)}

    def rules_get_default(self, msg: dict, device_id: str) -> dict:
        text = self._default_text()
        return {"rules": rules_mod.DEFAULT_ID, "exists": text is not None,
                "etag": roster_edit.etag_of(text.encode("utf-8")) if text is not None else "",
                "text": text or "", "effective": rules_mod.effective(text, None)}

    def rules_save_default(self, msg: dict, device_id: str) -> dict:
        new_text, parsed = self._rendered(msg.get("text"), device_id)
        target = self._rules_path(rules_mod.DEFAULT_ID)
        done = roster_edit.apply_file(target, msg.get("etag"), new_text, state_dir=self.state_dir,
                                      label="rules__default")
        self._changed(device_id, msg["type"], None, "rules/default.md", None, "reglas generales", done,
                      action="rules_default", rules=self._rules_summary(rules_mod.DEFAULT_ID, parsed, new_text))
        return {"rules": rules_mod.DEFAULT_ID, "etag": done["etag"], "effective": rules_mod.effective(new_text, None)}

    @staticmethod
    def _rules_summary(rules_id: str, parsed: dict, text: str) -> dict:
        """Lo que va al log y al correo de un cambio de reglas: nunca el texto (§11)."""
        return {"file": f"rules/{rules_id}.md", "enabled": parsed["enabled"],
                "reply": {c: parsed["reply"][c] for c in sorted(parsed["reply_set"])},
                "bytes": len(text.encode("utf-8"))}

    @staticmethod
    def _label(account) -> str:
        return "roster" if account is None else f"rosters__{account}"

    # --- log y aviso -------------------------------------------------------
    def _changed(self, device_id, kind, account, shown, row, name, done, *, action, fields=(),
                 member=None, before=None, rules=None) -> None:
        # `change` y no el etag: dos cambios pueden dejar el mismo archivo (una alta y su baja).
        entry = {"at": _now_iso(), "change": "c_" + secrets.token_hex(8), "device_id": device_id,
                 "type": kind, "action": action,
                 "account": account, "roster": shown, "row": row, "name": name, "fields": list(fields),
                 "etag_before": done["etag_before"], "etag_after": done["etag"], "backup": done["backup"]}
        if rules is not None:
            entry["rules"] = rules
        self._append(entry)
        self.log(f"roster: {action} fila {row} de {shown} desde {device_id}")
        self._notify(entry, member or {}, before or {})

    def _append(self, entry: dict) -> None:
        path = self.state_dir / CHANGES_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _notified(self, entry: dict, ok: bool, error: str = "") -> None:
        """
        El resultado del correo al dueño, como otra línea del log de cambios. El aviso
        es lo único que mitiga el riesgo aceptado en Q6 (un teléfono perdido puede
        cambiar el roster): uno que no sale no puede quedar en silencio, y
        `healthcheck.py` lo advierte con `unnotified()`.
        """
        line = {"at": _now_iso(), "type": "notify", "for": entry["change"], "roster": entry["roster"],
                "notified": ok}
        if error:
            line["error"] = error
        self._append(line)

    def owner_email(self) -> str:
        """El correo del dueño: el primer `Human` con correo del roster del agente."""
        try:
            _, text = self._read(self.agent_roster)
        except EditError:
            return ""
        for m in roster_edit.members(text)[1]:
            if m["type"] == "Human" and m["email"]:
                return m["email"]
        return ""

    def _notify(self, entry: dict, member: dict, before: dict) -> None:
        if self.notifier is None:
            return
        to = self.owner_email()
        if not to:
            self.log("roster: no hay dueño con correo en roster.md; el cambio no se avisó")
            self._notified(entry, False, "no_owner_email")
            return
        subject, body = notice(entry, member, before)
        notifier = self.notifier

        def run():
            try:
                notifier(to, subject, body)
            except Exception as exc:  # noqa: BLE001 -- el cambio ya está escrito y en el log
                self.log(f"roster: no se pudo mandar el aviso del cambio ({type(exc).__name__})")
                self._notified(entry, False, type(exc).__name__)
            else:
                self._notified(entry, True)

        thread = threading.Thread(target=run, daemon=True)
        self.notify_threads.append(thread)
        thread.start()

    # --- el pedido completo ------------------------------------------------
    def handle(self, msg: dict, device_id: str) -> dict:
        """El frame de respuesta (`result` o `error`) para un pedido de §11."""
        rid = msg.get("id")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            return {"type": "error", "code": "missing_field", "ref": str(rid or "")[:80], "field": "id",
                    "detail": "id es q_ y 32 hex"}
        kind = msg.get("type")
        digest = _digest(msg)
        if kind in WRITES:
            with self.lock:
                self._expire()
                seen = self.replays.get(rid)
            if seen is not None:
                if seen[0] != digest:
                    return {"type": "error", "code": "invalid", "ref": rid, "field": "id", "reason": "id_reused",
                            "detail": "ese id ya se usó con otro pedido"}
                return {**seen[1], "replayed": True}
        handler = {"roster.accounts": self.roster_accounts, "roster.list": self.roster_list,
                   "roster.save": self.roster_save, "roster.delete": self.roster_delete,
                   "rules.get": self.rules_get, "rules.preview": self.rules_preview,
                   "rules.save": self.rules_save, "rules.get_default": self.rules_get_default,
                   "rules.save_default": self.rules_save_default}[kind]
        try:
            response = {"type": "result", "ref": rid, "ok": True, "data": handler(msg, device_id)}
        except EditError as exc:
            response = {"type": "error", "ref": rid, **exc.as_error()}
        except Exception as exc:  # noqa: BLE001 -- nunca se cae la conexión por un pedido
            self.log(f"roster: {kind} falló ({type(exc).__name__})")
            response = {"type": "error", "code": "write_failed" if kind in WRITES else "unreadable",
                        "ref": rid, "detail": type(exc).__name__}
        if kind in WRITES and (response["type"] == "result" or response.get("code") in FINAL_ERRORS):
            with self.lock:
                self.replays[rid] = (digest, response, time.monotonic())
                while len(self.replays) > REPLAY_MAX:
                    self.replays.popitem(last=False)
        return response

    def _expire(self) -> None:
        cutoff = time.monotonic() - REPLAY_TTL_S
        for rid in [r for r, (_, _, at) in self.replays.items() if at < cutoff]:
            del self.replays[rid]


def unnotified(state_dir: Path, *, now: float | None = None, window_s: int = NOTIFY_WINDOW_S,
               grace_s: int = NOTIFY_GRACE_S) -> dict:
    """
    Los cambios desde la app de las últimas `window_s` que no tienen un aviso al dueño
    que salió: `{"count", "errors"}`. Uno sin línea de aviso cuenta después de
    `grace_s` (el correo tarda, o el proceso murió antes de mandarlo). Para
    `healthcheck.py`.
    """
    now = time.time() if now is None else now
    path = Path(state_dir) / CHANGES_LOG
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"count": 0, "errors": []}
    changes, results = [], {}
    for line in lines:
        try:
            item = json.loads(line)
            at = calendar.timegm(time.strptime(item["at"], "%Y-%m-%dT%H:%M:%SZ"))
        except (ValueError, KeyError, TypeError):
            continue
        if item.get("type") == "notify":
            if item.get("notified") or item.get("for") not in results:
                results[item.get("for")] = item
        elif "action" in item and now - at <= window_s:
            changes.append((at, item))
    count, errors = 0, []
    for at, item in changes:
        result = results.get(item.get("change"))
        if result is None:
            if now - at < grace_s:
                continue
            reason = "no_notice"
        elif result.get("notified"):
            continue
        else:
            reason = result.get("error") or "failed"
        count += 1
        if reason not in errors:
            errors.append(reason)
    return {"count": count, "errors": errors}


def notice(entry: dict, member: dict, before: dict) -> tuple[str, str]:
    """El asunto y el cuerpo del correo al humano: qué cambió y desde qué teléfono (Q5)."""
    if entry["action"] in ("rules", "rules_default"):
        info = entry["rules"]
        whose = "las reglas generales" if entry["action"] == "rules_default" else \
            f"las instrucciones de «{entry['name']}» ({entry['roster']}, fila {entry['row']})"
        reply = ", ".join(f"{c}: {v}" for c, v in info["reply"].items()) or "la de las reglas generales"
        lines = [f"Desde el teléfono {entry['device_id']}, a las {entry['at']}:", "",
                 f"Cambiaron {whose}, en {info['file']}.", "",
                 f"  Activas: {'sí' if info['enabled'] else 'no'}", f"  Respuesta: {reply}",
                 f"  Tamaño: {info['bytes']:,} bytes", "",
                 f"Copia anterior: {entry['backup'] or '(el archivo no existía)'}", "",
                 "El texto no va en este correo: está en ese archivo de la instalación.",
                 "Si no fuiste tú, revisa el archivo y revoca el teléfono con `paynani sms revoke`."]
        return f"paynani: cambio de reglas en {info['file']} desde PaynaniApp", "\n".join(lines) + "\n"
    what = {"add": "alta", "edit": "edición", "delete": "baja"}[entry["action"]]
    subject = f"paynani: {what} en {entry['roster']} desde PaynaniApp"
    lines = [f"Desde el teléfono {entry['device_id']}, a las {entry['at']}:", "",
             f"{what.capitalize()} de «{entry['name']}» en {entry['roster']} (fila {entry['row']}).", ""]

    def show(m):
        return [f"  Nombre: {m.get('name', '')}", f"  Correo: {m.get('email', '') or '—'}",
                f"  Tipo:   {m.get('type', '') or '—'}", f"  GitHub: {m.get('github', '') or '—'}",
                f"  Teléfonos: {', '.join(m.get('phones') or []) or '—'}"]

    if entry["action"] == "edit":
        lines += ["Antes:"] + show(before) + ["", "Ahora:"] + show(member)
        if entry["fields"]:
            lines += ["", f"Cambió: {', '.join(entry['fields'])}."]
    else:
        lines += show(member)
    lines += ["", f"Copia anterior del roster: {entry['backup'] or '(el archivo no existía)'}",
              "", "Si no fuiste tú, revisa el roster y revoca el teléfono con `paynani sms revoke`."]
    return subject, "\n".join(lines) + "\n"
