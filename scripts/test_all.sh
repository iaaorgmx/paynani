#!/usr/bin/env bash
# Runs every test in this repository and prints one summary.
#
# This exists because the obvious command is the wrong one. Seven of the test
# files are self-contained assertion scripts rather than `unittest.TestCase`
# classes, so `python3 -m unittest discover` cannot run them: six exit at import
# and are reported as errors, and the seventh imports cleanly and contributes
# nothing at all. Both outcomes are wrong in the same direction -- the loader
# reports on a suite it did not run. Two people reached for `discover` by reflex
# on two different runtimes before this script existed (issue #63).
#
# So the rule is: every test file is an executable, and the way to run the suite
# is to execute each one and read its exit status. That is all this does.
#
#   scripts/test_all.sh

set -uo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

self=$(basename "$0")
pass=0
fail=0
failed=()

run() {
	local name=$1
	local output
	shift
	if output=$("$@" 2>&1); then
		printf 'ok   %s\n' "$name"
		pass=$((pass + 1))
	else
		printf 'FAIL %s\n' "$name"
		# Individual tests print platform diagnostics on failure. Keep successful
		# suites quiet, but retain the evidence CI needs to explain a failure.
		if [ -n "$output" ]; then
			printf '%s\n' "$output" | sed 's/^/     /'
		fi
		# A test with context-specific observations prints its own block. Older
		# tests do not, so add the portable baseline here instead of leaving a CI
		# failure with only a traceback and no platform identity.
		if ! printf '%s\n' "$output" | grep -q '^diagnostic: python='; then
			python3 scripts/failure_diagnostics.py 2>&1 | sed 's/^/     /'
		fi
		fail=$((fail + 1))
		failed+=("$name")
	fi
}

for t in scripts/test_*.py; do
	[ -e "$t" ] || continue
	run "$t" python3 "$t"
done

for t in scripts/test_*.sh; do
	[ -e "$t" ] || continue
	# Skip this file, or it runs the suite inside the suite, forever.
	[ "$(basename "$t")" = "$self" ] && continue
	run "$t" bash "$t"
done

echo
echo "$pass passed, $fail failed"

if [ "$fail" -ne 0 ]; then
	echo
	echo "Re-run a failure on its own to see why it failed:"
	for t in "${failed[@]}"; do
		echo "  $t"
	done
fi

[ "$fail" -eq 0 ]
