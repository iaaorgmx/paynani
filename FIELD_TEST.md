# Field test

A reproducible checklist per runtime: which state to provoke, the exact
command that proves it, the exact text `healthcheck.py` (or another paynani
command) prints when that state holds, and what to paste into a GitHub
issue or PR as evidence. It exists because [#157](https://github.com/iaaorgmx/paynani/issues/157)
verified OpenCode's states by improvising over several comments; #160's
acceptance criteria turned that improvisation into a five-step list someone
could rerun. This document generalizes that list to every runtime, one
section at a time (#173).

Every expected output line here is copied from the source that prints it,
the same rule [`STATUS_MATRIX.md`](STATUS_MATRIX.md) follows -- if a step
doesn't match, either the state wasn't actually provoked, or this document
is stale and the mismatch is worth its own issue.

**Who runs this:** an agent, on its own real host, by hand -- the same way
Balam did for OpenCode in #157. It is not a script. Several steps need a
human or an agent literally typing in a live session, a TUI, or sending
real mail, which cannot be automated without already having the thing this
checklist is trying to prove exists.

## Claude Code (`claudecode`)

Covers the session-watch registry added in [#170](https://github.com/iaaorgmx/paynani/issues/170)
(`state/sessions/<session-id>/watch.json`), which is what turned `healthcheck`'s
`watch` row from unobservable into several distinguishable states.

**Before you start:** confirm this install is past #170. A session that
started on an older clone still gets mail (the SessionStart hook still
prints something to arm), but on the pre-#170 form the hook prints a byte
offset to arm with, not `--from-hook`, and that form never writes a
registry entry -- so `watch` reports "no session has armed a watch" even
while that session is actively receiving mail. That is not a bug to chase;
it is the sixth thing to rule out if step 1 or 3 below doesn't match.

**The pending line is baseline once any session exists, not a state you
provoke in isolation.** `write_registry()` runs unconditionally at every
SessionStart, before the agent can run anything -- so the instant a fresh
session can call `healthcheck.py`, its own registry already reads
`pending`. Steps 1a and 1b split what used to be one step: 1a is the
registry-free state, only real before the very first post-#170 session (or
after clearing it out); 1b is what every fresh session actually sees.

| # | State to provoke | Command | Exact expected output | Paste as evidence |
|---|---|---|---|---|
| 1a | No registries exist at all | Only true before the first post-#170 session on this install, or after `rm -rf state/sessions/` (registry state only, safe to clear -- not mail, roster, or credentials); then run `scripts/healthcheck.py \| grep -A2 '^watch'` | `watch        no session has armed a watch; unread bytes with no session open is normal` | Those two lines. |
| 1b | A fresh session, hook run, not yet armed | Start a fresh Claude Code session; before running the Monitor command the SessionStart hook prints, run the same grep | The top `watch` line that already held before this session existed (state 1a, or one of states 3/4 below if another session's watch is live, expired, or orphaned), followed by `             N session(s) ran the hook and never armed`, N &gt;= 1. | The full multi-line `watch` block, noting N. |
| 2 | Two fresh sessions, neither armed | Start a second fresh session and, in it too, do not run the Monitor command it prints; from either session, re-run the same grep | Same top line as 1b, with the pending count now 2. | The `watch` block, next to 1b's, so the count's difference is visible. |
| 3 | A session has armed the watch | Run the exact command the SessionStart hook printed: `bash harness/session_watch.sh <state_dir> --from-hook`, then re-run the `healthcheck.py` grep | `watch        armed by session <8-char session id> since <armed_at>, expires <expires_at>` (with `, last heartbeat <time>` appended once the watcher's first heartbeat lands) | The `watch` line, plus `cat state/sessions/<session-id>/watch.json`. |
| 4 | The last watch was retired, expired or killed without re-arming | Let the armed Monitor reach its 30-minute window (Claude Code retires it with a signal the watcher catches), or kill its process, without re-arming; then run the `healthcheck.py` grep | `watch        none armed: the last one (session <8-char session id>) ended at <ended_at> (the Monitor was retired) without re-arming` (the normal case), `expired at <expires_at> without re-arming` (a watcher alive past its expiry with no heartbeat), or `was killed (pid gone) without re-arming` (SIGKILL). Verified on 2026-09-18: the retirement landed at exactly `expires_at` and read `ended`. | The `watch` line. |
| 5 | `UserPromptSubmit` warns about mail nobody is watching | With state 4 provoked and new mail delivered since, send any prompt in that session | Injected turn context reading `paynani: N mail notification(s) arrived and no watch is showing them. Re-arm the watch now, before answering, with a Monitor running exactly:` followed by the `--from-hook` command and `It replays what is waiting first and then keeps watching.` | The injected context text for that turn (not the reply -- the context Claude Code shows was added to the prompt). |

Source for every line above: `scripts/healthcheck.py` (`render()`'s `watch`
block) and `harness/session_start.py` (`prompt_submit()`), not transcribed
from memory -- reread both before reusing this table on a future version.

## OpenAI Codex (`codex`)

Codex writes every event to `state/codex.spool` first (the durable, always-
safe path) and only then tries to wake a live session with the undocumented
`codex queue` command. `reachable`/`NOT REACHABLE` here means the spool
directory is writable, not that a session exists -- the same caveat as
Claude Code. `paynani doctor` declares `registered_session`,
`last_queue_attempt` and `last_queue_result` as observations for this
runtime, but none of them has a dedicated renderer in
`scripts/paynani_lib/diagnostics.py`'s `_observation_check()` today, so they
currently print as `unknown` regardless of real state -- `scripts/paynani
status` is where this runtime's live detail actually lives, and what every
step below uses instead.

Rows 1, 2 and 4 are provoked with a temporary `CODEX_HOME` or `PAYNANI_STATE`,
never by uninstalling hooks or deleting `state/codex.session` on a host that
is receiving real mail. Rows 3, 5 and 6 are read from the real, live state.

| # | State to provoke | Command | Exact expected output | Paste as evidence |
|---|---|---|---|---|
| 1 | Hooks not installed | `d=$(mktemp -d); env CODEX_HOME="$d" scripts/codex_hook.py --check` | Exit 1, with stdout containing `NOT registered in <path>/hooks.json` and no stderr. | The command output and exit code. |
| 2 | No session registered | Hooks installed, but no Codex TUI has started (or `SessionEnd` already ran and removed `state/codex.session`) | `scripts/paynani status` prints `Codex session: not registered` | That line. |
| 3 | A session is registered | Open a Codex TUI with the hooks installed, so `SessionStart` writes `state/codex.session` | `scripts/paynani status` prints `Codex session: registered` | That line, plus `cat state/codex.session`. |
| 4 | Mail lands in the spool, no live session to wake | `d=$(mktemp -d); printf 'imap:INBOX:1:1 email.received\n' > "$d/codex.spool"; env PAYNANI_STATE="$d" scripts/paynani status` | `Codex session: not registered`, `Codex spool: 0/30 bytes acknowledged` with the offset behind the total, and no `Last queue:` line. The `Codex queue contract` line is host-dependent (`supported` when the Codex binary is present, `unsupported (Codex binary not found)` when it is not). | The `Codex session`, `Codex spool`, and `Codex queue contract` lines together. |
| 5 | `codex queue` wakes a live, idle session | With a session registered (state 3) and mail delivered | `scripts/paynani status` shows a `Last queue: <event_id> at <timestamp>` line, and `Codex spool` shows `offset` caught up to `total` only once the queue call did not skip an older unread line | The `Last queue` and `Codex spool` lines, plus the Codex TUI actually showing the queued message. |
| 6 | The `codex queue` contract itself | Any time, with the Codex binary installed | `scripts/paynani status` prints `Codex queue contract: supported (--thread and --message are available)` (or `unsupported (Codex binary not found)` without one) | That line -- this is what proves the integration point in `harness/adapters/codex.py`'s own warning ("if a future Codex release changes it, this is the integration point to retest") hasn't silently broken. |

Source: `harness/adapters/codex.py` (`check()`, `queue_contract()`),
`scripts/healthcheck.py` (the `session_arming == "queue-or-replay"` branch
of `render()`), and `scripts/paynani_lib/status_cli.py` (the `Codex ...`
print lines) -- reread all three before reusing this table.

## OpenClaw (`openclaw`)

OpenClaw is a push runtime. Paynani calls `openclaw system event --mode now`;
that can prove the Gateway accepted the notification attempt, but not that a
session read it or answered. The extra OpenClaw-only state is the permanent
standing rule in `~/.openclaw/workspace/AGENTS.md`; without that rule, mail can
arrive, be accepted by OpenClaw, and still never be acted on by the agent.

**Before you start:** run this on the real OpenClaw host, from the paynani clone
that the services use. Do not edit `AGENTS.md` to provoke a failure. The missing
rule case is covered by `scripts/openclaw_rules.py --check`; the field test on a
healthy host should leave the rule in place.

| # | State to provoke | Command | Exact expected output | Paste as evidence |
|---|---|---|---|---|
| 1 | OpenClaw is the selected runtime and the CLI is reachable from the service environment | `scripts/healthcheck.py \| sed -n '1,7p'` | `runtime      openclaw` followed by `configured by <repo>/runtime.env`, `reachable: OpenClaw <version>`, `this proves the runtime answers, not that a delivered event reaches anyone`, and `instructions standing rule in place in ~/.openclaw/workspace/AGENTS.md` | The first seven `healthcheck.py` lines. |
| 2 | The standing rule exists in the actual OpenClaw workspace | `scripts/openclaw_rules.py --check` | `standing rule in place in <path-to-AGENTS.md>` and exit 0 | The command output and exit code if the shell prints it. |
| 3 | A synthetic OpenClaw route probe is accepted without touching IMAP or the mail journal | `scripts/paynani openclaw probe --dry-run` | `openclaw_probe=accepted namespace=probe:<uuid> state=<repo>/state/openclaw.probe.json` | That line, plus `cat state/openclaw.probe.json`. |
| 4 | `healthcheck.py` reports the latest synthetic probe separately from real mail | `scripts/healthcheck.py \| grep -A1 '^openclaw probe'` | `openclaw probe accepted at <time> (probe:<uuid>)` followed by `             openclaw system event accepted the synthetic probe` | The two `openclaw probe` lines. |
| 5 | A real roster mail event was accepted by OpenClaw | After a roster GitHub notification or roster email arrives, copy the event id from the wake line and run `scripts/paynani event show <event-id>` and `scripts/healthcheck.py \| grep -A1 '^dispatcher'` | The event JSON has `"roster_match": true` and lifecycle states `observed` then `dispatched`; `healthcheck.py` prints `dispatcher   active` followed by `last accepted <event-id> by openclaw at <time>` | The event JSON block around `roster_match` and `lifecycle`, plus the two dispatcher lines. |
| 6 | A reply was sent when the roster task required a reply | After acting on the mail, run `tail -1 state/sent.log` | A tab-separated line with `to=<roster address>`, optional `cc=<Julian address>`, `subject=<subject>`, and `message-id=<id>` | The `sent.log` line. If the task was a GitHub review or comment rather than an email reply, paste the GitHub URL and say why no `sent.log` line was expected. |

Source for the OpenClaw lines above: `scripts/healthcheck.py`
(`runtime`, `instructions`, `openclaw probe`, and `dispatcher` rows),
`scripts/paynani_lib/openclaw_cli.py` (`openclaw_probe=accepted`), and
`scripts/openclaw_rules.py --check`.

## Hermes Agent (`hermes`)

Hermes has no session and no spool either: delivery is an HTTP POST to one
of three operator-configured routes (health, notify, roster), described in
[`HERMES.md`](HERMES.md). `reachable`/`NOT REACHABLE` here comes from a GET
to `HERMES_HEALTH_URL` alone (`harness/adapters/hermes.py`'s `check()`); it
says nothing about the notify or roster routes. `paynani doctor` declares
`notify_route_configured` and `roster_route_configured` as observations for
this runtime, but like Codex's queue observations, neither has a dedicated
renderer yet, so both print `unknown` regardless of real state today --
provoke and read the routes directly, as below, rather than trusting
`doctor` for them.

| # | State to provoke | Command | Exact expected output | Paste as evidence |
|---|---|---|---|---|
| 1 | Health route reachable | `HERMES_HEALTH_URL` configured and answering | `scripts/healthcheck.py` prints `reachable: Hermes webhook server answers GET /health; this is reachability, not route readiness or agent completion` | That line. |
| 2 | Health route unreachable | Point `HERMES_HEALTH_URL` at a closed port or wrong host, then run the check | `scripts/healthcheck.py` prints `NOT REACHABLE: Hermes health endpoint is unreachable or timed out: <error>` | That line, then revert the URL. |
| 3 | Notify route delivers directly | Send real roster mail with the notify route configured correctly | The adapter's `_classify()` returns `accepted`, detail `Hermes completed direct delivery (HTTP 200)`; `scripts/healthcheck.py`'s `delivery` block shows `runtime said: Hermes completed direct delivery (HTTP 200)` | The `delivery` block. |
| 4 | Roster route queues an agent run, unconfirmed | Send real roster mail with the roster route configured correctly | Detail `Hermes queued the agent run (HTTP 202); completion is unconfirmed`; same `delivery` block shows that text | The `delivery` block, plus whatever the agent did afterward (or didn't) as the actual confirmation this line admits it cannot give. |
| 5 | Route URL and secret swapped | Configure the notify secret on the roster route or vice versa, then send mail | Detail `Hermes answered for route '<other>', not configured route '<expected>'. Check the route URL and secret pairing.` | The `delivery` block. |

Source: `harness/adapters/hermes.py` (`check()`, `_health()`,
`_classify()`) and [`HERMES.md`](HERMES.md) -- reread both before reusing
this table; the exact HTTP status/route-class combinations in `_classify()`
are more numerous than the five rows above, which cover the ones a real
mail send actually exercises.

## OpenCode (`opencode`)

The five states below are [#160](https://github.com/iaaorgmx/paynani/issues/160)'s
acceptance criteria, moved here rather than rewritten: they were already a
reproducible checklist, and re-deriving them from the code a second time
would only risk disagreeing with the version that shipped.

| # | State to provoke | Command | Exact expected output | Paste as evidence |
|---|---|---|---|---|
| 1 | OpenCode closed | No OpenCode process open, with the plugin installed (`scripts/opencode_plugin.py --install`) | `scripts/healthcheck.py` prints `no OpenCode process is open; unread bytes wait until OpenCode is open, which is normal` | That line. |
| 2 | OpenCode open, no message sent yet | Open the OpenCode TUI and do not write anything in it | `scripts/healthcheck.py` prints `OpenCode is open (process <pid>) but not delivering yet: write in a session and delivery starts when it is idle`; `ls state/opencode.processes/` shows `<pid>` | Both. |
| 3 | Delivering | Write in the open session and let it go idle | `scripts/healthcheck.py` prints `delivering from OpenCode process <pid>` | That line. |
| 4 | Closed again | Close OpenCode | `state/opencode.processes/` is empty; `scripts/healthcheck.py` prints state 1's line again | Both. |
| 5 | Headless `opencode run`, TUI closed | `opencode run "hola"` with no TUI open | `state/opencode.processes/` stays empty throughout (a one-shot `opencode run` never registers, by design -- `shouldRun()` in `harness/opencode/paynani.js`) | The empty `ls`, captured during the run. |

Source: `scripts/healthcheck.py` (`spool_facts()`, `opencode_plugin_facts()`)
and `harness/opencode/paynani.js` (`PaynaniPlugin`, `shouldRun()`) -- reread
both before reusing this table, and see #160 itself for how this checklist
was first run, on Balam's host, in OpenCode 1.18.31.
