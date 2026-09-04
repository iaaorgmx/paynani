#!/usr/bin/env bash
# Exercises send.sh without sending anything: who it will write to, and what it
# hands Himalaya when it does.
#
# The allowlist half exists because that list is the only thing standing between
# an agent that reads untrusted mail and an agent that can be talked into sending
# it. A path change once broke the lookup silently — it failed closed, so nothing
# was exposed, but nothing was caught either.
#
# The message half exists because the first half is not enough. Himalaya is faked
# here, so "the gate let it through" proves nothing about whether real mail would
# leave: a missing From: header made every live send fail on Himalaya v2 while
# this suite reported 11/11 (issue #23). Run this after touching send.sh or the
# roster format.
#
#   scripts/test_roster.sh

set -uo pipefail

SEND="$(cd "$(dirname "$0")" && pwd)/send.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

roster="$tmp/roster.md"
body="$tmp/body.txt"
echo "hi" >"$body"

> "$tmp/sent.eml"
export CAPTURE="$tmp/sent.eml"

# The fake Himalaya keeps what it was given. Before it did, this suite could pass
# while every real send failed: the allowlist was tested and the message handed to
# Himalaya never was, which is how a missing From: header survived to issue #23.
fakebin="$tmp/bin"
mkdir -p "$fakebin"
cat >"$fakebin/himalaya" <<'EOF'
#!/usr/bin/env bash
cat >"$CAPTURE"
exit 0
EOF
chmod +x "$fakebin/himalaya"
export PATH="$fakebin:$PATH"

# send.sh needs a sender, and reads it from the same env file the listener uses.
# Written with CRLF and a BOM on purpose — both appear in real installs.
envfile="$tmp/env"
printf '\xef\xbb\xbfPAYNANI_EMAIL=agent@example.com\r\nPAYNANI_PASSWORD=not-read-here\r\n' >"$envfile"
export ENV_FILE="$envfile"

cat >"$roster" <<'EOF'
# Comment that should never match.
#
# Format: | Name | Email | Type |

# 1. Approved contacts; any other contact/email address will be ignored.
| Name | Email | Type |
| --- | --- | --- |
| Julian Flores | jjulianfe@gmail.com | Human |
| Second Contact | second_contact@example.org | AI Agent |
| AI Agent | Reordered Contact | reordered@example.net |
bare-address-still-works@example.com
EOF

pass=0; fail=0

# Returns 0 only when the address got past the roster check. A fake Himalaya is
# first in PATH so the test never sends real mail on a configured machine.
allowed() {
    "$SEND" "$1" "subject" "$body" >/dev/null 2>&1
    case $? in
        1|2) return 1 ;;   # blocked
        *)   return 0 ;;   # got through the gate
    esac
}

check() {
    local want=$1 addr=$2 desc=$3
    if allowed "$addr"; then got=allow; else got=refuse; fi
    if [ "$got" = "$want" ]; then
        printf '  PASS  %-8s %s\n' "$want" "$desc"; pass=$((pass+1))
    else
        printf '  FAIL  wanted %s got %s — %s\n' "$want" "$got" "$desc"; fail=$((fail+1))
    fi
}

export ROSTER="$roster"

check allow  "jjulianfe@gmail.com"                         "listed as Name | email"
check allow  "second_contact@example.org"                  "second listed contact"
check allow  "reordered@example.net"                       "reordered table row"
check allow  "bare-address-still-works@example.com"        "line with no Name | prefix"
check allow  "JJulianFe@Gmail.com"                         "case-insensitive"

check refuse "stranger@example.com"                        "not listed at all"
check refuse "evil-jjulianfe@gmail.com"                    "substring of a listed address"
check refuse "jjulianfe@gmail.com.attacker.net"            "listed address as a prefix"
check refuse "Julian Flores"                               "the name, not the address"
check refuse "Julian Flores | jjulianfe@gmail.com | Human" "the whole roster line verbatim"
check refuse ""                                            "empty recipient"

# A missing roster must refuse, not fall open.
ROSTER="$tmp/does-not-exist.txt" check refuse "jjulianfe@gmail.com" "roster file missing"

# --- The shipped template's format, not just "Name | email" -----------------
#
# roster.md.example is a full markdown table -- leading "|", a Type column,
# and a trailing "|" -- which is exactly the shape that broke "take the field
# after the last |": the last field there is "Human", not the address. #88's
# sibling defect. This roster is the example file verbatim.
table_roster="$tmp/roster-table.md"
cat >"$table_roster" <<'EOF'
# The people this agent works for.

