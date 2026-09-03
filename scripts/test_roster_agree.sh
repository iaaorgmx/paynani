#!/usr/bin/env bash
# Cross-checks scripts/roster_extract.sh (send.sh's own address extraction)
# against scripts/roster.py's roster_addresses() on a set of fixture rosters.
#
# #91 happened because send.sh and roster.py each implemented "find the field
# containing @" independently, and nothing asserted they agreed -- roster.py
# was fixed for the table format and send.sh was not, so the drift shipped in
# a tagged release. This is that assertion. #98.
#
# Two implementations that both silently return nothing "agree" with each
# other while catching nothing. #90 fixed test_paths.sh for exactly this: a
# cross-check that cannot tell "agreed" from "neither ran" reports 0 failed
# either way. So every fixture also pins a specific address that must appear
# on both sides independently, not just that the two sides match each other.
#
#   scripts/test_roster_agree.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXTRACT="$ROOT/scripts/roster_extract.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

pass=0
fail=0

py_addresses() {  # roster-file
    python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
import roster
print("\n".join(sorted(roster.roster_addresses(Path(sys.argv[1])))))
' "$1" "$ROOT/scripts"
}

sh_addresses() {  # roster-file
    "$EXTRACT" "$1" | sort -u
}

agree() {  # description, roster-file, an-address-that-must-be-found
    local desc=$1 file=$2 expect=$3
    local p s

    if ! p=$(py_addresses "$file"); then
        printf 'FAIL %s: python3 roster.roster_addresses() errored\n' "$desc"
        fail=$((fail + 1))
        return
    fi
    if ! s=$(sh_addresses "$file"); then
        printf 'FAIL %s: roster_extract.sh errored\n' "$desc"
        fail=$((fail + 1))
        return
    fi

    if [ "$p" = "$s" ]; then
        printf 'ok   %s: shell agrees with python\n' "$desc"
        pass=$((pass + 1))
    else
        printf 'FAIL %s: shell disagrees with python\n       python: %s\n       shell:  %s\n' \
            "$desc" "$(echo "$p" | tr '\n' ',')" "$(echo "$s" | tr '\n' ',')"
        fail=$((fail + 1))
    fi

    # Pinned independently on each side: a fixture where both sides silently
    # produce nothing would otherwise "agree" and pass, catching nothing.
    if printf '%s\n' "$p" | grep -qxF "$expect"; then
        pass=$((pass + 1))
    else
        printf 'FAIL %s: python did not find %s\n' "$desc" "$expect"
        fail=$((fail + 1))
    fi
    if printf '%s\n' "$s" | grep -qxF "$expect"; then
        pass=$((pass + 1))
    else
        printf 'FAIL %s: shell did not find %s\n' "$desc" "$expect"
        fail=$((fail + 1))
    fi
}

# --- Plain two-field format: "Name | email", no header, no Type column. -----
f="$tmp/plain.md"
cat >"$f" <<'EOF'
Julian Flores | jjulianfe@gmail.com
Metis Claude-Tob | metis.claude.tob@gmail.com
EOF
agree "plain two-field" "$f" "jjulianfe@gmail.com"

# --- The shipped table shape: header, separator, Type column, outer pipes.
# This is the exact shape #91 broke on -- "take the last field" reads "Human". -
f="$tmp/table.md"
cat >"$f" <<'EOF'
| Name | Email | Type |
|---|---|---|
| Julian Flores | jjulianfe@gmail.com | Human |
| Metis Claude-Tob | metis.claude.tob@gmail.com | AI Agent |
EOF
agree "full table" "$f" "metis.claude.tob@gmail.com"

# --- A bare address, no pipes at all. ----------------------------------------
f="$tmp/bare.md"
printf 'bare-address@example.com\n' >"$f"
agree "bare address" "$f" "bare-address@example.com"

# --- CRLF-terminated rows -- real installs have shipped these. --------------
f="$tmp/crlf.md"
printf '| Name | Email | Type |\r\n|---|---|---|\r\n| Julian Flores | jjulianfe@gmail.com | Human |\r\n' >"$f"
agree "CRLF-terminated table" "$f" "jjulianfe@gmail.com"

# --- Reordered columns: the address is not the last field. -------------------
f="$tmp/reordered.md"
printf '| AI Agent | Reordered Contact | reordered@example.net |\n' >"$f"
agree "reordered row" "$f" "reordered@example.net"

# --- A missing roster: both sides must agree on nobody, not error into a
# false agreement (an empty python output and a hard shell failure would
# otherwise both look like "no addresses"). --------------------------------
missing="$tmp/does-not-exist.md"
p=$(py_addresses "$missing")
s_out=$("$EXTRACT" "$missing" 2>&1); s_rc=$?
if [ -z "$p" ] && [ "$s_rc" -eq 0 ] && [ -z "$s_out" ]; then
    printf 'ok   missing roster: both sides say nobody, cleanly\n'
    pass=$((pass + 1))
else
    printf 'FAIL missing roster: python=%q shell_rc=%s shell_out=%q\n' "$p" "$s_rc" "$s_out"
    fail=$((fail + 1))
fi

# --- The himalaya account name, spelled in shell and in python. -------------
#
# send.sh sends with `himalaya message send -a <account>` and healthcheck.py
# reports a problem when that account has no block in the himalaya config (#6).
# The name is written out in both files because one is shell and the other is
# python -- the same shape as the roster parsers above, and the same failure if
# they drift: healthcheck would look for an account nobody sends with and call
# an install healthy that cannot send at all.
sh_account=$(sed -n 's/^ACCOUNT="\(.*\)"$/\1/p' "$ROOT/scripts/send.sh" | head -1)
py_account=$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import healthcheck
print(healthcheck.SEND_ACCOUNT)
' "$ROOT/scripts")

if [ -n "$sh_account" ] && [ "$sh_account" = "$py_account" ]; then
    printf 'ok   himalaya account: send.sh and healthcheck.py agree on %s\n' "$sh_account"
    pass=$((pass + 1))
else
    printf 'FAIL himalaya account: send.sh=%q healthcheck.py=%q\n' "$sh_account" "$py_account"
    fail=$((fail + 1))
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
