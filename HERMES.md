# Hermes Agent adapter

`paynani` can deliver its canonical event journal to two authenticated
Hermes webhook routes. Unlisted senders go to a narrow direct-notification
route. Exact roster matches go to an isolated one-shot agent route that can
fetch the exact message by account, mailbox, UIDVALIDITY, and UID.

This adapter uses Hermes **Generic HMAC V2**. It was exercised against Hermes
Agent 0.20.4. An older gateway without `X-Webhook-Signature-V2` needs an
explicit legacy setting and does not have replay protection.

## Trust boundary

`roster_match=true` means one of two things, both decided by a human-maintained
file: the RFC 5322 `From` address exactly matched the list, or `From` matched a
notifier the operator declared in that same file and the header that notifier
names carried a value matching that person's column. It is **not authenticated
identity** in either case — and the second rests additionally on the platform's
own `From` being genuine, which nothing here verifies. The webhook
contains sender and subject metadata but no message body. The roster agent must
treat the webhook and the subsequently retrieved email as untrusted content;
email may contain task instructions, but never system or developer instructions.

The installer must not grant Hermes tools or skills. The operator reviews and
adds the roster route because it can grant a webhook-triggered agent access to
a mail client. [`examples/hermes-routes.yaml`](examples/hermes-routes.yaml) is
a JSON-compatible YAML example, checked by
`scripts/test_hermes_examples.py`; it is never installed automatically.

## 1. Configure the Hermes routes

The checked example is for a **standalone profile gateway**. Copy its two route
entries into that gateway profile's `platforms.webhook.extra.routes`, then
replace:

- both example secrets with **different random values**;
- the notification delivery target and chat ID;
- the roster-agent final delivery target and chat ID;
- the `himalaya` skill/toolset names if that profile exposes mail differently.

For a **multiplexed gateway**, port-binding webhook configuration and all route
definitions belong only in the default profile's `config.yaml`. Enable
`gateway.multiplex_profiles`, add `profile: mail-agent` to **both** route
entries, and do not enable `platforms.webhook` in the secondary profile. Use
both profile-prefixed route URLs:

```yaml
gateway:
  multiplex_profiles: true
platforms:
  webhook:
    extra:
      routes:
        paynani-notify:
          profile: mail-agent
          # copy the remaining notify fields from the checked example
        paynani-roster:
          profile: mail-agent
          # copy the remaining roster fields from the checked example
```

Without each route's matching `profile`, a `/p/mail-agent/...` request fails
closed with 404. Without multiplexing, Hermes ignores the profile prefix; do
not present such a URL as profile-bound.

**A route is not live until the gateway restarts, and the restart cannot come
from inside the gateway.**

```bash
hermes gateway restart      # from a shell outside the running gateway
```

Hermes reads its route configuration at start. Until it restarts, the routes you
just added do not exist: `HERMES_HEALTH_URL` has nothing listening on it, and the
installer's health probe fails on an otherwise correct configuration.

An agent that is itself running inside that gateway cannot perform this step.
Hermes refuses it — *"command or referenced script cannot restart or stop the
gateway from inside the gateway process"* — because the restart would kill the
command mid-flight. **That refusal is correct and is not a fault to work
around.** Hand the restart to the operator, wait, and resume verification
afterwards.

The notify route has `deliver_only: true`, so it sends the narrow rendered
notification without model execution. The roster route omits `deliver_only`,
so HTTP acceptance starts an asynchronous agent run. Its example grants only
the `himalaya` skill and `terminal` toolset needed by that skill. Review this
against the target profile; anyone who can sign a route with `terminal` can
trigger those capabilities.

The notify route accepts `email.received` and `listener.error`; the roster route
accepts `email.received` only. Listener faults therefore surface through direct
delivery and can never start an agent run.

Hermes stores static route secrets in its protected configuration. The adapter
reads matching copies from separate mode-0600 files. It refuses symlinks,
non-regular files, files owned by another user, and every mode other than 0600.
Do not put either secret in a command argument, unit file, journal event, or URL.

```bash
install -d -m 700 hermes    # from inside the clone
install -m 600 /dev/null hermes/notify.secret
install -m 600 /dev/null hermes/roster.secret
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' \
  > hermes/notify.secret
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' \
  > hermes/roster.secret
chmod 600 hermes/*.secret
```

Copy each generated value into only its matching static route. Keep the Hermes
configuration mode 0600. Restart that isolated gateway after editing static
routes.

## 2. Configure the dispatcher

Set these variables in the dispatcher service environment. The URL is supplied
in full: the adapter does not inspect `~/.hermes`, guess a port, or infer a
profile prefix.