| Name | Email | Type |
|---|---|---|
| Julian Flores | jjulianfe@gmail.com | Human |
| Metis Claude-Tob | metis.claude.tob@gmail.com | AI Agent |
EOF

ROSTER="$table_roster" check allow  "jjulianfe@gmail.com"          "table row, address before Type"
ROSTER="$table_roster" check allow  "metis.claude.tob@gmail.com"   "second table row"
ROSTER="$table_roster" check allow  "JJulianFe@Gmail.com"          "table row, case-insensitive"
ROSTER="$table_roster" check refuse "Human"                        "the Type column, not the address"
ROSTER="$table_roster" check refuse "stranger@example.com"         "not on the table roster"

# --- The message Himalaya actually receives ----------------------------------
#
# Himalaya v2 rejects a raw message with no From:, so "the gate let it through"
# is not the same as "the mail went out". These assert on the captured bytes.

echo

assert() {
    local desc=$1 cond=$2
    if eval "$cond"; then
        printf '  PASS  %-8s %s\n' "message" "$desc"; pass=$((pass+1))
    else
        printf '  FAIL  %-8s %s\n' "message" "$desc"; fail=$((fail+1))
    fi
}

send_ok() { "$SEND" "$@" >/dev/null 2>&1; }

: >"$CAPTURE"
send_ok "jjulianfe@gmail.com" "Prueba de correo — ñ, á" "$body"

assert "From: header is present"        'grep -q "^From: " "$CAPTURE"'
assert "From: carries the env address"  'grep -qx "From: agent@example.com" "$CAPTURE"'
assert "From: comes before To:"         '[ "$(grep -n -m1 "^From: " "$CAPTURE" | cut -d: -f1)" -lt "$(grep -n -m1 "^To: " "$CAPTURE" | cut -d: -f1)" ]'
assert "To: is the approved recipient"  'grep -qx "To: jjulianfe@gmail.com" "$CAPTURE"'
assert "direct human recipient is not duplicated as Cc" '! grep -q "^Cc: " "$CAPTURE"'
assert "accented Subject is encoded"    'grep -qE "^Subject: =\?UTF-8\?B\?[A-Za-z0-9+/=]+\?=\$" "$CAPTURE"'
assert "encoded Subject round-trips"    '[ "$(grep -m1 "^Subject: " "$CAPTURE" | sed -e "s/^Subject: =?UTF-8?B?//" -e "s/?=\$//" | base64 -d)" = "Prueba de correo — ñ, á" ]'
assert "blank line separates the body"  'awk "/^\$/{found=1} END{exit !found}" "$CAPTURE"'
assert "body is last"                   '[ "$(tail -1 "$CAPTURE")" = "hi" ]'

# Gmail accepted the From:-only message over SMTP and then bounced it as spam.
# These are the headers that made the difference on the live host in #23.
assert "Date: is RFC 5322"              'grep -qE "^Date: [A-Z][a-z]{2}, [0-9]{1,2} [A-Z][a-z]{2} [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} [+-][0-9]{4}\$" "$CAPTURE"'
assert "Message-ID: is bracketed"       'grep -qE "^Message-ID: <[^<> ]+@[^<> ]+>\$" "$CAPTURE"'
assert "Message-ID: uses sender domain" 'grep -qE "^Message-ID: <.*@example\.com>\$" "$CAPTURE"'
assert "MIME-Version: 1.0"              'grep -qx "MIME-Version: 1.0" "$CAPTURE"'
assert "Content-Type is UTF-8 plain"    'grep -qx "Content-Type: text/plain; charset=UTF-8" "$CAPTURE"'
assert "8bit, matching the raw body"    'grep -qx "Content-Transfer-Encoding: 8bit" "$CAPTURE"'

# Two messages in the same second must not share an ID.
first_id=$(grep -m1 "^Message-ID: " "$CAPTURE")
: >"$CAPTURE"
send_ok "jjulianfe@gmail.com" "second" "$body"
assert "Message-ID differs per send"    '[ "$first_id" != "$(grep -m1 "^Message-ID: " "$CAPTURE")" ]'

: >"$CAPTURE"
send_ok "second_contact@example.org" "cc check" "$body"
assert "Type is informational and does not add Cc" '! grep -q "^Cc:" "$CAPTURE"'

