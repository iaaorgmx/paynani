#!/usr/bin/env bash
# Exercises version.sh against a local bare remote: no network, no GitHub.
#
# The case worth guarding is not "1.2.0 is newer than 1.1.0". It is 1.10.0
# against 1.9.0, which string comparison gets backwards, and which will not
# occur for a year and will then be reported as an install being ahead of a
# release it is nine behind.
#
# The other half is the unreachable remote. A checker that says "up to date"
# when it means "I could not ask" is the silent failure this whole repository is
# built to avoid, and it is one `|| echo` away at all times.
#
#   scripts/test_version.sh

set -uo pipefail

VERSION_SH="$(cd "$(dirname "$0")" && pwd)/version.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export GIT_CONFIG_GLOBAL="$tmp/gitconfig"   # do not read the tester's identity
export GIT_CONFIG_NOSYSTEM=1

pass=0
fail=0

assert() {
    local desc=$1 cond=$2
    if eval "$cond"; then
        printf '  PASS  %-8s %s\n' "version" "$desc"; pass=$((pass+1))
    else
        printf '  FAIL  %-8s %s\n' "version" "$desc"; fail=$((fail+1))
    fi
}

# A bare repo standing in for origin, carrying the tags a release would create.
remote="$tmp/origin.git"
git init -q --bare "$remote"

seed="$tmp/seed"
git init -q "$seed"
git -C "$seed" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
for v in 1.0.0 1.1.0 1.9.0 1.10.0; do
    git -C "$seed" tag "v$v"
done
git -C "$seed" tag "not-a-version"       # must be ignored, not parsed as 0
git -C "$seed" push -q "$remote" --tags

# A clone of this repository's scripts, pointed at that remote. envpath.sh comes
# along because version.sh resolves its cache location through it rather than
# hard-coding a state directory, and a clone missing it is not a clone.
clone="$tmp/clone"
mkdir -p "$clone/scripts"
cp "$VERSION_SH" "$clone/scripts/version.sh"
cp "$(dirname "$VERSION_SH")/envpath.sh" "$clone/scripts/envpath.sh"
git init -q "$clone"
git -C "$clone" remote add origin "$remote"

run() {   # run <installed-version> [args...] -> prints output, sets $rc
    local v=$1; shift
    printf '%s\n' "$v" >"$clone/VERSION"
    out=$("$clone/scripts/version.sh" "$@" 2>&1); rc=$?
}

state="$tmp/state"
export PAYNANI_STATE="$state"
fresh() { rm -rf "$state"; }   # --line caches for a day; each case starts clean

# ---- ordering -------------------------------------------------------------

run 1.10.0
assert "1.10.0 is not behind 1.9.0"      '[ "$rc" -eq 0 ]'
assert "1.10.0 reports latest 1.10.0"    'grep -q "latest:    1.10.0" <<<"$out"'

run 1.9.0
assert "1.9.0 is behind 1.10.0"          '[ "$rc" -eq 2 ]'
assert "behind names the newer version"  'grep -q "1.10.0 has been released" <<<"$out"'

run 2.0.0
assert "2.0.0 is ahead of every tag"     '[ "$rc" -eq 0 ]'
assert "ahead says so, not up to date"   'grep -q "ahead of the newest tag" <<<"$out"'
assert "ahead without changelog says no entry" 'grep -q "no entry for 2.0.0" <<<"$out"'

# A changelog that exists but does not describe this version is the case the
# pattern guards. The absent-file case above passes even with no pattern.
printf '# Changelog\n\n## 1.9.0 (2026-08-18)\n' >"$clone/CHANGELOG.md"
run 2.0.0
assert "present changelog without the entry" 'grep -q "no entry for 2.0.0" <<<"$out"'

# A longer version that merely begins with this one is not this one.
printf '# Changelog\n\n## 2.0.01 (2026-08-18)\n' >"$clone/CHANGELOG.md"
run 2.0.0
assert "a longer version is not a match"     'grep -q "no entry for 2.0.0" <<<"$out"'

# A heading whose separators are not dots must not match. Without the escaping
# in version.sh, `.` is a wildcard and this reports an entry that is not there.
printf '# Changelog\n\n## 2x0x0 (2026-08-18)\n' >"$clone/CHANGELOG.md"
run 2.0.0
assert "dots are literal, not wildcards"     'grep -q "no entry for 2.0.0" <<<"$out"'

printf '# Changelog\n\n## 2.0.0 — 2026-08-19\n' >"$clone/CHANGELOG.md"
run 2.0.0
assert "ahead with changelog exits 0"    '[ "$rc" -eq 0 ]'
assert "ahead with changelog is observed" 'grep -q "does describe 2.0.0" <<<"$out"'

