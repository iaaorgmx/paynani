#!/usr/bin/env bash
# End-to-end run of bootstrap.sh on a clean Ubuntu VM (paynani#343, PRD #335 B1-B3).
#
# Runs as root on a CI runner that has systemd, sudo and linger -- a real VM, not
# a container, because a container has no systemd user session and the units
# bootstrap.sh installs would never start. It expects the fake mail server
# (scripts/fake_mail_server.py) already listening and its CA already trusted;
# the workflow does both before calling this.
#
#   sudo bash scripts/bootstrap_e2e.sh <repo checkout> <branch or tag>
#
# B4 (--dry-run) is not here: B5 and B6 are covered by the unit tests of BOOT-1
# and BOOT-2, as the issue says, and B4 is BOOT-1's.
set -euo pipefail

REPO=${1:?repo checkout}
REF=${2:?branch or tag for --ref}
USER_NAME=agente
OWNER_NAME=Prueba
OWNER_EMAIL=prueba@example.com
WORK=/tmp/paynani-e2e
# doctor rows that may be something other than ok here, and why. Keep this list
# short and every entry explained: a row added here is a check the job stops making.
#   runtime: the runner has no `claude` binary, so Claude Code cannot be reached.
ALLOWED_NOT_OK="runtime"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "ok   $*"; }
as_user() { sudo -u "$USER_NAME" -H env XDG_RUNTIME_DIR="/run/user/$(id -u "$USER_NAME")" "$@"; }

mkdir -p "$WORK"
id "$USER_NAME" >/dev/null 2>&1 || useradd -m -s /bin/bash "$USER_NAME"
HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)

# The credentials the fake server accepts, with the names `paynani onboard`
# writes (validate.py). The SMTP side only exists under the AGENT_EMAIL_ names;
# .env.example's PAYNANI_SMTP_* are read by nothing.
ENV_IN="$WORK/paynani.env"
cat > "$ENV_IN" <<EOF
AGENT_EMAIL_ACCOUNT=agente@example.com
AGENT_EMAIL_PASSWORD=${FAKE_MAIL_PASSWORD:?FAKE_MAIL_PASSWORD}
AGENT_EMAIL_FROM_NAME=Agente de prueba
AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=localhost
AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=${FAKE_IMAP_PORT:-9993}
AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=localhost
AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=${FAKE_SMTP_PORT:-9465}
EOF
chmod 644 "$ENV_IN"   # agente reads it through bootstrap_user.py; it holds a throwaway password

run_bootstrap() {
    local label=$1 log="$WORK/bootstrap-$1.log" rc=0
    echo "::group::bootstrap.sh ($label)"
    bash "$REPO/bootstrap.sh" --yes --user "$USER_NAME" --runtime claudecode \
        --env-file "$ENV_IN" --owner-name "$OWNER_NAME" --owner-email "$OWNER_EMAIL" \
        --ref "$REF" 2>&1 | tee "$log" || rc=${PIPESTATUS[0]}
    echo "::endgroup::"
    [ "$rc" -eq 0 ] || fail "bootstrap.sh ($label) exited $rc"
    pass "bootstrap.sh ($label) exited 0"
}

# Where the install put things, asked of paynani itself rather than guessed.
locate() {
    CLONE=$(find "$HOME_DIR" -maxdepth 4 -name bootstrap.sh -path '*paynani*' -printf '%h\n' | head -1)
    [ -n "$CLONE" ] || fail "no paynani clone under $HOME_DIR"
    ENV_FILE=$(as_user python3 -c "import sys; sys.path.insert(0, '$CLONE/harness'); import paths; print(paths.env_file())")
}

