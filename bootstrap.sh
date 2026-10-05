#!/usr/bin/env bash
# bootstrap.sh -- install paynani with one command.
#
# On Ubuntu and Debian this file is the root half only (BOOT-1): checks, system
# packages, himalaya, linger and the clone. Everything that belongs to the owner
# -- credentials, roster.md, the himalaya account, install.sh, the harness
# permissions and the final verification -- is done by scripts/bootstrap_user.py,
# run as the owner.
#
# On macOS this file hands off before the Linux-only bash 4 code below: Apple's
# /bin/bash is 3.2, Homebrew must never run as root, and LaunchAgents belong to
# the user. scripts/bootstrap_macos.py owns that path and delegates service
# convergence to scripts/install_macos.py through scripts/bootstrap_user.py.
# The PRD is https://github.com/iaaorgmx/paynani/issues/335#issuecomment-5977928967
#
# Usage:
#   sudo bash bootstrap.sh [--runtime R] [--user U] [--dir PATH] [--ref REF]
#                          [--env-file PATH] [--owner-name N --owner-email E]
#                          [--yes] [--with-sms] [--upgrade] [--dry-run] [--test-mail]
#   bash bootstrap.sh [--runtime R] [--dir PATH] [--ref REF]
#                     [--env-file PATH] [--owner-name N --owner-email E]
#                     [--yes] [--with-sms] [--upgrade] [--dry-run] [--test-mail]
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
# On Linux, root is used for apt-get and loginctl only. The clone, himalaya and
# everything after run as the user (sudo -u USER -H).
#
# On macOS, run this as the user. If it is invoked through sudo, the Darwin path
# re-executes as $SUDO_USER and refuses to continue as root.
#
# Test hooks, used by scripts/test_bootstrap.sh and for field trials:
#   BOOTSTRAP_OS_RELEASE  path of the os-release file (default /etc/os-release)
#   BOOTSTRAP_REPO_URL    clone source (default https://github.com/iaaorgmx/paynani.git)
#   BOOTSTRAP_RUN_USER_DIR  where the user's runtime dirs live (default /run/user)
#   BOOTSTRAP_BUS_WAIT    seconds to wait for the user's systemd bus (default 10)
#   BOOTSTRAP_GETFACL     the getfacl command (default getfacl); a path that does not exist
#                         simulates a system without the acl package

set -euo pipefail

