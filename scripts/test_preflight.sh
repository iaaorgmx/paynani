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

# ---------------------------------------------------------------------------
# No credentials file, no terminal: the case an agent actually hits.
# ---------------------------------------------------------------------------
out=$(PAYNANI_ENV="$tmp/missing" timeout 20 python3 "$PREFLIGHT" </dev/null 2>&1)
status=$?

check "no credentials: exits 1" "1" "$status"
check "no credentials: does not prompt for a host" "no" \
    "$(case $out in *"IMAP host:"*) echo yes ;; *) echo no ;; esac)"
check "no credentials: names the file it looked in" "yes" \
    "$(case $out in *"$tmp/missing"*) echo yes ;; *) echo no ;; esac)"
check "no credentials: points at the setup form" "yes" \
    "$(case $out in *setup_web.sh*) echo yes ;; *) echo no ;; esac)"
check "no credentials: says which step it belongs to" "yes" \
    "$(case $out in *"AGENTS.md step 2"*) echo yes ;; *) echo no ;; esac)"

# ---------------------------------------------------------------------------
# A file that exists but holds nothing useful is the same situation.
# ---------------------------------------------------------------------------
printf '# nothing here yet\n\n' >"$tmp/empty"
out=$(PAYNANI_ENV="$tmp/empty" timeout 20 python3 "$PREFLIGHT" </dev/null 2>&1)
check "empty credentials file: treated as nothing to check" "yes" \
    "$(case $out in *"nothing to check yet"*) echo yes ;; *) echo no ;; esac)"

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
out=$(PAYNANI_ENV="$tmp/env" timeout 30 python3 "$PREFLIGHT" </dev/null 2>&1)
check "settings present: gets past the guard" "no" \
    "$(case $out in *"nothing to check yet"*) echo yes ;; *) echo no ;; esac)"
check "settings present: actually tries the server" "yes" \
    "$(case $out in *no-such-host.invalid*) echo yes ;; *) echo no ;; esac)"

# ---------------------------------------------------------------------------
# --help answers without opening a socket (issue #7).
#
# Run with the same settings as the check above, whose host is unresolvable and
# therefore names itself in the output the moment the network is touched. So
# "does not mention the host" is a real assertion here and not a tautology.
# ---------------------------------------------------------------------------
out=$(PAYNANI_ENV="$tmp/env" timeout 20 python3 "$PREFLIGHT" --help </dev/null 2>&1)
status=$?

check "--help: exits 0" "0" "$status"
check "--help: prints the usage line" "yes" \
    "$(case $out in *"Usage:"*) echo yes ;; *) echo no ;; esac)"
check "--help: does not connect" "no" \
    "$(case $out in *no-such-host.invalid*) echo yes ;; *) echo no ;; esac)"

out=$(PAYNANI_ENV="$tmp/env" timeout 20 python3 "$PREFLIGHT" -h </dev/null 2>&1)
check "-h: same as --help" "yes" \
    "$(case $out in *"Usage:"*) echo yes ;; *) echo no ;; esac)"

# An unknown flag is refused rather than ignored: silently doing nothing leaves
# the caller believing it took effect.
out=$(PAYNANI_ENV="$tmp/env" timeout 20 python3 "$PREFLIGHT" --no-such-flag </dev/null 2>&1)
status=$?

check "unknown flag: exits 2" "2" "$status"
check "unknown flag: names the argument" "yes" \
    "$(case $out in *--no-such-flag*) echo yes ;; *) echo no ;; esac)"
check "unknown flag: does not connect" "no" \
    "$(case $out in *no-such-host.invalid*) echo yes ;; *) echo no ;; esac)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
