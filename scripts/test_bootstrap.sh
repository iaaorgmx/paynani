#!/usr/bin/env bash
# Exercises bootstrap.sh (the root half, BOOT-1) without root and without a network.
#
# apt-get, dpkg, loginctl, git, sudo, id, getent, curl, install and himalaya are
# replaced by fakes in a directory at the front of PATH. Each fake appends its
# arguments to one log, so a case can say what was called, in what order, and
# above all what was NOT called: the whole point of --dry-run (B4) is the absence
# of calls, and a test that only checks the exit code would pass for a script that
# ran everything and then exited 0.
#
#   scripts/test_bootstrap.sh

set -uo pipefail

# bootstrap.sh is the Ubuntu and Debian installer and uses bash 4 (associative
# arrays, mapfile); macOS ships bash 3.2 and has its own installer. Say so out
# loud, in the form the macOS job in .github/workflows/tests.yml counts as a skip,
# rather than failing there or passing silently.
if [ "$(uname -s)" != Linux ]; then
    printf 'skip bootstrap (bootstrap.sh is the Ubuntu/Debian installer; this host is %s)\n' "$(uname -s)"
    printf '\n0 passed, 0 failed, 1 suite skipped (not Linux)\n'
    exit 0
fi

BOOTSTRAP="$(cd "$(dirname "$0")/.." && pwd)/bootstrap.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

pass=0
fail=0
assert() {
    local desc=$1 cond=$2
    if eval "$cond"; then
        printf '  PASS  %-9s %s\n' "bootstrap" "$desc"; pass=$((pass+1))
    else
        printf '  FAIL  %-9s %s\n' "bootstrap" "$desc"; fail=$((fail+1))
    fi
}

fake="$tmp/bin"
home="$tmp/home/owner"
log="$tmp/calls.log"
mkdir -p "$fake" "$home"

# --- the fakes -------------------------------------------------------------

cat >"$fake/id" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-u" ]; then
    if [ $# -eq 1 ]; then echo "${FAKE_UID:-0}"; exit 0; fi
    [ "$2" = "${FAKE_USER:-owner}" ] && { echo 1000; exit 0; }
    exit 1
fi
[ "$1" = "${FAKE_USER:-owner}" ] && exit 0
exit 1
EOF
cat >"$fake/getent" <<'EOF'
#!/usr/bin/env bash
echo "$2:x:1000:1000::${FAKE_HOME}:/bin/bash"
EOF
cat >"$fake/dpkg" <<'EOF'
#!/usr/bin/env bash
case " ${FAKE_INSTALLED-git python3 curl ca-certificates} " in *" $2 "*) exit 0 ;; esac
exit 1
EOF
cat >"$fake/apt-get" <<'EOF'
#!/usr/bin/env bash
echo "apt-get $*" >>"$FAKE_LOG"
EOF
cat >"$fake/loginctl" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "show-user" ]; then echo "${FAKE_LINGER:-no}"; exit 0; fi
echo "loginctl $*" >>"$FAKE_LOG"
if [ "$1" = "enable-linger" ] && [ -z "${FAKE_NO_BUS-}" ]; then
    mkdir -p "$BOOTSTRAP_RUN_USER_DIR/1000"
    "$REAL_PYTHON3" -c 'import socket,sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' "$BOOTSTRAP_RUN_USER_DIR/1000/bus" 2>/dev/null || true   # already there: enable-linger is idempotent
fi
exit 0
EOF
# The "installer" the pipe feeds to sh leaves a mark; himalaya then reports v2.
cat >"$fake/curl" <<'EOF'
#!/usr/bin/env bash
echo "curl $*" >>"$FAKE_LOG"
echo ': > "$FAKE_MARK"'
EOF
cat >"$fake/install" <<'EOF'
#!/usr/bin/env bash
echo "install $*" >>"$FAKE_LOG"
src="" dst=""
for a in "$@"; do
    case "$a" in -m|-o|--|[0-9][0-9][0-9]|owner) ;; *) [ -z "$src" ] && src=$a || dst=$a ;; esac
