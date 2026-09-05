# Why paynani is shaped this way

Read this before changing anything. Most of what follows looks like style and is
not; each item is a failure that happened, was diagnosed, and is now prevented by
a specific line of code. Removing the line brings the failure back.

---

## The one property everything serves

**Never silently fail.**

Latency was the easy problem. IMAP `IDLE` solved it in an afternoon: the server
pushes, we hear about mail in about a second, and there is no polling interval to
tune.

Every other decision in this repository exists because the expensive failure is not
being slow. It is **confidently reporting no new mail while blind.** A tool that is
occasionally late is annoying. A tool that is silently deaf while its user believes
it is listening is worse than no tool, because it has replaced their vigilance with
a false guarantee.

When you weigh a change, weigh it against that. Anything that makes a failure
quieter is a regression, even if it makes the code shorter.

---

## Why there are three parts and not one

Two facts collide:

1. IMAP can push. `IDLE` (RFC 2177) holds a connection open and the server reports
   new mail immediately.
2. **A background process cannot speak into an agent session.** It has no handle on
   that context. Only something the harness runs can put words in front of the
   agent.

So: a long-lived listener that can hear but not speak, a harness-side dispatcher
that can speak, and a journal joining them.

**The journal is the contract between the two halves.** The listener appends one
canonical envelope per line to `events.jsonl` and never delivers anything. The
dispatcher reads that file from a byte offset, hands each record to a runtime
adapter, and advances the cursor **only once the adapter reports the runtime took
it**. Neither half knows anything about the other, which is what makes a second
harness an adapter rather than a fork.

**A record is structure, not prose.** Before the journal, delivering to another
harness meant parsing a line written for a person to read. The envelope carries
the sender, subject, mailbox, account, UID and roster result as fields, plus the
rendered line for the runtime whose delivery call takes exactly one string.

**Nothing is consumed by being read**, and that is the whole reason the journal
exists rather than a tail of the log. The old watcher read through `tail -F`, so
a line it had taken was gone from the pipe whether or not it had been delivered;
retrying meant holding it in memory, and recovering from a sustained failure
meant killing the process so a supervisor could restart it from a stored offset.
Reading a file by offset removes every part of that. A record that cannot be
delivered is simply retried, forever if need be, while the cursor stays where it
is.

**One dispatcher, enforced rather than assumed.** It takes an exclusive lock at
startup. The unit is meant to be the only one, but "meant to" is not a mechanism:
a copy run by hand for debugging is enough to deliver every event twice, and the
duplicate looks like nothing at all from outside.

**The journal has a lock too, and it exists for compaction.** Appending needs no
lock against another append; it is one `O_APPEND` write. Compaction reads the
size, decides, and truncates, so without a shared lock an append landing between
the decision and the truncation is destroyed after being counted as delivered.
Compaction therefore runs in the dispatcher, the only process that knows what has
been delivered, rather than in the log rotator, which is a different process on a
timer that knows neither.

**A record is durable before it is acknowledged.** The listener persists its
last-seen UID after appending, and that UID is the only thing deciding whether a
message is ever fetched again. If it reaches the disk and the record does not,
the message is gone. So the append writes every byte, `fsync`s, and only then
returns the offset that lets the UID move.

**So a stuck record holds the queue, loudly, instead of being stepped over.**
There is no dead-letter policy: a byte offset cannot describe a hole, and a
skipped record nobody counted is precisely the silent loss this project exists to
prevent. The dispatcher says what is wrong on stderr, the session hook reports it
at the start of the next session, and mail keeps accumulating in a journal that
loses nothing.

**A damaged record stops everything behind it.** A complete line that will not
parse is not skipped: skipping it advanced the cursor past it the moment anything
behind it was accepted, which is a dead-letter policy nobody chose. It stops the
queue and says so, and a person decides.

