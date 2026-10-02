"""
`paynani sms pair | devices | revoke` (SRV-1). La página de emparejamiento con
QR del onboarding es SRV-4; esto es lo mínimo para emparejar desde la terminal.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "harness"))

sys.path.insert(0, str(ROOT / "scripts"))

import paths  # noqa: E402
import phone  # noqa: E402
import roster as roster_mod  # noqa: E402

from .gateway import status_id  # noqa: E402
from .store import CODE_TTL_S, Store, now_utc, valid_order_id  # noqa: E402

MAX_TEXT = 1000
DEFAULT_TTL_MIN = 15
FINAL = {"sent": 0, "delivered": 0, "failed": 1, "rejected": 1, "expired": 1}


def _store() -> Store:
    return Store(paths.state_dir())


def _refuse(message: str) -> int:
    print(f"Refused: {message}", file=sys.stderr)
    return 2


def _expires(ttl_min: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl_min * 60))


def _describe(record: dict) -> str:
    line = f"{record.get('at', '')}  {record.get('status', '')}"
    if record.get("parts"):
        line += f"  ({record['parts']} SMS)"
    if record.get("error"):
        line += f"  error: {record['error']}"
    return line


def run_send(args) -> int:
    """
    El mismo portón que send.sh: un número que no está en roster.md sale con
    código 2 sin crear nada. Después encola la orden y espera el primer estado.
    """
    text = " ".join(args.text)
    if not text.strip():
        return _refuse("empty_text: there is nothing to send.")
    if len(text) > MAX_TEXT:
        return _refuse(f"text_too_long: {len(text)} characters, the limit is {MAX_TEXT}.")
    if args.ttl < 1:
        return _refuse("--ttl must be at least 1 minute.")
    number = phone.to_e164(args.number)
    if number is None:
        return _refuse(f"{args.number!r} is not a phone number. Write it in E.164, for example +525511112222.")
    roster = paths.roster()
    entries = roster_mod.roster_phone_entries(roster)
    phones = {e["phone"] for e in entries}
    if not roster_mod.phone_listed(number, phones):
        return _refuse(f"{number} is not in {roster}. Add it to the Phone column first; nothing was sent.")

    store = _store()
    device = store.device()
    if not device:
        print("No phone is paired, so there is nowhere to send from. Run `paynani sms pair`.",
              file=sys.stderr)
        return 1

    order_id = "o_" + secrets.token_hex(16)
    order = {"id": order_id, "to": number, "text": text, "expires_at": _expires(args.ttl)}
    if args.sim is not None:
        order["sim_slot"] = args.sim
    store.queue_order(order)
    store.append_status({"id": status_id(order_id, "queued"), "order_id": order_id,
                         "status": "queued", "at": now_utc()})
    name = next((e["name"] for e in entries if e["phone"] == number), "")
    print(f"Order {order_id} queued for {number}" + (f" ({name})" if name else "") + ".")
    if not device.get("connected"):
        print(f"The phone is not connected right now. The order waits until {order['expires_at']} "
              "and is then marked expired if it was never sent.")

    deadline = time.monotonic() + max(0, args.wait)
    shown = 0
    final = None
    while True:
        statuses = [s for s in store.order_statuses(order_id) if s.get("status") != "queued"]
        for record in statuses[shown:]:
            print(_describe(record))
            if record.get("status") in FINAL:
                final = record["status"]
        shown = len(statuses)
        if final or time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    if final is None:
        print(f"No status from the phone yet. Check with: paynani sms status {order_id}")
        return 3
    return FINAL[final]


def run_status(args) -> int:
    if not valid_order_id(args.order_id):
        return _refuse(f"{args.order_id!r} is not an order id (o_ and 32 hex digits).")
    statuses = _store().order_statuses(args.order_id)
    if not statuses:
        print(f"No order {args.order_id}.", file=sys.stderr)
        return 1
    for record in statuses:
        print(_describe(record))
    return 0


def run_pair(args) -> int:
    store = _store()
    device = store.device()
    if device and not args.replace:
        print(f"Ya hay un teléfono emparejado ({device['device_id']}). Esta versión maneja uno "
              "(DEC-3). Usa --replace para revocarlo y emparejar otro.", file=sys.stderr)
        return 2
    if device and args.replace:
        store.revoke()
        print(f"Teléfono {device['device_id']} revocado. Si estaba conectado, se cierra al reconectar.")
    base = (args.url or os.environ.get("PAYNANI_SMS_PUBLIC_URL", "")).rstrip("/")
    if not base:
        print("Falta la dirección pública de la pasarela: --url https://<túnel> o "
              "PAYNANI_SMS_PUBLIC_URL.", file=sys.stderr)
        return 2
    code = store.new_code()
    ws = base.replace("https://", "wss://").replace("http://", "ws://") + "/sms/ws"
    payload = {"v": 1, "pair": base + "/sms/pair", "ws": ws, "code": code}
    print(f"Código de emparejamiento: {code}  (vence en {CODE_TTL_S // 60} minutos, un solo uso)")
    print("Contenido del QR:")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def run_devices(args) -> int:
    device = _store().device()
    if not device:
        print("No hay teléfono emparejado.")
        return 0
    safe = {k: v for k, v in device.items() if k != "token_sha256"}
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    return 0


def run_revoke(args) -> int:
    device = _store().revoke()
    if not device:
        print("No había teléfono emparejado.")
        return 0
    print(f"Teléfono {device['device_id']} revocado: su token ya no abre la pasarela.")
    return 0
