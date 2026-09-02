#!/usr/bin/env bash
# Monitor command for a Claude Code session. One stdout line == one notification.
#
# Takes a byte offset rather than starting at end-of-file: the session-start hook
# has already replayed the spool up to that point, and anything landing between
# the hook running and this being armed would otherwise fall in the gap.
#
# Usage: session_watch.sh <state_dir> [start_byte_offset]

set -uo pipefail

STATE_DIR=${1:?state directory required}
SPOOL="$STATE_DIR/session.spool"
OFFSET_FILE="$STATE_DIR/session.offset"
LOCK="$STATE_DIR/session.watch.lock"

start=${2:-0}
case "$start" in '' | *[!0-9]*) start=0 ;; esac

mkdir -p "$STATE_DIR"

# One watcher, enforced rather than assumed.
#
# This repository has already paid for the alternative: two consumers of one
# stream racing on one cursor file duplicated events and corrupted the record of
# what had been seen. On every other runtime the fix was that a session never
# arms a watcher at all. Here it must, because nothing can push into a Claude
# Code session -- so the guard moves here instead of disappearing.
#
# A second session arming this exits immediately rather than quietly halving the
# accuracy of both.
exec 9>"$LOCK"
if ! flock -n 9; then
	echo "[watch] another session is already watching this spool; not arming a second." >&2
	exit 0
fi

# Arming the watch is what acknowledges the backlog the hook just replayed.
# Written up front so a session that arms and then sees no mail does not make the
# next session replay the same messages.
printf '%s' "$start" >"$OFFSET_FILE"

[ -f "$SPOOL" ] || : >"$SPOOL"

cursor=$start

# Advance by exactly the bytes of the line just reported, never by the file's
# current size. Recording the size acknowledges anything that landed while this
# line was being handled, and the next session's replay then starts past messages
# that were never shown -- which is indistinguishable from a quiet mailbox.
# Blank lines are counted too, or the cursor drifts out of step with the file it
# indexes into.
tail -c "+$((start + 1))" -F "$SPOOL" 2>/dev/null | while IFS= read -r line; do
	width=$(printf '%s\n' "$line" | wc -c | tr -d ' ')
	[ -n "$line" ] && printf '%s\n' "$line"
	cursor=$((cursor + width))
	printf '%s' "$cursor" >"$OFFSET_FILE.tmp" 2>/dev/null &&
		mv -f "$OFFSET_FILE.tmp" "$OFFSET_FILE" 2>/dev/null
done