**Delivery is at least once.** A runtime may be handed the same event twice: the
dispatcher can be stopped between a runtime accepting an event and the cursor
being written, and a mailbox rebuilt on the server changes UIDVALIDITY, which
changes every event ID. Both produce duplicates rather than losses. `event_id` is
stable across restarts precisely so a consumer can recognise one.

**`roster_match` is not identity.** It is an exact match against a
human-maintained allowlist, compared against a `From` header that anyone can
forge. It decides routing and nothing else. The envelope carries
`authenticated_sender` separately, and it stays false until something actually
validates provider authentication results. No consumer may present the first as
the second.

**The listener is only a doorbell.** It reports *that* mail arrived and from whom,
and never fetches bodies. Reading and sending belong to Himalaya. A bug in one
cannot take down the other, and the listener stays small enough to reason about.

---

## The five decisions inside the listener

### 1. Check for new mail after every IDLE cycle, not only when IDLE reported a change

Between sending `DONE` and re-entering `IDLE` there is a window in which the server
has no open connection to push to. A message landing there generates no `EXISTS`
that will ever be seen, and it sits unreported until the *next* message arrives,
which can be hours later, or never.

The fix is to run `fetch_since()` unconditionally after each cycle. It costs one
cheap `UID SEARCH` per 25 minutes and closes a hole that is otherwise invisible.

### 2. Persist the UID after each message, not after each batch

Crash halfway through a five-message catch-up and a per-batch save replays all
five. Per-message persistence with an atomic write-then-rename means a crash can
lose at most the message currently being processed, and never duplicates one
already reported.

### 3. Handle UIDVALIDITY

UIDs are only comparable within one `UIDVALIDITY` epoch. If a mailbox is deleted
and recreated, the server restarts numbering, and a stored `last_uid` of 400 will
suppress the next 400 messages. Silently.

It is compared on every connect. If it moved, the stored position is discarded and
the listener rebaselines. The one-time flood of "catching up" that follows is the
correct behaviour, not a bug.

### 4. Fail hard on bad credentials, retry on everything else

A wrong password never becomes right. Retrying it hammers the server until it rate
limits you, and buries the real error under a wall of reconnect noise. So a login
rejection exits 1 and stays exited.

Network errors are the opposite: always transient, always worth retrying, with
exponential backoff between 5 and 300 seconds.

**One consequence to know about:** a TLS certificate hostname mismatch arrives as a
connection error, not an auth error, so it lands in the retry path and the listener
will back off forever without saying anything useful. If a connection never
establishes and the log only shows `connection lost`, check the certificate.

### 5. stdout is the event stream; stderr is diagnostics

They go to different files, and the split is load-bearing in both directions. Every
stray `print()` to stdout becomes a notification in front of a human. Every
diagnostic that goes to stdout instead of stderr does the same.

---

## Header handling, and the bugs that hid there

Found on 2026-08-09 by an end-to-end test with three deliberately different
messages. Both had been live since the code was written, and both were invisible to
a single plain-ASCII test.

**RFC 5322 folds long subjects** onto continuation lines that begin with
whitespace, so what arrives is `...extremo\r\n\t (Issue #2)`. Replacing only `"\n"`
leaves the carriage return and the tab embedded mid-subject. `decode_hdr()` now
collapses every run of whitespace: `re.sub(r"\s+", " ", text).strip()`.

**The GitHub subject parser's ref group never matched.** It expected a bare `(#9)`.
GitHub writes `(Issue #9)` and `(PR #14)`. The capture always returned `None`, so
the branch consuming it was dead code, for a week, in front of someone reading
those notifications daily.

The lesson generalises: **test with the messages you will actually receive**, not
the simplest one that proves the pipe works. Accented subjects, folded subjects,
and real notification formats each exercise a different path, and the plain-ASCII
test passes regardless of whether any of them work.

---

## Lines in the shell that look optional and are not

**`tail -F`, never `-f`.** `-F` re-opens the file by name, so the tail survives log
rotation. `-f` follows the inode and goes permanently deaf the moment rotation
runs, with no error, no exit, and no notifications. This is the "everything worked
for a week and then stopped" failure.

