#!/usr/bin/env python3
"""Capability declarations are the contract shared by adapters, docs and doctor."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import capabilities  # noqa: E402
import dispatch  # noqa: E402

passed = failed = 0


def check(desc, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}\n       expected: {expected!r}\n       actual:   {actual!r}")
        failed += 1


errors = capabilities.validate()
check("capability declarations validate", [], errors)

declared = set(capabilities.CAPABILITIES)
available = set(dispatch.available())
check("every shipped adapter declares capabilities", available, declared)
check("no capabilities are declared for missing adapters", set(), declared - available)

data = capabilities.as_dict()
for name, spec in data["adapters"].items():
    static = spec["static"]
    missing = [field for field in capabilities.REQUIRED_STATIC_FIELDS if field not in static]
    check(f"{name}: no required static field is missing", [], missing)
    check(f"{name}: derived level is present", True,
          spec["derived_level"] in capabilities.LEVELS)

check("OpenClaw is live but not autonomous", "live",
      data["adapters"]["openclaw"]["derived_level"])
check("OpenClaw does not claim presentation is observable", "unknown",
      data["adapters"]["openclaw"]["static"]["presentation_observable"])
check("Hermes is autonomous", "autonomous",
      data["adapters"]["hermes"]["derived_level"])
check("Claude Code is replay-only unless an opt-in mode starts runs", "replay-only",
      data["adapters"]["claudecode"]["derived_level"])
check("OpenCode exposes a session-destination observation", True,
      "session_destination_available" in data["adapters"]["opencode"]["dynamic_observations"])

table = capabilities.markdown_table()
check("Markdown matrix includes OpenCode's no-session case source field", True,
      "OpenCode" in table and "replay-only" in table)

print()
print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
