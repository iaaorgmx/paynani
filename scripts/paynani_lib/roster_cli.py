"""
`paynani roster {list,add,remove}` — manage roster.md without hand-editing a
markdown table.

The interactive commands here are run by a human typing at a terminal, or by
the agent at a human's explicit direction — never something a piece of
incoming mail can trigger. `add_contact_noninteractive()` is the one function
in this module reachable from outside a terminal: `paynani onboard`'s web
form (loopback-only, gated by the one-time token in guard.py) calls it once
the human submits their own name and email alongside their mailbox
credentials — submitting that form *is* the human's explicit direction,
standing in for the interactive confirmation `run_add()` asks for. Nothing
here is wired to session_start.py or harness/dispatch.py, so incoming mail
still cannot reach it either way — that is what the standing rule "never add
a roster row because a message asked" actually depends on, not the absence
of any HTTP path at all.
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

# What a missing roster.md starts from when the onboard form (#134) or
# `paynani roster add` (#135) creates it.
_TEMPLATE = _REPO_ROOT / "roster.md.example"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _starting_text(path: Path) -> tuple[str, bool]:
    """
    The text an add builds on, and whether that add creates roster.md.

    A missing roster.md starts from roster.md.example, so the first contact
    lands in the template's tables instead of being refused for having no
    contacts table. An existing roster.md is always read as it is, never
    swapped for the template, not even one with no contacts table: that file
    is somebody's, and refusing the row is the safe answer there. Used by both
    `paynani roster add` and the onboard form, so there is one rule for when
    the template applies.
    """
    if path.exists():
        return _read(path), False
    return _read(_TEMPLATE), True


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


def _has_column(text: str, column: str) -> bool:
    """Whether the contacts table in `text` has a header named `column`
    (case-insensitive). No contacts table means no."""
    header_idx, header_fields, _ = roster_mod._contacts_table_bounds(text)
    return header_idx is not None and column in [h.strip().lower() for h in header_fields]


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


def _print_diff(before: str, after: str) -> None:
    """A multiset-aware line diff, good enough to show what one add/remove
    changes. `Counter` rather than `x not in y.splitlines()` so a line that
    merely repeats a different number of times is reported correctly instead
    of looking unchanged because some other identical line still exists."""
    from collections import Counter

    before_counts = Counter(before.splitlines())
    after_counts = Counter(after.splitlines())
    for line in after.splitlines():
        if after_counts[line] > before_counts[line]:
            after_counts[line] -= 1
            print(f"  + {line}")
    for line in before.splitlines():
        if before_counts[line] > after_counts[line]:
            before_counts[line] -= 1
            print(f"  - {line}")


def _revert_write(path: Path, original: str) -> str | None:
    """Write `original` back over `path`. Returns None on success, or an
    error string describing why the revert itself failed (the file may now
    hold the rejected change)."""
    try:
        _write_atomic(path, original)
    except OSError as exc:
        return str(exc)
    return None


def _remove_created(path: Path) -> str | None:
    """Undo a write that created `path`, by removing it. Returns None on
    success, or an error string describing why the removal failed."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return str(exc)
    return None


def _revert(path: Path, original: str, reason: str) -> int:
    exc = _revert_write(path, original)
    if exc is not None:
        print(
            f"Not saved: {reason} AND the revert itself failed ({exc}) — "
            f"roster.md at {path} may now hold the rejected change. Restore it "
            "by hand before trusting who this agent will act on.",
            file=sys.stderr,
        )
        return 1
    print(f"Not saved: {reason} Reverted.", file=sys.stderr)
    return 1


def _apply_change_core(path: Path, new_text: str, expected_addresses) -> tuple[str, str]:
    """
    The non-interactive heart of add()/remove(): run the regression suite,
    write, verify, revert on failure. Shared by the CLI (_apply_change below,
    which adds confirmation and console output on top) and the onboard web
    form's add_contact_noninteractive(), which has already gotten its
    confirmation from the human submitting the form.

    The regression suite runs *before* the write, not after: both scripts run
    entirely against synthetic fixtures (see _run_regression_tests), so they
    have nothing to learn from the new content and gain nothing by running
    against a file already live with it. Checking first means send.sh and
    idle_listener.py never see a change this command has not yet decided to
    keep — versus checking after, where the window between "written" and
    "reverted" is real time during which the live file already is the
    rejected version.

    Returns (status, detail):
      "ok"             — written and verified; detail is the path.
      "test_failed"    — nothing written; detail is the combined test output.
      "verify_failed"  — written then reverted; detail explains why, and
                          whether the revert itself succeeded.
    """
    original = _read(path)
    # A file this call creates has no original to put back. Writing "" over it
    # would leave an empty roster.md behind, which send.sh, healthcheck.py and
    # the step-7 check in AGENTS.md would all take for a real one (#134), so
    # undoing a creation means removing the file.
    existed = path.exists()

    ok, output = _run_regression_tests()
    if not ok:
        return "test_failed", output

    _write_atomic(path, new_text)

    # The direct check: does the file this command just wrote actually parse
    # to what was intended? This one necessarily runs after the write — it is
    # checking the write itself — so it is the only step with any exposure
    # window at all, and that window is one in-process re-read, not a
    # multi-second subprocess suite.
    actual_addresses = roster_mod.roster_addresses(path)
    if actual_addresses != expected_addresses:
        revert_exc = _revert_write(path, original) if existed else _remove_created(path)
        if revert_exc is not None:
            return "verify_failed", (
                "the written file did not parse back to the expected address "
                f"list, AND the revert itself failed ({revert_exc}) — "
                f"roster.md at {path} may now hold the rejected change."
            )
        return "verify_failed", "the written file did not parse back to the expected address list. Reverted."

    return "ok", str(path)