done
cp "$src" "$dst" && chmod 600 "$dst"
EOF
cat >"$fake/himalaya" <<'EOF'
#!/usr/bin/env bash
if [ -n "${FAKE_HIMALAYA-}" ]; then echo "himalaya $FAKE_HIMALAYA"
elif [ -e "$FAKE_MARK" ]; then echo "himalaya v2.0.0"
else exit 127; fi
EOF
cat >"$fake/python3" <<'EOF'
#!/usr/bin/env bash
if [ "${1-}" = "-c" ] && [[ "${2-}" == *version_info* ]]; then
    [ -z "${FAKE_PY_OLD-}" ]; exit $?
fi
exec "$REAL_PYTHON3" "$@"
EOF
# sudo -u USER -H env -i VAR=value... CMD...: log it, then run CMD with exactly that environment
# (what a real sudo hands over), plus the FAKE_* plumbing and the fakes' directory on PATH.
cat >"$fake/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >>"$FAKE_LOG"
[ "$1" = "-u" ] && shift 2
[ "$1" = "-H" ] && shift
if [ "$1" = env ] && [ "$2" = -i ]; then
    shift 2
    pairs=()
    while [ $# -gt 0 ] && [[ "$1" == [A-Za-z_]*=* ]]; do
        case "$1" in PATH=*) pairs+=("PATH=$FAKE_BIN:${1#PATH=}") ;; *) pairs+=("$1") ;; esac
        shift
    done
    plumbing=()
    while IFS= read -r line; do plumbing+=("$line"); done < <(env | grep -E '^(FAKE_|REAL_PYTHON3=|BOOTSTRAP_)')
    exec env -i "${pairs[@]}" "${plumbing[@]}" "$@"
fi
exec "$@"
EOF
cat >"$fake/git" <<'EOF'
#!/usr/bin/env bash
echo "git $*" >>"$FAKE_LOG"
if [ "$1" = "-C" ]; then
    case "$3" in
        remote) echo "https://github.com/iaaorgmx/paynani.git" ;;
    esac
    exit 0
fi
case "$1" in
    ls-remote)
        printf 'aaa\trefs/tags/v0.9.1\nbbb\trefs/tags/v0.10.0\nccc\trefs/tags/v0.11.0\nddd\trefs/tags/v0.2.0\n' ;;
    clone)
        echo "env HOME=${HOME-UNSET} XDG_CONFIG_HOME=${XDG_CONFIG_HOME-UNSET} XDG_DATA_HOME=${XDG_DATA_HOME-UNSET} XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR-UNSET} DBUS=${DBUS_SESSION_BUS_ADDRESS-UNSET} LEAK=${CALLER_SECRET_TOKEN-UNSET} PROXY=${https_proxy-UNSET}" >>"$FAKE_LOG"
        target=${!#}
        mkdir -p "$target/scripts" "$target/.git"
        if [ -z "${FAKE_NO_USER_PY-}" ]; then
            cat >"$target/scripts/bootstrap_user.py" <<'PY'
import os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("bootstrap_user.py " + " ".join(sys.argv[1:]) + " LANG=" + os.environ.get("LANG", "") + "\n")
raise SystemExit(int(os.environ.get("FAKE_USER_RC", "0")))
PY
        fi ;;
esac
exit 0
EOF
# stat: the real one, except that %U (the owner's name) is "owner" for every path of the fake
# world, or "root" for the ones listed in FAKE_ROOT_OWNED. The files really belong to whoever runs
# the tests, so the owner has to be faked to say something about ownership at all.
cat >"$fake/stat" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ] && [ "$2" = "%U" ]; then
    target=${!#}
    case " ${FAKE_ROOT_OWNED-} " in *" $target "*) echo root ;; *) echo owner ;; esac
    exit 0
fi
exec "$REAL_STAT" "$@"
EOF
# getfacl: a standard default ACL (no extra write) for every path, or the GitHub runner's one,
# which gives user "runner" rwx on everything created below, for the paths in FAKE_ACL_BAD.
# FAKE_ACL_MASKED lists paths with that same entry but a mask that leaves it read-only.
cat >"$fake/getfacl" <<'EOF'
#!/usr/bin/env bash
target=${!#}
echo "# file: $target"
echo "user::rwx"; echo "group::r-x"; echo "other::r-x"
echo "default:user::rwx"
case " ${FAKE_ACL_BAD-} " in
    *" $target "*) echo "default:user:runner:rwx"; echo "default:group::r-x"; echo "default:mask::rwx" ;;
    *) case " ${FAKE_ACL_MASKED-} " in
        *" $target "*) printf 'default:user:runner:rwx\t\t#effective:r-x\n'; echo "default:group::r-x"; echo "default:mask::r-x" ;;
        *) echo "default:group::r-x"; echo "default:mask::r-x" ;;
    esac ;;
