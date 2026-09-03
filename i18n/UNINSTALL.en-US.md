# Removing paynani

[Español (MX)](../UNINSTALL.md) · **English**

> Translated from [`UNINSTALL.md`](../UNINSTALL.md) at commit `2b1fc9c`, which is the source of
> truth. Where this contradicts the Spanish (MX) original, **the Spanish wins** —
> and say so, because it means this translation has fallen behind.

This installs a background service that touches six places on a machine. Here is
how to take all of it back off, for a clean reinstall, for handing the machine
on, or because you changed your mind.

**Nothing here touches the mailbox itself.** Mail already delivered stays on the
server. If you also want the agent to lose access, revoke its app-password at the
provider, which is the only step that cannot be undone from this machine.

For an install owned by the FR7 manifest, prefer the provenance-aware uninstall:

```bash
scripts/install.sh --runtime openclaw --uninstall --dry-run
scripts/install.sh --runtime openclaw --uninstall
```

Use the runtime recorded by the current install. The mutating command validates
all owned files before its first mutation, disables and stops reachable owned
units, and removes only manifest-recorded artifacts. It deliberately preserves
mailbox credentials, `roster.md`, the repository, event journal, cursor, logs,
and other state. If the systemd user manager is unavailable, filesystem cleanup
continues but reports that service deactivation is unconfirmed. Exit `10` means
successful changes; `0` means there was no ownership manifest and nothing was
removed. A changed owned artifact is preserved and causes a fail-closed refusal
with move-aside recovery instructions.

The manual destructive procedure below is for an install without an ownership
manifest, or for an operator who intentionally wants to remove the preserved
credentials/state/repository too.

---

## 0. First, if you intend to reinstall

**Copy your unit files out before touching anything.** They are the only working
ones you have, and step 1 deletes them.

```bash
mkdir -p ~/paynani-units-kept
cp ~/.config/systemd/user/paynani-*.service ~/paynani-units-kept/ 2>/dev/null
cp ~/.config/systemd/user/paynani-*.timer   ~/paynani-units-kept/ 2>/dev/null
ls -1 ~/paynani-units-kept/
```

**Note the clone URL too**, because step 6 deletes the repository and with it any
memory of where it came from:

```bash
git -C "$REPO" remote get-url origin
```

## 1. Stop and remove the services

### macOS launchd

For an OpenClaw macOS install:

```bash
scripts/install.sh --runtime openclaw --uninstall --dry-run
scripts/install.sh --runtime openclaw --uninstall
```

Manual equivalent:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.paynani.idle.plist 2>/dev/null || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.paynani.dispatch.plist 2>/dev/null || true
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.paynani.logrotate.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.paynani.idle.plist
rm -f ~/Library/LaunchAgents/com.paynani.dispatch.plist
rm -f ~/Library/LaunchAgents/com.paynani.logrotate.plist
```

Credentials, roster, state, journal, cursor and logs are preserved unless you
remove them explicitly.

### systemd

**Take an inventory first.** The names below are the usual ones, not necessarily
yours, and everything after this point is destructive:

```bash
systemctl --user list-unit-files | grep -i paynani
```

A full install has four: `idle.service`, `dispatch.service`, `logrotate.service`
and `logrotate.timer`. The logrotate *service* is typically `static`; it has no
`[Install]` section, so `disable` does nothing and it is simply deleted with the
rest. That is expected, not an error.

```bash
systemctl --user stop    paynani-idle.service paynani-dispatch.service
systemctl --user disable paynani-idle.service paynani-dispatch.service
systemctl --user stop    paynani-logrotate.timer
systemctl --user disable paynani-logrotate.timer

