#!/usr/bin/env bash
# One rule about where this install keeps its files, written in three languages.
#
# Python answers for the listener and preflight, shell for send.sh and the setup
# script, PHP for the form. They agreed before this test existed only because
# they all hard-coded the same string; now they resolve, and a resolver that
# drifts sends one half of the install to a file the other half never reads. The
# symptom is an agent that starts, connects, and refuses to send.
#
# Every accessor is checked here, not just the credentials one: a resolver that
# drifts on the state tree presents as a quiet mailbox rather than an error.
#
#   scripts/test_paths.sh

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
pass=0
fail=0
skip=0

check() {   # description, expected, actual
    if [ "$2" = "$3" ]; then
        printf 'ok   %s\n' "$1"
        pass=$((pass + 1))
    else
        printf 'FAIL %s\n       expected: %s\n       actual:   %s\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}

matches() {  # value, shell-pattern
    case "$1" in $2) echo yes ;; *) echo no ;; esac
}

py() { HOME="$1" PAYNANI_ENV="${2:-}" python3 "$ROOT/harness/paths.py" "${3:-env}"; }
sh_() (
    HOME="$1"
    PAYNANI_ENV="${2:-}"
    . "$ROOT/scripts/envpath.sh"
    case "${3:-env}" in
        env)         paynani_env_file ;;
        state)       paynani_state_dir ;;
        root)        paynani_root ;;
        config)      paynani_config_dir ;;
        runtime-env) paynani_runtime_env ;;
        manifest)    paynani_manifest ;;
        hermes)      paynani_hermes_dir ;;
        roster)      paynani_roster ;;
    esac
)
php_() {
    # Two different reasons to answer nothing, and they must not be conflated.
    # NA means the form never needed this accessor, so nothing is lost by not
    # asking. NOPHP means this host cannot check the PHP half of a question it
    # does answer -- a real gap in coverage, and the only one worth counting.
    #
    # Applicability is decided first on purpose. Testing for php first would
    # report every accessor as a missing check on a php-less host and overstate
    # the gap by more than double, which is its own kind of wrong number.
    #
    # The form only ever needs these two, and they are the two that must not
    # disagree with the tools it configures.
    case "${3:-env}" in
        env|state) ;;
        *) echo SKIP_NA; return ;;
    esac
    command -v php >/dev/null 2>&1 || { echo SKIP_NOPHP; return; }
    HOME="$1" PAYNANI_ENV="${2:-}" php -r '
        require "'"$ROOT"'/webapp/lib/envfile.php";
        echo "'"${3:-env}"'" === "env" ? env_path() : state_dir();
    ' 2>/dev/null
}

# Sets RESOLVED rather than printing it: this also prints check results, and a
# caller capturing stdout would swallow them into the answer.
RESOLVED=""
agree() {   # description, home, [override], [what]
    local desc=$1 home=$2 override=${3:-} what=${4:-env}
    local p s h
    p=$(py "$home" "$override" "$what")
    s=$(sh_ "$home" "$override" "$what")
    h=$(php_ "$home" "$override" "$what")
    check "$desc: shell agrees with python" "$p" "$s"
    case "$h" in
        SKIP_NA)   ;;
        SKIP_NOPHP)
            # Not silence. A run without php checks two implementations of
            # three, and a suite reporting "0 failed" either way is how #88's
            # PHP half came to be "verified" on a host that never ran it.
            skip=$((skip + 1)) ;;
        *) check "$desc: php agrees with python" "$p" "$h" ;;
    esac
    RESOLVED="$p"
}

# Every accessor, in one layout, from all three languages. The point is not the
# individual answers — those are checked below — but that nothing drifts.
agree_all() {   # description, home
    local desc=$1 home=$2 what
    for what in env state root config runtime-env manifest hermes roster; do
        agree "$desc [$what]" "$home" "" "$what"
    done
}

