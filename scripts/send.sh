#!/usr/bin/env bash
# Send via Himalaya, but only to allowlisted recipients.
#
#   send.sh [--check] [--cc <address>] [--attach <path>]... <to> <subject> <body-file>
#
# Anything not in roster.md exits 2 and sends nothing. That is the point: this
# agent reads mail all day and acts on the part of it that comes from the roster,
# so the address it writes to must come from the same list and nowhere else.
# --cc is held to the same rule -- it is a second address this agent writes to,
# not a lesser one, so it is checked against the roster exactly like <to>.
#
# --attach may be repeated; the files ride in the order given. With none, the
# message is byte-for-byte what it was before attachments existed: a single-part
# text/plain. With one or more it becomes multipart/mixed, and the body is the
# first part rather than the whole message. A field report that could only be
# pasted into the body is what asked for this (#38).
#
# --check prints the message it would send and sends nothing. Use it to prove
# this script can find its credentials, which the roster tests cannot: the roster
# gate runs first, so a refusal exits before the env file is ever read. It prints
# attachments encoded, not summarised, because a message you cannot see whole is
# one you cannot check.
#
# Environment:
#   ROSTER    path to the allowlist        (default: repo root/roster.md)
#   ENV_FILE  path to the credentials file (default: from envpath.sh)
#
# ENV_FILE matters on any host whose credentials live somewhere else — the
# OpenClaw workspace `.env`, say. The listener is told with `--env` on its unit;
# this script has no unit to carry the flag, so point the default at the real
# file once, at install time. INSTALL.md §3 says how.

set -euo pipefail

# The roster lives at the repository root, not beside this script. Resolve it
# from here rather than from the caller's working directory, and allow an
# override so a test can point somewhere else.
# roster.md is the one name -- see harness/paths.py roster() for why there is no
# fallback to a second one.
if [ -z "${ROSTER:-}" ]; then
	_paynani_root=$(cd "$(dirname "$0")/.." && pwd)
	ROSTER="$_paynani_root/roster.md"
fi
# shellcheck source=envpath.sh
. "$(cd "$(dirname "$0")" && pwd)/envpath.sh"
ENV_FILE="${ENV_FILE:-$(paynani_env_file)}"
ACCOUNT="paynani"

check_only=""
cc=""
attachments=()
while [ $# -gt 0 ]; do
    case "$1" in
        --check)
            check_only=yes
            shift
            ;;
        --cc)
            cc=${2:?--cc requires an address}
            shift 2
            ;;
        --attach)
            attachments+=("${2:?--attach requires a path}")
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

to=${1:?usage: send.sh [--check] [--cc <address>] [--attach <path>]... <to> <subject> <body-file>}
subject=${2:?missing subject}
bodyfile=${3:?missing body file}

[ -f "$bodyfile" ] || { echo "no such body file: $bodyfile" >&2; exit 1; }

# Attachments are checked before anything is built, so a bad path costs nothing
# and half a message is never sent. Exit 2 is the same code the roster refusal
# uses, and means the same thing here: nothing left this host.
attach_bytes=0
for _paynani_file in ${attachments[@]+"${attachments[@]}"}; do
    if [ ! -f "$_paynani_file" ] || [ ! -r "$_paynani_file" ]; then
        echo "REFUSED: cannot read attachment $_paynani_file" >&2
        echo "Nothing was sent. Check the path, or drop the --attach." >&2
        exit 2
    fi
    attach_bytes=$(( attach_bytes + $(wc -c < "$_paynani_file") ))
done

# Gmail rejects above 25 MB, and base64 costs a third on top of the raw bytes.
# Refusing here beats an SMTP rejection after the fact, which arrives as a bounce
# to a mailbox nobody may read for hours.
ATTACH_LIMIT=20971520
attach_encoded=$(( attach_bytes * 4 / 3 ))
if [ "$attach_encoded" -gt "$ATTACH_LIMIT" ]; then
    echo "REFUSED: attachments encode to ~${attach_encoded} bytes, over the ${ATTACH_LIMIT} limit" >&2
    echo "Nothing was sent. Send fewer files, or link to them instead." >&2
    exit 2
fi

