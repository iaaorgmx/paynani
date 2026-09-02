#!/usr/bin/env bash
# The address extraction send.sh's roster gate performs, factored out of it so
# a test can invoke exactly what send.sh runs -- not a hand-copied
# re-implementation that could itself drift from send.sh the way send.sh once
# drifted from scripts/roster.py (#91). send.sh sources this for its own gate,
# so there is one bash implementation, not two.
#
# For each non-comment, non-blank roster row, prints the first field
# containing "@", normalised (whitespace and CR stripped, lowercased) -- the
# same rule scripts/roster.py's roster_addresses() applies, so the two
# outputs can be compared directly (#98). A row with no such field
# contributes nothing, same as roster.py discarding it.
#
# Usage: roster_extract.sh <roster-file>

set -euo pipefail

roster=${1:?usage: roster_extract.sh <roster-file>}

[ -f "$roster" ] || exit 0

grep -vE '^[[:space:]]*(#|$)' "$roster" | awk -F'|' '
    {
        for (i = 1; i <= NF; i++) {
            field = $i
            gsub(/[ \t\r]/, "", field)
            if (index(field, "@") > 0) {
                print tolower(field)
                break
            }
        }
    }
'
