#!/usr/bin/env python3
"""Tests for the macOS bootstrap half (BOOT-7, #347)."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import stat
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bootstrap_macos as bm  # noqa: E402


failures = []
passed = 0


def check(name, condition, detail=""):
    global passed
    if condition:
        passed += 1
        print(f"ok   {name}")
    else:
        failures.append(name)
        print(f"FAIL {name}" + (f"\n     {detail}" if detail else ""))


class World:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bootstrap-macos-")).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.calls = self.tmp / "calls.log"
        self.calls.write_text("", encoding="utf-8")
        self.brew_prefix = self.tmp / "brew"
        (self.brew_prefix / "bin").mkdir(parents=True)
        self.python = self.brew_prefix / "bin" / "python3.13"
        self.python.write_text(
            "#!/usr/bin/env bash\n"
            "if [ \"$1\" = \"-c\" ]; then exit 0; fi\n"
            "echo python \"$@\" >>\"$CALLS\"\n",
            encoding="utf-8",
        )
        self.python.chmod(0o700)
        self._write(
            "brew",
            f"""\
            #!/usr/bin/env bash
            echo brew "$@" >>"$CALLS"
            if [ "$1" = "--prefix" ]; then
              case "$2" in
                python@3.13) printf '%s\\n' "{self.brew_prefix}" ;;
                *) exit 1 ;;
              esac
              exit 0
            fi
            exit 0
            """,
        )
        self._write("himalaya", "#!/usr/bin/env bash\necho 'himalaya v2.1.0'\n")
        self._write(
            "git",
            """\
            #!/usr/bin/env bash
            echo git "$@" >>"$CALLS"
            if [ "$1" = "ls-remote" ]; then
              printf 'aaa\\trefs/tags/v0.11.0\\n'
              printf 'bbb\\trefs/tags/v0.12.0\\n'
              exit 0
            fi
            exit 0
            """,
        )
        self._write(
            "curl",
            """\
            #!/usr/bin/env bash
            echo curl "$@" >>"$CALLS"
            out=""
            url=""
            while [ $# -gt 0 ]; do
              case "$1" in
                -o) out=$2; shift 2 ;;
                -*) shift ;;
                *) url=$1; shift ;;
              esac
            done
            case "$url" in
              file://*) cp "${url#file://}" "$out" ;;
              *) exit 22 ;;
            esac
            """,
        )
        self.saved_env = {k: os.environ.get(k) for k in (
            "HOME", "PATH", "BOOTSTRAP_BREW", "BOOTSTRAP_SERVICE_PYTHON", "CALLS", "BOOTSTRAP_REPO_URL",
        )}
        os.environ["HOME"] = str(self.home)
        os.environ["PATH"] = f"{self.bin}:{os.environ.get('PATH', '')}"
        os.environ["BOOTSTRAP_BREW"] = str(self.bin / "brew")
        os.environ["BOOTSTRAP_SERVICE_PYTHON"] = str(self.python)
        os.environ["CALLS"] = str(self.calls)
        os.environ["BOOTSTRAP_REPO_URL"] = "https://example.invalid/paynani.git"

    def _write(self, name: str, body: str) -> Path:
        path = self.bin / name
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        path.chmod(0o700)
        return path

    def close(self):
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def run(self, *args, patch_root=False):
        if patch_root:
            old_root = bm.ROOT
            bm.ROOT = self.home / ".openclaw" / "workspace" / "paynani"
            (bm.ROOT / "scripts").mkdir(parents=True)
            (bm.ROOT / "scripts" / "bootstrap_user.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        else:
            old_root = None
        out = io.StringIO()
        err = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = bm.main(list(args))
        except SystemExit as exc:
            code = int(exc.code or 0)
        except bm.BootstrapError as exc:
            print(f"bootstrap: {exc.message}", file=err)
            code = exc.code
        finally:
            if patch_root:
                bm.ROOT = old_root
        return code, out.getvalue(), err.getvalue()

    def run_bootstrap_file(self, *args, pipe=False, url=None):
        bootstrap = self.tmp / "standalone" / "bootstrap.sh"
        bootstrap.parent.mkdir()
        shutil.copy(ROOT / "bootstrap.sh", bootstrap)
        env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/bin:/usr/bin",
            "BOOTSTRAP_UNAME": "Darwin",
            "BOOTSTRAP_SKIP_CLT_CHECK": "1",
            "BOOTSTRAP_BREW": str(self.bin / "brew"),
            "BOOTSTRAP_SERVICE_PYTHON": str(self.python),
            "BOOTSTRAP_REPO_URL": "https://example.invalid/paynani.git",
        }
        if url is not None:
            env["BOOTSTRAP_MACOS_SCRIPT_URL"] = url
        else:
            env["BOOTSTRAP_MACOS_SCRIPT_URL"] = f"file://{ROOT / 'scripts' / 'bootstrap_macos.py'}"
        command = ["bash", str(bootstrap), *args]
        kwargs = {"text": True, "capture_output": True, "env": env, "timeout": 20}
        if pipe:
            return subprocess.run(["bash", "-s", "--", *args], input=bootstrap.read_text(encoding="utf-8"), **kwargs)
        return subprocess.run(command, **kwargs)

    def run_bootstrap_without_clt(self, *args):
        bootstrap = self.tmp / "no-clt" / "bootstrap.sh"
        bootstrap.parent.mkdir()
        shutil.copy(ROOT / "bootstrap.sh", bootstrap)
        self._write("xcode-select", "#!/usr/bin/env bash\nexit 1\n")
        env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/bin:/usr/bin",
            "BOOTSTRAP_UNAME": "Darwin",
        }
        return subprocess.run(["bash", str(bootstrap), *args], text=True, capture_output=True, env=env, timeout=20)


def with_world(fn):
    world = World()
    try:
        fn(world)
    finally:
        world.close()


def dry_run_fresh_openclaw(w: World):
    code, out, err = w.run("--runtime", "openclaw", "--yes", "--dry-run")
    text = out + err
    check("macOS dry-run exits 0", code == 0, text)
    check("macOS dry-run never invokes sudo", "sudo " not in text, text)
    check("macOS dry-run plans the clone at the OpenClaw workspace",
          "would: git clone --branch v0.12.0 https://example.invalid/paynani.git" in text
          and ".openclaw/workspace/paynani" in text, text)
    check("macOS dry-run hands over through the Homebrew Python",
          f"would: {w.python}" in text and "scripts/bootstrap_user.py" in text, text)


with_world(dry_run_fresh_openclaw)


def default_ref_ignores_release_candidates(w: World):
    (w.bin / "git").write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            echo git "$@" >>"$CALLS"
            if [ "$1" = "ls-remote" ]; then
              printf 'aaa\\trefs/tags/v0.4.0-rc1\\n'
              printf 'bbb\\trefs/tags/v0.9.1\\n'
              printf 'ccc\\trefs/tags/v0.10.0\\n'
              printf 'ddd\\trefs/tags/v0.11.0\\n'
              exit 0
            fi
            exit 0
            """
        ),
        encoding="utf-8",
    )
    (w.bin / "git").chmod(0o700)
    code, out, err = w.run("--runtime", "openclaw", "--yes", "--dry-run")
    text = out + err
    check("default ref ignores prerelease tags", code == 0 and "ValueError" not in text, text)
    check("default ref chooses the latest final semver tag",
          "would: git clone --branch v0.11.0 https://example.invalid/paynani.git" in text, text)
    check("default ref sorts versions numerically", "branch v0.9.1" not in text and "branch v0.10.0" not in text, text)