# A newline in any of these would end the header and start another one, so a
# crafted subject (or cc) could add Bcc: and reach an address the roster never
# approved. All three reach here from mail the agent was asked to act on, so
# strip rather than trust. Everything after the first line of a header is not
# a header.
to=$(printf '%s' "$to" | tr -d '\r\n')
subject=$(printf '%s' "$subject" | tr -d '\r\n')
cc=$(printf '%s' "$cc" | tr -d '\r\n')

if [ ! -f "$ROSTER" ]; then
    echo "no roster at $ROSTER — refusing to send" >&2
    echo "Create it from the template:  cp roster.md.example roster.md" >&2
    exit 2
fi

# The address is the field containing "@", not the field after the last "|".
# Taking the last field held for "Name | email" and breaks the moment a row
# carries anything after the address, which the Type column now does:
#
#     | Julian Flores | jjulianfe@gmail.com | Human |
#
# There the last field is "Human"; taking it silently drops that person from
# the list. scripts/roster.py's roster_addresses() picks the field containing
# "@" for exactly this reason -- the two must agree, so this mirrors it rather
# than re-deriving its own rule. Comparison is case-insensitive and blank-
# stripped, same as before.
#
# The extraction itself lives in roster_extract.sh, not here, so there is one
# bash implementation of it rather than a copy that can drift from what a test
# exercises -- which is exactly how send.sh drifted from roster.py in #91. Both
# <to> and --cc call this one function rather than each inlining the check, for
# the same reason.
_paynani_scriptdir="$(cd "$(dirname "$0")" && pwd)"
roster_allows() {
    _paynani_want=$(printf '%s' "$1" | tr -d '[:blank:]' | tr '[:upper:]' '[:lower:]')
    "$_paynani_scriptdir/roster_extract.sh" "$ROSTER" | grep -qxF "$_paynani_want"
}

if ! roster_allows "$to"; then
    echo "REFUSED: $to is not in $ROSTER" >&2
    echo "Add it deliberately, or ask your human to send this one." >&2
    exit 2
fi

if [ -n "$cc" ] && ! roster_allows "$cc"; then
    echo "REFUSED: cc $cc is not in $ROSTER" >&2
    echo "Add it deliberately, or ask your human to send this one." >&2
    exit 2
fi

# --- Who the message is from -------------------------------------------------
#
# Himalaya v2 refuses a raw message with no From: header — "No `From:` header
# found in raw message" — and v1 filled it in from account config, so this looks
# like it worked for as long as nobody was on v2.
#
# Read the same env file the listener reads, and accept the same two key schemas
# it accepts, so one install cannot end up with the listener and the sender
# disagreeing about which account this is. Tolerates CRLF and a UTF-8 BOM for the
# same reason load_env() in idle_listener.py does: both have bitten this repo.

env_value() {
    [ -f "$ENV_FILE" ] || return 0
    sed -e '1s/^\xef\xbb\xbf//' -e 's/\r$//' "$ENV_FILE" \
        | grep -m1 -E "^[[:space:]]*$1=" \
        | sed -e "s/^[[:space:]]*$1=//" \
              -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
              -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/" \
        || true
}

# PAYNANI_* wins where both are set — naming it explicitly means you meant it.
from_addr=$(env_value PAYNANI_EMAIL)
[ -n "$from_addr" ] || from_addr=$(env_value AGENT_EMAIL_ACCOUNT)
from_addr=$(printf '%s' "$from_addr" | tr -d '[:space:]')

from_name=$(env_value PAYNANI_FROM_NAME)
[ -n "$from_name" ] || from_name=$(env_value AGENT_EMAIL_FROM_NAME)
from_name=$(printf '%s' "$from_name" | tr -d '\r\n')

if [ -z "$from_addr" ]; then
    echo "no sender address in $ENV_FILE — refusing to send" >&2
    echo "Set PAYNANI_EMAIL (or AGENT_EMAIL_ACCOUNT), or point ENV_FILE at" >&2
    echo "the file the listener uses. Himalaya rejects a message with no From:." >&2
    exit 1
fi

case "$from_addr" in
    *@*) ;;
    *)  echo "sender address $from_addr has no domain — refusing to send" >&2
        exit 1 ;;
esac

