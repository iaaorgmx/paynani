#!/usr/bin/env python3
"""macOS bootstrap for paynani.

This is the Darwin half of bootstrap.sh (BOOT-7, #347). It intentionally runs as
the user: Homebrew must not run as root, LaunchAgents are per-user, and
scripts/install_macos.py is the single place that renders launchd artifacts.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EX_OK = 0
EX_STEP = 1
EX_USAGE = 2
EX_UNSUPPORTED = 3
EX_NOT_ROOT = 4

RUNTIMES = ("openclaw", "hermes", "claudecode", "codex", "opencode")
MACOS_RUNTIMES = ("openclaw", "codex", "opencode")
RUNTIME_ROOT = {
    "openclaw": ".openclaw",
    "hermes": ".hermes",
    "claudecode": ".claude",
    "codex": ".codex",
    "opencode": ".opencode",
}
HOMEBREW_INSTALL = "https://brew.sh/"


class BootstrapError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def say(message: str) -> None:
    print(f"bootstrap: {message}")


def die(code: int, message: str) -> None:
    raise BootstrapError(code, message)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Install paynani on macOS as the user, through launchd.",
    )
    p.add_argument("--runtime", default="")
    p.add_argument("--user", default="")
    p.add_argument("--dir", default="")
    p.add_argument("--ref", default="")
    p.add_argument("--env-file", default="")
    p.add_argument("--owner-name", default="")
    p.add_argument("--owner-email", default="")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--with-sms", action="store_true")
    p.add_argument("--upgrade", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--test-mail", action="store_true")
    return p


def run(args: list[str], *, dry_run: bool = False, env: dict[str, str] | None = None,
        capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    if dry_run:
        print("would: " + " ".join(args))
        return subprocess.CompletedProcess(args, 0, "", "")
    return subprocess.run(args, env=env, text=True, capture_output=capture, check=check)


def command_in_path(name: str, path: str | None = None) -> str | None:
    return shutil.which(name, path=path)


def rerun_as_sudo_user(argv: list[str], args: argparse.Namespace) -> None:
    sudo_user = os.environ.get("SUDO_USER", "")
    if not sudo_user or sudo_user == "root":
        die(EX_NOT_ROOT, "macOS installs as the owner, never as root; run: bash bootstrap.sh")
    command = ["sudo", "-u", sudo_user, "-H", sys.executable, str(Path(__file__).resolve()), *argv]
    if args.dry_run:
        print("would: " + " ".join(command))
        raise SystemExit(EX_OK)
    os.execvp("sudo", command)


def validate_options(args: argparse.Namespace) -> None:
    if args.user:
        die(EX_USAGE, "--user is Linux-only on macOS; run bootstrap.sh as the target user")
    if args.runtime:
        if args.runtime not in RUNTIMES:
            die(EX_USAGE, f"--runtime must be one of: {' '.join(RUNTIMES)}")
        if args.runtime not in MACOS_RUNTIMES:
            die(EX_UNSUPPORTED, f"macOS bootstrap currently supports: {' '.join(MACOS_RUNTIMES)}")
    if bool(args.owner_name) != bool(args.owner_email):
        die(EX_USAGE, "--owner-name and --owner-email go together")
    if args.env_file and not Path(args.env_file).is_file():
        die(EX_USAGE, f"--env-file {args.env_file} is not a file")


def homebrew_path() -> str | None:
    override = os.environ.get("BOOTSTRAP_BREW", "")
    candidates = [override, "/opt/homebrew/bin/brew", "/usr/local/bin/brew", command_in_path("brew")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return None


def brew_prefix(brew: str, formula: str) -> Path | None:
    result = subprocess.run([brew, "--prefix", formula], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return None


def python_ok(python: str) -> bool:
    result = subprocess.run(
        [python, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def resolve_service_python(brew: str) -> str | None:
    override = os.environ.get("BOOTSTRAP_SERVICE_PYTHON", "")
    candidates: list[str] = []
    if override:
        candidates.append(override)
    for formula in ("python@3.13", "python@3.12", "python@3.11", "python@3.10"):
        prefix = brew_prefix(brew, formula)
        if prefix:
            version = formula.split("@", 1)[1]
            candidates.extend([str(prefix / "bin" / f"python{version}"), str(prefix / "bin" / "python3")])
    candidates.extend([
        "/opt/homebrew/bin/python3",
        "/opt/homebrew/bin/python3.13",
        "/usr/local/bin/python3",
        "/usr/local/bin/python3.13",
        command_in_path("python3") or "",
    ])
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if Path(candidate).exists() and python_ok(candidate):
            return str(Path(candidate))
    return None


def himalaya_major(path: str) -> str:
    result = subprocess.run([path, "--version"], capture_output=True, text=True)
    text = result.stdout + result.stderr
    for token in text.replace("v", " ").split():
        parts = token.split(".")
        if parts and parts[0].isdigit():
            return parts[0]
    return ""


def ensure_homebrew_tools(args: argparse.Namespace) -> tuple[str, str]:
    brew = homebrew_path()
    if not brew:
        say("Homebrew is required on macOS and is not installed.")
        say(f"Install it from {HOMEBREW_INSTALL}, then run bootstrap.sh again.")
        die(EX_UNSUPPORTED, "Homebrew missing")

    missing = []
    service_python = resolve_service_python(brew)
    if not service_python:
        missing.append("python@3.13")
    himalaya = command_in_path("himalaya")
    if not himalaya or himalaya_major(himalaya) != "2":
        missing.append("himalaya")

    if missing:
        if args.dry_run:
            print(f"would: {brew} install {' '.join(dict.fromkeys(missing))}")
            if not service_python:
                planned_dir = "/opt/homebrew/bin" if str(brew).startswith("/opt/homebrew/") else "/usr/local/bin"
                service_python = str(Path(planned_dir) / "python3.13")
        else:
            run([brew, "install", *dict.fromkeys(missing)])
            service_python = resolve_service_python(brew)
            himalaya = command_in_path("himalaya")

    if not service_python:
        die(EX_UNSUPPORTED, "python3 is older than 3.10 or missing; install python@3.13 with Homebrew")
    if not args.dry_run and (not himalaya or himalaya_major(himalaya) != "2"):
        die(EX_STEP, "himalaya v2.x is still missing after Homebrew install")
    return brew, service_python


def detect_runtimes(home: Path) -> list[str]:
    return [name for name, root in RUNTIME_ROOT.items() if (home / root).is_dir()]


def choose_runtime(args: argparse.Namespace, home: Path) -> str:
    if args.runtime:
        return args.runtime
    found = [name for name in detect_runtimes(home) if name in MACOS_RUNTIMES]
    if len(found) == 1:
        if args.yes:
            return found[0]
        answer = input(f"Found {found[0]}. Install paynani there? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes", "s", "si", "sí"):
            return found[0]
        die(EX_USAGE, "not confirmed: pass --runtime")
    if not found:
        die(EX_USAGE, "no supported macOS harness found: pass --runtime")
    if args.yes or not sys.stdin.isatty():
        die(EX_USAGE, f"several supported harnesses found ({' '.join(found)}): pass --runtime or --dir")
    answer = input(f"Several supported harnesses found: {', '.join(found)}. Which one? ").strip()
    if answer not in found:
        die(EX_USAGE, f"{answer!r} is not one of: {' '.join(found)}")
    return answer


def default_ref() -> str:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", os.environ.get("BOOTSTRAP_REPO_URL", "https://github.com/iaaorgmx/paynani.git"), "v*"],
        capture_output=True,
        text=True,
    )
    tags = [
        tag
        for line in result.stdout.splitlines()
        if line.strip()
        for tag in [line.rsplit("/", 1)[-1]]
        if re.fullmatch(r"v\d+\.\d+\.\d+", tag)
    ]
    if not tags:
        die(EX_STEP, "cannot read release tags: check the network or pass --ref")
    # Tags are vMAJOR.MINOR.PATCH in this project; sort by numeric pieces.
    return sorted(tags, key=lambda t: tuple(int(p) for p in t.lstrip("v").split(".")))[-1]


def resolve_clone(args: argparse.Namespace, runtime: str, home: Path) -> Path:
    if args.dir:
        return Path(args.dir).expanduser().resolve()
    return home / RUNTIME_ROOT[runtime] / "workspace" / "paynani"


def ensure_clone(args: argparse.Namespace, runtime: str) -> tuple[Path, str]:
    home = Path.home()
    clone = resolve_clone(args, runtime, home)
    ref = args.ref or default_ref()
    repo_url = os.environ.get("BOOTSTRAP_REPO_URL", "https://github.com/iaaorgmx/paynani.git")
    if (clone / ".git").is_dir():
        origin = subprocess.run(["git", "-C", str(clone), "remote", "get-url", "origin"],
                                capture_output=True, text=True)
        if "paynani" not in origin.stdout:
            die(EX_USAGE, f"{clone} is a git clone of something else: pass another --dir")
        say(f"using the existing clone at {clone}")
        if args.upgrade:
            run(["git", "-C", str(clone), "fetch", "--tags", "--force", "origin"], dry_run=args.dry_run)
    elif clone.exists() and any(clone.iterdir()):
        die(EX_USAGE, f"{clone} exists and is not empty: pass another --dir")
    else:
        say(f"cloning paynani {ref} into {clone}")
        run(["mkdir", "-p", str(clone.parent)], dry_run=args.dry_run)
        run(["git", "clone", "--branch", ref, repo_url, str(clone)], dry_run=args.dry_run)
    return clone, ref


def run_user_half(args: argparse.Namespace, runtime: str, clone: Path, ref: str, service_python: str) -> int:
    script = clone / "scripts" / "bootstrap_user.py"
    if not args.dry_run and not script.is_file():
        die(EX_STEP, "bootstrap_user.py not found in this ref")
    argv = [service_python, str(script), "--runtime", runtime, "--ref", ref]
    if args.env_file:
        argv += ["--env-file", str(Path(args.env_file).resolve())]
    if args.owner_name:
        argv += ["--owner-name", args.owner_name, "--owner-email", args.owner_email]
    if args.yes:
        argv.append("--yes")
    if args.with_sms:
        argv.append("--with-sms")
    if args.upgrade:
        argv.append("--upgrade")
    if args.dry_run:
        argv.append("--dry-run")
    if args.test_mail:
        argv.append("--test-mail")
    env = dict(os.environ)
    env["PATH"] = f"{Path(service_python).parent}:{env.get('PATH', '')}"
    say("handing over to bootstrap_user.py")
    completed = run(argv, dry_run=args.dry_run, env=env, check=False)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(argv)
    validate_options(args)
    if os.geteuid() == 0:
        rerun_as_sudo_user(argv, args)
    _, service_python = ensure_homebrew_tools(args)
    runtime = choose_runtime(args, Path.home()) if not args.dir else (args.runtime or "")
    if not runtime:
        runtime = choose_runtime(args, Path.home())
    clone, ref = ensure_clone(args, runtime)
    return run_user_half(args, runtime, clone, ref, service_python)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as exc:
        print(f"bootstrap: {exc.message}", file=sys.stderr)
        raise SystemExit(exc.code)