# A sender with no domain would produce a nonsense Message-ID; refuse instead.
printf 'PAYNANI_EMAIL=agent-without-a-domain\n' >"$tmp/env-nodomain"
: >"$CAPTURE"
ENV_FILE="$tmp/env-nodomain" send_ok "jjulianfe@gmail.com" "subject" "$body" && nd=0 || nd=$?
assert "sender with no domain exits 1"  '[ "${nd:-0}" -eq 1 ] && [ ! -s "$CAPTURE" ]'

# --- --cc is held to the same allowlist as <to> -------------------------------
#
# A Cc is still an address this agent writes to. Letting it bypass the roster
# would reopen exactly what the roster exists to close, just on a header nobody
# thought to check.
: >"$CAPTURE"
send_ok --cc "second_contact@example.org" "jjulianfe@gmail.com" "subject" "$body"
assert "--cc adds a Cc: header"           'grep -qx "Cc: second_contact@example.org" "$CAPTURE"'
assert "--cc comes after To:"             '[ "$(grep -n -m1 "^To: " "$CAPTURE" | cut -d: -f1)" -lt "$(grep -n -m1 "^Cc: " "$CAPTURE" | cut -d: -f1)" ]'

: >"$CAPTURE"
"$SEND" --cc "stranger@example.com" "jjulianfe@gmail.com" "subject" "$body" >/dev/null 2>&1 && ccrc=0 || ccrc=$?
assert "--cc to an unlisted address is refused" '[ "${ccrc:-0}" -eq 2 ] && [ ! -s "$CAPTURE" ]'

: >"$CAPTURE"
send_ok "jjulianfe@gmail.com" "subject" "$body"
assert "no --cc means no Cc: header"      '! grep -q "^Cc:" "$CAPTURE"'

# A newline in --cc must not become a second header, same as subject.
: >"$CAPTURE"
send_ok --cc "$(printf 'second_contact@example.org\nBcc: evil@example.com')" "jjulianfe@gmail.com" "subject" "$body"
assert "no header injection via --cc"     '! grep -qi "^Bcc:" "$CAPTURE"'

# --check is how an install proves send.sh can find its credentials. The roster
# tests cannot: the gate runs first, so a refusal exits before the env is read.
: >"$CAPTURE"
checked=$("$SEND" --check "jjulianfe@gmail.com" "Prueba de correo — ñ, á" "$body" 2>/dev/null)
assert "--check prints the message"     'printf "%s" "$checked" | grep -q "^From: agent@example.com\$"'
assert "--check sends nothing"          '[ ! -s "$CAPTURE" ]'
assert "--check still obeys the roster" '! "$SEND" --check "stranger@example.com" "s" "$body" >/dev/null 2>&1'

: >"$CAPTURE"
send_ok "jjulianfe@gmail.com" "Prueba de correo — ñ, á" "$body"

# A display name must be quoted, and a comma inside it must not split the header.
printf 'PAYNANI_EMAIL=agent@example.com\nPAYNANI_FROM_NAME=Flores, Julian\n' >"$tmp/env-name"
: >"$CAPTURE"
ENV_FILE="$tmp/env-name" send_ok "jjulianfe@gmail.com" "subject" "$body"
assert "display name is quoted"         'grep -qx "From: \"Flores, Julian\" <agent@example.com>" "$CAPTURE"'

# A plain-ASCII subject must stay readable rather than being base64'd for nothing.
: >"$CAPTURE"
send_ok "jjulianfe@gmail.com" "Plain ascii subject" "$body"
assert "ASCII Subject stays literal"    'grep -qx "Subject: Plain ascii subject" "$CAPTURE"'

# An accented display name is an encoded-word, and an encoded-word inside quotes
# does not decode — so it must not be quoted.
printf 'PAYNANI_EMAIL=agent@example.com\nPAYNANI_FROM_NAME=José Ñuño\n' >"$tmp/env-utf8name"
: >"$CAPTURE"
ENV_FILE="$tmp/env-utf8name" send_ok "jjulianfe@gmail.com" "subject" "$body"
assert "accented name is encoded"       'grep -qE "^From: =\?UTF-8\?B\?[A-Za-z0-9+/=]+\?= <agent@example.com>\$" "$CAPTURE"'
assert "encoded name round-trips"       '[ "$(grep -m1 "^From: " "$CAPTURE" | sed -e "s/^From: =?UTF-8?B?//" -e "s/?= <.*\$//" | base64 -d)" = "José Ñuño" ]'

