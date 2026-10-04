#!/usr/bin/env bash
# bootstrap.sh -- install paynani with one sudo command (Ubuntu and Debian).
#
# This file is the root half only (BOOT-1): checks, system packages, himalaya,
# linger and the clone. Everything that belongs to the owner -- credentials,
# roster.md, the himalaya account, install.sh, the harness permissions and the
# final verification -- is done by scripts/bootstrap_user.py, run as the owner.
# The PRD is https://github.com/iaaorgmx/paynani/issues/335#issuecomment-5977928967
#
# Usage:
#   sudo bash bootstrap.sh [--runtime R] [--user U] [--dir PATH] [--ref REF]
#                          [--env-file PATH] [--owner-name N --owner-email E]
#                          [--yes] [--with-sms] [--upgrade] [--dry-run] [--test-mail]
#
# Options:
#   --runtime R         openclaw, hermes, claudecode, codex or opencode. Without it
#                       the user half detects the runtime and asks to confirm.
#   --user U            Who paynani is installed for. Default $SUDO_USER. Required
#                       when this runs as root without sudo.
#   --dir PATH          Where to clone. Default <harness root>/workspace/paynani.
#   --ref REF           Tag or branch to install. Default the newest v* tag.
#   --env-file PATH     Credentials already written (paynani .env format), for the
#                       no-questions mode. Copied to a private temporary file.
#   --owner-name N      The owner's row in roster.md.
#   --owner-email E     ditto.
#   --yes               Ask nothing. Exits 2 when a value is missing.
#   --with-sms          Also install the SMS gateway (install.sh --with-sms).
#   --upgrade           Upgrade an existing installation.
#   --dry-run           Print every action prefixed with "would:" and change nothing.
#   --test-mail         At the end, send a test message to the owner.
#   -h, --help          This text.
#
# Exit codes:
#   0 done   1 a step failed   2 missing data with --yes, or an invalid option
#   3 unsupported system or version   4 not run as root
#
# Root is used for apt-get and loginctl only. The clone, himalaya and everything
# after run as the user (sudo -u USER -H).
#
# Test hooks, used by scripts/test_bootstrap.sh and for field trials:
#   BOOTSTRAP_OS_RELEASE  path of the os-release file (default /etc/os-release)
#   BOOTSTRAP_REPO_URL    clone source (default https://github.com/iaaorgmx/paynani.git)

set -euo pipefail

readonly EX_OK=0
readonly EX_STEP=1
readonly EX_USAGE=2
readonly EX_UNSUPPORTED=3
readonly EX_NOT_ROOT=4

REPO_URL=${BOOTSTRAP_REPO_URL:-https://github.com/iaaorgmx/paynani.git}
OS_RELEASE=${BOOTSTRAP_OS_RELEASE:-/etc/os-release}
HIMALAYA_INSTALLER=https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh

# The runtime names, in the order of HARNESS_ROOTS in harness/paths.py.
RUNTIMES=(openclaw hermes claudecode codex opencode)
declare -A RUNTIME_ROOT=(
    [openclaw]=.openclaw [hermes]=.hermes [claudecode]=.claude
    [codex]=.codex [opencode]=.opencode
)

runtime="" user="" dir="" ref="" env_file="" owner_name="" owner_email=""
assume_yes=0 with_sms=0 upgrade=0 dry_run=0 test_mail=0
env_copy=""

say() { printf 'bootstrap: %s\n' "$*"; }
die() {   # die CODE MESSAGE...
    local code=$1
    shift
    printf 'bootstrap: %s\n' "$*" >&2
    exit "$code"
}

usage() {
    sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}"
}

# --- options ---------------------------------------------------------------

need_value() {   # need_value OPTION COUNT_LEFT
    [[ $2 -ge 2 ]] || die "$EX_USAGE" "$1 needs a value (see --help)"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --runtime)      need_value "$1" $#; runtime=$2; shift 2 ;;
        --user)         need_value "$1" $#; user=$2; shift 2 ;;
        --dir)          need_value "$1" $#; dir=$2; shift 2 ;;
        --ref)          need_value "$1" $#; ref=$2; shift 2 ;;
        --env-file)     need_value "$1" $#; env_file=$2; shift 2 ;;
        --owner-name)   need_value "$1" $#; owner_name=$2; shift 2 ;;
        --owner-email)  need_value "$1" $#; owner_email=$2; shift 2 ;;
        --yes)          assume_yes=1; shift ;;
        --with-sms)     with_sms=1; shift ;;
        --upgrade)      upgrade=1; shift ;;
        --dry-run)      dry_run=1; shift ;;
        --test-mail)    test_mail=1; shift ;;
        -h|--help)      usage; exit "$EX_OK" ;;
        *)              die "$EX_USAGE" "unknown option: $1 (see --help)" ;;
    esac
done

