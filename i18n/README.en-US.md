<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Elite messenger: the paynani were the official runners and messengers of the Aztec Empire.

[Español (MX)](../README.md) · **English (US)** · [Español (ES)](README.es-ES.md) · [Français (FR)](README.fr-FR.md) · [Português (BR)](README.pt-BR.md)

Push-style email for an AI agent. It finds out about new mail within about a
second, without polling, and can read and send under a recipient allowlist.

Built around [Himalaya](https://github.com/pimalaya/himalaya) for a plain
IMAP/SMTP account, running on Ubuntu 24.04 under the OpenClaw, Hermes Agent or
Claude Code harness. OpenClaw on macOS is supported through per-user launchd
LaunchAgents.

---

## Setting this up on your agent

Three steps. The first is yours alone, the second is one paste, the third is two
minutes of checking that it really works.

### Step 1: Give it a mailbox

The agent needs an email account of its own and the connection details for it,
written into a `.env` file. **If your agent runs under a harness, that file
belongs in the harness's own workspace folder** (`~/.hermes/workspace/.env`,
`~/.openclaw/workspace/.env`, `~/.claude/workspace/.env`), which is where the
agent is told to look and where this tool reads it from. On a host with no
harness, put it in the clone.

**[MAILBOX_SETUP.md](MAILBOX_SETUP.en-US.md) walks through it**: which account to use,
where to find the server hostname (the one part that reliably goes wrong), and the
file itself.

Do this yourself rather than asking the agent to. It needs a password, and a
password should not travel through a chat.

### Step 2: Point the agent at this repository

Paste this to your agent:

```text
Check your email account settings; they are in the workspace folder of your
Harness installation directory.

../workspace/.env

Then install this repository so you can use it:
https://github.com/iaaorgmx/paynani

Follow the instructions in the repository's AGENTS.md file.

You will need my name and my email address for the roster.md file.

Ask me anything you need.
```

<details>
<summary>En español</summary>

```text
Revisa la configuración de tu cuenta de correo electrónico; está en la
carpeta workspace del directorio de instalación de tu Harness.

../workspace/.env

Después, instala este repositorio para poder usarla:
https://github.com/iaaorgmx/paynani

Sigue las instrucciones del archivo AGENTS.md del repositorio.

Vas a necesitar mi nombre y mi dirección de correo electrónico para el archivo
roster.md.

Pregúntame lo que necesites.
```

</details>

Everything else the agent needs is in the repository, so the prompt only has to
point at it.

Expect questions before it starts. If Step 1 went well there should be few, and if
it asks for the password, refuse: a password pasted into a chat sits in that
transcript permanently, and no later care undoes it. That is not a step in any of
these instructions.

### Step 3: Test it yourself

The agent runs its own checklist and will tell you it passed. Two minutes of your
own testing is worth more, because you are testing the thing you actually care
about: does it notice, and does it stay inside its limits.

**Test 1: send it an email, and put an accent in the subject.**

From your own address, with a subject like `Prueba de correo: ñ, á, ¿qué tal?`
Then ask the agent what just arrived.

Within a couple of seconds it should tell you, and **the subject should come back
readable**. If you see `=?utf-8?q?...` instead, header decoding is broken, which
matters far more than it looks, because if you work in Spanish that is nearly every
message you will ever receive.

The accent is the whole point of this test. A plain English subject passes whether
or not decoding works.

**Test 2: ask it to email a stranger.**

First ask it to send you something, and confirm it arrives. Then ask it to send a
message to an address that is **not** on its approved list.

It should refuse. Not ask permission, not check with you first; refuse, and tell
you the address is not on the list. That allowlist is the entire reason it is safe
to let an agent that reads untrusted email also send it, so it is worth watching it
work once with your own eyes.

If it sends, stop and tell whoever set it up. Something is wrong.

---

## Delivery architecture by harness

Hermes operators configure two authenticated routes as described in
[`HERMES.md`](../HERMES.md).

Claude Code works differently from the other two, and the difference is not
cosmetic. Nothing outside a Claude Code session can speak into it, so mail is
not pushed to the agent: the agent comes and gets it. Its session-start hook
replays what arrived while nothing was running and then asks the agent to arm a
watch for what lands next. Nothing can enforce that from outside, so it is the
one step that rests on the agent doing as it is told. See
[`INSTALL.md`](../INSTALL.md) §6.

## What your agent will be able to do

- **Know about new mail in about a second**, without polling and without being
  told to check.
- **Read and send** through Himalaya, using the mailbox you configured.
- **Send only to addresses you approved**, listed in `roster.md`. Anything else is
  refused outright rather than asked about.
- **Work from mail sent by those same approved addresses.** You email it a task, it
  does the task and emails you the answer. No acknowledgement first, no permission
  round-trip; you already granted that by putting yourself on the list.
- **Leave everyone else's mail alone.** Mail from an address that is not on the
  list is reported to you and nothing more.

## What it changes on the machine

