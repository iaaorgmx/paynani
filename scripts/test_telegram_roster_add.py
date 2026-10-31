#!/usr/bin/env python3
"""
Agregar al roster a alguien que escribió por Telegram (PRD #609 FR-11, FR-15; #612): de
punta a punta con un `TelegramService` real, `FakeBotAPI` y el servicio del roster
(`roster.save`, el que usan PaynaniWeb, PaynaniApp y la API).

Alguien fuera del roster escribe; `telegram.roster_candidate` da su id; `roster.save`
guarda una fila nueva con ese id en la columna `Telegram`, sin correo ni teléfono;
`roster.list` lo devuelve; el aviso al dueño dice que la fila tiene Telegram sin el id; y
el mensaje siguiente de esa persona llega con `roster_match: true`.

Todo en carpetas temporales; al final se comprueba que el sha256 del `.env` (de
`paths.env_file()`) y de la configuración de Himalaya de la instalación no cambiaron.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.sms import roster_api  # noqa: E402
from paynani_lib.telegram import config  # noqa: E402
from paynani_lib.telegram.fake_api import FakeBotAPI  # noqa: E402
from paynani_lib.telegram.service import TelegramService  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def real_env() -> Path:
    import paths
    try:
        return Path(paths.env_file())
    except Exception:  # noqa: BLE001
        return Path.home() / ".claude/workspace/.env"


REAL = [real_env(), Path.home() / ".config/himalaya/config.toml"]
BEFORE = [sha(p) for p in REAL]

TOKEN = "424242:" + "k" * 30
PEDRO = 7000099


def events(state: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in (state / "events.jsonl").read_text().splitlines() if x.strip()]
    except OSError:
        return []


async def until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return bool(cond())


async def main():
    api = FakeBotAPI(token=TOKEN, bot_id=424242, username="AltaPaynaniBot").start()
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state"
    state.mkdir()
    (tmp / "rules").mkdir()
    roster = tmp / "roster.md"
    roster.write_text("| Name | Email | Type | Telegram |\n|---|---|---|---|\n"
                      "| Julian Flores | julian@example.com | Human |  |\n", encoding="utf-8")
    envf = tmp / "telegram.env"
    config.write({"TELEGRAM_ENABLED": "1", **config.with_token({}, TOKEN)}, envf)
    service = TelegramService(state, roster_path=roster, token=TOKEN, api_base=api.base_url, env_path=envf,
                              log=lambda line: None, mail_owner=lambda s, b: None, rules_root=tmp,
                              poll_timeout=1, backoff=(0.05, 0.2), ready_timeout_s=3.0)
    notices = []
    rs = roster_api.RosterService(roster, state, agent_email="agente@example.com",
                                  notifier=lambda to, subject, body: notices.append((subject, body)) or True,
                                  log=lambda line: None, rules_root=tmp)
    await service.start()
    try:
        await until(lambda: service.state == "running")
        api.private_message(PEDRO, "Hola, ¿hacen envíos?", first_name="Pedro")
        await until(lambda: any(e.get("event_type") == "telegram.received" for e in events(state)))
        first = [e for e in events(state) if e.get("event_type") == "telegram.received"]
        check("antes: Pedro llega fuera del roster", [False], [e.get("roster_match") for e in first])
        threads = (await service.handle({"type": "telegram.threads", "id": "q_" + "1" * 32, "by": "web",
                                         "limit": 50}))["data"]["threads"]
        cand = (await service.handle({"type": "telegram.roster_candidate", "id": "q_" + "2" * 32, "by": "web",
                                      "thread": threads[0]["thread"]}))["data"]
        check("roster_candidate da su id", str(PEDRO), cand.get("telegram"))

        listing = rs.handle({"type": "roster.list", "id": "q_" + "3" * 32}, "web:203.0.113.9")["data"]
        saved = rs.handle({"type": "roster.save", "id": "q_" + "4" * 32, "row": None, "etag": listing["etag"],
                           "member": {"name": cand["display_name"], "email": "", "type": "Human", "github": "",
                                      "phones": [], "telegram": cand["telegram"]}}, "web:203.0.113.9")
        check("roster.save acepta una fila sólo con Telegram", "result", saved.get("type"))
        text = roster.read_text(encoding="utf-8")
        check("la fila queda con el id en la columna Telegram", True, f"| Pedro |  | Human | {PEDRO} |" in text)
        members = rs.handle({"type": "roster.list", "id": "q_" + "5" * 32}, "web:203.0.113.9")["data"]["members"]
        check("roster.list devuelve telegram", str(PEDRO), next(m for m in members if m["name"] == "Pedro")["telegram"])
        await until(lambda: notices)
        check("el aviso al dueño dice que tiene Telegram, sin el id", (True, False),
              (bool(notices) and "Telegram: sí" in notices[-1][1], bool(notices) and str(PEDRO) in notices[-1][1]))
        changes = (state / "roster_changes.jsonl").read_text(encoding="utf-8")
        check("roster_changes.jsonl no trae el id", False, str(PEDRO) in changes)

        api.private_message(PEDRO, "Somos la tienda de enfrente", first_name="Pedro")
        await until(lambda: len([e for e in events(state) if e.get("event_type") == "telegram.received"]) >= 2)
        after = [e for e in events(state) if e.get("event_type") == "telegram.received"]
        check("después: el mensaje siguiente llega con roster_match true", True, after[-1].get("roster_match"))
        check("y con el nombre de su fila", "Pedro", (after[-1].get("sender") or {}).get("name"))
        check("ningún evento trae el id", False, str(PEDRO) in json.dumps(events(state)))
    finally:
        await service.stop()
        api.stop()


asyncio.run(main())
check("no se escribió telegram.env en el clon", False, (ROOT / "telegram.env").exists())
check("la configuración real no cambió (.env y Himalaya)", BEFORE, [sha(p) for p in REAL])
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
