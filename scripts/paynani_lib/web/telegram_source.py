"""
De dónde saca PaynaniWeb lo de Telegram (PRD #609 FR-28; TG-7 de #612).

La web le pide al servicio `paynani-telegram` lo que necesita por la interfaz local de
`TELEGRAM.md` §4 (`state/telegram/control.sock`), igual que con WhatsApp (WA-5). Las
pantallas no saben de dónde viene: hablan con un `Source`.

- `ControlSocket`: la de verdad, con `by: "web"`.
- `Demo`: en memoria, con hilos y un bot inventados. Contesta los mismos JSON de §4 y
  aplica las mismas reglas que el servicio. Es la de las pruebas y la de
  `PAYNANI_WEB_TELEGRAM=demo`, para ver las pantallas sin un bot.

Lo que nunca pasa por aquí ni se guarda (§8): el token y los ids de Telegram. El token
viaja una sola vez, en `telegram.token_check`, y la web no lo devuelve. El único id de
Telegram que llega a la web es el de `telegram.roster_candidate` (FR-15), que la
pantalla pone en el formulario de la fila nueva y no guarda en otro lugar. Las barreras
de la web (contraseña, CSRF y `Origin`) las pone `app.py` **antes** de llamar aquí.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path

MAX_TEXT = 4096                  # §4: más largo, el servicio lo parte
FILE_NAME = "telegram.env"
TOKEN_RE = re.compile(r"^\d{5,16}:[A-Za-z0-9_-]{30,64}$")   # la forma de un token de BotFather
STATES = ("starting", "running", "offline", "conflict", "token_invalid", "journal_mismatch", "stopped",
          "service_down")


class Failed(Exception):
    """Un `error` del servicio (§4, «Errores»), o `unavailable`."""

    def __init__(self, code: str, **fields):
        super().__init__(code)
        self.code = code
        self.fields = fields


def configured(root: Path | None = None) -> bool:
    """§4: «Telegram configurado» es `telegram_config.configured()` del núcleo (TG-2).
    Mientras no exista, la misma regla: `telegram.env` regular y legible, con
    `TELEGRAM_ENABLED=1` y un `TELEGRAM_TOKEN`. `root` es la carpeta de `runtime.env`
    (las pruebas pasan la suya); sin ella, la de la instalación."""
    try:
        from ..telegram import config as telegram_config  # TG-2
    except ImportError:
        telegram_config = None
    if telegram_config is not None and hasattr(telegram_config, "configured"):
        if root is None:
            return bool(telegram_config.configured())
        return bool(telegram_config.configured(Path(root) / FILE_NAME))
    from ..whatsapp import config as env_reader   # el mismo lector de `KEY=valor` (0600, sin enlaces)
    if root is None:
        import paths
        root = Path(paths.config_dir())
    values = env_reader.read(Path(root) / FILE_NAME)
    return values is not None and values.get("TELEGRAM_ENABLED") == "1" and bool(values.get("TELEGRAM_TOKEN"))


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class Source:
    """Lo que las pantallas usan. `request()` devuelve el `data` del `result` o
    levanta `Failed` con el `code` del `error`."""

    def request(self, kind: str, **fields) -> dict:  # pragma: no cover -- interfaz
        raise NotImplementedError

    def status(self) -> dict:
        """`telegram.status`; sin servicio, `state: "service_down"`, que según §4
        contesta el propio cliente."""
        try:
            return self.request("telegram.status")
        except Failed as exc:
            if exc.code != "unavailable":
                raise
            return {"state": "service_down", "bot_username": None, "since": None, "last_poll_at": None,
                    "counters": {}}


# ---- El servicio, por control.sock (TELEGRAM.md §4) -------------------------------
class ControlSocket(Source):
    def __init__(self, path: Path, timeout: float = 20.0):
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
# Nombres e ids inventados: ninguno es de nadie. Los ids de Telegram de la demostración
# sólo salen en `telegram.roster_candidate`, como en el servicio.
_DEMO_THREADS = [
    {"name": "Ana López", "in_roster": True, "tg": "700000001", "messages": [
        ("in", None, 30, "text", "¿Tienen mesa a las 8?", False),
        ("out", "agent", 27, "text", "Sí, a las 8 tenemos lugar. ¿Para cuántas personas?", False),
        ("in", None, 15, "image", "La terraza, por favor", False),
        ("in", None, 12, "text", "Somos 4. Gracias.", True),
    ]},
    {"name": "Julián Flores", "in_roster": True, "tg": "700000002", "messages": [
        ("in", None, 100, "text", "¿Ya quedó el pedido de mañana?", False),
        ("out", "phone:d_demo01", 95, "text", "Sí, sale a las 9.", False),
    ]},
    {"name": "Pedro", "in_roster": False, "tg": "700000099", "messages": [
        ("in", None, 41, "text", "Hola, ¿hacen envíos?", False),
        ("in", None, 40, "text", "Soy Pedro, de la tienda de enfrente", False),
    ]},
]
CHECK_TTL_S = 300       # §4: `check` vale 5 minutos


class Demo(Source):
    """En memoria, con las mismas reglas que el servicio (§4): oculta lo de fuera del
    roster sin Catch-All, sólo contesta a quien ya escribió (FR-25), el token viaja sólo
    en `token_check` y `token_apply` usa el `check` (5 min), y el único id de Telegram
    sale en `roster_candidate`. `state` empieza en `running`; las pruebas lo cambian."""

    def __init__(self, state: str = "running", clock=time.time, catch_all: bool = False):
        self.clock = clock
        self.lock = threading.Lock()
        self.state = state
        self.reason: str | None = None
        self.bot_username = "PruebaPaynaniBot"
        self.token = "123456:" + "A" * 35            # el token actual de la demostración
        self.webhook = False
        self.catch_all = catch_all
        self.since = _iso(clock() - 3600)
        self.checks: dict[str, dict] = {}
        self.apply_result = "applied"               # las pruebas lo cambian a "rollback"
        self.calls: list[tuple[str, dict]] = []
        self.threads = []
        base = clock()
        for i, spec in enumerate(_DEMO_THREADS):
            msgs = []
            for j, (direction, by, ago, kind, text, edited) in enumerate(spec["messages"]):
                ref = (f"tg:demo{i}{j}" if direction == "in" else f"tgo:demo{i}{j}")
                m = {"ref": ref, "dir": direction, "at": _iso(base - ago * 60), "kind": kind, "text": text}
                if direction == "in":
                    m["edited"] = edited
                else:
                    m["by"], m["status"] = by, "sent"
                msgs.append(m)
            self.threads.append({"thread": "t_" + secrets.token_hex(16), "name": spec["name"],
                                 "in_roster": spec["in_roster"], "tg": spec["tg"], "messages": msgs})

    # ---- hilos -------------------------------------------------------------------
    def _visible(self, t: dict) -> bool:
        return t["in_roster"] or self.catch_all

    def _public_thread(self, t: dict) -> dict:
        last = t["messages"][-1]
        can = t["in_roster"] and any(m["dir"] == "in" for m in t["messages"])
        name = t["name"] if t["in_roster"] else f"{t['name']} (no verificado)"
        row = {"thread": t["thread"], "name": name, "in_roster": t["in_roster"], "last_at": last["at"],
               "last_dir": last["dir"], "can_reply": can}
        if self._visible(t):
            row["last_excerpt"] = " ".join(str(last.get("text") or "").split())[:160] or None
            row["last_kind"] = last["kind"]
        else:
            row.update(last_excerpt=None, last_kind=None, hidden=True)
        return row

    def _find(self, thread: str) -> dict:
        for t in self.threads:
            if t["thread"] == thread:
                return t
        raise Failed("not_found")

    @staticmethod
    def _page(rows: list, limit, before) -> tuple[list, str | None]:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise Failed("invalid", field="limit")
        start = int(before) if before and str(before).isdigit() else 0
        chunk = rows[start:start + limit]
        return chunk, (str(start + limit) if start + limit < len(rows) else None)

    def request(self, kind: str, **fields) -> dict:
        with self.lock:
            self.calls.append((kind, {k: ("…" if k == "token" else v) for k, v in fields.items()}))
            if self.state == "service_down":
                raise Failed("unavailable")
            now = self.clock()
            self.checks = {k: v for k, v in self.checks.items() if now - v["at"] < CHECK_TTL_S}
            if kind == "telegram.status":
                out = {"state": self.state, "bot_username": self.bot_username, "since": self.since,
                       "last_poll_at": _iso(now - 5),
                       "counters": {"received_today": 12, "sent_today": 9, "send_limit_day": 300,
                                    "edits_ignored": 0, "media_rejected": 1, "groups_left": 0}}
                if self.state == "conflict":
                    out["reason"] = self.reason or "409"
                return out
            if kind == "telegram.threads":
                rows = sorted((self._public_thread(t) for t in self.threads if t["messages"]),
                              key=lambda r: r["last_at"], reverse=True)
                chunk, nxt = self._page(rows, fields.get("limit", 50), fields.get("before"))
                return {"threads": chunk, "next_before": nxt}
            if kind == "telegram.thread":
                t = self._find(str(fields.get("thread", "")))
                row = self._public_thread(t)
                base = {"thread": t["thread"], "name": row["name"], "in_roster": t["in_roster"],
                        "can_reply": row["can_reply"]}
                if not self._visible(t):
                    return dict(base, messages=[], hidden=True, next_before=None)
                # Del más reciente al más viejo, como `whatsapp.thread`; `next_before` pide la
                # página anterior, más vieja (Ximena en #613).
                msgs = [dict(m) for m in reversed(t["messages"])]
                chunk, nxt = self._page(msgs, fields.get("limit", 50), fields.get("before"))
                return dict(base, messages=chunk, next_before=nxt)
            if kind == "telegram.image":
                raise Failed("not_found")      # la demostración no tiene archivos
            if kind == "telegram.send":
                if "file" in fields:
                    raise Failed("invalid", field="file")   # §4: la web nunca manda archivos
                text = str(fields.get("text", ""))
                if not text.strip() or len(text) > MAX_TEXT:
                    raise Failed("invalid", field="text")
                try:
                    t = self._find(str(fields.get("thread", "")))
                except Failed:
                    raise Failed("not_allowed") from None
                if not t["in_roster"]:
                    raise Failed("not_allowed")
                if not any(m["dir"] == "in" for m in t["messages"]):
                    raise Failed("not_started")
                # El `by` canónico de §4: lo que manda esta web va como `web`.
                m = {"ref": "tgo:" + secrets.token_hex(6), "dir": "out", "by": "web", "at": _iso(now),
                     "kind": "text", "text": text, "status": "sent"}
                t["messages"].append(m)
                return {"ref": m["ref"], "status": "sent", "at": m["at"]}
            if kind == "telegram.roster_candidate":
                t = self._find(str(fields.get("thread", "")))
                if t["in_roster"]:
                    raise Failed("invalid", field="thread")
                return {"telegram": t["tg"], "display_name": t["name"]}
            if kind == "telegram.token_check":
                token = str(fields.get("token", ""))
                if not TOKEN_RE.match(token):
                    raise Failed("invalid", field="token")
                if token.endswith("REVOKED"):
                    raise Failed("invalid", field="token", reason="getMe")
                check = "c_" + secrets.token_hex(16)
                self.checks[check] = {"token": token, "at": now, "webhook": self.webhook}
                return {"bot_username": "NuevoPaynaniBot" if token != self.token else self.bot_username,
                        "same_token": token == self.token, "webhook": self.webhook, "check": check}
            if kind == "telegram.token_apply":
                check = self.checks.get(str(fields.get("check", "")))
                if check is None:
                    raise Failed("not_found")
                if fields.get("confirm_dedicated") is not True:
                    raise Failed("missing_field", field="confirm_dedicated")
                if check["webhook"] and fields.get("confirm_delete_webhook") is not True:
                    raise Failed("missing_field", field="confirm_delete_webhook")
                del self.checks[str(fields.get("check"))]
                if check["token"] == self.token:
                    return {"result": "unchanged", "bot_username": self.bot_username}
                if self.apply_result == "rollback":
                    return {"result": "rollback", "reason": "409", "bot_username": self.bot_username}
                self.token, self.bot_username, self.webhook = check["token"], "NuevoPaynaniBot", False
                return {"result": "applied", "bot_username": self.bot_username}
            if kind == "telegram.watch":
                return {"watching": False, "status": {"state": self.state}}
            raise Failed("unknown_type")


def for_install(state_dir: Path) -> Source:
    """La fuente de la instalación: la de demostración con `PAYNANI_WEB_TELEGRAM=demo`,
    y si no, el servicio por `state/telegram/control.sock`."""
    if os.environ.get("PAYNANI_WEB_TELEGRAM") == "demo":
        return Demo()
    return ControlSocket(Path(state_dir) / "telegram" / "control.sock")
