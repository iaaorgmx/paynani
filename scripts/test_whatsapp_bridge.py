#!/usr/bin/env python3
"""
Tests for the WhatsApp bridge supervisor (WA-1 #553, PRD #550 FR-2, FR-5, FR-6a,
FR-10; WHATSAPP_BRIDGE.md) against the fake bridge, and for the real bridge's
protocol handling when Node 20+ is available.
An assertion script, like the rest of this suite.

Nada se conecta a WhatsApp: el puente falso (scripts/whatsapp_bridge/fake_bridge.py)
sigue el mismo contrato, y el puente real sólo se prueba en lo que hace antes de
cargar Baileys.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

from paynani_lib.whatsapp import bridge  # noqa: E402

FAKE = [sys.executable, str(ROOT / "scripts" / "whatsapp_bridge" / "fake_bridge.py")]
NUM = "+15550001111"
OTHER = "+15550002222"

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


class Harness:
    """Un supervisor con el puente falso, tiempos cortos y todo lo que avisa guardado."""

    def __init__(self, tmp: Path, **kw):
        self.events: list[dict] = []
        self.health: list[tuple] = []
        self.logs: list[str] = []
        opts = dict(backoff_s=(0.05, 0.1, 0.2), stable_s=60, health_down_s=0.6,
                    ping_every_s=0.2, reply_timeout_s=2.0)
        opts.update(kw)
        self.sup = bridge.BridgeSupervisor(
            layout=bridge.Layout(tmp / "state" / "whatsapp"), command=FAKE,
            on_event=self.events.append, on_health=lambda k, r: self.health.append((k, r)),
            log=self.logs.append, allowed=[NUM], **opts)
        self.task: asyncio.Task | None = None

    async def __aenter__(self):
        self.task = asyncio.create_task(self.sup.run())
        await asyncio.wait_for(self.sup.ready.wait(), 5)
        return self

    async def __aexit__(self, *exc):
        await self.sup.stop()
        await asyncio.wait_for(self.task, 15)

    async def until(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            await asyncio.sleep(0.02)
        return False

    def of(self, kind):
        return [e for e in self.events if e.get("type") == kind]


async def scenario_basic(tmp: Path) -> None:
    async with Harness(tmp) as h:
        layout = h.sup.layout
        check("start: el puente arranca y avisa unlinked",
              True, await h.until(lambda: h.sup.state.get("state") == "unlinked"))
        check("state/whatsapp y auth/ quedan en 0700 (FR-10)",
              (0o700, 0o700, 0o700), (mode(layout.root), mode(layout.auth), mode(layout.media)))

        # Vincular por código: el código llega como aviso, nunca al log (FR-6a).
        await h.sup.request("link", mode="code", number=NUM)
        await h.until(lambda: h.of("link.code"))
        code = h.of("link.code")[0]["code"]
        check("link code: el aviso trae el código y su vencimiento",
              True, len(code) == 9 and "expires_at" in h.of("link.code")[0])
        check("link code: el código no aparece en el log", False, any(code in line for line in h.logs))
        check("link code: el log dice que hubo una credencial sin escribirla",
              True, any("link.code (credencial, no se registra)" in line for line in h.logs))
        check("link code: nada en disco trae el código", False,
              any(code in p.read_text(errors="ignore") for p in layout.root.rglob("*") if p.is_file()))

        await h.sup.request("fake.link_done")
        check("vinculado: status connected", True, await h.until(lambda: h.sup.state.get("state") == "connected"))
        creds = layout.auth / "creds.json"
        check("las llaves quedan en 0600 (FR-10)", 0o600, mode(creds))

        # Un mensaje que llega pasa tal cual al servicio, sin texto en el log.
        await h.sup.request("fake.message", from_e164=NUM, text="mesa para cuatro", key_id="3EB0AA")
        await h.until(lambda: h.of("message"))
        msg = h.of("message")[0]
        check("message: llega con from.e164, key_id y texto",
              (NUM, "3EB0AA", "mesa para cuatro"), (msg["from"]["e164"], msg["key_id"], msg["text"]))
        check("message: el texto no va al log", False, any("mesa para cuatro" in line for line in h.logs))

        # Envío: allowed es la segunda barrera.
        data = await h.sup.request("send", to=NUM, text="sí hay")
        check("send a un número de allowed: result con key_id", True, bool(data.get("key_id")))
        try:
            await h.sup.request("send", to=OTHER, text="hola")
            check("send fuera de allowed: not_allowed", "not_allowed", "result")
        except bridge.BridgeError as exc:
            check("send fuera de allowed: not_allowed", "not_allowed", exc.code)
        await h.sup.set_allowed([NUM, OTHER])
        data = await h.sup.request("send", to=OTHER, text="hola")
        check("set_allowed amplía la lista del puente", True, bool(data.get("key_id")))

        # Una orden desconocida no tumba al puente.
        try:
            await h.sup.request("nada")
        except bridge.BridgeError as exc:
            check("orden desconocida: unknown_type", "unknown_type", exc.code)
        check("después de un error el puente sigue", "connected", (await h.sup.request("ping"))["state"])

        # stderr: va al log, cortado a 1 KB.
        await h.sup.request("fake.stderr", text="x" * 5000)
        await h.until(lambda: any(line.startswith("whatsapp-bridge: x") for line in h.logs))
        long = [line for line in h.logs if line.startswith("whatsapp-bridge: x")]
        check("stderr del puente: cada línea se corta a 1 KB", True,
              bool(long) and len(long[0]) <= len("whatsapp-bridge: ") + bridge.STDERR_LINE_MAX)

    check("stop: el puente sale y no se relanza", 0, h.sup.last_exit)


async def scenario_restart(tmp: Path) -> None:
    async with Harness(tmp) as h:
        first = h.sup.proc.pid
        await h.sup.request("link", mode="qr")
        await h.until(lambda: h.of("link.qr"))
        qr = h.of("link.qr")[0]["qr"]
        check("link qr: el QR no va al log", False, any(qr in line for line in h.logs))
        await h.sup.request("fake.link_done", me=NUM)
        await h.until(lambda: h.sup.state.get("state") == "connected")

        # Se cae: el supervisor lo relanza y, con llaves, vuelve a conectar.
        try:
            await h.sup.request("fake.crash", code=1, _timeout=1)
        except bridge.BridgeError:
            pass
        check("crash: se relanza", True, await h.until(lambda: h.sup.restarts >= 1 and h.sup.ready.is_set()))
        check("crash: es otro proceso", True, h.sup.proc.pid != first)
        check("crash: con llaves vuelve a connected", True,
              await h.until(lambda: h.sup.state.get("state") == "connected"))
        check("crash: el log dice por qué y cuánto espera", True,
              any("se relanza en" in line for line in h.logs))

        # Deja de contestar: tres pings sin respuesta y se reinicia.
        before = h.sup.restarts
        # Sin esperar respuesta: un puente colgado no contesta ni esta orden.
        h.sup.proc.stdin.write(json.dumps({"type": "fake.hang", "id": bridge.new_id()}).encode() + b"\n")
        check("colgado: los pings lo detectan y se reinicia", True,
              await h.until(lambda: h.sup.restarts > before and h.sup.ready.is_set(), timeout=8))
        check("colgado: el log lo dice", True, any("no contesta" in line for line in h.logs))


async def scenario_health(tmp: Path) -> None:
    async with Harness(tmp) as h:
        await h.sup.request("link", mode="code", number=NUM)
        await h.sup.request("fake.link_done")
        await h.until(lambda: h.sup.state.get("state") == "connected")
        await h.sup.request("fake.disconnect")
        check("desconectado más del umbral: un whatsapp.health down (FR-5)", True,
              await h.until(lambda: ("down", "connection_lost") in h.health, timeout=3))
        await asyncio.sleep(0.8)
        check("...una sola vez mientras sigue el problema", 1, sum(1 for k, _ in h.health if k == "down"))
        await h.sup.request("fake.reconnect")
        check("al volver: health up", True, await h.until(lambda: ("up", None) in h.health))

        await h.sup.request("fake.logged_out")
        check("logged_out: health logged_out en seguida", True,
              await h.until(lambda: any(k == "logged_out" for k, _ in h.health)))
        check("logged_out: el puente borró las llaves", [], list(h.sup.layout.auth.iterdir()))
        n = len(h.health)
        await asyncio.sleep(1.0)
        check("sin vincular no cuenta como caída", n, len(h.health))


async def scenario_start_failures(tmp: Path) -> None:
    # auth/ abierto: el puente sale con 4 y el supervisor lo dice.
    h = Harness(tmp, backoff_s=(0.05,))
    h.sup.layout.prepare()
    (h.sup.layout.auth / "creds.json").write_text("{}")
    os.chmod(h.sup.layout.auth / "creds.json", 0o644)
    h.sup.layout.prepare()  # prepare() vuelve a cerrar los permisos
    check("prepare(): deja los archivos de auth/ en 0600", 0o600, mode(h.sup.layout.auth / "creds.json"))
    check("auth_is_private: sí después de prepare()", True, bridge.auth_is_private(h.sup.layout.auth))
    os.chmod(h.sup.layout.auth / "creds.json", 0o644)
    check("auth_is_private: no con un archivo 0644", False, bridge.auth_is_private(h.sup.layout.auth))

    env = dict(os.environ, FAKE_BRIDGE_EXIT="2")
    h2 = Harness(tmp / "b", env=env, backoff_s=(0.05,))
    task = asyncio.create_task(h2.sup.run())
    await h2.until(lambda: h2.sup.restarts >= 2)
    await h2.sup.stop()
    await asyncio.wait_for(task, 10)
    check("exit 2: el log nombra la causa (npm ci)", True,
          any("npm ci" in line for line in h2.logs))
    check("exit 2: sigue reintentando con espera, sin ready", True, h2.sup.restarts >= 2)


async def scenario_symlinks(tmp: Path) -> None:
    """Ximena en #564: un enlace donde va una carpeta no se sigue, ni se cambia ni se borra."""
    outside = tmp / "ajeno"
    outside.mkdir(parents=True)
    os.chmod(outside, 0o755)
    victim = outside / "importante.txt"
    victim.write_text("no tocar")
    os.chmod(victim, 0o644)

    def untouched():
        return (victim.exists(), victim.read_text(), mode(victim), mode(outside)) == (True, "no tocar", 0o644, 0o755)

    for name in ("auth", "media", "outbox"):
        layout = bridge.Layout(tmp / name / "state" / "whatsapp")
        layout.root.mkdir(parents=True)
        os.symlink(outside, layout.root / name)
        h = Harness(tmp / name)
        h.sup.layout = layout
        try:
            await asyncio.wait_for(h.sup.run(), 5)
            raised = False
        except bridge.UnsafePath:
            raised = True
        check(f"{name}/ es un enlace: el supervisor no arranca (UnsafePath)", True, raised)
        check(f"{name}/ es un enlace: el destino queda intacto (permisos y archivo)", True, untouched())
        check(f"{name}/ es un enlace: el log lo dice", True, any("no arranca" in line for line in h.logs))
        check(f"{name}/ es un enlace: el puente nunca se lanzó", None, h.sup.proc)

    layout = bridge.Layout(tmp / "root" / "state" / "whatsapp")
    layout.root.parent.mkdir(parents=True)
    os.symlink(outside, layout.root)
    try:
        layout.prepare()
        check("state/whatsapp es un enlace: UnsafePath", True, False)
    except bridge.UnsafePath:
        check("state/whatsapp es un enlace: UnsafePath", True, True)
    check("state/whatsapp es un enlace: el destino queda intacto", True, untouched())

    layout = bridge.Layout(tmp / "child" / "state" / "whatsapp")
    layout.prepare()
    os.symlink(victim, layout.auth / "creds.json")
    layout.prepare()
    check("un enlace dentro de auth/: se quita el enlace", False, (layout.auth / "creds.json").is_symlink())
    check("un enlace dentro de auth/: el destino queda intacto", True, untouched())

    auth = tmp / "fake-link" / "auth"
    auth.parent.mkdir()
    os.symlink(outside, auth)
    start = {"type": "start", "id": bridge.new_id(), "protocol": 1, "auth_dir": str(auth),
             "media_dir": str(tmp / "fake-link" / "media")}
    p = subprocess.run(FAKE, input=json.dumps(start) + "\n", capture_output=True, text=True, timeout=10)
    check("puente falso: auth/ enlazado sale con 4", 4, p.returncode)
    check("puente falso: auth/ enlazado no toca el destino", True, untouched())