with_world(default_ref_ignores_release_candidates)


def missing_homebrew_stops(w: World):
    old = bm.homebrew_path
    bm.homebrew_path = lambda: None
    try:
        code, out, err = w.run("--runtime", "openclaw", "--yes", "--dry-run")
    finally:
        bm.homebrew_path = old
    text = out + err
    check("missing Homebrew exits 3", code == 3, text)
    check("missing Homebrew points at brew.sh", "https://brew.sh/" in text, text)


with_world(missing_homebrew_stops)


def dry_run_plans_missing_formulae(w: World):
    os.environ.pop("BOOTSTRAP_SERVICE_PYTHON", None)
    (w.bin / "himalaya").unlink()
    os.environ["PATH"] = f"{w.bin}:/bin:/usr/bin"
    code, out, err = w.run("--runtime", "openclaw", "--yes", "--dry-run")
    text = out + err
    check("dry-run plans brew install without mutating", code == 0 and "would: " in text, text)
    check("dry-run includes himalaya in the Homebrew plan",
          "brew install himalaya" in text, text)


with_world(dry_run_plans_missing_formulae)


def root_dry_run_reexecs_as_sudo_user(w: World):
    old_geteuid = bm.os.geteuid
    saved_sudo = os.environ.get("SUDO_USER")
    bm.os.geteuid = lambda: 0
    os.environ["SUDO_USER"] = "ada"
    try:
        code, out, err = w.run("--runtime", "openclaw", "--dry-run")
    finally:
        bm.os.geteuid = old_geteuid
        if saved_sudo is None:
            os.environ.pop("SUDO_USER", None)
        else:
            os.environ["SUDO_USER"] = saved_sudo
    text = out + err
    check("sudo on macOS dry-run re-execs as SUDO_USER", code == 0 and "would: sudo -u ada -H" in text, text)
    check("sudo on macOS dry-run does not continue to Homebrew", "brew install" not in text, text)


