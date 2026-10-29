"""
`paynani whatsapp status|link|unlink|send|thread` (PRD #550 FR-6, FR-19; WHATSAPP_BRIDGE.md §11).

Le habla al servicio paynani-whatsapp por state/whatsapp/control.sock. Códigos de salida:
0 bien, 1 el servicio no corre o no contestó, 2 el servicio dijo que no (not_allowed,
not_started, rate_limited, invalid, already_linked…), 3 la vinculación terminó sin vincular.
"""
from __future__ import annotations

import json
import secrets
import socket
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT / "scripts"), str(_ROOT / "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import paths  # noqa: E402

from ..sms import qr  # noqa: E402

POLL_S = 2.0

_ERRORS = {
    "not_allowed": "no se puede: {detail}",
    "not_started": "el contacto todavía no te ha escrito por WhatsApp desde que se vinculó; "
                   "WhatsApp no deja escribir primero (FR-20)",
    "rate_limited": "demasiado seguido: espera {retry_after_s} s",
    "already_linked": "WhatsApp ya está vinculado; para cambiar de cuenta: paynani whatsapp unlink",
    "not_connected": "WhatsApp no está conectado (paynani whatsapp status)",
    "unavailable": "el puente de WhatsApp no está disponible ahora ({detail})",
    "not_found": "no encontrado",
}


class ServiceDown(Exception):
    pass


def socket_path(state: Path | None = None) -> Path:
    return Path(state or paths.state_dir()) / "whatsapp" / "control.sock"


class Conn:
    """Una conexión al socket; una línea de JSON por pedido y por respuesta."""

    def __init__(self, path: Path, timeout: float = 30.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as exc:
            self.sock.close()
            raise ServiceDown(type(exc).__name__) from None
        self.buf = b""

    def ask(self, type_: str, by: str = "terminal", **fields) -> dict:
        msg = {"type": type_, "id": "q_" + secrets.token_hex(16), "by": by, **fields}
        try:
            self.sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            while b"\n" not in self.buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ServiceDown("cerró la conexión")
                self.buf += chunk
        except (socket.timeout, OSError) as exc:
            raise ServiceDown(type(exc).__name__) from None
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def close(self) -> None:
        self.sock.close()


def _connect(args) -> Conn | None:
    try:
        return Conn(socket_path(getattr(args, "state", None)))
    except ServiceDown:
        print("el servicio paynani-whatsapp no está corriendo (state/whatsapp/control.sock). "
              "Revisa: systemctl --user status paynani-whatsapp", file=sys.stderr)
        return None


def _refused(reply: dict) -> int:
    code = reply.get("code", "error")
    template = _ERRORS.get(code)
    if template:
        text = template.format(detail=reply.get("detail") or code,
                               retry_after_s=reply.get("retry_after_s", "?"))
    else:
        text = f"{code}" + (f": {reply['detail']}" if reply.get("detail") else "") + (
            f" ({reply['field']})" if reply.get("field") else "")
    print(f"paynani whatsapp: {text}", file=sys.stderr)
    return 1 if code in ("unavailable", "timeout") else 2


def _call(args, type_: str, **fields):
    conn = _connect(args)
    if conn is None:
        return None, 1
    try:
        reply = conn.ask(type_, by=getattr(args, "by", None) or "terminal", **fields)
    except ServiceDown:
        print("el servicio paynani-whatsapp no contestó", file=sys.stderr)
        return None, 1
    finally:
        conn.close()
    if reply.get("type") == "error":
        return None, _refused(reply)
    return reply.get("data") or {}, 0


def run_status(args) -> int:
    data, rc = _call(args, "whatsapp.status")
    if rc:
        return rc
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"estado: {data.get('state')}")
    if data.get("me"):
        print(f"número: {data['me']}")
    if data.get("since"):
        print(f"desde: {data['since']}")
    linking = data.get("linking")
    if linking:
        print(f"vinculando: por {linking['mode']}, pedido desde {linking['by']}, vence en {linking['expires_in_s']} s")
    return 0


def run_link(args) -> int:
    mode = "code" if args.code else "qr"
    if mode == "code" and not args.number:
        print("paynani whatsapp link --code necesita --number (el número del teléfono que se vincula)",
              file=sys.stderr)
        return 2
    conn = _connect(args)
    if conn is None:
        return 1
    try:
        fields = {"mode": mode, **({"number": args.number} if args.number else {})}
        reply = conn.ask("whatsapp.link", **fields)
        if reply.get("type") == "error":
            return _refused(reply)
        data = reply["data"]
        link_id = data["link_id"]
        if mode == "code":
            print(f"Código de vinculación: {data['code']}  (vence en {data['expires_in_s']} s)")
            print("En el teléfono: WhatsApp → Dispositivos vinculados → Vincular un dispositivo → "
                  "Vincular con el número de teléfono, y escribe el código.")
            data["code"] = None
        shown = None
        try:
            while True:
                qr_text = data.get("qr")
                if mode == "qr" and qr_text and qr_text != shown:
                    print(qr.to_terminal(qr.encode(qr_text)))
                    print("En el teléfono: WhatsApp → Dispositivos vinculados → Vincular un dispositivo, "
                          "y escanea. El QR cambia cada 20 s; Ctrl-C cancela.")
                    shown = qr_text
                time.sleep(POLL_S)
                reply = conn.ask("whatsapp.link_current", link_id=link_id)
                if reply.get("type") == "error":
                    print("paynani whatsapp: la vinculación ya no existe", file=sys.stderr)
                    return 3
                data = reply["data"]
                if data.get("state") == "ended":
                    break
        except KeyboardInterrupt:
            conn.ask("whatsapp.link_cancel")
            print("\nvinculación cancelada")
            return 3
        if data.get("reason") == "linked":
            status = conn.ask("whatsapp.status").get("data") or {}
            print(f"WhatsApp vinculado: {status.get('me') or ''}".rstrip())
            return 0
        print(f"la vinculación terminó sin vincular ({data.get('reason')})", file=sys.stderr)
        return 3
    except ServiceDown:
        print("el servicio paynani-whatsapp dejó de contestar", file=sys.stderr)
        return 1
    finally:
        conn.close()


def run_unlink(args) -> int:
    if not args.yes:
        if not sys.stdin.isatty():
            print("paynani whatsapp unlink pide confirmación: agrega --yes", file=sys.stderr)
            return 2
        answer = input("¿Desvincular WhatsApp? Borra las llaves de state/whatsapp/auth/. [s/N] ")
        if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("no se desvinculó")
            return 0
    data, rc = _call(args, "whatsapp.unlink")
    if rc:
        return rc
    # #578: aunque WhatsApp acepte la salida (remote), el teléfono puede seguir
    # mostrando el dispositivo. Por eso siempre se pide revisarlo.
    print("WhatsApp desvinculado" + ("" if data.get("remote") else " aquí, pero WhatsApp no contestó"))
    print("Revisa WhatsApp → Dispositivos vinculados en el teléfono; si el dispositivo sigue ahí, quítalo.")
    return 0


def run_send(args) -> int:
    text = " ".join(args.text or [])
    fields = {"number": args.number, "text": text}
    if args.file:
        fields["file"] = str(Path(args.file).expanduser().absolute())
    data, rc = _call(args, "whatsapp.send", **fields)
    if rc:
        return rc
    msg = data.get("message") or {}
    print(f"{msg.get('id')}\t{msg.get('status')}")
    return 0


def run_thread(args) -> int:
    data, rc = _call(args, "whatsapp.thread", number=args.number, limit=args.limit)
    if rc:
        return rc
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    who = " ".join(p for p in (data.get("name"), data.get("number")) if p)
    print(f"{who}" + ("" if data.get("can_reply") else "  (no se le puede escribir ahora)"))
    for m in reversed(data.get("messages") or []):
        arrow = "←" if m.get("dir") == "in" else "→"
        if m.get("hidden"):
            print(f"{m.get('at')} {arrow} (oculto: fuera del roster)")
            continue
        extra = f" [{m['status']}]" if m.get("status") else ""
        print(f"{m.get('at')} {arrow} {m.get('text') or '[' + str(m.get('kind')) + ']'}{extra}")
    return 0
