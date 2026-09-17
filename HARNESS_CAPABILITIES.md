# Runtime Capabilities

This page is generated from `harness/capabilities.py`; edit the data there.

## Summary Matrix

| Adapter | Modes | Durable handoff | Requires open session | Starts agent run | Presentation observable | Headless | Level |
|---|---|---|---|---|---|---|---|
| Claude Code (`claudecode`) | replay | supported | no | opt_in | unknown | supported | replay-only |
| OpenAI Codex (`codex`) | replay, now | supported | no | opt_in | unknown | supported | live |
| Hermes Agent (`hermes`) | now, durable | supported | no | yes | unknown | supported | autonomous |
| OpenClaw (`openclaw`) | now | unsupported | yes | unknown | unknown | unsupported | live |
| OpenCode (`opencode`) | replay | supported | no | yes | yes | unsupported | autonomous |

## Claude Code (`claudecode`)

### How It Arrives

Paynani appends one line to state/session.spool.

### Guarantee

The event is durably waiting for SessionStart or an armed Monitor.

### What Not To Promise

Do not promise a Claude Code session was open or read the spool.

## OpenAI Codex (`codex`)

### How It Arrives

Paynani appends to state/codex.spool, then may call codex queue.

### Guarantee

The event is durably spooled; a registered live session may be queued.

### What Not To Promise

Do not promise Codex completed the mail work or that queue is public API.

## Hermes Agent (`hermes`)

### How It Arrives

Paynani posts the envelope to authenticated Hermes HTTP routes.

### Guarantee

Hermes accepted or delivered the route request it reported.

### What Not To Promise

Do not treat a 202 roster acceptance as completed agent work.

## OpenClaw (`openclaw`)

### How It Arrives

Paynani calls openclaw system event --mode now.

### Guarantee

The runtime accepted a live notification attempt.

### What Not To Promise

Do not promise the agent run started, read it, or replied.

## OpenCode (`opencode`)

### How It Arrives

Paynani appends to state/opencode.spool; the OpenCode plugin presents it.

### Guarantee

The event is durable, and the plugin can start an idle target session.

### What Not To Promise

Do not promise delivery when the TUI is open without a target session.

### Scenarios

| Scenario | Event accepted | Delivered to target session | Operator state | Label |
|---|---|---|---|---|
| `open_tui_without_target_session` | yes | no | warning | OpenCode TUI open without destination session |