if [[ -n "$runtime" ]]; then
    valid=0
    for candidate in "${RUNTIMES[@]}"; do
        [[ "$candidate" != "$runtime" ]] || valid=1
    done
    [[ $valid -eq 1 ]] || die "$EX_USAGE" "--runtime must be one of: ${RUNTIMES[*]}"
fi
if [[ -n "$owner_name" || -n "$owner_email" ]]; then
    [[ -n "$owner_name" && -n "$owner_email" ]] \
        || die "$EX_USAGE" "--owner-name and --owner-email go together"
fi
if [[ -n "$env_file" && ! -f "$env_file" ]]; then
    die "$EX_USAGE" "--env-file $env_file is not a file"
fi

# --- helpers ---------------------------------------------------------------

# Run a command, or only say what would run.
run() {
    if [[ $dry_run -eq 1 ]]; then
        printf 'would: %s\n' "$*"
        return 0
    fi
    "$@"
}

as_user() { sudo -u "$user" -H "$@"; }

# Same as run, for what runs as the user.
run_user() {
    if [[ $dry_run -eq 1 ]]; then
        printf 'would: sudo -u %s -H %s\n' "$user" "$*"
        return 0
    fi
    as_user "$@"
}

cleanup() {
    if [[ -n "$env_copy" ]]; then
        rm -f -- "$env_copy"
    fi
}
trap cleanup EXIT

# --- 1. checks -------------------------------------------------------------

[[ "$(id -u)" -eq 0 ]] || die "$EX_NOT_ROOT" "run this as root: sudo bash bootstrap.sh"

if [[ -z "$user" ]]; then
    user=${SUDO_USER:-}
fi
if [[ -z "$user" || "$user" == root ]]; then
    die "$EX_NOT_ROOT" "run this with sudo from the owner's account, or pass --user USER: paynani is installed for a user, never for root"
fi
id "$user" >/dev/null 2>&1 || die "$EX_USAGE" "the user $user does not exist"

home=$(getent passwd "$user" | cut -d: -f6)
[[ -n "$home" && -d "$home" ]] || die "$EX_USAGE" "cannot find the home directory of $user"

if [[ ! -r "$OS_RELEASE" ]]; then
    die "$EX_UNSUPPORTED" "cannot read $OS_RELEASE: only Ubuntu and Debian are supported"
fi
os_id=$(. "$OS_RELEASE" && printf '%s' "${ID:-}")
os_like=$(. "$OS_RELEASE" && printf '%s' "${ID_LIKE:-}")
case " $os_id $os_like " in
    *" ubuntu "*|*" debian "*) ;;
    *) die "$EX_UNSUPPORTED" "unsupported system ($os_id): this installer supports Ubuntu and Debian. Follow INSTALL.md instead; macOS and Fedora are not covered yet" ;;
esac

# --- 2. packages -----------------------------------------------------------

missing=()
for package in git python3 curl ca-certificates; do
    dpkg -s "$package" >/dev/null 2>&1 || missing+=("$package")