# --- The headers that decide whether it is delivered -------------------------
#
# Adding From: got the message past Himalaya. It did not get it past Gmail, which
# accepted it over SMTP and then bounced it: "554 5.7.1 Rejected due to high
# probability of spam". A message carrying only From/To/Subject looks like bulk
# machinery, because every ordinary client sends the rest of these.
#
# Found end to end on a live v2 host (#23). Do not trim this list back to the
# ones that look required — the message that failed was the short one.

# Header values are ASCII by RFC 5322. Raw UTF-8 rides on an extension the
# receiving server has to advertise, and where it is merely tolerated it still
# reads as a spam signal — which is the failure this whole block exists to avoid.
# Nearly every subject this agent sends has an accent in it, so this path is the
# common one, not the edge case.
#
# One encoded-word, not the folded sequence RFC 2047 asks for above 75 characters.
# Long accented subjects therefore produce an overlong word; clients accept it,
# and splitting correctly means chunking the UTF-8 *before* base64 so no character
# straddles a boundary. Revisit if a real subject is ever rejected for length.
encode_header() {
    if printf '%s' "$1" | LC_ALL=C grep -q '[^ -~]'; then
        printf '=?UTF-8?B?%s?=' "$(printf '%s' "$1" | base64 -w0)"
    else
        printf '%s' "$1"
    fi
}

# RFC 5322 date, with the offset. `date -R` is exactly this format.
date_hdr=$(date -R)

# Enough entropy that two sends in the same second cannot collide. The domain
# half must be one we plausibly own, so take it from the sender.
msgid="<$(date -u +%Y%m%d%H%M%S).$$.${RANDOM}@${from_addr##*@}>"

# --- Attachments -------------------------------------------------------------
#
# Only computed when there is something to attach, so the no-attachment path
# stays exactly the message this script sent before: same headers, same order,
# single part. A separator that could appear in the content would truncate the
# message at that line, so it carries 128 bits of randomness and a prefix no
# body plausibly contains.
boundary=""
if [ ${#attachments[@]} -gt 0 ]; then
    boundary="=_paynani_$(openssl rand -hex 16)"
fi

# A filename is a header parameter, and the quoting rules that protect the From
# display name protect this too: a quote or a backslash in a filename would
# otherwise end the parameter early and let the rest be read as more parameters.
# Non-ASCII needs RFC 2231 rather than an encoded-word -- an encoded-word inside
# a quoted string stays literal, so an accented filename would arrive as the
# =?UTF-8?B?...?= text itself. Spanish filenames are the common case here, not
# the edge case.
percent_encode() {
    LC_ALL=C
    _paynani_s=$1
    _paynani_out=""
    _paynani_i=0
    while [ "$_paynani_i" -lt "${#_paynani_s}" ]; do
        _paynani_c=${_paynani_s:$_paynani_i:1}
        case "$_paynani_c" in
            [A-Za-z0-9._~-]) _paynani_out="$_paynani_out$_paynani_c" ;;
            *) _paynani_out="$_paynani_out$(printf '%%%02X' "'$_paynani_c")" ;;
        esac
        _paynani_i=$(( _paynani_i + 1 ))
    done
    printf '%s' "$_paynani_out"
}

attachment_part() {
    _paynani_path=$1
    _paynani_name=$(basename "$_paynani_path" | tr -d '\r\n')

    # file(1) is the only thing here that knows what the bytes are. When it has
    # no opinion, say so honestly rather than guessing a type the client would
    # then trust.
    _paynani_type=$(file --mime-type -b "$_paynani_path" 2>/dev/null || true)
    case "$_paynani_type" in
        ''|*[!!-~]*) _paynani_type=application/octet-stream ;;
    esac

    printf -- '--%s\n' "$boundary"
    printf 'Content-Type: %s\n' "$_paynani_type"
    printf 'Content-Transfer-Encoding: base64\n'
    if printf '%s' "$_paynani_name" | LC_ALL=C grep -q '[^ -~]'; then
        printf "Content-Disposition: attachment; filename*=UTF-8''%s\n" \
            "$(percent_encode "$_paynani_name")"
    else
        printf 'Content-Disposition: attachment; filename="%s"\n' \
            "$(printf '%s' "$_paynani_name" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
    fi
    printf '\n'
    # GNU base64 wraps at 76 already; BSD base64 does not wrap at all. Stripping
    # and re-folding gives the same output on both rather than one that depends
    # on which host the agent happens to be installed on.
    base64 < "$_paynani_path" | tr -d '\n' | fold -w 76
    printf '\n'
}

