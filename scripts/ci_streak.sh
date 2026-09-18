#!/usr/bin/env bash
# How close `main` is to making suite-macos a required check.
#
#   ci_streak.sh                 the streak, in one line
#   ci_streak.sh --json          the same facts, for a script
#   ci_streak.sh --need N        a different target than 10 (tests, mostly)
#   ci_streak.sh --since DATE    a different earliest date than 2026-09-30
#
# Exit: 0 when the whole criterion holds, 2 when it does not yet, 1 when the
# runs could not be read (no gh, no auth, no network).
#
# The criterion is written in the 0.7.0 changelog: ten consecutive green runs
# of the `tests` workflow on `main`, none of them a re-run, and not before
# 2026-09-30. Two of those three are easy to get wrong by hand. A re-run
# (attempt > 1) is a run that failed once and was pushed through; it does not
# count as green, and it resets the streak, because the whole point of the
# count is that the suite passes on its own the first time. And a run that is
# still in progress is neither green nor red, so it is skipped rather than
# counted either way. This script reads the runs with `gh` and applies the rule
# the same way every time, which is what a hand count did not (#174).
#
# Counting is from the newest run backwards: the streak is how many consecutive
# first-attempt successes sit at the top of the list, and it stops at the first
# run that was a failure, a cancellation or a re-run. That run is the one that
# "reset" the count and it is named, so the number can be checked.

set -euo pipefail

need=10
since=2026-09-30
json=0
limit=60
while [ $# -gt 0 ]; do
    case "$1" in
        --json) json=1 ;;
        --need) need=$2; shift ;;
        --since) since=$2; shift ;;
        --limit) limit=$2; shift ;;
        -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "ci_streak.sh: unknown option $1" >&2; exit 64 ;;
    esac
    shift
done

command -v gh >/dev/null 2>&1 || { echo "ci_streak.sh: gh is not installed; cannot read the runs" >&2; exit 1; }

# Newest first, pushes to main only: a workflow_dispatch or a PR run on main
# is not the signal the criterion is about.
if ! runs=$(gh run list --branch main --workflow tests --event push --limit "$limit" \
        --json headSha,attempt,conclusion,status,createdAt 2>&1); then
    echo "ci_streak.sh: could not read the runs: ${runs%%$'\n'*}" >&2
    exit 1
fi

# One pass over the list in Python: the rule is small, and doing it in jq would
# make the reset logic harder to read than the rule it implements.
result=$(RUNS="$runs" NEED="$need" SINCE="$since" python3 - <<'PY'
import json, os, sys, datetime
runs = json.loads(os.environ["RUNS"])
need = int(os.environ["NEED"])
since = os.environ["SINCE"]
streak = 0
first_sha = None          # oldest run in the streak
reset = None              # the run that ended it, if any
counted = 0
for run in runs:
    if run.get("status") != "completed":
        continue          # neither green nor red yet
    counted += 1
    ok = run.get("conclusion") == "success" and int(run.get("attempt", 1)) == 1
    if ok:
        streak += 1
        first_sha = run["headSha"][:7]
        continue
    reset = run
    break
today = datetime.date.today().isoformat()
date_ok = today >= since
enough = streak >= need
out = {
    "streak": streak, "need": need, "since": since, "today": today,
    "from": first_sha, "enough": enough, "date_ok": date_ok,
    "criterion_met": bool(enough and date_ok),
    "reset": None if reset is None else {
        "sha": reset["headSha"][:7], "attempt": int(reset.get("attempt", 1)),
        "conclusion": reset.get("conclusion"), "at": reset.get("createdAt")},
    "runs_read": len(runs), "runs_completed": counted,
}
print(json.dumps(out))
PY
)

if [ "$json" = 1 ]; then
    printf '%s\n' "$result"
else
    python3 - "$result" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
line = f"{r['streak']}/{r['need']}"
line += f" desde {r['from']}" if r["from"] else " (ninguna corrida verde arriba)"
if r["reset"]:
    why = "attempt " + str(r["reset"]["attempt"]) if r["reset"]["attempt"] > 1 else r["reset"]["conclusion"]
    line += f"; la última que reinició fue {r['reset']['sha']} ({why})"
elif r["runs_completed"] < r["need"]:
    line += f"; sólo {r['runs_completed']} corrida(s) completas leídas"
if r["criterion_met"]:
    line += f". Criterio cumplido: suite-macos puede pasar a requerido."
elif r["enough"] and not r["date_ok"]:
    line += f". Cuenta cumplida; la fecha no: no antes del {r['since']} (hoy {r['today']})."
else:
    line += f". Faltan {max(0, r['need'] - r['streak'])} y no antes del {r['since']}."
print(line)
PY
fi

python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1])["criterion_met"] else 2)' "$result"