done
if [[ ${#missing[@]} -gt 0 ]]; then
    say "installing system packages: ${missing[*]}"
    run apt-get update
    run apt-get install -y "${missing[@]}"
else
    say "system packages already present"
fi

# paynani needs Python 3.10 or newer (harness/python_floor.py).
if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
        || die "$EX_UNSUPPORTED" "python3 is older than 3.10: paynani needs 3.10 or newer. Install a newer Python and run this again"
elif [[ $dry_run -eq 0 ]]; then
    die "$EX_STEP" "python3 is not available after installing it"
fi

# --- 3. himalaya v2.x, as the user -----------------------------------------

himalaya_major() {
    local out
    out=$(as_user env "PATH=$home/.local/bin:$PATH" himalaya --version 2>/dev/null || true)
    if [[ "$out" =~ ([0-9]+)\.[0-9]+ ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    fi
}

if [[ "$(himalaya_major)" == 2 ]]; then
    say "himalaya v2.x already present"
else
    say "installing himalaya v2.x into $home/.local"
    run_user env "PREFIX=$home/.local" sh -c "curl -sSL $HIMALAYA_INSTALLER | sh"
    if [[ $dry_run -eq 0 && "$(himalaya_major)" != 2 ]]; then
        die "$EX_STEP" "himalaya v2.x is still missing after the installer ran (INSTALL.md section 4.2)"
    fi
fi

# --- 4. linger -------------------------------------------------------------

if [[ "$(loginctl show-user "$user" --property=Linger --value 2>/dev/null || true)" == yes ]]; then
    say "linger already enabled for $user"
else
    say "enabling linger for $user"
    run loginctl enable-linger "$user"
fi

# --- 5. the clone ----------------------------------------------------------

detect_roots() {   # prints the runtimes whose harness directory exists
    local name
    for name in "${RUNTIMES[@]}"; do
        [[ -d "$home/${RUNTIME_ROOT[$name]}" ]] && printf '%s\n' "$name"
    done
    return 0
}

if [[ -z "$dir" ]]; then
    if [[ -n "$runtime" ]]; then
        dir="$home/${RUNTIME_ROOT[$runtime]}/workspace/paynani"
    else
        mapfile -t found < <(detect_roots)
        case ${#found[@]} in
            0) die "$EX_USAGE" "no harness found under $home: pass --runtime or --dir" ;;
            1) dir="$home/${RUNTIME_ROOT[${found[0]}]}/workspace/paynani" ;;
            *)
                if [[ $assume_yes -eq 1 || ! -t 0 ]]; then
                    die "$EX_USAGE" "several harnesses found (${found[*]}) and nothing to choose with: pass --runtime or --dir"
                fi
                case "${LANG:-}" in
                    es*) printf 'Encontré varios harness: %s\n¿Para cuál instalo paynani? ' "${found[*]}" ;;
                    *)   printf 'Several harnesses found: %s\nWhich one is paynani for? ' "${found[*]}" ;;
                esac
                read -r choice
                valid=0
                for candidate in "${found[@]}"; do
                    [[ "$candidate" != "$choice" ]] || valid=1
                done
                [[ $valid -eq 1 ]] || die "$EX_USAGE" "'$choice' is not one of: ${found[*]}"
                runtime=$choice
                dir="$home/${RUNTIME_ROOT[$runtime]}/workspace/paynani"
                ;;
        esac
    fi
fi

if [[ -z "$ref" ]]; then
    ref=$(git ls-remote --tags --refs "$REPO_URL" 'v*' 2>/dev/null \
        | sed 's|.*refs/tags/||' | sort -V | tail -n1 || true)
    [[ -n "$ref" ]] || die "$EX_STEP" "cannot read the release tags from $REPO_URL: check the network or pass --ref"
fi

existing_clone=0
if [[ -d "$dir/.git" ]]; then
    origin=$(as_user git -C "$dir" remote get-url origin 2>/dev/null || true)
    if [[ "$origin" == *paynani* ]]; then
        existing_clone=1
    else
        die "$EX_USAGE" "$dir is a git clone of something else ($origin): pass another --dir"
    fi
elif [[ -e "$dir" && -n "$(ls -A "$dir" 2>/dev/null)" ]]; then
    die "$EX_USAGE" "$dir exists and is not empty: pass another --dir"
fi

if [[ $existing_clone -eq 1 ]]; then
    if [[ $upgrade -eq 1 ]]; then
        say "updating the tags of the existing clone at $dir"
        run_user git -C "$dir" fetch --tags --force origin
    else
        say "using the existing clone at $dir (not replaced)"
    fi
else
    say "cloning paynani $ref into $dir"
    run_user mkdir -p "$(dirname "$dir")"
    run_user git clone --branch "$ref" "$REPO_URL" "$dir"
fi

# --- 6. hand over to the user half -----------------------------------------

user_script="$dir/scripts/bootstrap_user.py"
if [[ $dry_run -eq 0 && ! -f "$user_script" ]]; then
    die "$EX_STEP" "bootstrap_user.py not found in this ref"
fi

args=(--runtime "$runtime" --ref "$ref")
if [[ -n "$env_file" ]]; then
    # The original may not be readable by the user: root copies it to a private
    # temporary file of the user's and removes the copy when this script ends.
    if [[ $dry_run -eq 1 ]]; then
        env_copy="<private copy of $env_file>"
        printf 'would: copy %s to a mode-600 temporary file owned by %s\n' "$env_file" "$user"
    else
        env_copy=$(as_user mktemp)
        install -m 600 -o "$user" -- "$env_file" "$env_copy"
    fi
    args+=(--env-file "$env_copy")
fi
if [[ -n "$owner_name" ]]; then
    args+=(--owner-name "$owner_name" --owner-email "$owner_email")
fi
[[ $assume_yes -eq 0 ]] || args+=(--yes)
[[ $with_sms -eq 0 ]] || args+=(--with-sms)
[[ $upgrade -eq 0 ]] || args+=(--upgrade)
[[ $dry_run -eq 0 ]] || args+=(--dry-run)
[[ $test_mail -eq 0 ]] || args+=(--test-mail)

say "handing over to $user: bootstrap_user.py"
if [[ $dry_run -eq 1 ]]; then
    # Nothing runs in a dry run, and the user half may not exist yet (the clone is
    # only announced above). Run scripts/bootstrap_user.py --dry-run for its part.
    printf 'would: sudo -u %s -H env LANG=%s python3 %s %s\n' \
        "$user" "${LANG:-}" "$user_script" "${args[*]}"
    exit "$EX_OK"
fi
as_user env "LANG=${LANG:-}" python3 "$user_script" "${args[@]}"
