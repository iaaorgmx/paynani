"""
Writing the credentials file. Port of webapp/lib/envfile.php.

This is the same file a power user writes by hand before running the install
prompt, and its absence is what tells the agent a mailbox has not been
configured yet. The PHP form and this one both end at one file, resolved the
same way: through harness/paths.py's env_file(), the same function every
other Python part of this repository (idle_listener.py, preflight.py, ...)
already uses. Nothing here reimplements path resolution.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))
from paths import env_file  # noqa: E402

# The keys this form owns, in the order they are written.
ENV_FIELDS = [
    "AGENT_EMAIL_ACCOUNT",
    "AGENT_EMAIL_PASSWORD",
    "AGENT_EMAIL_FROM_NAME",
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST",
    "AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST",
    "AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT",
]

_KEY_VALUE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def env_path() -> Path:
    return env_file()


def readlink_absolute(path: Path) -> Path | None:
    """
    Where a symlink actually points, as an absolute path.

    Path.resolve() is not enough on its own for a dangling link: it still
    answers for a target that does not exist yet, which is exactly the case
    where writing to the link path instead would silently replace the link.
    os.readlink() answers the same for a dangling link as for a live one.
    """
    try:
        target = os.readlink(path)
    except OSError:
        return None
    if not target:
        return None
    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = path.parent / target_path
    return target_path


def read_env() -> dict:
    """
    Everything currently in the credentials file, as key => value.

    Quotes are stripped exactly one layer deep, which is what harness code and
    send.sh do when they read the same file back. Anything that is not a
    KEY=value line is ignored here; render_env() is the half that preserves
    it.
    """
    path = env_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    out: dict[str, str] = {}
    for line in re.split(r"\r\n|\n|\r", raw):
        m = _KEY_VALUE_RE.match(line)
        if not m:
            continue
        value = m.group(2).strip()
        if len(value) >= 2 and (
            (value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")
        ):
            value = value[1:-1]
        out[m.group(1)] = value
    return out


def sanitise_value(value: str) -> str:
    return value.replace("\r", "").replace("\n", "").strip()


def render_env(values: dict) -> str:
    """
    The file to write.

    Only the seven keys this form owns are touched. A real installation keeps
    more than mail settings in here, tokens for other services among them,
    and this tool has no idea what any of it is. So an existing file is
    edited in place, line by line: comments, blank lines, key order and
    unknown keys all survive. Only an absent or empty file gets the generated
    header.
    """
    path = env_path()
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        existing = ""

    if existing.strip() == "":
        import datetime

        out = [
            "# Written by the paynani onboarding CLI.",
            f"# {datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "#",
            "# Key names follow the schema in .env.example. Ports live in their own",
            "# keys: a port stored in a key named for a server is the one mistake",
            "# this file format refuses to survive.",
            "",
        ]
        for key in ENV_FIELDS:
            out.append(f"{key}={sanitise_value(values.get(key, ''))}")
        out.append("")
        return "\n".join(out)

    lines = re.split(r"\r\n|\n|\r", existing.rstrip("\r\n"))
    seen: set[str] = set()
    for i, line in enumerate(lines):
        m = _KEY_VALUE_RE.match(line)
        if not m or m.group(1) not in ENV_FIELDS:
            continue
        lines[i] = f"{m.group(1)}={sanitise_value(values.get(m.group(1), ''))}"
        seen.add(m.group(1))
    for key in ENV_FIELDS:
        if key not in seen:
            lines.append(f"{key}={sanitise_value(values.get(key, ''))}")
    return "\n".join(lines) + "\n"


def write_env(contents: str) -> tuple[bool, str]:
    """Returns (success, message) — the message is a path on success, and a
    human-readable reason otherwise."""
    from .i18n import t

    path = env_path()
    directory = path.parent

    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    except OSError:
        return False, t("f.mkdir_failed", dir=str(directory))

    # Write beside the target and rename, so an interrupted write cannot leave
    # a half-file that the listener would read as a complete one.
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except OSError:
        return False, t("f.write_failed", dir=str(directory))

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(contents)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False, t("f.incomplete")

    # Follow a symlink rather than replacing it: on a host where this path is
    # linked at a harness .env, renaming over it would break the link and
    # strand the listener on a file nobody updates.
    target = path
    if path.is_symlink():
        resolved = readlink_absolute(path)
        target = resolved if resolved is not None else path

    if target != path:
        try:
            target.write_text(contents, encoding="utf-8")
            target.chmod(0o600)
        except OSError:
            tmp.unlink(missing_ok=True)
            return False, t("f.symlink_failed", target=str(target))
        tmp.unlink(missing_ok=True)
        return True, str(target)

    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False, t("f.rename_failed", path=str(path))
    path.chmod(0o600)
    return True, str(path)