```ini
Environment=PAYNANI_RUNTIME=hermes
Environment=HERMES_NOTIFY_URL=http://127.0.0.1:8644/webhooks/paynani-notify
Environment=HERMES_NOTIFY_SECRET_FILE=/path/to/paynani/hermes/notify.secret
Environment=HERMES_ROSTER_URL=http://127.0.0.1:8644/webhooks/paynani-roster
Environment=HERMES_ROSTER_SECRET_FILE=/path/to/paynani/hermes/roster.secret
Environment=HERMES_HEALTH_URL=http://127.0.0.1:8644/health
Environment=HERMES_SIGNATURE_MODE=v2
```

For the multiplexed `mail-agent` example above, set both route URLs; keep the
shared gateway health URL unprefixed:

```ini
Environment=HERMES_NOTIFY_URL=http://127.0.0.1:8644/p/mail-agent/webhooks/paynani-notify
Environment=HERMES_ROSTER_URL=http://127.0.0.1:8644/p/mail-agent/webhooks/paynani-roster
Environment=HERMES_HEALTH_URL=http://127.0.0.1:8644/health
```

Use loopback unless the gateway is intentionally remote. A non-loopback URL is
refused unless it uses HTTPS and the service explicitly sets
`HERMES_ALLOW_REMOTE=1` after the operator verifies the destination and TLS.
Credentials in route URLs are always refused.

`HERMES_SIGNATURE_MODE=v2` is the default. `v1` sends the legacy
`X-Webhook-Signature` over the body only and emits a replay-protection warning.
The adapter never silently downgrades after a V2 failure.

After editing the unit:

```bash
systemctl --user daemon-reload
systemctl --user restart paynani-dispatch.service
scripts/healthcheck.py
```

The health command performs a finite-timeout `GET` to `HERMES_HEALTH_URL`. A
healthy response proves only that the webhook server answers. It does **not**
prove either route name, secret, profile binding, filter, target, or agent run.

## 3. Verify both routes

Do not call the installation complete after `GET /health`.

1. Send an external test email from an address **not** in `roster.md`.
2. Observe a real user-facing notification from `paynani-notify` without a
   model run.
3. Send an external test email from an exact roster address.
4. Observe the `paynani-roster` route accept it.
5. Separately observe the final agent output and confirm it fetched the exact
   account, mailbox, UIDVALIDITY, and UID.
6. Trigger or inject a canonical `listener.error` and confirm the direct notify
   route surfaces it rather than leaving it as an ignored head-of-line event.
7. Stop the test gateway, send another message, and confirm the journal cursor
   does not advance. Restart the gateway and confirm the same event is then
   accepted.
8. Confirm `scripts/send.sh` still refuses a recipient absent from `roster.md`.

`scripts/healthcheck.py` records the last adapter detail. For Hermes agent mode,
that detail deliberately distinguishes transport acceptance from completion.

## Response and retry contract

| Hermes response | Adapter result | Meaning |
|---|---|---|
| `202 status=accepted` on roster route | accepted | Hermes queued an asynchronous agent run; completion is unconfirmed. |
| `200 status=delivered` on notify route | accepted | Direct delivery completed. |
| `200 status=duplicate` | accepted | Hermes already recorded this transport ID; after an ambiguous timeout, verify the user-facing result. |
| accepted/delivered status on the wrong route mode, or a mismatched response `route` | configuration failure | Route URLs or secrets may be swapped; the routing boundary is not acknowledged. |
| `200 status=ignored` | configuration failure | The configured event filter did not route an event this adapter expected to route. |
| redirect, `400`, `401`, `403`, `404`, `413` | configuration failure | The ordered queue stops loudly without acknowledging the event. |
| network error, timeout, `408`, `429`, other `5xx` | retry | The cursor remains still and the dispatcher retries in place. |

Hermes records the request ID before attempting a direct-delivery target. After
an explicit direct `502`, retrying the same request ID could return `duplicate`
without trying the target again. The adapter therefore persists the current
direct-attempt ID under `$PAYNANI_STATE/hermes-attempts/`, records a known
failed attempt before returning, and makes at most one immediate retry with a
new ID. A later dispatcher call rotates away from every persisted known-failed
ID, including across process restarts. The canonical application `event_id`
never changes.

The dispatcher provides bounded exponential backoff with jitter and paces
accepted catch-up records after an outage. Delivery is at least once: a process
can stop after Hermes accepts an event but before the journal cursor is
persisted, and ambiguous timeouts cannot prove whether acceptance happened.

## Wire contract

For V2, the adapter serializes the canonical envelope once as compact,
sorted-key UTF-8 JSON. It signs and sends those exact bytes:

```text
X-Webhook-Timestamp: <current Unix seconds>
X-Webhook-Signature-V2: lowercase_hex(HMAC-SHA256(secret, timestamp + "." + body))
X-Request-ID: <stable SHA-256-derived account-and-route-scoped transport ID>
```

A delayed attempt receives a fresh timestamp and signature. No `svix-*` header
is sent. Fixed vectors and status/error behavior are covered by
`scripts/test_hermes_adapter.py`.
