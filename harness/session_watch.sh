#!/usr/bin/env bash
# Monitor command for a Claude Code session. One stdout line == one notification.
#
# Takes a byte offset rather than starting at end-of-file: the session-start hook
# has already replayed the spool up to that point, and anything landing between
# the hook running and this being armed would otherwise fall in the gap.
#
# Usage: session_watch.sh <state_dir> [start_byte_offset]
#        session_watch.sh <state_dir> --from-hook [session_id]
#
# --from-hook reads the offset from this session's own registry,
# state/sessions/<session_id>/watch.json, which the SessionStart hook wrote
# (#170). The session id comes from CLAUDE_CODE_SESSION_ID, which Claude Code
# sets for every command a session runs, so nothing is copied by hand. The
# registry is then kept for as long as this watcher lives: armed with the pid
# and an expiry, a heartbeat once a minute, and ended on exit. healthcheck.py
# and the UserPromptSubmit hook read it; that is how "whether a session has
# armed a watch" stopped being unobservable.

set -uo pipefail

STATE_DIR=${1:?state directory required}
SPOOL="$STATE_DIR/session.spool"
OFFSET_FILE="$STATE_DIR/session.offset"
LOCK="$STATE_DIR/session.watch.lock"
# Resolved with parameter expansion, not dirname: a test runs this with a PATH
# that has no coreutils to prove the guard needs no flock, and it needs no
# dirname either.
HOOK="${0%/*}/session_start.py"
[ "$HOOK" != "$0/session_start.py" ] || HOOK="./session_start.py"

registry() {   # verb [k=v ...]  -> the registry of this session, if it has one
	[ -n "${session_id:-}" ] || return 0
	PAYNANI_RUNTIME=claudecode python3 "$HOOK" --registry "$1" "$session_id" "state=$STATE_DIR" "${@:2}" 2>/dev/null 9>&-
}

session_id="${CLAUDE_CODE_SESSION_ID:-}"
start=${2:-0}
if [ "$start" = "--from-hook" ]; then
	session_id=${3:-${CLAUDE_CODE_SESSION_ID:-}}
	if [ -z "$session_id" ]; then
		echo "[watch] --from-hook needs a session id and CLAUDE_CODE_SESSION_ID is not set; NOT armed. Pass the offset the hook printed instead."
		exit 1
	fi
	if ! start=$(registry offset); then
		echo "[watch] no registry to arm from for session $session_id in $STATE_DIR/sessions (none written, or its watcher is still alive); NOT armed. The SessionStart hook writes it: start a new session, or pass the offset by hand."
		exit 1
	fi
fi
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

# A Monitor that Claude Code takes away gets SIGTERM. Routed through exit from
# here on, so whichever EXIT trap is current runs and the registry says ended
# rather than looking killed. Set before the lock is taken: a signal between
# arming and the fifo setup used to skip every trap.
trap 'exit 143' TERM
trap 'exit 130' INT

