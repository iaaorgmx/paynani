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

## Other runtimes

Codex, Hermes Agent and OpenCode are next, one section each, same skeleton, in
a follow-up PR (#173): Ocelotl validates Codex, Atenea Hermes Agent, and Balam
OpenCode, each on their own host. OpenCode's five states already have a
version of this table in [#160](https://github.com/iaaorgmx/paynani/issues/160)'s
acceptance criteria; that PR moves it here rather than rewriting it.

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