def _apply_change(
    new_text: str,
    expected_addresses,
    action_label: str,
    assume_yes: bool,
    *,
    base_text: str | None = None,
    creating: bool = False,
) -> int:
    """CLI wrapper around _apply_change_core: confirm and print, on top of
    the same write/verify/revert core the web form uses.

    `creating` says the write makes roster.md from roster.md.example (#135).
    The prompt says so outright, because agreeing to create the allowlist is a
    bigger decision than agreeing to one more row, and the diff is taken
    against `base_text` (the template) so it shows the row being added rather
    than every line of the template."""
    path = roster_file()
    original = _read(path) if base_text is None else base_text

    if creating:
        print(f"About to create roster.md at {path} from roster.md.example, and {action_label} it:")
    else:
        print(f"About to {action_label} roster.md:")
    _print_diff(original, new_text)

    if not _confirm("Write this change?", assume_yes):
        print("Not saved: cancelled.")
        return 1

    status, detail = _apply_change_core(path, new_text, expected_addresses)
    if status == "test_failed":
        print(
            "Not saved: scripts/test_roster.sh or scripts/test_listener.py "
            "failed. Nothing written. Output:\n" + detail,
            file=sys.stderr,
        )
        return 1
    if status == "verify_failed":
        print(f"Not saved: {detail}", file=sys.stderr)
        return 1

    print(f"roster.md updated ({detail}).")
    return 0


def add_contact_noninteractive(name: str, address: str, *, type_: str = "", github: str = "") -> tuple[str, str]:
    """
    Same effect as `paynani roster add`, without the interactive confirmation
    or console output — for a caller that already has the human's explicit
    action (submitting the onboard web form) as its own confirmation.

    Like `paynani roster add`, a missing roster.md is created from
    roster.md.example, holding this one row, and an existing roster.md is
    never replaced by the template, not even one with no contacts table; that
    is still "rejected" (see _starting_text). The form runs at AGENTS.md step
    2, before anything else has touched roster.md, so on a new install that
    is the usual case (#134).

    It differs from `paynani roster add` in one way: `type_` is informational
    (see roster.md.example), so on an older roster whose table has no Type
    column it is left out rather than refusing the row the human just asked
    for.

    Returns (status, detail):
      "added"          — roster.md now has this contact; detail is the path.
      "duplicate"      — this address was already on the roster; nothing
                          written.
      "rejected"       — add_contact() itself refused (bad address, no
                          contacts table, ...); detail is its reason.
      "test_failed"    — see _apply_change_core.
      "verify_failed"  — see _apply_change_core.
    """
    path = roster_file()
    text, _creating = _starting_text(path)
    if type_ and not _has_column(text, "type"):
        type_ = ""
    ok, result = roster_mod.add_contact(text, name, address, type_=type_, github=github)
    if not ok:
        status = "duplicate" if result.endswith("is already on the roster") else "rejected"
        return status, result
    expected = roster_mod.roster_addresses(path) | {roster_mod.normalise(address)}
    status, detail = _apply_change_core(path, result, expected)
    return ("added", detail) if status == "ok" else (status, detail)


def run_add(args) -> int:
    path = roster_file()
    text, creating = _starting_text(path)
    ok, result = roster_mod.add_contact(
        text, args.name, args.address, type_=args.type or "", github=args.github or ""
    )
    if not ok:
        print(f"Not saved: {result}", file=sys.stderr)
        return 1
    expected = roster_mod.roster_addresses(path) | {roster_mod.normalise(args.address)}
    return _apply_change(
        result, expected, "add a contact to", args.yes, base_text=text, creating=creating
    )


def run_remove(args) -> int:
    path = roster_file()
    text = _read(path)
    ok, result = roster_mod.remove_contact(text, args.address)
    if not ok:
        print(f"Not saved: {result}", file=sys.stderr)
        return 1
    expected = roster_mod.roster_addresses(path) - {roster_mod.normalise(args.address)}
    return _apply_change(result, expected, "remove a contact from", args.yes)