esac
echo "default:other::r-x"
EOF
chmod +x "$fake"/*

# The Ubuntu and Fedora files bootstrap.sh reads through BOOTSTRAP_OS_RELEASE.
printf 'ID=ubuntu\nID_LIKE=debian\n' >"$tmp/os-ubuntu"
printf 'ID=debian\n' >"$tmp/os-debian"
printf 'ID=linuxmint\nID_LIKE="ubuntu debian"\n' >"$tmp/os-mint"
printf 'ID=fedora\nID_LIKE="rhel centos"\n' >"$tmp/os-fedora"

export REAL_PYTHON3 REAL_STAT
REAL_PYTHON3=$(command -v python3)
REAL_STAT=$(command -v stat)
export PATH="$fake:$PATH"
export FAKE_LOG="$log" FAKE_HOME="$home" FAKE_USER=owner FAKE_MARK="$tmp/himalaya-installed"
export BOOTSTRAP_OS_RELEASE="$tmp/os-ubuntu"
export BOOTSTRAP_RUN_USER_DIR="$tmp/run" BOOTSTRAP_BUS_WAIT=1 FAKE_BIN="$fake"
export BOOTSTRAP_REPO_URL="https://example.invalid/paynani.git"
export SUDO_USER=owner
export LANG=en_US.UTF-8

reset() {   # a clean host for the next case
    : >"$log"
    rm -rf "$home" "$FAKE_MARK" "$tmp/run"
    mkdir -p "$home"
    unset FAKE_UID FAKE_INSTALLED FAKE_LINGER FAKE_HIMALAYA FAKE_PY_OLD FAKE_NO_USER_PY FAKE_USER_RC FAKE_NO_BUS FAKE_ROOT_OWNED FAKE_ACL_BAD FAKE_ACL_MASKED
    unset XDG_CONFIG_HOME XDG_DATA_HOME CALLER_SECRET_TOKEN https_proxy
    export SUDO_USER=owner BOOTSTRAP_OS_RELEASE="$tmp/os-ubuntu"
}

bs() {   # bs <args...>  -> sets $out and $rc
    out=$(bash "$BOOTSTRAP" "$@" 2>&1); rc=$?
}
called() { grep -q -- "$1" "$log"; }
calledE() { grep -Eq -- "$1" "$log"; }

listing() { (cd "$tmp" && find home -mindepth 1 | sort); }

# ---- B5: who may run it, and on what ---------------------------------------

reset; FAKE_UID=1000 bs --runtime claudecode
assert "not root: exit 4"                                   '[ "$rc" -eq 4 ]'
assert "not root: says to use sudo"                         'grep -q "sudo" <<<"$out"'
assert "not root: nothing was called"                       '[ ! -s "$log" ]'

reset; unset SUDO_USER; bs --runtime claudecode
assert "root without sudo and without --user: exit 4 (B5)"  '[ "$rc" -eq 4 ]'
assert "...and the message names --user"                    'grep -q -- "--user" <<<"$out"'

reset; SUDO_USER=root bs --runtime claudecode
assert "SUDO_USER=root is not a target: exit 4"             '[ "$rc" -eq 4 ]'

reset; unset SUDO_USER; bs --runtime claudecode --user owner --dry-run
assert "root without sudo but with --user is accepted"      '[ "$rc" -eq 0 ]'

reset; bs --runtime claudecode --user nobody-here --dry-run
assert "a user that does not exist: exit 2"                 '[ "$rc" -eq 2 ]'

reset; BOOTSTRAP_OS_RELEASE="$tmp/os-fedora" bs --runtime claudecode
assert "Fedora: exit 3 (B5)"                                '[ "$rc" -eq 3 ]'
assert "Fedora: nothing was installed or cloned"            '[ ! -s "$log" ]'
reset; BOOTSTRAP_OS_RELEASE="$tmp/os-debian" bs --runtime claudecode --dry-run
assert "Debian is accepted"                                 '[ "$rc" -eq 0 ]'
reset; BOOTSTRAP_OS_RELEASE="$tmp/os-mint" bs --runtime claudecode --dry-run
assert "a derivative (ID_LIKE contains debian) is accepted" '[ "$rc" -eq 0 ]'

reset; FAKE_PY_OLD=1 bs --runtime claudecode --dry-run
assert "python3 older than 3.10: exit 3"                    '[ "$rc" -eq 3 ]'

# ---- options ----------------------------------------------------------------

reset; bs --frobnicate
assert "an unknown option: exit 2"                          '[ "$rc" -eq 2 ]'
reset; bs --runtime
assert "an option without its value: exit 2"                '[ "$rc" -eq 2 ]'
reset; bs --runtime emacs
assert "an unknown runtime: exit 2"                         '[ "$rc" -eq 2 ]'
reset; bs --runtime claudecode --owner-name Someone
assert "--owner-name alone: exit 2"                         '[ "$rc" -eq 2 ]'
reset; bs --runtime claudecode --env-file "$tmp/nope"
assert "an --env-file that is not a file: exit 2"           '[ "$rc" -eq 2 ]'
reset; bs --help
assert "--help exits 0 and shows the exit codes"            '[ "$rc" -eq 0 ] && grep -q "Exit codes" <<<"$out"'

# ---- B4: --dry-run changes nothing ------------------------------------------

reset; FAKE_INSTALLED="" ; export FAKE_INSTALLED
before=$(listing)
bs --runtime claudecode --yes --with-sms --test-mail --owner-name "Ada" --owner-email ada@example.com --dry-run
after=$(listing)
assert "--dry-run exits 0"                                  '[ "$rc" -eq 0 ]'
assert "--dry-run prints the actions with would:"           'grep -q "^would: apt-get install -y git python3 curl ca-certificates" <<<"$out"'
assert "--dry-run names the clone and the linger"           'grep -q "^would: sudo -u owner -H git clone --branch v0.11.0" <<<"$out" && grep -q "^would: loginctl enable-linger owner" <<<"$out"'
assert "--dry-run names the himalaya install"               'grep -q "^would: sudo -u owner -H env PREFIX=.*/.local sh -c" <<<"$out"'
assert "--dry-run names the hand over"                      'grep -q "^would: sudo -u owner -H env -i <clean environment, LANG=en_US.UTF-8> python3 .*/scripts/bootstrap_user.py --runtime claudecode --ref v0.11.0" <<<"$out"'
assert "--dry-run did not touch the disk (B4)"              '[ "$before" = "$after" ]'
assert "--dry-run says it would wait for the user's bus" 'grep -q "^would: wait up to 1s for $tmp/run/1000/bus" <<<"$out"'
assert "--dry-run called no mutating command"               '! called "apt-get" && ! called "loginctl" && ! called "git clone" && ! called "curl" && ! called "bootstrap_user.py"'
unset FAKE_INSTALLED

