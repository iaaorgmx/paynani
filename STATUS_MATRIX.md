# Status matrix

`scripts/healthcheck.py` prints one line per mechanism, not one line per named
state, so reading it during a field verification means recognising which lines
go together. This page is that map: given a situation, what `healthcheck.py`
actually prints for it. It grew out of two false reads in the field --
[#157](https://github.com/iaaorgmx/paynani/issues/157) mistook "OpenCode open,
nobody has written to it yet" for "OpenCode closed", and
[#160](https://github.com/iaaorgmx/paynani/issues/160) is the fix that let
`healthcheck.py` tell the two apart for OpenCode. This page generalizes the
lesson to every runtime and to the other two mechanisms `healthcheck.py`
reports on.

The listener, dispatcher, replies and notifiers rows are universal -- every
runtime prints the same shape of line, because those mechanisms exist outside
any runtime adapter. The closed/open/delivering distinction turns on whether a
runtime session was ever open, which only matters for a pull-based runtime
(Claude Code, Codex, OpenCode, Antigravity CLI); OpenClaw and Hermes Agent are always either
reachable or not, with no distinct "open without a session" state to report.
The instructions standing rule exists on OpenClaw alone.

## Universal: listener, dispatcher, replies

| State | What it means | What `healthcheck.py` prints |
|---|---|---|
| Listener healthy | The IDLE connection is up and has a position in the mailbox. | `listener     active, <mailbox> at uid <N>`, with no `last diagnostic:` line under it. |
| Listener unhealthy | The service is not active, or it is retrying and cannot complete an IDLE cycle. | `listener     <inactive/failed/unknown>...`, or `active` with a `last diagnostic: <error>` line underneath (a retrying listener keeps writing to `idle.err.log` even mid-retry). |
| Dispatcher healthy | The dispatcher is running and has handed at least one event to a runtime. | `dispatcher   active` followed by `last accepted <event_id> by <runtime> at <timestamp>`. |
| Dispatcher unhealthy | The service is down, or it has never accepted anything. | `dispatcher   <inactive/failed/unknown>`, or `active` with `nothing has been accepted by a runtime yet`. |
| Roster mail unanswered | Roster mail was delivered to a runtime and nothing has been sent since. | `replies      N roster message(s) delivered; ...` followed by `nothing sent since the newest one at <timestamp>`. Reported, never judged: the reply may be in progress, or the message may not have warranted one. |
| Roster mail answered (or none pending) | Every delivered roster message has a send recorded after it, or none has been delivered yet. | Same `replies` line, with no `nothing sent since...` line under it. |

Two more rows, both universal and both new in 0.7.1 (#188), sit under
`roster` rather than getting their own line:

| State | What it means | What `healthcheck.py` prints |
|---|---|---|
| GitHub notifier declared | A roster row's `GitHub` column has a handle, so that person's GitHub notifications count as their mail. | `             notifiers: <address> via <header>, from the github column` (or `from the notifiers table`, for the older explicit-row form). |
| No notifier declared | Nothing in `roster.md` maps a notification sender to a roster address. | `             no notifiers: mail sent on someone's behalf (GitHub, Jira) arrives untagged`. |

## Per-runtime: closed, open without a session, delivering

OpenCode's plugin keeps a presence registry (`state/opencode.processes/`,
added by #160) and Claude Code's watcher keeps one per session
(`state/sessions/<id>/watch.json`, added by #170); both can tell "closed"
apart from "open, nothing delivering yet." Codex, OpenClaw and Hermes Agent
each report a single reachability check instead -- they cannot make this
distinction today.

| State | OpenCode | Codex | Claude Code | OpenClaw / Hermes Agent |
|---|---|---|---|---|
| Runtime closed | `no OpenCode process is open; unread bytes wait until OpenCode is open, which is normal` | Not distinguished from "reachable": `NOT REACHABLE: <detail>` if the CLI cannot be run right now, `reachable` otherwise. | `watch        no session has armed a watch; unread bytes with no session open is normal` (no registry at all), or `watch        none armed: the last one (session <id>) ended at <time> (the Monitor was retired) without re-arming` / `expired at <time> without re-arming` / `was killed (pid gone) without re-arming`; with unread bytes the second form is also a warning. | Not distinguished: `NOT REACHABLE: <detail>` (binary not found or not runnable) or `reachable`. |
| Runtime open, no session yet | `OpenCode is open (process <pid>) but not delivering yet: write in a session and delivery starts when it is idle` | Not distinguished -- see above. | `N session(s) ran the hook and never armed` under the `watch` row: the SessionStart hook wrote a registry and no watcher took it. | Not distinguished -- see above. |
| Runtime delivering | `delivering from OpenCode process <pid>` | `Codex wakes a registered live session with codex queue; unread bytes wait for SessionStart replay`, plus `reachable`. | `watch        armed by session <id> since <time>, expires <time>, last heartbeat <time>` (#170: read from `state/sessions/<id>/watch.json`, kept by the watcher). | `reachable` (proves the binary answers, not that a delivered event reached anyone). |

**Reading this table:** "reachable" and "NOT REACHABLE" always sit on their
own line, right after the spool line, prefixed with `this proves the runtime
answers, not that a delivered event reaches anyone` (OpenClaw/Hermes/Codex); on
Claude Code the `watch` row sits between the spool line and that one. None of these lines is
proof that a person saw and acted on a message -- only `replies` speaks to
that, and only for roster mail.

## Antigravity CLI: the spool and autonomous mode

Antigravity CLI keeps no presence registry, so like Codex it cannot tell
"closed" from "open, nothing delivering yet": `agy`'s SessionStart and
PreInvocation hooks show the spool, and whether a conversation runs them is not
visible from outside. What it can report is the spool and, with autonomous mode
on (`PAYNANI_ANTIGRAVITY_MODE=agent`, the default since #771), how the last
`agy -p` run went. Measured on Manu Agy-Tob's host with `agy` 1.5.3 and
paynani 0.25.0 (2026-11-08, #749).

| State | What it means | What `healthcheck.py` prints |
|---|---|---|
| Spool line | Always shown. Unread bytes with no conversation open is normal: the next conversation or turn shows them. | `spool        <clone>/state/antigravity.spool`, then `N byte(s) not yet picked up by a session, of M` and `whether a session has armed a watch is not observable from here; unread bytes with no session open is normal`, then `reachable: <spool>` (the spool is writable). |
| Autonomous run answered | The dispatcher wrote the spool and `agy -p` exited 0 with `SUCCESS` and no refused permission. | Under `dispatcher`: `last accepted <event_id> by antigravity at <timestamp>` and `runtime said: spooled; agy -p run completed`. |
| Autonomous run failed | The event is still in the spool for the next conversation, and it is not retried. The problem is one of `login`, `permission`, `timeout` or `run`; `paynani doctor` says what to do in its `last_agent_run` row. | `runtime said: spooled; agy -p failed (<problem>): <detail>`. Measured: `agy -p failed (permission): permission that headless mode cannot prompt for, so it was auto-denied` (the run had already answered with `send.sh`, then tried to edit a file outside the sandbox). A run cut short by a restart of `paynani-dispatch` prints no `runtime said:` line, because the dispatcher stopped before it could log one; `state/antigravity.json` keeps it as `problem: run`, `detail: interrupted`, and `paynani doctor` shows it. |
| Autonomous mode off | Only the spool is written. | `last accepted <event_id> by antigravity at <timestamp>` with no `runtime said:` line under it; mail waits for someone to start a turn in `agy`. |

## OpenClaw only: the instructions standing rule

A row that exists on no other runtime, because it caught a real gap:
`healthcheck.py` and every other row here could be green while OpenClaw never
answered a single piece of roster mail (#186). Delivery only hands OpenClaw a
notification line; turning that into a reply needs a standing rule in the
agent's own `AGENTS.md`, and nothing else checks whether it is there.

| State | What it means | What `healthcheck.py` prints |
|---|---|---|
| Rule in place | `scripts/openclaw_rules.py --install` has written the rule block. | `instructions standing rule in place in <path>` |
| Rule missing or outdated | The block is absent, or its wording no longer matches. | `instructions standing rule <ABSENT/OUTDATED> in <path>` followed by `run: python3 scripts/openclaw_rules.py --install` |
| Could not check | The target file could not be read. | `instructions standing rule in <path>: could not check` |

This row is absent entirely on every runtime except OpenClaw -- Claude Code,
Codex, OpenCode and Hermes Agent carry the same instruction inside the prompt
itself, so there is nothing standing to verify.

See [`HARNESS_CAPABILITIES.md`](HARNESS_CAPABILITIES.md) for which of these
states each runtime's mode (`replay`, `now`, `durable`) and `Requires open
session` column predict, and [`INSTALL.md`](INSTALL.md) §7 for running
`healthcheck.py` as part of a fresh install's verification.
