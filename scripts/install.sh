#!/usr/bin/env bash
# Idempotent paynani installer — FR7 implementation skeleton.
#
# The public CLI contract, inert discovery, and fail-closed ownership inventory
# land before any host mutation phase. Every valid non-help, non-dry invocation
# remains deliberately inert.

set -euo pipefail

readonly EX_OK=0
readonly EX_CHANGED=10
readonly EX_USAGE=64
readonly EX_CONFIG=78
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
readonly ROOT

if [[ "$(uname -s 2>/dev/null || true)" == Darwin ]]; then
    exec python3 "$ROOT/scripts/install_macos.py" "$@"
fi

# The installer must not write into the tree it is converging.
#
# Several helpers here are Python that imports repository-local modules, and the
# install root is now the clone — so CPython dropped __pycache__/*.pyc into
# harness/ and harness/adapters/ as a side effect of running the installer. The
# ownership model says the repository is preserved, not managed, and an install
# that quietly modifies it contradicts that.
#
# It also hid itself: the caches are gitignored, so `git status` stayed clean,
# and once they existed a rerun looked inert. Only a clean clone shows it, which
# is why the regression test builds one.
export PYTHONDONTWRITEBYTECODE=1

usage() {
    cat <<'EOF'
Usage:
  scripts/install.sh --runtime openclaw [--upgrade|--uninstall] [--dry-run]
  scripts/install.sh --runtime hermes [--deliver TARGET --chat-id ID | --profile PROFILE]
  scripts/install.sh --runtime claudecode [--upgrade|--uninstall] [--dry-run]
                     [--upgrade|--uninstall] [--non-interactive]
                     [--notify-secret-file PATH --roster-secret-file PATH]
                     [--dry-run]

Modes:
  (default)          Install or converge the selected runtime
  --upgrade          Upgrade/converge artifacts owned by this installer
  --uninstall        Remove only artifacts owned by this installer

Options:
  --runtime RUNTIME          Required: openclaw, hermes, or claudecode
  --deliver TARGET          Guidance label for an operator-managed Hermes target
  --chat-id ID               Guidance label for that target's chat ID
  --profile PROFILE          Guidance label for an existing operator-managed profile
  --non-interactive          Never create or print route secrets
  --notify-secret-file PATH  Pre-provisioned Hermes notification-route secret
  --roster-secret-file PATH  Pre-provisioned Hermes roster-route secret
  --dry-run                  Discover and plan without executing runtimes or changing host
  -h, --help                 Show this help

Exit status:
  0   Success: converged and no changes were needed
  10  Success: converged and changes were made
  64  Usage error
  78  Configuration, prerequisite, or not-yet-implemented phase error

Exit status 10 is success. Shell wrappers, CI, and configuration-management
callers must accept both 0 and 10 as successful convergence.

FR7 boundary status: OpenClaw filesystem artifacts converge atomically;
service enablement and Hermes mutation remain deferred.
EOF
}

die_usage() {
    printf 'install: %s\n' "$1" >&2
    printf "Try 'scripts/install.sh --help'.\n" >&2
    exit "$EX_USAGE"
}

die_config() {
    printf 'install: %s\n' "$1" >&2
    exit "$EX_CONFIG"
}

resolve_command() {
    command -v "$1" 2>/dev/null || return 1
}

resolve_in_path() {
    local name=$1 search_path=$2
    PATH="$search_path" command -v "$name" 2>/dev/null || return 1
}

systemd_service_path() {
    local systemctl_bin=$1 environment line
    environment=$("$systemctl_bin" --user show-environment 2>/dev/null) || return 1
    while IFS= read -r line; do
        if [[ "$line" == PATH=* ]]; then
            printf '%s' "${line#PATH=}"
            return 0
        fi
    done <<<"$environment"
    return 2
}

validate_hermes_secret_files() {
    local python=$1 output
    if ! output=$(PYTHONPATH="$ROOT/harness" "$python" - \
        "$notify_secret_file" "$roster_secret_file" <<'PYINNER'
import hmac
import sys

# Installer validation deliberately shares the adapter contract. A regression
# test pins this import and its mode-0600 rejection behavior.
from adapters.hermes import _load_secret

loaded = []
for label, path in (("notify", sys.argv[1]), ("roster", sys.argv[2])):
    secret, error = _load_secret(path)
    if error:
        print(f"{label} secret: {error}")
        raise SystemExit(1)
    loaded.append(secret)
if hmac.compare_digest(loaded[0], loaded[1]):
    print("Hermes notify and roster route secrets must differ")
    raise SystemExit(1)
PYINNER
    ); then
        printf '%s' "$output"
        return 1
    fi
}

# What this installer already recorded, for a run that did not repeat it.
#
# `runtime.env` is generated here (see render_artifact's
# generated-runtime-config branch) and, until now, never read back — so a second
# run on a converged Hermes host demanded every value it had already written and
# failed with "HERMES_NOTIFY_URL is required" on a host that was configured,
# running and delivering mail. Re-running the installer is ordinary: it is what
# an upgrade that changes a rendered path asks for.
#
# Parsed as KEY=VALUE data and never sourced, undoing exactly the escaping the
# writer applies — change both or neither. It holds no secrets; the two route
# secrets are named by path and never by value.
declare -A recorded_runtime_env=()