# ---------------------------------------------------------------------------
# A host with nothing on it. Everything hangs off the clone, and nothing is
# written under ~/.config or ~/.local/state at all.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
agree_all "fresh host" "$home"
check "fresh host: credentials are .env in the clone" "$ROOT/.env" "$(py "$home" "" env)"
check "fresh host: state is one tree in the clone" "$ROOT/state" "$(py "$home" "" state)"
check "fresh host: runtime config is in the clone" "$ROOT/runtime.env" "$(py "$home" "" runtime-env)"
check "fresh host: manifest is in the clone" "$ROOT/install.manifest" "$(py "$home" "" manifest)"
check "fresh host: hermes secrets are in the clone" "$ROOT/hermes" "$(py "$home" "" hermes)"
check "fresh host: roster is in the clone" "$ROOT/roster.md" "$(py "$home" "" roster)"
check "fresh host: nothing resolves under ~/.config" "no" \
    "$(matches "$(py "$home" "" config)" "$home/.config/*")"
check "fresh host: nothing resolves under ~/.local/state" "no" \
    "$(matches "$(py "$home" "" state)" "$home/.local/state/*")"
rm -rf "$home"

# ---------------------------------------------------------------------------
# A stray ~/.config/paynani is not an install.
#
# Somebody ran mkdir and stopped, or an uninstall left the directory behind.
# Nothing outside the clone is ever adopted, and this pins that: adopting a
# directory because it is named after this project would put an agent's
# credentials somewhere the operator never chose.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.config/paynani" "$home/.local/state/paynani"
agree_all "empty leftover directories" "$home"
check "empty leftover directories: not adopted for credentials" "$ROOT/.env" "$(py "$home" "" env)"
check "empty leftover directories: not adopted for state" "$ROOT/state" "$(py "$home" "" state)"
rm -rf "$home"

# ---------------------------------------------------------------------------
# Setting one per-path override splits the paths on purpose. The "cannot
# disagree" property is conditional on neither being set, and this pins that
# reading rather than leaving the docstring to carry it.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
check "PAYNANI_STATE alone moves state and leaves credentials" "$ROOT/.env" \
    "$(HOME="$home" PAYNANI_STATE=/srv/state python3 "$ROOT/harness/paths.py" env)"
check "PAYNANI_STATE alone is honoured for state" "/srv/state" \
    "$(HOME="$home" PAYNANI_STATE=/srv/state python3 "$ROOT/harness/paths.py" state)"
rm -rf "$home"

# ---------------------------------------------------------------------------
# An install that said where its credentials are. Nothing second-guesses it,
# including a harness file sitting right there.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.openclaw/workspace"
printf 'AGENT_EMAIL_ACCOUNT=ignored@example.com\n' >"$home/.openclaw/workspace/.env"
agree "explicit override" "$home" "/etc/paynani/env"; resolved=$RESOLVED
check "explicit override: wins over everything" "/etc/paynani/env" "$resolved"
rm -rf "$home"

# ---------------------------------------------------------------------------
# The same for the state tree. An install that pinned it stays pinned.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
check "explicit state override: wins on a fresh host" "/srv/paynani-state" \
    "$(HOME="$home" PAYNANI_STATE=/srv/paynani-state python3 "$ROOT/harness/paths.py" state)"
check "explicit state override: shell agrees" "/srv/paynani-state" \
    "$(HOME="$home" PAYNANI_STATE=/srv/paynani-state bash -c \
        ". '$ROOT/scripts/envpath.sh'; paynani_state_dir")"
rm -rf "$home"

# ---------------------------------------------------------------------------
# A different mail deployment on the same host is not this one.
#
# Apollo's box runs its own AgentMail install with its own configuration under
# ~/.config/apollo-agentmail. Resolving by "something mail-shaped is nearby"
# would adopt it: the install would read credentials it was never given. Only
# the names this project has ever written are looked at.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.config/apollo-agentmail" "$home/.hermes"
printf 'ACCOUNT=someone-elses@example.com\n' >"$home/.config/apollo-agentmail/config"
printf 'HERMES_TOKEN=not-ours\n' >"$home/.hermes/.env"
agree_all "unrelated deployment" "$home"
check "unrelated deployment: is not adopted" "$ROOT/.env" "$(py "$home" "" env)"
check "unrelated deployment: its files are untouched" "someone-elses@example.com" \
    "$(sed -n 's/^ACCOUNT=//p' "$home/.config/apollo-agentmail/config")"
check "unrelated deployment: nothing is written into a runtime's own env" "HERMES_TOKEN=not-ours" \
    "$(cat "$home/.hermes/.env")"
rm -rf "$home"

# ---------------------------------------------------------------------------
# The repo root is found, not assumed. The old hard-coded OpenClaw path was
# wrong on every other host and failed silently, because the session hook
# swallows its own errors so a session is never blocked.
# ---------------------------------------------------------------------------
found=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT/harness')
import paths; print(paths.repo_root())
")
check "the repo root is this checkout" "$ROOT" "$found"
home=$(mktemp -d)
checkout="$home/elsewhere/paynani"
mkdir -p "$checkout/harness"
checkout=$(cd "$checkout" && pwd -P)
cp "$ROOT/harness/paths.py" "$checkout/harness/paths.py"
found=$(CHECKOUT="$checkout" python3 - <<'PY'
import os
import sys

sys.path.insert(0, os.path.join(os.environ["CHECKOUT"], "harness"))
import paths

print(paths.repo_root())
PY
)
check "the repo root is found from an arbitrary checkout" "$checkout" "$found"
rm -rf "$home"
check "the install root is the clone" "$ROOT" "$(py "$(mktemp -d)" "" root)"

# ---------------------------------------------------------------------------
# Every runtime-owned path is ignored by git.
#
# The install now lives inside the working tree, so an ignore rule is the only
# thing standing between a mail password and `git add -A`. This is the cheap
# half of that guarantee; scripts/install.sh refuses to write if it fails.
# ---------------------------------------------------------------------------
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    for relative in .env runtime.env install.manifest roster.md \
        hermes/notify.secret state/idle.json state/mail.log; do
        if git -C "$ROOT" check-ignore -q "$relative"; then
            check "git ignores $relative" ignored ignored
        else
            check "git ignores $relative" ignored "NOT ignored"
        fi
    done
    for relative in .env runtime.env install.manifest roster.md; do
        if git -C "$ROOT" ls-files --error-unmatch "$relative" >/dev/null 2>&1; then
            check "git does not track $relative" untracked "TRACKED"
        else
            check "git does not track $relative" untracked untracked
        fi
    done
else
    printf 'skip git ignore checks (not a git checkout)\n'
fi

# ---------------------------------------------------------------------------
# A harness keeps its agent's credentials in its own workspace, and this reads
# them where they lie.
#
# Found the hard way on the first Hermes Agent install: the operator provisioned
# ~/.hermes/workspace/.env, which is where the install prompt tells an agent to
# look, and the resolver — which knew only the OpenClaw path — answered with the
# clone. AGENTS.md step 2 then reported NO CREDENTIALS on a host whose
# credentials were one directory up, and the install had to be finished with a
# symlink nobody should have needed. #59.
#
# Only the credentials move. State, runtime.env, the manifest and hermes/ still
# hang off the clone, and that split is deliberate: the harness owns that file
# and this project does not.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.hermes/workspace"
printf 'PAYNANI_EMAIL=agent@example.com\n' >"$home/.hermes/workspace/.env"
agree_all "hermes harness" "$home"
check "hermes harness: credentials are read where the harness keeps them" \
    "$home/.hermes/workspace/.env" "$(py "$home" "" env)"
check "hermes harness: state still hangs off the clone" "$ROOT/state" "$(py "$home" "" state)"
check "hermes harness: runtime config still hangs off the clone" \
    "$ROOT/runtime.env" "$(py "$home" "" runtime-env)"
check "hermes harness: hermes secrets still hang off the clone" \
    "$ROOT/hermes" "$(py "$home" "" hermes)"
check "hermes harness: nothing resolves under ~/.config" "no" \
    "$(matches "$(py "$home" "" config)" "$home/.config/*")"
check "hermes harness: an explicit override still wins" "/srv/named.env" \
    "$(py "$home" /srv/named.env env)"
# The file is asked about as a link too: an operator may point the harness path
# at a credential file kept elsewhere, and a link to a file says where it belongs.
rm "$home/.hermes/workspace/.env"
ln -s "$home/elsewhere.env" "$home/.hermes/workspace/.env"
agree "hermes harness symlink" "$home"
check "hermes harness: a dangling link is still where the credentials belong" \
    "$home/.hermes/workspace/.env" "$(py "$home" "" env)"
rm -rf "$home"

# ---------------------------------------------------------------------------
# Claude Code is a harness root like the other two. It was once added to
# HARNESS_ROOTS in harness/paths.py but not to the shell or PHP copies — see
# #88 — so this pins all three in agreement the same way the hermes and
# openclaw cases above do.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.claude/workspace"
printf 'PAYNANI_EMAIL=agent@example.com\n' >"$home/.claude/workspace/.env"
agree_all "claude harness" "$home"
check "claude harness: credentials are read where the harness keeps them" \
    "$home/.claude/workspace/.env" "$(py "$home" "" env)"
check "claude harness: state still hangs off the clone" "$ROOT/state" "$(py "$home" "" state)"
check "claude harness: runtime config still hangs off the clone" \
    "$ROOT/runtime.env" "$(py "$home" "" runtime-env)"
check "claude harness: hermes secrets still hang off the clone" \
    "$ROOT/hermes" "$(py "$home" "" hermes)"
case "$(py "$home" "" config)" in
    "$home"/.config/*) claude_under_config=yes ;;
    *) claude_under_config=no ;;
esac
check "claude harness: nothing resolves under ~/.config" "no" \
    "$claude_under_config"
check "claude harness: an explicit override still wins" "/srv/named.env" \
    "$(py "$home" /srv/named.env env)"
rm -rf "$home"

# ---------------------------------------------------------------------------
# The runtime's own config is not the agent's mailbox.
#
# ~/.hermes/.env holds Hermes' gateway token. The rule matches
# <harness-root>/workspace/.env exactly and nothing else, because "something
# mail-shaped nearby" is how an install reads credentials it was never given.
# The unrelated-deployment case above plants exactly this file; this states the
# reason separately so the next reader cannot delete one and keep the other.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.hermes"
printf 'HERMES_TOKEN=not-ours\n' >"$home/.hermes/.env"
agree_all "runtime own config" "$home"
check "a runtime's own .env is not the agent's credentials" "$ROOT/.env" \
    "$(py "$home" "" env)"
rm -rf "$home"

# ---------------------------------------------------------------------------
# Credentials are not an install. #72.
#
# A brand-new OpenClaw agent does exactly what the README tells it: it puts its
# mailbox settings in its harness's workspace. That file is credentials and
# nothing more: it is written by the human or by the harness, never by this
# project, so it says where to read a password and says nothing about where
# this install keeps its own files. State, config and secrets stay in the
# clone regardless.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.openclaw/workspace"
printf 'AGENT_EMAIL_ACCOUNT=agent@example.com\n' >"$home/.openclaw/workspace/.env"
agree_all "openclaw harness" "$home"
check "openclaw harness: credentials are read where they lie" \
    "$home/.openclaw/workspace/.env" "$(py "$home" "" env)"
check "openclaw harness: a credentials file is not an install (state)" \
    "$ROOT/state" "$(py "$home" "" state)"
check "openclaw harness: a credentials file is not an install (config)" \
    "$ROOT/config-is-the-clone" "$(py "$home" "" config)/config-is-the-clone"
check "openclaw harness: nothing resolves under ~/.local/state" "no" \
    "$(matches "$(py "$home" "" state)" "$home/.local/state/*")"
check "openclaw harness: the hermes secrets stay in the clone" "$ROOT/hermes" \
    "$(py "$home" "" hermes)"
rm -rf "$home"

# ---------------------------------------------------------------------------
# Two harnesses on one host: neither is adopted.
#
# Two agents share the machine. Either file could be the wrong mailbox, and a
# listener on the wrong mailbox is indistinguishable from a quiet one — the
# failure this whole module exists to prevent. So the answer falls back to the
# file this install owns, and the operator names the right one with
# PAYNANI_ENV.
#
# Two non-OpenClaw roots would be truer to the future, but there is only one
# today. Since #72 the OpenClaw credentials file no longer pins the layout, so
# this host is an ordinary one and the fallback is the clone's own file.
# ---------------------------------------------------------------------------
home=$(mktemp -d)
mkdir -p "$home/.hermes/workspace" "$home/.openclaw/workspace"
printf 'PAYNANI_EMAIL=hermes@example.com\n' >"$home/.hermes/workspace/.env"
printf 'AGENT_EMAIL_ACCOUNT=openclaw@example.com\n' >"$home/.openclaw/workspace/.env"
agree_all "two harnesses" "$home"
check "two harnesses: neither agent's mailbox is guessed at" "no" \
    "$(matches "$(py "$home" "" env)" "$home/.hermes/*")"
check "two harnesses: the fallback is the file this install owns" "$ROOT/.env" \
    "$(py "$home" "" env)"
check "two harnesses: an explicit override is how you say which" "/srv/named.env" \
    "$(py "$home" /srv/named.env env)"
rm -rf "$home"

if [ "$skip" -gt 0 ]; then
    # php is not a prerequisite for running paynani -- AGENTS.md wants it
    # only for the setup form -- so a host without it is fully supported and
    # this is not a failure. It is only allowed to pass while it says so.
    printf '\nskip %d php agreement checks (php not on PATH)\n' "$skip"
    printf '\n%d passed, %d failed, %d skipped (no php)\n' "$pass" "$fail" "$skip"
else
    printf '\n%d passed, %d failed\n' "$pass" "$fail"
fi
[ "$fail" -eq 0 ]
