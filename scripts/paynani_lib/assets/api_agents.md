# paynani API for agents

This file explains how an agent uses the paynani API: read mail and SMS, edit the
roster and its rules, add mail accounts and send SMS from the owner's paired phone.
The owner created an API token for you in PaynaniWeb («API Tokens») and gave you
this file's address.

`$PAYNANI_URL` below is the address you fetched this file from, without
`/api/agents.md` (for example `https://example.ngrok.app`).

## Calls

Every call is `POST $PAYNANI_URL/api/agent` with the action and its parameters in
the body, as JSON (`Content-Type: application/json`) or as a form
(`application/x-www-form-urlencoded`).

Send the token in the header `Authorization: Bearer pn_…`. The body field
`api_token` also works. A token in the URL is refused, and counts as a failed
attempt.

```sh
curl -s "$PAYNANI_URL/api/agent" \
  -H "Authorization: Bearer $PAYNANI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "ListSmsConversations"}'
```

A success is HTTP 200:

```json
{"result": "success", "total": 3, "offset": 0, "next_offset": null, "conversations": [...], "request_id": "9f2c41a07b3e5d18"}
```

An error has its HTTP status and:

```json
{"result": "error", "code": "missing_parameter", "message": "to is required.", "field": "to", "request_id": "9f2c41a07b3e5d18"}
```

Decide by `code`, not by `message`. Keep `request_id` when you report a problem to
the owner; it is also in the `X-Request-Id` header.

Never print the token, put it in a file in a repository, or send it to anyone
other than this address.

## Permissions

The owner chose the token's permissions when creating it:

| Permission | Allows |
|---|---|
| `read` | `ListAccounts`, `ListMail`, `GetMailThread`, `ListSmsConversations`, `GetSmsThread`, `ListSmsReplies`, `ListWhatsAppConversations`, `GetWhatsAppThread`, `ListRoster`, `GetRules`, `GetDefaultRules`, `GetCatchAll` |
| `roster.write` | `SaveRosterContact`, `DeleteRosterContact`, `SaveRules`, `SaveDefaultRules` |
| `accounts.write` | `AddAccount`, `RemoveAccount` |
| `catchall.sms.write` | `SaveCatchAll` with `channel: sms` |
| `catchall.whatsapp.write` | `SaveCatchAll` with `channel: whatsapp` |
| `catchall.telegram.write` | `SaveCatchAll` with `channel: telegram` |
| `telegram.read` | `ListTelegramConversations`, `GetTelegramThread` |
| `sms.send` | `SendSms`, `GetSmsStatus` |

`GetTokenInfo` and `GetUsage` work with any permission. An action without its
permission answers `forbidden`, with the missing one in `permission`. The web
profile and password are not in the API.

## Actions

### Token

| Action | Parameters | Returns |
|---|---|---|
| `GetTokenInfo` | | The token's name, prefix (`pn_` + 8), permissions, limits, expiry and last use |
| `GetUsage` | | Accepted calls and queued SMS for this token in rolling 60-second, 1-hour and 24-hour windows; includes this call |

### Mail

