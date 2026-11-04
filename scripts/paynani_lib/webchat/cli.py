"""
`paynani webchat send | typing | thread` (#648 W-2, WEBCHAT.md §6).

El agente contesta al dueño en el Webchat de PaynaniWeb. No hay servicio: todo pasa por
`webchat/store.py`, igual que la web.
"""
from __future__ import annotations

import codecs
import json
import os
import sys
import time
from pathlib import Path

from paynani_lib.webchat import store

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness"))
import ledger  # noqa: E402

DRAFT_EVERY_S = 0.3        # cada cuánto se reescribe el borrador de --stream
_OPEN = ("observed", "dispatched", "presented")


def _err(text: str) -> None:
    print(f"paynani webchat: {text}", file=sys.stderr)


def _state_dir() -> Path:
    return store.root().parent


def _outbox_file(raw: str) -> tuple[str, bytes] | None:
    """Un archivo de state/webchat/outbox/ (WEBCHAT.md §2), o None si está fuera."""
    outbox = (store.root() / "outbox").resolve()
    try:
        path = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        _err(f"no existe: {raw}")
        return None
    if outbox not in path.parents or not path.is_file():
        _err(f"--file tiene que estar en {outbox}/: cópialo ahí primero")
        return None
    return path.name, path.read_bytes()


def mark_replied(message: dict, *, state_dir: Path | None = None) -> list[str]:
    """
    Marca `replied` cada `webchat.received` abierto que llegó antes de la respuesta: si
    el dueño mandó tres mensajes y el agente contesta una vez, la respuesta es de los
    tres.
    """
    state = Path(state_dir) if state_dir else _state_dir()
    path = state / "lifecycle.jsonl"
    done = []
    for event_id, record in ledger.latest(path).items():
        if not event_id.startswith("wc:") or record.get("state") not in _OPEN:
            continue
        observed = next((r for r in ledger.history(path, event_id) if r.get("state") == "observed"), {})
        if (observed.get("at") or "") > message["at"]:
            continue
        ledger.transition(path, event_id, "replied", runtime="webchat", detail=message["id"],
                          provider_id=record.get("provider_id", ""))
        done.append(event_id)
    return done


def _send(text: str, files: list[tuple[str, bytes]], reply_to: str | None = None) -> int:
    try:
        message = store.append("agent", text, files, reply_to=reply_to)
    except store.Rejected as exc:
        _err(f"rechazado: {exc.code}" + (f" ({exc.detail})" if getattr(exc, "detail", "") else ""))
        return 2
    mark_replied(message)
    quote = message.get("reply_to")
    if quote and quote.get("missing"):
        print(f"{message['id']}\tsent\treply dropped: {reply_to} is not in the conversation")
    else:
        print(f"{message['id']}\tsent" + (f"\treply_to {quote['ref']}" if quote else ""))
    return 0


def run_send(args) -> int:
    reply_to = getattr(args, "reply_to", None)
    if reply_to is not None and not store._MSG_ID.match(reply_to):  # noqa: SLF001
        _err("--reply-to es el id de un mensaje de la conversación (w_…, de webchat thread)")
        return 2
    if args.stream:
        if args.text or args.file:
            _err("--stream lee el texto de stdin: sin texto ni --file")
            return 2
        return _run_stream(reply_to)
    text = " ".join(args.text or [])
    if not text and not args.file and not sys.stdin.isatty():
        text = sys.stdin.read()
    files = []
    for raw in args.file or []:
        item = _outbox_file(raw)
        if item is None:
            return 2
        files.append(item)
    return _send(text, files, reply_to)


def _run_stream(reply_to: str | None = None) -> int:
    """Lee stdin mientras llega y lo deja como borrador; al final, el mensaje."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    text, shown, last = "", "", 0.0
    try:
        while True:
            chunk = os.read(sys.stdin.fileno(), 4096)
            text += decoder.decode(chunk, final=not chunk)
            now = time.monotonic()
            if chunk and text != shown and now - last >= DRAFT_EVERY_S:
                store.draft_set(text)
                shown, last = text, now
            if not chunk:
                break
    except store.Rejected as exc:
        store.draft_clear()
        _err(f"rechazado: {exc.code}")
        return 2
    except BaseException:
        store.draft_clear()
        raise
    if not text.strip():
        store.draft_clear()
        _err("--stream terminó sin texto")
        return 2
    rc = _send(text, [], reply_to)
    if rc:
        store.draft_clear()
    return rc


def run_typing(args) -> int:
    if args.off:
        store.typing_off()
        print("typing\toff")
        return 0
    store.typing(args.seconds)
    print(f"typing\t{min(max(int(args.seconds), 1), 600)}s")
    return 0


def run_thread(args) -> int:
    limit = min(max(int(args.limit), 1), 100)
    rows = store.messages(limit=limit)
    if args.json:
        print(json.dumps({"messages": rows, "typing": store.is_typing()}, ensure_ascii=False, indent=2))
        return 0
    for m in rows:
        arrow = "←" if m.get("dir") == "in" else "→"
        parts = [m.get("text") or ""]
        parts += [f"[{'foto' if f.get('kind') == 'image' else 'documento'}: {f.get('name')}]"
                  for f in m.get("files", [])]
        quote = m.get("reply_to")
        if quote:
            parts.insert(0, f"(respondiendo a «{quote.get('excerpt') or ''}»)" if not quote.get("missing")
                         else "(se mandó sin cita)")
        print(f"{m.get('at')} {m.get('id')} {arrow} {' '.join(p for p in parts if p)}")
    return 0
