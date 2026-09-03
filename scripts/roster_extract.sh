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

# Comments and headings are handled here rather than by a grep in front, because
# the notifier section is introduced by a `##` heading and a pre-filter that
# strips every line starting with `#` removes exactly the line that says where
# the section begins.
#
# Notifier rows are skipped on purpose. They authorise INCOMING mail — a
# platform speaking for somebody already on the list — and nobody writes to a
# notification address. Emitting one here would add it to the addresses send.sh
# accepts as a destination, which is a wider outgoing list for no reason.
# scripts/test_roster_agree.sh pins that it stays out of both halves.
awk '
    function is_separator(s) {
        gsub(/[|]/, "", s); gsub(/[ \t\r]/, "", s)
        return (s != "" && s ~ /^[-:]+$/)
    }
    {
        line = $0
        sub(/^[ \t]+/, "", line); sub(/[ \t\r]+$/, "", line)
        if (line ~ /^#/) {
            heading = line
            sub(/^#+[ \t]*/, "", heading)
            heading = tolower(heading)
            if (heading ~ /^notifier/ || heading ~ /^notificador/) in_notifiers = 1
            else if (line ~ /^##/) in_notifiers = 0
            next
        }
        if (line == "" || is_separator(line) || in_notifiers) next

        n = split(line, parts, "|")
        for (i = 1; i <= n; i++) {
            field = parts[i]
            gsub(/[ \t\r]/, "", field)
            if (index(field, "@") > 0) {
                print tolower(field)
                break
            }
        }
    }
' "$roster"
