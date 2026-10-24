"""
Lo que la pasarela SMS guarda en disco, bajo `state/sms/` (modo 700):

    device.json         el teléfono emparejado (DEC-3: uno), con el SHA-256 del token
    pairing.json        el código de emparejamiento vigente, como hash, y los fallos
    inbox/<id>.json     el texto de cada SMS recibido (600); el sobre del evento no lo lleva
    outbox/<id>.json    órdenes de envío que escribe `outgoing.queue` (SRV-3, PRD #489 FR-13)
    sent/<id>.json      la misma orden, cuando el teléfono ya la tomó (para `paynani sms thread`)

Una orden la crea el agente (`o_`), el dueño desde PaynaniWeb (`w_`, PRD #489) o
la API (`a_`, PRD #491). El prefijo del id dice cuál, y nunca cambia.
    orders.jsonl        cada estado de cada orden, una línea por estado
    human.jsonl         cada estado de cada SMS que mandó el dueño desde PaynaniApp (PaynaniApp#111)

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
ORDER_PREFIX = {"agent": "o", "owner": "w", "api": "a"}
ORDER_ID = re.compile(r"^[owa]_[0-9a-f]{32}$")
# h_: lo que el dueño mandó desde PaynaniApp; w_: lo que mandó desde PaynaniWeb, con el
# id de su orden (PRD #489 FR-15).
HUMAN_ID = re.compile(r"^[hw]_[0-9a-f]{32}$")
MESSAGE_ID = re.compile(r"^[0-9a-f]{64}$")


def valid_order_id(order_id) -> bool:
    return bool(ORDER_ID.match(str(order_id or "")))


def order_origin(order_id) -> str | None:
    """'agent', 'owner' o 'api' según el prefijo del id; None si el id no es válido."""
    if not valid_order_id(order_id):
        return None
    prefix = str(order_id)[0]
    return next(origin for origin, p in ORDER_PREFIX.items() if p == prefix)


def valid_human_id(local_id) -> bool:
    return bool(HUMAN_ID.match(str(local_id or "")))


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
        for sub in (self.root, self.root / "inbox", self.root / "outbox", self.root / "sent"):
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
    def _orders_in(self, folder: str, origins) -> list[dict]:
        orders = []
        for origin in origins:
            for path in sorted((self.root / folder).glob(f"{ORDER_PREFIX[origin]}_*.json")):
                try:
                    order = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not (valid_order_id(order.get("id")) and path.stem == order["id"]):
                    continue
                # El origin del JSON debe coincidir con el prefijo del id: una w_ que dice
                # origin "api" se saltaría la capacidad que anunció el teléfono. Inválida, no sale.
                if (order.get("origin") or "agent") != origin:
                    continue
                orders.append(order)
        return orders

    def pending_orders(self, origins=("agent",)) -> list[dict]:
        """
        Las órdenes que esperan en outbox/. Por omisión sólo las del agente: la
        pasarela todavía no manda las del dueño ni las de la API (eso es T2 de #490,
        que antes pregunta si el teléfono las acepta).
        """
        return self._orders_in("outbox", origins)

    def queue_order(self, order: dict) -> None:
        """Deja la orden en outbox/ (atómico, 600). Lo usa `outgoing.queue`."""
        if not valid_order_id(order.get("id")):
            raise ValueError("order_id inválido")
        self._write(self.root / "outbox" / f"{order['id']}.json", order)

    def finish_order(self, order_id: str) -> None:
        """
        La orden sale de outbox/ para no reenviarse, y se queda en sent/: el
        estado no dice a quién ni qué, y `paynani sms thread` lo necesita.
        """
        if not valid_order_id(order_id):
            raise ValueError("order_id inválido")
        try:
            os.replace(self.root / "outbox" / f"{order_id}.json", self.root / "sent" / f"{order_id}.json")
        except FileNotFoundError:
            pass

    def sent_orders(self, origins=("agent",)) -> list[dict]:
        return self._orders_in("sent", origins)

    def order(self, order_id: str) -> dict | None:
        """La orden, esté en outbox/ o ya en sent/; None si no existe."""
        if not valid_order_id(order_id):
            return None
        for folder in ("outbox", "sent"):
            try:
                order = json.loads((self.root / folder / f"{order_id}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if order.get("id") == order_id:
                return order
        return None

    def opted_out(self, number: str) -> dict | None:
        """
        ¿Ese número se dio de baja de la API (STOP, PRD #491 FR-13)? El registro de la
        baja, o None. La lista vive en `optout.json` como `{"numbers": {e164: {...}}}`;
        la escribe la pasarela cuando llega un STOP (A5 #497).
        """
        data = self._read("optout.json", None) or {}
        numbers = data.get("numbers") if isinstance(data, dict) else None
        entry = numbers.get(number) if isinstance(numbers, dict) else None
        return entry if isinstance(entry, dict) else None

    def accepts(self, origin: str) -> bool:
        """
        ¿El teléfono emparejado acepta órdenes de este origen? Lo anuncia en su
        saludo (PRD #489 FR-11, PRD #491 FR-19). Las del agente, siempre.
        """
        if origin == "agent":
            return True
        device = self.device() or {}
        # Sólo un true booleano cuenta: "false", 1 o un estado viejo no habilitan nada.
        return device.get({"owner": "accepts_owner_out", "api": "accepts_api_out"}.get(origin, "")) is True

    def append_status(self, record: dict) -> bool:
        """
        Agrega un estado de orden. False si ese id de estado ya estaba (idempotente).

        Lee todo orders.jsonl para encontrar el id: O(n) por estado. Con el volumen
        de un teléfono no importa; si crece, un índice de ids vistos lo resuelve.
        """
        return self._append_once(self.root / "orders.jsonl", record)

    def _append_once(self, path: Path, record: dict) -> bool:
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

    # --- SMS del dueño (PaynaniApp#111) --------------------------------------
    def append_human(self, record: dict) -> bool:
        """Un estado de un SMS del dueño en human.jsonl. False si ese id ya estaba."""
        if not valid_human_id(record.get("local_id")):
            raise ValueError("local_id inválido")
        return self._append_once(self.root / "human.jsonl", record)

    def human_records(self) -> list[dict]:
        path = self.root / "human.jsonl"
        out = []
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        return out

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