Worth knowing before you agree to it. The agent is instructed to report all of
this back when it finishes, and you can hold it to the list:

- Four supervised user units, not one. Two run continuously and restart on
  failure: the listener (`paynani-idle.service`) and the dispatcher
  (`paynani-dispatch.service`). Two more rotate the logs:
  `paynani-logrotate.timer`, which enables itself, and
  `paynani-logrotate.service`, which is `static` because the timer starts it and
  it is never enabled on its own. On macOS these are three equivalent
  LaunchAgents: `com.paynani.idle`, `com.paynani.dispatch` and
  `com.paynani.logrotate`
- A credentials file at mode `600`: your harness's workspace `.env` if you keep
  one there, otherwise `.env` inside the clone. It is read where it lies and
  never copied
- Log and state files under `state/` inside the clone
- Lingering enabled for the user on systemd hosts, or per-user LaunchAgents on
  macOS
- A standing rule added to the agent's own instructions

All of it is reversible; [`UNINSTALL.md`](UNINSTALL.en-US.md) removes every item on that
list, in an order that does not leave you working from memory.

## Keeping it up to date

The installed version is in [`VERSION`](../VERSION), and the agent is told which
one it is running at the start of every session, along with whether anything
newer has been released.

You can ask it the same question directly:

```bash
scripts/version.sh
```

It reads the released version from this repository's tags, so there is no
account and no token involved, and it says so plainly when it could not reach
the network rather than reporting an install as current because nothing
contradicted it.

Upgrading is [`UPGRADE.md`](../UPGRADE.md), and what changed between two versions
is [`CHANGELOG.md`](../CHANGELOG.md). Read the changelog first: a release
occasionally needs a step beyond `git pull`, and the failure mode of skipping it
is a listener that works until the next reboot.

## Security

The agent works from its mail, so the question is not whether it takes
instructions from email (it does, that is the point) but **whose**.

- `roster.md` is an exact-match allowlist, and it is the entire answer. On the
  list: the agent does what the message asks and replies. Not on the list: the
  agent tells you the mail arrived and does nothing else with it.
- Matching is on `From` only. A `Reply-To` pointing at someone you approved
  confers nothing, so a stranger cannot borrow a listed address with a header.
- **Adding someone to `roster.md` is your decision**, never a response to
  something that arrived in the mail. That line is what turns a sender into
  someone your agent obeys, so it is worth treating as a real one.
- No roster file means nobody is trusted; a fresh install reads mail and acts on
  none of it until you write the list.
- The password lives in a `600` file outside the repository and never passes
  through a chat transcript.

Note what this design leans on: your mail provider. SPF, DKIM and DMARC are
enforced upstream, before anything reaches the inbox, which is what keeps a forged
`From` from being trivial. If you point this at a mailbox with no such filtering,
the roster is weaker than it looks.

---

## The rest of the repository

Everything below is in English. The Spanish (MX) originals of the first two are
the source of truth; where a translation disagrees with them, they win.

| | |
|---|---|
| [`MAILBOX_SETUP.md`](MAILBOX_SETUP.en-US.md) | Step 1: the mailbox and the `.env` file |
| [`webapp/README.md`](../webapp/README.md) | Step 1 without a terminal: a local setup form |
| [`AGENTS.md`](../AGENTS.md) | What the agent follows. Start here if you are one. |
| [`INSTALL.md`](../INSTALL.md) | The deployment sequence, step by step |
| [`CHANGELOG.md`](../CHANGELOG.md) | What changed per release, and which releases need more than a pull |
| [`HERMES.md`](../HERMES.md) | The Hermes Agent adapter: routes, signatures and trust |
| [`UPGRADE.md`](../UPGRADE.md) | Moving an existing install to a newer version |
| [`DESIGN.md`](../DESIGN.md) | Why the pieces are shaped this way; read before changing any of it |
| [`UNINSTALL.md`](UNINSTALL.en-US.md) | How to take all of it back off |

```
scripts/idle_listener.py  supervised user service. Holds an IMAP IDLE connection
  │                       open; the server pushes the moment mail lands.
  │  one line per message
  ▼
<clone>/state/
  mail.log                the event stream
  idle.err.log            diagnostics, watched separately
  events.jsonl            the queue: one canonical envelope per line
  dispatch.offset         how far delivery has been confirmed
  │
  ├─► harness/dispatch.py         the one supervised consumer. Reads the journal,
  │                               hands each event to a runtime adapter, and moves
  │                               the cursor only once the runtime accepts it
  │     └─► harness/adapters/     openclaw, hermes and claudecode. The only code
  │                               here that knows what a harness is
  ├─► harness/session_start.py    shows what is still queued; never acknowledges
  └─► harness/rotate_logs.py      copytruncate rotation, on a user timer

scripts/version.sh        installed version against the newest release, and
                          what to do about the difference.
himalaya                  reads and sends. The listener never fetches bodies.
scripts/send.sh + roster.md  sending is restricted to allowlisted recipients.
<clone>/state/sent.log     what was sent, and to whom. Himalaya saves no copy
                          unless asked and SMTP has no Sent folder, so this is
                          the only record by default. No message bodies.
scripts/roster.py         the same allowlist, read by the listener to tag senders.
scripts/preflight.py      proves a host can run this before you install it.
webapp/ + setup_web.sh    a local form that writes the credentials file, for
                          people who do not want a terminal. Loopback only.
```

