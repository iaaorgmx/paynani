"""
De dónde saca PaynaniWeb lo de WhatsApp (PRD #550 FR-7, FR-24; WA-5 #557).

La web le pide al servicio `paynani-whatsapp` lo mismo que PaynaniApp le pide a la
pasarela (`SMS_GATEWAY.md` §12), por la interfaz local de `WHATSAPP_BRIDGE.md` §11.
Las pantallas no saben de dónde viene: hablan con un `Source`.

- `ControlSocket`: la de verdad, por `state/whatsapp/control.sock`, con `by: "web"`.
- `Demo`: en memoria, con hilos inventados (números `+1555…`, que no son de nadie).
  Es la de las pruebas y la de `PAYNANI_WEB_WHATSAPP=demo`, para ver las pantallas
  sin vincular un teléfono.

Las reglas de privacidad y de envío (FR-16a, FR-19 a FR-22) las aplica siempre el
servicio. Las barreras de la web (contraseña y CSRF para vincular, cancelar y
desvincular, FR-6a) las pone `app.py` **antes** de llamar aquí.

El QR y el código de vinculación son credenciales de un solo uso (FR-6a): llegan en
el `result` de `whatsapp.link` y de `whatsapp.link_current`, sólo a quien tiene el
`link_id`, y nada de aquí los guarda ni los escribe en un log.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path

MAX_TEXT = 4000


class Failed(Exception):
    """Un `error` del servicio (§12, «Errores de esta sección»), o `unavailable`."""

    def __init__(self, code: str, **fields):
        super().__init__(code)
        self.code = code
        self.fields = fields


def configured(root: Path | None = None) -> bool:
    """§11: el único predicado de «WhatsApp configurado», `whatsapp_config.configured()`
    de WA-2. `root` es la carpeta de `runtime.env` (las pruebas pasan la suya); sin
    ella, la de la instalación."""
    from ..whatsapp import config as whatsapp_config
    if root is None:
        return whatsapp_config.configured()
    return whatsapp_config.configured(Path(root) / whatsapp_config.FILE_NAME)


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class Source:
    """Lo que las pantallas usan. `request()` devuelve el `data` del `result` o
    levanta `Failed` con el `code` del `error`."""

    def request(self, kind: str, **fields) -> dict:  # pragma: no cover -- interfaz
        raise NotImplementedError

    def status(self) -> dict:
        """`whatsapp.status`; sin servicio, `state: "service_down"`, que según §11
        contesta el propio cliente."""
        try:
            return self.request("whatsapp.status")
        except Failed as exc:
            if exc.code != "unavailable":
                raise
            return {"state": "service_down", "me": None, "since": None, "linking": None, "link_number": None}


# ---- El servicio, por control.sock (WHATSAPP_BRIDGE.md §11) ----------------------
class ControlSocket(Source):
    def __init__(self, path: Path, timeout: float = 15.0):
        self.path = Path(path)
        self.timeout = timeout

    def request(self, kind: str, **fields) -> dict:
        rid = "q_" + secrets.token_hex(16)
        line = json.dumps({"type": kind, "id": rid, "by": "web", **fields}, ensure_ascii=False) + "\n"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self.path))
            sock.sendall(line.encode("utf-8"))
            for raw in sock.makefile("r", encoding="utf-8"):
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("ref") != rid:
                    continue
                if msg.get("type") == "result":
                    return msg.get("data") or {}
                extra = {k: v for k, v in msg.items() if k not in ("type", "ref", "code", "ok")}
                raise Failed(str(msg.get("code") or "unavailable"), **extra)
        except OSError:
            raise Failed("unavailable")
        finally:
            sock.close()
        raise Failed("unavailable")


# ---- La de demostración ------------------------------------------------------------
_DEMO_THREADS = [
    {"number": "+15550100001", "name": "Ana López", "in_roster": True, "minutes_ago": 12, "messages": [
        ("in", None, 30, "text", "Hola, ¿tienen mesa para 4 hoy?"),
        ("out", "agent", 27, "text", "Sí, a las 8 tenemos lugar. ¿A nombre de quién?"),
        ("in", None, 15, "image", None),
        ("in", None, 12, "text", "A nombre de Ana. Gracias."),
    ]},
    {"number": "+15550100002", "name": "Julián Flores", "in_roster": True, "minutes_ago": 95, "messages": [
        ("in", None, 100, "text", "¿Ya quedó el pedido de mañana?"),
        ("out", "owner", 95, "text", "Sí, sale a las 9."),
    ]},
    {"number": "+15550100099", "name": None, "in_roster": False, "minutes_ago": 40, "messages": [
        ("in", None, 41, "text", "Tu código es 123456"),
        ("in", None, 40, "text", "No lo compartas"),
    ]},
]

LINK_IDLE_S = 60      # §11: con QR, sin un link_current en 60 s, se cancela
ENDED_KEPT_S = 300    # §11: un link_id terminado responde `ended` 5 minutos
QR_ROTATE_S = 20
CODE_TTL_S = 180


class Demo(Source):
    """En memoria, con las mismas reglas que el servicio: oculta lo de fuera del
    roster (FR-16a), sólo contesta a quien ya escribió (FR-20), una sola vinculación
    a la vez (FR-6a) y el `link_id` como única llave del QR o del código (§11).
    `state` empieza en `connected` con hilos; las pruebas lo cambian."""

    def __init__(self, state: str = "connected", clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.state = state
        self.me = "+15550100000" if state == "connected" else None
        self.since = _iso(clock() - 3600) if state == "connected" else None
        self.link: dict | None = None        # la vinculación en curso
        self.ended: dict[str, tuple[str, float]] = {}
        self.link_number = "+15550100000"
        self.unlink_remote = True
        self.calls: list[tuple[str, dict]] = []
        self.threads = []
        base = clock()
        for spec in _DEMO_THREADS:
            msgs = []
            for i, (direction, by, ago, kind, text) in enumerate(spec["messages"]):
                m = {"id": (f"wa:demo:{spec['number'][-3:]}{i}" if direction == "in"
                            else f"wo_demo{spec['number'][-3:]}{i}"),
                     "dir": direction, "at": _iso(base - ago * 60), "kind": kind, "text": text,
                     "media": ({"kind": kind, "mime": "image/jpeg", "bytes": 48213, "filename": None, "seconds": None}
                               if kind != "text" else None)}
                if direction == "out":
                    m["by"], m["status"] = by, "read"
                msgs.append(m)
            self.threads.append({"number": spec["number"], "name": spec["name"], "in_roster": spec["in_roster"],
                                 "can_reply": spec["in_roster"] and any(m["dir"] == "in" for m in msgs),
                                 "messages": msgs})

    # ---- vincular ------------------------------------------------------------------
    def _end(self, reason: str) -> None:
        if self.link is not None:
            self.ended[self.link["id"]] = (reason, self.clock())
            self.link = None
        if self.state == "linking":
            self.state = "unlinked"

    def _expire(self) -> None:
        now = self.clock()
        self.ended = {k: v for k, v in self.ended.items() if now - v[1] < ENDED_KEPT_S}
        link = self.link
        if link is None:
            return
        if link["mode"] == "qr" and now - link["asked"] > LINK_IDLE_S:
            self._end("canceled")
        elif link["mode"] == "code" and now >= link["expires"]:
            self._end("expired")
        elif link["mode"] == "qr" and now >= link["expires"]:
            # WhatsApp rota el QR: uno nuevo, y el anterior deja de valer.
            link["qr"], link["expires"] = self._new_qr(), now + QR_ROTATE_S

    @staticmethod
    def _new_qr() -> str:
        return "2@" + secrets.token_urlsafe(120) + "," + secrets.token_urlsafe(32) + "," + secrets.token_urlsafe(32)

    def _link_view(self, link: dict, first: bool = False) -> dict:
        """El QR vigente, o el código sólo en la primera respuesta: el código no se
        vuelve a entregar (§12, revisión de Ximena en #565)."""
        left = max(0, int(link["expires"] - self.clock()))
        out = {"mode": link["mode"], "expires_at": _iso(link["expires"]), "expires_in_s": left}
        if link["mode"] == "qr":
            out["qr"] = link["qr"]
        elif first:
            out["code"] = link["code"]
        return out

    def finish_link(self, reason: str = "linked") -> None:
        """Para las pruebas y la demostración: lo que pasa al escanear (o al fallar)."""
        with self.lock:
            self._end(reason)
            if reason == "linked":
                self.state, self.me, self.since = "connected", "+15550100000", _iso(self.clock())

    # ---- hilos -------------------------------------------------------------------
    @staticmethod
    def _public_thread(t: dict) -> dict:
        last = t["messages"][-1]
        row = {"number": t["number"], "name": t["name"] if t["in_roster"] else None, "in_roster": t["in_roster"],
               "last_at": last["at"], "last_dir": last["dir"], "can_reply": t["can_reply"]}
        if t["in_roster"]:
            row["last_excerpt"] = " ".join(str(last.get("text") or "").split())[:160] or None
            row["last_kind"] = last["kind"]
        else:
            row.update(last_excerpt=None, last_kind=None, hidden=True)
        return row

    @staticmethod
    def _public_message(t: dict, m: dict) -> dict:
        if t["in_roster"]:
            return dict(m)
        return {"id": m["id"], "dir": m["dir"], "at": m["at"], "hidden": True}

    def _find(self, number: str) -> dict:
        for t in self.threads:
            if t["number"] == number:
                return t
        raise Failed("not_found")

    @staticmethod
    def _page(rows: list, limit, before) -> tuple[list, str | None]:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise Failed("invalid", field="limit", reason="range")
        start = int(before) if before else 0
        chunk = rows[start:start + limit]
        return chunk, (str(start + limit) if start + limit < len(rows) else None)

    def request(self, kind: str, **fields) -> dict:
        with self.lock:
            self.calls.append((kind, dict(fields)))
            if self.state == "service_down":
                raise Failed("unavailable")
            self._expire()
            if kind == "whatsapp.status":
                linking = None
                if self.link is not None:
                    link = self.link
                    linking = {"by": "web", "mode": link["mode"], "expires_at": _iso(link["expires"]),
                               "expires_in_s": max(0, int(link["expires"] - self.clock()))}
                return {"state": self.state, "me": self.me, "since": self.since, "linking": linking,
                        "link_number": self.link_number}
            if kind == "whatsapp.link":
                if self.state == "connected":
                    raise Failed("already_linked")
                mode = fields.get("mode")
                if mode not in ("qr", "code"):
                    raise Failed("invalid", field="mode", reason="qr or code")
                self._end("replaced")
                now = self.clock()
                link = {"id": "l_" + secrets.token_hex(16), "mode": mode, "asked": now}
                if mode == "qr":
                    link["qr"], link["expires"] = self._new_qr(), now + QR_ROTATE_S
                else:
                    link["code"], link["expires"] = "DEMO-" + secrets.token_hex(2).upper(), now + CODE_TTL_S
                self.link, self.state = link, "linking"
                return {"link_id": link["id"], **self._link_view(link, first=True)}
            if kind == "whatsapp.link_current":
                link_id = str(fields.get("link_id", ""))
                if self.link is not None and self.link["id"] == link_id:
                    self.link["asked"] = self.clock()
                    return {"state": "waiting", **self._link_view(self.link)}
                if link_id in self.ended:
                    return {"state": "ended", "reason": self.ended[link_id][0]}
                raise Failed("not_found")
            if kind == "whatsapp.link_cancel":
                self._end("canceled")
                return {}
            if kind == "whatsapp.unlink":
                self._end("canceled")
                self.state, self.me, self.since = "unlinked", None, None
                return {"remote": self.unlink_remote}
            if kind == "whatsapp.threads":
                rows = sorted((self._public_thread(t) for t in self.threads if t["messages"]),
                              key=lambda r: r["last_at"], reverse=True)
                chunk, nxt = self._page(rows, fields.get("limit", 50), fields.get("before"))
                return {"threads": chunk, "next_before": nxt}
            if kind == "whatsapp.thread":
                t = self._find(str(fields.get("number", "")))
                msgs = [self._public_message(t, m) for m in reversed(t["messages"])]
                chunk, nxt = self._page(msgs, fields.get("limit", 50), fields.get("before"))
                return {"number": t["number"], "name": t["name"] if t["in_roster"] else None,
                        "in_roster": t["in_roster"], "can_reply": t["can_reply"], "messages": chunk,
                        "next_before": nxt}
            if kind == "whatsapp.image":
                raise Failed("not_found")  # la demostración no tiene archivos (#573)
            if kind == "whatsapp.send":
                text = str(fields.get("text", ""))
                if not text.strip() or len(text) > MAX_TEXT:
                    raise Failed("invalid", field="text", reason="length")
                if self.state != "connected":
                    raise Failed("not_connected")
                try:
                    t = self._find(str(fields.get("number", "")))
                except Failed:
                    raise Failed("not_allowed") from None
                if not t["in_roster"]:
                    raise Failed("not_allowed")
                if not t["can_reply"]:
                    raise Failed("not_started")
                m = {"id": "wo_" + secrets.token_hex(6), "dir": "out", "by": "owner", "at": _iso(self.clock()),
                     "kind": "text", "text": text, "status": "sending", "media": None}
                t["messages"].append(m)
                return {"message": dict(m)}
            raise Failed("unknown_type")


def for_install(state_dir: Path) -> Source:
    """La fuente de la instalación: la de demostración con `PAYNANI_WEB_WHATSAPP=demo`,
    y si no, el servicio por `state/whatsapp/control.sock`."""
    if os.environ.get("PAYNANI_WEB_WHATSAPP") == "demo":
        return Demo()
    return ControlSocket(Path(state_dir) / "whatsapp" / "control.sock")
