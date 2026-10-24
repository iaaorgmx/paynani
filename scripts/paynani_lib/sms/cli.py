"""
`paynani sms pair | devices | revoke` (SRV-1). La página de emparejamiento con
QR del onboarding es SRV-4; esto es lo mínimo para emparejar desde la terminal.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "harness"))

sys.path.insert(0, str(ROOT / "scripts"))

import event as ev  # noqa: E402
import paths  # noqa: E402
import phone  # noqa: E402
import roster as roster_mod  # noqa: E402

from . import outgoing  # noqa: E402
from . import pairing  # noqa: E402
from . import thread as thread_mod  # noqa: E402
from .store import CODE_TTL_S, Store, now_utc, valid_order_id  # noqa: E402

MAX_TEXT = outgoing.MAX_TEXT
DEFAULT_TTL_MIN = outgoing.DEFAULT_TTL_MIN
FINAL = {"sent": 0, "delivered": 0, "failed": 1, "rejected": 1, "expired": 1}
PAUSED = 4  # el humano contestó ese número hace poco (PaynaniApp#111, SMS_GATEWAY.md §4)


def _store() -> Store:
    return Store(paths.state_dir())


def _refuse(message: str) -> int:
    print(f"Refused: {message}", file=sys.stderr)
    return 2


def _describe(record: dict) -> str:
    line = f"{record.get('at', '')}  {record.get('status', '')}"
    if record.get("parts"):
        line += f"  ({record['parts']} SMS)"
    if record.get("error"):
        line += f"  error: {record['error']}"
    return line


def human_pause(store: Store, number: str, now: str | None = None) -> str | None:
    """
    Hasta cuándo el agente no le escribe a `number`, o None. La decide el último
    `sent` del dueño a ese número: uno nuevo la reinicia y uno con pausa 0 la
    termina (SMS_GATEWAY.md §4).
    """
    until = (_latest_owner_sent(store, number) or {}).get("pause_until")
    return until if until and until > (now or now_utc()) else None


def _latest_owner_sent(store: Store, number: str) -> dict | None:
    """El último `sent` del dueño a ese número, de PaynaniApp o de PaynaniWeb."""
    latest = None
    for record in store.human_records():
        if record.get("status") == "sent" and record.get("to") == number:
            if latest is None or str(record.get("at", "")) >= str(latest.get("at", "")):
                latest = record
    return latest


def pause_source(store: Store, number: str) -> str:
    """Desde dónde le escribió el dueño: PaynaniWeb (`origin: web`) o PaynaniApp."""
    record = _latest_owner_sent(store, number) or {}
    return "PaynaniWeb" if record.get("origin") == "web" else "PaynaniApp"


def run_send(args) -> int:
    """
    El mismo portón que send.sh: un número que no está en roster.md sale con
    código 2 sin crear nada. Después encola la orden y espera el primer estado.
    """
    text = " ".join(args.text)
    try:
        outgoing.check_text(text)
        if args.ttl < 1:
            return _refuse("--ttl must be at least 1 minute.")
        number = outgoing.normalize(args.number)
    except outgoing.Refused as refused:
        return _refuse(refused.message)
    roster = paths.roster()
    entries = roster_mod.roster_phone_entries(roster)
    phones = {e["phone"] for e in entries}
    if not roster_mod.phone_listed(number, phones):
        return _refuse(f"{number} is not in {roster}. Add it to the Phone column first; nothing was sent.")
    # La segunda barrera, después del roster (#409 I-3): reply.sms: never en sus reglas.
    from paynani_lib import reply_policy

    override, override_by = getattr(args, "override", None), getattr(args, "override_by", None)
    problem = reply_policy.override_problem(override, override_by)
    if problem:
        return _refuse(f"{problem}. Nothing was sent.")
    never, problems = reply_policy.check(roster, "sms", [number])
    for line in reply_policy.warning_lines("sms", problems):
        print(line, file=sys.stderr)
    if never and override is None:
        for line in reply_policy.refusal_lines("sms", never):
            print(line, file=sys.stderr)
        return 2

    store = _store()
    paused = human_pause(store, number)
    if paused and not getattr(args, "override_pause", False):
        print(f"Refused: human_replied. The phone's owner replied to {number} from {pause_source(store, number)}, "
              "so the agent "
              f"does not write to it until {paused}. Nothing was sent. Use --override-pause only if the "
              "owner asked you to.", file=sys.stderr)
        return PAUSED
    device = store.device()
    if not device:
        print("No phone is paired, so there is nowhere to send from. Run `paynani sms pair`.",
              file=sys.stderr)
        return 1

    if never:
        for item in never:
            print(f"OVERRIDE: writing to {number} despite reply.sms: never in {item['rules']} "
                  f"(by {override_by}: {override})", file=sys.stderr)
        reply_policy.log_override(paths.state_dir(), tool="paynani sms send", channel="sms", items=never,
                                  by=override_by, reason=override)
    try:
        order = outgoing.queue(store, to=number, text=text, origin="agent", ttl_min=args.ttl, sim_slot=args.sim)
    except outgoing.Refused as refused:
        return _refuse(refused.message)
    order_id = order["id"]
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


def _when(stamp: str) -> tuple[float, str]:
    return thread_mod.when(stamp)


def _thread_items(store: Store, number: str, journal: Path) -> list[tuple[str, str, str, str]]:
    """(hora local, quién, estado, texto) de la conversación con `number`, en orden de hora."""
    return [(i["local"], i["kind"], i["status"], i["text"]) for i in thread_mod.items(store, journal, number=number)]


def run_thread(args) -> int:
    """
    `paynani sms thread <número>` (PaynaniApp#111): lo que llegó de ese número, lo
    que le mandó el agente y lo que le contestó el dueño desde PaynaniApp, en
    orden. Con un número fuera del roster no muestra textos, como
    `paynani event show --body`.
    """
    number = phone.to_e164(args.number)
    if number is None:
        return _refuse(f"{args.number!r} is not a phone number. Write it in E.164, for example +525511112222.")
    roster = paths.roster()
    phones = {e["phone"] for e in roster_mod.roster_phone_entries(roster)}
    in_roster = roster_mod.phone_listed(number, phones)
    store = _store()
    items = _thread_items(store, number, paths.state_dir() / "events.jsonl")
    if args.limit and args.limit > 0:
        items = items[-args.limit:]
    if not items:
        print(f"No messages with {number}.")
    for when, who, status, text in items:
        label = {"received": "received", "agent": "agent", "human": "human"}[who]
        shown = ev.safe_excerpt(text, 1000) if in_roster else "(text hidden: the number is not on roster.md)"
        print(f"{when}  {label:<8} {('[' + status + ']') if status else '':<12} {shown}")
    paused = human_pause(store, number)
    if paused:
        print(f"Agent pause: the owner replied from {pause_source(store, number)}; the agent does not write to {number} "
              f"until {paused} (--override-pause only if the owner asks).")
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
    payload = pairing.payload(base, code)
    print(f"Código de emparejamiento: {code}  (vence en {CODE_TTL_S // 60} minutos, un solo uso)")
    print("Si vence antes de usarlo, no es un error: vuelve a correr este comando y usa el código nuevo.")
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
