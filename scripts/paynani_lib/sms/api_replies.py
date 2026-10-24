"""
Respuestas a conversaciones de la API y bajas (A5 #497 del PRD #491, FR-11 a FR-13).

- **Respuesta a la API:** un SMS que llega de un número al que la API le escribió en
  los últimos 7 días es una respuesta a ese token. La pasarela lo marca en el evento
  (`api_reply`), `ListSmsReplies` lo devuelve a ese token, y el agente lo ve marcado.
  Por omisión el agente no contesta; el token puede tener `agent_replies: true`.
- **Bajas:** un SMS que dice sólo STOP, BAJA, ALTO o CANCELAR (sin importar
  mayúsculas ni acentos) da de baja el número para la API; START o ALTA lo da de alta.
  La lista vive en `state/sms/optout.json` y se edita en PaynaniWeb.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

WINDOW_S = 7 * 86400
STOP_WORDS = {"stop", "baja", "alto", "cancelar"}
START_WORDS = {"start", "alta"}
SPANISH = {"baja", "alto", "cancelar", "alta"}

CONFIRM = {
    ("stop", "es"): "Listo: ya no recibirás mensajes automáticos de este número. Para volver a recibirlos, responde ALTA.",
    ("stop", "en"): "Done: you will no longer receive automated messages from this number. Reply START to receive them again.",
    ("start", "es"): "Listo: volverás a recibir mensajes automáticos de este número. Para dejar de recibirlos, responde BAJA.",
    ("start", "en"): "Done: you will receive automated messages from this number again. Reply STOP to opt out.",
}


def _fold(text: str) -> str:
    """Minúsculas y sin acentos: «Bájá» y «BAJA» son la misma palabra."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def keyword(text) -> tuple[str, str] | None:
    """
    ("stop" | "start", la palabra) si el SMS dice sólo una de esas palabras, o None.
    Se toleran espacios y un signo final («Baja.», «STOP!»); «stop por favor» no cuenta.
    """
    if not isinstance(text, str):
        return None
    word = _fold(text).strip().rstrip(".!¡¿?").strip()
    if word in STOP_WORDS:
        return "stop", word
    if word in START_WORDS:
        return "start", word
    return None


def confirmation(kind: str, word: str) -> str:
    return CONFIRM[(kind, "es" if word in SPANISH else "en")]


def _epoch(stamp) -> float | None:
    try:
        moment = datetime.fromisoformat(str(stamp or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def conversation(store, number: str | None, now: float | None = None) -> dict | None:
    """
    La conversación de la API más reciente con ese número en los últimos 7 días:
    `{"token", "token_id", "order_id", "at"}`, o None. El token sale del `queued` de la
    orden en orders.jsonl (A4 #496), pero sólo cuenta una orden que el teléfono envió
    (`sent` o `delivered`), y la ventana corre desde ese envío. Una orden en cola,
    fallida, rechazada o vencida no le habló a nadie, así que no le da a su token los
    SMS que lleguen después de ese número (revisión de #523).
    """
    if not number:
        return None
    now = time.time() if now is None else now
    path = store.root / "orders.jsonl"
    if not path.exists():
        return None
    tokens = {}  # order_id → su `queued`, sólo órdenes a_ con token
    sent = {}    # order_id → la hora del primer sent o delivered
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            oid = str(rec.get("order_id", ""))
            if not oid.startswith("a_"):
                continue
            status = rec.get("status")
            if status == "queued" and rec.get("token_id"):
                tokens.setdefault(oid, rec)
            elif status in ("sent", "delivered"):
                at = _epoch(rec.get("at"))
                if at is not None and (oid not in sent or at < sent[oid][0]):
                    sent[oid] = (at, str(rec.get("at", "")))
    found = None
    for oid, (at, stamp) in sent.items():
        rec = tokens.get(oid)
        if rec is None or not (now - WINDOW_S < at <= now + 60):
            continue
        if found is not None and at < found["epoch"]:
            continue
        if (store.order(oid) or {}).get("to") != number:
            continue
        found = {"token": rec.get("token", ""), "token_id": rec["token_id"], "order_id": oid,
                 "at": stamp, "epoch": at}
    if found:
        found.pop("epoch")
    return found


def agent_replies(tokens_path: Path | None, token_id: str) -> bool:
    """¿Ese token deja que el agente local conteste sus respuestas (FR-12)? False si no se sabe."""
    if not tokens_path or not token_id:
        return False
    try:
        records = json.loads(Path(tokens_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if isinstance(records, dict):
        records = records.get("tokens", [])
    for record in records if isinstance(records, list) else []:
        if isinstance(record, dict) and record.get("prefix") == token_id:
            return record.get("agent_replies") is True
    return False


def token_active(tokens_path: Path | None, token_id: str, now: datetime | None = None) -> bool:
    """
    ¿El token sigue vigente (ni revocado ni vencido)? Un token revocado o vencido ya no
    puede leer sus respuestas, así que su conversación deja de contar: el siguiente SMS
    de ese número llega sin marca y el agente lo atiende con sus reglas. Si no se puede
    leer `api_tokens.json`, cuenta como vigente, que es lo que pasaba antes.
    """
    if not tokens_path or not token_id:
        return True
    try:
        records = json.loads(Path(tokens_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if isinstance(records, dict):
        records = records.get("tokens", [])
    if not isinstance(records, list):
        return True  # Una forma que no entendemos cuenta como vigente, igual que un archivo ilegible.
    record = next((r for r in records if isinstance(r, dict) and r.get("prefix") == token_id), None)
    if record is None:
        return True
    if record.get("revoked_at"):
        return False
    expires = _epoch(record.get("expires_at")) if record.get("expires_at") else None
    moment = (now or datetime.now(timezone.utc)).timestamp()
    return expires is None or expires > moment


# --- La lista de bajas ----------------------------------------------------------------

def _path(store) -> Path:
    return store.root / "optout.json"


@contextlib.contextmanager
def _locked(store):
    store.root.mkdir(parents=True, exist_ok=True)
    with open(store.root / "optout.lock", "a+b") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read(store) -> dict:
    try:
        data = json.loads(_path(store).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"numbers": {}}
    if not isinstance(data, dict) or not isinstance(data.get("numbers"), dict):
        raise ValueError("optout.json no tiene la forma {\"numbers\": {…}}")
    return data


def _write(store, data: dict) -> None:
    target = _path(store)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".optout.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def listing(store) -> list[dict]:
    """Los números dados de baja, el más reciente primero: `{"number", "at", "by", …}`."""
    numbers = _read(store)["numbers"]
    rows = [{"number": n, **(v if isinstance(v, dict) else {})} for n, v in numbers.items()]
    return sorted(rows, key=lambda r: str(r.get("at", "")), reverse=True)


def set_opt_out(store, number: str, out: bool, *, by: str, word: str = "", at: str | None = None) -> bool:
    """
    Da de baja (`out=True`) o de alta un número. `by` dice quién: `sms` (lo pidió por
    SMS) o `web:<dirección>`. True si cambió algo; una baja repetida no cambia nada.
    """
    with _locked(store):
        data = _read(store)
        numbers = data["numbers"]
        if out == (number in numbers):
            return False
        if out:
            entry = {"at": at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "by": by}
            if word:
                entry["keyword"] = word
            numbers[number] = entry
        else:
            numbers.pop(number, None)
        _write(store, data)
        return True
