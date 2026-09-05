#!/usr/bin/env python3
"""Secure ownership-manifest and atomic artifact operations for install.sh."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

MAX_MANIFEST = 64 * 1024
DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class Refusal(Exception):
    pass


def _die(message: str) -> None:
    print(f"install: {message}", file=sys.stderr)
    raise SystemExit(78)


def _open_dir(path: Path) -> int:
    """Open an absolute directory without following any path-component symlink."""
    if not path.is_absolute():
        raise Refusal(f"managed directory must be absolute: {path}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except OSError as exc:
        os.close(fd)
        raise Refusal(f"cannot securely open managed directory {path}: {exc.strerror}") from exc


def _read_manifest_at(dir_fd: int, name: str, runtime: str, allowed: set[str]) -> list[tuple[str, str, str]]:
    try:
        metadata = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise Refusal("ownership manifest must be a user-owned mode-0600 regular file (not a symlink)")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=dir_fd)
    try:
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise Refusal("ownership manifest changed during secure read")
        data = bytearray()
        while len(data) <= MAX_MANIFEST:
            chunk = os.read(fd, min(8192, MAX_MANIFEST + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > MAX_MANIFEST:
            raise Refusal("ownership manifest exceeds 64 KiB")
    finally:
        os.close(fd)
    try:
        lines = bytes(data).decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Refusal("ownership manifest is not valid UTF-8") from exc
    if len(lines) < 2 or lines[0] != "version\t1" or lines[1] != f"runtime\t{runtime}":
        raise Refusal("ownership manifest has an unsupported version or runtime")
    records: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for line in lines[2:]:
        fields = line.split("\t")
        if len(fields) != 4 or fields[0] != "artifact":
            raise Refusal("ownership manifest contains a malformed record")
        _, kind, path, digest = fields
        if kind not in {"file", "secret"} or path not in allowed or not DIGEST_RE.fullmatch(digest):
            raise Refusal("ownership manifest contains an unauthorized artifact record")
        if path in seen:
            raise Refusal("ownership manifest contains a duplicate artifact record")
        seen.add(path)
        records.append((kind, path, digest))
    return records


def _serialize(runtime: str, records: list[tuple[str, str, str]]) -> bytes:
    lines = ["version\t1", f"runtime\t{runtime}"]
    lines.extend(f"artifact\t{kind}\t{path}\t{digest}" for kind, path, digest in records)
    return ("\n".join(lines) + "\n").encode()


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _atomic_replace(dir_fd: int, name: str, data: bytes, mode: int) -> None:
    temp_name = f".{name}.tmp.{os.getpid()}.{os.urandom(8).hex()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp_name, flags, mode, dir_fd=dir_fd)
    try:
        os.fchmod(fd, mode)
        _write_all(fd, data)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(temp_name, dir_fd=dir_fd)
        raise
    else:
        os.close(fd)
    os.replace(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    os.fsync(dir_fd)


def cmd_read(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    fd = _open_dir(path.parent)
    try:
        records = _read_manifest_at(fd, path.name, args.runtime, set(args.allowed))
    finally:
        os.close(fd)
    for kind, artifact, digest in records:
        print(f"{kind}\t{artifact}\t{digest}")


def cmd_init(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    fd = _open_dir(path.parent)
    try:
        try:
            _read_manifest_at(fd, path.name, args.runtime, set(args.allowed))
            return
        except FileNotFoundError:
            pass
        # Link a complete temporary file into an absent destination, so init
        # never replaces a path introduced after inventory.
        data = _serialize(args.runtime, [])
        temp_name = f".{path.name}.tmp.{os.getpid()}.{os.urandom(8).hex()}"
        temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
        try:
            _write_all(temp_fd, data)
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)
        try:
            os.link(temp_name, path.name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            os.fsync(fd)
        except FileExistsError as exc:
            raise Refusal("ownership manifest appeared during initialization; refusing to replace it") from exc
        finally:
            os.unlink(temp_name, dir_fd=fd)
    finally:
        os.close(fd)


def cmd_record(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    fd = _open_dir(path.parent)
    try:
        records = _read_manifest_at(fd, path.name, args.runtime, set(args.allowed))
        updated = [record for record in records if record[1] != args.path]
        updated.append((args.kind, args.path, args.digest))
        _atomic_replace(fd, path.name, _serialize(args.runtime, updated), 0o600)
    finally:
        os.close(fd)


def cmd_forget(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    fd = _open_dir(path.parent)
    try:
        records = _read_manifest_at(fd, path.name, args.runtime, set(args.allowed))
        updated = [record for record in records if record[1] != args.path]
        if len(updated) == len(records):
            raise Refusal("ownership manifest does not authorize requested removal")
        _atomic_replace(fd, path.name, _serialize(args.runtime, updated), 0o600)
    finally:
        os.close(fd)


def cmd_finalize(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    fd = _open_dir(path.parent)
    try:
        records = _read_manifest_at(fd, path.name, args.runtime, set(args.allowed))
        if records:
            raise Refusal("ownership manifest still contains artifacts; refusing final removal")
        os.unlink(path.name, dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(fd)


def cmd_migrate_runtime(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    fd = _open_dir(path.parent)
    try:
        records = _read_manifest_at(fd, path.name, args.from_runtime, set(args.allowed))
        _atomic_replace(fd, path.name, _serialize(args.runtime, records), 0o600)
    finally:
        os.close(fd)


def cmd_remove_artifact(args: argparse.Namespace) -> None:
    destination = Path(args.path)
    dir_fd = _open_dir(destination.parent)
    try:
        try:
            metadata = os.stat(destination.name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise Refusal(f"owned artifact is not a user-owned regular file: {destination}")
        file_fd = os.open(destination.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
        try:
            current = hashlib.sha256()
            while chunk := os.read(file_fd, 8192):
                current.update(chunk)
            opened = os.fstat(file_fd)
        finally:
            os.close(file_fd)
        if current.hexdigest() != args.expected_digest:
            raise Refusal(
                f"owned artifact changed outside the installer: {destination}; "
                "move it to an operator-owned backup path, then rerun --uninstall"
            )
        latest = os.stat(destination.name, dir_fd=dir_fd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (latest.st_dev, latest.st_ino):
            raise Refusal(f"owned artifact changed during removal: {destination}")
        if args.verify_only:
            return
        os.unlink(destination.name, dir_fd=dir_fd)
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def cmd_write_artifact(args: argparse.Namespace) -> None:
    destination = Path(args.path)
    data = sys.stdin.buffer.read()
    desired_digest = hashlib.sha256(data).hexdigest()
    dir_fd = _open_dir(destination.parent)
    try:
        try:
            metadata = os.stat(destination.name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            metadata = None
        if metadata is not None:
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise Refusal(f"managed artifact is not a user-owned regular file: {destination}")
            fd = os.open(destination.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
            try:
                current = hashlib.sha256()
                while chunk := os.read(fd, 8192):
                    current.update(chunk)
                opened = os.fstat(fd)
            finally:
                os.close(fd)
            current_digest = current.hexdigest()
            latest = os.stat(destination.name, dir_fd=dir_fd, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (latest.st_dev, latest.st_ino):
                raise Refusal(f"managed artifact changed during convergence: {destination}")
            if args.expected_digest:
                if current_digest != args.expected_digest:
                    raise Refusal(f"owned artifact changed outside the installer: {destination}")
            elif current_digest != desired_digest:
                raise Refusal(f"unowned artifact appeared during convergence: {destination}")
            # With no expected digest, an exact content match is the recoverable
            # create-before-record crash state. It may now be recorded safely.
            if current_digest == desired_digest and stat.S_IMODE(latest.st_mode) == args.mode:
                print(desired_digest)
                return
            _atomic_replace(dir_fd, destination.name, data, args.mode)
        else:
            temp_name = f".{destination.name}.tmp.{os.getpid()}.{os.urandom(8).hex()}"
            temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, args.mode, dir_fd=dir_fd)
            try:
                os.fchmod(temp_fd, args.mode)
                _write_all(temp_fd, data)
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)
            try:
                os.link(temp_name, destination.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
                os.fsync(dir_fd)
            except FileExistsError as exc:
                raise Refusal(f"unowned artifact appeared during convergence: {destination}") from exc
            finally:
                os.unlink(temp_name, dir_fd=dir_fd)
        print(desired_digest)
    finally:
        os.close(dir_fd)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("read", "init", "record", "forget", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", required=True)
        p.add_argument("--runtime", required=True)
        p.add_argument("--allowed", action="append", default=[])
    record = sub.choices["record"]
    record.add_argument("--kind", required=True, choices=("file", "secret"))
    record.add_argument("--path", required=True)
    record.add_argument("--digest", required=True)
    forget = sub.choices["forget"]
    forget.add_argument("--path", required=True)
    migrate = sub.add_parser("migrate-runtime")
    migrate.add_argument("--manifest", required=True)
    migrate.add_argument("--from-runtime", required=True,
                         choices=("openclaw", "hermes", "claudecode", "codex"))
    migrate.add_argument("--runtime", required=True,
                         choices=("openclaw", "hermes", "claudecode", "codex"))
    migrate.add_argument("--allowed", action="append", default=[])
    write = sub.add_parser("write-artifact")
    write.add_argument("--path", required=True)
    write.add_argument("--mode", type=lambda value: int(value, 8), required=True)
    write.add_argument("--expected-digest", default="")
    remove = sub.add_parser("remove-artifact")
    remove.add_argument("--path", required=True)
    remove.add_argument("--expected-digest", required=True)
    remove.set_defaults(verify_only=False)
    verify = sub.add_parser("verify-artifact")
    verify.add_argument("--path", required=True)
    verify.add_argument("--expected-digest", required=True)
    verify.set_defaults(verify_only=True)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        {"read": cmd_read, "init": cmd_init, "record": cmd_record,
         "forget": cmd_forget, "finalize": cmd_finalize,
         "migrate-runtime": cmd_migrate_runtime,
         "write-artifact": cmd_write_artifact,
         "remove-artifact": cmd_remove_artifact,
         "verify-artifact": cmd_remove_artifact}[args.command](args)
    except Refusal as exc:
        _die(str(exc))
    except OSError as exc:
        _die(f"secure installer filesystem operation failed: {exc}")


if __name__ == "__main__":
    main()