claim_lock() {
	mkdir "$LOCK_DIR" 2>/dev/null || return 1
	printf 'watcher=%s
session=%s
chain=%s
' "$watcher_pid" "$session_pid" "$session_chain" >"$OWNER_FILE"
	# Release on every ordinary exit. A hard kill skips this, and the stale
	# branch below is what covers that.
	trap 'rm -rf "$LOCK_DIR"; registry end "offset=${cursor:-$start}" >/dev/null 2>&1 || true' EXIT
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
	elif [ -n "$held_watcher" ] && ! kill -0 "$held_watcher" 2>/dev/null; then
		# The session is fine; its watcher is not. A Monitor killed hard
		# leaves this exact shape: live chain, dead watcher, lock in place.
		# Judging the chain alone read it as "already watching" and the
		# session could never re-arm without deleting the lock by hand.
		echo "[watch] the watcher holding this lock (pid $held_watcher) is dead; taking over."
		rm -rf "$LOCK_DIR"
		claim_lock || {
			echo "[watch] could not take the watch lock after clearing it; NOT armed. Mail will queue but nothing will show it."
			exit 1
		}
	elif { held_chain=$(read_owner chain)
	       if [ -n "$held_chain" ]; then chain_is_usable "$held_chain"
	       else session_is_usable "$held_session"; fi; }; then
		echo "[watch] another session is already watching this spool; not arming a second."
		# Recorded, so no registry is left pending with an offset nobody will
		# use: the holder's watcher covers the spool from its own offset.
		registry yield "holder_session=$held_session" >/dev/null || true
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
registry arm "watcher_pid=$watcher_pid" "session_pid=$session_pid" >/dev/null || true

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
# The interval between liveness checks, and the most mail this can lose: a
# suspension that starts just after one check is noticed at the next.
STATE_EVERY=2

stop_watching() {   # reason
	# stdout, because from Claude Code's side stderr goes to a file nothing
	# reads -- the same reason the lock message moved here (#62).
	echo "[watch] $1; stopping without advancing the cursor, so the next session replays what is left."
}

# The checks must not depend on mail arriving. Tying them to a line looks
# harmless -- if nothing is arriving, nothing is being lost -- and it leaves a
# watcher sitting on the lock of a session that ended hours ago, in a mailbox
# that happens to be quiet.
#
# That used to be `read -t`, and it rested on two things bash does not promise
# equally everywhere. Returning over 128 for a timeout arrived in bash 4; 3.2
# answers 1, the same as for end-of-file. And the timeout itself is not a thing
# to lean on either: on the 3.2 that macOS still ships, a watcher with a stopped
# grandparent recorded in its own chain sat there having printed one line and
# never asked another question -- alive, holding the lock, checking nothing.
#
# So the interval stops being a property of `read` and becomes data in the
# stream. A ticker writes a token into the same fifo on a timer, the reader
# blocks with no timeout at all, and a token means "no mail, ask the questions".
# What was a promise about a builtin is now a line arriving, which is the one
# thing this loop already knows how to handle.
TICK="__paynani_tick_${$}_${RANDOM}"

FIFO="$STATE_DIR/session.watch.$$.fifo"
rm -f "$FIFO"
if ! mkfifo "$FIFO" 2>/dev/null; then
	echo "[watch] could not create the read fifo in $STATE_DIR; NOT armed. Mail will queue but nothing will show it."
	exit 1
fi

# Neither writer holds the cross-version lock: descriptor 9 is closed in each
# before it starts. A `sleep` orphaned from the ticker for up to STATE_EVERY
# seconds after cleanup kept flock held, and the next watcher of the same
# session read that as "a watcher from a previous version" and refused to arm.
(
	exec 9>&-
	if [ -n "${PAYNANI_TEST_TAIL_DELAY:-}" ]; then
		sleep "$PAYNANI_TEST_TAIL_DELAY"
	fi
	exec tail -c "+$((start + 1))" -F "$SPOOL" 2>/dev/null >"$FIFO"
) &
tail_pid=$!
# Both writers are short lines, well under PIPE_BUF, so a tick cannot land in
# the middle of a message.
( exec 9>&-; while :; do printf '%s\n' "$TICK"; sleep "$STATE_EVERY"; done ) >"$FIFO" &
ticker_pid=$!

# Blocks until a writer opens its end, which is why the writers start first.
# Keep the fifo path until cleanup: if it is unlinked before every background
# writer has opened it, a late shell redirection can recreate the path as a
# regular file and send tail output somewhere the reader will never see.
exec 8<"$FIFO"

# A watcher that has decided to stop has to actually stop, and that is about
# processes rather than about the loop returning. The reader runs in this shell
# rather than at the end of a pipeline for the same reason: `cmd | while ...`
# puts the loop in a subshell, so `exit` there ends the subshell and leaves the
# writers running. GNU tail hides that -- it notices the closed read end and
# goes -- and BSD tail does not, so on macOS the orphan sat holding whatever
# descriptors it had inherited. Under a CI step that captures output with
# `$(...)`, that is the capture's own pipe, and the step hangs until the runner
# is taken away rather than failing.
cleanup() {
	rm -f "$FIFO"
	rm -rf "$LOCK_DIR"
	kill "$tail_pid" "$ticker_pid" 2>/dev/null || true
	wait "$tail_pid" "$ticker_pid" 2>/dev/null || true
	# Last, and best effort: a hard kill skips this whole function, and the
	# dead pid in the registry is what tells healthcheck.py it was an orphan.
	registry end "offset=$cursor" >/dev/null || true
}
trap cleanup EXIT

# A heartbeat every BEAT_EVERY ticks. One python3 a minute is cheap; one per
# tick would put a fork between every liveness check for no more information.
BEAT_EVERY=$((60 / STATE_EVERY))
ticks=0

while IFS= read -r -u 8 line; do
	# Cheap enough to ask on every line: `kill -0` is a builtin at ~25us, so a
	# dead session is caught on the very next one and nothing is lost.
	if ! chain_is_alive "$session_chain"; then
		stop_watching "the session that armed this watch is gone"
		exit 0
	fi

	if [ "$line" = "$TICK" ]; then
		# The ticker outlives the tail, so end-of-mail has to be asked about
		# rather than waited for.
		kill -0 "$tail_pid" 2>/dev/null || break
		# ~8.1ms, which is why it waits for a tick instead of riding every line.
		if ! chain_is_awake "$session_chain"; then
			stop_watching "the session that armed this watch is suspended"
			exit 0
		fi
		ticks=$((ticks + 1))
		if [ "$ticks" -ge "$BEAT_EVERY" ]; then
			ticks=0
			registry beat "offset=$cursor" >/dev/null || true
		fi
		continue
	fi

	width=$(printf '%s\n' "$line" | wc -c | tr -d ' ')
	[ -n "$line" ] && printf '%s\n' "$line"
	cursor=$((cursor + width))
	printf '%s' "$cursor" >"$OFFSET_FILE.tmp" 2>/dev/null &&
		mv -f "$OFFSET_FILE.tmp" "$OFFSET_FILE" 2>/dev/null
	# If the Monitor is killed hard, cleanup cannot persist the cursor. Keep the
	# registry current as lines are shown so a later --from-hook does not replay
	# mail that already reached this session.
	registry beat "offset=$cursor" >/dev/null || true
done
