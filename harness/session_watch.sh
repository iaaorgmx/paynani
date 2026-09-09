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
# Recorded inside: this watcher's pid, and the chain of processes above it.
#
# The chain, and not $PPID, because $PPID is not the session. The harness runs
# this through a wrapper, and the shape on a real host is:
#
#     claude --channels ...      Sl+   <- the session. This is what gets stopped.
#     /bin/bash -c source ...    Ss    <- the wrapper. This is $PPID.
#     bash session_watch.sh      S     <- here
#
# A stopped process does not stop its children: with the grandparent in state T
# its child stayed in S, measured rather than assumed. So a check on $PPID reads
# a wrapper that is perfectly healthy while the session above it is suspended,
# and never fires -- which is the whole of #62 surviving its own fix.
session_pid=$PPID
watcher_pid=$$

# One `ps` per hop, so this runs once at arming and the answer is remembered.
#
# The walk stops at the first ancestor this user cannot signal, and that boundary
# is the point rather than an optimisation. Walking to pid 1 collects the shell's
# own ancestors and then kernel threads, and `kill -0` fails on those for lack of
# permission -- not because they died. Reading that as "the session is gone"
# stopped the watcher on the first line it ever read, which is how this was
# found. What belongs in the chain is the processes this session owns, because
# those are the ones whose suspension means nothing will be rendered.
ancestors() {
	local pid=$1 hops=0 out=""
	while [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null && [ "$hops" -lt 12 ]; do
		kill -0 "$pid" 2>/dev/null || break
		out="$out $pid"
		pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
		hops=$((hops + 1))
	done
	printf '%s' "${out# }"
}
session_chain=$(ancestors "$session_pid")

# `kill -0` is a bash builtin: 25us and no fork, against 8.1ms for one `ps`.
# That gap is why the loop below can afford to ask this on every single line and
# only asks the expensive question on a timer.
chain_is_alive() {   # chain
	local pid
	for pid in $1; do
		kill -0 "$pid" 2>/dev/null || return 1
	done
	return 0
}

chain_is_awake() {   # chain
	local pid state
	for pid in $1; do
		state=$(ps -o state= -p "$pid" 2>/dev/null | tr -d ' ')
		case "$state" in
			T*) return 1 ;;
		esac
	done
	return 0
}

# The two callers of this want opposite things when the answer is unclear, and
# saying so here is cheaper than discovering it twice.
#
# Taking over another watcher's lock: being wrong gives two readers on one
# cursor, which is the corruption this guard exists to prevent. Err towards
# leaving it alone.
#
# Stopping this watcher's own loop: being wrong costs one unnecessary re-arm,
# and the mail stays in the spool because the cursor did not move. Err towards
# stopping.
#
# So `session_is_usable` is the conservative one, and the loop below uses the
# primitives directly instead of it.
session_is_usable() {
	local pid=$1 state
	[ -n "$pid" ] || return 1
	kill -0 "$pid" 2>/dev/null || return 1
	state=$(ps -o state= -p "$pid" 2>/dev/null | tr -d ' ')
	case "$state" in
		T*) return 1 ;;
		"") return 0 ;;   # exists, and ps will not say. Do not steal from it.
		*)  return 0 ;;
	esac
}

chain_is_usable() {   # chain
	[ -n "$1" ] || return 1
	chain_is_alive "$1" || return 1
	chain_is_awake "$1" || return 1
	return 0
}

read_owner() {   # field
	[ -r "$OWNER_FILE" ] || return 1
	awk -v want="$1" -F'=' '$1 == want { print $2 }' "$OWNER_FILE" 2>/dev/null
}

