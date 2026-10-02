"""
Lo que la pasarela SMS guarda en disco, bajo `state/sms/` (modo 700):

    device.json         el teléfono emparejado (DEC-3: uno), con el SHA-256 del token
    pairing.json        el código de emparejamiento vigente, como hash, y los fallos
    inbox/<id>.json     el texto de cada SMS recibido (600); el sobre del evento no lo lleva
    outbox/<id>.json    órdenes de envío que escribe `paynani sms send` (SRV-3)
    orders.jsonl        cada estado de cada orden, una línea por estado

Nada de esto se imprime en logs: tokens y códigos sólo como hash, y el texto de
los SMS sólo en inbox/, igual que el cuerpo de un correo vive en el servidor IMAP
y no en el diario de eventos.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL_S = 600
FAIL_WINDOW_S = 600
FAIL_LIMIT = 10

# Los ids que terminan en nombres de archivo. Validados aquí también, aunque la
# pasarela ya los valide: el almacén no confía en quien lo llame (un order_id
# "../device" borraba device.json; lo encontró Iris en #316).
ORDER_ID = re.compile(r"^o_[0-9a-f]{32}$")
MESSAGE_ID = re.compile(r"^[0-9a-f]{64}$")


def valid_order_id(order_id) -> bool:
    return bool(ORDER_ID.match(str(order_id or "")))


def _check_message_id(message_id) -> str:
    if not MESSAGE_ID.match(str(message_id or "")):
        raise ValueError("id de mensaje inválido")
    return str(message_id)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    def __init__(self, state_dir: Path):
        self.root = Path(state_dir) / "sms"
        for sub in (self.root, self.root / "inbox", self.root / "outbox"):
            sub.mkdir(parents=True, exist_ok=True)
            os.chmod(sub, 0o700)

    # --- archivos -----------------------------------------------------------
    def _read(self, name: str, default):
        path = self.root / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default

    def _write(self, path: Path, data) -> None:
        """Atómico y durable: temporal 600, fsync, rename."""
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    # --- teléfono emparejado -----------------------------------------------
    def device(self) -> dict | None:
        return self._read("device.json", None)

    def device_for_token(self, token: str) -> dict | None:
        device = self.device()
        if not device or not token:
            return None
        if secrets.compare_digest(device.get("token_sha256", ""), _sha256(token)):
            return device
        return None

    def save_device(self, device: dict) -> None:
        self._write(self.root / "device.json", device)

    def revoke(self) -> dict | None:
        device = self.device()
        try:
            (self.root / "device.json").unlink()
        except FileNotFoundError:
            pass
        return device

    def touch(self, **fields) -> None:
        device = self.device()
        if device:
            device.update(fields)
            self.save_device(device)

    # --- emparejamiento -----------------------------------------------------
    def new_code(self, now: float | None = None) -> str:
        """Un código nuevo. Reemplaza al anterior y limpia el bloqueo por fallos."""
        now = time.time() if now is None else now
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        self._write(self.root / "pairing.json", {
            "code_sha256": _sha256(code), "expires": now + CODE_TTL_S,
            "used": False, "fails": [], "blocked": False,
        })
        return code

    def redeem(self, code: str, now: float | None = None) -> str:
        """
        'ok', 'expired' (vencido, usado o inexistente) o 'blocked'.
        El código queda gastado en cuanto se acepta, aunque la respuesta no llegue.
        """
        now = time.time() if now is None else now
        pairing = self._read("pairing.json", None)
        if not pairing:
            return "expired"
        fails = [t for t in pairing.get("fails", []) if now - t < FAIL_WINDOW_S]
        if pairing.get("blocked") or len(fails) >= FAIL_LIMIT:
            pairing.update(blocked=True, fails=fails)
            self._write(self.root / "pairing.json", pairing)
            return "blocked"
        if pairing.get("used") or now > pairing.get("expires", 0):
            return "expired"
        if not secrets.compare_digest(pairing.get("code_sha256", ""), _sha256(str(code or "").strip().upper())):
            fails.append(now)
            pairing.update(fails=fails, blocked=len(fails) >= FAIL_LIMIT)
            self._write(self.root / "pairing.json", pairing)
            return "blocked" if pairing["blocked"] else "expired"
        pairing["used"] = True
        self._write(self.root / "pairing.json", pairing)
        return "ok"

    # --- SMS recibidos ------------------------------------------------------
    def inbox_path(self, message_id: str) -> Path:
        return self.root / "inbox" / f"{_check_message_id(message_id)}.json"

    def inbox(self, message_id: str) -> dict | None:
        if not MESSAGE_ID.match(str(message_id or "")):
            return None
        try:
            return json.loads(self.inbox_path(message_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_inbox(self, message_id: str, data: dict) -> None:
        self._write(self.inbox_path(message_id), data)

    # --- órdenes de envío ---------------------------------------------------
    def pending_orders(self) -> list[dict]:
        orders = []
        for path in sorted((self.root / "outbox").glob("o_*.json")):
            try:
                order = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if valid_order_id(order.get("id")) and path.stem == order["id"]:
                orders.append(order)
        return orders

    def queue_order(self, order: dict) -> None:
        """Deja la orden en outbox/ (atómico, 600). Lo usa `paynani sms send`."""
        if not valid_order_id(order.get("id")):
            raise ValueError("order_id inválido")
        self._write(self.root / "outbox" / f"{order['id']}.json", order)

    def finish_order(self, order_id: str) -> None:
        if not valid_order_id(order_id):
            raise ValueError("order_id inválido")
        try:
            (self.root / "outbox" / f"{order_id}.json").unlink()
        except FileNotFoundError:
            pass

    def append_status(self, record: dict) -> bool:
        """
        Agrega un estado de orden. False si ese id de estado ya estaba (idempotente).

        Lee todo orders.jsonl para encontrar el id: O(n) por estado. Con el volumen
        de un teléfono no importa; si crece, un índice de ids vistos lo resuelve.
        """
        path = self.root / "orders.jsonl"
        sid = record.get("id")
        if sid and path.exists():
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if f'"id":"{sid}"' in line:
                        return False
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return True

    def order_statuses(self, order_id: str) -> list[dict]:
        if not valid_order_id(order_id):
            return []
        path = self.root / "orders.jsonl"
        out = []
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("order_id") == order_id:
                        out.append(rec)
        return out