# A tag that is not a version must be ignored rather than sorted.
assert "non-version tag ignored"         '! grep -q "not-a-version" <<<"$out"'

# ---- the honest failures --------------------------------------------------

rm -f "$clone/VERSION"
out=$("$clone/scripts/version.sh" 2>&1); rc=$?
assert "no VERSION file exits 1"         '[ "$rc" -eq 1 ]'
# "Up to date." on its own line is the success message. Match it exactly: the
# failure messages talk about being up to date in order to warn against it.
assert "no VERSION file never claims currency" '! grep -Fqx "Up to date." <<<"$out"'

printf '1.0.0\n' >"$clone/VERSION"
git -C "$clone" remote set-url origin "$tmp/does-not-exist.git"
out=$("$clone/scripts/version.sh" 2>&1); rc=$?
assert "unreachable remote exits 1"      '[ "$rc" -eq 1 ]'
assert "unreachable is not exit 2"       '[ "$rc" -ne 2 ]'
assert "unreachable never claims currency" '! grep -Fqx "Up to date." <<<"$out"'
assert "unreachable says it could not find out" 'grep -q "could not find out" <<<"$out"'

fresh
out=$("$clone/scripts/version.sh" --line 2>&1); rc=$?
assert "--line unreachable exits 1"      '[ "$rc" -eq 1 ]'
assert "--line unreachable says unknown" 'grep -q "update status unknown" <<<"$out"'
assert "--line unreachable is one line"  '[ "$(wc -l <<<"$out")" -eq 1 ]'

# ---- the session-start line -----------------------------------------------

git -C "$clone" remote set-url origin "$remote"

fresh; run 1.10.0 --line
assert "--line current exits 0"          '[ "$rc" -eq 0 ]'
assert "--line current is one line"      '[ "$(wc -l <<<"$out")" -eq 1 ]'
assert "--line current names the version" 'grep -q "paynani 1.10.0 (latest)" <<<"$out"'

# Ahead of every tag is a third answer, and --line used to round it into the
# catch-all and report "(latest)". The long form has always described it
# correctly; --line is the form that gets read, because it feeds the session-start
# hook and healthcheck.py's version field. An agent was told it was on the newest
# release while running code nobody had tagged. #64.
fresh; run 1.11.0 --line
assert "--line ahead exits 0"            '[ "$rc" -eq 0 ]'
assert "--line ahead is one line"        '[ "$(wc -l <<<"$out")" -eq 1 ]'
assert "--line ahead does not claim latest" '! grep -q "(latest)" <<<"$out"'
assert "--line ahead names the newest tag" 'grep -q "AHEAD of the newest tag (1.10.0)" <<<"$out"'

# ---- the cache behind --line (#61) ----------------------------------------
#
# --line answers from a cache with a one-day TTL, and that is the right call: a
# session must not pay for a network round trip. But the cached value can span
# several releases, and while it does, --line reads exactly like a fresh fact.
# It cost a whole session once: the hook said "0.2.0 is AHEAD of the newest tag
# (0.1.0)" with 0.2.0 tagged the day before, and the agent spent hours
# recommending a tag that already existed.

# 1. The installed version moving is evidence the tag landscape moved with it.
#    A cache written while 1.9.0 was installed must not answer for 1.10.0.
fresh
printf '%s 1.9.0 1.9.0\n' "$(date +%s)" >"$state/version.check"
run 1.10.0 --line
assert "--line refreshes when VERSION moved under the cache" \
    '! grep -q "AHEAD of the newest tag (1.9.0)" <<<"$out"'
assert "--line refreshed says latest"    'grep -q "paynani 1.10.0 (latest)" <<<"$out"'
assert "the refreshed cache records the installed version" \
    '[ "$(cut -d" " -f3 "$state/version.check")" = "1.10.0" ]'

# 2. What the cache cannot fix it must disclose. The second call inside the TTL
#    is answered from disk, and has to say so: an agent told "the newest tag is
#    X" reads a fact, one told "as of a check 20h ago" knows to ask.
run 1.10.0 --line
assert "a cached --line names its age"   'grep -q "from a check" <<<"$out"'
assert "a cached --line is still one line" '[ "$(wc -l <<<"$out")" -eq 1 ]'

# 3. And the two forms must stop contradicting each other. This is the exact
#    pair from #61: --line said AHEAD while --report said Up to date, at the
#    same moment, on the same host.
fresh
printf '%s 1.9.0 1.9.0\n' "$(date +%s)" >"$state/version.check"
run 1.10.0 --line;   line_out=$out
run 1.10.0 --report; report_out=$out
assert "--line and --report agree on a stale in-TTL cache" \
    '! { grep -q "AHEAD" <<<"$line_out" && grep -Fq "Up to date." <<<"$report_out"; }'

