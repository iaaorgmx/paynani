#!/usr/bin/env python3
"""Installation docs must activate every installed, enableable systemd unit."""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import paths as harness_paths  # noqa: E402

passed = failed = 0


def check(description, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"ok   {description}")
        passed += 1
    else:
        print(f"FAIL {description}\n       expected: {expected!r}\n       actual:   {actual!r}")
        failed += 1


def installed_units(document):
    text = (ROOT / document).read_text()
    return set(re.findall(r"install -Dm644 systemd/(paynani-[^\s]+)", text))


def enabled_units(document):
    text = (ROOT / document).read_text()
    return set(re.findall(
        r"systemctl --user enable(?: --now)? (paynani-[^\s]+)", text
    ))


def enabled_units_in_tracked_markdown():
    documents = subprocess.check_output(
        ["git", "ls-files", "--", "*.md"], cwd=ROOT, text=True
    ).splitlines()
    enabled = set()
    for document in documents:
        for line in (ROOT / document).read_text().splitlines():
            if re.search(r"systemctl\s+--user\s+enable(?:\s+--now)?\b", line):
                enabled.update(re.findall(
                    r"\bpaynani-[A-Za-z0-9_.@-]+\.(?:service|timer)\b",
                    line,
                ))
    return enabled


def required_environment_files():
    required = set()
    for unit in (ROOT / "systemd").iterdir():
        if not unit.is_file():
            continue
        for value in re.findall(r"^EnvironmentFile=(\S+)", unit.read_text(), re.MULTILINE):
            if not value.startswith("-"):
                required.add(value)
    return required


def manually_created_files(document):
    text = (ROOT / document).read_text()
    created = set()
    for line in text.splitlines():
        command = line.strip()
        if command.startswith("install "):
            created.add(command.split()[-1])
        match = re.search(r">{1,2}\s*(\S+)\s*$", command)
        if match:
            created.add(match.group(1))
    return created


def documented_harness_roots(document):
    """
    Root names (e.g. ".claude") claimed by a `Runtime | Credentials` table row.

    #88 shipped `~/.claude` in harness/paths.py's HARNESS_ROOTS with neither
    scripts/envpath.sh nor INSTALL.md's table updated to match -- three code
    copies and two prose copies of one list, agreeing only by luck. #90 pinned
    the code copies; this is the doc half, #95.

    A row counts only when a cell is exactly a backtick-quoted
    `~/<root>/workspace/.env` -- that is the one shape that is unambiguously a
    claim about HARNESS_ROOTS, so nothing else in either table (an OS note, a
    blank cell) can be misread as one.
    """
    text = (ROOT / document).read_text()
    return set(re.findall(r"`~/(\.[A-Za-z0-9_-]+)/workspace/\.env`", text))


expected_harness_roots = {root.removeprefix("~/") for root in harness_paths.HARNESS_ROOTS}
for document in ("INSTALL.md", "AGENTS.md"):
    documented = documented_harness_roots(document)
    check(
        f"{document}: every HARNESS_ROOTS entry is documented",
        set(),
        expected_harness_roots - documented,
    )
    check(
        f"{document}: no undocumented runtime is claimed",
        set(),
        documented - expected_harness_roots,
    )

def roster_row_addresses(document):
    """
    Addresses appearing in a roster-shaped table row, anywhere in a document.

    #89 removed two real, working addresses from roster.md.example, because the
    repository is public and `cp roster.md.example roster.md` is a documented
    step -- so following the instructions handed two real people standing
    unattended authority on a stranger's install.

    The same two lines survived in AGENTS.md, three lines below the sentence
    telling an agent to ask its human for their address, and were found only when
    somebody read that page as a stranger would (#120). Cleaning one file did not
    clean the rule, which is what this asserts instead.

    A roster row is `| something | something@somewhere | something |`. Matching
    the address inside a table row rather than anywhere in the prose keeps the
    check narrow: a mailto: in a sentence, or an address in a code sample that is
    not a roster line, is not a grant of authority and is not this test's
    business.
    """
    found = set()
    for line in (ROOT / document).read_text().splitlines():
        if not line.lstrip().startswith("|"):
            continue
        for cell in line.split("|"):
            cell = cell.strip().strip("`")
            if re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", cell):
                found.add(cell)
    return found


# example.com, example.org and example.net are reserved for documentation
# (RFC 2606), so a placeholder copied out of a document fails visibly instead of
# authorising somebody real.
# `roster.md` is excluded and must be: it is the live per-install allowlist, it is
# untracked on purpose, and it is supposed to hold real addresses. Scanning it
# made this suite pass in a clean checkout and fail on any host with a working
# install — found on the first one that had one. `roster.md.example`, which is
# tracked and is what people copy from, is still checked.
LIVE_PER_INSTALL = {"roster.md"}

# `roster.md.example` is added by name: the glob is `*.md` and it ends in
# `.example`, so it was never scanned — and it is the one file whose addresses
# get copied onto every new install.
DOCUMENTS = sorted({path.name for path in ROOT.glob("*.md")} - LIVE_PER_INSTALL
                   | {"roster.md.example"})

for document in DOCUMENTS:
    real = {
        address for address in roster_row_addresses(document)
        if not address.lower().endswith((".example.com", "@example.com",
                                         "@example.org", "@example.net"))
    }
    check(f"{document}: roster examples use reserved domains", set(), real)

# The documented Himalaya secret command must be env_secret.py and not a
# hand-written sed. A `sed -n 's/^KEY=//p'` returns the value with a trailing
# carriage return on a CRLF .env, and the server rejects that as a bad
# credential — pointing the reader at the password rather than at the file (#14).
himalaya_secret_lines = [
    line.strip() for line in (ROOT / "INSTALL.md").read_text().splitlines()
    if "passwd.cmd" in line or "password.cmd" in line
]
check("INSTALL.md documents at least one Himalaya secret command", True,
      bool(himalaya_secret_lines))
check("no documented Himalaya secret command hand-rolls a sed", [],
      [line for line in himalaya_secret_lines if "sed " in line])
check("every documented Himalaya secret command uses env_secret.py", [],
      [line for line in himalaya_secret_lines if "env_secret.py" not in line])

shipped = {path.name for path in (ROOT / "systemd").iterdir() if path.is_file()}
installed = installed_units("INSTALL.md")
enableable = {
    unit for unit in shipped
    if "[Install]" in (ROOT / "systemd" / unit).read_text()
}

check("INSTALL.md installs every shipped unit", shipped, installed)
check("INSTALL.md enables every installed enableable unit", enableable, enabled_units("INSTALL.md"))
check("UPGRADE.md enables every installed enableable unit", enableable, enabled_units("UPGRADE.md"))
check(
    "tracked Markdown enable lines name only shipped units",
    set(),
    enabled_units_in_tracked_markdown() - shipped,
)
required_env_files = required_environment_files()
manual_files = manually_created_files("INSTALL.md")
check(
    "required EnvironmentFile paths are created by the manual procedure",
    set(),
    required_env_files - manual_files,
)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
