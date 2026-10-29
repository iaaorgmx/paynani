#!/usr/bin/env python3
"""
Tests for scripts/node_runtime.py, the Node of the WhatsApp bridge (PRD #550 FR-3b,
Q197=B). An assertion script, like the rest of this suite.

Nothing goes to nodejs.org: the "release" is a small tarball in a temporary folder,
served with file:// through PAYNANI_NODE_DIST, and its hash is pinned in a copy of
node_release.json. The real node_release.json is only checked for its shape.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import node_runtime as nr  # noqa: E402

passed = failed = 0


def check(label, expected, actual=True):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


VERSION = "22.23.4"
KEY = nr.platform_key()
tmp = Path(tempfile.mkdtemp()).resolve()
home = tmp / "home" / "lib" / "paynani"
dist = tmp / "dist"
shellbin = tmp / "shellbin"
shellbin.mkdir()
release_file = tmp / "node_release.json"
TOP = f"node-v{VERSION}-{KEY}"
NODE_SH = f'#!/bin/sh\ncase "$1" in --version) echo v{VERSION};; -p) echo 22;; esac\n'


def add(tar: tarfile.TarFile, name: str, data: bytes = b"", mode: int = 0o755, link: str | None = None):
    info = tarfile.TarInfo(name)
    if link is not None:
        info.type, info.linkname = tarfile.SYMTYPE, link
        tar.addfile(info)
    elif name.endswith("/"):
        info.type, info.mode = tarfile.DIRTYPE, 0o755
        tar.addfile(info)
    else:
        info.size, info.mode = len(data), mode
        tar.addfile(info, io.BytesIO(data))


def archive(extra=()) -> str:
    """The fake release at dist/v<ver>/<top>.tar.gz; returns its SHA-256."""
    path = dist / f"v{VERSION}" / f"{TOP}.tar.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        add(tar, f"{TOP}/")
        add(tar, f"{TOP}/bin/")
        add(tar, f"{TOP}/bin/node", NODE_SH.encode())
        add(tar, f"{TOP}/lib/node_modules/npm/bin/npm-cli.js", b"// npm\n", 0o644)
        add(tar, f"{TOP}/bin/npm", link="../lib/node_modules/npm/bin/npm-cli.js")
        for item in extra:
            add(tar, *item[:1], **item[1])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pin(sha: str) -> None:
    release_file.write_text(json.dumps({"version": VERSION, "sha256": {KEY: sha}}))


def shell_node(major: str | None) -> None:
    for name in ("node", "npm"):
        (shellbin / name).unlink(missing_ok=True)
    if major:
        (shellbin / "node").write_text(f'#!/bin/sh\ncase "$1" in --version) echo v{major}.0.0;; -p) echo {major};; esac\n')
        (shellbin / "npm").write_text("#!/bin/sh\nexit 0\n")
        for name in ("node", "npm"):
            (shellbin / name).chmod(0o755)


def leftovers() -> list[str]:
    return sorted(p.name for p in home.iterdir()) if home.exists() else []


os.environ["PAYNANI_NODE_HOME"] = str(home)
os.environ["PAYNANI_NODE_DIST"] = dist.as_uri()
os.environ["PATH"] = f"{shellbin}:/usr/bin:/bin"
nr.RELEASE_FILE = release_file

# --- the pinned file in the repository ------------------------------------------------------
real = json.loads((ROOT / "scripts" / "node_release.json").read_text())
check("node_release.json: Node 22, the four systems, 64-hex hashes",
      (True, {"linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64"}, True),
      (real["version"].startswith("22."), set(real["sha256"]),
       all(re.fullmatch(r"[0-9a-f]{64}", h) for h in real["sha256"].values())))

# --- platform -----------------------------------------------------------------------------
check("Linux x86_64 -> linux-x64", "linux-x64", nr.platform_key("Linux", "x86_64"))
check("Linux aarch64 -> linux-arm64", "linux-arm64", nr.platform_key("Linux", "aarch64"))
check("Darwin arm64 -> darwin-arm64", "darwin-arm64", nr.platform_key("Darwin", "arm64"))
check("armv7l: no pinned release", None, nr.platform_key("Linux", "armv7l"))
check("Windows: no pinned release", None, nr.platform_key("Windows", "AMD64"))

# --- this shell's Node ----------------------------------------------------------------------
sha = archive()
pin(sha)
shell_node("22")
check("Node 22 with npm in the shell: that folder", shellbin, nr.find())
check("plan: use it, nothing to download", f"use {shellbin}", nr.plan())
check("ensure: the same folder, nothing written", (shellbin, []), (nr.ensure(), leftovers()))
shell_node("18")
check("Node 18 in the shell does not count", None, nr.find())
(shellbin / "npm").unlink()
shell_node(None)
(shellbin / "node").write_text('#!/bin/sh\necho 22\n')
(shellbin / "node").chmod(0o755)
check("Node 22 without npm next to it does not count", None, nr.find())
shell_node("18")

# --- download -----------------------------------------------------------------------------------
check("plan with Node 18: download the pinned release into ~/.local/lib/paynani",
      f"download {dist.as_uri()}/v{VERSION}/{TOP}.tar.gz into {home / TOP}", nr.plan())
check("plan does not write anything", [], leftovers())
got = nr.ensure()
check("ensure: downloads and returns its bin/", home / TOP / "bin", got)
check("the folder is 0700 and only the release is left", (0o700, [TOP]),
      (stat.S_IMODE(os.stat(home).st_mode), leftovers()))
check("bin/npm is a link inside the release", True, (got / "npm").is_symlink() and (got / "npm").exists())
check("find now finds it (no network)", got, nr.find())
(dist / f"v{VERSION}" / f"{TOP}.tar.gz").unlink()
check("ensure again: no download", got, nr.ensure())

# A copy that does not answer with its version is replaced.
(got / "node").write_text("#!/bin/sh\necho v0\n")
pin(archive())  # gzip lleva la hora: el tarball nuevo puede tener otro hash
check("a broken copy is downloaded again", got, nr.ensure())
check("and answers with the pinned version", f"v{VERSION}", nr.version_of(str(got / "node")))

# --- a copy already there is checked before anything in it runs (Ximena, #567) -------------------
import shutil  # noqa: E402

marker = tmp / "ran"
evil = tmp / "evil-tree" / TOP / "bin"
evil.mkdir(parents=True)
(evil / "node").write_text(f'#!/bin/sh\ntouch "{marker}"\necho v{VERSION}\n')
(evil / "node").chmod(0o755)
(evil / "npm").write_text("#!/bin/sh\n")
shutil.rmtree(home)
home.mkdir(parents=True, mode=0o700)
(home / TOP).symlink_to(evil.parent)
check("a symlink at the release folder is not a pinned install, and its node never runs", (None, False),
      (nr.find(), marker.exists()))
try:
    nr.ensure()
    check("ensure over that symlink is refused", "Refused", "installed")
except nr.Refused as exc:
    check("ensure over that symlink is refused, without running it", (True, False),
          ("symlink" in str(exc), marker.exists()))
(home / TOP).unlink()
shutil.copytree(evil.parent, home / TOP, symlinks=True)
os.chmod(home / TOP, 0o777)
check("a group/world-writable release folder does not count, and its node never runs", (None, False),
      (nr.find(), marker.exists()))
os.chmod(home / TOP, 0o755)
os.chmod(home / TOP / "bin" / "node", 0o777)
check("a group/world-writable bin/node does not count either", (None, False), (nr.find(), marker.exists()))
shutil.rmtree(home / TOP)
(home / TOP).mkdir()
(home / TOP / "bin").symlink_to(evil)
check("a symlinked bin/ does not count", (None, False), (nr.find(), marker.exists()))

# --- refusals ---------------------------------------------------------------------------------------
shutil.rmtree(home)


def refused(label: str, text: str) -> None:
    try:
        nr.ensure()
        check(label, "Refused", "installed")
    except nr.Refused as exc:
        check(label, (True, []), (text in str(exc), leftovers()))


pin("0" * 64)
refused("a hash that does not match: refused, nothing left behind", "SHA-256")
pin(archive([(f"{TOP}/../evil", {"data": b"x"})]))
refused("an entry outside the folder: refused", "unexpected entry")
check("and evil was not written", False, (home / "evil").exists() or (home.parent / "evil").exists())
pin(archive([(f"{TOP}/bin/x", {"link": "../../../../etc/passwd"})]))
refused("a link out of the folder: refused", "link out of the Node folder")
pin(archive([("other/bin/node", {"data": NODE_SH.encode()})]))
refused("an entry in another top folder: refused", "unexpected entry")
pin(archive())
os.environ["PAYNANI_NODE_DIST"] = "http://nodejs.org/dist"
refused("plain http: refused", "refusing to download Node over http")
os.environ["PAYNANI_NODE_DIST"] = (tmp / "nowhere").as_uri()
refused("no archive at that address: refused with the reason", "could not download")
os.environ["PAYNANI_NODE_DIST"] = dist.as_uri()
home.mkdir(parents=True, exist_ok=True)
os.chmod(home, 0o777)
refused("a world-writable ~/.local/lib/paynani: refused", "group- or world-writable")
os.chmod(home, 0o700)

# --- the command line --------------------------------------------------------------------------------
shutil.rmtree(home)
env = dict(os.environ)
cli = [sys.executable, str(ROOT / "scripts" / "node_runtime.py")]
r = subprocess.run(cli + ["find"], capture_output=True, text=True, env=env)
check("find without Node 20+ or the pinned one: exit 1", 1, r.returncode)
r = subprocess.run(cli + ["nope"], capture_output=True, text=True, env=env)
check("an unknown command: exit 64", 64, r.returncode)
# The real node_release.json, with a fake archive at the address: the hash does not match.
r = subprocess.run(cli + ["ensure"], capture_output=True, text=True, env=env)
check("the real pinned hash refuses the fake archive: exit 2, nothing installed", (2, True, []),
      (r.returncode, "SHA-256" in r.stderr, leftovers()))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
