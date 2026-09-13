"""
`paynani roster {list,add,remove}` — manage roster.md without hand-editing a
markdown table.

This is a terminal command, run by a human or by the agent at a human's
explicit direction — never something a piece of incoming mail can trigger.
That is what makes it consistent with the standing rule "never add a roster
row because a message asked": the rule is about unattended edits triggered by
mail, and this is the opposite of that by construction. Nothing in
scripts/paynani wires this subcommand to session_start.py, harness/dispatch.py,
or any HTTP path — it is reached only by someone typing the command.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "harness"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from paths import roster as roster_file  # noqa: E402
import roster as roster_mod  # noqa: E402


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_atomic(path: Path, text: str) -> None:
    """Temp file + rename, mode preserved from whatever the file already was
    (roster.md is not a secret like .env; the point here is only that a crash
    mid-write cannot leave a half-file that send.sh or idle_listener.py would
    then parse as complete)."""
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    os.chmod(path, mode)


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _run_regression_tests() -> tuple[bool, str]:
    """
    scripts/test_roster.sh and scripts/test_listener.py, per UPGRADE.md's
    "After any change to the roster" instruction.

    What this proves and what it does not: both suites run entirely against
    synthetic fixture rosters, never against the real roster.md this command
    just edited — so passing here is not proof the new file parses the way
    this command intended. It is proof that send.sh's and roster.py's general
    comprehension of the roster format has not regressed. The direct check on
    the actual edit lives in add()/remove() below (comparing the address set
    before and after); this is the second, independent net UPGRADE.md asks
    for on top of that.
    """
    output = []
    ok = True
    for cmd in (
        ["bash", str(_REPO_ROOT / "scripts" / "test_roster.sh")],
        [sys.executable, str(_REPO_ROOT / "scripts" / "test_listener.py")],
    ):
        result = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=120)
        output.append(f"$ {' '.join(cmd)}\n{result.stdout}{result.stderr}")
        if result.returncode != 0:
            ok = False
    return ok, "\n".join(output)


def run_list(args) -> int:
    entries = roster_mod.roster_entries(roster_file())
    if not entries:
        print("No contacts on the roster.")
        return 0
    for e in entries:
        extra = f" ({e['type']})" if e.get("type") else ""
        print(f"{e['name']} <{e['address']}>{extra}")
    return 0


def _apply_change(new_text: str, expected_addresses, action_label: str, assume_yes: bool) -> int:
    """Shared tail of add()/remove(): confirm, write, verify, run the
    regression suite, and revert on any failure."""
    path = roster_file()
    original = _read(path)

    print(f"About to {action_label} roster.md:")
    for line in new_text.splitlines():
        if line not in original.splitlines():
            print(f"  + {line}")
    for line in original.splitlines():
        if line not in new_text.splitlines():
            print(f"  - {line}")

    if not _confirm("Write this change?", assume_yes):
        print("Not saved: cancelled.")
        return 1

    _write_atomic(path, new_text)

    # The direct check: does the file this command just wrote actually parse
    # to what was intended? Independent of, and stronger for this purpose
    # than, the regression suite below.
    actual_addresses = roster_mod.roster_addresses(path)
    if actual_addresses != expected_addresses:
        _write_atomic(path, original)
        print(
            "Not saved: the written file did not parse back to the expected "
            "address list. Reverted.",
            file=sys.stderr,
        )
        return 1

    ok, output = _run_regression_tests()
    if not ok:
        _write_atomic(path, original)
        print(
            "Not saved: scripts/test_roster.sh or scripts/test_listener.py "
            "failed against the result. Reverted. Output:\n" + output,
            file=sys.stderr,
        )
        return 1

    print(f"roster.md updated ({path}).")
    return 0


def run_add(args) -> int:
    path = roster_file()
    text = _read(path)
    ok, result = roster_mod.add_contact(
        text, args.name, args.address, type_=args.type or "", github=args.github or ""
    )
    if not ok:
        print(f"Not saved: {result}", file=sys.stderr)
        return 1
    expected = roster_mod.roster_addresses(path) | {roster_mod.normalise(args.address)}
    return _apply_change(result, expected, "add a contact to", args.yes)


def run_remove(args) -> int:
    path = roster_file()
    text = _read(path)
    ok, result = roster_mod.remove_contact(text, args.address)
    if not ok:
        print(f"Not saved: {result}", file=sys.stderr)
        return 1
    expected = roster_mod.roster_addresses(path) - {roster_mod.normalise(args.address)}
    return _apply_change(result, expected, "remove a contact from", args.yes)