# Schema B is the OpenClaw workspace .env, and must work the same way.
printf 'AGENT_EMAIL_ACCOUNT=agent@example.com\n' >"$tmp/env-b"
: >"$CAPTURE"
ENV_FILE="$tmp/env-b" send_ok "jjulianfe@gmail.com" "subject" "$body"
assert "falls back to AGENT_EMAIL_ACCOUNT" 'grep -qx "From: agent@example.com" "$CAPTURE"'

# No sender configured must fail loudly rather than hand Himalaya a bad message.
: >"$CAPTURE"
ENV_FILE="$tmp/no-such-env" send_ok "jjulianfe@gmail.com" "subject" "$body" && rc=0 || rc=$?
assert "missing sender exits 1"         '[ "${rc:-0}" -eq 1 ]'
assert "missing sender sends nothing"   '[ ! -s "$CAPTURE" ]'

# A newline in the subject must not become a second header. The subject is built
# from mail the agent was told to act on, so this is reachable from outside.
: >"$CAPTURE"
send_ok "jjulianfe@gmail.com" "$(printf 'Test\nBcc: evil@example.com')" "$body"
assert "no header injection via subject" '! grep -qi "^Bcc:" "$CAPTURE"'

# --- What was sent is written down ---------------------------------------------
#
# #117: the only record of a send used to be a line on stdout that died with the
# process, so an agent asked whether it had sent something searched its whole
# mailbox and could not tell. Himalaya saves no copy unless asked, and sending is
# SMTP, which has no Sent folder at all -- so this log is the only record that
# exists by default.
sent_state="$tmp/sentlog-state"
sent_log="$sent_state/sent.log"

PAYNANI_STATE="$sent_state" send_ok "jjulianfe@gmail.com" "Acentuación ñ" "$body"
assert "a send is recorded"             '[ -s "$sent_log" ]'
assert "the record is one line"         '[ "$(wc -l <"$sent_log")" -eq 1 ]'
assert "the record names the recipient" 'grep -q "to=jjulianfe@gmail.com" "$sent_log"'
assert "the record carries the subject" 'grep -q "subject=Acentuación ñ" "$sent_log"'
assert "the record carries a message-id that matches what was sent" \
    '[ "$(sed -n "s/.*message-id=//p" "$sent_log")" = "$(grep -m1 "^Message-ID: " "$CAPTURE" | sed "s/^Message-ID: //")" ]'

# Appended, not replaced. A log that keeps only the last send answers "did I ever
# write to them" with "no" for everyone but the most recent recipient.
PAYNANI_STATE="$sent_state" send_ok "jjulianfe@gmail.com" "second" "$body"
assert "a second send appends"          '[ "$(wc -l <"$sent_log")" -eq 2 ]'

# --check must never record anything. A log entry for a message that was
# deliberately not sent is worse than no log at all: it is a false record of an
# action, in the file whose whole purpose is to be believed.
rm -rf "$sent_state"
PAYNANI_STATE="$sent_state" "$SEND" --check "jjulianfe@gmail.com" "not sent" "$body" >/dev/null 2>&1
assert "--check records nothing"        '[ ! -e "$sent_log" ]'

# --cc is part of "who", so the audit log this exists for must not go blind to
# it -- the whole point of #117 was that "who was this sent to" had to be
# answerable from the log alone.
rm -rf "$sent_state"
PAYNANI_STATE="$sent_state" send_ok --cc "second_contact@example.org" "jjulianfe@gmail.com" "with cc" "$body"
assert "the record names the cc"        'grep -q "cc=second_contact@example.org" "$sent_log"'
assert "message-id stays last with a cc" \
    '[ "$(sed -n "s/.*message-id=//p" "$sent_log")" = "$(grep -m1 "^Message-ID: " "$CAPTURE" | sed "s/^Message-ID: //")" ]'

# --- Attachments ---------------------------------------------------------------
#
# #38: send.sh built a single-part text/plain and nothing else, so a field report
# that came with a document had to be pasted into the body. Text survives that;
# a screenshot or a PDF has no way through at all.
#
# The first assertion is the one that matters most: a message with no --attach
# must still be the message this script sent before, because every send this
# project makes today is that one.
attach_dir="$tmp/attach"
mkdir -p "$attach_dir"
printf 'col1,col2\n1,2\n' >"$attach_dir/datos.csv"
printf 'segundo archivo\n' >"$attach_dir/otro.txt"

: >"$CAPTURE"
send_ok "jjulianfe@gmail.com" "sin adjuntos" "$body"
assert "no --attach stays single-part"     'grep -qx "Content-Type: text/plain; charset=UTF-8" "$CAPTURE"'
assert "no --attach declares no boundary"  '! grep -q "boundary=" "$CAPTURE"'

