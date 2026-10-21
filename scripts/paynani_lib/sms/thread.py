"""
Las conversaciones SMS de la pasarela: lo que llegó, lo que mandó el agente y lo
que contestó el dueño desde PaynaniApp, en orden de hora (PaynaniApp#111).

Una sola fuente para `paynani sms thread <número>` y para Messages de PaynaniWeb
(PRD #434 FR-17, FR-18). La CLI usa los SMS de un número; la web, además, las
llamadas, y todos los números a la vez.

De dónde sale cada cosa:

- **Recibido:** el evento `sms.received` del diario (`events.jsonl`) y su texto en
  el `inbox/` del store.
- **Del agente:** las órdenes de `paynani sms send` (enviadas y pendientes) con su
  último estado de `orders.jsonl`.
- **Del dueño:** lo que mandó desde PaynaniApp (`human.jsonl`) y su texto en el
  inbox, con su último estado.
- **Llamadas** (sólo la web): los eventos `call.missed` y `call.answered` del diario.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_HARNESS = Path(__file__).resolve().parents[3] / "harness"
if str(_HARNESS) not in sys.path:
    sys.path.insert(0, str(_HARNESS))

import event as ev  # noqa: E402

KINDS = ("received", "agent", "human", "call_missed", "call_answered")


def when(stamp: str) -> tuple[float, str]:
    """
    (segundos de época, hora local con zona) de una hora ISO 8601. Los SMS recibidos
    traen la zona del teléfono («-05:00») y lo demás va en UTC («Z»): ordenarlos como
    texto mezclaba los de un mismo día (QA de PaynaniApp#111 en el teléfono de Rock).
    """
    try:
        moment = datetime.fromisoformat(str(stamp).strip().replace("Z", "+00:00"))
    except ValueError:
        return 0.0, str(stamp)
    if moment.tzinfo is None:
        return moment.timestamp(), moment.isoformat(timespec="seconds")
    return moment.timestamp(), moment.astimezone().isoformat(timespec="seconds")


def items(store, journal: Path, *, number: str | None = None, calls: bool = False) -> list[dict]:
    """
    Cada mensaje (y, con `calls`, cada llamada) como
    `{"number", "epoch", "local", "kind", "status", "text", "name", "duration_s"}`,
    en orden de hora. Con `number`, sólo los de ese número.
    """
    raw = []
    for record, _ in ev.read_from(journal, 0) or ():
        if not isinstance(record, dict):
            continue
        kind = record.get("event_type")
        if kind not in (ev.SMS_RECEIVED, ev.CALL_MISSED, ev.CALL_ANSWERED):
            continue
        if kind != ev.SMS_RECEIVED and not calls:
            continue
        sender = record.get("sender") or {}
        who = sender.get("address")
        if not who or (number is not None and who != number):
            continue
        if kind == ev.SMS_RECEIVED:
            message_id = str(record.get("provider_id", "")).split(":", 1)[-1]
            saved = store.inbox(message_id) or {}
            stamp = str(record.get("sent_at") or record.get("observed_at") or "")
            raw.append((who, stamp, "received", "", str(saved.get("text", "")), sender.get("name", ""), None))
        else:
            stamp = str(record.get("started_at") or record.get("observed_at") or "")
            raw.append((who, stamp, "call_missed" if kind == ev.CALL_MISSED else "call_answered", "", "",
                        sender.get("name", ""), record.get("duration_s")))
    statuses: dict[str, str] = {}
    path = store.root / "orders.jsonl"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("status") != "queued":
                    statuses[rec.get("order_id", "")] = rec.get("status", "")
    for order in store.sent_orders() + store.pending_orders():
        to = order.get("to")
        if not to or (number is not None and to != number):
            continue
        queued = next((r.get("at", "") for r in store.order_statuses(order["id"]) if r.get("status") == "queued"), "")
        raw.append((to, queued, "agent", statuses.get(order["id"], "queued"), str(order.get("text", "")), "", None))
    by_send: dict[str, dict] = {}
    last: dict[str, str] = {}
    for rec in store.human_records():
        to = rec.get("to")
        if not to or (number is not None and to != number):
            continue
        if rec.get("event_id"):
            by_send[rec["local_id"]] = rec
        last[rec["local_id"]] = rec.get("status", "")
    for local_id, rec in by_send.items():
        saved = store.inbox(rec["id"]) or {}
        raw.append((rec["to"], rec.get("at", ""), "human", last.get(local_id, ""), str(saved.get("text", "")), "", None))
    out = []
    for who, stamp, kind, status, text, name, duration in raw:
        epoch, local = when(stamp)
        out.append({"number": who, "epoch": epoch, "local": local, "kind": kind, "status": status,
                    "text": text, "name": name or "", "duration_s": duration})
    out.sort(key=lambda item: item["epoch"])
    return out


def conversations(all_items: list[dict]) -> list[dict]:
    """Un resumen por número, la conversación con lo más reciente primero."""
    by_number: dict[str, dict] = {}
    for item in all_items:
        conv = by_number.setdefault(item["number"], {"number": item["number"], "name": "", "count": 0,
                                                     "last": None, "missed": 0})
        conv["count"] += 1
        if item["name"] and not conv["name"]:
            conv["name"] = item["name"]
        if item["kind"] == "call_missed":
            conv["missed"] += 1
        if conv["last"] is None or item["epoch"] >= conv["last"]["epoch"]:
            conv["last"] = item
    return sorted(by_number.values(), key=lambda c: c["last"]["epoch"], reverse=True)
