#!/usr/bin/env python3
"""Install paynani on macOS using per-user LaunchAgents."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

from paths import env_file, runtime_env, state_dir  # noqa: E402

EX_OK = 0
EX_CHANGED = 10
EX_USAGE = 64
EX_CONFIG = 78

LABELS = {
    "idle": "com.paynani.idle",
    "dispatch": "com.paynani.dispatch",
    "logrotate": "com.paynani.logrotate",
}


def die(message: str, code: int = EX_CONFIG) -> None:
    print(f"install: {message}", file=sys.stderr)
    raise SystemExit(code)


def gui_domain() -> str:
    return f"gui/{os.getuid()}"


def launch_agent_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(name: str) -> Path:
    return launch_agent_dir() / f"{LABELS[name]}.plist"


def agent_env(runtime: str, runtime_bin: str | None = None) -> dict[str, str]:
    path_parts = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    if runtime_bin:
        path_parts.insert(0, str(Path(runtime_bin).parent))
    env = {
        "PAYNANI_RUNTIME": runtime,
        "PAYNANI_ENV": str(env_file()),
        "PATH": ":".join(dict.fromkeys(path_parts)),
    }
    if runtime == "openclaw" and runtime_bin:
        env["OPENCLAW"] = runtime_bin
    return env


def plist_for(name: str, python: str, runtime: str, runtime_bin: str | None = None) -> dict:
    state = state_dir()
    env = agent_env(runtime, runtime_bin)
    if name == "idle":
        return {
            "Label": LABELS[name],
            "ProgramArguments": [
                python,
                str(ROOT / "scripts" / "idle_listener.py"),
                "--env",
                str(env_file()),
            ],
            "WorkingDirectory": str(ROOT),
            "RunAtLoad": True,
            "KeepAlive": True,
            "EnvironmentVariables": env,
            "StandardOutPath": str(state / "mail.log"),
            "StandardErrorPath": str(state / "idle.err.log"),
        }
    if name == "dispatch":
        return {
            "Label": LABELS[name],
            "ProgramArguments": [python, str(ROOT / "harness" / "dispatch.py")],
            "WorkingDirectory": str(ROOT),
            "RunAtLoad": True,
            "KeepAlive": True,
            "EnvironmentVariables": env,
            "StandardOutPath": str(state / "dispatch.log"),
            "StandardErrorPath": str(state / "dispatch.err.log"),
        }
    if name == "logrotate":
        return {
            "Label": LABELS[name],
            "ProgramArguments": [python, str(ROOT / "harness" / "rotate_logs.py")],
            "WorkingDirectory": str(ROOT),
            "StartCalendarInterval": {"Hour": 3, "Minute": 17},
            "EnvironmentVariables": env,
            "StandardOutPath": str(state / "logrotate.log"),
            "StandardErrorPath": str(state / "logrotate.err.log"),
        }
    raise ValueError(name)


def read_plist(path: Path) -> dict | None:
    try:
        with path.open("rb") as fh:
            return plistlib.load(fh)
    except FileNotFoundError:
        return None
    except Exception as exc:
        die(f"{path} exists but is not a readable plist: {exc}")


def plist_owned_by_this_checkout(path: Path) -> bool:
    data = read_plist(path)
    if data is None:
        return True
    args = data.get("ProgramArguments")
    if not isinstance(args, list):
        return False
    return any(str(ROOT) in str(arg) for arg in args)


def write_plist(path: Path, payload: dict) -> bool:
    old = None
    if path.exists():
        with path.open("rb") as fh:
            old = fh.read()
    data = plistlib.dumps(payload, sort_keys=True)
    if old == data:
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o644)
    tmp.replace(path)
    return True


def run_launchctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        die(f"launchctl {' '.join(args)} failed: {detail}")
    return result


def service_state(label: str) -> str:
    result = run_launchctl("print", f"{gui_domain()}/{label}")
    if result.returncode != 0:
        return "inactive"
    text = result.stdout
    if "state = running" in text:
        return "active"
    return "loaded"


def bootstrap(path: Path, label: str) -> bool:
    before = service_state(label)
    if before != "inactive":
        run_launchctl("bootout", gui_domain(), str(path))
    run_launchctl("bootstrap", gui_domain(), str(path), check=True)
    run_launchctl("enable", f"{gui_domain()}/{label}")
    after = service_state(label)
    for _ in range(20):
        if after == "active":
            break
        time.sleep(0.25)
        after = service_state(label)
    if after not in ("active", "loaded"):
        die(f"{label} did not load; state is {after}")
    return before != after


def secure_existing_env(path: Path) -> None:
    if not path.exists():
        die(f"no credentials at {path}; set PAYNANI_ENV or create the harness .env first")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        die(f"credentials at {path} are mode {mode:o}; expected 600 or 400")


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install paynani on macOS with launchd."
    )
    parser.add_argument("--runtime", required=True, choices=("openclaw", "hermes", "codex"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--deliver")
    parser.add_argument("--chat-id")
    parser.add_argument("--profile")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--notify-secret-file")
    parser.add_argument("--roster-secret-file")
    args = parser.parse_args(argv)
    if args.runtime == "hermes":
        die("macOS install currently supports --runtime openclaw and codex only", EX_USAGE)
    modes = sum(bool(x) for x in (args.upgrade, args.uninstall))
    if modes > 1:
        die("--upgrade and --uninstall are mutually exclusive", EX_USAGE)
    return args


def print_plan(runtime: str, runtime_bin: str | None, python: str, args: argparse.Namespace) -> int:
    print(f"discovery runtime={runtime}")
    print(f"repo_root={ROOT}")
    print(f"platform=macos-launchd")
    print(f"python={python}")
    print(f"runtime_cli={runtime_bin or f'not-required-for-{runtime}'}")
    print(f"credentials={env_file()}")
    print(f"state_dir={state_dir()}")
    print(f"launch_agent_dir={launch_agent_dir()}")
    print("runtime_probe=deferred (dry-run never executes runtime code)" if args.dry_run else "runtime_probe=launchd")
    for name in ("idle", "dispatch", "logrotate"):
        path = plist_path(name)
        if not plist_owned_by_this_checkout(path):
            print(f"inventory conflict-preserve-file={path} reason=unproven-ownership")
            return EX_CONFIG
        state = "existing" if path.exists() else "planned"
        print(f"inventory {state}-launchagent={path} label={LABELS[name]}")
    print(f"inventory planned-runtime-env={runtime_env()}")
    return EX_CHANGED


def uninstall(args: argparse.Namespace) -> int:
    changed = False
    for name, label in LABELS.items():
        path = plist_path(name)
        if path.exists() and not plist_owned_by_this_checkout(path):
            die(f"refusing to remove unowned LaunchAgent: {path}")
        if args.dry_run:
            print(f"inventory planned-remove-launchagent={path}")
            continue
        run_launchctl("bootout", gui_domain(), str(path))
        if path.exists():
            path.unlink()
            changed = True
            print(f"removed_launchagent={path}")
    if not args.dry_run and runtime_env().exists():
        runtime_env().unlink()
        changed = True
        print(f"removed_runtime_env={runtime_env()}")
    if args.dry_run:
        return EX_CHANGED
    return EX_CHANGED if changed else EX_OK


def write_runtime_env(runtime: str, runtime_bin: str | None = None) -> bool:
    path = runtime_env()
    lines = [f'PAYNANI_RUNTIME="{runtime}"\n']
    if runtime == "openclaw" and runtime_bin:
        lines.append(f'OPENCLAW="{runtime_bin}"\n')
    lines.append(f'PAYNANI_ENV="{env_file()}"\n')
    lines.append('PAYNANI_SUPERVISOR="launchd"\n')
    desired = "".join(lines)
    current = path.read_text() if path.exists() else None
    if current == desired:
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(desired, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return True


def install(args: argparse.Namespace) -> int:
    python = sys.executable
    runtime_bin = None
    if args.runtime == "openclaw":
        runtime_bin = os.environ.get("OPENCLAW") or shutil.which("openclaw")
        if not runtime_bin:
            die("openclaw executable not found in PATH; set OPENCLAW to an absolute path")
        runtime_bin = str(Path(runtime_bin).resolve())
        if not Path(runtime_bin).exists():
            die(f"OPENCLAW path does not exist: {runtime_bin}")
    if not shutil.which("himalaya"):
        die("himalaya executable not found in PATH; install Himalaya before running paynani")
    secure_existing_env(env_file())
    plan_status = print_plan(args.runtime, runtime_bin, python, args)
    if args.dry_run:
        return plan_status

    changed = False
    state_dir().mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir(), 0o700)
    launch_agent_dir().mkdir(parents=True, exist_ok=True)
    changed = write_runtime_env(args.runtime, runtime_bin) or changed
    for name, label in LABELS.items():
        path = plist_path(name)
        if not plist_owned_by_this_checkout(path):
            die(f"refusing to overwrite unowned LaunchAgent: {path}")
        changed = write_plist(path, plist_for(name, python, args.runtime, runtime_bin)) or changed
        changed = bootstrap(path, label) or changed
        print(f"launchagent={path} label={label} state={service_state(label)}")

    if args.runtime == "openclaw":
        result = subprocess.run([runtime_bin, "--version"], capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            die(f"OpenClaw probe failed: {detail}")
        print(f"openclaw_probe=accepted executable={runtime_bin}")
    else:
        print(f"codex_spool_probe=accepted spool={state_dir() / 'codex.spool'}")
        print("codex_spool_probe=queue-or-replay scope=writability-only")
    print("verification_report_end result=passed")
    return EX_CHANGED if changed else EX_OK


def main(argv: list[str]) -> int:
    if sys.platform != "darwin":
        die("install_macos.py is only for macOS hosts", EX_USAGE)
    args = parse(argv)
    if args.uninstall:
        return uninstall(args)
    return install(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