# ---- the real run: packages, himalaya, linger, clone, hand over -------------

reset
bs --runtime claudecode
assert "a run exits 0"                                      '[ "$rc" -eq 0 ]'
assert "present packages are not installed again"           '! called "apt-get"'
assert "himalaya missing: the official installer runs as the user into ~/.local" \
    'calledE "sudo -u owner -H env -i .* env PREFIX=$home/.local sh -c"'
assert "linger is enabled"                                  'called "loginctl enable-linger owner"'
assert "the clone goes to the harness workspace, as the user, at the newest tag" \
    'calledE "sudo -u owner -H env -i .* git clone --branch v0.11.0 https://example.invalid/paynani.git $home/.claude/workspace/paynani"'
assert "v0.11.0 beats v0.9.1 and v0.10.0 (version sort, not text sort)" '! called "branch v0.9.1" && ! called "branch v0.10.0"'
assert "the hand over is the one BOOT-2 relies on" \
    'calledE "sudo -u owner -H env -i .* LANG=en_US.UTF-8 .* python3 $home/.claude/workspace/paynani/scripts/bootstrap_user.py --runtime claudecode --ref v0.11.0"'

reset; FAKE_HIMALAYA="v2.1.0" FAKE_LINGER=yes bs --runtime claudecode
assert "himalaya 2.x present: no installer"                 '! called "PREFIX="'
assert "linger already yes: not enabled again"              '! called "enable-linger"'
reset; FAKE_HIMALAYA="v1.4.0" bs --runtime claudecode
assert "himalaya 1.x counts as missing: the installer runs" 'called "PREFIX="'
assert "...and it fails the run when v2 is still missing (exit 1)" '[ "$rc" -eq 1 ] && grep -q "himalaya v2.x is still missing" <<<"$out"'

