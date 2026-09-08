# Migrating from agenteiamail to paynani

This document is only for a renamed installation: a host that already ran
`agenteiamail` and is now moving that same mailbox workflow to `paynani`.

It is not the clean-install path and it is not the ordinary upgrade path:

- New host, no previous mail agent: follow [`INSTALL.md`](INSTALL.md).
- Existing `paynani` install, newer release: follow [`UPGRADE.md`](UPGRADE.md).
- Existing `agenteiamail` install, renamed to `paynani`: use this file, then
  return to [`INSTALL.md`](INSTALL.md) for any missing first-run checks.

Run these checks before starting new work from a migrated host. The symptoms are
confusing because the old name can keep working in config, logs, and systemd
state even after the old clone has been removed.

## 1. Remove the old Himalaya account

First inspect the live account table:

```bash
himalaya account list
```

If it still shows an `agenteiamail` account, especially with `DEFAULT yes`, bare
`himalaya` commands will keep talking to the old account. When those credentials
are gone, the failure looks like this:

```text
IMAP AUTHENTICATE PLAIN failed: NO Invalid credentials
```

Back up the Himalaya config and edit the account table:

```bash
cp ~/.config/himalaya/config.toml \
  ~/.config/himalaya/config.toml.bak.$(date +%Y%m%d-%H%M%S)

${EDITOR:-vi} ~/.config/himalaya/config.toml
```

In that file, remove the old account sections:

```toml
[accounts.agenteiamail]
[accounts.agenteiamail.imap]
[accounts.agenteiamail.imap.sasl.plain]
[accounts.agenteiamail.smtp]
[accounts.agenteiamail.smtp.sasl.plain]
```

Keep the `paynani` sections and make the default choice explicit there if this
mailbox should be the default:

```toml
[accounts.paynani]
default = true
```

Then verify both the default and the named account:

```bash
himalaya account list
himalaya account check -a paynani
himalaya envelope list -a paynani -s 3
```

Operational scripts still use `-a paynani`; the default mainly protects humans
and ad-hoc commands from accidentally reaching the removed account.

## 2. Replace live instructions that name the old send script

The old path:

```text
~/.openclaw/workspace/agenteiamail/scripts/send.sh
```

must become:

```text
~/.openclaw/workspace/paynani/scripts/send.sh
```

Search the places that usually survive a rename:

```bash
grep -rn 'agenteiamail' \
  ~/.openclaw/AGENTS.md \
  ~/.openclaw/HEARTBEAT.md \
  ~/.openclaw/workflows \
  ~/.config
```

**`grep`, not `rg`, and no `2>/dev/null` on this one.** ripgrep is not part of a
base install anywhere -- not on macOS, not on a minimal Ubuntu -- and this repo
does not require it. Silencing stderr on top of that is what makes it dangerous
rather than merely absent: on a host without ripgrep the line prints *nothing*,
and in this section nothing reads as "no old instructions remain". You would tick
this step off with the heartbeat still pointing at a `send.sh` that no longer
exists, which is the exact leftover the step exists to catch.

Errors here are worth seeing. A path that does not exist on your host prints one
line and costs nothing; a search tool that is not installed prints one line and
saves you from a false clean.

Edit each live instruction file that still points at the old product:

```bash
${EDITOR:-vi} ~/.openclaw/AGENTS.md
${EDITOR:-vi} ~/.openclaw/HEARTBEAT.md
```

If your host stores workflows somewhere else, include that directory in the
search and edit the matching files too. Do not leave a compatibility symlink as
the fix; it hides the migration bug and makes the next cleanup harder.

## 3. Clear stale systemd user units

After the old unit files are deleted, systemd can still remember failed units
under the old name. The common symptom is a row such as:

```text
agenteiamail-idle.service loaded failed failed not-found
```

Inspect both the unit files and remembered unit state:

```bash
ls -l ~/.config/systemd/user/agenteiamail-* 2>/dev/null || true
systemctl --user list-units --all 'agenteiamail*'
systemctl --user list-unit-files 'agenteiamail*'
```

If old unit files still exist, disable them and move them out of systemd's live
directory:

```bash
systemctl --user disable --now agenteiamail-idle.service agenteiamail-dispatch.service 2>/dev/null || true
mkdir -p ~/.config/systemd/user/archive-agenteiamail
mv ~/.config/systemd/user/agenteiamail-* ~/.config/systemd/user/archive-agenteiamail/ 2>/dev/null || true
systemctl --user daemon-reload
```

Then clear systemd's remembered failures:

```bash
systemctl --user reset-failed agenteiamail-idle.service \
  agenteiamail-dispatch.service \
  agenteiamail-logrotate.service \
  agenteiamail-logrotate.timer

systemctl --user list-units --all 'agenteiamail*'
```

The final command should print no active, failed, or not-found `agenteiamail`
units.

## 4. Verify the paynani path

Now confirm the renamed install is the one that actually sends, listens, and
dispatches:

```bash
cd ~/.openclaw/workspace/paynani

scripts/version.sh
scripts/healthcheck.py
scripts/test_all.sh

systemctl --user is-active paynani-idle.service
systemctl --user is-active paynani-dispatch.service
himalaya envelope list -a paynani -s 3
```

If `scripts/test_all.sh` is missing, the checkout is older than the migration
documentation expects. Update the repository first by following
[`UPGRADE.md`](UPGRADE.md), then return here.
