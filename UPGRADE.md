# Upgrading an existing install

**Audience:** an agent that already has this running and has been told, or has
found out, that a newer release exists.

A pull is the easy part. What makes this a document rather than one command is
that three things this tool depends on are deliberately outside the repository,
so `git pull` cannot reach them, and the pieces it does reach are running code
that has to be restarted before the new version is the one in memory.

For an install already owned by the FR7 manifest, use the idempotent installer
after reviewing the changelog and pulling the repository:

```bash
scripts/install.sh --runtime openclaw --upgrade --dry-run
scripts/install.sh --runtime openclaw --upgrade
# Or migrate explicitly; runtime changes are refused without --upgrade:
scripts/install.sh --runtime hermes --profile PROFILE --upgrade
```

The mutating run revalidates manifest provenance, converges changed owned files,
verifies runtime-specific probes, reloads systemd, and restarts required units when
the owned runtime boundary changed. It preserves credentials, roster, journal,
cursor, logs, and generated Hermes secrets across a runtime migration. Exit `10`
means successful changes; `0` means already converged. For Hermes, configure the
operator-managed routes and full URL environment described in `INSTALL.md` and
`HERMES.md` first; `--profile` and `--deliver`/`--chat-id` do not edit Hermes.

The manual sequence below remains the recovery path for an install without an
ownership manifest.

---

## After any change to the roster

`roster.md` is the one name the resolver, `send.sh` and `envpath.sh` answer.
After editing it, rerun both tests:

```bash
scripts/test_roster.sh
scripts/test_listener.py
```

**Rerun them for any change to this file.** It is the one file that decides
whose mail you act on, and the failure it produces when wrong is silent: an
empty allowlist refuses every recipient and stops tagging every sender
`roster`, which looks exactly like nobody having written to you.

**Markdown tables are accepted** now that the file is `.md`, so a row like
`| Julian Flores | jjulianfe@gmail.com |` parses. Plain `Name | address` lines
work exactly as before, and an entry without an `@` is ignored rather than
becoming an allowlist entry, which is what keeps a table's header row harmless.

## 1. Find out where you are

```bash
cd "$(git -C . rev-parse --show-toplevel 2>/dev/null || echo ~/.openclaw/workspace/paynani)"
scripts/version.sh
```

It prints the installed version, the newest released one, and exits 2 when there
is something to do. If it exits 1, **stop and read what it says**: it could not
reach the remote, which is not the same as being up to date, and upgrading blind
is worse than not upgrading.

If there is no `scripts/version.sh` at all, the clone has been edited. Carry on
here anyway; the sequence is the same.

## 2. Read the changelog entries you are crossing

[`CHANGELOG.md`](CHANGELOG.md), every entry between your version and the target,
not just the newest. Entries with an **Upgrade actions** section need a step
beyond the pull, and doing the pull first and the reading afterwards is how a
working install becomes a broken one.

## 3. Check you have nothing uncommitted

```bash
git status --short
```

**Expect it to be empty apart from untracked files.** If a tracked file has
local changes, `git pull --ff-only` will refuse, and that refusal is correct: on
this tool the file most likely to be edited in place is
`harness/session_start.py`, whose marked block is Claude Code's payload format.
Reapply your adaptation onto the new version rather than keeping your copy of the
old file.

**Only Claude Code installs have any reason to have edited it.** On OpenClaw and
Hermes nothing invokes that script, so a local change to it there is almost
certainly a leftover from following older instructions, and reverting is safer
than reapplying.

`roster.md` and your credentials will show as untracked or not at all. That is
correct and covered in §7.

## 4. Pull

```bash
git pull --ff-only origin main
```

`--ff-only` rather than a bare pull, so a diverged clone stops here and says so
instead of opening a merge you did not intend and cannot review.

## 5. Re-copy anything the install copied rather than referenced

This is the step that gets skipped, because nothing complains when it is.

**The systemd units in your install are copies**, made with `install -Dm644`
during `INSTALL.md` §5. A changed template under `systemd/` in this repository
does not reach `~/.config/systemd/user/` on its own, and nothing will tell you
so. If the changelog entry says a unit template changed, or that a file moved,
re-copy them and replace the two placeholders again:

```bash
install -Dm644 systemd/paynani-idle.service       ~/.config/systemd/user/
install -Dm644 systemd/paynani-dispatch.service   ~/.config/systemd/user/
install -Dm644 systemd/paynani-logrotate.service  ~/.config/systemd/user/
install -Dm644 systemd/paynani-logrotate.timer    ~/.config/systemd/user/
#   /path/to/paynani  ->  your clone's absolute path
#   /path/to/env      ->  your credentials file (idle only)
```

Then confirm every `ExecStart` still names a file that exists:

```bash
grep -h ExecStart ~/.config/systemd/user/paynani-*.service
systemd-analyze verify ~/.config/systemd/user/paynani-*.{service,timer}
```

`systemd-analyze verify` prints nothing and exits 0 when the units are sound.

### On macOS, the same trap with different files

A macOS install is supervised by two LaunchAgents in `~/Library/LaunchAgents`,
rendered by `scripts/install_macos.py`. They are copies for the same reason the
systemd units are, and a `git pull` does not touch them either.

The difference is that you do not re-copy them by hand. Re-run the installer and
let it converge:

```bash
scripts/install.sh --runtime openclaw --dry-run    # read the plan first
scripts/install.sh --runtime openclaw
```

The dry run lists any plist it intends to rewrite, so it also answers whether
this step was needed. Then check what is actually loaded, which is the launchd
equivalent of the `ExecStart` check above:

```bash
launchctl print "gui/$(id -u)/com.paynani.idle" | grep -A3 'arguments'
launchctl print "gui/$(id -u)/com.paynani.dispatch" | grep -A3 'arguments'
```

A plist that still names a path from before the pull is the macOS version of the
failure this whole section exists to prevent: an install whose supervisor points
at a file that has moved, and nothing anywhere saying so.
**Read the exit code**; it is easy to see no obvious complaint and move on while
it was in fact objecting.

## 6. Restart, and only then believe the new version is running

The listener is a long-lived process. Until it restarts, you have pulled new
code and are still running the old.

```bash
systemctl --user daemon-reload
systemctl --user enable paynani-idle.service
systemctl --user enable paynani-dispatch.service
systemctl --user enable paynani-logrotate.timer
systemctl --user restart paynani-idle.service
systemctl --user restart paynani-dispatch.service
```

A restart can take up to 30 seconds; the listener is blocked on the IMAP socket
and notices the stop signal when that wait ends.

## 7. What the pull could not touch

None of these are bugs. They are the design, and they are worth confirming
rather than assuming:

- **`roster.md` is untracked**, so a pull cannot change who you may write to.
  It survives the upgrade unchanged, which is the point of it being untracked.
- **Credentials are untracked**, at `.env` in the clone, at the file it links
  to, or in the harness workspace this install reads from. Untouched either way.
- **Log and state files** under `state/` in the clone are untouched, including
  `dispatch.offset`, the event journal and the last-seen UID, which is why an
  upgrade does not replay your mailbox.
- **A pull cannot reach any of them.** They are ignored, and `scripts/install.sh`
  refuses to write if any of them is tracked or unignored. What a pull cannot
  protect you from is `git clean -xdf`, which deletes ignored files: on a live
  install that is the mailbox password, both route secrets, the roster and the
  UID baseline. Use `git clean -df`.

## 7b. If you linked your harness's credentials into the clone

Only relevant if your credentials live in a harness workspace —
`~/.hermes/workspace/.env` or the OpenClaw equivalent — and you linked or copied
them to `.env` inside the clone because an older version of this tool could not
find them there.

**The resolver now reads them where the harness keeps them**, so the answer to
"where are my credentials" changes on your host even though nothing moved. Your
existing link keeps working, and nothing breaks at the moment you pull.

What changes is what `scripts/install.sh` renders: the listener unit carries
`--env <path>` fixed at install time, and it now resolves to the harness file
rather than to the link. Re-run the installer so the unit matches:

```bash
scripts/install.sh --runtime <your runtime> --profile <your profile> --dry-run
scripts/install.sh --runtime <your runtime> --profile <your profile>
grep ExecStart ~/.config/systemd/user/paynani-idle.service
```

Only once that reports the harness path is it safe to remove the link. Removing
it while the unit still names it is the failure INSTALL.md warns about: a
hand-run test succeeds and the service dies at startup on a file that is no
longer there.

**Himalaya holds its own copy of that path, and nothing here can update it.**
`~/.config/himalaya/config.toml` reads the password with a command naming the
file in full, and Himalaya's config lives outside the clone. If that command
points at the link you just removed, sending fails with a `FileNotFoundError`
for a path that no longer exists — while the listener, the units and the
healthcheck all look correct, because none of them go through Himalaya's config.

```bash
grep -n 'password.cmd\|passwd.cmd' ~/.config/himalaya/config.toml
```

Point it at the same file `paynani_env_file` now reports, and keep a backup
first. Found on the first host to make this change, where it was the only step
the installer could not do for itself.

## 8. Verify, with the checks that can actually fail

```bash
# The new version is the installed version
scripts/version.sh

# Running, and for more than a moment
systemctl --user is-active paynani-idle.service
systemctl --user is-active paynani-dispatch.service

# The one that proves state survived: "resuming from uid N", not "baseline uid N"
tail -2 state/idle.err.log

# The watcher can still reach openclaw: silence is the pass
grep -iE "openclaw not found|injection failed" state/watch.err.log

# The allowlist still behaves, on both the send and the receive side
scripts/test_roster.sh
python3 scripts/test_listener.py
```

**"resuming from uid N" is the line that matters.** If it says `baseline` after
a restart, the state file is not being written and the next reboot will
silently swallow every message that arrived while the machine was off.

Then send yourself one message and confirm it arrives in the session. Every
check above can pass on an install that delivers nothing, which is a real
failure this tool has had, so the end-to-end test is not optional politeness.

## 9. Tell your human what you did

Which version to which version, anything from an **Upgrade actions** section
that you applied, and any unit file you re-copied. The same rule as the install:
everything that matters here lives outside the repository, and without the list
they have a changed system and no record of what changed.

## After any upgrade

```bash
scripts/healthcheck.py
```

Nonzero means mail cannot currently be detected or delivered, and it says which.
Checking that nothing arrived is not the same check, and a quiet mailbox will
pass it whether or not anything is listening.
