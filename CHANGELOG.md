# Changelog

## Sin publicar

Todo lo de abajo salió de la primera prueba de campo de 0.1.0
([#1](https://github.com/iaaorgmx/paynani/issues/1)), en un host OpenClaw real
que no era una máquina virgen.

- **`healthcheck.py` reportaba `healthy: true` en instalaciones que no podían
  enviar ni actuar sobre ningún correo**
  ([#6](https://github.com/iaaorgmx/paynani/issues/6)). Nunca abría `roster.md` ni
  miraba la configuración de Himalaya, así que ninguna de sus condiciones tocaba
  la lista de autorizados ni el cliente con el que se envía.

  Ahora son problema, no advertencia: `roster.md` ausente, `roster.md` sin
  ninguna dirección, y la falta de un bloque `[accounts.paynani]` en la
  configuración de Himalaya. Las tres dejan cada unidad activa, cada cola vacía y
  cada bitácora en calma mientras el correo no se mueve, que es exactamente la
  falla que este proyecto existe para no tener.

  El roster se lee con `roster.roster_addresses`, la misma función del listener,
  para que esta herramienta no pueda reportar una lista que el listener no ve. El
  nombre de la cuenta se escribe en `send.sh` y en `healthcheck.py` por separado
  —uno es shell y el otro Python— y `scripts/test_roster_agree.sh` los amarra:
  si se separan, esta comprobación buscaría una cuenta con la que nadie envía.

  Dos personas llegaron al mismo punto ciego el mismo día por instancias
  distintas: un roster vacío en un clon limpio, y una cuenta de Himalaya faltante
  en el host de la prueba de campo.

- **`preflight.py --help` abría una conexión IMAP en vivo en lugar de imprimir
  ayuda** ([#7](https://github.com/iaaorgmx/paynani/issues/7)). El script no
  procesaba argumentos: cualquier bandera se ignoraba en silencio y corría la
  comprobación completa. `--help` es justo la bandera que alguien usa cuando
  **no** quiere ejecutar todavía. Ahora `-h` y `--help` imprimen la cadena de uso
  y salen con `0` antes de tocar la red, y cualquier otro argumento se rechaza con
  `2` en vez de ignorarse.

- **`UNINSTALL.md` §2 no quitaba las credenciales en un host con harness**
  ([#5](https://github.com/iaaorgmx/paynani/issues/5)), que es la mayoría.
  Regresión introducida en `a7b1040`: el `rm -f .env` desde dentro del clon no
  borra nada cuando la contraseña vive en `~/.openclaw/workspace/.env`. Un
  procedimiento anunciado como destructivo que no borra lo que dice borrar deja a
  quien entrega una máquina creyendo que quitó la contraseña del buzón. Ahora el
  paso empieza por resolver la ruta con `python3 harness/paths.py env` y distingue
  el archivo del harness —del que solo se quitan las claves de esta instalación—
  del `.env` del clon, que sí se va entero.

- **El README describía la instalación como más pequeña de lo que es**
  ([#2](https://github.com/iaaorgmx/paynani/issues/2),
  [#3](https://github.com/iaaorgmx/paynani/issues/3),
  [#4](https://github.com/iaaorgmx/paynani/issues/4)). Decía «un servicio de
  usuario de systemd» donde una instalación completa deja cuatro unidades;
  ubicaba las credenciales en `<clon>/.env`, que en un host con harness ni
  siquiera existe; y listaba `<clon>/hermes/` sin condicionarlo a Hermes, en una
  sección titulada «Rutas en esta máquina» que se lee como inventario. Las tres
  corregidas, también en las cuatro traducciones.

- **Nada advertía que un contacto puede escribir desde una dirección distinta a
  la que se le escribe** ([#8](https://github.com/iaaorgmx/paynani/issues/8)).
  `roster.md.example` explicaba que la coincidencia es contra `From`, que es
  correcto, pero quien llena el archivo por primera vez escribe naturalmente la
  dirección a la que va a escribir, que puede ser la única que conoce. Cuando no
  coinciden, el correo llega, se registra y nunca se etiqueta `roster`, que se lee
  igual que si nadie hubiera escrito. `roster.md.example`, `INSTALL.md` §7 y
  `AGENTS.md` paso 7 ahora dicen que hay que preguntar las dos cosas, y que un
  contacto puede necesitar más de una fila.

## 0.1.0

Paynani se bifurca de [agenteiamail](https://github.com/julianflores/agenteiamail)
en la versión 1.9.1 y arranca aquí su propia numeración. Upstream sigue su
camino; a partir de este punto son dos productos distintos.

Todo lo que está debajo de esta entrada es la historia de agenteiamail, y se
conserva porque es la historia de este código y porque sus enlaces a issues
siguen resolviendo contra aquel repositorio. Nada de eso describe una versión de
Paynani.

Lo que cambió en la bifurcación misma:

- **Renombrado completo.** Variables de entorno `PAYNANI_*`, unidades systemd
  `paynani-*`, agentes de arranque `com.paynani.*`, el bloque `[accounts.paynani]`
  de Himalaya y la ruta Hermes `/webhooks/paynani-roster`. El renombrado es lo que
  permite que los dos productos corran en la misma máquina sin compartir
  credenciales, unidades ni la marca del último UID.

  Los identificadores de ruta de Hermes se derivan de la URL del webhook, así que
  son distintos a los de agenteiamail. Una ruta registrada para uno no es una ruta
  para el otro.

- **Se eliminó la disposición anterior al raíz único y su migración.**
  `legacy_layout()`, los inventarios de marcadores, `install.sh --migrate` y la
  transacción de migración ya no existen en ninguno de los cuatro lenguajes que
  los implementaban. Paynani no tiene instalaciones anteriores al raíz único, y
  conservar la detección solo le daría una manera de adoptar la configuración y el
  estado de una instalación viva de agenteiamail.

  `scripts/tree_digest.py` y `scripts/durable.py` se fueron con ella; la migración
  era su único consumidor.

- **`roster.md` es el único nombre del roster.** El respaldo a `roster.txt` servía
  a instalaciones anteriores a ese renombrado, y Paynani no tiene ninguna.

- **El español (MX) es el idioma principal y la fuente de verdad** de la
  documentación para humanos: `README.md`, `MAILBOX_SETUP.md`, `UNINSTALL.md` y el
  formulario web de configuración. Las versiones en inglés, español (ES), francés
  y portugués viven en `i18n/` y son traducciones. La documentación dirigida a
  agentes — `AGENTS.md`, `INSTALL.md`, `UPGRADE.md`, `HERMES.md` — y el código
  fuente siguen en inglés.

  El inventario de unidades en `UNINSTALL.md` nombraba `watch.service`, que dejó de
  existir cuando se renombró a `dispatch.service`. Corregido en ambos idiomas.

## Unreleased in agenteiamail at the fork point

- **`scripts/healthcheck.py` now says when roster mail was delivered and nothing
  was sent after it**
  ([#125](https://github.com/julianflores/agenteiamail/issues/125)). Every other
  check here asks whether mail can move; this one asks whether the loop closes.

  It was unanswerable until four days ago. The record of what came in has always
  existed, and [#117](https://github.com/julianflores/agenteiamail/issues/117)
  shipped the record of what went out in 1.9.1 — so the comparison became
  possible and nothing was reading it. A live OpenClaw host took three roster
  messages between 16:11 and 17:08, answered none of them for six hours, and
  every check this project offered reported a healthy install, correctly.

  **A warning and never a failure.** Delivery working is what makes it worth
  saying at all, and two different things produce the same shape: the agent was
  told and did not reply, or nothing was attached to be told
  ([#108](https://github.com/julianflores/agenteiamail/issues/108)). The check
  reports the shape and names both readings rather than picking one. Mail still
  queued is not counted against the agent, non-roster mail is never counted at
  all, and a grace window (`HEALTH_REPLY_GRACE`, one hour) keeps a reply that is
  still being written from being accused.

  It also reads `sent.log.1`: `rotate_logs.py` rotates every `*.log` in the state
  directory, `sent.log` included, so reading only the live file would report a
  host that sent mail yesterday as never having sent anything.

## 1.9.1 — 2026-08-26

**The session-start hook failed on every healthy Claude Code host.** If you run
this on Claude Code, upgrade. Everything else here is tests and documentation.

- **`harness/session_start.py` emitted `"systemMessage": null`** when it had
  nothing to say, and Claude Code rejects that payload with
  `Hook JSON output validation failed — (root): Invalid input`, discarding the
  whole output: no replay of mail that arrived while nothing was running, no
  watch command, no byte offset. The key is now omitted rather than sent as null
  ([#104](https://github.com/julianflores/agenteiamail/issues/104)).

  The failure was inverted, which is how it survived two releases. Every branch
  that fills `systemMessage` is a branch where something is broken — listener
  down, dispatcher down, dispatcher reporting errors — so the hook worked on
  every unhealthy install and failed only on a healthy one with mail waiting,
  which is the single case it exists to serve. The first Claude Code host saw it
  work on day one because its dispatcher was still logging errors from a
  crash-loop; the next session, after that install was repaired, got nothing at
  all. **Fixing the install is what exposed it.**

  Found by running the acceptance test nobody had run — #78's criterion 6, which
  the PRD had called *"the test that distinguishes this runtime from the other
  two and the one most likely to fail"*, in bold, a week before it failed.

  The offset held throughout. The hook failed for a day without consuming
  anything, so nothing was lost and the next session could still be told —
  `session_start.py` chooses repetition over silence deliberately, and that
  choice held against a fault nobody had anticipated.

### What the tools now admit they did not do

Four separate places where something reported success while quietly checking
less than it appeared to. They are one habit, not four bugs.

- **`scripts/version.sh --line` called an untagged install `(latest)`**
  ([#64](https://github.com/julianflores/agenteiamail/issues/64)). Its three
  branches were unknown, out of date, and a catch-all; ahead-of-tag fell into the
  catch-all. The long report had always described it correctly, and `--line` is
  the form that gets read — it feeds the session-start hook and
  `healthcheck.py`'s version field.
- **`scripts/test_paths.sh` dropped every PHP assertion when `php` was absent**
  and still said `0 failed`
  ([#90](https://github.com/julianflores/agenteiamail/issues/90)). 271 with php,
  225 without, nothing in the verdict to tell them apart. It now reports
  `46 skipped (no php)`. A php-less host still passes, deliberately: php is not
  a prerequisite for running this, only for the setup form.
- **`test_install.sh` and `test_migrate.sh` were skipped on macOS by the
  tester's judgement rather than by the suites saying so**
  ([#101](https://github.com/julianflores/agenteiamail/issues/101)). They now
  announce it themselves and exit 0, because a macOS host is supported and the
  rule is not *be Linux* but *do not claim to have checked what you did not
  check*.
- **Nothing recorded what was sent**
  ([#117](https://github.com/julianflores/agenteiamail/issues/117)).
  `scripts/send.sh` now appends one line per send to `state/sent.log` —
  timestamp, recipient, subject, message-id, no bodies. Himalaya saves no copy
  unless asked, and sending is SMTP, which has no Sent folder at all; a copy
  there is a separate IMAP `APPEND`. So there was no record anywhere by default,
  and an agent asked whether it had sent something searched its entire mailbox
  and could not tell.

### One rule, five statements, now mechanically pinned

`HARNESS_ROOTS` is written down in `harness/paths.py`, `scripts/envpath.sh`,
`webapp/lib/envfile.php` and two documentation tables. 1.8.0 updated one of them.
`scripts/test_paths.sh` pinned the first three; `scripts/test_docs.py` now pins
the last two, failing in both directions — an undocumented runtime and a
documented-but-unimplemented one
([#95](https://github.com/julianflores/agenteiamail/issues/95)).

The same shape produced #91, so the address-extraction rule got the same
treatment: `send.sh`'s awk moved into `scripts/roster_extract.sh`, which the send
path and the test both call, checked against `roster.py` on five roster shapes
including CRLF and reordered columns
([#98](https://github.com/julianflores/agenteiamail/issues/98)). A test that
reimplements the rule is a third copy of it.

### Documentation that was describing a different program

- **Catch-up is Claude Code's, and the other runtimes need none**
  ([#79](https://github.com/julianflores/agenteiamail/issues/79)). `INSTALL.md`
  told OpenClaw operators to maintain the output payload of a program their
  runtime never runs. On a push runtime the queue is the catch-up: the cursor
  moves only once the runtime accepts, and *"a session not yet up"* is retryable.
  Claude Code cannot borrow that because appending to a spool always succeeds.
- **`AGENTS.md` stopped a macOS install at step 1**
  ([#110](https://github.com/julianflores/agenteiamail/issues/110)) by testing
  for systemd unconditionally — three days after 1.9.0 made macOS supported.
  Step 1 now branches; `UPGRADE.md` gained the launchd half of a trap it already
  documented for systemd.
- **`DESIGN.md` described one runtime and one supervisor**
  ([#68](https://github.com/julianflores/agenteiamail/issues/68)). It now states
  the delivery boundary for all three — what `ACCEPTED` means to each adapter and
  what it does not prove — and why supervision inverts on macOS. The honest form
  of the guarantee is that **mail is never lost before the runtime takes it, and
  the moment it is taken is recorded**; everything after that belongs to the
  runtime, and [#108](https://github.com/julianflores/agenteiamail/issues/108)
  records where OpenClaw's own boundary sits.

## 1.9.0 — 2026-08-25

**macOS is a supported host.** An OpenClaw agent on a Mac can now install and
supervise this the way a Linux one does, without WSL, Ubuntu, or a
`systemd --user` session. Written and proved on the only Mac in the fleet by the
agent that runs on it, against [#81](https://github.com/julianflores/agenteiamail/issues/81).

- **`scripts/install_macos.py` renders and converges two LaunchAgents** in
  `~/Library/LaunchAgents`, with `KeepAlive` and `RunAtLoad`, doing for launchd
  what the installer already did for systemd units.
- **`scripts/install.sh` delegates on Darwin**, which also disposes of a problem
  rather than fighting it: Apple ships bash 3.2, and the installer uses `declare -A`
  and `mapfile -d ''` in nine places. A fresh clone on macOS did not fail somewhere
  informative — it died at line 143 with `declare: -A: invalid option`, before any
  install logic ran at all. Moving the macOS path into Python means the question
  does not arise, instead of nine rewrites for a shell nobody wants to target.
- **`scripts/env_secret.py` prints one value from the env file**, so Himalaya's
  `password.cmd` reads the password at need and `config.toml` never holds it.
  It tolerates a UTF-8 BOM and CRLF, both of which have bitten this repository
  before.
- **The generated plists carry a deliberate `PATH`** — the OpenClaw binary's
  directory, Homebrew, then the standard system directories — and specifically do
  not append the installing shell's own `PATH`. The hand-written plists this
  replaced had frozen a per-run temporary directory into a service definition
  meant to outlive reboots.

### What the LaunchAgents do and do not promise

A LaunchAgent runs as the user, which is what a mailbox with a mode `600`
credentials file needs, and is tied to a login session. There is no macOS
equivalent of `enable-linger` that would keep it unprivileged and survive logout
both at once.

That is not a shortfall against the other runtimes, and it is worth writing down
rather than leaving to be rediscovered: **on every host this project currently
runs on, the listener's availability follows the user session.** A WSL host's
`enable-linger` keeps the units alive across a logout inside the Linux session,
but the whole session is down until Windows starts it. No supported host today
returns from a cold boot without a human, and a macOS one is no different. A
native Linux host would be, and none exists yet.

### A test that had never been run by anyone it applied to

`scripts/test_paths.sh` asserted "the repo root does not assume a harness" by
matching the resolved path against `*.openclaw*`. That fails on a clone at
`~/.openclaw/workspace/agenteiamail` — which is the location `README.md`
recommends — so the suite asserted that a documented install location was wrong.
It survived because nobody who had followed that line had run the suite. The
first host to do so was the Mac.

The assertion could not do what its name claimed either: where a clone sits and
how `repo_root()` derives its answer are unrelated, and matching the result
against a substring conflates them. It is replaced by one that copies `paths.py`
to an arbitrary path holding no harness name and requires `repo_root()` to
resolve from the file's own location — the property, rather than the spelling of
the answer. Removing it was right; removing it silently would not have been.

### Not covered

`scripts/test_install.sh` and `scripts/test_migrate.sh` exercise systemd and are
not a signal on macOS. They were skipped there by the tester's judgement rather
than by the suites saying so, which is
[#101](https://github.com/julianflores/agenteiamail/issues/101). Both were run on
Linux against this release.

## 1.8.1 — 2026-08-25

**1.8.0 could not send mail.** Every defect below was found within an hour by the
first Claude Code install ([#87](https://github.com/julianflores/agenteiamail/issues/87)),
on the first host that had never run this software before. Anyone who installed
1.8.0 and followed the documentation should upgrade.

- **`scripts/send.sh` still parsed the pre-1.8.0 roster format**, so every address
  in a `roster.md` table was refused and the agent could send to nobody
  ([#91](https://github.com/julianflores/agenteiamail/issues/91)). 1.8.0 rewrote
  the rule in `roster.py` — find the field containing `@` rather than the field
  after the last `|` — and left `send.sh` on the old one. On a markdown table the
  result is worse than the wrong field: rows end in a trailing `|`, so a greedy
  match consumed the whole line and yielded nothing at all.
- **Inbound and outbound disagreed about who was on the roster**, which is what
  made it quiet. Mail arrived, was tagged `roster` by the Python half, and the
  agent acted on it — and then could not reply to any of it. `REFUSED` reads like
  a roster nobody has filled in, and the message even says "Add it deliberately",
  pointing at a file where the address is already sitting.
- **`~/.claude` never reached the shell and PHP resolvers**
  ([#88](https://github.com/julianflores/agenteiamail/issues/88)). 1.8.0 added it
  to `HARNESS_ROOTS` in `harness/paths.py` and not to `scripts/envpath.sh` or
  `webapp/lib/envfile.php`, both of which carry a comment saying to keep all
  three in step. Everything that sources `envpath.sh` inherited the wrong answer,
  and on a live host that pointed the generated systemd unit's `--env` at a file
  that does not exist — the listener crash-looped, which is the outcome
  `install.sh`'s own comment says a fourth copy of the list would cause.
- **The two halves also disagreed on a CRLF roster**, which the fix for #91 would
  otherwise have preserved. `send.sh` stripped space and tab; `roster.py` strips
  all whitespace. `send.sh` already tolerates CRLF in `.env`, and says there that
  it "has bitten this repo" — same script, same hazard, one of the two handled.
- **`roster.md.example` shipped two real, working addresses**
  ([#89](https://github.com/julianflores/agenteiamail/issues/89)). The repository
  is public and `cp roster.md.example roster.md` is the documented step, so
  following the instructions handed two real people standing unattended authority
  on a stranger's install. That list carries two powers, per the template's own
  header: an address on it may be written to unattended, **and** mail from it is
  treated as instructions the agent carries out. A `From:` header is forged
  trivially. The rows are gone; the format stays in the header and the table
  headings, neither of which holds an `@`. `INSTALL.md` already promised this —
  "Until you add a line it is empty" — and was describing a file we were not
  shipping.

The tests that should have caught all of this were green throughout, which is the
part worth keeping.

- **`scripts/test_paths.sh` had no case for the runtime 1.8.0 added.** It asserted
  shell/Python/PHP agreement for OpenClaw, Hermes and two-harness hosts, reported
  `0 failed`, and never touched `~/.claude`. It now has a `claude harness` case
  mirroring the other two.
- **`scripts/test_roster.sh`'s fixture predated the format change**, still written
  as `Name | email` with no outer pipes and no `Type` column — so it exercised a
  shape the project no longer ships and never the one it does. It now carries
  five cases against the real template shape, including refusing `Human` as an
  address.
- **The shipped template is now asserted to authorise nobody**, resolved through
  `roster.py` rather than by grepping for `@`, because the parser is what decides
  who is allowed.
- **`scripts/test_paths.sh` still drops all PHP checks silently when `php` is
  absent** — 255 assertions with it, 211 without, `0 failed` either way. Not fixed
  here; it is [#90](https://github.com/julianflores/agenteiamail/issues/90). It is
  why the PHP half of #88 could be repaired on a host that never ran it.

Documentation, from the tester's recommendations.

- **`INSTALL.md` §1.1 checks user lingering** alongside systemd and `loginctl`.
  The installer already refused without it and named the exact command, so nothing
  failed wrongly; what was lost was a round trip, because an agent has no password
  and by the time the dry-run stops, the human who was just asked for credentials
  has gone.
- **`INSTALL.md` §3's harness table names Claude Code.** `AGENTS.md` has carried
  all three since 1.8.0. The paragraph directly beneath that table is the
  procedure that would have prevented #88 — add the root to all three files
  together, with `test_paths.sh` asserting they agree. It was published, then not
  followed, under a table that was itself not updated, with a promise about a test
  that had no case for the new root.

One rule stated in several places, kept in step by hand, is the cause of #88, #90,
#91 and the table above. Each is fixed as an instance;
[#95](https://github.com/julianflores/agenteiamail/issues/95) tracks the class.

## 1.8.0 — 2026-08-23

**Claude Code is a third runtime**, and the roster is `roster.md`. Everything
below shipped across #82, #83, #84 and #85.

- **`roster.txt` is now `roster.md`.** The template is `roster.md.example` and
  every document names the new file.
- **`roster.txt` still resolves when it is the only one present**, and this is
  the part that matters rather than the rename. Every install made before this
  has a `roster.txt`; resolving only the new name would empty the allowlist on
  upgrade, and an empty allowlist does not announce itself. Sending refuses
  everyone, every inbound message stops being tagged `roster`, and the agent
  quietly stops acting on mail it was supposed to act on — which is
  indistinguishable from nobody having written. `paths.py`, `send.sh` and
  `envpath.sh` all answer the same way, and prefer `roster.md` when both exist.
- **Markdown table rows parse**, now that the file is `.md`. A row ends in a
  pipe, and the old parser took everything after the last one — which yielded an
  empty string that was then discarded, silently leaving that person off the
  list. Outer pipes are stripped, separator rows are skipped, and an entry
  without an `@` is ignored rather than becoming an allowlist entry, which is
  what keeps a table's header row harmless.
- **The roster carries a `Type` column** — `Human` or `AI Agent` — and
  `roster.md.example` ships as a markdown table.
- **The address is now found by looking for it, not by counting columns.** Every
  earlier parser took the field after the last `|`, which held for
  `Name | email` and breaks the moment anything follows the address. With a
  `Type` column the last field is `Human`; taking it yields a non-address, the
  row contributes nobody, and that person is silently off the list. The parser
  picks the field containing an `@` and is indifferent to the columns around it,
  so an older `Name | address` line still works unchanged.
- **`Type` is informational and nothing branches on it.** Being on the list is
  the whole permission: a row is exactly as authorised whether it says `Human`,
  `AI Agent`, or nothing. `roster.py` says so where the column is parsed, because
  a reader who believes it is load-bearing will eventually edit it expecting
  something to change.
- `roster_entries()` reads rows back as `{name, address, type}` for anything that
  wants to display the list rather than match against it.
- `UPGRADE.md` says how to rename an existing file, and warns against keeping
  both: the resolver prefers `roster.md`, so an address added to a stale
  `roster.txt` beside it never takes effect and nothing says why.

Towards [#78](https://github.com/julianflores/agenteiamail/issues/78), the install
side. With this, a Claude Code agent can install by following `AGENTS.md`.

- **`scripts/install.sh --runtime claudecode`.** It requires no `claude` binary,
  because delivery is a file append and the binary is only used by the opt-in
  agent mode. Demanding it would refuse hosts this runtime works fine on.
- **The installer proves the spool by writing to it**, not by reading a mode bit.
  It also states what that does *not* prove: whether any session is reading is
  invisible from outside one, and the verification report says so in its own line
  rather than letting `result=accepted` imply an end-to-end path.
- **`scripts/claude_hook.py` registers the session-start hook by merging**, and
  Claude Code's `settings.json` is deliberately never a managed artifact. It is
  the operator's file and holds configuration this project knows nothing about,
  so converging it would eventually overwrite somebody's unrelated hooks. It
  appends rather than replacing the `SessionStart` list, is idempotent, backs up
  first, writes through a temporary file, and **refuses to touch a settings file
  it cannot parse** rather than rewriting one it could not read.
- **`healthcheck.py` reports the spool backlog as information, not as a verdict.**
  Unread bytes with no session open is this runtime's normal resting state. The
  stronger check first sketched for it — "unread bytes and no watch attached" —
  is not implementable honestly, so the output says what is true and names what
  it cannot see.
- `INSTALL.md` gains a Claude Code section and `AGENTS.md` step 4 points at it.

Towards [#78](https://github.com/julianflores/agenteiamail/issues/78), the session
side: the hook branch, the watch, and the design note.

- **A Claude Code session is told what it missed and how to start listening.**
  The session-start hook replays `session.spool` from the recorded offset and
  then names the exact watch command, including the byte offset it replayed
  through, so nothing falls in the gap between the hook finishing and the monitor
  attaching.
- **Arming the watch is what acknowledges the replay**, and the hook deliberately
  does not do it. The hook advancing the offset would claim an arming it cannot
  observe, and an agent that read the replay and never armed would lose that mail
  silently. The failure this chooses is repetition, which is visible.
- **`session_watch.sh` takes an exclusive lock.** `session_start.py` says that on
  every other runtime a session must never arm a watcher, because two consumers
  of one stream racing on one cursor duplicated events and corrupted the record
  of what had been seen. Claude Code cannot obey that rule and still receive
  anything, so the guard moved rather than disappeared: a second session refuses
  to arm instead of quietly halving the accuracy of both.
- **A spool shorter than the recorded offset replays from zero** rather than
  trusting it. It was truncated or replaced, and stepping over everything now in
  it is the failure that looks like a quiet mailbox.
- `DESIGN.md` gains *"Why one runtime pulls"*, which also starts closing #68.

Towards [#78](https://github.com/julianflores/agenteiamail/issues/78): Claude Code
as a third runtime. This is the runtime core — adapter, resolution and tests.
Installer support and the full documentation follow separately.

- **Claude Code delivers by inversion.** Nothing outside a Claude Code session
  can speak into it: there is no `claude system event`, and `claude -p --resume`
  starts a fresh headless turn rather than appearing in the session a human is
  sitting in. So where OpenClaw and Hermes are pushed to, this runtime comes and
  gets it. The adapter appends the rendered line to a spool that two session-side
  readers consume — the `SessionStart` hook for what arrived while nothing ran,
  and an armed `Monitor` for what lands next.
- **The spool is deliberately not named `*.log`.** `rotate_logs.py` rotates every
  `*.log` in the state directory, and rotation renumbers bytes underneath two
  readers that index by offset. A rotation between a hook replay and a monitor
  arming would resume at the wrong place — showing mail twice, or stepping over
  mail that was never shown, which is indistinguishable from a quiet mailbox.
- **One record is exactly one line.** A rendered notification can carry a line
  break, usually from a folded subject, and letting it through would make the
  monitor report one message as two and leave every later offset out of step. A
  test pins it; it caught this during development rather than in the field.
- **Spooled means durable, not seen**, and the code says so where it returns
  `ACCEPTED`. This is the same bargain the Hermes adapter makes with HTTP 202,
  with one difference worth remembering: Hermes always has something running to
  drain the queue, and here there may be no session for hours.
- **`~/.claude` joins `HARNESS_ROOTS`**, so credentials resolve from
  `~/.claude/workspace/.env` under the existing rule rather than a special case.
  It is deliberately **not** a `legacy_layout()` marker — a credentials path
  doing double duty as a layout marker is what caused #72.
- Optional `AGENTEIAMAIL_CLAUDE_MODE=agent` starts a headless run per event so
  mail can reach an agent with no session open. Off by default, because it
  widens what an inbound message can cause. The spool write happens either way,
  so a failed run can never lose an event.

Closes [#77](https://github.com/julianflores/agenteiamail/issues/77).

- **The installer says how to fix the PATH failure it stops on.** A fresh
  OpenClaw host reliably meets `openclaw executable not found in the systemd user
  PATH` during the install, and the message named the problem without naming the
  remedy. The remedy is in `INSTALL.md` §6, a section the agent has not reached:
  `AGENTS.md` step 4 points at `INSTALL.md` as a whole, and it is ~800 lines. Both
  `prereq_error` calls now carry the fix and the section title.
- **`AGENTS.md` step 4 warns that the installer can stop on harness wiring**, so
  the answer is discoverable before the failure rather than only after it.
- Found on the first fresh OpenClaw install of 1.7.0 (#74). The tester got past
  it by inventing a solution, which turned out better than the documented one and
  became #75. The next installer should not have to be that resourceful.

## 1.7.1 — 2026-08-21

Closes [#75](https://github.com/julianflores/agenteiamail/issues/75).

- **The documented fix for an unreachable `openclaw` no longer disappears on
  upgrade.** §6 told operators to pin `OPENCLAW` and `PATH` by adding
  `Environment=` lines to the installed unit. The installer converges all four
  units from the copies in `systemd/`, so that edit is drift and `--upgrade`
  removes it — leaving the dispatcher unable to reach `openclaw` again, every
  check in §7 still passing, and the only evidence in `state/watch.err.log`.
  The advice produced an install that broke later, for the exact reason the
  section tells you to stop suspecting.
- **`~/.config/environment.d/` is the documented mechanism now**, because it
  lives outside the converged artifacts and survives. The section also says that
  the file is only read when the user manager starts, and gives
  `systemctl --user set-environment` for applying it to the running one — a gap
  that made the file look ineffective on the host where it was first used.
- Pinning in the unit is still supported and now says how to do it correctly:
  uncomment the line in `systemd/agenteiamail-dispatch.service` in the clone,
  where convergence copies *from*, rather than in the installed copy. The
  template carries the same warning, since an operator reading the installed
  unit sees that comment and not this changelog.
- Found on the first fresh OpenClaw install of 1.7.0, by the tester having
  solved it a different way than the documentation prescribes.

Closes [#72](https://github.com/julianflores/agenteiamail/issues/72).

- **A credentials file is no longer evidence of an install.** A brand-new
  OpenClaw agent that followed the README — put your mailbox settings in your
  harness's workspace — landed in the pre-single-root layout, with config and
  state outside the clone, on a host where nothing had ever been installed.
  `~/.openclaw/workspace/.env` was doing double duty as both a credential
  location and the `legacy_layout()` marker, and the documentation change that
  made the harness workspace the recommended place turned "follow the
  instructions" into "get the old layout".
- **The marker was the odd one out all along.** `legacy_layout()` counts files
  this project has written — `install.manifest`, `runtime.env`, `idle.json`, the
  journal, the logs. The harness `.env` is written by the human or the harness.
  It was included because its presence used to correlate with an install made
  before this repository knew about other runtimes; making it the recommended
  location for a new one broke the correlation. Removed from the predicate in all
  three implementations.
- **A genuine pre-1.7.0 install is still found**, by the artifacts it actually
  has: the installer writes `install.manifest` and `runtime.env`, and a listener
  that has ever run leaves `idle.json` and logs. The case that stops being
  detected is the one that was never an install — a credentials file and nothing
  else. The legacy-layout test now proves its host with a UID baseline rather
  than with credentials, which is what made the conflation visible.
- Credential *resolution* is unchanged: the OpenClaw path stays in
  `HARNESS_ROOTS`, so those credentials are still read where they lie, in either
  layout.
- `DESIGN.md`'s account of why the predicate probes what it probes was written
  around the old behaviour and is corrected: credentials at a harness path with
  everything else in the clone is the ordinary arrangement, not a split-brain.

Closes [#70](https://github.com/julianflores/agenteiamail/issues/70).

- **The prompt a human pastes to their agent points at the harness workspace.**
  It said the mailbox was "already configured at `<clone>/.env`", which names one
  runtime's arrangement as though it were the only one and asserts a fact the
  human may not have established yet. It now tells the agent to *check* its
  settings in the workspace folder of its harness installation directory, which
  reads the same to a person and to an agent and stays true as runtimes are
  added. Changed in `README.md`, its inline Spanish copy, and all four
  translations together — a prompt that differs by language is four prompts.
- **The setup instructions now agree with that prompt.** They told the human to
  write credentials into the clone while the prompt sent their agent to the
  harness workspace — two places that both happen to work, which is how a
  convention quietly becomes optional. `README.md` step 1, `MAILBOX_SETUP.md`,
  `INSTALL.md` and the "what it changes on the machine" list now name the
  harness's workspace `.env` first and the clone as the answer for a host with no
  harness, in English and in all four translations. The Himalaya `password.cmd`
  examples stop naming a clone path they cannot know.

Closes [#67](https://github.com/julianflores/agenteiamail/issues/67).

- **The installer reads back the `runtime.env` it wrote.** A second run on a
  converged Hermes host demanded every value the installer had already recorded
  itself, and failed with `HERMES_NOTIFY_URL is required` — which reads as "this
  host was never configured" on a host that was configured, running and
  delivering mail. Re-running the installer is ordinary: it is what an upgrade
  changing a rendered path asks for, and that is exactly when this was found,
  while verifying the change below on the first Hermes host. Precedence is now an
  explicit flag, then the environment, then the recorded file, then fail. A host
  that has never converged has nothing to recall and fails exactly as before.
- **Recalled values are validated like supplied ones.** The recall happens before
  every argument check rather than after, so the file cannot become a way around
  validation. Both route-secret paths are recalled only when neither was given,
  so a supplied flag is never paired with a path the operator did not choose.
- **Each recalled value says where it came from**, as
  `inventory recalled=NAME from=PATH`. A value that appears from nowhere is worse
  than one somebody typed.
- Parsed as `KEY=VALUE` data and never sourced, undoing exactly the escaping that
  writes it. The file holds no secrets: the two route secrets are named by path
  and never by value.
Closes [#59](https://github.com/julianflores/agenteiamail/issues/59), the last
thing the first Hermes Agent install had to work around by hand.

- **A harness's credentials are read where the harness keeps them.** Every
  runtime keeps its agent's mail credentials in the workspace folder of its own
  installation directory — `~/.openclaw/workspace/.env`,
  `~/.hermes/workspace/.env` — and the resolver knew only the OpenClaw one. On a
  correctly provisioned Hermes host, `AGENTS.md` step 2 answered
  `NO CREDENTIALS` for a file that was one directory up, and the install was
  finished with a symlink nobody should have needed. The rule is now written as
  a **pattern** rather than a second hardcoded path: `HARNESS_ROOTS` plus
  `workspace/.env`, in `harness/paths.py`, `scripts/envpath.sh` and
  `webapp/lib/envfile.php`, which `scripts/test_paths.sh` asserts agree. Adding
  a runtime is adding a root and nothing else.
- **Only the credentials resolve there.** State, `runtime.env`, the manifest and
  `hermes/` still hang off the clone. That split is deliberate and is the one
  exception to "credentials and state cannot disagree": the harness owns that
  file, this project does not, and copying it to satisfy the single-root
  convention would put a second copy of a password on the disk.
- **An OpenClaw host is unchanged.** Its path is listed as an instance of the
  same rule, but it is also what `legacy_layout()` detects, so such a host still
  resolves into the split layout entirely — credentials *and* state — as it did
  before. Pinned by a test, because the failure it prevents is a live OpenClaw
  install quietly half-moving into the clone.
- **Two harnesses on one host adopt neither.** Two agents sharing a machine
  means either file could be the wrong mailbox, and a listener on the wrong
  mailbox is indistinguishable from a quiet one. The answer falls back to the
  file this install owns; `AGENTEIAMAIL_ENV` is how an operator says which.
- **A runtime's own config is still not a mailbox.** The rule matches
  `<harness-root>/workspace/.env` exactly, so `~/.hermes/.env` — Hermes' gateway
  token — is not adopted. That was already asserted; it now has its own case
  saying why, since the two are easy to conflate.
- `AGENTS.md` and `INSTALL.md` drop the symlink workaround they carried for one
  release and describe the behaviour instead.

## 1.7.0 — 2026-08-21

Documentation, from the first Hermes Agent install (#52) and the tester's report
@ateneabuffayhermes filed on #60. No code changes.

- **Where a harness keeps its credentials is written down.** Each runtime keeps
  its agent's mail credentials in the workspace folder of its own installation
  directory — `~/.openclaw/workspace/.env`, `~/.hermes/workspace/.env` — and
  `AGENTS.md` step 2 said instead that a new install of either harness keeps them
  inside the clone, which is untrue for Hermes. An agent that followed it on a
  correctly provisioned host was told `NO CREDENTIALS` and sent to re-enter a
  password already on disk. Step 2 now states the rule, names
  [#59](https://github.com/julianflores/agenteiamail/issues/59) as the reason the
  resolver can still disagree with it, and prescribes the symlink — never a copy,
  because a second copy of a password is a second thing to leak.
- **The Himalaya examples no longer hardcode an OpenClaw path.** All three
  `password.cmd` lines read `~/.openclaw/workspace/agenteiamail/.env`, which is
  the wrong runtime and a pre-single-root path besides. They now carry an
  unmistakable placeholder and point at whatever step 2 reported.
- **`mailbox.alias.inbox = "INBOX"` is in the v2 Himalaya example.** Without it
  the account is valid and `himalaya account check` passes while every
  `envelope list` fails — found on v2.1.0 during the first Hermes install. The
  neighbouring text now also says plainly that `account check` authenticates
  rather than reads a mailbox, so section 4.4 is the proof and this is not.
- **`HERMES.md` says a route is not live until the gateway restarts**, that the
  restart must come from a shell outside the gateway, and that Hermes refusing to
  restart itself from a tool subprocess is correct rather than a fault to work
  around. Skipping it leaves nothing listening on `HERMES_HEALTH_URL` and fails
  the installer's health probe on a correct configuration. This stopped the first
  install until an operator intervened.

Closes [#61](https://github.com/julianflores/agenteiamail/issues/61), found by
@ateneabuffayhermes on the first Hermes Agent install — she hit it, diagnosed it,
and patched her own clone to get past it.

- **`scripts/healthcheck.py` reads `runtime.env` itself.** The services are
  handed that file by systemd's `EnvironmentFile=`; a hand-run healthcheck was
  handed it by nothing, and the two runtimes do not notice that equally.
  `adapters/openclaw.py` detects its runtime by finding a binary on the host, so
  the manual command has always worked there. `adapters/hermes.py` detects its
  own by reading five `HERMES_*` variables out of the environment, so on a
  Hermes install the documented verification step reported *no runtime selected*
  while the services were delivering mail. The file is now parsed as `KEY=value`
  data — never sourced, values never printed, the exact inverse of the escaping
  `scripts/install.sh` writes — and layered *under* the real environment, so an
  explicit `AGENTEIAMAIL_RUNTIME` still wins. A missing file stays what it always
  was: an OpenClaw or manual install, not a fault.
- **"No runtime" and "this command cannot see the runtime" now read
  differently.** When nothing is selected and no `runtime.env` could be read, the
  failure names the path it looked for, because those two readings send the next
  person to different places.
- **The health output says which file configured the runtime**, so the answer
  can be traced to its source instead of inferred.

Closes [#57](https://github.com/julianflores/agenteiamail/issues/57) — the last of
the migration follow-ups, against acceptance criteria agreed with @apollohermesfl
before implementation rather than discovered during review of it.

- **Durability is an ordering now, and the ordering is pinned.** The previous
  version fsynced one temporary file beneath a comment claiming power-loss
  durability. `scripts/durable.py` owns the sequence — staged data before the
  manifest names it, the manifest rename before any service stops, each
  destination before its source is unlinked, each source's parent after, and the
  install root last so a reboot cannot resurrect a deleted legacy entry or a
  finished transaction. Each of those syncs was removed to confirm its own
  assertion fails.
- **Any exit after a service is stopped restores it.** A rollback used to leave
  the listener and dispatcher stopped while printing that the install was
  unchanged: the files were unchanged and the mail had stopped. The set to
  restore is recorded before the first stop and written into the transaction, so
  a unit the operator had deliberately stopped stays stopped and a resume in a
  different process still knows what to put back. A restore that fails names the
  unit, keeps the transaction for a retry, and exits nonzero.
- **Resume revalidates instead of inferring.** Committed destinations and
  surviving staged copies are checked against digests recorded in the
  transaction. A mismatch preserves every copy and the manifest and refuses to
  clean up.
- **Filenames inside the state tree are data again.** The digest that resume
  checks artifacts against was a `find | xargs -I{} sh -c` pipeline, which
  substitutes each pathname into shell program text — a file named
  `"; touch PWNED; #` in the state tree executed a command, and the state tree
  is a directory the migration copies wholesale.
  [`scripts/tree_digest.py`](scripts/tree_digest.py) computes it without a
  shell, and pins quote, newline and metacharacter names.
- **A resume keeps the pre-stop service set recorded in the transaction**
  instead of re-reading it from a host whose services it has already stopped.
  Re-reading returned an empty set and persisted it, destroying the only record
  of what had been running before the migration started.
- **Every migration failure-path test now asserts service state**, not only
  files — the check that would have caught the two defects above. `DESIGN.md`
  records the rule, along with its limit: `is-active` proves service state, not
  mail detection.

Follow-up to [#53](https://github.com/julianflores/agenteiamail/issues/53),
fixing three defects @apollohermesfl found reviewing
[#54](https://github.com/julianflores/agenteiamail/pull/54) after merge.
[#55](https://github.com/julianflores/agenteiamail/issues/55).

- **The layout predicate abandoned undelivered mail.** It probed four files; a
  legacy state tree holding an `events.jsonl` and no `idle.json` resolved into
  the clone and left the journal behind — mail that had arrived and had never
  been delivered, dropped with no error anywhere. It now inventories every file
  either legacy directory can durably own, with a one-marker-only test per
  entry. The "credentials and state cannot disagree" property is also restated
  as conditional on neither `AGENTEIAMAIL_ENV` nor `AGENTEIAMAIL_STATE` being
  set, which is what it always meant.
- **`--migrate` is a recoverable transaction.** It used to move each artifact
  with its own `mv` and, on a failure partway, tell the operator the install was
  split and had to be repaired by hand. Artifacts are now copied into staging on
  the destination filesystem, validated, and recorded in a durable manifest
  before anything is committed; the sources stay intact, so a rollback is a
  delete rather than a move that can fail for the same reason the move did.
  Interruption has exactly two recoverable states and rerunning `--migrate`
  resolves either. The services are stopped and **verified inactive** first —
  the previous `|| true` meant a failed stop was indistinguishable from a
  successful one, under a comment claiming the stop protected the move.
- **While a migration is unfinished, nothing pretends otherwise.**
  `scripts/install.sh` refuses every mode except `--migrate`, and
  `scripts/healthcheck.py` reports the install as between layouts and its other
  facts as unreliable.
- **An unverifiable git-hygiene check no longer reports as a pass.** On a
  deployment with no `.git` the installer could not check, said so once
  mid-inventory, and still finished `result=passed`. Hygiene is now a tri-state
  carried into the final report: a non-`.git` tree finishes
  `result=passed-with-unverified-control`.

**One install, one directory, and that directory is the clone.** An install used
to spread itself over three places — credentials and route secrets in
`~/.config/agenteiamail`, queue state and logs in `~/.local/state/agenteiamail`,
the roster in the clone — so backing it up, inspecting it or removing it meant
remembering all three. Everything it owns now lives inside the clone, which also
answers "install it wherever you want" without a flag: you clone where you want,
and the install is there.
[#53](https://github.com/julianflores/agenteiamail/issues/53).

Recommended clone locations, recommendations rather than checks:

| Runtime | Clone at |
| --- | --- |
| OpenClaw | `~/.openclaw/workspace/agenteiamail` |
| Hermes Agent | `~/.hermes/workspace/agenteiamail` |

- **The credentials file is `.env`**, at the top of the clone, mode `600`. State,
  logs, the journal and the cursor are in `state/`; `runtime.env`,
  `install.manifest` and `hermes/` sit beside them. The four unit files stay in
  `~/.config/systemd/user`, because systemd will not read them anywhere else.
- **The layout is decided by one predicate**, `legacy_layout()` in
  [`harness/paths.py`](harness/paths.py), rather than one decision per file.
  Deciding credentials and state separately produces a split-brain install — the
  listener reading a password from one layout and writing its UID baseline into
  the other — and that failure presents as a mailbox that has simply gone quiet.
- **`harness/rotate_logs.py` was the only consumer that could not be
  redirected.** Pointed at a directory the units no longer write to, it recreated
  that directory empty, matched no logs, printed nothing and exited 0 — so the
  weekly timer would have reported success indefinitely while the real logs grew
  without bound. It asks the resolver now, and
  [`scripts/test_rotate_logs.py`](scripts/test_rotate_logs.py) asserts both that
  it rotates in the right place and that it never creates the old one.
- **The units carry rendered absolute paths instead of `%h`**, which cannot
  express "wherever the clone is". `runtime.env` and the route secrets render
  from a separate placeholder, so a legacy install still renders correctly.
- **The installer refuses to write when git would expose the install.** Every
  runtime-owned path must be untracked and ignored before anything is written; a
  deployment with no `.git` is reported as unverifiable rather than refused.

### Upgrade actions

**Existing installs need no action.** An install made before this release keeps
its split layout, entirely and indefinitely — every tool resolves it correctly,
and an upgrade will never move it.

To move one into the clone, opt in. It stops the services while it works, and
refuses rather than half-moving on an occupied destination, a symlinked source,
or a file owned by somebody else:

```bash
scripts/install.sh --runtime openclaw --migrate --dry-run   # review the moves
scripts/install.sh --runtime openclaw --migrate             # then do them

python3 harness/paths.py env      # expect <clone>/.env
python3 harness/paths.py state    # expect <clone>/state
```

**`git clean -xdf` is now destructive on a live install.** It deletes ignored
files, which here means the mailbox password, both route secrets, `roster.txt`
and the UID baseline, in one command. Use `git clean -df`.

## 1.6.0 — 2026-08-19

Adds the supported, idempotent installer for OpenClaw and Hermes Agent runtimes,
including runtime-aware service generation and health checks, plus documentation
corrections for installation and upgrades.

### Upgrade actions

- Use `scripts/install.sh` as the supported installation and upgrade path. Run it
  with `--dry-run` first, review the plan, then rerun without `--dry-run`.
- Enable all three user units installed by the supported path:

  ```bash
  systemctl --user enable agenteiamail-idle.service
  systemctl --user enable agenteiamail-dispatch.service
  systemctl --user enable agenteiamail-logrotate.timer
  ```

- Generated units use
  `EnvironmentFile=-%h/.config/agenteiamail/runtime.env`. The leading `-` makes
  this runtime environment file optional, so existing manual installs continue
  to work without it.

## 1.5.0 (2026-08-18)

**One command that answers whether this install can do its job.** Until now the
only way to know was to read four files and two unit states and infer it, which
means in practice nobody knew: the failure this project exists to prevent is
exactly the one where every individual thing looks fine. FR8 of
[#35](https://github.com/julianflores/agenteiamail/issues/35).

- **[`scripts/healthcheck.py`](scripts/healthcheck.py)** reports the selected
  runtime and whether it can be reached, both service states, the listener's
  mailbox and position, the queue depth with the age of the oldest thing in it,
  a damaged record if there is one, the credentials path and its mode, and the
  installed version. `--json` for a script.
- **It exits nonzero when mail cannot be detected or delivered**, so it can be
  the thing an install is judged by rather than a page to read.
- **It asks about mechanisms, never about traffic.** An empty inbox is what a
  healthy install and a dead listener both look like. Every check here is
  phrased so that the second one fails.
- **It refuses to let reachability read as delivery.** Reaching a runtime proves
  the runtime answers; for a webhook runtime it says nothing about whether the
  route, its secret or its delivery target are right. Printed in place, because
  "health: ok" is the phrase people stop reading after.
- **A queue is only a fault when it is not moving.** Depth alone cannot tell a
  burst that arrived a second ago from a backlog nothing has touched since
  yesterday; the age of the oldest record is what separates them, and it is read
  from the record rather than the file's timestamp, which compaction disturbs.
- **What the runtime last said is recorded by the dispatcher**, in
  `delivery.json`: the last accepted event id, when, which runtime, and the
  adapter's own words verbatim. A health check cannot ask an adapter what
  happened an hour ago, and must never reconstruct it from a reachability check,
  because a gateway answering now says nothing about whether something accepted
  earlier was ever acted on. Where a runtime only acknowledges receipt, that
  distinction is the difference between "handed over" and "done", and only the
  first is ever known here.
- **That record holds an identifier and a sentence, never the mail.** No sender,
  no subject, no payload, no credentials, asserted rather than intended, at mode
  `600`.
- **It never prints a credential**, asserted rather than intended.
- `AGENTS.md` gains it as step 6, and as a standing rule: say "no new mail" only
  when something checked.

- **28 assertions in
  [`scripts/test_healthcheck.py`](scripts/test_healthcheck.py)**, each one about
  whether a failure that looks like nothing is reported as a failure.

---

## 1.4.0 (2026-08-18)

**Nothing assumes a harness any more.** The delivery half stopped knowing about
one in 1.3.0; the paths still did. A clone had to sit at
`~/.openclaw/workspace/agenteiamail` or the session hook silently did nothing,
and the setup form wrote credentials into `~/.openclaw/workspace/.env` on hosts
with no OpenClaw on them. FR6 of
[#35](https://github.com/julianflores/agenteiamail/issues/35).

- **One rule about where the credentials live**, in
  [`harness/paths.py`](harness/paths.py) with the shell half in
  [`scripts/envpath.sh`](scripts/envpath.sh): `AGENTEIAMAIL_ENV` if set, then an
  existing `~/.config/agenteiamail/env` (including the symlink older installs
  left there), then a legacy `~/.openclaw/workspace/.env`, then the neutral path
  for a new install. The listener, preflight, `send.sh` and the setup form all
  ask it rather than each keeping their own default.
- **An existing install keeps its credentials where they are.** They are read
  where they lie and never copied to a second location to satisfy a convention:
  a second copy of a password is a second thing to leak. Nothing is written into
  a harness's own `.env`, OpenClaw's or Hermes's.
- **The clone can be anywhere.** `harness/session_start.py` finds the repository
  from its own location instead of a hard-coded path. That failure was invisible
  by construction, since the hook swallows its own errors so a session is never
  blocked: a clone elsewhere produced no version line, no pending mail, and no
  complaint. `~/.local/share/agenteiamail` is the suggested default for a new
  install, and nothing requires it.
- **A different mail deployment on the same host is not adopted.** Only the two
  paths this project has itself written are ever looked at.

- **23 assertions in [`scripts/test_paths.sh`](scripts/test_paths.sh)**, which
  check the Python, shell and PHP resolvers give the same answer for a fresh
  host, a legacy OpenClaw install, the symlinked arrangement, a dangling link, an
  explicit override, and an unrelated deployment sitting alongside.

### Upgrade actions

**None required.** An existing install resolves to the file it already uses. If
you would rather move to the neutral path, move the file and delete the symlink
in one step, and restart both services:

```bash
mv ~/.openclaw/workspace/.env ~/.config/agenteiamail/env.real
rm -f ~/.config/agenteiamail/env
mv ~/.config/agenteiamail/env.real ~/.config/agenteiamail/env
systemctl --user restart agenteiamail-idle.service agenteiamail-dispatch.service
```

---

## 1.3.0 (2026-08-18)

**The delivery half no longer knows what a harness is.** Until now, delivering to
a second harness meant forking the repository: the watcher searched for the
`openclaw` binary itself, called it directly, and passed it a line written for a
person to read. This release puts a structured event and a runtime adapter between
the two halves, which is what makes a second harness an adapter rather than a
fork. First half of [#35](https://github.com/julianflores/agenteiamail/issues/35)
(FR1, FR2, FR3), with FR4 to follow.

**There is still no Hermes adapter in this release.** `AGENTEIAMAIL_RUNTIME`
accepts `hermes`, and this version will tell you plainly that it is not
implemented rather than pretending otherwise.

- **A canonical event envelope** ([`harness/event.py`](harness/event.py)): one
  JSON object per message carrying account, mailbox, UIDVALIDITY, UID, sender,
  subject, `roster_match` and the rendered line. No message body and no
  credentials, ever. `event_id` is `imap:<mailbox>:<uidvalidity>:<uid>`, stable
  across restarts and retries so a consumer can recognise a duplicate.
- **An append-only journal**, `events.jsonl`, written by the listener. It is a
  queue, not a log: `mail.log` is unchanged and is still what a person reads.
- **A runtime adapter interface** ([`harness/adapters/`](harness/adapters/)).
  An adapter reports accepted, retryable, or configuration-fault, and may not
  touch the cursor, listener state, or print a credential.
- **[`harness/dispatch.py`](harness/dispatch.py) replaces `watch.sh`**, which is
  removed along with `watch_service.sh`. It reads the journal by offset and moves
  the cursor only once an adapter accepts a record.
- **`AGENTEIAMAIL_RUNTIME`** selects the adapter: `openclaw`, `hermes`, or `auto`.
  `auto` chooses only when exactly one runtime is present and refuses rather than
  guessing when none or several are.
- **The exit-and-restart recovery from 1.2.2 is gone, and is not needed.** It
  existed because `tail -F` consumed a line by reading it, so surviving a failure
  meant killing the process. Reading a journal by offset consumes nothing, so a
  failed record is simply retried in place, indefinitely, while the cursor stays
  where it is. `StartLimitBurst` on the unit goes with it.
- **A stuck record holds the queue rather than being skipped**, loudly, on stderr
  and at the next session start. There is deliberately no dead-letter policy: a
  byte offset cannot describe a hole.
- **Journal compaction runs in the dispatcher**, which is the only process that
  knows what has been delivered, and takes the journal lock before it decides. It
  empties `events.jsonl` only when the cursor proves everything in it was
  delivered. The journal is never rotated with the logs; the cursor is an offset
  into that exact file, and a rotator on a timer could truncate away an event
  that had just been appended and never seen.
- **A record is written whole, flushed, and only then acknowledged.** One
  `os.write` may write fewer bytes than it was given, and the listener persists
  its last-seen UID after the append returns: if that UID reaches the disk and
  the record does not, the message is gone for good. The write now loops to
  completion and `fsync`s before reporting an offset.
- **A journal the listener cannot write blocks acknowledgement.** It used to log
  the failure and carry on, and the caller advanced the UID anyway, so a full
  disk or a permission error dropped the message permanently with a line in
  `mail.log` as the only trace. The UID now stays where it is and the messages
  are picked up again once the journal is writable.
- **Only one dispatcher may run.** It takes an exclusive lock at startup and
  refuses to start beside another, because two would read the same cursor and
  hand the runtime the same event twice.
- **A damaged record stops the queue** rather than being stepped over. Skipping
  an unparseable line advanced the cursor past it as soon as anything behind it
  was accepted, which is a dead-letter policy nobody chose and nobody was told
  about.
- **Listener faults are events.** `listener.error` envelopes go into the same
  journal as the mail, on transitions only, so an outage writes one record and a
  recovery writes one more. A fault reported only where nobody looks is a fault
  nobody sees. The state that suppresses repeats means *durably recorded*, not
  *attempted*: marking a failed append as reported would suppress it on every
  retry and could later produce a recovery record for an outage nobody was told
  about.

- **72 assertions in [`scripts/test_dispatch.py`](scripts/test_dispatch.py)**,
  covering the envelope, the journal, the cursor rules, runtime selection, the
  OpenClaw adapter against a faked binary, and each of the loss and duplication
  cases above including a concurrent append racing compaction.

### Upgrade actions

**This release renames a unit and changes where delivery state lives.** A `git
pull` alone leaves the old watcher running.

```bash
systemctl --user stop    agenteiamail-watch.service
systemctl --user disable agenteiamail-watch.service
rm -f ~/.config/systemd/user/agenteiamail-watch.service

install -Dm644 systemd/agenteiamail-dispatch.service ~/.config/systemd/user/
# then edit it: replace /path/to/agenteiamail with your clone's absolute path
systemctl --user daemon-reload
systemctl --user enable --now agenteiamail-dispatch.service
systemctl --user restart agenteiamail-idle.service
```

**Restart the listener too**, as shown. It is what writes the journal, and until
it restarts nothing is being queued for the new dispatcher.

**`seen.offset` is not migrated, and does not need to be.** It indexed
`mail.log`, which the dispatcher no longer reads. The new cursor,
`dispatch.offset`, starts at the beginning of a journal that starts empty, so the
first messages delivered after upgrading are the ones that arrive after it. Mail
that arrived while you were upgrading is in `mail.log` and in the listener's UID
state, not lost, but it will not be redelivered. Upgrade when the mailbox is
quiet if that matters to you.

---

## 1.2.3 (2026-08-18)

**A new install could not start on a host with no mailbox, which is the host the
setup form exists for.** `AGENTS.md` sent the agent to `scripts/preflight.py` at
step 1, before the credentials fork at step 2. Preflight has nothing to check
without credentials, so it asked for them on a terminal, found none because an
agent runs non-interactively, and exited 1. Step 1 also said to stop on failure
and not work around it, which is the right rule, so an agent following the file
correctly stopped before ever reaching the form.
Reported in [#31](https://github.com/julianflores/agenteiamail/issues/31).

- **The path in [`AGENTS.md`](AGENTS.md) is reordered** so each check runs when
  it has something to check. The systemd user session comes first and needs
  nothing but the host; the credentials fork comes second and needs only PHP;
  preflight comes third, with an account to test against. Steps 3 to 6 renumber
  to 4 to 7; nothing else in them changed, and the "stop, do not work around it"
  rule stays attached to preflight in its new position.
- **[`scripts/preflight.py`](scripts/preflight.py) now says what is actually
  wrong** when it is run with no credentials and no terminal, and points at the
  setup form instead of asking for an IMAP host. The reorder fixes the documented
  path; this fixes the tool for anyone who arrives at it in a different order.

- **8 assertions in [`scripts/test_preflight.sh`](scripts/test_preflight.sh)**,
  covering the empty and missing credential cases and confirming that a
  configured account still gets past the guard and reaches the server. Four fail
  against 1.2.2.

---

## 1.2.2 (2026-08-18)

**The 1.2.1 cursor fix could not recover from the failure it handled.** Stopping
the cursor at the first undelivered line was right; leaving it stopped for the
lifetime of the process was not. Nothing could restart it: the watcher stayed
alive and healthy so `Restart=always` never fired, and 1.2.1 had just removed the
session hook that used to arm a fresh watcher. One transient refusal left the
install delivering mail live while `seen.offset` stayed permanently behind, and
the only way out was restarting the service by hand. Reported by
[@apollohermesfl](https://github.com/apollohermesfl) reviewing
[#36](https://github.com/julianflores/agenteiamail/pull/36).

- **A failed line is retried in place with bounded backoff**
  ([`harness/watch.sh`](harness/watch.sh)), so a transient failure recovers on its
  own and the cursor carries on. `DELIVERY_ATTEMPTS` and `DELIVERY_BACKOFF` set
  how long that takes; the defaults spend about 30 seconds on a line.
- **When the retries are spent the watcher exits** instead of running on with a
  cursor that can no longer move. systemd restarts it, `watch_service.sh` resumes
  from the last confirmed byte, and the line is retried in order.
- **`StartLimitIntervalSec=600` / `StartLimitBurst=6`** in
  [`systemd/agenteiamail-watch.service`](systemd/agenteiamail-watch.service), so a
  failure that never clears ends as a failed unit rather than a restart loop.
  `session_start.py` already reports that as MAIL WATCHER IS DOWN.
- The 1.2.1 note that a failure meant the rest was "replayed next session" was
  wrong once the hook stopped arming a watcher. The hook shows what is pending;
  redelivery is the restart's job.

- **14 assertions in [`scripts/test_watch.sh`](scripts/test_watch.sh)**, now
  including a transiently failed line recovering without intervention and a
  sustained failure exiting rather than freezing. Five of them fail against 1.2.1.

### Upgrade actions

**Reinstall the watcher unit, then restart it.** The start limits are new, and a
`git pull` does not reach an installed unit file:

```bash
cp systemd/agenteiamail-watch.service ~/.config/systemd/user/   # re-apply your paths
systemctl --user daemon-reload
systemctl --user restart agenteiamail-watch.service
```

---

## 1.2.1 (2026-08-18)

**Three ways of losing mail without saying so.** All three lived in the cursor
that decides what a later session replays, and all three failed the same way:
the message was gone, nothing was logged as wrong, and the install looked exactly
like a mailbox with nothing in it. Found by review of `main` at `7d7efcc`
([#35](https://github.com/julianflores/agenteiamail/issues/35)).

- **A failed injection was recorded as delivered.**
  [`harness/watch.sh`](harness/watch.sh) advanced `seen.offset` after every
  `emit_system_event`, which deliberately returns success so that a failure
  cannot kill the watcher. The two together meant a refused `openclaw system
  event` acknowledged the message anyway, and the next session's replay started
  past it. `emit_system_event` now reports whether delivery happened, and the
  cursor moves only when it did. Having no `openclaw` to call at all counts as a
  failure, for the same reason.
- **The cursor recorded the log's size, not the line it had handled.** It was
  written as `wc -c` of the whole file, so anything appended while a delivery was
  in flight was stepped over. It now advances by exactly the bytes of the line
  just delivered, counted as bytes so a non-ASCII subject cannot leave it short.
- **A session started a second watcher next to the service.** The systemd unit
  runs `watch.sh` continuously while `session_start.py` told the agent to arm
  another one, putting two consumers on one stream and two writers on one cursor.
  The supervised service is now the only consumer and the only writer;
  `session_start.py` shows what is still pending and acknowledges nothing.

Delivery is now **at least once**: on failure the cursor stops at the first line
that did not arrive rather than skipping it, so that line and everything after it
are replayed. Expect an occasional duplicate notification after a delivery
failure. That is the intended trade.

- **8 assertions in [`scripts/test_watch.sh`](scripts/test_watch.sh)**, covering
  each defect above. They fail against 1.2.0.

### Upgrade actions

**Restart the watcher after pulling**, or the old code keeps running with the old
cursor behaviour:

```bash
systemctl --user restart agenteiamail-watch.service
```

**If your harness hook was generated from an older `session_start.py`**, its
output no longer asks the session to arm a watcher. Nothing needs removing, but a
session that is still being told to start one is running the duplicate consumer
this release removes.

---

## 1.2.0 (2026-08-16)

**An install can now tell whether it is current.** Until this release there was
no version anywhere in the repository, so an agent had no way to answer the
question and no reason to think of asking it. The fix below reached this
repository on 2026-08-13 and no running install had any way to learn that it
existed, which is the same shape of failure as the bug itself: everything looks
healthy, and the thing that would tell you otherwise is not wired up.

- **[`VERSION`](VERSION)**, the ground truth for what is installed. Read from a
  file rather than derived from `git describe`, so a tarball copy, a shallow
  clone or a detached HEAD still reports correctly.
- **[`scripts/version.sh`](scripts/version.sh)**: installed against released,
  read from the clone's own origin with `git ls-remote`, so there is no API
  token to hold and no rate limit to hit. It exits 1 rather than claiming
  currency when it could not reach the remote.
- **The session-start hook says the version in one line**, refreshing the remote
  check at most once a day. A session is the only moment an agent can be told
  unprompted, and one that is never told never asks.
- **[`UPGRADE.md`](UPGRADE.md)**: the upgrade sequence, including the three
  things a pull cannot reach.
- **29 assertions in [`scripts/test_version.sh`](scripts/test_version.sh)**,
  against a local bare repository rather than the network. The case they exist
  for is 1.10.0 against 1.9.0, which string comparison gets backwards and which
  nothing will notice for a year.

**Fixed: the watcher discarded the reason an event injection failed.** A host
where `openclaw` was present, executable, and failing on every call logged mail
correctly, passed every check in `INSTALL.md` §7, and delivered nothing to the
session. The failure signal and the health signal were byte-identical. The
reason is now captured to `watch.err.log` on transitions, and `session_start.py`
reports a non-empty error log and a dead watch unit the way it already reported
a dead listener. This is the defect named at the end of the 1.1.0 notes.

**Documentation.** `INSTALL.md` §6 now says that `openclaw` is a Node program
and the service PATH decides which Node it gets, which is how the bug above
reached a live install: one host needed Node 24 and the service supplied 22. Em
dashes are gone from the webapp and the public documentation, 246 of them,
including the four translations.

### Upgrade actions

**If you adapted the marked block in `harness/session_start.py`,** the one
between `---- ADAPT THIS BLOCK TO OPENCLAW'S HOOK CONTRACT ----` and its closing
rule, your pull will conflict there. That is the file this release changed, and
the conflict is the correct outcome: reapply your harness's output shape onto
the new version rather than keeping your old copy, or you lose the version line
and the watcher fault reporting along with it.

**If you are on a clone with no `VERSION` file,** you are older than 1.2.0 and
nothing in your install can tell you so. That is unavoidable for one upgrade
only: `version.sh` cannot exist on a clone that predates it. From 1.2.0 onward
the check runs itself.

---

## 1.1.0 (2026-08-13)

**A local setup page for Step 1.** `scripts/setup_web.sh` serves a form on
loopback, prints a one-time link, and stops once `~/.openclaw/workspace/.env`
exists. It authenticates against the mail server before writing anything, so
settings that do not sign in are never saved. The agent starts the page and
never sees the password.

**Fixed:**

- The certificate-mismatch diagnosis never fired, so the one message the feature
  existed to produce fell through to raw PHP noise.
- Writing through the `~/.config/agenteiamail/env` symlink replaced it, which on
  a host following `INSTALL.md` §3 would have stranded the listener on a file
  nobody updates.
- `AGENT_EMAIL_INCOMING_SERVER_POP` sat in the listener's `LEGACY_AMBIGUOUS`
  guard and could refuse the install over a vestigial key nothing reads.

**Documentation.** POP is gone everywhere; it was never implemented. The Step 2
prompt no longer carries the password rule. The four translations are updated
and carry staleness banners naming the English commit they track.

---

## 1.0.0 (2026-08-10)

First release. IMAP IDLE listener as a systemd user service, roster-gated
instruction channel, well-formed outbound mail with RFC 2047 headers and
injection guards, session catch-up and log rotation, 38 assertions across
`test_roster.sh` and `test_listener.py`, documentation in five languages.

### Upgrade actions

**Only if your clone predates 2026-08-09.** The scripts moved into `scripts/`
that day, and a systemd unit still naming the old path keeps working until the
next restart or reboot, then refuses to start long after the change that caused
it. The fix is in the box at the top of [`INSTALL.md`](INSTALL.md).