# The files B2 and B3 compare between runs: credentials, roster, himalaya,
# runtime.env, the user units and the harness settings bootstrap may write.
snapshot() {
    {
        for f in "$ENV_FILE" "$CLONE/roster.md" "$HOME_DIR/.config/himalaya/config.toml" \
                 "$CLONE/runtime.env" "$HOME_DIR/.claude/settings.json"; do
            [ -e "$f" ] && sha256sum "$f" || echo "absent  $f"
        done
        find "$HOME_DIR/.config/systemd/user" -maxdepth 1 -name 'paynani-*' -type f -exec sha256sum {} + 2>/dev/null | sort -k2
        git -C "$CLONE" rev-parse HEAD
    } > "$1"
}

check_b1() {
    locate
    echo "clone: $CLONE"
    echo "credentials: $ENV_FILE"

    grep -q 'listo\|ready' "$WORK/bootstrap-first.log" || fail "bootstrap.sh never said it was ready"
    pass "bootstrap.sh said it was ready"

    for unit in paynani-idle.service paynani-dispatch.service; do
        as_user systemctl --user is-active --quiet "$unit" || {
            as_user systemctl --user status "$unit" --no-pager || true
            fail "$unit is not active for $USER_NAME"
        }
        pass "$unit active"
    done

    [ "$(loginctl show-user "$USER_NAME" -p Linger --value)" = "yes" ] || fail "linger is not on for $USER_NAME"
    pass "linger yes"

    [ "$(stat -c '%a %U' "$ENV_FILE")" = "600 $USER_NAME" ] || fail "$ENV_FILE is $(stat -c '%a %U' "$ENV_FILE"), want 600 $USER_NAME"
    pass ".env 600 and owned by $USER_NAME"

    grep -qiF "$OWNER_EMAIL" "$CLONE/roster.md" || fail "the owner's row is not in roster.md"
    pass "owner in roster.md"

    grep -qE '^\[accounts\.paynani(\.[^]]*)?\]' "$HOME_DIR/.config/himalaya/config.toml" || fail "no [accounts.paynani] in the himalaya config"
    pass "[accounts.paynani] in the himalaya config"

    as_user "$CLONE/scripts/paynani" doctor --json > "$WORK/doctor.json" || true
    python3 - "$WORK/doctor.json" "$ALLOWED_NOT_OK" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
allowed = set(sys.argv[2].split())
checks = data.get("checks", data) if isinstance(data, dict) else data
bad = []
for c in checks:
    name, status = c.get("name"), c.get("status")
    mark = "ok  " if status == "ok" else ("skip" if name in allowed else "FAIL")
    print(f"  {mark} doctor {name}: {status} - {c.get('summary', '')}")
    if status != "ok" and name not in allowed:
        bad.append(name)
if bad:
    sys.exit("doctor rows not ok: " + ", ".join(bad))
PY
    pass "doctor rows ok (allowed otherwise: $ALLOWED_NOT_OK)"
}

# B1: a clean machine.
run_bootstrap first
check_b1
snapshot "$WORK/after-first.sums"

# B2: a second run changes nothing and is ready again.
run_bootstrap second
snapshot "$WORK/after-second.sums"
diff -u "$WORK/after-first.sums" "$WORK/after-second.sums" || fail "the second run changed files (B2)"
pass "B2: the second run changed nothing"

# B3: a roster.md edited by hand survives a third run untouched.
# A row in the same shape as the table's header, as a person would add it.
cols=$(grep -m1 -E '^\| *Name *\|' "$CLONE/roster.md" | tr -cd '|' | wc -c)
row="| Persona a mano | mano@example.com | Human |"
for _ in $(seq 4 $((cols - 1))); do row="$row |"; done
printf '%s\n' "$row" >> "$CLONE/roster.md"
chown "$USER_NAME:" "$CLONE/roster.md"
before=$(sha256sum "$CLONE/roster.md")
run_bootstrap third
[ "$(sha256sum "$CLONE/roster.md")" = "$before" ] || fail "the third run rewrote the hand-edited roster.md (B3)"
pass "B3: the hand-edited roster.md is untouched"

echo "bootstrap end-to-end: all checks passed"
