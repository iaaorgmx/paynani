#!/usr/bin/env bash
# ci_streak.sh applies the suite-macos rule the same way every time (#174).
#
# `gh` is faked with a script on PATH that prints canned runs, so the rule is
# exercised on known lists rather than on whatever main's history holds today.

set -uo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

pass=0; fail=0
check() {   # check <description> <expected-exit> <expected-substring> <args...>
    local desc=$1 want_rc=$2 want=$3; shift 3
    local out rc
    out=$(scripts/ci_streak.sh "$@" 2>&1); rc=$?
    if [ "$rc" -eq "$want_rc" ] && [[ "$out" == *"$want"* ]]; then
        printf 'ok   %s\n' "$desc"; pass=$((pass + 1))
    else
        printf 'FAIL %s\n     exit %s, wanted %s\n     %s\n' "$desc" "$rc" "$want_rc" "$out"; fail=$((fail + 1))
    fi
}

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
export PATH="$tmp/bin:$PATH"
export FAKE_RUNS="$tmp/runs.json"

# The fake gh prints whatever FAKE_RUNS holds, or fails like an unauthenticated gh.
cat >"$tmp/bin/gh" <<'EOF'
#!/usr/bin/env bash
[ -n "${FAKE_GH_FAIL:-}" ] && { echo "gh: To get started with GitHub CLI, please run: gh auth login" >&2; exit 4; }
cat "$FAKE_RUNS"
EOF
chmod +x "$tmp/bin/gh"

run() {   # run <sha> <attempt> <conclusion> [status]
    printf '{"headSha":"%s0000000000000000000000000000000000","attempt":%s,"conclusion":"%s","status":"%s","createdAt":"2026-09-17T00:00:00Z"}' \
        "$1" "$2" "$3" "${4:-completed}"
}
runs() {   # runs <json-object>... -> writes the list, newest first
    local sep="" out="["
    for r in "$@"; do out+="$sep$r"; sep=","; done
    printf '%s]\n' "$out" >"$FAKE_RUNS"
}

# Twelve green first attempts: count and date both matter, separately.
green=(); for i in $(seq 1 12); do green+=("$(run "$(printf 'aaa%04d' "$i")" 1 success)"); done
runs "${green[@]}"
check "enough green runs before the date is exit 2" 2 "Cuenta cumplida; la fecha no" --since 2099-01-01
check "and names the oldest run in the streak" 2 "12/10 desde aaa0012" --since 2099-01-01
check "enough green runs after the date is exit 0" 0 "Criterio cumplido" --since 2000-01-01
check "--need lowers the bar" 0 "12/3" --need 3 --since 2000-01-01
check "--json carries the facts" 0 '"criterion_met": true' --json --since 2000-01-01

# A re-run in the middle resets the count there, and is named with its attempt.
runs "${green[@]:0:5}" "$(run bbb0001 2 success)" "${green[@]:5}"
check "a re-run resets the streak" 2 "5/10 desde aaa0005; la última que reinició fue bbb0001 (attempt 2)" --since 2000-01-01
check "a re-run is not counted as green even after the date" 2 "Faltan 5" --since 2000-01-01

# A failure resets it too, and says so.
runs "${green[@]:0:3}" "$(run ccc0001 1 failure)" "${green[@]:3}"
check "a failure resets the streak" 2 "3/10 desde aaa0003; la última que reinició fue ccc0001 (failure)" --since 2000-01-01

# A run still in progress is skipped, not counted either way.
runs "$(run ddd0001 1 "" in_progress)" "${green[@]}"
check "an in-progress run is skipped" 0 "12/10 desde aaa0012" --since 2000-01-01

# The newest run is the reset: zero, and honest about it.
runs "$(run eee0001 2 success)" "${green[@]}"
check "a re-run on top means zero" 2 "0/10 (ninguna corrida verde arriba); la última que reinició fue eee0001 (attempt 2)" --since 2000-01-01

# Fewer runs than needed, all green: not met, and it says how many were read.
runs "${green[@]:0:4}"
check "too few runs is not met" 2 "4/10 desde aaa0004; sólo 4 corrida(s) completas leídas" --since 2000-01-01

# gh failing is exit 1 with its message, never a streak of zero.
FAKE_GH_FAIL=1 check "gh failing is exit 1" 1 "could not read the runs: gh: To get started"
unset FAKE_GH_FAIL

check "an unknown option is a usage error" 64 "unknown option" --bogus

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