reset; FAKE_INSTALLED="git curl" bs --runtime claudecode
assert "only the missing packages are installed"            'called "apt-get install -y python3 ca-certificates"'

reset
bs --runtime codex --dir "$home/where/paynani" --ref main --with-sms --upgrade --yes --test-mail \
    --owner-name "Ada Lovelace" --owner-email ada@example.com
assert "every option reaches the user half" \
    'called "bootstrap_user.py --runtime codex --ref main --owner-name Ada Lovelace --owner-email ada@example.com --yes --with-sms --upgrade --test-mail"'
assert "--dir and --ref are honoured by the clone"          'called "git clone --branch main https://example.invalid/paynani.git $home/where/paynani"'
reset; LANG=es_MX.UTF-8 bs --runtime claudecode
assert "LANG is handed to the user half"                    'called "LANG=es_MX.UTF-8"'

# --env-file: copied private, handed over, and the copy is gone afterwards.
reset
printf 'PAYNANI_EMAIL=agent@example.com\nPAYNANI_PASSWORD=not-a-real-secret\n' >"$tmp/creds.env"
chmod 640 "$tmp/creds.env"
bs --runtime claudecode --env-file "$tmp/creds.env"
copy=$(grep -o -- '--env-file [^ ]*' "$log" | tail -1 | cut -d' ' -f2)
assert "--env-file: the user half gets a copy, not the original" '[ -n "$copy" ] && [ "$copy" != "$tmp/creds.env" ]'
assert "--env-file: the copy was made with mode 600"        'called "install -m 600"'
assert "--env-file: the copy is removed when the script ends" '[ -n "$copy" ] && [ ! -e "$copy" ]'
assert "--env-file: the secret never appears in the output or the log" '! grep -q "not-a-real-secret" <<<"$out" && ! grep -q "not-a-real-secret" "$log"'

# ---- the environment the user's commands get (BOOT-2 finding by Andy, #358) ---

reset
export XDG_CONFIG_HOME=/root/.config XDG_DATA_HOME=/root/.local/share CALLER_SECRET_TOKEN=leak-me
bs --runtime claudecode
assert "a run with the caller's XDG_* exported still exits 0" '[ "$rc" -eq 0 ]'
assert "every command as the user starts from env -i (never the caller's environment)" \
    '[ "$(grep -c "^sudo -u owner -H " "$log")" -gt 3 ] && [ "$(grep "^sudo -u owner -H " "$log" | grep -vc "^sudo -u owner -H env -i ")" -eq 0 ]'
assert "the sudo line carries neither XDG_CONFIG_HOME nor XDG_DATA_HOME of the caller" \
    '! grep "^sudo " "$log" | grep -q "XDG_CONFIG_HOME=/root\|XDG_DATA_HOME=/root"'
assert "the clone, as the user, sees no XDG_CONFIG_HOME, XDG_DATA_HOME or caller secret" \
    'calledE "^env HOME=$home XDG_CONFIG_HOME=UNSET XDG_DATA_HOME=UNSET .* LEAK=UNSET"'
assert "...and sees the user's HOME, runtime dir and session bus" \
    'called "XDG_RUNTIME_DIR=$tmp/run/1000 DBUS=unix:path=$tmp/run/1000/bus"'
unset XDG_CONFIG_HOME XDG_DATA_HOME CALLER_SECRET_TOKEN

reset; export https_proxy=http://proxy.invalid:3128
bs --runtime claudecode
assert "a proxy of the caller still reaches the user's commands (git, curl need it)" 'called "PROXY=http://proxy.invalid:3128"'
unset https_proxy

# linger starts the user's systemd; install.sh needs its bus, so the script waits for it.
reset; FAKE_NO_BUS=1 bs --runtime claudecode
assert "no user bus after linger: exit 1, and it says why" \
    '[ "$rc" -eq 1 ] && grep -q "systemd user session of owner did not come up" <<<"$out"'
