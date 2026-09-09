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
# The guard used to be `flock -n` on a file descriptor, and it failed in two
# directions at once.
#
# On macOS it failed always (#105). `flock` is util-linux and macOS does not
# ship it, so the command exited 127, `! flock -n 9` was true, and every session
# took the "somebody else is watching" branch and exited 0 without arming. The
# line it printed was not a silence -- it was a reassuring lie, which is worse.
#
# On Linux it failed when the holder was alive but useless (#62). The guard
# assumed whoever holds the lock is a session that will render what it reads. A
# watcher whose parent session had been suspended for nearly nine hours kept
# draining the spool and advancing the cursor, so the next session could not arm,
# did not know it, and never replayed the backlog either: it had been
# acknowledged by nobody. Every indicator green, no mail delivered.
#
# What replaces it holds to the same rule -- exactly one watcher -- and adds the
# question the old one never asked: is the watcher that holds this lock attached
# to a session that can still show a message to a person?
LOCK_DIR="$LOCK.d"
OWNER_FILE="$LOCK_DIR/owner"

# `mkdir` is the lock. It is atomic on every POSIX filesystem and it needs no
# binary that a platform might not ship, which is the whole of #105. The
# directory is removed on exit; a holder killed hard leaves it behind, and that
# is what the liveness check below is for.
#
# Recorded inside: this watcher's pid, and the pid of the session that owns it.
# The second one is the one that matters. In #62 the watcher itself was alive and
# working perfectly -- it was the session above it that had stopped being able to
# receive anything.
session_pid=$PPID
watcher_pid=$$

# Alive is not the same as usable, and this is the distinction #62 was about.
session_is_usable() {
	local pid=$1 state
	[ -n "$pid" ] || return 1
	kill -0 "$pid" 2>/dev/null || return 1

	# `ps -o state=` is POSIX and answers on both Linux and macOS, which is why
	# it is here instead of /proc: a check that only works on the platform where
	# the bug was found is how #105 happened.
	state=$(ps -o state= -p "$pid" 2>/dev/null | tr -d ' ')
	case "$state" in
		T*)
			# Suspended by SIGTSTP. Alive, and it will not render a line until
			# somebody continues it -- which may be never. This is the case that
			# ate nine hours of mail.
			return 1
			;;
		"")
			# The process exists and `ps` would not say what it is doing. Treat
			# it as usable rather than steal from it: a wrong steal gives two
			# watchers on one cursor, which is the corruption this guard exists
			# to prevent. The caller says this out loud rather than deciding in
			# silence.
			return 0
			;;
		*)
			return 0
			;;
	esac
}

read_owner() {   # field
	[ -r "$OWNER_FILE" ] || return 1
	awk -v want="$1" -F'=' '$1 == want { print $2 }' "$OWNER_FILE" 2>/dev/null
}

claim_lock() {
	mkdir "$LOCK_DIR" 2>/dev/null || return 1
	printf 'watcher=%s
session=%s
' "$watcher_pid" "$session_pid" >"$OWNER_FILE"
	# Release on every ordinary exit. A hard kill skips this, and the stale
	# branch below is what covers that.
	trap 'rm -rf "$LOCK_DIR"' EXIT
	return 0
}

if ! claim_lock; then
	held_session=$(read_owner session)
	held_watcher=$(read_owner watcher)

	if [ -z "$held_session" ]; then
		# A lock directory with no readable owner is not a watcher, it is
		# wreckage: an older version, or a process killed between mkdir and the
		# write. Taking it over is right, and saying so is what keeps this from
		# being the silent branch all over again.
		echo "[watch] found a watch lock with no owner recorded; taking it over."
		rm -rf "$LOCK_DIR"
		claim_lock || {
			echo "[watch] could not take the watch lock; NOT armed. Mail will queue but nothing will show it."
			exit 1
		}
	elif session_is_usable "$held_session"; then
		echo "[watch] another session is already watching this spool; not arming a second."
		exit 0
	else
		# The holder is gone, or suspended and going to stay that way. Its
		# watcher is either dead with it or still draining into a session that
		# cannot show anything -- #62 either way.
		echo "[watch] the session holding this watch (pid $held_session) is gone or suspended; taking over."
		if [ -n "$held_watcher" ] && kill -0 "$held_watcher" 2>/dev/null; then
			# Stop the orphan before arming, or two readers advance one cursor
			# and the corruption this guard prevents happens anyway.
			kill "$held_watcher" 2>/dev/null || true
			echo "[watch] stopped the orphaned watcher (pid $held_watcher)."
		fi
		rm -rf "$LOCK_DIR"
		claim_lock || {
			echo "[watch] could not take the watch lock after clearing it; NOT armed. Mail will queue but nothing will show it."
			exit 1
		}
	fi
fi

# Cross-version guard, and only where it can matter.
#
# A watcher from before this change holds `flock` on the lock *file*, and knows
# nothing about the directory above. Honouring the old lock where `flock` exists
# keeps the two versions excluding each other through an upgrade. Where `flock`
# does not exist there is nothing to honour and nothing to miss: on macOS the old
# script never armed at all, so no legacy watcher can be running there.
if command -v flock >/dev/null 2>&1; then
	exec 9>"$LOCK"
	if ! flock -n 9; then
		echo "[watch] a watcher from a previous version still holds this spool; not arming a second."
		echo "[watch] restart that session, or end it, and arm again."
		exit 0
	fi
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