claim_lock() {
	mkdir "$LOCK_DIR" 2>/dev/null || return 1
	printf 'watcher=%s
session=%s
chain=%s
' "$watcher_pid" "$session_pid" "$session_chain" >"$OWNER_FILE"
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
	elif { held_chain=$(read_owner chain)
	       if [ -n "$held_chain" ]; then chain_is_usable "$held_chain"
	       else session_is_usable "$held_session"; fi; }; then
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
# Advancing the cursor is a claim that somebody saw the line. This loop stops
# making that claim the moment it stops being true (#110).
#
# What went wrong without this: a watcher whose session had been suspended kept
# reading, kept printing to a descriptor nobody was attached to, and kept moving
# the cursor -- 8h43m and 3299 bytes on one host. The next session's hook reads
# that cursor to decide what to replay, so those messages were skipped then and
# were never shown afterwards either. They had been acknowledged by nobody.
#
# Stopping is safe in a way that advancing is not. The mail stays in the spool,
# the cursor still points before it, and the next session replays it. The worst
# a false alarm costs is one re-arm.
#
# Two questions on two schedules, because they cost three orders of magnitude
# apart. `kill -0` is a builtin at ~25us, so a dead session is caught on the very
# next line and nothing is lost. `ps` is ~8.1ms, and asking it per line would put
# a fork between every message, so suspension is caught within STATE_EVERY
# seconds instead. That interval is the most mail this can lose, and it is
# written here rather than left implicit.
STATE_EVERY=2
last_state_check=$SECONDS

stop_watching() {   # reason
	# stdout, because from Claude Code's side stderr goes to a file nothing
	# reads -- the same reason the lock message moved here (#62).
	echo "[watch] $1; stopping without advancing the cursor, so the next session replays what is left."
}

# The read has a timeout so the checks do not depend on mail arriving.
#
# Tying them to a line looks harmless -- if nothing is arriving, nothing is being
# lost -- and it leaves a watcher sitting on the lock of a session that ended
# hours ago, in a mailbox that happens to be quiet. The next session then has to
# clear it, which works, but a watcher that knows it is useless should say so and
# go rather than wait to be found.
# The reader runs in this shell rather than at the end of a pipeline, and `tail`
# writes through a fifo instead of a pipe, because `cmd | while ...` puts the
# loop in a subshell: `exit` there ends the subshell and leaves `tail` running,
# and the script is then left waiting on a pipeline that will never finish.
#
# GNU tail hides this. It notices the closed read end and goes, so the watcher
# exits on Linux and the stopping path looks correct. BSD tail does not, and on
# macOS the orphan sits there holding whatever descriptors it inherited -- under
# a CI step that captures output with `$(...)`, that is the capture's own pipe,
# so the step hangs until the runner is taken away rather than failing.
#
# A watcher that has decided to stop has to actually stop, on both platforms, so
# the tail is something this shell owns a pid for and kills on the way out.
FIFO="$STATE_DIR/session.watch.$$.fifo"
rm -f "$FIFO"
if ! mkfifo "$FIFO" 2>/dev/null; then
	echo "[watch] could not create the read fifo in $STATE_DIR; NOT armed. Mail will queue but nothing will show it."
	exit 1
fi
tail -c "+$((start + 1))" -F "$SPOOL" 2>/dev/null >"$FIFO" &
tail_pid=$!
# Blocks until the writer above opens its end, which is why the tail is started
# first. The fifo is unlinked immediately: both ends are held open by descriptor
# from here on, and nothing else should be able to join the stream.
exec 8<"$FIFO"
rm -f "$FIFO"
trap 'rm -rf "$LOCK_DIR"; kill "$tail_pid" 2>/dev/null' EXIT

while :; do
	if IFS= read -r -t "$STATE_EVERY" -u 8 line; then
		got_line=yes
	else
		# Over 128 is the timeout; anything else is EOF or a read error, and
		# there is nothing left to watch either way.
		[ "$?" -gt 128 ] || break
		got_line=""
	fi

	if ! chain_is_alive "$session_chain"; then
		stop_watching "the session that armed this watch is gone"
		exit 0
	fi
	if [ $((SECONDS - last_state_check)) -ge "$STATE_EVERY" ]; then
		last_state_check=$SECONDS
		if ! chain_is_awake "$session_chain"; then
			stop_watching "the session that armed this watch is suspended"
			exit 0
		fi
	fi

	[ -n "$got_line" ] || continue

	width=$(printf '%s\n' "$line" | wc -c | tr -d ' ')
	[ -n "$line" ] && printf '%s\n' "$line"
	cursor=$((cursor + width))
	printf '%s' "$cursor" >"$OFFSET_FILE.tmp" 2>/dev/null &&
		mv -f "$OFFSET_FILE.tmp" "$OFFSET_FILE" 2>/dev/null
done