: >"$CAPTURE"
send_ok --attach "$attach_dir/datos.csv" "jjulianfe@gmail.com" "con adjunto" "$body"
assert "--attach makes it multipart/mixed" 'grep -qE "^Content-Type: multipart/mixed; boundary=\"=_paynani_[0-9a-f]{32}\"\$" "$CAPTURE"'
assert "the body survives as a part"       'grep -qx "hi" "$CAPTURE"'
assert "the attachment is base64"          'grep -qx "Content-Transfer-Encoding: base64" "$CAPTURE"'
assert "the attachment is named"           'grep -qx "Content-Disposition: attachment; filename=\"datos.csv\"" "$CAPTURE"'
assert "file(1) supplies the type"         'grep -qx "Content-Type: text/csv" "$CAPTURE"'
assert "the closing separator is present"  'grep -qE "^--=_paynani_[0-9a-f]{32}--\$" "$CAPTURE"'

# The bytes have to come back out. Everything above could pass on a message whose
# attachment decoded to something else, or to nothing.
assert "the attachment round-trips" \
    'python3 -c "
import email, email.policy, sys
m = email.message_from_binary_file(open(sys.argv[1], \"rb\"), policy=email.policy.default)
parts = [p for p in m.walk() if p.get_content_disposition() == \"attachment\"]
assert len(parts) == 1, parts
assert parts[0].get_filename() == \"datos.csv\"
assert parts[0].get_payload(decode=True) == b\"col1,col2\n1,2\n\"
" "$CAPTURE"'

: >"$CAPTURE"
send_ok --attach "$attach_dir/datos.csv" --attach "$attach_dir/otro.txt" \
    "jjulianfe@gmail.com" "dos adjuntos" "$body"
assert "--attach repeats, in order" \
    'python3 -c "
import email, email.policy, sys
m = email.message_from_binary_file(open(sys.argv[1], \"rb\"), policy=email.policy.default)
names = [p.get_filename() for p in m.walk() if p.get_content_disposition() == \"attachment\"]
assert names == [\"datos.csv\", \"otro.txt\"], names
" "$CAPTURE"'

# An accented filename is the common case in this project, not the edge case. An
# encoded-word inside a quoted string stays literal, so this needs RFC 2231.
cp "$attach_dir/datos.csv" "$attach_dir/reporte señales.csv"
: >"$CAPTURE"
send_ok --attach "$attach_dir/reporte señales.csv" "jjulianfe@gmail.com" "acentos" "$body"
assert "an accented filename uses RFC 2231" 'grep -q "filename\*=UTF-8'"''"'" "$CAPTURE"'
assert "an accented filename round-trips" \
    'python3 -c "
import email, email.policy, sys
m = email.message_from_binary_file(open(sys.argv[1], \"rb\"), policy=email.policy.default)
names = [p.get_filename() for p in m.walk() if p.get_content_disposition() == \"attachment\"]
assert names == [\"reporte señales.csv\"], names
" "$CAPTURE"'

# A path that cannot be read must stop the whole send, not produce a message with
# a hole in it.
: >"$CAPTURE"
"$SEND" --attach "$attach_dir/does-not-exist.pdf" "jjulianfe@gmail.com" "subject" "$body" >/dev/null 2>&1 && arc=0 || arc=$?
assert "a missing attachment exits 2"      '[ "${arc:-0}" -eq 2 ]'
assert "a missing attachment sends nothing" '[ ! -s "$CAPTURE" ]'

# --- The shipped template authorises nobody -----------------------------------
#
# roster.md.example used to carry two real, working addresses as data rows, so
# `cp roster.md.example roster.md` -- the step INSTALL.md gives -- handed two
# real people standing unattended authority on any install that followed it,
# without the operator having decided anything. INSTALL.md says of that copy:
# "Until you add a line it is empty, and an empty roster means you can send to
# nobody." This asserts that sentence is true of the file actually shipped.
#
# Checked through roster.py rather than by grepping for "@": the parser is what
# decides who is authorised, so it is the only thing whose answer counts.
#
# The header and separator rows stay -- they carry the format, and neither holds
# an "@", so neither contributes an address.
repo=$(cd "$(dirname "$SEND")/.." && pwd)
template_addrs=$(python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/scripts")
import roster
print(" ".join(sorted(roster.roster_addresses(Path(sys.argv[1]) / "roster.md.example"))))
' "$repo")
assert "shipped template contributes no addresses" '[ -z "$template_addrs" ]'

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
