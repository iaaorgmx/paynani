# The setup page

A form that collects the seven mailbox settings, signs in to the mail server to
confirm they work, and, only if the server accepts the account, writes
`.env` at the top of the clone.

That is the same file a power user writes by hand before running the install
prompt, and its absence is what tells the agent no mailbox has been configured
yet. Both routes end at one file, so "is this set up?" has one answer.
`.env` at the top of the clone, where the listener and `scripts/send.sh` look by
default, is symlinked at it afterwards.

**Nothing is written unless the account authenticates.** A configuration that
does not sign in is not a configuration, and writing one would leave the agent
with a file that looks finished and a mailbox it cannot open.

It exists because everything else in this repository assumes a terminal, and the
person who owns the mailbox often does not have one. Step 1 of `MAILBOX_SETUP.md`
(create a file at a path, in a format, with the right permissions) is the step
that stops people, and it is also the step that must not be done for them by
handing the password to an agent in a chat.

## Running it

The agent runs this:

```bash
scripts/setup_web.sh          # or: scripts/setup_web.sh 8766
```

It prints a link with a one-time key. The human opens the link, fills in the
form, and closes the tab. The script stops on its own once the file is written.

If the agent is on a machine the human is not sitting at, the link still works,
they forward the port from their own computer first:

```bash
ssh -L 8765:127.0.0.1:8765 user@that-host
```

Then open the same `http://127.0.0.1:8765/…` link locally. The page is never
exposed to a network in either case.

## Requirements

PHP 8.1 or newer, CLI only. No composer, no framework, no database. The only
JavaScript is `assets/lang.js`, twenty lines that switch language when the
selector changes; everything the page does works without it. On Ubuntu:

```bash
sudo apt-get install -y php8.3-cli
```

The page uses only the standard library: `stream_socket_client` for the mail
checks, `session` for state. If `php -v` works, so does this.

## Why it is safe to put a password into it

This is a web form that collects a mail password, which is a shape worth being
suspicious of. Five things make it a local configuration tool rather than an
exposure:

**It only answers the loopback interface.** `scripts/setup_web.sh` binds
`127.0.0.1`, and `webapp/lib/guard.php` independently rejects any request whose
`REMOTE_ADDR` is not loopback. Starting the server bound to `0.0.0.0` by mistake
therefore still does not serve the form to anyone. An SSH tunnel arrives as
`127.0.0.1`, so the remote case is unaffected.

**It requires a key that only the terminal saw.** A fresh random token per run,
compared with `hash_equals`, stored at mode `600` and deleted when the script
exits. Old links stop working the moment the server restarts.

**The key leaves the URL immediately.** The built-in PHP server logs every
request line, so a token that stayed in the address bar would be written to disk
on every click. The first valid request moves it into the session and redirects
to a bare URL. The log itself is mode `600`, outside the repository.

**The password is never rendered back.** It is read from a POST body, held in the
server-side session between the check and the save, and dropped once written. It
is never placed in a `value` attribute, a URL, or a log line, so it is not in
the page source, the browser cache, or a screenshot of the screen.

**The file is written the way the rest of the repo expects.** Mode `600`,
directory `700`, written to a temporary file and renamed so an interrupted write
cannot leave a half-file. Where the path is a symlink (the arrangement
`INSTALL.md` §3 recommends), it writes *through* the link rather than replacing
it, which would otherwise strand the listener on a file nobody updates.

## Telling people where to find their settings

The form carries the instructions, because the person filling it in has nowhere
else to look. cPanel comes first: mail that arrived with web hosting is the
common case, and cPanel already publishes the exact values under *Email Accounts
→ Connect Devices → Mail Client Manual Settings*, in a Secure SSL/TLS column that
people miss next to the non-SSL one.

Then Gmail, Outlook, Zoho and Fastmail, each with the caveat that actually
stops them, which is almost always an app password rather than a wrong server
name. It is a `<details>` block, so it collapses on its own with no script involved.

## The language it speaks

The person filling this form is not always the person who runs the agent, and is
not always the person who chose the language the rest of the install speaks. They
are handing over a mailbox password, so they get to read what they are agreeing
to in their own language.

