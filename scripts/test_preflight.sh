#!/usr/bin/env bash
# What preflight says when it is run before there is anything to check.
#
# This is the failure an agent meets on a host with no mailbox, which is exactly
# the host the setup form exists for. It used to fall through to a prompt, find
# no terminal, and exit complaining about a missing IMAP host (issue #31). An
# agent following AGENTS.md, which says to stop on failure and not work around
# it, stopped there and never reached the form.
#
# The connection checks themselves need a real server and are not exercised here.
#
#   scripts/test_preflight.sh

set -uo pipefail

PREFLIGHT="$(cd "$(dirname "$0")" && pwd)/preflight.py"
pass=0
fail=0

check() {   # description, expected, actual
    if [ "$2" = "$3" ]; then
        printf 'ok   %s\n' "$1"
        pass=$((pass + 1))
    else
        printf 'FAIL %s\n       expected: %s\n       actual:   %s\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# `case` inside `$( )` is the shape that broke this whole file on macOS.
#
# bash 3.2 closes the command substitution at the first unbalanced `)`, and a
# case pattern -- `*"IMAP host:"*)` -- is exactly that. The whole file was a
# syntax error on any host with bash 3.2, which is every stock macOS, and the
# suite reported `syntax error near unexpected token 'newline'` rather than a
# failing assertion. bash 5 parses it, so nothing showed on Linux.
#
# Moving the case into a function body is the fix: the substitution now wraps a
# plain call, and the pattern's `)` is nowhere near it.
contains() {
	case "$1" in
		*"$2"*) echo yes ;;
		*)      echo no  ;;
	esac
}

# `timeout` is GNU coreutils and macOS does not ship it, so a bare `timeout 20`
# here is a command that is not there -- exit 127, and every assertion about the
# real exit status fails for a reason that has nothing to do with preflight.
# Same trade as scripts/version.sh made for #68: keep the ceiling where the tool
# exists, run without it where it does not. A test that runs unbounded beats one
# that cannot run.
limit=()
if command -v timeout >/dev/null 2>&1; then
	limit=(timeout 20)
elif command -v gtimeout >/dev/null 2>&1; then
	limit=(gtimeout 20)
fi


# ---------------------------------------------------------------------------
# No credentials file, no terminal: the case an agent actually hits.
# ---------------------------------------------------------------------------
out=$(PAYNANI_ENV="$tmp/missing" ${limit[@]+"${limit[@]}"} python3 "$PREFLIGHT" </dev/null 2>&1)
status=$?

check "no credentials: exits 1" "1" "$status"
check "no credentials: does not prompt for a host" "no" \
    "$(contains "$out" "IMAP host:")"
check "no credentials: names the file it looked in" "yes" \
    "$(contains "$out" "$tmp/missing")"
check "no credentials: points at the setup form" "yes" \
    "$(contains "$out" setup_web.sh)"
check "no credentials: says which step it belongs to" "yes" \
    "$(contains "$out" "AGENTS.md step 2")"

# ---------------------------------------------------------------------------
# A file that exists but holds nothing useful is the same situation.
# ---------------------------------------------------------------------------
printf '# nothing here yet\n\n' >"$tmp/empty"
out=$(PAYNANI_ENV="$tmp/empty" ${limit[@]+"${limit[@]}"} python3 "$PREFLIGHT" </dev/null 2>&1)
check "empty credentials file: treated as nothing to check" "yes" \
    "$(contains "$out" "nothing to check yet")"

# ---------------------------------------------------------------------------
# With settings present it must get past the guard and actually try the server.
# A host that cannot resolve proves it stopped guarding and started checking.
# ---------------------------------------------------------------------------
cat >"$tmp/env" <<'EOF'
PAYNANI_IMAP_HOST=no-such-host.invalid
PAYNANI_IMAP_PORT=993
PAYNANI_EMAIL=agent@example.com
PAYNANI_PASSWORD=not-used
EOF
out=$(PAYNANI_ENV="$tmp/env" ${limit[@]+"${limit[@]}"} python3 "$PREFLIGHT" </dev/null 2>&1)
check "settings present: gets past the guard" "no" \
    "$(contains "$out" "nothing to check yet")"
check "settings present: actually tries the server" "yes" \
    "$(contains "$out" no-such-host.invalid)"

# ---------------------------------------------------------------------------
# --help answers without opening a socket (issue #7).
#
# Run with the same settings as the check above, whose host is unresolvable and
# therefore names itself in the output the moment the network is touched. So
# "does not mention the host" is a real assertion here and not a tautology.
# ---------------------------------------------------------------------------
out=$(PAYNANI_ENV="$tmp/env" ${limit[@]+"${limit[@]}"} python3 "$PREFLIGHT" --help </dev/null 2>&1)
status=$?

check "--help: exits 0" "0" "$status"
check "--help: prints the usage line" "yes" \
    "$(contains "$out" "Usage:")"
check "--help: does not connect" "no" \
    "$(contains "$out" no-such-host.invalid)"

out=$(PAYNANI_ENV="$tmp/env" ${limit[@]+"${limit[@]}"} python3 "$PREFLIGHT" -h </dev/null 2>&1)
check "-h: same as --help" "yes" \
    "$(contains "$out" "Usage:")"

# An unknown flag is refused rather than ignored: silently doing nothing leaves
# the caller believing it took effect.
out=$(PAYNANI_ENV="$tmp/env" ${limit[@]+"${limit[@]}"} python3 "$PREFLIGHT" --no-such-flag </dev/null 2>&1)
status=$?

check "unknown flag: exits 2" "2" "$status"
check "unknown flag: names the argument" "yes" \
    "$(contains "$out" --no-such-flag)"
check "unknown flag: does not connect" "no" \
    "$(contains "$out" no-such-host.invalid)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