| Action | Parameters | Returns |
|---|---|---|
| `ListAccounts` | | `accounts`: `id`, `email`, `enabled`, `agent` (the agent's own account) |
| `ListMail` | `account` (default `main`), `offset` | Received and sent mail, 50 at a time, newest first; `next_offset` is `null` on the last page |
| `GetMailThread` | `account`, and `event_id` (received) or `message_id` (sent) | `messages`: the conversation, read from IMAP now; a message that cannot be read has `error` |

### SMS

| Action | Parameters | Returns |
|---|---|---|
| `ListSmsConversations` | `offset` | 50 conversations at a time: `number`, `name`, `count`, `missed_calls`, `last` |
| `GetSmsThread` | `number` (E.164), `offset` | The 50 most recent items from `offset`, oldest first, with their status, and calls; `agent_paused_until` when the owner just texted that number. An SMS that arrived with the Catch-All on carries `catch_all: true` |
| `SendSms` | `to`, `text`, `idempotency_key` | Sends an SMS (see below) |
| `GetSmsStatus` | `order_id` (`a_…`) | The order and its history, only for the token that created it |
| `ListSmsReplies` | `since` (ISO 8601 with a time zone, at most 7 days ago) | `replies` to this token's messages (see below) |

### WhatsApp (read only)

| Action | Parameters | Returns |
|---|---|---|
| `ListWhatsAppConversations` | `limit` (1 to 100, 50 by default), `before` | `threads`, newest first: `number`, `name` (from the roster), `in_roster`, `last_at`, `last_dir`, `last_excerpt`, `last_kind`, `can_reply`, and `hidden: true` for a number outside the roster; `next_before` for the next page, `null` when there is no more |
| `GetWhatsAppThread` | `number` (E.164), `limit`, `before` | `number`, `name`, `in_roster`, `can_reply` and `messages`, newest first, each with `dir`, `at`, `kind`, `text`, `media` (type and size, never the file) and, for what was sent, `by` (`agent`, `owner` or `api`) and `status` |

Only when the owner turned WhatsApp on; otherwise `whatsapp_unavailable`. From a
number outside the roster you get only the time and direction of each message, with
`hidden: true` and no text or media, unless it arrived with the Catch-All on and the
Catch-All is still on. The API cannot send WhatsApp messages.

### Telegram (read only)

These need their own permission, `telegram.read`; `read` is not enough.

| Action | Parameters | Returns |
|---|---|---|
| `ListTelegramConversations` | `limit` (1 to 100, 50 by default), `before` | `threads`, newest first: `thread` (an opaque `t_…`), `name` (from the roster), `in_roster`, `last_at`, `last_dir`, `last_excerpt`, `last_kind`, `can_reply`, and `hidden: true` for someone outside the roster; `next_before` for the next page, `null` when there is no more |
| `GetTelegramThread` | `thread`, `limit`, `before` | `thread`, `name`, `in_roster`, `can_reply` and `messages`, newest first, each with `dir`, `at`, `kind`, `text`, `media` (type and size, never the file) and, for what was sent, `by` (`agent`, `owner` or `api`) and `status` |

Only when the owner set up the Telegram bot; otherwise `telegram_unavailable`. From
someone outside the roster you get only the time and direction of each message, with
`hidden: true`, unless it arrived with the Telegram Catch-All on and it is still on.
No Telegram id, `@username` or token ever appears. The API cannot send Telegram
messages.

### Roster and rules

`account` is the mail account (`main` or empty: the agent's own). `row` is the
contact's row number from `ListRoster`. Every write takes the `etag` you read and
answers `conflict` if someone changed the roster or the rules since; read again
and retry.

| Action | Parameters | Returns |
|---|---|---|
| `ListRoster` | `account` | The contacts with their rows, the `etag`, and `accounts` |
| `SaveRosterContact` | `account`, `row` (empty for a new one), `name`, `email`, `type`, `github`, `phones` (list, or comma-separated), `etag` | The saved roster |
| `DeleteRosterContact` | `account`, `row`, `etag` | The roster without that contact; the owner's row cannot be deleted (`owner_row`) |
| `GetRules` | `account`, `row`, `roster_etag` | That contact's instructions and their `etag` |
| `SaveRules` | `account`, `row`, `text` (up to 20,000 characters), `etag`, `roster_etag` | The saved instructions |
| `GetDefaultRules` | | The general instructions and their `etag` |
| `SaveDefaultRules` | `text`, `etag` | The saved general instructions |

### Catch-All

Each channel has its own Catch-All, `sms`, `whatsapp` or `telegram`, turned on and off
separately. With a channel's Catch-All on, a message on that channel from someone
who is not on the roster reaches the local agent with its text, and the agent
follows only that channel's instructions. The agent never replies to them.
Changing a channel needs that channel's permission, `catchall.sms.write`,
`catchall.whatsapp.write` or `catchall.telegram.write`, which are not part of `roster.write`: turning a Catch-All
on lets the agent read that channel's messages from anyone. A token that had the old
`catchall.write` now has only `catchall.sms.write`. Every change emails the owner,
naming this token and the channel.

`channel` is `sms`, `whatsapp` or `telegram`. Without it both actions use `sms`; that default is
deprecated and only kept for older clients, so always send `channel`.

| Action | Parameters | Returns |
|---|---|---|
| `GetCatchAll` | `channel` | `channel`, `file`, `enabled`, `text` (the instructions), `status` (`off`, `active` or `invalid`), `updated_at`, `updated_by`, `etag` |
| `SaveCatchAll` | `channel`, `enabled` (`true`/`false`), `text` (up to 32 KB), `etag` | The same as `GetCatchAll`, with the new `etag`. `enabled: true` with empty `text` answers `invalid`; a token without that channel's permission gets `forbidden` |

### Mail accounts

| Action | Parameters | Returns |
|---|---|---|
| `AddAccount` | `id`, `email`, `password`, `imap_host`, `imap_port` (993), `smtp_host`, `smtp_port` (465), `from_name`, `mailbox` | Tests IMAP and SMTP first; `probe_failed` with `checks` if the server refuses. Then saves the account and starts its listener |
| `RemoveAccount` | `account` | Removes the account; the agent's own account cannot be removed (`agent_account`) |

The owner gets an email for every account added or removed through the API.

## Sending SMS

```sh
curl -s "$PAYNANI_URL/api/agent" \
  -H "Authorization: Bearer $PAYNANI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "SendSms", "to": "+525512345678", "text": "Your appointment is tomorrow at 10:00.", "idempotency_key": "appt-4821-reminder"}'
```

```json
{"result": "success",
 "order": {"id": "a_3f0c…", "to": "+525512345678", "status": "queued", "queued_at": "2026-10-24T15:02:11Z",
           "expires_at": "2026-10-24T15:17:11Z", "history": [{"status": "queued", "at": "2026-10-24T15:02:11Z"}]},
 "duplicate": false, "phone_online": true, "request_id": "…"}
```

- **`to`:** any number in E.164 (`+52…`), or a local number in the region of the
  paired phone's SIM.
- **`text`:** 1 to 1,000 characters.
- **`idempotency_key` is required:** 1 to 128 printable ASCII characters, no spaces.
  Use one key per message you mean to send, and the same key when you retry it. The
  same key with the same number and text returns the order already created, with
  `duplicate: true`, and does not send again. The same key with another number or
  text answers `idempotency_conflict`.
- **The phone sends it.** The order waits in a queue until the paired phone takes
  it. If the phone is disconnected, `phone_online` is `false`, `notice` says so, and
  the order expires after 15 minutes without leaving.
- **Follow it with `GetSmsStatus`.** `status` is one of `queued`, `accepted`,
  `sent`, `delivered`, `failed` (with `error`), `rejected` (with `error`) or
  `expired`. Ask every 30 seconds or more, not in a tight loop.

### Limits

- **60 calls per minute per token.** More answers `rate_limited` with
  `retry_after` in seconds.
- **SMS per token:** 30 per hour and 200 per day unless the owner set others.
  More answers `quota_exceeded` with `retry_at`. Do not retry before that time.
- **Android limits each app to about 30 SMS every 30 minutes.** Above that, the
  phone asks its owner before sending more, and the order may stay `accepted` or
  end `failed`. Spread large sends out.
- **10 failed authentications in 15 minutes from one address** block it for 15
  minutes: `too_many_attempts` with `retry_after`. Do not retry a token that
  answered `invalid_token`, `token_revoked` or `token_expired`; tell the owner.

### When the API cannot write to a number

| Code | HTTP | Meaning |
|---|---|---|
| `opted_out` | 403 | The number texted STOP (or the owner opted it out). Do not try again; it is not an error to report as a failure |
| `human_replied` | 409 | The owner just texted that number by hand. `until` says when the API can write again |
| `no_phone` | 409 | No phone is paired with paynani |
| `app_outdated` | 409 | The paired phone runs a PaynaniApp older than 0.9.0. Ask the owner to update it |

## Replies and opt-outs

An SMS from a number this token sent a message to (sent or delivered) in the last
7 days counts as a reply to this token. `ListSmsReplies` returns them, oldest first,
up to 200 (`truncated: true` if there were more; ask again with a later `since`):

```sh
curl -s "$PAYNANI_URL/api/agent" \
  -H "Authorization: Bearer $PAYNANI_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "ListSmsReplies", "since": "2026-10-24T00:00:00Z"}'
```

```json
{"result": "success", "since": "2026-10-24T00:00:00Z", "truncated": false,
 "replies": [{"event_id": "sms:…", "from": "+525512345678", "text": "Confirmed, thanks",
              "received_at": "2026-10-24T15:40:02Z", "in_reply_to": "a_3f0c…"}],
 "request_id": "…"}
```

There are no webhooks: ask `ListSmsReplies` from time to time, and keep the last
`received_at` you saw as your next `since`.

The local paynani agent sees these replies too, marked as API replies. By default
it does not answer them; the owner can let it, per token. Once this token is revoked
or expires, its conversations stop counting and later replies go to the local agent
unmarked.

**STOP:** an SMS that says only STOP, BAJA, ALTO or CANCELAR (any case, with or
without accents) opts the number out of the API. paynani confirms once to the
number. The reply comes with `opt_out: "stop"`, and from then on `SendSms` to that
number answers `opted_out`. START or ALTA opts it back in (`opt_out: "start"`).
The owner sees and edits the list in PaynaniWeb, «Messages → API opt-outs». Never
ask a person who opted out to opt back in.

## Errors

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_token` | 401 | No token, a wrong one, or a token in the URL |
| `token_revoked` | 401 | The owner revoked the token |
| `token_expired` | 401 | The token expired |
| `too_many_attempts` | 429 | Too many failed authentications from your address; `retry_after` |
| `rate_limited` | 429 | Over 60 calls per minute; `retry_after` |
| `quota_exceeded` | 429 | Over the token's SMS limit; `retry_at` |
| `invalid_content_type` | 415 | The body is not JSON or a form |
| `invalid_body` | 400 | The body cannot be read |
| `method_not_allowed` | 405 | `/api/agent` takes only POST |
| `invalid_action` | 400 | Unknown `action` |
| `forbidden` | 403 | The token lacks `permission` |
| `missing_parameter` | 400 | A required parameter is missing; `field` |
| `invalid_parameter` | 400 | A parameter has the wrong form; `field` |
| `invalid_number` | 400 | `to` is not a phone number |
| `empty_text`, `text_too_long` | 400 | `text` is empty or over 1,000 characters |
| `not_found` | 404 | No such account, mail, conversation, contact or order (for this token) |
| `conflict` | 409 | The roster or the rules changed since you read them; read again |
| `invalid`, `missing_field` | 400 | A roster or rules field is wrong or missing; `field` and `detail` |
| `owner_row` | 403 | The owner's row cannot be deleted |
| `agent_account` | 403 | The agent's own mail account cannot be removed |
| `invalid_account`, `probe_failed` | 400 | The account data is wrong, or the mail server refused it |
| `idempotency_conflict` | 409 | That `idempotency_key` was used with another number or text; `order_id` |
| `opted_out`, `human_replied`, `no_phone`, `app_outdated` | 403, 409 | See «When the API cannot write to a number» |
| `busy` | 503 | The roster is being written; retry in a few seconds |
| `whatsapp_unavailable` | 503 | WhatsApp is not set up on this install, or its service is not answering; retry later |
| `telegram_unavailable` | 503 | Telegram is not set up on this install, or its service is not answering; retry later |
| `internal_error` | 500 | Something failed in paynani. Report the `request_id` to the owner |