load_recorded_runtime_env() {
    local file line name value
    file=$(paynani_runtime_env)
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line=${line%$'\r'}
        [[ -n "$line" && "$line" != '#'* && "$line" == *=* ]] || continue
        name=${line%%=*}
        name=${name//[[:space:]]/}
        [[ "$name" == HERMES_* ]] || continue
        value=${line#*=}
        if [[ ${#value} -ge 2 && "$value" == '"'*'"' ]]; then
            value=${value:1:${#value}-2}
            value=${value//\\\"/\"}
            value=${value//\\\\/\\}
        fi
        recorded_runtime_env[$name]=$value
    done < "$file"
}

# Precedence: an explicit flag, then the environment, then this file, then fail.
# An install that has never converged has no file and still fails exactly as it
# did before, which is correct — there is nothing to recall.
apply_recorded_runtime_env() {
    local name source
    source=$(paynani_runtime_env)
    load_recorded_runtime_env
    for name in HERMES_NOTIFY_URL HERMES_ROSTER_URL HERMES_HEALTH_URL \
                HERMES_SIGNATURE_MODE HERMES_ALLOW_REMOTE; do
        if [[ -z "${!name:-}" && -n "${recorded_runtime_env[$name]:-}" ]]; then
            export "$name=${recorded_runtime_env[$name]}"
            printf 'inventory recalled=%s from=%s\n' "$name" "$source"
        fi
    done
    # Only when neither was given. Supplying one and recalling the other would
    # pair a flag the operator chose with a path they did not, and the
    # supplied-together check below exists to stop exactly that kind of half
    # answer.
    if [[ -z "$notify_secret_file" && -z "$roster_secret_file" &&
          -n "${recorded_runtime_env[HERMES_NOTIFY_SECRET_FILE]:-}" &&
          -n "${recorded_runtime_env[HERMES_ROSTER_SECRET_FILE]:-}" ]]; then
        notify_secret_file=${recorded_runtime_env[HERMES_NOTIFY_SECRET_FILE]}
        roster_secret_file=${recorded_runtime_env[HERMES_ROSTER_SECRET_FILE]}
        printf 'inventory recalled=%s from=%s\n' HERMES_NOTIFY_SECRET_FILE "$source"
        printf 'inventory recalled=%s from=%s\n' HERMES_ROSTER_SECRET_FILE "$source"
    fi
}

validate_hermes_route_environment() {
    local name value
    for name in HERMES_NOTIFY_URL HERMES_ROSTER_URL HERMES_HEALTH_URL; do
        value=${!name:-}
        [[ -n "$value" ]] || {
            printf '%s is required; supply the full operator-approved URL' "$name"
            return 1
        }
        [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || {
            printf '%s must be a single-line URL' "$name"
            return 1
        }
    done
    if [[ "${HERMES_SIGNATURE_MODE:-v2}" != v2 ]]; then
        printf 'HERMES_SIGNATURE_MODE must be v2 for installer route verification'
        return 1
    fi
}

prereq_error() {
    if ((dry_run)); then
        prerequisite_errors+=("$1")
    else
        die_config "$1"
    fi
}

discover_prerequisites() {
    local python="" systemctl_bin="" loginctl_bin="" linger="unknown" user_name=""
    local runtime_cli="" logrotate_bin="" service_path=""
    local systemd_state="unavailable" quoted_user path_status
    local service_path_error_reported=0
    prerequisite_errors=()

    if [[ -z "${HOME:-}" || "$HOME" != /* ]]; then
        prereq_error 'HOME must be set to an absolute path'
    fi

    python=$(resolve_command python3 || true)
    [[ -n "$python" ]] || prereq_error 'python3 executable not found'

    systemctl_bin=$(resolve_command systemctl || true)
    if [[ -z "$systemctl_bin" ]]; then
        if [[ "$mode" == uninstall ]]; then
            systemd_state="unavailable (filesystem inventory continues)"
        else
            prereq_error 'systemctl executable not found; a systemd user session is required'
        fi
    elif service_path=$(systemd_service_path "$systemctl_bin"); then
        systemd_state="available"
    else
        path_status=$?
        if ((path_status == 2)); then
            systemd_state="available (PATH not reported)"
            if [[ "$mode" != uninstall && "$runtime" == openclaw ]]; then
                prereq_error 'systemd user environment does not report PATH; cannot verify OpenClaw'
                service_path_error_reported=1
            fi
        elif [[ "$mode" == uninstall ]]; then
            systemd_state="unavailable (filesystem inventory continues)"
            systemctl_bin=""
        else
            prereq_error 'systemctl --user is unavailable; use a host with a systemd user session'
        fi
    fi

    user_name=$(id -un 2>/dev/null || true)
    if [[ -z "$user_name" || ! "$user_name" =~ ^[A-Za-z0-9_.-]+$ ]]; then
        prereq_error 'cannot derive a safe service account name from id -un'
    fi
    loginctl_bin=$(resolve_command loginctl || true)
    if [[ -z "$loginctl_bin" ]]; then
        if [[ "$mode" == uninstall ]]; then
            linger="unknown (informational; uninstall continues)"
        else
            prereq_error 'loginctl executable not found; cannot verify user lingering'
        fi
    elif [[ -n "$user_name" ]]; then
        linger=$("$loginctl_bin" show-user "$user_name" -p Linger --value 2>/dev/null || true)
        if [[ "$linger" != yes ]]; then
            if [[ "$mode" == uninstall ]]; then
                linger="disabled (informational; uninstall continues)"
            else
                printf -v quoted_user '%q' "$user_name"
                prereq_error "user lingering is disabled; run: sudo loginctl enable-linger $quoted_user"
            fi
        else
            linger="enabled"
        fi
    fi

    if [[ "$mode" == uninstall ]]; then
        runtime_cli="not-required-for-uninstall"
    else
        if [[ "$runtime" == claudecode ]]; then
            # No runtime CLI is required. Delivery is a file append, and the
            # `claude` binary is only used by the opt-in agent mode -- so
            # demanding it here would refuse a host that this runtime works
            # perfectly well on. The spool being writable is the real
            # prerequisite, and the adapter's own check() owns that question.
            runtime_cli="not-required-for-claudecode"
        elif [[ "$runtime" == openclaw ]]; then
            if [[ -z "$service_path" ]]; then
                if ((service_path_error_reported == 0)); then
                    prereq_error 'openclaw executable cannot be verified because the systemd user PATH is unavailable
  fix: set OPENCLAW and PATH in ~/.config/environment.d/10-openclaw-user-path.conf,
       then `systemctl --user set-environment` for the manager already running
  see: INSTALL.md section 6, "Check the dispatcher can actually reach openclaw"'
                fi
            else
                runtime_cli=$(resolve_in_path "$runtime" "$service_path" || true)
                if [[ -z "$runtime_cli" ]]; then
                    prereq_error 'openclaw executable not found in the systemd user PATH
  why: a systemd user service gets a minimal PATH with nothing under $HOME, so an
       npm-installed binary your shell finds is invisible here
  fix: set OPENCLAW and PATH in ~/.config/environment.d/10-openclaw-user-path.conf,
       then `systemctl --user set-environment` for the manager already running
  see: INSTALL.md section 6, "Check the dispatcher can actually reach openclaw"'
                fi
            fi
        else
            runtime_cli=$(resolve_command hermes || true)
            if [[ -z "$runtime_cli" ]]; then
                prereq_error 'hermes executable not found in the installer PATH'
            fi
        fi
        if [[ "$runtime" == hermes && -n "$notify_secret_file" && -n "$python" ]]; then
            local secret_error=""
            if ! secret_error=$(validate_hermes_secret_files "$python"); then
                prereq_error "$secret_error"
            fi
        fi
        if [[ "$runtime" == hermes ]]; then
            local route_error=""
            if ! route_error=$(validate_hermes_route_environment); then
                prereq_error "$route_error"
            fi

        fi
    fi

    logrotate_bin=$(resolve_command logrotate || true)
    printf 'discovery runtime=%s\n' "$runtime"
    printf 'repo_root=%s\n' "$ROOT"
    [[ -n "$python" ]] && printf 'python=%s\n' "$python"
    [[ -n "$runtime_cli" ]] && printf 'runtime_cli=%s\n' "$runtime_cli"
    printf 'service_path=%s\n' "${service_path:-not-reported}"
    if ((dry_run)); then
        printf 'runtime_probe=deferred (dry-run never executes runtime code)\n'
    else
        printf 'runtime_probe=deferred (filesystem-only convergence never executes runtime code)\n'
    fi
    printf 'systemd_user=%s\n' "$systemd_state"
    printf 'linger=%s\n' "$linger"
    if [[ -n "$logrotate_bin" ]]; then
        printf 'logrotate=%s\n' "$logrotate_bin"
    else
        printf 'logrotate=absent (managed Python rotation will be used)\n'
    fi
    if [[ -n "${XDG_CONFIG_HOME:-}${XDG_STATE_HOME:-}" ]]; then
        printf 'xdg_overrides=ignored (the install root is the clone)\n'
    fi

    if ((${#prerequisite_errors[@]})); then
        printf 'prerequisite failures (%d):\n' "${#prerequisite_errors[@]}" >&2
        local error
        for error in "${prerequisite_errors[@]}"; do
            printf -- '- %s\n' "$error" >&2
        done
        return 1
    fi
    discovered_python=$python
    discovered_systemctl=$systemctl_bin
    discovered_runtime_cli=$runtime_cli
}

# One rule, and it is not written here. harness/paths.py has it, scripts/
# envpath.sh is the shell half, and scripts/test_paths.sh asserts the two agree.
# A fourth copy in the installer is how the units end up pointing at a file the
# listener never reads.
# shellcheck source=envpath.sh
. "$ROOT/scripts/envpath.sh"

resolve_credentials_path() {
    paynani_env_file
}

validate_container_chain() {
    local target=$1 anchor current relative component owner mode mode_value
    local -a components=()

    # Two anchors, because the install root is wherever the clone is and that is
    # not necessarily under $HOME. Whichever anchor is used, it is validated
    # itself before anything beneath it: the loop's first iteration checks
    # `current` before appending a component.
    if [[ "$target" == "$HOME" || "$target" == "$HOME"/* ]]; then
        anchor=$HOME
    elif [[ "$target" == "$install_root" || "$target" == "$install_root"/* ]]; then
        anchor=$install_root
    else
        printf 'inventory conflict-container=%s reason=outside-home-and-install-root\n' "$target"
        inventory_conflicts=1
        inventory_blocked_details+=("$target"$'\t'outside-home-and-install-root)
        return 1
    fi

    current=$anchor
    relative=${target#"$anchor"}
    relative=${relative#/}
    if [[ -n "$relative" ]]; then
        IFS='/' read -r -a components <<<"$relative"
    fi
    for component in "" "${components[@]}"; do
        if [[ -n "$component" ]]; then
            current="$current/$component"
        fi
        if [[ -L "$current" ]]; then
            printf 'inventory conflict-container=%s reason=symlink\n' "$current"
            inventory_conflicts=1
            inventory_blocked_details+=("$current"$'\t'symlink)
            return 1
        fi
        if [[ -e "$current" ]]; then
            if [[ ! -d "$current" ]]; then
                printf 'inventory conflict-container=%s reason=not-directory\n' "$current"
                inventory_conflicts=1
                inventory_blocked_details+=("$current"$'\t'not-directory)
                return 1
            fi
            owner=$(stat -Lc '%u' -- "$current" 2>/dev/null || true)
            mode=$(stat -Lc '%a' -- "$current" 2>/dev/null || true)
            if [[ "$owner" != "$EUID" || -z "$mode" ]]; then
                printf 'inventory conflict-container=%s reason=unsafe-owner-or-metadata\n' \
                    "$current"
                inventory_conflicts=1
                inventory_blocked_details+=("$current"$'\t'unsafe-owner-or-metadata)
                return 1
            fi
            mode_value=$((8#$mode))
            if ((mode_value & 18)); then
                printf 'inventory conflict-container=%s reason=group-or-world-writable\n' \
                    "$current"
                inventory_conflicts=1
                inventory_blocked_details+=("$current"$'\t'group-or-world-writable)
                return 1
            fi
        else
            printf 'inventory planned-container=%s policy=create-securely-and-revalidate\n' \
                "$target"
            return 0
        fi
    done
    printf 'inventory existing-container=%s policy=revalidate-before-write\n' "$target"
}

set_managed_paths() {
    # The clone is the install: config, state, credentials, secrets and roster
    # all hang off it.
    install_root=$(paynani_root)
    config_dir=$(paynani_config_dir)
    state_dir=$(paynani_state_dir)
    unit_dir="$HOME/.config/systemd/user"
    hermes_dir="$config_dir/hermes"
    manifest="$config_dir/install.manifest"
    credentials=$(resolve_credentials_path)
    managed_paths=(
        "$unit_dir/paynani-idle.service"
        "$unit_dir/paynani-dispatch.service"
        "$unit_dir/paynani-logrotate.service"
        "$unit_dir/paynani-logrotate.timer"
        "$config_dir/runtime.env"
        # Generated Hermes secrets remain installer-owned across an explicit
        # runtime migration so rollback can reuse them and uninstall can still
        # account for them. Fresh OpenClaw installs never record these paths.
        "$hermes_dir/notify.secret"
        "$hermes_dir/roster.secret"
    )
}

manifest_arguments() {
    local manifest_runtime_value=${1:-$runtime} path
    printf '%s\0' --manifest "$manifest" --runtime "$manifest_runtime_value"
    for path in "${managed_paths[@]}"; do
        printf '%s\0' --allowed "$path"
    done
}

load_ownership_manifest() {
    local output kind path digest previous_runtime
    declare -gA owned_digests=()
    manifest_runtime=$runtime
    [[ -e "$manifest" || -L "$manifest" ]] || return 0
    local -a arguments=()
    mapfile -d '' -t arguments < <(manifest_arguments)
    if ! output=$(python3 "$ROOT/scripts/install_manifest.py" read "${arguments[@]}" 2>&1); then
        if [[ "$mode" != upgrade ]]; then
            printf '%s\n' "$output" >&2
            exit "$EX_CONFIG"
        fi
        if [[ "$runtime" == openclaw ]]; then
            previous_runtime=hermes
        else
            previous_runtime=openclaw
        fi
        mapfile -d '' -t arguments < <(manifest_arguments "$previous_runtime")
        if ! output=$(python3 "$ROOT/scripts/install_manifest.py" read "${arguments[@]}" 2>&1); then
            printf '%s\n' "$output" >&2
            exit "$EX_CONFIG"
        fi
        manifest_runtime=$previous_runtime
    fi
    while IFS=$'\t' read -r kind path digest; do
        [[ -n "$kind" ]] || continue
        owned_digests["$path"]=$digest
    done <<<"$output"
}

migrate_ownership_manifest() {
    local output path
    [[ "$manifest_runtime" != "$runtime" ]] || return 0
    local -a arguments=(
        --manifest "$manifest"
        --from-runtime "$manifest_runtime"
        --runtime "$runtime"
    )
    for path in "${managed_paths[@]}"; do
        arguments+=(--allowed "$path")
    done
    if ! output=$(python3 "$ROOT/scripts/install_manifest.py" migrate-runtime \
        "${arguments[@]}" 2>&1); then
        printf '%s\n' "$output" >&2
        exit "$EX_CONFIG"
    fi
    printf 'runtime_migration=%s-to-%s state=ownership-transferred\n' \
        "$manifest_runtime" "$runtime"
    manifest_runtime=$runtime
    changes_made=1
}

render_artifact() {
    local destination=$1 source=$2
    if [[ "$source" == generated-runtime-config ]]; then
        if [[ "$runtime" == openclaw ]]; then
            printf 'PAYNANI_RUNTIME=openclaw\n'
            return
        fi
        if [[ "$runtime" == claudecode ]]; then
            printf 'PAYNANI_RUNTIME=claudecode\n'
            return
        fi
        python3 - "$notify_secret_file" "$roster_secret_file" <<'PYINNER'
import os
import sys

values = {
    "PAYNANI_RUNTIME": "hermes",
    "HERMES_NOTIFY_URL": os.environ["HERMES_NOTIFY_URL"],
    "HERMES_NOTIFY_SECRET_FILE": sys.argv[1],
    "HERMES_ROSTER_URL": os.environ["HERMES_ROSTER_URL"],
    "HERMES_ROSTER_SECRET_FILE": sys.argv[2],
    "HERMES_HEALTH_URL": os.environ["HERMES_HEALTH_URL"],
    "HERMES_SIGNATURE_MODE": "v2",
}
if os.environ.get("HERMES_ALLOW_REMOTE", "").lower() in ("1", "true", "yes"):
    values["HERMES_ALLOW_REMOTE"] = "1"
for name, value in values.items():
    if "\n" in value or "\r" in value or "\0" in value:
        raise SystemExit(f"invalid multiline or NUL value for {name}")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    print(f'{name}="{escaped}"')
PYINNER
        return
    fi
    python3 - "$source" "$ROOT" "$credentials" "$config_dir" "$state_dir" <<'PYINNER'
import sys
from pathlib import Path

# Order matters only in that every placeholder is distinct; none is a prefix of
# another, so a single pass is enough. config and state are rendered separately
# from the root so an install that overrides either still gets the path it named.
text = Path(sys.argv[1]).read_text()
text = text.replace("/path/to/paynani", sys.argv[2])
text = text.replace("/path/to/env", sys.argv[3])
text = text.replace("/path/to/config", sys.argv[4])
text = text.replace("/path/to/state", sys.argv[5])
sys.stdout.write(text)
PYINNER
}

sha256_file() {
    sha256sum -- "$1" | cut -d ' ' -f1
}

sha256_desired() {
    render_artifact "$1" "$2" | sha256sum | cut -d ' ' -f1
}

classify_planned_artifact() {
    local kind=$1 destination=$2 source=$3 actual desired
    if [[ -e "$destination" || -L "$destination" ]]; then
        if [[ -n "${owned_digests[$destination]+present}" ]]; then
            if [[ -L "$destination" || ! -f "$destination" ]]; then
                printf 'inventory conflict-owned-%s=%s reason=unsafe-artifact-type\n' \
                    "$kind" "$destination"
                inventory_conflicts=1
                return
            fi
            actual=$(sha256_file "$destination")
            if [[ "$actual" != "${owned_digests[$destination]}" ]]; then
                printf 'inventory conflict-owned-%s=%s reason=changed-outside-installer\n' \
                    "$kind" "$destination"
                inventory_conflicts=1
                return
            fi
            desired=$(sha256_desired "$destination" "$source")
            if [[ "$actual" == "$desired" ]]; then
                printf 'inventory existing-managed-%s=%s state=converged\n' \
                    "$kind" "$destination"
            else
                printf 'inventory planned-update-%s=%s source=%s\n' \
                    "$kind" "$destination" "$source"
                inventory_changes=1
            fi
        else
            # A process can stop after the atomic artifact link but before the
            # manifest record. Exact generated bytes are safe to adopt; any
            # differing, linked, non-regular, or foreign-owned path remains an
            # unproven conflict. write-artifact revalidates this at mutation.
            if [[ "$source" != generated-once-interactively &&
                  ! -L "$destination" && -f "$destination" && -O "$destination" ]]; then
                actual=$(sha256_file "$destination")
                desired=$(sha256_desired "$destination" "$source")
            else
                actual=""
                desired=""
            fi
            if [[ -n "$actual" && "$actual" == "$desired" ]]; then
                printf 'inventory planned-adopt-%s=%s reason=generated-content-match\n' \
                    "$kind" "$destination"
                inventory_changes=1
            else
                printf 'inventory conflict-preserve-%s=%s reason=unproven-ownership\n' \
                    "$kind" "$destination"
                inventory_conflicts=1
                inventory_unproven_conflicts=1
            fi
        fi
    else
        printf 'inventory planned-managed-%s=%s source=%s\n' \
            "$kind" "$destination" "$source"
        inventory_changes=1
    fi
}

classify_planned_secret() {
    local destination=$1 actual expected
    if [[ ! -e "$destination" && ! -L "$destination" ]]; then
        printf 'inventory planned-managed-secret=%s source=generated-once-interactively\n' \
            "$destination"
        inventory_changes=1
        return
    fi
    expected=${owned_digests[$destination]:-}
    if [[ -z "$expected" ]]; then
        printf 'inventory conflict-preserve-secret=%s reason=unproven-ownership\n' \
            "$destination"
        inventory_conflicts=1
        inventory_unproven_conflicts=1
        return
    fi
    if [[ -L "$destination" || ! -f "$destination" || ! -O "$destination" ||
          "$(stat -Lc '%a' -- "$destination" 2>/dev/null || true)" != 600 ]]; then
        printf 'inventory conflict-owned-secret=%s reason=unsafe-artifact-metadata\n' \
            "$destination"
        inventory_conflicts=1
        return
    fi
    actual=$(sha256_file "$destination")
    if [[ "$actual" != "$expected" ]]; then
        printf 'inventory conflict-owned-secret=%s reason=changed-outside-installer\n' \
            "$destination"
        inventory_conflicts=1
        return
    fi
    printf 'inventory existing-managed-secret=%s state=converged\n' "$destination"
}

print_managed_inventory() {
    local unit
    local unit_container_safe=1 config_container_safe=1 hermes_container_safe=1
    # These paths deliberately follow the resolver rather than XDG overrides.
    # Everything the install owns hangs off the clone, and the units are
    # rendered with the same answers; honoring XDG_CONFIG_HOME here would place
    # secrets where the unit never reads them and surface later as a 401.
    set_managed_paths
    inventory_conflicts=0
    inventory_unproven_conflicts=0
    inventory_blocked=0
    inventory_changes=0
    inventory_blocked_details=()

    printf 'inventory root=%s mode=%s runtime=%s\n' "$ROOT" "$mode" "$runtime"
    validate_container_chain "$unit_dir" || unit_container_safe=0
    validate_container_chain "$config_dir" || config_container_safe=0
    if ((config_container_safe)); then
        load_ownership_manifest
        if [[ "$manifest_runtime" != "$runtime" ]]; then
            printf 'inventory planned-runtime-migration=%s-to-%s mode=upgrade\n' \
                "$manifest_runtime" "$runtime"
            inventory_changes=1
        fi
    fi

    for unit in paynani-idle.service paynani-dispatch.service \
        paynani-logrotate.service paynani-logrotate.timer; do
        if ((unit_container_safe)); then
            classify_planned_artifact file "$unit_dir/$unit" "$ROOT/systemd/$unit"
        else
            inventory_blocked=1
            printf 'inventory blocked-managed-file=%s/%s reason=unsafe-container\n' \
                "$unit_dir" "$unit"
        fi
    done
    if ((config_container_safe)); then
        classify_planned_artifact file "$config_dir/runtime.env" generated-runtime-config
        if [[ -e "$manifest" && ! -L "$manifest" ]]; then
            printf 'inventory ownership-manifest=%s state=secure
' "$manifest"
        else
            printf 'inventory planned-ownership-manifest=%s
' "$manifest"
            inventory_changes=1
        fi
    else
        inventory_blocked=1
        printf 'inventory blocked-managed-file=%s/runtime.env reason=unsafe-container\n' \
            "$config_dir"
        printf 'inventory blocked-managed-file=%s/install.manifest reason=unsafe-container\n' \
            "$config_dir"
    fi
    printf 'inventory container-directory=%s policy=never-own-directory\n' "$unit_dir"
    printf 'inventory container-directory=%s policy=never-own-directory\n' "$config_dir"

    printf 'inventory preserve-file=%s role=mailbox-credentials\n' "$credentials"
    printf 'inventory preserve-file=%s/roster.md role=recipient-roster\n' "$ROOT"
    printf 'inventory preserve-tree=%s role=uid-journal-cursor-and-logs\n' "$state_dir"
    printf 'inventory preserve-repository=%s\n' "$ROOT"

    if [[ "$runtime" == hermes ]]; then
        if [[ -n "$notify_secret_file" ]]; then
            printf 'inventory external-secret=%s role=notify validate-only=true\n' \
                "$notify_secret_file"
            printf 'inventory external-secret=%s role=roster validate-only=true\n' \
                "$roster_secret_file"
        else
            if ((config_container_safe)); then
                validate_container_chain "$hermes_dir" || hermes_container_safe=0
            else
                hermes_container_safe=0
            fi
            printf 'inventory container-directory=%s policy=never-own-directory\n' \
                "$hermes_dir"
            if ((hermes_container_safe)); then
                classify_planned_secret "$hermes_dir/notify.secret"
                classify_planned_secret "$hermes_dir/roster.secret"
            else
                inventory_blocked=1
                printf 'inventory blocked-managed-secret=%s/notify.secret reason=unsafe-container\n' \
                    "$hermes_dir"
                printf 'inventory blocked-managed-secret=%s/roster.secret reason=unsafe-container\n' \
                    "$hermes_dir"
            fi
        fi
    fi
    check_git_hygiene
    if ((inventory_blocked)); then
        printf 'inventory result=blocked configuration-refusal=true\n'
    fi
}

# Every runtime-owned path is ignored by git, and none of them is tracked.
#
# The install lives inside the working tree now, so an ignore rule is all that
# stands between a mail password and `git add -A`. This runs in the inventory
# phase, before anything is written: refusing to write a secret beats writing it
# and printing a warning nobody reads.
#
# A deployment with no .git — a tarball, an export — cannot be checked and is
# not refused for it. It is reported, so the difference between "checked and
# clean" and "could not check" stays visible.
check_git_hygiene() {
    local relative tracked=() exposed=()
    git_hygiene=violated

    if ! git -C "$install_root" rev-parse --git-dir >/dev/null 2>&1; then
        git_hygiene=unverifiable
        printf 'inventory git-hygiene=unverifiable reason=not-a-git-checkout root=%s\n' \
            "$install_root"
        return 0
    fi

    # `state/` and `hermes/` keep their trailing slash: .gitignore matches them
    # as directories, and `git check-ignore state` answers "not ignored" for a
    # directory that does not exist yet — which is exactly when this runs.
    for relative in .env runtime.env install.manifest roster.md \
        hermes/notify.secret hermes/roster.secret hermes/ state/; do
        if git -C "$install_root" ls-files --error-unmatch -- "$relative" >/dev/null 2>&1; then
            tracked+=("$relative")
        elif ! git -C "$install_root" check-ignore -q -- "$relative"; then
            exposed+=("$relative")
        fi
    done

    if ((${#tracked[@]})); then
        for relative in "${tracked[@]}"; do
            printf 'inventory conflict-git-tracked=%s reason=runtime-path-is-tracked\n' "$relative"
        done
        inventory_conflicts=1
        inventory_blocked=1
    fi
    if ((${#exposed[@]})); then
        for relative in "${exposed[@]}"; do
            printf 'inventory conflict-git-exposed=%s reason=not-ignored\n' "$relative"
        done
        inventory_conflicts=1
        inventory_blocked=1
    fi
    if ((${#tracked[@]} == 0 && ${#exposed[@]} == 0)); then
        git_hygiene=clean
        printf 'inventory git-hygiene=clean root=%s\n' "$install_root"
    fi
}

plan_has_changes() {
    if [[ "$mode" == uninstall ]]; then
        [[ -e "$manifest" || -L "$manifest" ]]
        return
    fi
    ((inventory_changes))
}

create_secure_containers() {
    umask 077
    # The state tree is created here rather than left to the services. systemd
    # does not create the parent of a StandardOutput=append: path — it fails the
    # unit — so an install that converged the units and enabled them would leave
    # both services dead on a host where nobody had run mkdir by hand.
    mkdir -p -- "$unit_dir" "$config_dir" "$state_dir"
    validate_container_chain "$unit_dir" >/dev/null || die_config "unsafe unit container after creation: $unit_dir"
    validate_container_chain "$config_dir" >/dev/null || die_config "unsafe config container after creation: $config_dir"
    validate_container_chain "$state_dir" >/dev/null || die_config "unsafe state container after creation: $state_dir"
    if [[ "$runtime" == hermes && -z "$notify_secret_file" ]]; then
        mkdir -p -- "$hermes_dir"
        validate_container_chain "$hermes_dir" >/dev/null || \
            die_config "unsafe Hermes secret container after creation: $hermes_dir"
    fi
}

converge_artifact() {
    local kind=$1 destination=$2 source=$3 file_mode=$4 expected="" actual desired digest output current_mode
    expected=${owned_digests[$destination]:-}
    desired=$(sha256_desired "$destination" "$source")
    if [[ -e "$destination" && -n "$expected" ]]; then
        actual=$(sha256_file "$destination")
        current_mode=$(stat -Lc '%a' -- "$destination" 2>/dev/null || true)
        if [[ "$actual" == "$desired" && "$actual" == "$expected" &&
              "$current_mode" == "${file_mode#0}" ]]; then
            return
        fi
    fi
    if ! output=$(render_artifact "$destination" "$source" | python3         "$ROOT/scripts/install_manifest.py" write-artifact --path "$destination"         --mode "$file_mode" --expected-digest "$expected" 2>&1); then
        printf '%s
' "$output" >&2
        exit "$EX_CONFIG"
    fi
    digest=${output##*$'
'}
    write_count=$((write_count + 1))
    if [[ "${PAYNANI_TEST_INTERRUPT_AFTER_WRITE:-}" == "$write_count" ]]; then
        printf 'install: test interruption after artifact creation before ownership record %d\n' \
            "$write_count" >&2
        exit 99
    fi
    local -a arguments=()
    mapfile -d '' -t arguments < <(manifest_arguments)
    if ! output=$(python3 "$ROOT/scripts/install_manifest.py" record "${arguments[@]}"         --kind "$kind" --path "$destination" --digest "$digest" 2>&1); then
        printf '%s
' "$output" >&2
        exit "$EX_CONFIG"
    fi
    owned_digests["$destination"]=$digest
    changes_made=1
    runtime_filesystem_changed=1
    mutation_count=$((mutation_count + 1))
    if [[ "${PAYNANI_TEST_INTERRUPT_AFTER:-}" == "$mutation_count" ]]; then
        printf 'install: test interruption after artifact %d
' "$mutation_count" >&2
        exit 99
    fi
}

deactivate_owned_services() {
    local unit unit_path changed=0
    if [[ -z "$discovered_systemctl" ]]; then
        printf 'install: warning: systemd user manager unavailable; service deactivation unconfirmed.\n' >&2
        return 0
    fi
    for unit in paynani-idle.service paynani-dispatch.service \
        paynani-logrotate.timer; do
        unit_path="$unit_dir/$unit"
        [[ -n "${owned_digests[$unit_path]+present}" ]] || continue
        if "$discovered_systemctl" --user is-enabled --quiet "$unit" 2>/dev/null ||
           "$discovered_systemctl" --user is-active --quiet "$unit" 2>/dev/null; then
            "$discovered_systemctl" --user disable --now "$unit" || \
                die_config "failed to disable owned user unit $unit; filesystem preserved"
            changed=1
        fi
        if "$discovered_systemctl" --user is-enabled --quiet "$unit" 2>/dev/null ||
           "$discovered_systemctl" --user is-active --quiet "$unit" 2>/dev/null; then
            die_config "owned user unit $unit remained enabled or active; filesystem preserved"
        fi
    done
    ((changed == 0)) || changes_made=1
}

uninstall_owned_filesystem() {
    local destination output
    local -a arguments=()
    set_managed_paths
    validate_container_chain "$config_dir" >/dev/null || \
        die_config "unsafe config container during uninstall: $config_dir"
    if [[ ! -e "$manifest" && ! -L "$manifest" ]]; then
        return
    fi
    load_ownership_manifest
    # Validate every durable ownership record before the first service or
    # filesystem mutation. A late modified artifact must not leave a half-
    # uninstalled runtime boundary.
    for destination in "${managed_paths[@]}"; do
        [[ -n "${owned_digests[$destination]+present}" ]] || continue
        validate_container_chain "${destination%/*}" >/dev/null || \
            die_config "unsafe artifact container during uninstall: ${destination%/*}"
        if [[ -d "${destination%/*}" ]]; then
            if ! output=$(python3 "$ROOT/scripts/install_manifest.py" verify-artifact \
                --path "$destination" --expected-digest "${owned_digests[$destination]}" 2>&1); then
                printf '%s\n' "$output" >&2
                exit "$EX_CONFIG"
            fi
        fi
    done
    deactivate_owned_services
    for destination in "${managed_paths[@]}"; do
        [[ -n "${owned_digests[$destination]+present}" ]] || continue
        validate_container_chain "${destination%/*}" >/dev/null || \
            die_config "unsafe artifact container during uninstall: ${destination%/*}"
        if [[ -d "${destination%/*}" ]]; then
            if ! output=$(python3 "$ROOT/scripts/install_manifest.py" remove-artifact \
                --path "$destination" --expected-digest "${owned_digests[$destination]}" 2>&1); then
                printf '%s\n' "$output" >&2
                exit "$EX_CONFIG"
            fi
        fi
        mapfile -d '' -t arguments < <(manifest_arguments)
        if ! output=$(python3 "$ROOT/scripts/install_manifest.py" forget "${arguments[@]}" \
            --path "$destination" 2>&1); then
            printf '%s\n' "$output" >&2
            exit "$EX_CONFIG"
        fi
        unset 'owned_digests[$destination]'
        changes_made=1
    done
    mapfile -d '' -t arguments < <(manifest_arguments)
    if ! output=$(python3 "$ROOT/scripts/install_manifest.py" finalize "${arguments[@]}" 2>&1); then
        printf '%s\n' "$output" >&2
        exit "$EX_CONFIG"
    fi
    changes_made=1
    if [[ -n "$discovered_systemctl" ]]; then
        "$discovered_systemctl" --user daemon-reload || \
            die_config 'filesystem removed, but systemctl --user daemon-reload failed; rerun daemon-reload manually'
    fi
}

initialize_ownership_manifest() {
    local output
    create_secure_containers
    local -a arguments=()
    mapfile -d '' -t arguments < <(manifest_arguments)
    if ! output=$(python3 "$ROOT/scripts/install_manifest.py" init "${arguments[@]}" 2>&1); then
        printf '%s
' "$output" >&2
        exit "$EX_CONFIG"
    fi
    load_ownership_manifest
}

converge_runtime_filesystem() {
    local unit
    for unit in paynani-idle.service paynani-dispatch.service         paynani-logrotate.service paynani-logrotate.timer; do
        converge_artifact file "$unit_dir/$unit" "$ROOT/systemd/$unit" 0644
    done
    converge_artifact file "$config_dir/runtime.env" generated-runtime-config 0600
}

converge_generated_secret() {
    local label=$1 destination=$2 expected actual secret_value output digest
    expected=${owned_digests[$destination]:-}
    if [[ -e "$destination" && -n "$expected" ]]; then
        actual=$(sha256_file "$destination")
        if [[ "$actual" == "$expected" ]]; then
            return
        fi
        die_config "owned Hermes $label secret changed outside the installer: $destination"
    fi
    [[ ! -e "$destination" && ! -L "$destination" ]] || \
        die_config "unowned Hermes $label secret is preserved; move it aside before retrying: $destination"
    secret_value=$("$discovered_python" -c 'import secrets; print(secrets.token_urlsafe(32))')
    if ! output=$(printf '%s\n' "$secret_value" | \
        "$discovered_python" "$ROOT/scripts/install_manifest.py" write-artifact \
        --path "$destination" --mode 0600 --expected-digest '' 2>&1); then
        printf '%s\n' "$output" >&2
        exit "$EX_CONFIG"
    fi
    digest=${output##*$'\n'}
    write_count=$((write_count + 1))
    local -a arguments=()
    mapfile -d '' -t arguments < <(manifest_arguments)
    if ! output=$("$discovered_python" "$ROOT/scripts/install_manifest.py" record \
        "${arguments[@]}" --kind secret --path "$destination" --digest "$digest" 2>&1); then
        printf '%s\n' "$output" >&2
        exit "$EX_CONFIG"
    fi
    owned_digests["$destination"]=$digest
    changes_made=1
    mutation_count=$((mutation_count + 1))
    generated_secrets=1
    printf 'hermes_%s_secret=%s\n' "$label" "$secret_value"
    secret_value=''
}

print_hermes_route_guidance() {
    local quoted
    if [[ -n "$profile" ]]; then
        printf -v quoted '%q' "$profile"
        printf 'hermes_route_guidance=existing-profile profile=%s edits_hermes_config=false\n' \
            "$quoted"
    elif [[ -n "$deliver" ]]; then
        local quoted_deliver quoted_chat
        printf -v quoted_deliver '%q' "$deliver"
        printf -v quoted_chat '%q' "$chat_id"
        printf 'hermes_route_guidance=guided-only delivery_target=%s chat_id=%s edits_hermes_config=false\n' \
            "$quoted_deliver" "$quoted_chat"
    else
        printf 'hermes_route_guidance=operator-selection-required edits_hermes_config=false\n'
    fi
}

prepare_hermes_secrets() {
    generated_secrets=0
    print_hermes_route_guidance
    if [[ -n "$notify_secret_file" ]]; then
        return
    fi
    converge_generated_secret notify "$hermes_dir/notify.secret"
    converge_generated_secret roster "$hermes_dir/roster.secret"
    notify_secret_file="$hermes_dir/notify.secret"
    roster_secret_file="$hermes_dir/roster.secret"
    if ((generated_secrets)); then
        printf '%s\n' \
            'install: configure the two Hermes routes with the newly shown secrets, then rerun the installer; services were not activated' >&2
        exit "$EX_CONFIG"
    fi
}

probe_hermes_webhook_support() {
    local output
    if ! output=$("$discovered_runtime_cli" webhook --help 2>&1); then
        printf '%s\n' "$output" >&2
        die_config 'Hermes webhook support is unavailable; install a V2-capable Hermes release'
    fi
    printf 'hermes_webhook_probe=accepted executable=%s\n' "$discovered_runtime_cli"
}

probe_hermes_routes() {
    HERMES_NOTIFY_SECRET_FILE="$notify_secret_file" \
    HERMES_ROSTER_SECRET_FILE="$roster_secret_file" \
    HERMES_SIGNATURE_MODE=v2 \
    "$discovered_python" "$ROOT/scripts/hermes_smoke.py"
}

verify_installed_units() {
    local systemd_analyze output
    systemd_analyze=$(resolve_command systemd-analyze || true)
    [[ -n "$systemd_analyze" ]] || \
        die_config 'systemd-analyze executable not found; installed units were not activated'
    if ! output=$("$systemd_analyze" verify \
        "$unit_dir/paynani-idle.service" \
        "$unit_dir/paynani-dispatch.service" \
        "$unit_dir/paynani-logrotate.service" \
        "$unit_dir/paynani-logrotate.timer" 2>&1); then
        printf '%s\n' "$output" >&2
        die_config 'systemd-analyze verify rejected the installed units; no service state was changed'
    fi
}

probe_openclaw_service_environment() {
    local systemd_run output
    systemd_run=$(resolve_command systemd-run || true)
    [[ -n "$systemd_run" ]] || \
        die_config 'systemd-run executable not found; cannot execute OpenClaw in the systemd user environment'
    if ! output=$("$systemd_run" --user --pipe --quiet --wait \
        "$discovered_runtime_cli" --version 2>&1); then
        printf '%s\n' "$output" >&2
        die_config 'OpenClaw is present but cannot run in the systemd user service environment'
    fi
    printf 'openclaw_service_probe=accepted executable=%s\n' "$discovered_runtime_cli"
}

probe_claudecode_spool() {
    # The whole prerequisite for this runtime: can the dispatcher write the file
    # a session will read? Proved by writing, because a stat that says "should
    # be writable" and a write that fails are the pair this project keeps
    # getting caught by.
    #
    # Deliberately NOT proved here: that anyone is reading it. A Monitor is armed
    # inside a session and is invisible from out here, so claiming a delivery
    # path end to end would be claiming something this code cannot see.
    local state spool probe
    state=$(python3 -c 'import sys; sys.path.insert(0, "'"$ROOT"'/harness"); import paths; print(paths.state_dir())') ||         die_config 'could not resolve the state directory for the Claude Code spool'
    spool="$state/session.spool"
    mkdir -p -- "$state" 2>/dev/null ||         die_config "state directory $state cannot be created"
    probe="$state/.spool-probe.$$"
    if ! : >"$probe" 2>/dev/null; then
        rm -f -- "$probe" 2>/dev/null || true
        die_config "state directory $state is not writable, so no event could ever be delivered"
    fi
    rm -f -- "$probe" 2>/dev/null || true
    if [[ -e "$spool" && ! -w "$spool" ]]; then
        die_config "$spool exists but is not writable"
    fi
    printf 'claudecode_spool_probe=accepted spool=%s\n' "$spool"
    printf 'claudecode_spool_probe=session-arming-unobservable scope=writability-only\n'
}

print_final_verification_report() {
    local unit label secret_path secret_mode
    printf 'verification_report_begin\n'
    printf 'verification_runtime=%s\n' "$runtime"
    for unit in paynani-idle.service paynani-dispatch.service \
        paynani-logrotate.service paynani-logrotate.timer; do
        printf 'verification_unit=%s/%s validated=true\n' "$unit_dir" "$unit"
    done
    if [[ "$runtime" == hermes ]]; then
        for label in notify roster; do
            if [[ "$label" == notify ]]; then
                secret_path=$notify_secret_file
            else
                secret_path=$roster_secret_file
            fi
            [[ -f "$secret_path" && ! -L "$secret_path" && -O "$secret_path" ]] || \
                die_config "final verification rejected unsafe $label secret path: $secret_path"
            secret_mode=$(stat -Lc '%a' -- "$secret_path" 2>/dev/null || true)
            [[ "$secret_mode" == 600 ]] || \
                die_config "final verification requires mode 0600 for $label secret: $secret_path"
            printf 'verification_secret=%s path=%s mode=0600 validated=true\n' \
                "$label" "$secret_path"
        done
        printf 'verification_smoke=health result=accepted scope=reachability-only\n'
        printf 'verification_smoke=notify-email.received result=delivered\n'
        printf 'verification_smoke=notify-listener.error result=delivered\n'
        printf 'verification_smoke=roster-email.received result=accepted completion=unconfirmed\n'
    elif [[ "$runtime" == claudecode ]]; then
        printf 'verification_secret=not-applicable runtime=claudecode\n'
        printf 'verification_smoke=claudecode-spool result=writable\n'
        # Said plainly rather than implied. Nothing outside a session can see
        # whether a Monitor is armed, so a writable spool proves mail can be
        # delivered and proves nothing about whether anyone is reading it.
        printf 'verification_note=claudecode-delivery scope=spool-writable-only session-arming=unobservable\n'
    else
        printf 'verification_secret=not-applicable runtime=openclaw\n'
        printf 'verification_smoke=openclaw-service-environment result=accepted\n'
    fi
    # The hygiene state reaches the final report, not only the inventory stream.
    # It used to be printed once, mid-inventory, while the report still ended
    # `result=passed` — so "could not check" and "checked and clean" were
    # distinguishable to a human reading every line and to nothing else: not the
    # caller, not the exit status, not the report. A control nobody verified is
    # not a control that passed.
    printf 'verification_git_hygiene=%s root=%s\n' "$git_hygiene" "$install_root"
    case "$git_hygiene" in
        clean)
            printf 'verification_report_end result=passed\n'
            ;;
        unverifiable)
            printf 'verification_report_end result=passed-with-unverified-control control=git-hygiene\n'
            ;;
        *)
            die_config 'final verification reached an install whose git hygiene was never established'
            ;;
    esac
}

converge_required_services() {
    local unit
    "$discovered_systemctl" --user daemon-reload || \
        die_config 'systemctl --user daemon-reload failed; no service was enabled'
    for unit in paynani-idle.service paynani-dispatch.service \
        paynani-logrotate.timer; do
        if "$discovered_systemctl" --user is-enabled --quiet "$unit" && \
           "$discovered_systemctl" --user is-active --quiet "$unit"; then
            if ((runtime_filesystem_changed)); then
                "$discovered_systemctl" --user restart "$unit" || \
                    die_config "failed to restart changed required user unit: $unit"
                if ! "$discovered_systemctl" --user is-active --quiet "$unit"; then
                    die_config "restarted required user unit did not remain active: $unit"
                fi
                printf 'service=%s state=enabled-active restarted=true\n' "$unit"
                continue
            fi
            printf 'service=%s state=enabled-active\n' "$unit"
            continue
        fi
        "$discovered_systemctl" --user enable --now "$unit" || \
            die_config "failed to enable and start required user unit: $unit"
        if ! "$discovered_systemctl" --user is-enabled --quiet "$unit" || \
           ! "$discovered_systemctl" --user is-active --quiet "$unit"; then
            die_config "required user unit did not become enabled and active: $unit"
        fi
        printf 'service=%s state=enabled-active changed=true\n' "$unit"
        changes_made=1
    done
}

runtime=""
deliver=""
chat_id=""
profile=""
notify_secret_file=""
roster_secret_file=""
mode="install"
# Tri-state, defaulting to the pessimistic end: `violated` until something
# actually checks. An unset-or-empty variable read as "fine" is the failure this
# whole tri-state exists to remove.
git_hygiene=violated
upgrade=0
uninstall=0
non_interactive=0
dry_run=0
declare -A seen_options=()

mark_option_once() {
    local option=$1
    [[ -z "${seen_options[$option]+present}" ]] || die_usage "duplicate option: $option"
    seen_options[$option]=1
}

while (($#)); do
    case "$1" in
        --runtime|--deliver|--chat-id|--profile|--notify-secret-file|--roster-secret-file)
            mark_option_once "$1"
            (($# >= 2)) || die_usage "$1 requires a value"
            value=$2
            [[ -n "$value" && "$value" != --* ]] || die_usage "$1 requires a value"
            case "$1" in
                --runtime) runtime=$value ;;
                --deliver) deliver=$value ;;
                --chat-id) chat_id=$value ;;
                --profile) profile=$value ;;
                --notify-secret-file) notify_secret_file=$value ;;
                --roster-secret-file) roster_secret_file=$value ;;
            esac
            shift 2
            ;;
        --upgrade)
            mark_option_once "$1"
            upgrade=1
            shift
            ;;
        --uninstall)
            mark_option_once "$1"
            uninstall=1
            shift
            ;;
        --non-interactive)
            mark_option_once "$1"
            non_interactive=1
            shift
            ;;
        --dry-run)
            mark_option_once "$1"
            dry_run=1
            shift
            ;;
        -h|--help)
            usage
            exit "$EX_OK"
            ;;
        *)
            die_usage "unknown argument: $1"
            ;;
    esac
done

[[ -n "$runtime" ]] || die_usage '--runtime is required'
case "$runtime" in
    openclaw|hermes|claudecode) ;;
    *) die_usage "unsupported runtime: $runtime" ;;
esac

if ((upgrade + uninstall > 1)); then
    die_usage '--upgrade and --uninstall are mutually exclusive'
elif ((upgrade)); then
    mode="upgrade"
elif ((uninstall)); then
    mode="uninstall"
fi

# Before every check below, so a recalled value is validated exactly as a
# supplied one is. Recalling past validation would make the file a way to skip it.
if [[ "$runtime" == hermes ]]; then
    apply_recorded_runtime_env
fi

if [[ "$runtime" != hermes ]]; then
    if [[ -n "$deliver" || -n "$chat_id" || -n "$profile" ||
          -n "$notify_secret_file" || -n "$roster_secret_file" ]] ||
       ((non_interactive)); then
        die_usage 'delivery, profile, non-interactive, and route-secret options are Hermes-only'
    fi
fi
if [[ -n "$deliver" && -z "$chat_id" ]]; then
    die_usage '--deliver requires --chat-id'
fi
if [[ -n "$chat_id" && -z "$deliver" ]]; then
    die_usage '--chat-id requires --deliver'
fi
if [[ -n "$profile" && ( -n "$deliver" || -n "$chat_id" ) ]]; then
    die_usage '--profile is mutually exclusive with --deliver and --chat-id'
fi
for value in "$deliver" "$chat_id" "$profile"; do
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || \
        die_usage 'Hermes delivery and profile labels must be single-line values'
done
if [[ -n "$notify_secret_file" && -z "$roster_secret_file" ]] ||
   [[ -n "$roster_secret_file" && -z "$notify_secret_file" ]]; then
    die_usage '--notify-secret-file and --roster-secret-file must be supplied together'
fi
if [[ -n "$notify_secret_file" && "$notify_secret_file" == "$roster_secret_file" ]]; then
    die_usage 'notify and roster secret files must be different'
fi
if [[ "$runtime" == hermes && "$mode" != uninstall ]] && ((non_interactive)) &&
   [[ -z "$notify_secret_file" || -z "$roster_secret_file" ]]; then
    die_usage '--non-interactive requires --notify-secret-file and --roster-secret-file for Hermes'
fi

if ! discover_prerequisites; then
    exit "$EX_CONFIG"
fi

changes_made=0

set_managed_paths

if ((dry_run)); then
    print_managed_inventory
    if ((inventory_conflicts || inventory_blocked)); then
        if ((inventory_unproven_conflicts)); then
            printf 'install: unproven pre-existing artifacts are preserved; ownership manifest support is required before mutation\n' >&2
        fi
        if ((inventory_blocked)); then
            for blocked_detail in "${inventory_blocked_details[@]}"; do
                IFS=$'\t' read -r blocked_container blocked_reason <<<"$blocked_detail"
                case "$blocked_reason" in
                    group-or-world-writable)
                        printf 'install: unsafe managed container %s reason=%s; run: chmod go-w -- %q\n' \
                            "$blocked_container" "$blocked_reason" "$blocked_container" >&2
                        ;;
                    symlink)
                        printf 'install: unsafe managed container %s reason=%s; replace the symlink with a user-owned directory before retrying\n' \
                            "$blocked_container" "$blocked_reason" >&2
                        ;;
                    not-directory)
                        printf 'install: unsafe managed container %s reason=%s; replace it with a user-owned directory before retrying\n' \
                            "$blocked_container" "$blocked_reason" >&2
                        ;;
                    unsafe-owner-or-metadata)
                        printf 'install: unsafe managed container %s reason=%s; verify user ownership and readable metadata before retrying\n' \
                            "$blocked_container" "$blocked_reason" >&2
                        ;;
                    *)
                        printf 'install: unsafe managed container %s reason=%s; correct the container path before retrying\n' \
                            "$blocked_container" "$blocked_reason" >&2
                        ;;
                esac
            done
        fi
        exit "$EX_CONFIG"
    fi
    if plan_has_changes; then
        printf 'dry-run: plan contains create, modify, or remove actions; no changes made.\n'
        exit "$EX_CHANGED"
    fi
    printf 'dry-run: system is converged; no changes needed.\n'
    exit "$EX_OK"
fi

if [[ "$mode" == uninstall ]]; then
    changes_made=0
    uninstall_owned_filesystem
    if ((changes_made)); then
        printf 'install: owned services deactivated when reachable and recorded artifacts removed; credentials and state preserved.\n'
        exit "$EX_CHANGED"
    fi
    printf 'install: no ownership manifest; no filesystem artifacts removed.\n'
    exit "$EX_OK"
fi

print_managed_inventory
if ((inventory_conflicts || inventory_blocked)); then
    die_config 'filesystem convergence refused because managed inventory is unsafe or unowned'
fi
mutation_count=0
write_count=0
runtime_filesystem_changed=0
if [[ "$runtime" == hermes ]]; then
    probe_hermes_webhook_support
fi
migrate_ownership_manifest
initialize_ownership_manifest
if [[ "$runtime" == hermes ]]; then
    prepare_hermes_secrets
fi
converge_runtime_filesystem
verify_installed_units
if [[ "$runtime" == openclaw ]]; then
    probe_openclaw_service_environment
elif [[ "$runtime" == claudecode ]]; then
    probe_claudecode_spool
else
    probe_hermes_routes
fi
converge_required_services
print_final_verification_report
if ((changes_made)); then
    printf 'install: %s artifacts and required user services converged.\n' "$runtime"
    exit "$EX_CHANGED"
fi
printf 'install: %s artifacts and required user services already converged.\n' "$runtime"
exit "$EX_OK"
