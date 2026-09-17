#!/usr/bin/env python3
"""Capability declarations are the contract shared by adapters, docs and doctor."""

import pathlib
import sys
from copy import deepcopy

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
check("OpenClaw does not claim agent runs never start", "unknown",
      data["adapters"]["openclaw"]["static"]["starts_agent_run"])
check("OpenClaw does not claim presentation is observable", "unknown",
      data["adapters"]["openclaw"]["static"]["presentation_observable"])
check("Hermes does not equate accepted roster delivery with presentation", "unknown",
      data["adapters"]["hermes"]["static"]["presentation_observable"])
check("Claude Code is replay-only unless an opt-in mode starts runs", "replay-only",
      data["adapters"]["claudecode"]["derived_level"])
check("OpenCode starts an agent run when its plugin delivers to an idle session", "yes",
      data["adapters"]["opencode"]["static"]["starts_agent_run"])
check("OpenCode derives autonomous from plugin delivery", "autonomous",
      data["adapters"]["opencode"]["derived_level"])
check("OpenCode exposes the open TUI without target-session scenario", True,
      "open_tui_without_target_session" in data["adapters"]["opencode"]["scenarios"])
check("OpenCode scenario says accepted is not target-session delivery", "no",
      data["adapters"]["opencode"]["scenarios"]["open_tui_without_target_session"][
          "delivered_to_target_session"
      ])

bad = deepcopy(capabilities.CAPABILITIES)
bad["openclaw"]["static"]["credentials_location"] = ""
check("empty credentials_location is invalid", True,
      any("credentials_location" in error for error in capabilities.validate(bad)))

bad = deepcopy(capabilities.CAPABILITIES)
bad["openclaw"]["static"]["session_discovery"] = ""
check("empty session_discovery is invalid", True,
      any("session_discovery" in error for error in capabilities.validate(bad)))

bad = deepcopy(capabilities.CAPABILITIES)
bad["opencode"]["scenarios"]["open_tui_without_target_session"]["documentation_label"] = ""
check("empty scenario documentation_label is invalid", True,
      any("documentation_label" in error for error in capabilities.validate(bad)))

table = capabilities.markdown_table()
check("Markdown matrix reflects OpenCode's derived level", True,
      "OpenCode (`opencode`)" in table and "autonomous" in table)

page = capabilities.markdown_page()
check("Generated page has the three required blocks per harness", True,
      "### How It Arrives" in page
      and "### Guarantee" in page
      and "### What Not To Promise" in page)
check("Generated OpenCode page renders the no-target-session scenario", True,
      "OpenCode TUI open without destination session" in page)

print()
print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
