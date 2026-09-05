#!/usr/bin/env bash
# Where this install keeps its files, for the shell half. The rule is written
# down in harness/paths.py and the two are asserted to agree in
# scripts/test_paths.sh; change both or neither.
#
# Sourced, not run: it defines functions and sets nothing.

# The clone, which is also the install root. Resolved from this file rather than
# from $PWD or $HOME, so a script run from anywhere gets the same answer Python
# gets. BASH_SOURCE is this file even when sourced, which is the point.
paynani_root() {
    (cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
}

# Every harness keeps its agent's mail credentials in the workspace folder of its
# own installation directory. One pattern, not a list of special cases: a new
# runtime is a new root here and nothing else. Keep in step with HARNESS_ROOTS /
# HARNESS_ENV_RELATIVE in harness/paths.py and the same pair in
# webapp/lib/paths.php; scripts/test_paths.sh asserts all three agree.
#
# The OpenClaw root is listed because it is an instance of the rule rather than
# an exception to it.
PAYNANI_HARNESS_ROOTS=".openclaw .hermes .claude .codex"
PAYNANI_HARNESS_ENV_RELATIVE="workspace/.env"

paynani_config_dir() {
    paynani_root
}

# One value out of the installer-generated runtime.env, or nothing. Kept
# deliberately identical to recorded_env() in harness/paths.py and to
# recorded_env() in webapp/lib/paths.php: three implementations of one rule,
# and scripts/test_paths.sh exists because they have drifted before.
paynani_recorded_env() {
    local file line value
    file="$(paynani_runtime_env)"
    [ -f "$file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        case "$line" in
            PAYNANI_ENV=*)
                value=${line#PAYNANI_ENV=}
                value=${value%\"}; value=${value#\"}
                value=${value%\'}; value=${value#\'}
                [ -n "$value" ] && printf '%s' "$value"
                return 0
                ;;
        esac
    done < "$file"
}

paynani_env_file() {
    local recorded
    if [ -n "${PAYNANI_ENV:-}" ]; then
        printf '%s' "$PAYNANI_ENV"
        return
    fi

    # What the install recorded, when it was told which file is its own.
    recorded="$(paynani_recorded_env)"
    if [ -n "$recorded" ]; then
        printf '%s' "$recorded"
        return
    fi

    # Read the harness's file where it lies. Everything else still hangs off
    # the clone; that split is deliberate and is explained in harness/paths.py.
    # Two harness files means two agents share this host, either could be the
    # wrong mailbox, and a listener on the wrong mailbox is indistinguishable
    # from a quiet one — so neither is adopted.
    local root candidate found="" count=0
    for root in $PAYNANI_HARNESS_ROOTS; do
        candidate="$HOME/$root/$PAYNANI_HARNESS_ENV_RELATIVE"
        if [ -f "$candidate" ] || [ -L "$candidate" ]; then
            found=$candidate
            count=$((count + 1))
        fi
    done
    if [ "$count" -eq 1 ]; then
        printf '%s' "$found"
        return
    fi
    printf '%s/.env' "$(paynani_root)"
}

paynani_state_dir() {
    if [ -n "${PAYNANI_STATE:-}" ]; then
        printf '%s' "$PAYNANI_STATE"
        return
    fi

    printf '%s/state' "$(paynani_root)"
}

paynani_runtime_env() { printf '%s/runtime.env' "$(paynani_config_dir)"; }
paynani_manifest() { printf '%s/install.manifest' "$(paynani_config_dir)"; }
paynani_hermes_dir() { printf '%s/hermes' "$(paynani_config_dir)"; }
# roster.md, the one name. See harness/paths.py roster() for why there is no
# second one: an allowlist with two possible filenames can be edited in the file
# nothing reads, and that failure is silent.
paynani_roster() {
	printf '%s/roster.md' "$(paynani_root)"
}