with_world(root_dry_run_reexecs_as_sudo_user)


def unsupported_runtime(w: World):
    code, out, err = w.run("--runtime", "hermes", "--yes", "--dry-run")
    text = out + err
    check("macOS rejects unsupported runtimes before Homebrew", code == 3, text)
    check("the supported set is named", "openclaw codex opencode" in text, text)


with_world(unsupported_runtime)


def standalone_bootstrap_downloads_helper(w: World):
    result = w.run_bootstrap_file("--runtime", "openclaw", "--dry-run")
    text = result.stdout + result.stderr
    check("standalone bootstrap.sh downloads the macOS helper", result.returncode == 0, text)
    check("standalone bootstrap.sh reaches the clone plan", "would: git clone" in text, text)


with_world(standalone_bootstrap_downloads_helper)


def piped_bootstrap_downloads_helper(w: World):
    result = w.run_bootstrap_file("--runtime", "openclaw", "--dry-run", pipe=True)
    text = result.stdout + result.stderr
    check("piped bootstrap.sh has no BASH_SOURCE crash", "BASH_SOURCE" not in text, text)
    check("piped bootstrap.sh downloads the helper and plans clone",
          result.returncode == 0 and "would: git clone" in text, text)


with_world(piped_bootstrap_downloads_helper)


def helper_download_failure_is_clear(w: World):
    result = w.run_bootstrap_file("--runtime", "openclaw", "--dry-run",
                                  url="https://example.invalid/no-bootstrap-macos.py")
    text = result.stdout + result.stderr
    check("missing downloaded helper exits 1", result.returncode == 1, text)
    check("missing downloaded helper names the URL and --ref",
          "cannot download scripts/bootstrap_macos.py from https://example.invalid/no-bootstrap-macos.py" in text
          and "pass --ref" in text, text)


with_world(helper_download_failure_is_clear)


def missing_command_line_tools_stops_before_python(w: World):
    result = w.run_bootstrap_without_clt("--runtime", "openclaw", "--dry-run")
    text = result.stdout + result.stderr
    check("missing Command Line Tools exits 3 before python", result.returncode == 3, text)
    check("missing Command Line Tools message points at Homebrew",
          "macOS needs Homebrew first" in text and "https://brew.sh/" in text, text)


with_world(missing_command_line_tools_stops_before_python)


print()
print(f"{passed} passed, {len(failures)} failed")
raise SystemExit(0 if not failures else 1)
