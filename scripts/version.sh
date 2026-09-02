#!/usr/bin/env bash
# What is installed, what has been released, and what to do about the gap.
#
#   version.sh              installed vs latest, live, with the upgrade path
#   version.sh --installed  the installed version alone, for scripting
#   version.sh --line       one cached line, for the session-start hook
#
# Exit: 0 up to date, 2 a newer release exists, 1 could not find out.
#
# 1 is the case worth designing for. "You are on the latest" and "I could not
# reach the remote" are different answers, and a checker that returns the first
# when it means the second is exactly the silent failure this repository exists
# to avoid — an agent believing it is current because nothing said otherwise.
#
# The installed version comes from the VERSION file rather than `git describe`,
# because the file survives what the tag does not: a tarball copy, a shallow
# clone, a detached HEAD, a clone whose tags were never fetched. All four report
# an install correctly; `git describe` reports three of them as unknown.
#
# The released version comes from `git ls-remote` against this clone's own
# origin, not the GitHub API: no token to hold, no rate limit to hit, and it
# works against a fork or a mirror without being told about it.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$REPO/VERSION"
# shellcheck source=envpath.sh
. "$REPO/scripts/envpath.sh"
STATE_DIR="$(paynani_state_dir)"
CACHE="$STATE_DIR/version.check"

MAX_AGE=86400       # --line re-checks the remote at most once a day
REMOTE_TIMEOUT=10   # a hook waits on this; it must have a ceiling

installed_version() {
    [ -r "$VERSION_FILE" ] || return 1
    tr -d '[:space:]' < "$VERSION_FILE" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$'
}

latest_version() {
    # GIT_TERMINAL_PROMPT=0 matters more than the timeout: without it, a remote
    # that has gone private asks for a username on a terminal nobody is watching
    # and blocks until something kills it.
    local out
    out=$(GIT_TERMINAL_PROMPT=0 timeout "$REMOTE_TIMEOUT" \
              git -C "$REPO" ls-remote --tags --refs origin 'v*' 2>/dev/null) || return 1
    printf '%s\n' "$out" \
        | sed -n 's#.*refs/tags/v##p' \
        | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' \
        | sort -V | tail -1 | grep .
}

# True when $2 is strictly newer than $1. String comparison gets 1.10.0 wrong,
# which is a bug that arrives quietly and years late; `sort -V` gets it right.
is_newer() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$2" ]
}

# ---------------------------------------------------------------------------

mode="${1:---report}"

if [ "$mode" = "--installed" ]; then
    installed_version && exit 0
    echo "unknown: no readable VERSION file at $VERSION_FILE" >&2
    exit 1
fi

if [ "$mode" = "--line" ]; then
    # One line for the session-start hook, from a cache refreshed at most daily.
    # A session must not pay for a network round trip, and an update that lands
    # today is not urgent enough to check on every start.
    inst=$(installed_version) || { echo "paynani: no VERSION file, version unknown"; exit 1; }

    now=$(date +%s)
    stamp=0
    cached=""
    if [ -r "$CACHE" ]; then
        read -r stamp cached < "$CACHE" 2>/dev/null || true
        case "$stamp" in
            ''|*[!0-9]*) stamp=0 ;;   # unreadable stamp means overdue, not current
        esac
    fi

    if [ $((now - stamp)) -ge "$MAX_AGE" ]; then
        if latest=$(latest_version); then
            cached="$latest"
        else
            cached="?"
        fi
        mkdir -p "$STATE_DIR"
        printf '%s %s\n' "$now" "$cached" > "$CACHE"
        stamp="$now"
    fi

    if [ "$cached" = "?" ] || [ -z "$cached" ]; then
        # Never round this up to "current". Not knowing is its own answer.
        echo "paynani $inst (update status unknown: the last check could not reach the remote; run scripts/version.sh)"
        exit 1
    fi

    if is_newer "$inst" "$cached"; then
        echo "paynani $inst is OUT OF DATE: $cached has been released. Read CHANGELOG.md for what changed between them, then UPGRADE.md. Some releases need a step beyond git pull."
        exit 2
    fi

    if is_newer "$cached" "$inst"; then
        # Ahead of every tag is neither current nor out of date, and the full
        # report has always said so. --line rounded it into the catch-all below
        # and answered "(latest)", which is the one form that gets read: it feeds
        # this hook and healthcheck.py's version field, so the agent was told it
        # was on the newest release while running code nobody had tagged.
        #
        # Exit 0 matches the report, where this is not an error: there is
        # genuinely nothing to pull.
        echo "paynani $inst is AHEAD of the newest tag ($cached): running untagged code, so there is nothing to pull. Run scripts/version.sh for the long form."
        exit 0
    fi

    echo "paynani $inst (latest)"
    exit 0
fi

if [ "$mode" != "--report" ]; then
    echo "usage: version.sh [--installed|--line]" >&2
    exit 64
fi

# ---- full report ----------------------------------------------------------

if ! inst=$(installed_version); then
    cat >&2 <<EOF
No readable VERSION file at $VERSION_FILE.

Every release ships one. A clone without it has been edited, and the answer is
the same either way: treat it as out of date and follow UPGRADE.md.
EOF
    exit 1
fi

if ! latest=$(latest_version); then
    cat >&2 <<EOF
installed: $inst
latest:    could not find out

Reading the released version from the remote failed. Not "there is no newer
release": no answer at all. Do not report this as up to date.

  git -C $REPO ls-remote --tags --refs origin 'v*'

Run that to see why. Usual causes: no network from this host, a remote that has
been renamed or made private, or a clone with no origin.
EOF
    exit 1
fi

echo "installed: $inst"
echo "latest:    $latest"
echo

if is_newer "$inst" "$latest"; then
    cat <<EOF
$latest has been released and this install is on $inst.

Read every CHANGELOG.md entry between them before pulling. Releases carry an
"Upgrade actions" section when a pull alone is not enough, and the change that
has broken an install once already was a file moving to a path the systemd unit
still named.

Then follow UPGRADE.md, which is that sequence in order:

  cd $REPO && git pull --ff-only origin main
EOF
    exit 2
fi

if is_newer "$latest" "$inst"; then
    changelog_version=${inst//./\\.}
    if grep -qE "^## ${changelog_version}([^0-9]|$)" "$REPO/CHANGELOG.md" 2>/dev/null; then
        cat <<EOF
This install is ahead of the newest tag ($latest), so it is running code that
has not been tagged yet. CHANGELOG.md does describe $inst, so read that entry
for what you have; there is nothing newer to pull.
EOF
    else
        cat <<EOF
This install is ahead of the newest tag ($latest), so it is running code that
has not been tagged yet. CHANGELOG.md has no entry for $inst either, so the
commit history is the only description of what you are running.
EOF
    fi
    exit 0
fi

echo "Up to date."
exit 0
