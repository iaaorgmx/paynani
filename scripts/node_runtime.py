#!/usr/bin/env python3
"""
The Node the WhatsApp bridge runs with (PRD #550 FR-3b, Q197=B).

If this shell already has Node 20 or newer with npm, that one is used, and
nothing is downloaded. Otherwise the installer puts the official Node release
pinned in `scripts/node_release.json` under `~/.local/lib/paynani/`, without
sudo. The archive comes from nodejs.org, and it is used only if its SHA-256
matches the one pinned in the repository. A mismatch stops the install, with
nothing written.

    node_runtime.py find     the folder with node and npm, or exit 1 (no network)
    node_runtime.py plan     what `ensure` would do, without doing it (the dry-run)
    node_runtime.py ensure   the folder, downloading the pinned release if needed

Exit codes: 0 ok, 1 not found (`find`), 2 cannot be done here (unsupported
system, no download, a hash that does not match).

Only the standard library, like the installer.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILE = ROOT / "scripts" / "node_release.json"
MIN_MAJOR = 20
DIST = "https://nodejs.org/dist"
MAX_BYTES = 200 * 1024 * 1024
TIMEOUT_S = 60


class Refused(Exception):
    pass


def release() -> dict:
    data = json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data.get("version"), str) or not isinstance(data.get("sha256"), dict):
        raise Refused(f"{RELEASE_FILE} is not valid")
    return data


def platform_key(system: str | None = None, machine: str | None = None) -> str | None:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system not in ("linux", "darwin") or not arch:
        return None
    return f"{system}-{arch}"


def home_dir() -> Path:
    """Where the private Node goes. PAYNANI_NODE_HOME is for the tests."""
    return Path(os.environ.get("PAYNANI_NODE_HOME") or Path.home() / ".local" / "lib" / "paynani")


def private_dir(rel: dict, key: str) -> Path:
    return home_dir() / f"node-v{rel['version']}-{key}"


def major_of(node: str) -> int | None:
    try:
        out = subprocess.run([node, "-p", 'process.versions.node.split(".")[0]'], capture_output=True,
                             text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return int(out) if out.isdigit() else None


def version_of(node: str) -> str | None:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def shell_node() -> Path | None:
    """The folder of this shell's node, if it is 20 or newer and npm is in the same folder."""
    node = shutil.which("node")
    if not node or not (Path(node).parent / "npm").exists():
        return None
    major = major_of(node)
    if major is None or major < MIN_MAJOR:
        return None
    return Path(node).parent


def installed(rel: dict, key: str) -> Path | None:
    """The pinned release under home_dir(), if it is there and answers with its version."""
    bin_dir = private_dir(rel, key) / "bin"
    node = bin_dir / "node"
    if node.is_file() and os.access(node, os.X_OK) and (bin_dir / "npm").exists() \
            and version_of(str(node)) == f"v{rel['version']}":
        return bin_dir
    return None


def find() -> Path | None:
    found = shell_node()
    if found:
        return found
    key = platform_key()
    return installed(release(), key) if key else None


def archive_url(rel: dict, key: str) -> str:
    """PAYNANI_NODE_DIST replaces nodejs.org (a mirror, or the tests); the pinned hash still decides."""
    base = (os.environ.get("PAYNANI_NODE_DIST") or DIST).rstrip("/")
    return f"{base}/v{rel['version']}/node-v{rel['version']}-{key}.tar.gz"


def plan() -> str:
    found = find()
    if found:
        return f"use {found}"
    key = platform_key()
    if not key:
        raise Refused(f"no Node {MIN_MAJOR}+ here and no pinned Node release for "
                      f"{platform.system()} {platform.machine()}; install Node {MIN_MAJOR}+ yourself")
    rel = release()
    if key not in rel["sha256"]:
        raise Refused(f"no pinned hash for {key} in {RELEASE_FILE}")
    return f"download {archive_url(rel, key)} into {private_dir(rel, key)}"


def _safe_home(path: Path) -> None:
    """The folder is created 0700 by this user; a symlink or someone else's folder is refused."""
    for part in (path.parent, path):
        if part.is_symlink():
            raise Refused(f"{part} is a symlink; remove it and run this again")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(path)
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o022:
        raise Refused(f"{path} must belong to you and not be group- or world-writable")


def _download(url: str, dest: Path, expected: str) -> None:
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("https", "file"):
        raise Refused(f"refusing to download Node over {scheme or 'no scheme'}: {url}")
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp, dest.open("wb") as out:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise Refused(f"{url} is larger than {MAX_BYTES} bytes")
                digest.update(chunk)
                out.write(chunk)
    except OSError as exc:
        raise Refused(f"could not download {url} ({exc}); check the network and run this again") from None
    got = digest.hexdigest()
    if got != expected:
        raise Refused(f"SHA-256 of {url} is {got}, expected {expected} (scripts/node_release.json); "
                      "nothing was installed")


def _check_members(tar: tarfile.TarFile, top: str) -> None:
    """Every entry inside `top/`, no absolute paths, no `..`, links that stay inside, no devices."""
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if m.name.startswith("/") or ".." in parts or not parts or parts[0] != top:
            raise Refused(f"unexpected entry in the Node archive: {m.name!r}")
        if not (m.isfile() or m.isdir() or m.issym()):
            raise Refused(f"unexpected entry type in the Node archive: {m.name!r}")
        if m.issym():
            target = os.path.normpath(os.path.join(os.path.dirname(m.name), m.linkname))
            if m.linkname.startswith("/") or not (target == top or target.startswith(top + os.sep)):
                raise Refused(f"link out of the Node folder in the archive: {m.name!r} -> {m.linkname!r}")


def ensure() -> Path:
    found = find()
    if found:
        return found
    plan()  # the same refusals as the dry-run
    rel = release()
    key = platform_key()
    target = private_dir(rel, key)
    top = target.name
    home = home_dir()
    _safe_home(home)
    work = Path(tempfile.mkdtemp(prefix=".node-", dir=home))
    try:
        archive = work / f"{top}.tar.gz"
        _download(archive_url(rel, key), archive, rel["sha256"][key])
        with tarfile.open(archive, "r:gz") as tar:
            _check_members(tar, top)
            if hasattr(tarfile, "data_filter"):
                tar.extractall(work, filter="data")
            else:  # Python without extraction filters: _check_members already vetted every entry
                tar.extractall(work)
        node = work / top / "bin" / "node"
        if version_of(str(node)) != f"v{rel['version']}":
            raise Refused(f"the downloaded Node does not run here ({node})")
        if target.exists() or target.is_symlink():
            # A copy that did not answer with its version: ours, from an earlier run.
            if target.is_symlink():
                raise Refused(f"{target} is a symlink; remove it and run this again")
            shutil.rmtree(target)
        os.rename(work / top, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    bin_dir = installed(rel, key)
    if not bin_dir:
        raise Refused(f"Node was unpacked into {target} but does not answer")
    return bin_dir


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("find", "plan", "ensure"):
        print(__doc__.strip().split("\n\n")[2], file=sys.stderr)
        return 64
    try:
        if argv[1] == "find":
            found = find()
            if not found:
                return 1
            print(found)
        elif argv[1] == "plan":
            print(plan())
        else:
            print(ensure())
    except Refused as exc:
        print(f"node_runtime: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