assert "...and nothing was cloned or handed over" '! called "git clone" && ! called "bootstrap_user.py"'
reset; mkdir -p "$tmp/run/1000"; "$REAL_PYTHON3" -c 'import socket,sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' "$tmp/run/1000/bus"
FAKE_LINGER=yes bs --runtime claudecode
assert "linger already on and the bus there: it goes on without waiting" '[ "$rc" -eq 0 ] && ! called "enable-linger"'

# ---- what the script creates in the user's home is private (BOOT-2 finding by Andy, #358) ---

reset
oldmask=$(umask); umask 002      # the usual Ubuntu umask: group-writable by default
bs --runtime claudecode
umask "$oldmask"
assert "the run succeeds with a group-writable umask" '[ "$rc" -eq 0 ]'
assert "~/.claude, which the script creates for the clone, is not group or world writable" \
    '[ "$(stat -c %a "$home/.claude")" = 700 ] && [ "$(stat -c %a "$home/.claude/workspace")" = 700 ]'
assert "...and neither is the himalaya installer's target nor anything else it made" \
    '! find "$home" -perm /022 | grep -q .'
assert "with umask 002 in the caller, every command handed to sudo carries umask 077" \
    '[ "$(grep -c "^sudo -u owner -H " "$log")" -gt 3 ] && [ "$(grep "^sudo -u owner -H " "$log" | grep -vc "umask 077; exec")" -eq 0 ]'

# ---- directories that already exist on the way to the clone (install.sh refuses g/o-writable ones) ---

reset
mkdir -p "$home/.claude/workspace" "$home/.claude/other"
chmod 775 "$home/.claude"; chmod 777 "$home/.claude/workspace"; chmod 777 "$home/.claude/other"
bs --runtime claudecode
assert "a group-writable ~/.claude on the way to the clone no longer blocks the run" '[ "$rc" -eq 0 ]'
assert "...~/.claude and ~/.claude/workspace lose group and world write (775 -> 755, 777 -> 755)" \
    '[ "$(stat -c %a "$home/.claude")" = 755 ] && [ "$(stat -c %a "$home/.claude/workspace")" = 755 ]'
assert "...and each is announced" 'grep -q "removing group and world write from $home/.claude " <<<"$out" && grep -q "removing group and world write from $home/.claude/workspace " <<<"$out"'
assert "...a directory that is not on the way to the clone is left alone" '[ "$(stat -c %a "$home/.claude/other")" = 777 ]'
assert "...and the home itself is never touched" '! called "chmod go-w -- $home$"'

reset
mkdir -p "$home/.claude"; chmod 700 "$home/.claude"
bs --runtime claudecode
assert "directories that are already private are not touched" '! called "chmod"'

reset
mkdir -p "$home/.claude"; chmod 775 "$home/.claude"
bs --runtime claudecode --dry-run
assert "--dry-run says it would tighten, and does not" \
    'grep -q "^would: sudo -u owner -H chmod go-w -- $home/.claude" <<<"$out" && [ "$(stat -c %a "$home/.claude")" = 775 ]'

reset
mkdir -p "$home/.claude/workspace"; chmod 777 "$home/.claude/workspace"
FAKE_ROOT_OWNED="$home/.claude/workspace" bs --runtime claudecode
assert "a directory on the way that is not the user's: exit 1, naming it" \
    '[ "$rc" -eq 1 ] && grep -q "$home/.claude/workspace belongs to root, not to owner" <<<"$out"'
assert "...it is not touched: no chmod, no clone, nothing handed over" \
    '! called "chmod" && ! called "git clone" && ! called "bootstrap_user.py" && [ "$(stat -c %a "$home/.claude/workspace")" = 777 ]'
reset
mkdir -p "$home/.claude/workspace"; chmod 755 "$home/.claude/workspace"
FAKE_ROOT_OWNED="$home/.claude" bs --runtime claudecode
assert "a root-owned directory on the way fails even when it is not writable (install.sh would refuse it)" \
    '[ "$rc" -eq 1 ] && grep -q "$home/.claude belongs to root" <<<"$out" && ! called "git clone"'
reset
mkdir -p "$home/.claude"; chmod 775 "$home/.claude"
FAKE_ROOT_OWNED="$home" bs --runtime claudecode
assert "the home itself is never inspected, so a home that is not the user's is install.sh's to report" '[ "$rc" -eq 0 ]'

