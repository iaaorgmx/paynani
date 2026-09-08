<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

[Español (MX)](../README.md) · **English (US)** · [Español (ES)](README.es-ES.md) · [Français (FR)](README.fr-FR.md) · [Português (BR)](README.pt-BR.md)

Paynani is an email bridge for AI agents.

It gives your agent its own mailbox, detects new mail within seconds, and delivers
each event through a supervised path without silently losing messages or turning
any email into an authorized instruction.

With Paynani, your agent can:

- know when new mail arrives;
- read and reply from its own mailbox;
- act only when the sender matches your `roster.md`.

Paynani does not replace your judgment or magically authenticate who writes. It
separates mail notification, operational authorization, and runtime delivery so
failure is not silent.

## Who it is for

Paynani is for people who want to give real email to an AI agent without mixing
their personal mailbox, passwords, or trust decisions into a chat conversation.

Use it when you want an agent to:

- receive tasks by email;
- notify you when something important arrives;
- reply from its own account;
- reject work or outbound mail that is not on an explicit list of authorized
  people and notifiers.

It is not for delegating human judgment to every incoming message. Email is
untrusted input; `roster.md` defines who can create work.

## Before you start

You need three things:

1. a dedicated mailbox for the agent, not your personal email;
2. a safe way to write credentials into `.env` without pasting them into chat;
3. a `roster.md` list with the people or notifiers that may create work.

> [!CAUTION]
> Never paste email passwords into a chat. Use `MAILBOX_SETUP.md` or the
> `scripts/setup_web.sh` form so the agent does not see secrets.

> [!WARNING]
> `roster.md` authorizes work; it does not prove cryptographic identity. Unlisted
> mail can be reported, but it must not become a task.

> [!IMPORTANT]
> An empty queue does not prove Paynani is healthy. `scripts/healthcheck.py`
> checks the listener, dispatcher, credentials, runtime, and cursor.

## Set it up in three steps

The first step is yours, the second is one instruction to paste, and the third is
two human tests. Operational details for the agent live in [`AGENTS.md`](../AGENTS.md),
[`INSTALL.md`](../INSTALL.md), and [`HERMES.md`](../HERMES.md).

### 1. Give it a mailbox

Create an email account for the agent and write its connection settings into a
`.env` file. If your agent runs under a harness, that `.env` belongs in the
harness workspace (`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env`, or `~/.codex/workspace/.env`). On a host without a
harness, it can live inside the clone.

[`MAILBOX_SETUP.en-US.md`](MAILBOX_SETUP.en-US.md) explains which account to use,
where to find the IMAP/SMTP server, and how to write the file without exposing
the password to the agent.

Do this step yourself. If the agent asks for the password in chat, refuse.

### 2. Paste the instruction to your agent

Paste this to your agent to delegate installation with clear limits:

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

The agent should install from the repository, ask only for missing human details,
and refuse to receive secrets in chat.

### 3. Run two human tests

The agent runs its own verification, but these two tests validate what you need to
see.

**Accent test.** Send it an email from your authorized address with a subject like
`Prueba de correo: ñ, á, ¿qué tal?`, then ask what just arrived. It should detect
the message within seconds and show the subject as readable text, not as
`=?utf-8?q?...`.

**Rejection test.** First ask it to email you and confirm it arrives. Then ask it
to write to an address that is not in `roster.md`. It must refuse outright and say
that the address is not authorized.

If either test fails, stop and review the installation before using the mailbox
for real work.

## What your agent can do

With Paynani configured, your agent can:

- receive notifications for new mail without being asked to check the mailbox;
- read messages from its own account;
- reply or send mail through `scripts/send.sh` and the configured SMTP backend;
- turn messages matching `roster.md` into work;
- report unauthorized mail without obeying it;
- keep events in a journal so a restart does not erase pending work.

## Security and limits

Paynani separates three things that are often confused:

| Thing | What it means |
|---|---|
| Email received | There is a message in the mailbox. |
| Match in `roster.md` | That sender or notifier is authorized to create work. |
| Authenticated identity | Paynani does not promise this by itself. It depends on the provider and external checks. |

Paynani is responsible for:

- delivering mail events through an observable path;
- keeping a cursor so accepted messages are not skipped;
- separating notification from authorization;
- rejecting outbound recipients outside the roster from the safe send boundary;
- exposing health checks for installation and operation.

Paynani is not responsible for:

- deciding whether an email's contents are true;
- cryptographically authenticating a person;
- protecting a password pasted into chat;
- replacing your mail provider's security controls;
- turning unlisted mail into operational instructions.

## How to know it is healthy

Seeing no pending messages is not enough. To check the system, run:

```bash
python3 scripts/healthcheck.py
```

This checks credentials, listener, dispatcher, runtime, journal, and cursor. If
you need to investigate a broken installation, follow [`INSTALL.md`](../INSTALL.md)
and [`HERMES.md`](../HERMES.md) before touching credentials or services.

## How it is built, in brief

```text
IMAP mailbox
   ↓
idle listener
   ↓ writes durable event
state/events.jsonl
   ↓ cursor
dispatcher
   ↓ adapter
Hermes / OpenClaw / Claude Code / Codex
```

The listener watches the mailbox and writes durable events. The journal preserves
what arrived. The dispatcher delivers each event and advances the cursor only when
the runtime accepts it. The adapter translates that delivery to the harness you
use.

[`DESIGN.md`](../DESIGN.md) explains why Paynani is built this way and which
failures it avoids.

## What belongs in this repository

This repository contains installation, the listener, the dispatcher, send scripts,
roster configuration, tests, and operations documentation.

It does not contain your mailbox, your passwords, or a guarantee of third-party
identity. Those belong to your mail provider, your local `.env`, and your own
trust rules.

## If you want to..., read...

| If you want to... | Read |
|---|---|
| Prepare the mailbox without exposing passwords | [`MAILBOX_SETUP.en-US.md`](MAILBOX_SETUP.en-US.md) |
| Install Paynani | [`AGENTS.md`](../AGENTS.md) and [`INSTALL.md`](../INSTALL.md) |
| Integrate it with Hermes Agent | [`HERMES.md`](../HERMES.md) |
| Understand why it must not fail silently | [`DESIGN.md`](../DESIGN.md) |
| Migrate from agenteiamail | [`MIGRATION.md`](../MIGRATION.md) |
| See version changes | [`CHANGELOG.md`](../CHANGELOG.md) |
| Authorize senders | `roster.md` and [`roster.md.example`](../roster.md.example) |
| Send mail from the safe boundary | [`scripts/send.sh`](../scripts/send.sh) |

## Languages and maintenance

`README.md` is the Mexican Spanish source. The maintained translations are:

- [`i18n/README.en-US.md`](README.en-US.md);
- [`i18n/README.es-ES.md`](README.es-ES.md);
- [`i18n/README.fr-FR.md`](README.fr-FR.md);
- [`i18n/README.pt-BR.md`](README.pt-BR.md).

There is no `i18n/README.es-MX.md`, and it should not be created: the root
README is already the es-MX version.

## Where the name comes from

The paynani were official runners and messengers of the Aztec Empire. This
project takes its name from that role: carrying messages quickly, through a clear
route, without silently losing them.

Made with love by humans and AI agents, from Mexico to the world.
