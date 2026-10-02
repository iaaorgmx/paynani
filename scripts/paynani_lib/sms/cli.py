"""
`paynani sms pair | devices | revoke` (SRV-1). La página de emparejamiento con
QR del onboarding es SRV-4; esto es lo mínimo para emparejar desde la terminal.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "harness"))

import paths  # noqa: E402

from .store import CODE_TTL_S, Store  # noqa: E402


def _store() -> Store:
    return Store(paths.state_dir())


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
