"""
El puente de Baileys como proceso hijo (WHATSAPP_BRIDGE.md, PRD #550 FR-1, FR-2, FR-5).

`BridgeSupervisor` lanza el puente, le manda `start`, le pasa órdenes y espera sus
respuestas, y entrega al servicio lo que el puente avisa por su cuenta. Si el
puente se cae o deja de contestar, lo vuelve a lanzar con espera creciente. No abre
puertos: todo va por stdin y stdout del hijo.

El QR y el código de vinculación pasan por aquí sólo en memoria (FR-6a). El log no
lleva textos de mensajes, nombres, QR, códigos ni nada de `auth/` (§8).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import shutil
import signal
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

PROTOCOL = 1
BRIDGE_DIR = Path(__file__).resolve().parents[2] / "whatsapp_bridge"

# FR-5: 5 s, 10 s, 30 s y luego cada 60 s. Vuelve a 5 s tras 10 minutos conectado.
BACKOFF_S = (5, 10, 30, 60)
STABLE_S = 600
# Sin `connected` por más de esto, un evento whatsapp.health (FR-5).
HEALTH_DOWN_S = 600
PING_EVERY_S = 30
PING_MISSES = 3
REPLY_TIMEOUT_S = 30
SEND_FILE_TIMEOUT_S = 120
SHUTDOWN_GRACE_S = 5
STDERR_LINE_MAX = 1024
STDOUT_LINE_MAX = 1024 * 1024

# Avisos del puente cuyo contenido nunca va al log (credenciales o texto ajeno).
_SECRET_EVENTS = {"link.qr", "link.code"}
_CONTENT_EVENTS = {"message"}

EXIT_REASONS = {2: "faltan Node o las dependencias (npm ci)", 3: "protocolo distinto",
                4: "auth/ con permisos abiertos"}


class UnsafePath(Exception):
    """Una carpeta de state/whatsapp/ que es un enlace simbólico o no es carpeta."""


def _private_dir(path: Path) -> None:
    """
    Crea `path` si falta y lo deja en 0700, sin seguir enlaces: si es un enlace
    simbólico (o un archivo), UnsafePath. Seguirlo cambiaría permisos, o borraría
    archivos (`logout`), fuera de state/whatsapp/.
    """
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise UnsafePath(f"{path} es un enlace simbólico o no es una carpeta") from exc
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise UnsafePath(f"{path} no es una carpeta")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def _tighten(tree: Path) -> None:
    """Dentro de auth/: carpetas 0700, archivos 0600, enlaces fuera. Nunca sigue enlaces."""
    for entry in os.scandir(tree):
        if entry.is_symlink():
            os.unlink(entry.path)
        elif entry.is_dir(follow_symlinks=False):
            _private_dir(Path(entry.path))
            _tighten(Path(entry.path))
        else:
            os.chmod(entry.path, 0o600)


class BridgeError(Exception):
    """Una orden que el puente contestó con `error`, o que no contestó."""

    def __init__(self, code: str, detail: str | None = None, field: str | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.field = field


@dataclass
class Layout:
    """Las carpetas de state/whatsapp/ (FR-10, FR-16)."""

    root: Path

    @property
    def auth(self) -> Path:
        return self.root / "auth"

    @property
    def media(self) -> Path:
        return self.root / "media"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def outbox(self) -> Path:
        return self.root / "outbox"

    def prepare(self) -> None:
        """
        Crea las carpetas con 0700 y deja lo de auth/ en 0600. Ninguna de las cinco
        puede ser un enlace simbólico: si lo es, UnsafePath y no se toca nada más.
        """
        self.root.parent.mkdir(parents=True, exist_ok=True)
        for d in (self.root, self.auth, self.media, self.inbox, self.outbox):
            _private_dir(d)
        _tighten(self.auth)


def default_command() -> list[str]:
    node = shutil.which("node") or "node"
    return [node, str(BRIDGE_DIR / "index.js")]


def node_major(node: str | None = None) -> int | None:
    """La versión mayor de Node, o None si no está (FR-3b pide 20 o más)."""
    import subprocess

    node = node or shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def new_id() -> str:
    return "c_" + secrets.token_hex(16)


def describe(msg: dict) -> str:
    """Una línea de log para un aviso del puente, sin nada sensible."""
    kind = msg.get("type")
    if kind in _SECRET_EVENTS:
        return f"{kind} (credencial, no se registra)"
    if kind == "status":
        return f"status {msg.get('state')}" + (f" ({msg.get('reason')})" if msg.get("reason") else "")
    if kind in _CONTENT_EVENTS:
        return f"message {msg.get('kind')} key={str(msg.get('key_id'))[:24]}"
    if kind == "receipt":
        return f"receipt {msg.get('status')} key={str(msg.get('key_id'))[:24]}"
    if kind == "call":
        return f"call {msg.get('status')}"
    if kind == "link.ended":
        return f"link.ended {msg.get('reason')}"
    return str(kind)


EventHandler = Callable[[dict], Awaitable[None] | None]
HealthHandler = Callable[[str, str | None], Awaitable[None] | None]


@dataclass
class BridgeSupervisor:
    """
    Mantiene vivo un puente y habla con él.

    on_event recibe cada aviso del puente (status, message, call, receipt, link.*).
    on_health recibe ("down", motivo), ("logged_out", None) y ("up", None) (FR-5).
    """

    layout: Layout
    command: list[str] = field(default_factory=default_command)
    on_event: EventHandler | None = None
    on_health: HealthHandler | None = None
    log: Callable[[str], None] = lambda line: None
    read_receipts: bool = False
    max_media_mb: int = 25
    allowed: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    backoff_s: tuple[float, ...] = BACKOFF_S
    stable_s: float = STABLE_S
    health_down_s: float = HEALTH_DOWN_S
    ping_every_s: float = PING_EVERY_S
    reply_timeout_s: float = REPLY_TIMEOUT_S

    def __post_init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.state: dict[str, Any] = {"state": "unknown", "me": None, "since": None, "reason": None}
        self.ready = asyncio.Event()
        self.restarts = 0
        self.last_exit: int | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._stop = asyncio.Event()
        self._step = 0
        self._tasks: list[asyncio.Task] = []
        self._down_since: float | None = time.monotonic()
        self._health_sent: str | None = None
        self._connected_at: float | None = None
        self._write_lock = asyncio.Lock()

    # --- ciclo de vida -------------------------------------------------------

    async def run(self) -> None:
        """
        Lanza el puente y lo relanza hasta que alguien llame a stop(). Si
        state/whatsapp/ tiene un enlace simbólico donde va una carpeta, no arranca:
        lanza UnsafePath (código de salida 4 del servicio).
        """
        try:
            self.layout.prepare()
        except UnsafePath as exc:
            self.log(f"whatsapp: no arranca: {exc}")
            self.last_exit = 4
            raise
        watchdog = asyncio.create_task(self._health_watch())
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                rc = await self._run_once()
                self.last_exit = rc
                if self._stop.is_set():
                    break
                if self._connected_at and time.monotonic() - self._connected_at >= self.stable_s:
                    self._step = 0
                elif time.monotonic() - started >= self.stable_s:
                    self._step = 0
                wait = self.backoff_s[min(self._step, len(self.backoff_s) - 1)]
                self._step += 1
                self.restarts += 1
                why = EXIT_REASONS.get(rc or 0, f"salió con {rc}")
                self.log(f"whatsapp: el puente se detuvo ({why}); se relanza en {wait:g} s")
                self._set_state({"state": "bridge_down", "me": self.state.get("me"),
                                 "since": None, "reason": f"exit_{rc}"})
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog

    async def _run_once(self) -> int | None:
        self.ready.clear()
        self.proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=self.env, limit=STDOUT_LINE_MAX + 1024,
            start_new_session=True,
        )
        proc = self.proc
        reader = asyncio.create_task(self._read_stdout(proc))
        errs = asyncio.create_task(self._read_stderr(proc))
        pinger = None
        try:
            await self.request("start", protocol=PROTOCOL, auth_dir=str(self.layout.auth),
                               media_dir=str(self.layout.media), read_receipts=self.read_receipts,
                               max_media_mb=self.max_media_mb, allowed=list(self.allowed))
            self.ready.set()
            pinger = asyncio.create_task(self._ping_loop(proc))
        except BridgeError as exc:
            self.log(f"whatsapp: start falló ({exc.code})")
            await self._kill(proc)
        waiter = asyncio.create_task(proc.wait())
        stopper = asyncio.create_task(self._stop.wait())
        await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if self._stop.is_set() and proc.returncode is None:
            await self._graceful(proc)
        rc = await proc.wait()
        for t in (pinger, stopper, reader, errs):
            if t:
                t.cancel()
        for t in (reader, errs):
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self.ready.clear()
        self._fail_pending("bridge_down")
        return rc

    async def stop(self) -> None:
        self._stop.set()

    async def _graceful(self, proc: asyncio.subprocess.Process) -> None:
        with contextlib.suppress(BridgeError, ConnectionError, OSError):
            await self.request("shutdown", _timeout=SHUTDOWN_GRACE_S)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=SHUTDOWN_GRACE_S)
            return
        await self._kill(proc)

    async def _kill(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=SHUTDOWN_GRACE_S)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    # --- órdenes -------------------------------------------------------------

    async def request(self, type_: str, _timeout: float | None = None, **fields: Any) -> dict:
        """Manda una orden y devuelve `data` del `result`, o lanza BridgeError."""
        proc = self.proc
        if proc is None or proc.returncode is not None or proc.stdin is None:
            raise BridgeError("bridge_down")
        if type_ != "start" and type_ != "shutdown" and not self.ready.is_set():
            raise BridgeError("bridge_down", "el puente no ha arrancado")
        cid = new_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        line = json.dumps({"type": type_, "id": cid, **fields}, ensure_ascii=False) + "\n"
        try:
            async with self._write_lock:
                proc.stdin.write(line.encode("utf-8"))
                await proc.stdin.drain()
        except (ConnectionError, OSError) as exc:
            self._pending.pop(cid, None)
            raise BridgeError("bridge_down", type(exc).__name__) from None
        timeout = _timeout
        if timeout is None:
            timeout = SEND_FILE_TIMEOUT_S if (type_ == "send" and fields.get("file")) else self.reply_timeout_s
        try:
            msg = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise BridgeError("timeout", f"{type_} sin respuesta en {timeout:g} s") from None
        finally:
            self._pending.pop(cid, None)
        if msg.get("type") == "error":
            raise BridgeError(str(msg.get("code")), msg.get("detail"), msg.get("field"))
        return msg.get("data") or {}

    async def set_allowed(self, numbers: list[str]) -> None:
        """La segunda barrera (WHATSAPP_BRIDGE.md §5). Se reenvía en cada `start`."""
        self.allowed = sorted(set(numbers))
        if self.ready.is_set():
            await self.request("allow", allowed=self.allowed)

    def _fail_pending(self, code: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result({"type": "error", "code": code})
        self._pending.clear()

    # --- lo que dice el puente -------------------------------------------------

    async def _read_stdout(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while True:
            try:
                raw = await proc.stdout.readline()
            except (asyncio.LimitOverrunError, ValueError):
                self.log("whatsapp: el puente mandó una línea demasiado larga; se descarta")
                continue
            if not raw:
                return
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.log("whatsapp: línea del puente que no es JSON; se descarta")
                continue
            if not isinstance(msg, dict):
                continue
            ref = msg.get("ref")
            if msg.get("type") in ("result", "error") and ref in self._pending:
                fut = self._pending[ref]
                if not fut.done():
                    fut.set_result(msg)
                continue
            if msg.get("type") == "error":
                self.log(f"whatsapp: error del puente sin orden ({msg.get('code')})")
                continue
            await self._event(msg)

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while True:
            try:
                raw = await proc.stderr.readline()
            except (asyncio.LimitOverrunError, ValueError):
                continue
            if not raw:
                return
            text = raw.decode("utf-8", "replace").rstrip("\n")[:STDERR_LINE_MAX]
            if text:
                self.log(f"whatsapp-bridge: {text}")

    async def _event(self, msg: dict) -> None:
        self.log(f"whatsapp: {describe(msg)}")
        if msg.get("type") == "status":
            self._set_state(msg)
        if self.on_event:
            res = self.on_event(msg)
            if asyncio.iscoroutine(res):
                await res

    def _set_state(self, msg: dict) -> None:
        state = msg.get("state")
        self.state = {k: msg.get(k) for k in ("state", "me", "since", "reason")}
        now = time.monotonic()
        if state == "connected":
            self._down_since = None
            self._connected_at = now
            if self._health_sent:
                self._health_sent = None
                self._health("up", None)
        else:
            self._connected_at = None
            if self._down_since is None:
                self._down_since = now
        if state == "logged_out" and self._health_sent != "logged_out":
            self._health_sent = "logged_out"
            self._health("logged_out", msg.get("reason"))

    def _health(self, kind: str, reason: str | None) -> None:
        if not self.on_health:
            return
        res = self.on_health(kind, reason)
        if asyncio.iscoroutine(res):
            asyncio.ensure_future(res)

    async def _health_watch(self) -> None:
        """Más de health_down_s sin `connected`, un aviso; no se repite (FR-5)."""
        tick = max(min(self.health_down_s / 4, 30.0), 0.05)
        while True:
            await asyncio.sleep(tick)
            if self.state.get("state") == "unlinked" and self._health_sent is None:
                # Sin vincular no es una caída: el dueño todavía no vincula.
                self._down_since = time.monotonic()
                continue
            if (self._down_since is not None and self._health_sent is None
                    and time.monotonic() - self._down_since >= self.health_down_s):
                self._health_sent = "down"
                self._health("down", self.state.get("reason") or self.state.get("state"))

    async def _ping_loop(self, proc: asyncio.subprocess.Process) -> None:
        misses = 0
        while proc.returncode is None:
            await asyncio.sleep(self.ping_every_s)
            try:
                await self.request("ping", _timeout=self.ping_every_s)
                misses = 0
            except BridgeError as exc:
                if exc.code == "bridge_down":
                    return
                misses += 1
                if misses >= PING_MISSES:
                    self.log(f"whatsapp: el puente no contesta {PING_MISSES} pings; se reinicia")
                    await self._kill(proc)
                    return


def auth_is_private(auth: Path) -> bool:
    """auth/ en 0700 y cada archivo en 0600, como exige el puente (código de salida 4)."""
    try:
        st = auth.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
        return False
    for p in auth.iterdir():
        if p.is_symlink() or stat.S_IMODE(p.lstat().st_mode) & 0o077:
            return False
    return True