# ---- default ACLs: neither the umask nor chmod can fix them, so the script refuses (BOOT-3 finding) ---

reset
mkdir -p "$home/.claude"
FAKE_ACL_BAD="$home/.claude" bs --runtime claudecode
assert "a default ACL that lets another user write on the way to the clone: exit 1, naming it" \
    '[ "$rc" -eq 1 ] && grep -q "$home/.claude has a default ACL" <<<"$out" && grep -q "default:user:runner:rwx" <<<"$out"'
assert "...it does not change the ACL or anything else: no chmod, no clone, nothing handed over" \
    '! called "chmod" && ! called "setfacl" && ! called "git clone" && ! called "bootstrap_user.py"'
assert "...and says how to remove it, or to choose another --dir" 'grep -q "setfacl -k $home/.claude" <<<"$out" && grep -q -- "--dir" <<<"$out"'

reset
FAKE_ACL_BAD="$home" bs --runtime claudecode
assert "the same ACL on the home itself (where the runner image puts it) refuses too" \
    '[ "$rc" -eq 1 ] && grep -q "$home has a default ACL" <<<"$out" && ! called "git clone"'

reset
mkdir -p "$home/.claude"
FAKE_ACL_MASKED="$home/.claude $home" bs --runtime claudecode
assert "an entry the mask leaves read-only is not a problem" '[ "$rc" -eq 0 ]'
reset
bs --runtime claudecode
assert "the usual default ACL (user::rwx, group::r-x, other::r-x) does not block" '[ "$rc" -eq 0 ]'

# ---- B3: what exists is not replaced ----------------------------------------

reset
bs --runtime claudecode >/dev/null
reset
mkdir -p "$home/.claude/workspace/paynani/.git" "$home/.claude/workspace/paynani/scripts"
printf 'import sys\nsys.exit(0)\n' >"$home/.claude/workspace/paynani/scripts/bootstrap_user.py"
bs --runtime claudecode
assert "an existing clone is used, not cloned over (B3)"    '[ "$rc" -eq 0 ] && ! called "git clone" && grep -q "existing clone" <<<"$out"'
assert "...and without --upgrade the tags are not fetched"  '! called "fetch"'
bs --runtime claudecode --upgrade
assert "--upgrade on an existing clone fetches the tags"    'called "git -C $home/.claude/workspace/paynani fetch --tags --force origin"'

reset; mkdir -p "$home/.claude/workspace/paynani"; echo x >"$home/.claude/workspace/paynani/file"
bs --runtime claudecode
assert "a non-empty directory that is not a clone: exit 2"  '[ "$rc" -eq 2 ] && ! called "git clone"'

# ---- which harness, when --runtime is not given -----------------------------

reset; mkdir -p "$home/.openclaw" "$home/.claude"
bs --yes
assert "two harnesses and --yes without --runtime or --dir: exit 2, no choice (B6)" \
    '[ "$rc" -eq 2 ] && grep -q "openclaw claudecode\|several harnesses" <<<"$out" && ! called "git clone"'
reset; mkdir -p "$home/.hermes"
bs
assert "one harness and no --runtime: its workspace, and --runtime goes empty to the user half" \
    'called "git clone --branch v0.11.0 https://example.invalid/paynani.git $home/.hermes/workspace/paynani" && called "bootstrap_user.py --runtime  --ref v0.11.0"'
reset
bs
assert "no harness, no --runtime, no --dir: exit 2"         '[ "$rc" -eq 2 ] && ! called "git clone"'
reset; mkdir -p "$home/.openclaw" "$home/.claude"
bs --yes --dir "$home/p"
assert "with --dir the user half picks (runtime empty)"     '[ "$rc" -eq 0 ] && called "bootstrap_user.py --runtime  --ref v0.11.0"'

# ---- hand over failures ------------------------------------------------------

reset; FAKE_NO_USER_PY=1 bs --runtime claudecode
assert "no scripts/bootstrap_user.py in the ref: exit 1 and says so" \
    '[ "$rc" -eq 1 ] && grep -q "bootstrap_user.py not found in this ref" <<<"$out"'
reset; FAKE_USER_RC=1 bs --runtime claudecode
assert "the user half failing fails the run with its status" '[ "$rc" -eq 1 ]'

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
