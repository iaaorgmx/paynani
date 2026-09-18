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

Two of the six rows are universal -- every runtime prints the same shape of
line, because the listener and the dispatcher exist outside any runtime
adapter. The other four turn on whether a runtime session was ever open, which
only matters for a pull-based runtime (Claude Code, Codex, OpenCode); OpenClaw
and Hermes Agent are always either reachable or not, with no distinct "open
without a session" state to report.

## Universal: listener, dispatcher, replies

| State | What it means | What `healthcheck.py` prints |
|---|---|---|
| Listener healthy | The IDLE connection is up and has a position in the mailbox. | `listener     active, <mailbox> at uid <N>`, with no `last diagnostic:` line under it. |
| Listener unhealthy | The service is not active, or it is retrying and cannot complete an IDLE cycle. | `listener     <inactive/failed/unknown>...`, or `active` with a `last diagnostic: <error>` line underneath (a retrying listener keeps writing to `idle.err.log` even mid-retry). |
| Dispatcher healthy | The dispatcher is running and has handed at least one event to a runtime. | `dispatcher   active` followed by `last accepted <event_id> by <runtime> at <timestamp>`. |
| Dispatcher unhealthy | The service is down, or it has never accepted anything. | `dispatcher   <inactive/failed/unknown>`, or `active` with `nothing has been accepted by a runtime yet`. |
| Roster mail unanswered | Roster mail was delivered to a runtime and nothing has been sent since. | `replies      N roster message(s) delivered; ...` followed by `nothing sent since the newest one at <timestamp>`. Reported, never judged: the reply may be in progress, or the message may not have warranted one. |
| Roster mail answered (or none pending) | Every delivered roster message has a send recorded after it, or none has been delivered yet. | Same `replies` line, with no `nothing sent since...` line under it. |

## Per-runtime: closed, open without a session, delivering

OpenCode's plugin keeps a presence registry (`state/opencode.processes/`,
added by #160) and Claude Code's watcher keeps one per session
(`state/sessions/<id>/watch.json`, added by #170); both can tell "closed"
apart from "open, nothing delivering yet." Codex, OpenClaw and Hermes Agent
each report a single reachability check instead -- they cannot make this
distinction today.

| State | OpenCode | Codex | Claude Code | OpenClaw / Hermes Agent |
|---|---|---|---|---|
| Runtime closed | `no OpenCode process is open; unread bytes wait until OpenCode is open, which is normal` | Not distinguished from "reachable": `NOT REACHABLE: <detail>` if the CLI cannot be run right now, `reachable` otherwise. | `watch        no session has armed a watch; unread bytes with no session open is normal` (no registry at all), or `watch        none armed: the last one (session <id>) expired at <time> without re-arming` / `was killed (pid gone) without re-arming`; with unread bytes the second form is also a warning. | Not distinguished: `NOT REACHABLE: <detail>` (binary not found or not runnable) or `reachable`. |
| Runtime open, no session yet | `OpenCode is open (process <pid>) but not delivering yet: write in a session and delivery starts when it is idle` | Not distinguished -- see above. | `N session(s) ran the hook and never armed` under the `watch` row: the SessionStart hook wrote a registry and no watcher took it. | Not distinguished -- see above. |
| Runtime delivering | `delivering from OpenCode process <pid>` | `Codex wakes a registered live session with codex queue; unread bytes wait for SessionStart replay`, plus `reachable`. | `watch        armed by session <id> since <time>, expires <time>, last heartbeat <time>` (#170: read from `state/sessions/<id>/watch.json`, kept by the watcher). | `reachable` (proves the binary answers, not that a delivered event reached anyone). |

**Reading this table:** "reachable" and "NOT REACHABLE" always sit on their
own line, right after the spool line, prefixed with `this proves the runtime
answers, not that a delivered event reaches anyone` (OpenClaw/Hermes/Codex); on
Claude Code the `watch` row sits between the spool line and that one. None of these lines is
proof that a person saw and acted on a message -- only `replies` speaks to
that, and only for roster mail.

See [`HARNESS_CAPABILITIES.md`](HARNESS_CAPABILITIES.md) for which of these
states each runtime's mode (`replay`, `now`, `durable`) and `Requires open
session` column predict, and [`INSTALL.md`](INSTALL.md) §7 for running
`healthcheck.py` as part of a fresh install's verification.