**`grep --line-buffered` and `sed -u`.** Without them each stage buffers 4 KB, and
notifications arrive in batches hours late. **Never put `head` in this pipe.** It
cannot flush at all.

**The second tail, on the error log, is not optional.** If only the success path is
watched, a dead listener produces silence, and silence is indistinguishable from a
quiet mailbox. This is the single worst failure mode available here, because the
agent will confidently report no new mail while blind. That is the exact scenario
the whole design exists to prevent, and one `grep` on stderr is what prevents it.

**A failed injection must not become a failed dispatcher, and must not become a
delivered event either.** Both were tried and both were wrong. Swallowing the
failure kept the process alive and acknowledged mail that never arrived; refusing
to acknowledge it but carrying on left a cursor that could never move again. The
adapter now reports which of the three things happened, and the dispatcher retries
in place without ever stepping past the record.

**`send.sh` writes a full header block, not the three headers it needs.** This is
two failures deep, and the second only appeared once the first was fixed.

Himalaya v1 filled in `From:` from account config; v2 refuses the message outright,
with *"No `From:` header found in raw message"*. The address is read from the same env
file the listener reads, under the same two key schemas, so an install cannot end
up with the listener and the sender disagreeing about which account this is.

Adding `From:` got the message past Himalaya and not past Gmail, which accepted it
over SMTP and then bounced it: *"554 5.7.1 Rejected due to high probability of
spam"*. `Date`, `Message-ID`, `MIME-Version`, `Content-Type` and
`Content-Transfer-Encoding` are what every ordinary client sends, and a message
without them reads as bulk machinery. **Do not trim that list back to the headers
that look required**: the message that got rejected was the short one.

Header values are then RFC 2047 encoded when they are not plain ASCII. Raw UTF-8 in
a header depends on an extension the receiving server has to advertise, and this
project is Spanish-first: an accented subject is the common case, not the edge one.
Note that an encoded-word must **not** be wrapped in quotes; inside a quoted
string it stays literal instead of decoding, which is why the display name is
quoted only when it is ASCII.

**`send.sh` strips CR and LF from the recipient and subject.** Both are composed
from mail the agent was asked to act on, and a newline inside a header value ends
that header and begins another; a crafted subject could append `Bcc:` and reach
an address the roster never approved. The allowlist checks the recipient it was
given; it cannot see a second one smuggled into a header.

**Rotation uses `copytruncate`.** systemd holds the log open in append mode. A
rename-style rotate moves the file out from under the open descriptor, and every
line written afterwards goes to a file nobody reads. Silently.

---

## Why the dispatcher pushes instead of being read

The first version of this design assumed the harness would consume a script's
stdout as an event stream, the way Claude Code's Monitor tool does.

**OpenClaw has no such primitive.** There is no `--stream-command` in its cron.
That search has been done; it is a dead end.

The inverse works: `dispatch.py` is an **active producer**. It injects each
OpenClaw mail event as a live notification with `openclaw system event --mode
now`; roster mail carries the `roster` tag in that rendered line, but the
OpenClaw adapter does not start an agent run from incoming mail. If you port
this to another harness, that runtime delivery boundary is the part to inspect
first; the rest is harness-independent.

### The four runtimes, and where each stops being ours

That delivery boundary is worth stating for all four, because it is the same
question answered four different ways.

`dispatch.py` moves its cursor only when an adapter reports `ACCEPTED`. What
`ACCEPTED` means is the adapter's judgement, and it is never *"a person read
it"* — no runtime can tell us that. Each one draws the line somewhere earlier:

| Runtime | Delivery | `ACCEPTED` means | What it does not prove |
|---|---|---|---|
| OpenClaw | `openclaw system event --mode now` | the event is enqueued on the main session | that the heartbeat injected it, or that the session survived to run one |
| Hermes | authenticated HTTP route | `200 status=delivered` on the notify route; `202 status=accepted` on the roster route | for `202`, that the queued agent run ever completed |
| Claude Code | append to `state/session.spool` | the bytes are on disk | that any session ever read them — a file write cannot fail informatively |
| OpenAI Codex | append to `state/codex.spool`, then `codex queue` to the registered thread | the event is either queued into a live Codex session or durably spooled for replay | that the agent completed the requested mail work |

Read down the last column and the shape is one thing: **every runtime has a point
past which this project cannot see, and the runtimes differ only in how early it
comes.** Claude Code's is the earliest, which is why it needs session-start
replay. Codex keeps the same replay backstop, but now moves the live boundary to
`codex queue` when a session has registered its thread. Hermes is explicit about
it in its own contract, which is why `HERMES.md` documents `202` as
*"completion is unconfirmed"* rather than as success. OpenClaw's looks the
latest and is not
([#108](https://github.com/julianflores/agenteiamail/issues/108)).

The honest way to describe the guarantee, then, is not *"mail reaches the agent"*.
It is **mail is never lost before the runtime takes it, and the moment it is
taken is recorded.** Everything after that belongs to the runtime, and the value
of naming the boundary per runtime is that nobody has to guess which half a
failure fell in.

### Looking past the boundary without pretending to see across it

Naming the boundary is not the same as being able to say which side a failure
fell on, and for a long time nothing could. A live OpenClaw host took three
roster messages in one afternoon and answered none of them; the listener was
active, the dispatcher was active, `ACCEPTED` was recorded three times, and every
check this project offered said so
([#125](https://github.com/julianflores/agenteiamail/issues/125)).

`scripts/healthcheck.py` now compares two records this project already keeps —
roster mail the dispatcher has delivered, and sends recorded in `state/sent.log`
since [#117](https://github.com/julianflores/agenteiamail/issues/117) — and says
when roster mail has been delivered and nothing has gone out after it. It is a
**warning and never a failure**, for the reason this whole section exists: what
happens after a runtime accepts is not ours, and two very different things
produce the same shape. Either the agent was told and did not reply — the
standing rule in `AGENTS.md` never reaching its own persistent instructions — or
nothing was attached to be told, which is
[#108](https://github.com/julianflores/agenteiamail/issues/108).

This command cannot tell those apart and does not try. It reports the shape and
names both readings, which is enough to send a person to the right place, and is
the most that can be claimed from this side of the line.

### Supervision inverts on macOS, the way delivery inverts on Claude Code

Everything above assumes a supervisor that starts services at boot and restarts
them on crash, and until v1.9.0 that assumption was spelled `systemd --user`
throughout.

macOS has no systemd. It has launchd, and the substitution is not one-for-one in
a way that matters:

- A **LaunchAgent** in `~/Library/LaunchAgents` runs as the user, which is what a
  mailbox with a mode `600` credentials file requires — and is tied to a login
  session.
- A **LaunchDaemon** survives logout and runs as root, which is wrong for a
  personal mailbox.
- There is **no `enable-linger` equivalent** that gives both.

So on Linux *"survives logout"* and *"runs unprivileged as the mailbox's owner"*
are one configuration, and on macOS they are two, and you must choose.

This project chooses the LaunchAgent, and the reason is not a preference about
availability. **The credentials file is the constraint.** A supervisor running as
root reading a mode `600` file owned by someone else is either a permissions
problem or a `chmod` nobody should make, and the second is how a mail password
stops being a secret.

The consequence is that a macOS host does not return from a cold boot
unattended. That sounds like a loss against Linux and is not, on the hosts this
project actually runs on: a WSL host's `enable-linger` survives a logout inside
the Linux session, but the whole session is down until Windows starts it. **On
every host supported today, the listener's availability follows the user
session.** A native Linux host would be the exception and none exists yet.

`scripts/install_macos.py` renders and converges the plists that `install.sh`
renders and converges for units, and the one thing worth knowing about it is
negative: the generated plists carry a deliberate `PATH` rather than a copy of
whatever the installing shell had. A supervisor definition holding a photograph
of the session that produced it works for months and then does not.


---

## Why some runtimes pull

Claude Code and OpenAI Codex are exceptions to the section above, and it is worth
understanding before changing anything in their adapters, `session_watch.sh`, or
the pull-runtime branch of `session_start.py`.

**Nothing outside a Claude Code session can speak into it.** There is no
`claude system event`. `claude -p --resume` starts a fresh headless turn and
never appears on the screen of the session a person is sitting in front of. The
active-producer trick that works for OpenClaw has nothing to call.

So on this runtime delivery inverts. The dispatcher writes the rendered line to
`state/session.spool` and stops there; the session comes and gets it, through two
readers that both index the file by byte offset:

- the **session-start hook**, which replays what arrived while nothing was running;
- an armed **Monitor**, which reports each new line as it lands.

The offset is what makes two readers safe: the hook replays through byte *N* and
asks for the watch to be armed **at** *N*, so nothing falls in the gap between the
hook finishing and the monitor attaching, and nothing is shown twice.

### What the push runtimes use instead

The obvious question is why OpenClaw and Hermes need no equivalent, and the
answer is that they already have one: **the queue is their catch-up.**

`dispatch.py` moves the cursor only once a runtime has accepted an event, and
`adapters/openclaw.py` treats a failed injection as retryable rather than fatal —
its own words are that *"openclaw restarting, or a session not yet up, is a
condition that clears on its own."* So on a push runtime, mail arriving with
nothing running is not delivered, the cursor does not advance, and the dispatcher
keeps trying until it lands. Nothing needs replaying because nothing was
consumed.

Claude Code cannot borrow that, because its delivery always succeeds. Appending
to a spool is a write to a file, so the adapter returns `ACCEPTED` and the cursor
moves whether or not any session ever reads the line — *spooled means durable,
not seen*. The queue stops being a backstop the moment delivery cannot fail, and
the hook is what replaces it.

**Session catch-up is therefore a pull-runtime mechanism by necessity, not a
feature the push runtimes are missing.** `harness/session_start.py` exists for
Claude Code and OpenAI Codex; on OpenClaw and Hermes, nothing invokes it and
nothing should. It is worth saying plainly because the reverse was implied for
two releases, and it cost an investigation.

### Why Codex queues first and still keeps replay

Codex CLI 0.153.4 has a `codex queue --thread <THREAD> --message <TEXT>`
command. It is not documented in the public OpenAI documentation as of this
implementation, so paynani treats it as a measured dependency rather than a
published contract: the behavior is covered by tests and called out in
`INSTALL.md`.

The live path is now the primary one. Codex's `SessionStart` hook receives a
documented `session_id` in its stdin payload, and `harness/session_start.py`
writes that id to `state/codex.session`. The dispatcher writes the rendered
notification line to `state/codex.spool`, then the Codex adapter runs:

```bash
codex queue --thread "$(cat state/codex.session)" --message "Procesa el evento paynani <event_id> del journal..."
```

Only the event id is queued. The body of the mail is never put into the queued
message, because Codex receives that text as user input and the mail body is not
trusted until the agent fetches the event from the journal and verifies the
roster decision.

The spool stays because a live session is optional. If `codex queue` succeeds,
`state/codex.offset` advances through the line that was just queued, so the next
SessionStart replay will not show it again. If there is no active session, the
event remains spooled and either waits for the next SessionStart replay or, when
`PAYNANI_CODEX_MODE=agent` is set, starts a headless `codex exec` run. That mode
is off by default for the same reason as Claude Code's agent mode: it widens
what inbound roster mail can cause on the machine.

Queue failures are classified by stderr, not only by exit code. Exit `0` means
queued and accepted. Exit `2` is configuration. Exit `1` with `No active session
found` is a normal fallback path, not a fault. Exit `1` with `attempt to write a
readonly database` means the command ran inside Codex's sandbox and is
configuration, because the dispatcher service is supposed to run outside that
sandbox.

### Where that guarantee stops

The paragraph above rests on a failed injection being visible to the dispatcher,
and it has a boundary that is worth naming precisely, because it was confirmed
rather than assumed.

`openclaw system event --mode now` **accepts an event with no session attached to
see it.** OpenClaw enqueues it into the main session and surfaces it on the next
heartbeat; a probe on a live host returns `{"ok":true}` either way. So acceptance
happens at OpenClaw's session-queue layer, not at the point anything reads it.

This project's backstop therefore ends the instant OpenClaw says `ok`. From then
on the event is held by OpenClaw's queue rather than by `events.jsonl`, and
`dispatch.offset` has already advanced. `ok` is the strongest signal the adapter
can obtain, so this is invisible from here by construction.

**The queue is the catch-up up to the point of acceptance, and no further.** That
is still a materially stronger position than Claude Code's, where delivery is a
file write that cannot fail — but it is not the unconditional claim it would be
easy to read the previous section as making.

What happens to a queued event if OpenClaw restarts before the heartbeat delivers
it is
[#108](https://github.com/julianflores/agenteiamail/issues/108), and unanswered.

### The spool is not named `*.log`, and that is load-bearing

`rotate_logs.py` rotates every `*.log` in the state directory. Rotation renumbers
bytes. Pull-runtime readers index spools by offset, so a rotation landing between
a replay and an acknowledgement resumes at the wrong place: mail shown twice, or
mail stepped over that nobody ever saw. The second is indistinguishable from a
quiet mailbox, which is the failure this whole repository exists to prevent.

The cost is a file that grows without bound. That is accepted, because it grows
by one line per message, and the alternative is a rotation scheme that would have
to move two independent readers' cursors atomically.

### One record is exactly one line

A rendered notification can carry a line break — a folded subject is the usual
source. Letting it through makes a pull-runtime reader report one message as two
and leaves every later offset a line out of step with the file it indexes into.
The adapters flatten line breaks before appending; `scripts/test_claudecode.py`
and `scripts/test_codex.py` pin it.

### Why the watch takes a lock, when the other runtimes forbid one outright

`session_start.py` says, for every other runtime, that it deliberately does not
start a watcher: *a session that armed its own copy made two consumers of one
stream racing on one cursor file, which duplicated events and corrupted the
record of what had been seen.* That is a scar, not a preference.

Claude Code cannot obey that rule, because a session that does not arm a watcher
receives nothing at all. So the rule is not dropped — the guard moves. The
dispatcher writes the spool and never reads it, which leaves exactly one
consumer, and `session_watch.sh` takes an exclusive `flock` so a second session
refuses to arm rather than quietly halving the accuracy of both. Two sessions on
one host is precisely the original bug; the lock is what keeps it from coming
back by a different route.

### Arming is the acknowledgement, and the hook must not perform it

The hook reports the offset it replayed through; the **watch** writes it, when it
is actually armed. The hook advancing it would be claiming an arming it cannot
observe, and an agent that read the replay and never armed would lose that mail
silently.

The failure mode this chooses is repetition. An agent that ignores the arming
instruction sees the same messages again next session. That is annoying and
visible, which is the right trade against skipping, which is neither.

The same reasoning runs the other way for a spool shorter than the recorded
offset: it was truncated or replaced, so the offset is meaningless and reading
resumes from zero. Replaying is survivable; stepping over everything now in the
file is not.

---

## Why the install lives inside the clone

An install could reasonably be spread over three directories: credentials and
secrets in `~/.config`, queue state and logs in `~/.local/state`, the roster in
the clone. Nothing is wrong with any one of them. What is wrong is that "where
is this install?" then has three answers, so backing it up, inspecting it, or
removing it means remembering all three.

It is one directory, and that directory is the clone. That answers "install
it wherever you want" without a flag: you clone where you want, and the install
is there. Nothing has to be told where anything is, because every consumer lives
inside the clone and can find itself from `__file__`.

**Credentials at a harness path with everything else in the clone is the
ordinary arrangement**, not a split install: the harness owns that file, this
project owns the clone, and neither is half of the other. A credentials file
says where credentials are. It says nothing about whether there is an install —
which is why nothing outside the clone is ever adopted as evidence of one.

Twice in this project's history a comment asserted a guarantee the code did not
implement: one claimed power-loss durability over a single fsynced temporary
file, another claimed a `|| true` service stop was what protected a move.
**A comment stating a property nothing enforces is worse than no comment**,
because it stops the next reader from checking.

**Any exit after a service has been stopped owes the operator their services
back.** That is a trap rather than a call at each exit, because the paths that
needed it were the ones nobody remembered to write: a rollback three functions
deep used to leave the listener and the dispatcher stopped while printing that
the install was unchanged. The files were unchanged. The mail had stopped. The
set to restore is recorded before the first stop and written into the
transaction, so a unit the operator had deliberately stopped stays stopped, and
so a resume in a different process still knows what to put back. A restore that
fails is reported, names the unit, keeps the transaction for a retry, and exits
nonzero — it is never folded into a success.

**The cost of this layout is that secrets live in a git working tree.** Three
things hold that line: anchored `.gitignore` rules, a fail-closed check in the
installer that refuses to write when a runtime-owned path is tracked or
unignored, and assertions in `scripts/test_paths.sh` so a rule cannot be dropped
without CI noticing. One thing does not: **`git clean -xdf` deletes ignored
files**, and on a live install that is the mailbox password, both route secrets,
the roster and the UID baseline, in one command. That is documented rather than
prevented, because the alternative — leaving them untracked but unignored — trades
a destructive command for a `git add -A` that publishes the password, and that is
the worse failure.

The units are the one thing still outside, in `~/.config/systemd/user`, because
systemd will not read them from anywhere else. They carry absolute paths rendered
by the installer rather than `%h`, since `%h` cannot express "wherever the clone
is".

### What a complete assertion looks like

A suite can assert artifacts — files in the right place, resolver agreeing,
modes correct — and never ask whether mail is still being detected afterwards.
That is how the same defect keeps arriving in a new costume: an operation that
leaves the services stopped passes every assertion in the suite.

So, for any path that stops or starts a service: **an assertion about that path
which does not cover the resulting service state is not a complete assertion.**
The mocked suite must say what it expects both units to be doing at the end,
including the cases where one of them was already stopped and the case where the
restore itself fails.

And the honest limit, because overclaiming here is the same mistake in a
different place: `is-active` and start-call assertions establish **service
state**, not **mail detection**. A running listener is not proof that mail is
arriving. Proving detection needs a real host, real IMAP, and a message actually
arriving — which is why releasing an install onto a live mailbox has its own gate
and is not something the suite can grant.

## Why the roster is the whole model

This agent reads untrusted content all day (emails, web pages, documents) and it
holds send credentials. Email is therefore both the thing the agent is *for* and
the most obvious way to talk it into something. The design does not resolve that by
refusing to take instructions from mail, because taking instructions from mail is
the product. It resolves it by making one list, written only by a human, decide
which mail counts.

`roster.md` answers a single question, *did my human vouch for this person*, and
that one answer drives everything:

| | on `roster.md` | everyone else |
|---|---|---|
| Reported to the agent | yes | yes |
| Tagged `roster` in the notification | yes | no |
| Body treated as instructions | yes | no |
| May be replied to | yes | no |
| May be sent to by `send.sh` | yes | no, exit 2 |

An earlier version of this file argued that message bodies are data and never
commands. That rule was coherent, and it was wrong for what this tool is: it
described an agent that watches a mailbox rather than one that works from it. What
was actually load-bearing in it survives below.

**Matching is exact.** `grep -qixF` in `send.sh`, whole-string comparison in
`scripts/roster.py`. A substring match would let `evil-human@example.com` through
on the strength of `human@example.com` appearing inside it. The two
implementations are tested separately (`test_roster.sh`, `test_listener.py`)
because a divergence between them is silent and means the agent answers someone
`send.sh` would have refused.

**`From` decides, never `Reply-To`.** `Reply-To` is set by whoever sent the
message. Honouring it would let a stranger borrow a listed identity by writing one
header, the exact hole the roster exists to close.

**Adding an entry is a human decision.** This is the rule the loosening leans on
hardest. One line in that file promotes an address from "reported" to "obeyed", so
an entry added because a message asked for it hands that message everything. The
file is untracked for the same reason: a `git pull` must not be able to change who
the agent works for.

**Absence fails closed.** No roster file means no sender is tagged and `send.sh`
refuses everyone. A fresh clone can read mail and can do nothing with it until a
human writes the list.

What the code cannot enforce is the reply itself: that the agent answers only the
sender, answers once, and says so when it could not actually find something out.
Those live in `AGENTS.md`, and that is why it insists they be copied into the
agent's own persistent instructions rather than left in a file it may not reread.

---

## Why the version is a file, and the check is a remote read

The property this serves is the same one as everything else: an install must not
be able to believe it is current while it is not.

**The installed version is `VERSION`, not `git describe`.** A tag is a fact
about a clone's git metadata, and there are four ordinary ways to have this
software installed with that metadata absent or wrong: a tarball copy, a shallow
clone, a detached HEAD, and a clone whose tags were never fetched. A file copies
with the files. The cost is that it has to be bumped by hand at release time,
which is a discipline problem rather than a silent-failure problem, and it fails
in the direction of reporting an older version than you have.

**The released version comes from `git ls-remote`, not the GitHub API.** No
token to hold on a machine that already holds a mail password, no rate limit to
hit, and it follows the clone's own `origin`, so a fork or a mirror answers for
itself without being configured to. `GIT_TERMINAL_PROMPT=0` is load-bearing
there: a remote that has gone private otherwise asks for a username on a
terminal nobody is watching, and a hook waits on that until something kills it.

**Failure and currency are different answers, and the code keeps them apart.**
`version.sh` exits 1 when it could not reach the remote and never rounds that up
to "up to date". This is the same mistake as a dead listener looking like a
quiet mailbox: the absence of bad news is not good news, and every layer here
that treats it as such has eventually cost somebody a real message.

**The check runs at session start because nothing else would run it.** An agent
that is never told it is behind does not think to ask, and this repository has
already shipped a fix that no running install had any way to learn about. The
line costs one line of context per session, and the network round trip is cached
for a day, because an update that landed this morning is not worth a network
call at every start.

**Upgrading has its own document because a pull does not finish the job.** The
systemd units are copies made at install time, not links into the repository, so
a changed template does not reach a running install and nothing complains that
it did not. `harness/session_start.py` is meant to be edited per harness, so a
pull that touches it conflicts, and the conflict is the correct outcome rather
than a nuisance to force past. Both of those are in [`UPGRADE.md`](UPGRADE.md)
because they are the parts somebody working from memory would miss.

---

## What this repository is, and what it is not

This repo is the artifact. It was built from a 1,181-line replication guide that
has since been deleted, because once the code existed the guide became a **second
copy of every file in it**, and within hours the two had diverged, with fixes
present in one and absent from the other.

That is the third time the same failure has appeared in this project's short life:
a guide sent as a file attachment went stale within a day; a bugfix sat committed
on one machine while the shared copy stayed broken; and a document restating code
drifted from the code it restated.

**So: nothing here restates the code.** [`INSTALL.md`](INSTALL.md) says how to
deploy it and points at files. This document says why the files are the way they
are. Neither can go stale against the source, because neither contains it.
