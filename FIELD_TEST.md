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
`watch` row from unobservable into five distinguishable states.

**Before you start:** confirm this install is past #170. A session that
started on an older clone still gets mail (the SessionStart hook still
prints something to arm), but on the pre-#170 form the hook prints a byte
offset to arm with, not `--from-hook`, and that form never writes a
registry entry -- so `watch` reports "no session has armed a watch" even
while that session is actively receiving mail. That is not a bug to chase;
it is the sixth thing to rule out if step 1 or 3 below doesn't match.

**The pending line is baseline, not a state you provoke in isolation.**
`write_registry()` runs unconditionally at every SessionStart, before the
agent can run anything -- so the instant a fresh session can call
`healthcheck.py`, its own registry already reads `pending`, and the count in
step 1 below is never zero. Step 1 and step 2 both show this line; step 2
is there to prove the count is a real tally and not a fixed sentence, by
making it grow.

| # | State to provoke | Command | Exact expected output | Paste as evidence |
|---|---|---|---|---|
| 1 | A fresh session, before it arms: its own not-yet-armed entry, on top of whatever else already held | Start a fresh Claude Code session on this install; before running the Monitor command the SessionStart hook prints, run: `scripts/healthcheck.py \| grep -A2 '^watch'` | The top `watch` line that already held before this session existed (`no session has armed a watch...` on a clean install, or one of states 3/4 below if another session's watch is live, expired, or orphaned), followed by `             N session(s) ran the hook and never armed`, N &gt;= 1. | The full multi-line `watch` block, noting N. |
| 2 | A second, independent session also pending | Start a second fresh session on the same install and, in it too, do not run the Monitor command it prints; from either session, re-run the same grep | Same top line as step 1, with the pending count one higher than what step 1 showed. | The `watch` block again, next to step 1's, so the count's difference is visible. |
| 3 | A session has armed the watch | Run the exact command the SessionStart hook printed: `bash harness/session_watch.sh <state_dir> --from-hook`, then re-run the `healthcheck.py` grep | `watch        armed by session <8-char session id> since <armed_at>, expires <expires_at>` (with `, last heartbeat <time>` appended once the watcher's first heartbeat lands) | The `watch` line, plus `cat state/sessions/<session-id>/watch.json`. |
| 4 | The last watch expired or was killed without re-arming | Let the armed Monitor's window lapse (or kill its process) without re-arming, then run the `healthcheck.py` grep | `watch        none armed: the last one (session <8-char session id>) expired at <expires_at> without re-arming` (or `was killed (pid gone) without re-arming` if the process died instead) | The `watch` line. |
| 5 | `UserPromptSubmit` warns about mail nobody is watching | With state 4 provoked and new mail delivered since, send any prompt in that session | Injected turn context reading `paynani: N mail notification(s) arrived and no watch is showing them. Re-arm the watch now, before answering, with a Monitor running exactly:` followed by the `--from-hook` command and `It replays what is waiting first and then keeps watching.` | The injected context text for that turn (not the reply -- the context Claude Code shows was added to the prompt). |

Source for every line above: `scripts/healthcheck.py` (`render()`'s `watch`
block) and `harness/session_start.py` (`prompt_submit()`), not transcribed
from memory -- reread both before reusing this table on a future version.

## Other runtimes

Codex, OpenClaw, Hermes Agent and OpenCode are next, one section each, same
skeleton, in a follow-up PR (#173): Ocelotl validates Codex, Xochitl
OpenClaw, Atenea Hermes Agent, and Balam OpenCode, each on their own host.
OpenCode's five states already have a version of this table in
[#160](https://github.com/iaaorgmx/paynani/issues/160)'s acceptance
criteria; that PR moves it here rather than rewriting it.