# 4. A two-field cache written by an older paynani has no installed version to
#    match, so it refreshes rather than being trusted. No migration step, and
#    the safe direction.
fresh
printf '%s 1.9.0\n' "$(date +%s)" >"$state/version.check"
run 1.10.0 --line
assert "a legacy two-field cache is refreshed" 'grep -q "paynani 1.10.0 (latest)" <<<"$out"'

# ---- a host without timeout(1) (#68) --------------------------------------
#
# `timeout` is GNU coreutils and macOS does not ship it. Wrapping the remote
# call in a command that is not there made latest_version() fail on every macOS
# install, permanently -- and "could not find out" reads like a passing network
# glitch, so nobody investigates. Found by Ximena on the first macOS install,
# after three of my four predictions about that host turned out to be wrong.
#
# Simulated with a PATH that has everything except timeout and gtimeout: a
# symlink farm, because a trimmed literal PATH loses tools the script needs for
# unrelated reasons and would pass for the wrong reason.
notimeout="$tmp/notimeout-bin"
mkdir -p "$notimeout"
_old_ifs=$IFS; IFS=:
for _d in $PATH; do
    [ -d "$_d" ] || continue
    for _f in "$_d"/*; do
        [ -x "$_f" ] || continue
        _b=${_f##*/}
        case "$_b" in timeout|gtimeout) continue ;; esac
        [ -e "$notimeout/$_b" ] || ln -s "$_f" "$notimeout/$_b" 2>/dev/null
    done
done
IFS=$_old_ifs

if PATH="$notimeout" command -v timeout >/dev/null 2>&1; then
    # The farm did not actually hide it, so anything below would pass for the
    # wrong reason. Say so instead of reporting a green that means nothing.
    assert "the no-timeout farm really hides timeout" 'false'
else
    fresh
    printf '%s\n' "1.10.0" >"$clone/VERSION"
    out=$(PATH="$notimeout" "$clone/scripts/version.sh" 2>&1); rc=$?
    assert "the report resolves latest without timeout" '[ "$rc" -eq 0 ]'
    assert "without timeout it does not give up"  '! grep -q "could not find out" <<<"$out"'
    assert "without timeout it names the tag"     'grep -q "latest:    1.10.0" <<<"$out"'

    fresh
    out=$(PATH="$notimeout" "$clone/scripts/version.sh" --line 2>&1); rc=$?
    assert "--line resolves latest without timeout" '[ "$rc" -eq 0 ]'
    assert "--line without timeout says latest"     'grep -q "paynani 1.10.0 (latest)" <<<"$out"'
fi

fresh; run 1.0.0 --line
assert "--line behind exits 2"           '[ "$rc" -eq 2 ]'
assert "--line behind says OUT OF DATE"  'grep -q "OUT OF DATE" <<<"$out"'
assert "--line behind names both docs"   'grep -q "CHANGELOG.md" <<<"$out" && grep -q "UPGRADE.md" <<<"$out"'

# The cache is what keeps a session from paying for a network call, so it has to
# actually be written and actually be read.
assert "--line writes a cache"           '[ -s "$state/version.check" ]'
git -C "$clone" remote set-url origin "$tmp/does-not-exist.git"
run 1.0.0 --line
assert "--line answers from cache with the remote gone" '[ "$rc" -eq 2 ]'

# A corrupt cache must re-check rather than be trusted or crash.
git -C "$clone" remote set-url origin "$remote"
printf 'garbage\n' >"$state/version.check"
run 1.0.0 --line
assert "corrupt cache re-checks"         '[ "$rc" -eq 2 ]'
# The third field is the installed version at the moment of writing (#61); the
# cache is what it compares against on the next call, so its shape is part of
# what "replaced with something well-formed" means.
assert "corrupt cache is replaced"       'grep -qE "^[0-9]+ 1\.10\.0 1\.0\.0$" "$state/version.check"'

# ---- --installed ----------------------------------------------------------

run 1.2.0 --installed
assert "--installed prints only the version" '[ "$out" = "1.2.0" ]'

printf '  1.2.0  \n' >"$clone/VERSION"
out=$("$clone/scripts/version.sh" --installed 2>&1)
assert "--installed tolerates whitespace" '[ "$out" = "1.2.0" ]'

printf 'v1.2.0\n' >"$clone/VERSION"
out=$("$clone/scripts/version.sh" --installed 2>&1); rc=$?
assert "a malformed VERSION exits 1"     '[ "$rc" -eq 1 ]'

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