build_message() {
    printf 'Date: %s\n' "$date_hdr"
    printf 'Message-ID: %s\n' "$msgid"
    printf 'MIME-Version: 1.0\n'
    # The body is written as raw UTF-8 and sent as-is. Declaring 7bit here would
    # be a lie the moment anyone writes an accent, which in this project is most
    # messages. With attachments the same two lines move down onto the body part,
    # where they describe the body rather than the whole message.
    if [ -n "$boundary" ]; then
        printf 'Content-Type: multipart/mixed; boundary="%s"\n' "$boundary"
    else
        printf 'Content-Type: text/plain; charset=UTF-8\n'
        printf 'Content-Transfer-Encoding: 8bit\n'
    fi
    if [ -n "$from_name" ]; then
        if printf '%s' "$from_name" | LC_ALL=C grep -q '[^ -~]'; then
            # An encoded-word is not a quoted string and must not be quoted —
            # inside quotes it stays literal instead of decoding.
            printf 'From: %s <%s>\n' "$(encode_header "$from_name")" "$from_addr"
        else
            # Quote the display name and escape what would end the quoted string,
            # so a name containing a comma or a quote cannot restructure the header.
            printf 'From: "%s" <%s>\n' \
                "$(printf '%s' "$from_name" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')" \
                "$from_addr"
        fi
    else
        printf 'From: %s\n' "$from_addr"
    fi
    printf 'To: %s\n' "$to"
    if [ -n "$cc" ]; then
        printf 'Cc: %s\n' "$cc"
    fi
    printf 'Subject: %s\n' "$(encode_header "$subject")"
    printf '\n'
    if [ -z "$boundary" ]; then
        cat "$bodyfile"
        return
    fi
    printf -- '--%s\n' "$boundary"
    printf 'Content-Type: text/plain; charset=UTF-8\n'
    printf 'Content-Transfer-Encoding: 8bit\n'
    printf '\n'
    cat "$bodyfile"
    # A body file that does not end in a newline would otherwise put the closing
    # separator on the same line as its last word, and a separator that is not
    # alone on its line is not a separator.
    printf '\n'
    for _paynani_file in ${attachments[@]+"${attachments[@]}"}; do
        attachment_part "$_paynani_file"
    done
    printf -- '--%s--\n' "$boundary"
}

if [ -n "$check_only" ]; then
    build_message
    echo "check only — nothing sent" >&2
    exit 0
fi

build_message | himalaya message send -a "$ACCOUNT"

# --- What was sent, written down where it survives the process -----------------
#
# Until #117 this script's only record of a send was the line below, on stdout,
# which dies with the shell that ran it. Inbound, this project journals every
# message twice over so nothing can be lost silently; outbound it kept nothing,
# and the first agent asked whether it had sent something searched its whole
# mailbox and could not tell. An empty Sent folder and a message that never left
# look identical.
#
# Himalaya does not save a copy unless asked -- `--save <MAILBOX>` is opt-in, and
# sending is SMTP, which has no Sent folder at all; a copy there is a separate
# IMAP APPEND. So this is the only record that exists by default, and it is ours
# rather than the mail server's: readable with no network, and still true if the
# account is later lost.
#
# Deliberately not the body. The question a roster raises is who and when, and a
# log of message bodies is a mail password's worth of liability in a different
# shape. cc is part of "who" -- omitting it here would leave the audit this log
# exists for blind to half of what --cc was built to do.
#
# Written after the send, never before, so nothing here can claim a delivery that
# did not happen. A failure to write is reported and does not fail the command:
# the mail has already gone, and exiting nonzero would report a failed send for
# one that succeeded -- which is the mistake this whole change exists to stop
# people making in the other direction.
sent_log="$(paynani_state_dir)/sent.log"
if ! {
    mkdir -p "$(dirname "$sent_log")" &&
    printf '%s\tto=%s\tcc=%s\tsubject=%s\tmessage-id=%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$to" "$cc" "$subject" "$msgid" >> "$sent_log"
} 2>/dev/null; then
    echo "warning: sent, but could not record it in $sent_log" >&2
fi

if [ -n "$cc" ]; then
    echo "sent to $to (cc $cc)"
else
    echo "sent to $to"
fi
