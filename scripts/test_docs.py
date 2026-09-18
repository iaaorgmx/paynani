#!/usr/bin/env python3
"""Installation docs must activate every installed, enableable systemd unit."""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import capabilities  # noqa: E402
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
    repository is public and `cp roster.md.example roster.md` was a documented
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

# The onboard form creates roster.md at step 2 with the human's row (#134). An
# install step that copies the template unconditionally would overwrite that
# row with a roster that authorises nobody, so every documented copy has to
# leave an existing file alone.
unguarded_roster_copies = [
    f"{document}: {line.strip()}"
    for document in ("AGENTS.md", "INSTALL.md")
    for line in (ROOT / document).read_text().splitlines()
    if re.search(r"\bcp\s+roster\.md\.example\s+roster\.md\b", line)
    and not re.search(r"\[\s+-f\s+roster\.md\s+\]\s*\|\|", line)
]
check("no documented step copies roster.md.example over an existing roster.md", [],
      unguarded_roster_copies)

# A hand-written .env means no form and no roster.md (#135). `paynani roster
# add` creates the file with the first row; a bare template copy authorises
# nobody, so both install documents point at the command.
# A tester held an install that was already healthy open while waiting for
# test mail a person had to send (#146). The required checklist must be
# something the agent can finish alone; mail sent by a person lives in §7.1.
install_text = (ROOT / "INSTALL.md").read_text()
required_section = install_text.split("## 7. Verification", 1)[1].split("### 7.1", 1)[0]
check("INSTALL.md §7: no required check needs a person to send mail", [],
      [phrase for phrase in ("have someone external send you mail", "Send yourself one",
                             "Worth asking your external sender")
       if phrase in required_section])
check("INSTALL.md: the real-mail tests have an optional §7.1", True,
      "### 7.1 Optional: real mail, after the install is complete" in install_text)
agents_text = (ROOT / "AGENTS.md").read_text()
check("AGENTS.md step 2: OpenCode asks the human to wake it", True,
      "write 'listo' here" in agents_text)
check("AGENTS.md step 2: no promise to continue after onboard exits", False,
      "and then you\ncontinue at step 3." in agents_text)
check("AGENTS.md step 8: the checklist no longer has to pass in full", False,
      "passes in full" in agents_text)
check("AGENTS.md step 8: §7.1 never holds the completion report", True,
      "never hold the report for" in agents_text)

check("AGENTS.md and INSTALL.md create a missing roster.md with paynani roster add", [],
      [document for document in ("AGENTS.md", "INSTALL.md")
       if "scripts/paynani roster add" not in (ROOT / document).read_text()])

# macOS upgrades need the same explicit supervisor steps as Linux. The release
# that first changed the listener after adding LaunchAgents exposed that the
# upgrade guide named the wrong inventory and had no restart command (#149).
upgrade_text = (ROOT / "UPGRADE.md").read_text()
check("UPGRADE.md names three LaunchAgents", False,
      "two LaunchAgents" in upgrade_text)
for label in ("com.paynani.idle", "com.paynani.dispatch",
              "com.paynani.logrotate"):
    check(f"UPGRADE.md names {label}", True, label in upgrade_text)
for label in ("com.paynani.idle", "com.paynani.dispatch"):
    command = f'launchctl kickstart -k "gui/$(id -u)/{label}"'
    check(f"UPGRADE.md restarts {label}", True, command in upgrade_text)
check("UPGRADE.md no longer requires real mail", False,
      "not optional politeness" in upgrade_text)
check("UPGRADE.md points optional real mail to INSTALL.md §7.1", True,
      "`INSTALL.md` §7.1" in upgrade_text)
check("UPGRADE.md has no em dashes", False, "—" in upgrade_text)
check("UPGRADE.md lines stay within 80 columns", [],
      [number for number, line in enumerate(upgrade_text.splitlines(), 1)
       if len(line) > 80])

design_text = (ROOT / "DESIGN.md").read_text()
start_marker = "<!-- capabilities-matrix:start -->"
end_marker = "<!-- capabilities-matrix:end -->"
check("DESIGN.md carries generated capabilities matrix markers", True,
      start_marker in design_text and end_marker in design_text)
if start_marker in design_text and end_marker in design_text:
    generated = capabilities.markdown_table().strip()
    block = design_text.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()
    check("DESIGN.md capabilities matrix comes from harness/capabilities.py",
          generated, block)

capabilities_page = (ROOT / "HARNESS_CAPABILITIES.md").read_text().strip()
check("HARNESS_CAPABILITIES.md is generated from harness/capabilities.py",
      capabilities.markdown_page().strip(), capabilities_page)
check("HARNESS_CAPABILITIES.md renders OpenCode no-target-session scenario", True,
      "OpenCode TUI open without destination session" in capabilities_page)

candidate_template = ROOT / ".github" / "ISSUE_TEMPLATE" / "harness-candidate.md"
check("candidate harness issue template exists", True, candidate_template.is_file())
candidate_text = candidate_template.read_text() if candidate_template.is_file() else ""
for question in (
    "session-start hook",
    "open session after it becomes idle",
    "target session is busy",
    "non-interactive or headless mode",
    "credentials and runtime secrets",
):
    check(f"candidate template asks about {question}", True, question in candidate_text)

def readme_shape(document):
    """
    A translation-agnostic fingerprint of a README: how many headers at each
    level, how many fenced code blocks, and which other repository documents
    it links to.

    Text differs by design between README.md (es-MX, the source of truth) and
    its four i18n/README.*.md translations, so this never compares words. It
    compares structure: a heading added to one and not the others, or a code
    block present in the source but dropped from a translation (#173 found
    i18n/README.es-ES.md missing the `roster explain` example this way), moves
    the counts out of sync and fails by name.

    Link targets are normalized before comparing: a translation links to its
    own locale's MAILBOX_SETUP.<locale>.md and to its sibling
    README.<locale>.md files, neither of which the source or any other
    translation names, so both are stripped -- one by dropping the locale
    suffix shared with every other per-locale document, the other by
    recognising the README-to-README navigation links by name and excluding
    them outright.
    """
    text = (ROOT / document).read_text()
    headers = re.findall(r"^(#{1,6})\s", text, re.MULTILINE)
    header_counts = tuple(
        sum(1 for h in headers if len(h) == level) for level in range(1, 7)
    )
    code_blocks = len(re.findall(r"^```", text, re.MULTILINE)) // 2
    link_targets = set()
    for link in re.findall(r"\]\(([^)]+)\)", text):
        if link.startswith(("http://", "https://", "#")) or not link.endswith(".md"):
            continue
        name = pathlib.Path(link).name
        if re.fullmatch(r"README(\.[a-z]{2}-[A-Z]{2})?\.md", name):
            continue
        link_targets.add(re.sub(r"\.[a-z]{2}-[A-Z]{2}(?=\.md$)", "", name))
    return {"headers by level": header_counts, "code blocks": code_blocks,
            "linked documents": link_targets}

translations = sorted(path.name for path in (ROOT / "i18n").glob("README.*.md"))
source_shape = readme_shape("README.md")
for translation in translations:
    check(f"i18n/{translation} matches README.md's structure",
          source_shape, readme_shape(f"i18n/{translation}"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
