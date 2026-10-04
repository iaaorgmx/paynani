#!/usr/bin/env python3
"""
Tests for scripts/paynani_lib/harness_rules.py (BOOT-4, #344).

What matters is what the module does NOT do: write a rule outside the three
paynani scripts, touch another key of the harness settings, or pick for the
human when it cannot read the current state. No real harness is touched: HOME
is a temporary directory and `openclaw` is a fake.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from paynani_lib import harness_rules as hr  # noqa: E402

passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


tmp = Path(tempfile.mkdtemp(prefix="paynani-rules-"))
clone = tmp / "clone"
clone.mkdir()
home = tmp / "home"
settings = home / ".claude" / "settings.json"
quiet = lambda *a, **k: None  # noqa: E731

# --- Claude Code ------------------------------------------------------------
rules = hr.claude_rules(clone)
check("three rules, all by absolute path of this clone", True,
      len(rules) == 3 and all(str(clone.resolve()) in r for r in rules))
check("B7: only scripts/paynani, scripts/send.sh and harness/session_watch.sh", True,
      [r.split(str(clone.resolve()))[1].split()[0].rstrip(")") for r in rules]
      == ["/scripts/paynani", "/scripts/send.sh", "/harness/session_watch.sh"])

check("no settings file: the plan adds the three", 3, len(hr.plan("claudecode", clone, home=home)))
ok, detail = hr.apply("claudecode", clone, assume_yes=True, home=home, out=quiet)
check("apply creates settings.json with the rules", (True, rules),
      (ok, json.loads(settings.read_text())["permissions"]["allow"]))
check("a new settings.json is 600", 0o600, settings.stat().st_mode & 0o777)

settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": []},
                                "permissions": {"allow": ["Bash(git status)"], "deny": ["Read(/secret)"]}}))
settings.chmod(0o644)
ok, detail = hr.apply("claudecode", clone, assume_yes=True, home=home, out=quiet)
data = json.loads(settings.read_text())
check("other keys stay as they were", ("x", {"Stop": []}, ["Read(/secret)"]),
      (data["model"], data["hooks"], data["permissions"]["deny"]))
check("existing allow rules are kept, ours appended", ["Bash(git status)"] + rules, data["permissions"]["allow"])
check("the file mode is kept", 0o644, settings.stat().st_mode & 0o777)

before = settings.read_text()
check("second run: nothing to add", [], hr.plan("claudecode", clone, home=home))
ok, detail = hr.apply("claudecode", clone, assume_yes=True, home=home, out=quiet)
check("second run: ok, file unchanged", (True, "harness rules: already in place", before),
      (ok, detail, settings.read_text()))

settings.write_text(json.dumps({"permissions": {"allow": []}}))
ok, detail = hr.apply("claudecode", clone, home=home, out=quiet, confirm=lambda _: "n")
check("the owner says no: ok, nothing written", (True, []),
      (ok, json.loads(settings.read_text())["permissions"]["allow"]))

settings.write_text("{not json")
ok, detail = hr.apply("claudecode", clone, assume_yes=True, home=home, out=quiet)
check("broken settings.json: refused, not overwritten", (False, "{not json"), (ok, settings.read_text()))
settings.write_text(json.dumps({"permissions": {"allow": "Bash(*)"}}))
ok, _ = hr.apply("claudecode", clone, assume_yes=True, home=home, out=quiet)
check("allow that is not a list: refused", False, ok)

# a symlinked settings.json (dotfiles) is written at its target, link kept
dot = tmp / "dotfiles"
dot.mkdir()
target = dot / "settings.json"
target.write_text(json.dumps({"model": "y"}, indent=4) + "\n")
settings.unlink()
settings.symlink_to(target)
ok, _ = hr.apply("claudecode", clone, assume_yes=True, home=home, out=quiet)
check("symlinked settings.json: still a link, target has the rules", (True, True, rules),
      (ok, settings.is_symlink(), json.loads(target.read_text())["permissions"]["allow"]))
check("and the original 4-space indentation is kept", True, '\n    "model"' in target.read_text())
settings.unlink()


def no_terminal(prompt):
    raise EOFError


settings.write_text(json.dumps({"permissions": {"allow": []}}))
ok, detail = hr.apply("claudecode", clone, home=home, out=quiet, confirm=no_terminal)
check("no terminal to confirm: refused with a pointer to --yes, nothing written", (False, True, []),
      (ok, "--yes" in detail, json.loads(settings.read_text())["permissions"]["allow"]))

# --- OpenClaw -----------------------------------------------------------------
calls = []


def fake_openclaw(listed, as_strings=False):
    def runner(argv, **kw):
        calls.append(argv[1:])
        if argv[1:3] == ["approvals", "get"]:
            if "--agent" in argv:  # OpenClaw 2026.9.2 rejects it (#352)
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr='does not recognize option "--agent"')
            entries = listed if as_strings else [{"pattern": p} for p in (listed or [])]
            body = {"file": {"version": 1, "defaults": {}, "agents": {"main": {"allowlist": entries}} if listed is not None else {}}}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(body), stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="added", stderr="")
    return runner


which = lambda name: "/fake/openclaw"  # noqa: E731
paths = hr.scripts(clone)
steps = hr.plan("openclaw", clone, which=which, runner=fake_openclaw(None))
check("openclaw: empty file.agents -> one allowlist add per script, agent main",
      [f"openclaw approvals allowlist add --agent main {p}" for p in paths], steps)
calls.clear()
hr.plan("openclaw", clone, which=which, runner=fake_openclaw([]))
check("openclaw: get is called as get --json, never with --agent", [["approvals", "get", "--json"]], calls)
calls.clear()
ok, _ = hr.apply("openclaw", clone, assume_yes=True, out=quiet, which=which, runner=fake_openclaw([paths[0]]))
adds = [c for c in calls if c[:3] == ["approvals", "allowlist", "add"]]
check("openclaw: only the missing ones are added, with --agent main",
      (True, [["approvals", "allowlist", "add", "--agent", "main", p] for p in paths[1:]]), (ok, adds))
check("openclaw: nothing to add when all are listed", [], hr.plan("openclaw", clone, which=which, runner=fake_openclaw(paths)))
check("openclaw: string entries count too", [], hr.plan("openclaw", clone, which=which, runner=fake_openclaw(paths, as_strings=True)))
lookalikes = [paths[0] + "_old", paths[1] + ".bak", paths[2]]
check("openclaw: paynani_old and send.sh.bak do not count as paynani and send.sh",
      [f"openclaw approvals allowlist add --agent main {p}" for p in paths[:2]],
      hr.plan("openclaw", clone, which=which, runner=fake_openclaw(lookalikes)))
manual = hr.plan("openclaw", clone, which=lambda n: None)
check("openclaw not on PATH: manual text, no command", True, len(manual) == 1 and manual[0].startswith("harness rules:"))


def failing_get(argv, **kw):
    return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")


def garbage_get(argv, **kw):
    return subprocess.CompletedProcess(argv, 0, stdout="Allowlist 0", stderr="")


for label, runner in (("fails", failing_get), ("is not JSON", garbage_get)):
    ok, detail = hr.apply("openclaw", clone, assume_yes=True, out=quiet, which=which, runner=runner)
    check(f"openclaw get {label}: manual text, nothing added", (True, "harness rules: printed for manual setup"), (ok, detail))

# --- the rest -----------------------------------------------------------------
for rt in ("hermes", "codex", "opencode"):
    printed = []
    ok, detail = hr.apply(rt, clone, assume_yes=True, home=home, out=printed.append)
    check(f"{rt}: prints the three paths, writes nothing", (True, True),
          (ok, all(p in printed[0] for p in paths)))
try:
    hr.plan("nope", clone)
    raised = False
except ValueError:
    raised = True
check("unknown runtime is refused", True, raised)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