## Runtime paths

The clone is the install. Everything it owns lives inside it, so choosing where
to clone is how you choose where to install.

- Repo: anywhere. `~/.openclaw/workspace/paynani` on OpenClaw,
  `~/.hermes/workspace/paynani` on Hermes Agent,
  `~/.claude/workspace/paynani` on Claude Code, if you have no preference;
  every generated path is resolved from where the scripts are, so an existing
  clone needs no move.
- Secret env: your harness's workspace `.env` when there is exactly one
  (`~/.openclaw/workspace/.env`, `~/.hermes/workspace/.env`,
  `~/.claude/workspace/.env`), and `<clone>/.env` when there is not. Mode `600`,
  ignored by git, never committed. It is read where it lies and never copied into
  the clone: a second copy of a password is a second thing that can leak. Ask the
  install rather than guessing, with `python3 harness/paths.py env`.
- Event state: `<clone>/state/`
- Route secrets: `<clone>/hermes/`, mode `600`. **Hermes only**: on OpenClaw
  and Claude Code that directory does not exist and nothing is missing
- User units: `~/.config/systemd/user/paynani-idle.service`,
  `paynani-dispatch.service`, `paynani-logrotate.service` and
  `paynani-logrotate.timer` on Ubuntu, or the three `com.paynani.*.plist` files
  in `~/Library/LaunchAgents/` on macOS. This is the only thing outside the clone,
  because systemd does not read units from anywhere else

Secrets inside a git working tree are kept out of `git status` by `.gitignore`,
and `scripts/install.sh` refuses to write if any of them is tracked or unignored.
`git clean -xdf` still deletes them all, so use `git clean -df` on a live install.

## The property everything serves

**Never silently fail.** Latency was the easy problem; IDLE solved it in an
afternoon. Everything else here exists because the expensive failure is not being
slow, it is **confidently reporting no new mail while blind**.

That is why the last-seen UID is persisted per message, why `UIDVALIDITY` is
checked on every connect, why the error log is watched alongside the event log, and
why the session-start hook asks whether the service is actually running.
[`DESIGN.md`](../DESIGN.md) explains each one and what breaks without it.

Built and verified end to end on 2026-08-09.

## Where the name comes from

**paynani** is Classical Nahuatl, and it means something plainer than it sounds:
*"the one who runs lightly."* From the verb `paina` ("correr ligeramente," in
Alonso de Molina's 1571 vocabulary) plus the suffix `-ni`, which turns an action
into the one who does it for a living.

The spelling varies because sixteenth-century friars wrote Nahuatl with the
Spanish conventions of their day, in which `i`, `y` and `j` were used almost
interchangeably. The Gran Diccionario Náhuatl indexes the same Florentine Codex
passages under both `painani` and `painanj`, and records `payna` as a variant of
`paina`: one word, several spellings. This project writes `paynani`, the form a
Spanish-speaking reader recognizes.

The name of the office grew out of that quality. Nahuatl had two ways to name
the imperial messenger: `titlantli`, "the one sent," which defines him by the
errand he carries, and `paynani`, which defines him by how he moves. The one that
stuck to these men was the second: they were known for the way they ran, not for
who dispatched them.

The runners worked in relays, through staging posts called `techialoyan`, and
trained from childhood. Of everything recorded about them, one detail is exactly
what this tool does: **the messenger classified the news before he opened his
mouth.** Arriving with loose, disheveled hair meant a defeat, and he was given no
greeting at all; arriving with braided hair and a coloured ribbon, carrying shield
and club, meant a victory, and crowds followed him to the palace. That is what the
`roster` tag does here: the envelope says how to receive the news before anyone
reads it.

The same root gave Paynal, who ran in Huitzilopochtli's place during processions.
The Florentine Codex explains him in three words, *"the delegate, the substitute,
the deputy"*, because "they pressed him on quickly; he was made to hasten." An
agent that goes for the mail on behalf of whoever cannot be everywhere at once.

<sub>Sources: [Gran Diccionario Náhuatl](https://gdn.iib.unam.mx/diccionario/painani/233892)
(UNAM) · [Nahuatl Dictionary](https://nahuatl.wired-humanities.org/content/paina)
(Wired Humanities) · [Mexicolore](https://www.mexicolore.co.uk/aztecs/ask-experts/did-they-send-post-mail).</sub>

---

<sub>Translated from [`README.md`](../README.md) at commit `2b1fc9c`, which is the source of truth. Where this contradicts the Spanish (MX) original, **the Spanish wins**, and say so, because it means this translation has fallen behind.</sub>