A selector sits next to the title, offering the same five languages the
documentation is translated into, with **Español (MX)** selected by default.
Everything the page can say is translated with it: the form, the provider help,
the field validation, the live check's step-by-step report, and the three refusal
screens in `guard.php`.

**Switching does not lose what has been typed.** The selector and its button
belong to the main form through the `form=` attribute even though they sit above
it, so changing language posts the whole form and the fields come back filled.
That submit carries `formnovalidate`, because without it the browser refuses to
send while the password box is empty, which would mean nobody could change
language until they had finished the form.

**The selector switches on change, and degrades to a button.** That needs a
script, so the policy carries `script-src 'self'`: same-origin files only, no
`'unsafe-inline'`, no `'unsafe-eval'`, no remote origin. Inline handlers stay
forbidden, which is the part that matters — a string injected into this page
still cannot execute. The one file allowed is `assets/lang.js`.

The page ships a real submit button and the script hides it on load. That is
deliberately not a `<noscript>` fallback: a script blocked by CSP still counts as
scripting being enabled, so `<noscript>` would render nothing and leave a dead
selector. This way, if the script does not run for any reason, what is left on
screen is a button that works. The failure mode is one extra click.

**The caret is drawn in CSS, not loaded as an image.** The policy does not
declare `img-src`, so it falls back to `default-src 'none'` and a `data:` URI is
blocked without a word — which is exactly what happened first, leaving a control
with nothing to mark it as a dropdown. Two rotated borders need no permission.

Catalogues are flat `key => string` arrays in `webapp/i18n/`. A key a translation
is missing falls back to `es-MX` rather than rendering blank, so a half-finished
catalogue degrades to a mixed page instead of an empty one. `es-MX` is the source
language; every other file is translated from it and carries exactly the same
keys.

## What the check does

It opens a real connection to both servers and signs in, then signs straight out.
It does not read, send, or change anything. Passing it is the condition for the
file being written at all.

The check exists because the failures this project actually sees do not look like
mistakes in the file:

- A host name that resolves but is not on the server's TLS certificate. The
  listener sees this as a network error, so it retries forever with `connection
  lost` and nothing naming the cause. The form says the certificate is not issued
  for that name.
- Port 143 instead of 993. The listener opens IMAP over TLS immediately, so 143
  cannot work; the form refuses it by name rather than letting it fail later.
- A password that works on the provider's website but not over IMAP, because the
  account needs an app password. The form says so when the server refuses.
- A server with no `IDLE` capability, which this whole design depends on. Asked
  after authenticating, because many servers only advertise it to a signed-in
  session.

A port number typed into a host field is caught before any connection is made,
that is the one mistake this file format cannot survive, and `.env.example`
documents it as the schema trap it is.

## Files

```
webapp/index.php        the form, the report, and the confirmation
webapp/lib/guard.php    loopback check, one-time key, CSRF, headers
webapp/lib/validate.php field checks, each one a mistake seen in the wild
webapp/lib/probe.php    live IMAP and SMTP sign-in
webapp/lib/envfile.php  writing the resolved credentials file, and the symlink
webapp/lib/i18n.php     which language this render speaks, and t()/th()
webapp/i18n/*.php       one flat array of strings per language
webapp/assets/app.css   no webfonts: this host may have no internet route
webapp/assets/lang.js   switches language on change; the button works without it
scripts/setup_web.sh    generates the key, serves the page, stops when saved
```

## What it deliberately does not do

**It does not install anything.** It writes one file. Himalaya, the systemd
units, the roster and the verification checklist are the agent's job, and
`INSTALL.md` is where they live.

**It does not decide anything.** It writes credentials. Whether the mail server
accepts them is the mail server's answer, not the form's opinion.

**It does not touch `roster.md`.** Who the agent may write to, and whose mail it
may act on, is a decision made by a human in a text file, not through a web form
that anyone with the link could reach.

**It is not a service.** It runs while someone is filling it in and then stops.
Nothing here is meant to stay listening.