rm -f ~/.config/systemd/user/paynani-*.service
rm -f ~/.config/systemd/user/paynani-*.timer
systemctl --user daemon-reload
```

Confirm nothing is left:

```bash
systemctl --user list-unit-files 'paynani-*'    # expect no rows
pgrep -af idle_listener.py                           # expect nothing
```

## 2. Remove the credentials

**Find out where they are first, because on most installs they are not in the
clone.** When the host has a harness, the mailbox password lives in that
harness's workspace `.env` — `~/.openclaw/workspace/.env`,
`~/.hermes/workspace/.env`, `~/.claude/workspace/.env` — and `<clone>/.env` does
not exist at all. An `rm -f .env` from the clone would delete nothing in that
case, and leave you believing you had removed the password.

Do not guess the path. Ask the install, from inside the clone:

```bash
python3 harness/paths.py env
```

If what it answers is **outside** the clone, that file belongs to the harness and
not to this tool: other things use it and it is **not deleted whole.** Remove
only the keys this install added — the `PAYNANI_*` ones, and the `AGENT_EMAIL_*`
ones if they were for this mailbox and nothing else reads them — and leave the
rest of the file standing. The same holds for a symlink: **do not delete what it
points at.**

If what it answers is `<clone>/.env`, that file does belong to this install and
goes entirely, with the command below.

Then, from inside the clone, what always belongs to it:

```bash
rm -f .env runtime.env install.manifest
rm -rf hermes
```

## 3. Remove state and logs

```bash
rm -rf state/
```

This holds the event log, the error log, the last-seen UID and the byte offset.
Deleting it is what makes the next install a genuine fresh start: with the state
file gone, a new listener takes a baseline from whatever is already in the
mailbox rather than resuming, so nothing replays.

## 4. Remove the Himalaya account, carefully

`~/.config/himalaya/config.toml` may hold accounts other than this one. **Remove
only the `[accounts.paynani]` block**, not the file.

```bash
cp ~/.config/himalaya/config.toml ~/.config/himalaya/config.toml.bak.$(date +%F)
```

Then delete the block. A reproducible way, rather than editing by eye; it removes
from the `[accounts.paynani]` header up to the next top-level `[` and leaves
everything else untouched:

```bash
python3 - <<'PY'
import pathlib, re
p = pathlib.Path.home() / ".config/himalaya/config.toml"
text = p.read_text()
out = re.sub(r'(?ms)^\[accounts\.paynani(?:\.[^\]]+)?\].*?(?=^\[(?!accounts\.paynani)|\Z)', '', text)
p.write_text(out)
print("removed" if out != text else "nothing matched: check the account name")
PY

himalaya account list       # every other account must still be there
```

If it was the only account and you set `default = true` on it, give the default
to another account or the next bare `himalaya` command has nowhere to go.

## 5. Remove the standing rule from the agent's own instructions

The install adds a rule to the agent's persistent instructions (usually its
`AGENTS.md` or equivalent) saying that mail from an address on `roster.md` is
work it should carry out and answer.

**Remove it, and do not treat this step as optional.** This rule grants something
rather than withholding it, so a stale copy is not harmlessly redundant the way a
leftover caution would be. The `roster.md` it refers to is gone, the listener that
tagged senders is gone, and what remains is an instruction to act on mail with
nothing left to define whose. If the agent keeps a mailbox by some other route, it
will apply this rule there.

**Reinstalling is not a reason to leave it.** The "Standing rules" section of
`AGENTS.md` puts it back during the install, against the roster that will actually
exist then.

## 6. Remove the repository

```bash
rm -rf "$REPO"   # the clone you installed from
```

**`roster.md` lives in there and is not in git**, so this deletes it and no
`git clone` brings it back. If the list took any effort to assemble, copy it out
first:

```bash
cp "$REPO/roster.md" ~/roster.md.kept
```

Do this **last**. Everything above references paths inside it, and removing it
first leaves you working from memory.

---

## What is deliberately left alone

**Lingering.** `loginctl enable-linger` was turned on during the install, but
other user services may now depend on it. Turn it off only if you know nothing
else needs it:

```bash
loginctl show-user "$USER" -p Linger      # check first
sudo loginctl disable-linger "$USER"      # only if you are sure
```

**Himalaya itself**, if the install put it there. It is a general mail client and
may be useful on its own.

**The mailbox and everything in it.** See the note at the top.

---

## Confirm it is gone

```bash
systemctl --user list-unit-files 'paynani-*'  # no rows
pgrep -af "[i]dle_listener.py"                # nothing; brackets stop pgrep
                                              # matching its own command line
ls .env state hermes 2>&1                     # no such file or directory
himalaya account list                         # paynani absent, others intact
```

Four clean results and the machine is back where it started.
