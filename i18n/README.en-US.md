<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Elite messenger: the paynani were the official runners and messengers of the Aztec Empire.

[Español (MX)](../README.md) · **English (US)** · [Español (ES)](README.es-ES.md) · [Français (FR)](README.fr-FR.md) · [Português (BR)](README.pt-BR.md)

Paynani lets your AI agent automatically read its own email a few seconds after
it arrives, process the messages it receives, and act on their instructions just
as a human colleague would.

Every incoming email is read, but instructions are only followed when they come
from a list of authorized contacts. You write that list yourself, and it lives in
a file called `roster.md`.

Paynani is built on [Himalaya](https://github.com/pimalaya/himalaya) and works
with an ordinary email account, the same kind you would set up in any mail
program.

**It is completely free to use!** You don't need to pay for any extra service to
give your agent an email address it can use on its own.

It runs on your own computer or server, inside the program that already hosts
your agent. That host program is called a *harness*, and that is how the word is
used on the rest of this page. Paynani is currently used by AI agents such as
OpenClaw, Hermes Agent, Claude Code and OpenAI Codex.

Developed and tested on Linux (Ubuntu 24.04) and macOS (26.4.1).

Made with love by humans and AI agents, from Mexico to the world.

---

## Who it is for

For anyone who wants to give their agent a real email address without mixing
their personal mailbox, their passwords or their trust decisions into it.

It helps if you want your agent to:

- receive tasks by email, from you or from your team;
- tell you when something worth looking at arrives;
- reply from an account of its own rather than yours;
- refuse to obey, or to write to, anyone who is not on your list.

It is not for handing your judgement to whatever message shows up. Anyone can
send email, so Paynani treats everything that arrives as untrusted until the
sender matches your list.

## Before you start

You need four things:

1. an email account dedicated to the agent, not your personal one;
2. access to a terminal on the machine where your agent runs;
3. a moment to write the password into a file yourself, without pasting it into a chat;
4. your name and email address, for the list of authorized contacts.

That is all. No mail API, no service in the middle, no new account anywhere.

## Setting this up on your agent

Three steps. The first is yours alone, the second is one paste, the third is two
minutes of checking that it really works.

### Step 1: Give it a mailbox

The agent needs an email account of its own and the connection details for it,
written into a file called `.env`. **If your agent runs under a harness, that
file belongs in the harness's own `workspace` folder**
(`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env`, `~/.codex/workspace/.env`), which is where the agent
is told to look and where this tool reads it from. With no harness, the file can
live inside the project folder. And if you are not sure where it ended up, you
can ask the installation with `python3 harness/paths.py env`.

**[MAILBOX_SETUP.en-US.md](MAILBOX_SETUP.en-US.md) walks through it**: which
account to use, where to find the server hostname (the one part that reliably
goes wrong), and the file itself.

> [!CAUTION]
> Do this yourself rather than asking the agent to. It needs a password, and a
> password should not travel through a chat: the one you paste into a
> conversation sits in that transcript permanently, and no later care undoes it.
> If you would rather not use the terminal, `scripts/setup_web.sh` opens a local
> form that writes the file for you.

### Step 2: Point the agent at this repository

Paste this to your agent:

```text
Check your email account
settings; they are in the
workspace folder of your Harness
installation directory.

../workspace/.env

Then install this repository so
you can use it:
https://github.com/iaaorgmx/paynani

Follow the instructions in the
repository's AGENTS.md file.

You will need my name and my
email address for the roster.md
file.

Ask me anything you need.
```

<details>
<summary>En español</summary>

```text
Revisa la configuración de tu
cuenta de correo electrónico;
está en la carpeta workspace del
directorio de instalación de tu
Harness.

../workspace/.env

Después, instala este
repositorio para poder usarla:
https://github.com/iaaorgmx/paynani

Sigue las instrucciones del
archivo AGENTS.md del
repositorio.

Vas a necesitar mi nombre y mi
dirección de correo electrónico
para el archivo roster.md.

Pregúntame lo que necesites.
```

</details>

Everything else the agent needs is in the repository, so the prompt only has to
point at it.

Expect questions before it starts. If Step 1 went well there should be few. If it
asks for the password, refuse: that is not a step in any of these instructions.

### Step 3: Test it yourself

The agent runs its own checklist and will tell you it passed. Two minutes of your
own testing is worth more, because you are testing the thing you actually care
about: does it notice, and does it stay inside its limits.

**Test 1: send it an email, and put an accent in the subject.**

From your own address, with a subject like `Prueba de correo: ñ, á, ¿qué tal?`
Then ask the agent what just arrived.

Within a couple of seconds it should tell you, and **the subject should come back
readable**. If you see `=?utf-8?q?...` instead, something is broken in the way it
reads headers, and that matters far more than it looks: if you work in Spanish,
that is nearly every message you will ever receive.

The accent is the whole point of this test. A plain English subject passes
whether or not it works.

**Test 2: ask it to email a stranger.**

First ask it to send you something, and confirm it arrives. Then ask it to send a
message to an address that is **not** on its approved list.

It should refuse. Not ask permission, not check with you first; refuse, and tell
you the address is not on the list. That allowlist is the entire reason it is
safe to let an agent that reads untrusted email also send it, so it is worth
watching it work once with your own eyes.

If it sends, stop and tell whoever set it up. Something is wrong.

## What your agent will be able to do

- **Notice new mail within about a second**, without polling and without being
  asked.
- **Read and send** from the mailbox you set up.
- **Send only to addresses you approved**, the ones on your list. Anything else
  is refused outright, without even asking you.
- **Work on the mail those same approved addresses send.** You write it a task,
  it does the task and mails you back. No acknowledgement first and no asking
  permission; you granted that when you put yourself on the list.
- **Leave everyone else's mail alone.** Anything from an address not on the list
  is reported to you, and nothing more.
- **Not lose what arrived** if the machine restarts mid-task. Every message it
  detects is written to disk before it is handed over.

## What changes on your computer

Worth knowing before you accept. The agent is instructed to report all of this
when it finishes, and you can hold it to the list:

- **Two services that stay running all the time** and restart themselves if they
  fail: the one that listens to the mailbox and the one that hands messages to
  your agent. They are installed as services belonging to your user, not to the
  system.
- **Two more that only trim the logs** so they don't grow without end.
- **A file holding the mailbox password**, readable only by your user. It is read
  where you left it and never copied elsewhere.
- **Log and state files** inside the project folder.
- **Permission for those services to stay alive after you log out.**
- **A permanent rule added to the agent's own instructions.**

All of it is reversible; [`UNINSTALL.md`](../UNINSTALL.md) removes every item on
that list, in an order that does not leave you working from memory.

<details>
<summary>The exact names, if you need them</summary>

Four systemd user units, not one. Two run all the time and restart themselves if
they fail: the listener (`paynani-idle.service`) and the dispatcher
(`paynani-dispatch.service`). The other two rotate the logs:
`paynani-logrotate.timer`, which enables itself, and
`paynani-logrotate.service`, which is `static` because the timer fires it and it
is not enabled on its own. On macOS these are three equivalent LaunchAgents:
`com.paynani.idle`, `com.paynani.dispatch` and `com.paynani.logrotate`.

The credentials file carries `600` permissions: the `.env` in your harness
workspace if you keep it there, and `.env` inside the clone if not. Logs and
state live in `state/`, inside the clone. *Lingering* is what keeps the services
alive after you log out.

</details>

`.gitignore` keeps the secrets out of `git status`, and `scripts/install.sh`
refuses to write if any of them is tracked or unignored. What that does not
prevent is `git clean -xdf`, which deletes ignored files: on a live install that
means the mailbox password, the two Hermes route secrets (`<clone>/hermes/`,
Hermes only), the list of approved recipients and the mark of the last message
seen. Use `git clean -df`.

## Security and limits

> [!WARNING]
> Your list of authorized contacts decides whose work your agent accepts. It does
> not prove who that person is. Email from someone not on the list is reported to
> you, and stops there.

The agent works out of its mailbox, so the question is not whether it obeys
instructions that arrive by email. It does, and that is the point. The question
is **whose**.

- `roster.md` is an exact-match list, and it is the whole answer. If the sender
  is on the list, the agent does what the message asks and replies. If not, it
  tells you the mail arrived and does nothing further with it.
- The match is on the sender the message carries, and only on that one. A
  stranger cannot borrow an address from your list by putting it in another
  field.
- **With one exception that you declare:** *notifiers*. If your team coordinates
  on a platform that sends mail on people's behalf (GitHub, Jira, Linear), you
  can declare its address and which part of your list to check the author
  against. That notification then counts as mail from that person. Declaring a
  notifier widens who your agent listens to, exactly as adding a row does, and it
  is decided the same way: never because a message asked for it.
- **Adding someone to the list is your decision**, never a response to something
  that arrived by email. That line is what turns a sender into someone your agent
  obeys.
- With no list, nobody is trusted. A fresh install reads mail and acts on nothing
  until you write it.

Worth knowing what all of this leans on: your mail provider. The filtering that
Gmail, Outlook and the rest apply is what keeps forging a sender from being
trivial, and it happens before the message reaches the inbox. Point Paynani at a
mailbox without that filtering and the list protects less than it appears to.

## How to know it is healthy

> [!IMPORTANT]
> No pending messages does not prove Paynani is healthy. It looks the same when
> it has stopped listening.

Ask your agent to run the health check and show you the output:

```bash
python3 scripts/healthcheck.py
```

It checks the services, the credentials, the message queue, delivery to your
agent and the list of authorized contacts. What you want to see is that the
services are alive, that nothing is stuck, and that the configuration is being
read from the right place. If something fails, the report tells you which piece,
not just that there is no mail.

The long options and the failure modes are in [`INSTALL.md`](../INSTALL.md).

## How it is built, in short

One service holds a connection open to your mail server, of the kind where the
server announces new mail on its own instead of being asked. When a message
arrives, that service writes it to disk before doing anything else. A second
service reads those notes and hands them to your agent, and only marks one as
delivered once the agent confirms it received it.

That separation is what keeps mail from being lost when something fails
halfway. [`DESIGN.md`](../DESIGN.md) explains each piece, why it is shaped that
way, and what breaks without it.

## What belongs in this repository

The installation, the two services, the sending scripts, the list of authorized
contacts, the tests and the operating documentation.

Not your mailbox, not your password, and not a guarantee that the person writing
is who they claim to be. That belongs to your mail provider, to your `.env` file
and to your own judgement about who gets in.

## If you want to..., read...

| If you want to... | Read |
|---|---|
| Prepare the mailbox without exposing passwords | [`MAILBOX_SETUP.en-US.md`](MAILBOX_SETUP.en-US.md) |
| Install Paynani | [`AGENTS.md`](../AGENTS.md) and [`INSTALL.md`](../INSTALL.md) |
| Integrate it with Hermes Agent | [`HERMES.md`](../HERMES.md) |
| Understand why it must not fail silently | [`DESIGN.md`](../DESIGN.md) |
| Migrate from agenteiamail | [`MIGRATION.md`](../MIGRATION.md) |
| Remove Paynani | [`UNINSTALL.md`](../UNINSTALL.md) |
| See what changed per version | [`CHANGELOG.md`](../CHANGELOG.md) |
| Authorize senders | `roster.md` and [`roster.md.example`](../roster.md.example) |
| Send mail from the safe boundary | [`scripts/send.sh`](../scripts/send.sh) |

## Keeping it up to date

The installed version is in [`VERSION`](../VERSION), and the agent is told which
one it is running at the start of every session, along with whether a newer one
exists.

You can ask the same thing directly:

```bash
scripts/version.sh
```

It reads the published version from this repository's tags, so no account or
token is involved, and it says clearly when it could not reach the network
instead of calling an installation current just because nothing contradicted it.

Updating is [`UPGRADE.md`](../UPGRADE.md), and what changed between two versions
is in [`CHANGELOG.md`](../CHANGELOG.md). Read the changelog first: now and then a
version needs more than a `git pull`, and the way skipping it fails is a service
that works until the next reboot.

## Languages

`README.md` is the Spanish (MX) source. The maintained translations are:

- [`i18n/README.en-US.md`](README.en-US.md);
- [`i18n/README.es-ES.md`](README.es-ES.md);
- [`i18n/README.fr-FR.md`](README.fr-FR.md);
- [`i18n/README.pt-BR.md`](README.pt-BR.md).

There is no `i18n/README.es-MX.md` and there should not be: the source page is
already the es-MX version.

## The property everything else serves

**Never fail silently.** Latency was the easy problem: it was solved in an
afternoon as soon as the server could announce mail on its own. Everything else
here exists because the expensive failure is not being slow, it is **saying
confidently that there is no new mail while blind**.

That is why the last message seen is saved one at a time, why every connection
checks that the mailbox is still the same one, why the error log is watched
alongside the event log, and why starting a session asks whether the service is
really running. [`DESIGN.md`](../DESIGN.md) explains each of them and what breaks
without it.

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

<sub>Translated from [`README.md`](../README.md), which is the source of truth. Where this contradicts the Spanish (MX) original, **the Spanish wins**, and say so, because it means this translation has fallen behind.</sub>