BOOTSTRAP_UNAME=${BOOTSTRAP_UNAME:-$(uname -s 2>/dev/null || true)}
if [[ "$BOOTSTRAP_UNAME" == Darwin ]]; then
    if [[ -z "${BOOTSTRAP_SKIP_CLT_CHECK:-}" ]] && ! xcode-select -p >/dev/null 2>&1; then
        echo "bootstrap: macOS needs Homebrew first (it also installs the Command Line Tools, python3 and git): https://brew.sh/ , then run bootstrap.sh again" >&2
        exit 3
    fi

    bootstrap_ref=main
    bootstrap_next_is_ref=0
    for bootstrap_arg in "$@"; do
        if [[ $bootstrap_next_is_ref -eq 1 ]]; then
            bootstrap_ref=$bootstrap_arg
            bootstrap_next_is_ref=0
            continue
        fi
        case "$bootstrap_arg" in
            --ref) bootstrap_next_is_ref=1 ;;
            --ref=*) bootstrap_ref=${bootstrap_arg#--ref=} ;;
        esac
    done

    bootstrap_source=${BASH_SOURCE[0]:-}
    bootstrap_script=""
    if [[ -n "$bootstrap_source" ]]; then
        bootstrap_root=$(cd "$(dirname "$bootstrap_source")" && pwd -P)
        if [[ -f "$bootstrap_root/scripts/bootstrap_macos.py" ]]; then
            bootstrap_script=$bootstrap_root/scripts/bootstrap_macos.py
        fi
    fi
    if [[ -z "$bootstrap_script" ]]; then
        bootstrap_url=${BOOTSTRAP_MACOS_SCRIPT_URL:-https://raw.githubusercontent.com/iaaorgmx/paynani/$bootstrap_ref/scripts/bootstrap_macos.py}
        bootstrap_tmp=$(mktemp -d)
        bootstrap_script=$bootstrap_tmp/bootstrap_macos.py
        if ! curl -fsSL "$bootstrap_url" -o "$bootstrap_script"; then
            echo "bootstrap: cannot download scripts/bootstrap_macos.py from $bootstrap_url: check the network or pass --ref" >&2
            exit 1
        fi
    fi
    exec python3 "$bootstrap_script" "$@"
fi

readonly EX_OK=0
readonly EX_STEP=1
readonly EX_USAGE=2
readonly EX_UNSUPPORTED=3
readonly EX_NOT_ROOT=4

REPO_URL=${BOOTSTRAP_REPO_URL:-https://github.com/iaaorgmx/paynani.git}
OS_RELEASE=${BOOTSTRAP_OS_RELEASE:-/etc/os-release}
GETFACL=${BOOTSTRAP_GETFACL:-getfacl}
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

# Everything that runs as the user starts from an environment built here, not
# inherited: `sudo -u USER -H` changes HOME and leaves the caller's XDG_CONFIG_HOME
# (and whatever else an `env_keep` or a CI runner passes) pointing at someone
# else's home, so himalaya and git read or write the wrong user's files. The
# systemd user session needs XDG_RUNTIME_DIR and its bus, which exist once linger
# has started user@UID.service (wait_for_user_bus).
#
# Everything as the user also runs under umask 077, not under the account's own:
# on Ubuntu that is usually 002 (USERGROUPS_ENAB), which leaves what this script
# creates in the home (the directories above the clone, the clone, ~/.local/bin)
# group-writable, and install.sh then refuses ~/.claude as an unsafe container
# (found by the end-to-end job). A umask is not an environment variable, so
# `env -i` does not fix it.
user_env=()
as_user() { sudo -u "$user" -H "${user_env[@]}" sh -c 'umask 077; exec "$@"' sh "$@"; }

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

uid=$(id -u "$user")
RUN_USER_DIR=${BOOTSTRAP_RUN_USER_DIR:-/run/user}
BUS_WAIT=${BOOTSTRAP_BUS_WAIT:-10}
user_env=(env -i
    "HOME=$home" "USER=$user" "LOGNAME=$user" "SHELL=/bin/bash"
    "PATH=$home/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin"
    "LANG=${LANG:-C.UTF-8}"
    "XDG_RUNTIME_DIR=$RUN_USER_DIR/$uid"
    "DBUS_SESSION_BUS_ADDRESS=unix:path=$RUN_USER_DIR/$uid/bus")
# What a clean environment must not lose: the network path (proxies, CA bundles)
# and the terminal, which the owner's questions need.
for passed in http_proxy https_proxy no_proxy all_proxy HTTP_PROXY HTTPS_PROXY NO_PROXY ALL_PROXY \
              SSL_CERT_FILE SSL_CERT_DIR CURL_CA_BUNDLE GIT_SSL_CAINFO REQUESTS_CA_BUNDLE TERM; do
    if [[ -n "${!passed:-}" ]]; then
        user_env+=("$passed=${!passed}")
    fi
done

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
    out=$(as_user himalaya --version 2>/dev/null || true)
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

# linger starts user@UID.service; install.sh talks to that user's systemd, so wait
# for its bus before going on.
wait_for_user_bus() {
    local waited=0
    if [[ $dry_run -eq 1 ]]; then
        printf 'would: wait up to %ss for %s/%s/bus\n' "$BUS_WAIT" "$RUN_USER_DIR" "$uid"
        return 0
    fi
    while [[ ! -S "$RUN_USER_DIR/$uid/bus" ]]; do
        if [[ $waited -ge $BUS_WAIT ]]; then
            die "$EX_STEP" "the systemd user session of $user did not come up: $RUN_USER_DIR/$uid/bus is missing after ${BUS_WAIT}s (is systemd running, and logind enabled?)"
        fi
        sleep 1
        waited=$((waited + 1))
    done
}
wait_for_user_bus

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

# install.sh refuses an install whose path from $HOME down to the clone has a
# directory that group or others can write to (its own advice is "chmod go-w").
# Such a directory is not always ours to blame: /etc/skel and a tool that made
# ~/.claude under umask 002 both leave one behind, and the umask above only
# governs what this script creates. So the directories that already exist between
# the home and the clone lose group and world write, and each one is said out loud.
# Only those two bits, only on that path, never on $HOME itself. A directory on
# that path that does not belong to the user is not touched at all: install.sh
# would refuse it too (unsafe-owner), and a chmod by a user who does not own it
# cannot work, so the script stops and names it.
#
# A default ACL is the one thing neither the umask nor chmod can fix: mkdir ignores
# the umask under it and gives new directories the ACL's entries, and chmod go-w only
# lowers the mask. It is put there on purpose by an administrator (or, on GitHub's
# runner image, on /home), so it is not removed here: refuse, and say where it is.
# Only a default entry that lets someone other than the owner write counts; the usual
# "user::rwx, group::r-x, other::r-x" does not. Without getfacl nothing can be judged,
# so a "+" on a directory only earns a warning, and install.sh's own refusal stays as
# the safety net.
has_acl() {   # has_acl DIR: the "+" ls -ld appends to the mode; needs no `acl` package
    local listing
    listing=$(ls -ld -- "$1" 2>/dev/null) || return 1
    [[ "${listing%%[[:space:]]*}" == *+ ]]
}

writable_default_acl() {   # writable_default_acl DIR: prints each offending entry
    command -v "$GETFACL" >/dev/null 2>&1 || return 0
    "$GETFACL" -p -- "$1" 2>/dev/null | awk '
        /^default:/ {
            n = split($0, f, ":")
            rest = f[4]
            for (i = 5; i <= n; i++) rest = rest ":" f[i]
            perms = rest; sub(/[ \t].*/, "", perms)
            effective = perms
            if (match(rest, /#effective:[rwx-]+/)) effective = substr(rest, RSTART + 11, RLENGTH - 11)
            if ((f[2] == "user" && f[3] == "") || f[2] == "mask") next
            if (effective ~ /w/) print $0
        }'
}

tighten_path() {
    local current=$dir offending
    local -a chain=()
    [[ "$dir" == "$home"/* ]] || return 0
    while [[ "$current" != "$home" && "$current" != / && -n "$current" ]]; do
        chain+=("$current")
        current=$(dirname "$current")
    done
    # The ACL of the home counts too (what is created below inherits from it), though
    # its mode and owner are install.sh's to judge.
    for current in "$home" "${chain[@]}"; do
        [[ -d "$current" && ! -L "$current" ]] || continue
        if ! command -v "$GETFACL" >/dev/null 2>&1; then
            if has_acl "$current"; then
                say "warning: $current has an ACL; install acl (getfacl) to check it, or expect install.sh to refuse it"
            fi
            continue
        fi
        offending=$(writable_default_acl "$current")
        if [[ -n "$offending" ]]; then
            die "$EX_STEP" "$current has a default ACL that lets others write to everything created under it, and install.sh refuses such a path. I do not change ACLs an administrator set. Remove it (setfacl -k $current) or choose another --dir, and run this again. The entries:
$offending"
        fi
    done
    local entry mode owner
    for entry in "${chain[@]}"; do
        [[ -d "$entry" && ! -L "$entry" ]] || continue
        owner=$(stat -c %U -- "$entry" 2>/dev/null || true)
        if [[ -n "$owner" && "$owner" != "$user" ]]; then
            die "$EX_STEP" "$entry belongs to $owner, not to $user, and install.sh refuses a path it does not own: fix it (chown $user: $entry, or choose another --dir) and run this again"
        fi
        mode=$(stat -c %a -- "$entry" 2>/dev/null || true)
        [[ -n "$mode" ]] || continue
        if (( 8#$mode & 8#022 )); then
            say "removing group and world write from $entry (mode $mode): install.sh refuses it otherwise"
            run_user chmod go-w -- "$entry" || die "$EX_STEP" "cannot run chmod go-w on $entry: fix it by hand"
        fi
    done
}
tighten_path

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
    printf 'would: sudo -u %s -H env -i <clean environment, LANG=%s> python3 %s %s\n' \
        "$user" "${LANG:-C.UTF-8}" "$user_script" "${args[*]}"
    exit "$EX_OK"
fi
as_user python3 "$user_script" "${args[@]}"
