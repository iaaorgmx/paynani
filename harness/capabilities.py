#!/usr/bin/env python3
"""Static runtime capability declarations for paynani adapters."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy

VERSION = 1

TRI_STATE = ("yes", "no", "unknown")
TRI_STATE_WITH_OPT_IN = ("yes", "no", "opt_in", "unknown")
SUPPORT_STATE = ("supported", "unsupported", "unknown")
DELIVERY_MODES = ("now", "durable", "replay")
LEVELS = ("replay-only", "live", "autonomous", "unknown")
CREDENTIAL_LOCATIONS = ("harness_workspace_env", "route_env_and_secret_files")
SESSION_DISCOVERY = ("cli_gateway", "health_route", "session_start_hook", "opencode_plugin")

REQUIRED_STATIC_FIELDS = (
    "delivery_modes",
    "durable_handoff",
    "requires_open_session",
    "starts_agent_run",
    "presentation_observable",
    "headless_mode",
    "credentials_location",
    "session_discovery",
)

REQUIRED_SCENARIO_FIELDS = (
    "event_accepted",
    "delivered_to_target_session",
    "operator_visible_state",
    "documentation_label",
)

CAPABILITIES = {
    "openclaw": {
        "display_name": "OpenClaw",
        "static": {
            "delivery_modes": ("now",),
            "durable_handoff": "unsupported",
            "requires_open_session": "yes",
            "starts_agent_run": "unknown",
            "presentation_observable": "unknown",
            "headless_mode": "unsupported",
            "credentials_location": "harness_workspace_env",
            "session_discovery": "cli_gateway",
        },
        "dynamic_observations": (
            "binary_runnable",
            "gateway_reachable",
            "session_destination_available",
            "last_delivery_attempt",
            "last_delivery_result",
        ),
        "notes": (
            "openclaw system event --mode now accepts a live notification; "
            "it does not start an agent run or prove the session acted on it."
        ),
    },
    "hermes": {
        "display_name": "Hermes Agent",
        "static": {
            "delivery_modes": ("now", "durable"),
            "durable_handoff": "supported",
            "requires_open_session": "no",
            "starts_agent_run": "yes",
            "presentation_observable": "unknown",
            "headless_mode": "supported",
            "credentials_location": "route_env_and_secret_files",
            "session_discovery": "health_route",
        },
        "dynamic_observations": (
            "health_route_reachable",
            "notify_route_configured",
            "roster_route_configured",
            "last_delivery_attempt",
            "last_delivery_result",
        ),
        "notes": (
            "Hermes routes authenticate the envelope; a 202 roster response "
            "means accepted by Hermes, not completed by the agent."
        ),
    },
    "claudecode": {
        "display_name": "Claude Code",
        "static": {
            "delivery_modes": ("replay",),
            "durable_handoff": "supported",
            "requires_open_session": "no",
            "starts_agent_run": "opt_in",
            "presentation_observable": "unknown",
            "headless_mode": "supported",
            "credentials_location": "harness_workspace_env",
            "session_discovery": "session_start_hook",
        },
        "dynamic_observations": (
            "spool_writable",
            "spool_unread_bytes",
            "session_watch_state",
        ),
        "notes": (
            "Delivery is a durable spool append. SessionStart replays it later; "
            "with session_watch.sh armed, Monitor can present it live seconds "
            "after the append. Agent mode is opt-in."
        ),
    },
    "codex": {
        "display_name": "OpenAI Codex",
        "static": {
            "delivery_modes": ("replay", "now"),
            "durable_handoff": "supported",
            "requires_open_session": "no",
            "starts_agent_run": "opt_in",
            "presentation_observable": "unknown",
            "headless_mode": "supported",
            "credentials_location": "harness_workspace_env",
            "session_discovery": "session_start_hook",
        },
        "dynamic_observations": (
            "spool_writable",
            "registered_session",
            "last_queue_attempt",
            "last_queue_result",
        ),
        "notes": (
            "Every event is spooled first. codex queue can wake a registered "
            "live session; headless exec is opt-in."
        ),
    },
    "opencode": {
        "display_name": "OpenCode",
        "static": {
            "delivery_modes": ("replay",),
            "durable_handoff": "supported",
            "requires_open_session": "no",
            "starts_agent_run": "yes",
            "presentation_observable": "yes",
            "headless_mode": "unsupported",
            "credentials_location": "harness_workspace_env",
            "session_discovery": "opencode_plugin",
        },
        "dynamic_observations": (
            "spool_writable",
            "plugin_installed",
            "open_processes",
            "session_destination_available",
            "spool_unread_bytes",
        ),
        "scenarios": {
            "open_tui_without_target_session": {
                "event_accepted": "yes",
                "delivered_to_target_session": "no",
                "operator_visible_state": "warning",
                "documentation_label": "OpenCode TUI open without destination session",
            },
        },
        "notes": (
            "The dispatcher only spools. The OpenCode plugin presents pending "
            "events when an idle session exists; open TUI without a destination "
            "is an explicit state."
        ),
    },
}


def derived_level(static):
    """Return replay-only, live, autonomous, or unknown from static fields."""
    starts = static.get("starts_agent_run")
    modes = set(static.get("delivery_modes") or ())
    if starts == "yes":
        return "autonomous"
    if "now" in modes:
        return "live"
    if "replay" in modes or static.get("durable_handoff") == "supported":
        return "replay-only"
    return "unknown"


def _validate_adapter(name, spec):
    errors = []
    if not spec.get("display_name"):
        errors.append(f"{name}: missing display_name")
    static = spec.get("static")
    if not isinstance(static, dict):
        return [f"{name}: missing static declaration"]
    for field in REQUIRED_STATIC_FIELDS:
        if field not in static:
            errors.append(f"{name}: missing static.{field}")
    modes = static.get("delivery_modes", ())
    if not modes or not isinstance(modes, (tuple, list)):
        errors.append(f"{name}: static.delivery_modes must be a non-empty list")
    for mode in modes:
        if mode not in DELIVERY_MODES:
            errors.append(f"{name}: unknown delivery mode {mode!r}")
    for field in ("requires_open_session", "presentation_observable"):
        if static.get(field) not in TRI_STATE:
            errors.append(f"{name}: static.{field} must be one of {TRI_STATE}")
    if static.get("starts_agent_run") not in TRI_STATE_WITH_OPT_IN:
        errors.append(
            f"{name}: static.starts_agent_run must be one of {TRI_STATE_WITH_OPT_IN}"
        )
    for field in ("durable_handoff", "headless_mode"):
        if static.get(field) not in SUPPORT_STATE:
            errors.append(f"{name}: static.{field} must be one of {SUPPORT_STATE}")
    if static.get("credentials_location") not in CREDENTIAL_LOCATIONS:
        errors.append(
            f"{name}: static.credentials_location must be one of {CREDENTIAL_LOCATIONS}"
        )
    if static.get("session_discovery") not in SESSION_DISCOVERY:
        errors.append(f"{name}: static.session_discovery must be one of {SESSION_DISCOVERY}")
    if not spec.get("dynamic_observations"):
        errors.append(f"{name}: missing dynamic_observations")
    for scenario, fields in (spec.get("scenarios") or {}).items():
        for field in REQUIRED_SCENARIO_FIELDS:
            if field not in fields:
                errors.append(f"{name}: scenario {scenario} missing {field}")
            elif isinstance(fields.get(field), str) and not fields.get(field).strip():
                errors.append(f"{name}: scenario {scenario} {field} must not be empty")
        for field in ("event_accepted", "delivered_to_target_session"):
            if fields.get(field) not in TRI_STATE:
                errors.append(f"{name}: scenario {scenario} {field} must be one of {TRI_STATE}")
        if fields.get("operator_visible_state") not in ("ok", "warning", "blocked", "unknown"):
            errors.append(
                f"{name}: scenario {scenario} operator_visible_state must be ok/warning/blocked/unknown"
            )
    level = derived_level(static)
    if level not in LEVELS:
        errors.append(f"{name}: derived level {level!r} is invalid")
    return errors


def validate(capabilities=CAPABILITIES):
    errors = []
    for name, spec in capabilities.items():
        errors.extend(_validate_adapter(name, spec))
    return errors


def as_dict():
    data = {
        "version": VERSION,
        "adapters": deepcopy(CAPABILITIES),
    }
    for spec in data["adapters"].values():
        spec["derived_level"] = derived_level(spec["static"])
    return data


def markdown_table():
    header = (
        "| Adapter | Modes | Durable handoff | Requires open session | "
        "Starts agent run | Presentation observable | Headless | Level |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    rows = []
    data = as_dict()["adapters"]
    for name in sorted(data):
        spec = data[name]
        static = spec["static"]
        rows.append(
            "| {display} (`{name}`) | {modes} | {durable} | {session} | "
            "{starts} | {presentation} | {headless} | {level} |".format(
                display=spec["display_name"],
                name=name,
                modes=", ".join(static["delivery_modes"]),
                durable=static["durable_handoff"],
                session=static["requires_open_session"],
                starts=static["starts_agent_run"],
                presentation=static["presentation_observable"],
                headless=static["headless_mode"],
                level=spec["derived_level"],
            )
        )
    return "\n".join([header] + rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON capabilities.")
    parser.add_argument("--markdown", action="store_true", help="Print the Markdown matrix.")
    args = parser.parse_args(argv)
    errors = validate()
    if errors:
        for error in errors:
            print(error)
        return 1
    if args.markdown:
        print(markdown_table())
        return 0
    print(json.dumps(as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