def scenario_fake_stdin_eof(tmp: Path) -> None:
    auth = tmp / "eof" / "auth"
    auth.mkdir(parents=True, mode=0o700)
    start = {"type": "start", "id": bridge.new_id(), "protocol": 1, "auth_dir": str(auth),
             "media_dir": str(tmp / "eof" / "media")}
    p = subprocess.run(FAKE, input=json.dumps(start) + "\n", capture_output=True, text=True, timeout=10)
    check("puente falso: stdin cerrado es un cierre normal (código 0)", 0, p.returncode)
    p = subprocess.run(FAKE, input=json.dumps({**start, "protocol": 2}) + "\n",
                       capture_output=True, text=True, timeout=10)
    check("puente falso: protocolo distinto sale con 3", 3, p.returncode)


def describe_checks() -> None:
    check("describe: link.code no lleva el código", True,
          "ABCD" not in bridge.describe({"type": "link.code", "code": "ABCD-EFGH"}))
    check("describe: message no lleva el texto ni el push_name", True,
          "hola" not in bridge.describe({"type": "message", "kind": "text", "text": "hola", "push_name": "hola"}))
    check("new_id: c_ + 32 hex", True, bridge.new_id().startswith("c_") and len(bridge.new_id()) == 34)


def node_checks(tmp: Path) -> None:
    """El puente real, en lo que hace antes de cargar Baileys (sin red, sin npm ci)."""
    major = bridge.node_major()
    if major is None or major < 20:
        print(f"skip puente real: Node {major} (hace falta 20 o más)")
        return
    index = ROOT / "scripts" / "whatsapp_bridge" / "index.js"
    auth = tmp / "real" / "auth"
    auth.mkdir(parents=True, mode=0o700)
    lines = [
        "no es json",
        json.dumps({"type": "ping", "id": bridge.new_id()}),
        json.dumps({"type": "ping"}),
        json.dumps({"type": "start", "id": bridge.new_id(), "protocol": 2,
                    "auth_dir": str(auth), "media_dir": str(tmp / "real" / "media")}),
    ]
    p = subprocess.run(["node", str(index)], input="\n".join(lines) + "\n",
                       capture_output=True, text=True, timeout=30)
    out = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    codes = [m.get("code") for m in out]
    check("puente real: bad_json, not_started, missing_field id, unsupported_protocol",
          ["bad_json", "not_started", "missing_field", "unsupported_protocol"], codes)
    check("puente real: protocolo distinto sale con 3", 3, p.returncode)

    os.chmod(auth, 0o755)
    start = json.dumps({"type": "start", "id": bridge.new_id(), "protocol": 1,
                        "auth_dir": str(auth), "media_dir": str(tmp / "real" / "media")})
    p = subprocess.run(["node", str(index)], input=start + "\n", capture_output=True, text=True, timeout=30)
    check("puente real: auth/ en 0755 no arranca (código 4)", 4, p.returncode)
    os.chmod(auth, 0o700)

    outside = tmp / "real-ajeno"
    outside.mkdir()
    os.chmod(outside, 0o700)
    (outside / "importante.txt").write_text("no tocar")
    linked = tmp / "real-link" / "auth"
    linked.parent.mkdir()
    os.symlink(outside, linked)
    start_link = json.dumps({"type": "start", "id": bridge.new_id(), "protocol": 1,
                             "auth_dir": str(linked), "media_dir": str(tmp / "real-link" / "media")})
    p = subprocess.run(["node", str(index)], input=start_link + "\n", capture_output=True, text=True, timeout=30)
    check("puente real: auth/ enlazado (aunque el destino sea 0700) sale con 4", 4, p.returncode)
    check("puente real: auth/ enlazado no toca el destino", True,
          (outside / "importante.txt").read_text() == "no tocar")

    os.symlink(outside, tmp / "real" / "media-link")
    start_media = json.dumps({"type": "start", "id": bridge.new_id(), "protocol": 1,
                              "auth_dir": str(auth), "media_dir": str(tmp / "real" / "media-link")})
    p = subprocess.run(["node", str(index)], input=start_media + "\n", capture_output=True, text=True, timeout=30)
    check("puente real: media/ enlazado sale con 4", 4, p.returncode)

    if not (ROOT / "scripts" / "whatsapp_bridge" / "node_modules" / "baileys").is_dir():
        p = subprocess.run(["node", str(index)], input=start + "\n", capture_output=True, text=True, timeout=30)
        check("puente real sin npm ci: sale con 2 y lo dice en stderr", (2, True),
              (p.returncode, "npm ci" in p.stderr))
    lib = subprocess.run(["node", "--test", str(ROOT / "scripts" / "whatsapp_bridge" / "test" / "lib.test.js")],
                         capture_output=True, text=True, timeout=60)
    check("puente real: node --test de lib.js", 0, lib.returncode)
    if lib.returncode:
        print(lib.stdout[-3000:], lib.stderr[-2000:])


async def main_async() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        await scenario_basic(tmp / "basic")
        await scenario_restart(tmp / "restart")
        await scenario_health(tmp / "health")
        await scenario_start_failures(tmp / "fail")
        await scenario_symlinks(tmp / "links")
        scenario_fake_stdin_eof(tmp)
        describe_checks()
        node_checks(tmp)


if __name__ == "__main__":
    asyncio.run(main_async())
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
