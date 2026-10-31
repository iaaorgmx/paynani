#!/usr/bin/env bash
# Regression boundary for the first FR7 installer skeleton: it must be runnable,
# reject ambiguous input, and keep dry-run free of host and runtime side effects.

set -uo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON=${PYTHON:-python3}
pass=0
fail=0

file_mode() {
    if stat -c %a . >/dev/null 2>&1; then
        stat -c %a "$1"
    else
        stat -f '%OLp' "$1"
    fi
}

# ---------------------------------------------------------------------------
# This suite exercises systemd units, `loginctl` and ~/.config/systemd/user.
# On a host without a systemd user session there is nothing here to test, and
# the right answer is to say so rather than to fail or to be quietly omitted
# from a report.
#
# The tester on the first macOS install skipped both Linux suites and said which
# and why, which was correct -- and rested entirely on their noticing. The suite
# knew less about its own applicability than the person running it. #101.
#
# Exit 0, not a distinct failure code, for the same reason test_paths.sh passes
# without php: this is a host the project supports, running a suite that does
# not apply to it. The rule is not "be Linux", it is "do not claim to have
# checked what you did not check".
if ! systemctl --user show-environment >/dev/null 2>&1; then
    printf 'skip %s (no systemd --user session on this host: %s)\n' \
        "$(basename "$0")" "$(uname -s)"
    printf '\n0 passed, 0 failed, 1 suite skipped (no systemd --user)\n'
    exit 0
fi

# The clone is the install, so the installer under test has to be a clone inside
# the sandbox — not this working copy. Running $ROOT/scripts/install.sh against
# a fake HOME would have it converge into the real repository.
#
# It is a genuine git checkout because the installer refuses to write when a
# runtime-owned path is tracked or unignored, and that guard is worth
# exercising rather than skipping.

check_status() {
    local description=$1 expected=$2
    shift 2
    local output status service_path
    # Every invocation gets a fresh hostile-runtime marker. This keeps a real
    # non-dry probe from contaminating the later dry-run inertness assertion.
    rm -f "$sandbox/runtime-side-effect"
    service_path=${FAKE_SERVICE_PATH:-$fixture_bin:/usr/bin:/bin}
    output=$(env -u PAYNANI_ENV \
        HOME="$sandbox" USER='victim; id' \
        XDG_CONFIG_HOME="$sandbox/ignored-config" \
        XDG_STATE_HOME="$sandbox/ignored-state" \
        HERMES_NOTIFY_URL=http://127.0.0.1:9/webhooks/paynani-notify \
        HERMES_ROSTER_URL=http://127.0.0.1:9/webhooks/paynani-roster \
        HERMES_HEALTH_URL=http://127.0.0.1:9/health \
        FAKE_SERVICE_PATH="$service_path" \
        PATH="${PATH_EXTRA:+$PATH_EXTRA:}$fixture_bin:/usr/bin:/bin" \
        "$INSTALL" "$@" 2>&1)
    status=$?
    if [[ "$status" == "$expected" ]]; then
        printf 'ok   %s
' "$description"
        pass=$((pass + 1))
    else
        printf 'FAIL %s (expected status %s, got %s)
%s
'             "$description" "$expected" "$status" "$output"
        fail=$((fail + 1))
    fi
    LAST_OUTPUT=$output
}

sandbox=$(mktemp -d)
fixture_root=$(mktemp -d)
fixture_bin="$fixture_root/bin"
mkdir -p "$fixture_bin"
trap 'rm -rf "$sandbox" "$fixture_root"' EXIT

# Removes everything the installer owns, in both containers, without deleting
# the installer itself — the clone is now the config directory, so the old
# `rm -rf "$sandbox/.config"` would take scripts/install.sh with it.
reset_install() {
    rm -rf "$sandbox/.config" "$sandbox/.local"
    rm -rf "$clone/hermes" "$clone/state"
    rm -f "$clone/install.manifest" "$clone/runtime.env" "$clone/.env" "$clone/roster.md"
}

clone="$sandbox/workspace/paynani"
mkdir -p "$(dirname "$clone")"
cp -a "$ROOT" "$clone"
rm -rf "$clone/state" "$clone/.env" "$clone/runtime.env" "$clone/install.manifest" \
    "$clone/hermes" "$clone/roster.md"
# A genuinely clean clone. Leaving pre-existing bytecode caches here made the
# "leaves HOME untouched" check order-dependent: with a matching __pycache__
# already present when the tree is snapshotted, an installer that writes
# bytecode into the repository it is converging looks inert.
find "$clone" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
INSTALL="$clone/scripts/install.sh"
state_tree="$clone/state"
before=$("$PYTHON" -c 'from pathlib import Path; print(sorted(str(p) for p in Path("'$sandbox'").rglob("*")))')

cat >"$fixture_bin/systemctl" <<'EOF'
#!/usr/bin/env bash
[[ "${FAKE_SYSTEMD:-yes}" == yes ]] || exit 1
case "$*" in
    '--user show-environment')
        if [[ "${FAKE_SERVICE_PATH:-}" == '__NONE__' ]]; then
            printf 'LANG=C.UTF-8\n'
        else
            printf 'PATH=%s\n' "${FAKE_SERVICE_PATH:-/usr/bin:/bin}"
        fi
        ;;
    '--user daemon-reload')
        printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
        ;;
    '--user is-enabled --quiet '*)
        unit=${*: -1}
        [[ -e "$FAKE_SYSTEMD_STATE/$unit.enabled" ]]
        ;;
    '--user is-active --quiet '*)
        unit=${*: -1}
        [[ -e "$FAKE_SYSTEMD_STATE/$unit.active" ]]
        ;;
    '--user enable --now '*)
        unit=${*: -1}
        : >"$FAKE_SYSTEMD_STATE/$unit.enabled"
        if [[ "${FAKE_START_INACTIVE_UNIT:-}" != "$unit" ]]; then
            : >"$FAKE_SYSTEMD_STATE/$unit.active"
        fi
        printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
        ;;
    '--user enable '*)
        unit=${*: -1}
        : >"$FAKE_SYSTEMD_STATE/$unit.enabled"
        printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
        ;;
    '--user stop '*)
        unit=${*: -1}
        rm -f "$FAKE_SYSTEMD_STATE/$unit.active"
        printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
        ;;
    '--user disable --now '*)
        unit=${*: -1}
        rm -f "$FAKE_SYSTEMD_STATE/$unit.enabled" "$FAKE_SYSTEMD_STATE/$unit.active"
        printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
        ;;
    '--user restart '*)
        unit=${*: -1}
        : >"$FAKE_SYSTEMD_STATE/$unit.active"
        printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
        ;;
    *) exit 2 ;;
esac
EOF
cat >"$fixture_bin/systemd-analyze" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
[[ "${FAKE_VERIFY:-yes}" == yes ]]
EOF
cat >"$fixture_bin/systemd-run" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_SYSTEMD_LOG"
[[ "${FAKE_RUNTIME_RUN:-yes}" == yes ]] || exit 23
runtime=${*: -2:1}
"$runtime" "${@: -1}"
EOF
cat >"$fixture_bin/loginctl" <<'EOF'
#!/usr/bin/env bash
if [[ "${FAKE_LINGER:-yes}" == yes ]]; then
    printf 'yes\n'
else
    printf 'no\n'
fi
EOF
cat >"$fixture_bin/id" <<'EOF'
#!/usr/bin/env bash
[[ "$1" == '-un' ]] || exit 2
printf 'test-user\n'
EOF
cat >"$fixture_bin/openclaw" <<'EOF'
#!/usr/bin/env bash
: >"$HOME/runtime-side-effect"
[[ "$1" == '--version' ]] || exit 2
printf 'openclaw test\n'
EOF
cat >"$fixture_bin/hermes" <<'EOF'
#!/usr/bin/env bash
: >"$HOME/runtime-side-effect"
if [[ "$1" == 'webhook' && "$2" == '--help' ]]; then
    printf 'webhook test help\n'
    exit 0
fi
[[ "$1" == '--version' ]] || exit 2
printf 'hermes test\n'
EOF
chmod 755 "$fixture_bin/systemctl" "$fixture_bin/loginctl" "$fixture_bin/id" \
    "$fixture_bin/systemd-analyze" "$fixture_bin/systemd-run" \
    "$fixture_bin/openclaw" "$fixture_bin/hermes"
export FAKE_SYSTEMD_LOG="$fixture_root/systemd.log"
export FAKE_SYSTEMD_STATE="$fixture_root/systemd-state"
mkdir -p "$FAKE_SYSTEMD_STATE"
notify_secret="$fixture_root/notify.secret"
roster_secret="$fixture_root/roster.secret"
printf 'notify-test-secret\n' >"$notify_secret"
printf 'roster-test-secret\n' >"$roster_secret"
chmod 600 "$notify_secret" "$roster_secret"

check_status 'help is runnable' 0 --help
[[ "$LAST_OUTPUT" == *'--runtime openclaw'* ]] || {
    printf 'FAIL help documents OpenClaw\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *'--runtime codex'* ]] || {
    printf 'FAIL help documents Codex\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *'--runtime opencode'* ]] || {
    printf 'FAIL help documents OpenCode\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *'--upgrade'* && "$LAST_OUTPUT" == *'--uninstall'* ]] || {
    printf 'FAIL help documents upgrade and uninstall modes\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *'Exit status 10 is success'* ]] || {
    printf 'FAIL help documents successful status 10\n'; fail=$((fail + 1));
}
if grep -Fq 'Exit status `10` is success' "$ROOT/INSTALL.md" &&
   grep -Fq -- '--upgrade' "$ROOT/INSTALL.md" &&
   grep -Fq -- '--uninstall' "$ROOT/INSTALL.md" &&
   grep -Fq -- '`--deliver` and `--chat-id` are guidance labels only' "$ROOT/INSTALL.md"; then
    printf 'ok   INSTALL.md documents installer modes and successful status 10\n'
    pass=$((pass + 1))
else
    printf 'FAIL INSTALL.md omits installer modes or successful status 10\n'
    fail=$((fail + 1))
fi

check_status 'Hermes delivery CLI shape parses' 78 \
    --runtime hermes --deliver telegram --chat-id 12345
[[ "$LAST_OUTPUT" == *'hermes_route_guidance=guided-only'* &&
   "$LAST_OUTPUT" == *'delivery_target=telegram'* &&
   "$LAST_OUTPUT" == *'chat_id=12345'* &&
   "$LAST_OUTPUT" == *'edits_hermes_config=false'* ]] || {
    printf 'FAIL guided delivery shape did not disclose its non-mutating boundary\n'
    fail=$((fail + 1))
}
# Interactive Hermes parsing now creates one-time route secrets before stopping
# for operator route configuration. Keep the alternative profile shape isolated
# so it tests its own first-run boundary rather than reusing the prior fixture.
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"
check_status 'Hermes profile CLI shape parses' 78 \
    --runtime hermes --profile default
[[ "$LAST_OUTPUT" == *'hermes_route_guidance=existing-profile'* &&
   "$LAST_OUTPUT" == *'profile=default'* &&
   "$LAST_OUTPUT" == *'edits_hermes_config=false'* ]] || {
    printf 'FAIL profile shape did not disclose its operator-managed boundary\n'
    fail=$((fail + 1))
}
check_status 'runtime is mandatory' 64
check_status 'unknown runtime is rejected' 64 --runtime something-else
check_status 'duplicate value option is rejected' 64 \
    --runtime openclaw --runtime hermes
[[ "$LAST_OUTPUT" == *'duplicate option: --runtime'* ]] || {
    printf 'FAIL duplicate value option does not name itself\n'; fail=$((fail + 1));
}
check_status 'duplicate flag is rejected' 64 \
    --runtime openclaw --dry-run --dry-run
check_status 'Hermes options cannot leak into OpenClaw flow' 64 \
    --runtime openclaw --profile default
check_status 'Hermes options cannot leak into Codex flow' 64 \
    --runtime codex --profile default
check_status 'non-interactive cannot leak into OpenClaw flow' 64 \
    --runtime openclaw --non-interactive
check_status 'non-interactive cannot leak into Codex flow' 64 \
    --runtime codex --non-interactive
check_status 'Hermes options cannot leak into OpenCode flow' 64 \
    --runtime opencode --profile default
check_status 'non-interactive cannot leak into OpenCode flow' 64 \
    --runtime opencode --non-interactive
check_status 'delivery target requires a chat ID' 64 \
    --runtime hermes --deliver telegram
check_status 'profile and delivery configuration are alternatives' 64 \
    --runtime hermes --profile default --deliver telegram --chat-id 12345
# Parser-shape checks above may leave a valid first-stage Hermes manifest and
# generated secrets. Upgrade convergence needs a fresh OpenClaw fixture rather
# than an intentionally incompatible manifest from another runtime.
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"
check_status 'upgrade mode converges the same owned filesystem boundary' 10 --runtime openclaw --upgrade
reset_install
check_status 'uninstall without ownership is idempotent' 0 --runtime openclaw --uninstall
check_status 'upgrade and uninstall are mutually exclusive' 64 \
    --runtime hermes --upgrade --uninstall
[[ "$LAST_OUTPUT" == *'mutually exclusive'* ]] || {
    printf 'FAIL mode exclusion reports the contract\n'; fail=$((fail + 1));
}
check_status 'non-interactive Hermes install requires route secrets' 64 \
    --runtime hermes --non-interactive --profile default
[[ "$LAST_OUTPUT" == *'requires --notify-secret-file and --roster-secret-file'* ]] || {
    printf 'FAIL non-interactive secret error is actionable\n'; fail=$((fail + 1));
}
check_status 'non-interactive Hermes secret-file shape parses' 78 \
    --runtime hermes --non-interactive --profile default \
    --notify-secret-file /tmp/notify --roster-secret-file /tmp/roster

# Runtime migration is explicit upgrade work. A first-stage Hermes install owns
# its generated secrets even before route configuration; switching to OpenClaw
# must preserve those secrets and shared mail state while converging the common
# unit/config boundary under the new runtime.
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"
check_status 'Hermes migration fixture creates owned route secrets' 78 \
    --runtime hermes --profile default
generated_notify="$clone/hermes/notify.secret"
generated_roster="$clone/hermes/roster.secret"
notify_before=$(sha256sum "$generated_notify")
roster_before=$(sha256sum "$generated_roster")
check_status 'runtime migration requires explicit upgrade mode' 78 \
    --runtime openclaw
check_status 'Hermes to OpenClaw upgrade preserves owned secrets and state' 10 \
    --runtime openclaw --upgrade
manifest="$clone/install.manifest"
runtime_env="$clone/runtime.env"
if grep -Fxq $'runtime\topenclaw' "$manifest" &&
   [[ "$(<"$runtime_env")" == 'PAYNANI_RUNTIME=openclaw' &&
      "$(sha256sum "$generated_notify")" == "$notify_before" &&
      "$(sha256sum "$generated_roster")" == "$roster_before" ]]; then
    printf 'ok   runtime migration preserves generated secrets and selects OpenClaw\n'
    pass=$((pass + 1))
else
    printf 'FAIL runtime migration changed generated secrets or missed the runtime boundary\n'
    fail=$((fail + 1))
fi
check_status 'migrated OpenClaw upgrade is idempotent' 0 \
    --runtime openclaw --upgrade
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"

check_status 'fresh Codex convergence creates managed artifacts' 10 \
    --runtime codex
runtime_env="$clone/runtime.env"
[[ "$(file_mode "$runtime_env")" == 600 ]] || {
    printf 'FAIL Codex generated runtime configuration is not mode 0600\n'
    fail=$((fail + 1))
}
[[ "$(<"$runtime_env")" == 'PAYNANI_RUNTIME=codex' ]] || {
    printf 'FAIL generated runtime configuration selects Codex\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *'codex_spool_probe=accepted'* &&
   "$LAST_OUTPUT" == *'verification_smoke=codex-spool result=writable'* &&
   "$LAST_OUTPUT" == *'codex_spool_probe=queue-or-replay scope=writability-only'* ]] || {
    printf 'FAIL Codex convergence did not report queue-or-replay verification\n'
    fail=$((fail + 1))
}
check_status 'second Codex convergence is idempotent' 0 --runtime codex
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"

check_status 'fresh OpenCode convergence creates managed artifacts' 10 \
    --runtime opencode
runtime_env="$clone/runtime.env"
[[ "$(file_mode "$runtime_env")" == 600 ]] || {
    printf 'FAIL OpenCode generated runtime configuration is not mode 0600\n'
    fail=$((fail + 1))
}
[[ "$(<"$runtime_env")" == 'PAYNANI_RUNTIME=opencode' ]] || {
    printf 'FAIL generated runtime configuration selects OpenCode\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *'opencode_spool_probe=accepted'* &&
   "$LAST_OUTPUT" == *'verification_smoke=opencode-spool result=writable'* &&
   "$LAST_OUTPUT" == *'opencode_plugin_next_step='*'scripts/opencode_plugin.py --install'* &&
   "$LAST_OUTPUT" == *'plugin=unobservable'* ]] || {
    printf 'FAIL OpenCode convergence did not report the spool probe and the plugin step\n'
    fail=$((fail + 1))
}
check_status 'second OpenCode convergence is idempotent' 0 --runtime opencode
check_status 'OpenCode uninstall names the plugin step' 10 --runtime opencode --uninstall
[[ "$LAST_OUTPUT" == *'opencode_plugin.py --uninstall'* ]] || {
    printf 'FAIL OpenCode uninstall did not name the plugin removal step\n'
    fail=$((fail + 1))
}
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"

# A fresh filesystem-only OpenClaw convergence creates each managed artifact,
# then atomically records ownership, verifies the installed units, proves the
# runtime through the user manager, and converges only required service state.
check_status 'fresh OpenClaw convergence creates managed artifacts' 10 \
    --runtime openclaw
manifest="$clone/install.manifest"
runtime_env="$clone/runtime.env"
[[ -f "$manifest" && ! -L "$manifest" && "$(file_mode "$manifest")" == 600 ]] || {
    printf 'FAIL ownership manifest is not a mode-0600 regular file\n'
    fail=$((fail + 1))
}
[[ "$(file_mode "$runtime_env")" == 600 ]] || {
    printf 'FAIL generated runtime configuration is not mode 0600\n'
    fail=$((fail + 1))
}
chmod 0644 "$runtime_env"
if [[ "$(file_mode "$runtime_env")" == 644 ]]; then
    printf 'ok   generated runtime configuration mode check detects 0644\n'
    pass=$((pass + 1))
else
    printf 'FAIL generated runtime configuration mode check does not detect 0644\n'
    fail=$((fail + 1))
fi
chmod 0600 "$runtime_env"
# systemd does not create the parent of a StandardOutput=append: path, it fails
# the unit. An install that converged the units and enabled them without this
# directory leaves both services dead, and the only symptom is a quiet mailbox.
[[ -d "$state_tree" && ! -L "$state_tree" && "$(file_mode "$state_tree")" == 700 ]] || {
    printf 'FAIL convergence did not create the state tree as a mode-0700 directory\n'
    fail=$((fail + 1))
}
# Six, plus paynani-telegram.service, which every install adds since 0.20.0 (#635).
[[ "$(grep -c '^artifact[[:space:]]' "$manifest")" == 7 ]] || {
    printf 'FAIL manifest does not record exactly seven created artifacts\n'
    fail=$((fail + 1))
}
[[ "$(<"$runtime_env")" == 'PAYNANI_RUNTIME=openclaw' ]] || {
    printf 'FAIL generated runtime configuration selects OpenClaw\n'
    fail=$((fail + 1))
}
for unit in paynani-idle.service paynani-idle@.service paynani-dispatch.service \
    paynani-logrotate.service paynani-logrotate.timer; do
    installed="$sandbox/.config/systemd/user/$unit"
    [[ -f "$installed" && ! -L "$installed" ]] || {
        printf 'FAIL convergence omitted unit %s\n' "$unit"
        fail=$((fail + 1))
        continue
    }
    [[ "$(<"$installed")" != *'/path/to/paynani'* ]] || {
        printf 'FAIL unit %s retains unresolved repository placeholder\n' "$unit"
        fail=$((fail + 1))
    }
done
installed_dispatch="$sandbox/.config/systemd/user/paynani-dispatch.service"
dispatch_unit="$(<"$installed_dispatch")"
[[ "$dispatch_unit" == *"EnvironmentFile=-$clone/runtime.env"* ]] || {
    printf 'FAIL dispatcher unit does not optionally load the installer-generated runtime configuration\n'
    fail=$((fail + 1))
}
[[ "$dispatch_unit" == *'Environment=PAYNANI_RUNTIME=auto'* ]] || {
    printf 'FAIL dispatcher unit does not retain the manual-install runtime default\n'
    fail=$((fail + 1))
}
[[ "$dispatch_unit" == *"Environment=PAYNANI_RUNTIME=auto"$'\n'"EnvironmentFile=-$clone/runtime.env"* ]] || {
    printf 'FAIL dispatcher runtime configuration does not override the inline default\n'
    fail=$((fail + 1))
}
[[ -e "$sandbox/runtime-side-effect" ]] || {
    printf 'FAIL OpenClaw was not executed in the systemd service environment\n'
    fail=$((fail + 1))
}
rm -f "$sandbox/runtime-side-effect"
[[ "$(<"$FAKE_SYSTEMD_LOG")" == *"verify $sandbox/.config/systemd/user/paynani-idle.service"* &&
   "$(<"$FAKE_SYSTEMD_LOG")" == *'--user --pipe --quiet --wait '*"$fixture_bin/openclaw --version"* &&
   "$(<"$FAKE_SYSTEMD_LOG")" == *'--user enable --now paynani-idle.service'* &&
   "$(<"$FAKE_SYSTEMD_LOG")" == *'--user enable --now paynani-dispatch.service'* &&
   "$(<"$FAKE_SYSTEMD_LOG")" == *'--user enable --now paynani-logrotate.timer'* &&
   "$(<"$FAKE_SYSTEMD_LOG")" != *'enable --now paynani-logrotate.service'* ]] || {
    printf 'FAIL service verification, runtime probe, or activation command shape is wrong\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *'openclaw_rules_next_step='*'scripts/openclaw_rules.py --install'* &&
   "$LAST_OUTPUT" == *'standing-rule=unobservable'* ]] || {
    printf 'FAIL OpenClaw convergence did not name the standing-rule step\n'
    fail=$((fail + 1))
}
: >"$FAKE_SYSTEMD_LOG"
check_status 'second OpenClaw convergence is idempotent' 0 --runtime openclaw
[[ "$(<"$FAKE_SYSTEMD_LOG")" != *'enable --now'* ]] || {
    printf 'FAIL converged service state was enabled again\n'; fail=$((fail + 1));
}
check_status 'owned converged artifacts are accepted by dry-run' 0 \
    --runtime openclaw --dry-run
reset_install

# A successful `enable --now` subprocess is not enough: the required unit must
# actually converge to both enabled and active before installation reports green.
rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"
FAKE_START_INACTIVE_UNIT=paynani-dispatch.service check_status \
    'activation refuses a required unit that does not become active' 78 \
    --runtime openclaw
[[ "$LAST_OUTPUT" == *'required user unit did not become enabled and active: paynani-dispatch.service'* ]] || {
    printf 'FAIL activation postcondition refusal is not actionable\n'
    fail=$((fail + 1))
}
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"
mkdir -p "$FAKE_SYSTEMD_STATE"

# Deliberately terminate after artifact N. The durable manifest must authorize
# exactly successful artifacts 1..N, not later planned paths.
PAYNANI_TEST_INTERRUPT_AFTER=2 check_status \
    'interrupted convergence exposes a partial-run status' 99 --runtime openclaw
manifest="$clone/install.manifest"
manifest_count=$(grep -c '^artifact[[:space:]]' "$manifest")
created_count=0
for path in "$sandbox/.config/systemd/user"/paynani-*.service \
    "$sandbox/.config/systemd/user"/paynani-*.timer \
    "$clone/runtime.env"; do
    [[ -e "$path" ]] && created_count=$((created_count + 1))
done
[[ "$manifest_count" == 2 && "$created_count" == 2 ]] || {
    printf 'FAIL partial run records %s artifacts but created %s (expected 2/2)\n' \
        "$manifest_count" "$created_count"
    fail=$((fail + 1))
}
while IFS=$'\t' read -r marker kind path digest extra; do
    [[ "$marker" != artifact ]] && continue
    [[ -f "$path" && -z "$extra" && -n "$digest" ]] || {
        printf 'FAIL manifest authorizes an absent or malformed artifact: %s\n' "$path"
        fail=$((fail + 1))
    }
done <"$manifest"
check_status 'partial convergence resumes to completion' 10 --runtime openclaw
check_status 'resumed convergence is idempotent' 0 --runtime openclaw
reset_install

# A stop after artifact creation but before manifest recording must self-heal:
# byte-identical generated content is adopted, while differing content remains
# unproven and fail-closed.
PAYNANI_TEST_INTERRUPT_AFTER_WRITE=1 check_status \
    'post-create pre-record interruption exposes crash window' 99 --runtime openclaw
manifest="$clone/install.manifest"
crash_window_artifact="$sandbox/.config/systemd/user/paynani-idle.service"
[[ -f "$crash_window_artifact" && "$(grep -c '^artifact[[:space:]]' "$manifest")" == 0 ]] || {
    printf 'FAIL crash-window fixture did not leave one created, unrecorded artifact\n'
    fail=$((fail + 1))
}
check_status 'matching crash-window artifact is adopted on resume' 10 --runtime openclaw
[[ "$(grep -c '^artifact[[:space:]]' "$manifest")" == 7 ]] || {
    printf 'FAIL resumed convergence did not record the adopted artifact set\n'
    fail=$((fail + 1))
}
check_status 'adopted crash-window convergence is idempotent' 0 --runtime openclaw
reset_install

# Uninstall consumes only durable ownership records from a partial run. A file
# at a later planned destination, plus credentials/state, must survive.
PAYNANI_TEST_INTERRUPT_AFTER=2 check_status \
    'second partial run prepares uninstall authorization fixture' 99 \
    --runtime openclaw
unowned_later="$sandbox/.config/systemd/user/paynani-logrotate.service"
printf 'operator-managed later artifact\n' >"$unowned_later"
printf 'mail-password=preserve\n' >"$clone/.env"
mkdir -p "$clone/state"
printf 'uid-state\n' >"$clone/state/uid.json"
check_status 'partial-run uninstall removes exactly recorded artifacts' 10 \
    --runtime openclaw --uninstall
[[ ! -e "$sandbox/.config/systemd/user/paynani-idle.service" &&
   ! -e "$sandbox/.config/systemd/user/paynani-dispatch.service" &&
   -f "$unowned_later" &&
   -f "$clone/.env" &&
   -f "$clone/state/uid.json" &&
   ! -e "$clone/install.manifest" ]] || {
    printf 'FAIL partial uninstall removed an unowned artifact or preserved owned state\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *'openclaw_rules.py --uninstall'* ]] || {
    printf 'FAIL OpenClaw uninstall did not name the standing-rule removal step\n'
    fail=$((fail + 1))
}
check_status 'second partial-run uninstall is idempotent' 0 \
    --runtime openclaw --uninstall
reset_install

# Modified owned artifacts are preserved, and the refusal names a safe recovery
# path that transfers ownership back to the operator without deleting edits.
check_status 'modified-artifact recovery fixture converges' 10 --runtime openclaw
modified="$clone/runtime.env"
printf 'PAYNANI_RUNTIME=openclaw\n# operator edit\n' >"$modified"
check_status 'modified owned artifact is preserved with actionable recovery' 78 \
    --runtime openclaw --uninstall
[[ "$LAST_OUTPUT" == *"owned artifact changed outside the installer: $modified"* &&
   "$LAST_OUTPUT" == *'move it to an operator-owned backup path, then rerun --uninstall'* ]] || {
    printf 'FAIL modified-artifact refusal omitted the path or safe uninstall recovery\n'
    fail=$((fail + 1))
}
[[ -f "$sandbox/.config/systemd/user/paynani-idle.service" &&
   -f "$sandbox/.config/systemd/user/paynani-dispatch.service" &&
   -e "$FAKE_SYSTEMD_STATE/paynani-idle.service.active" &&
   -e "$FAKE_SYSTEMD_STATE/paynani-dispatch.service.active" ]] || {
    printf 'FAIL uninstall mutated units or service state before validating all owned artifacts\n'
    fail=$((fail + 1))
}
modified_backup="$fixture_root/operator-runtime.env"
mv -- "$modified" "$modified_backup"
check_status 'uninstall forgets a preserved modified artifact after move-aside' 10 \
    --runtime openclaw --uninstall
[[ -f "$modified_backup" &&
   ! -e "$clone/install.manifest" &&
   ! -e "$FAKE_SYSTEMD_STATE/paynani-idle.service.enabled" &&
   ! -e "$FAKE_SYSTEMD_STATE/paynani-idle.service.active" &&
   ! -e "$FAKE_SYSTEMD_STATE/paynani-dispatch.service.enabled" &&
   ! -e "$FAKE_SYSTEMD_STATE/paynani-dispatch.service.active" &&
   ! -e "$FAKE_SYSTEMD_STATE/paynani-logrotate.timer.enabled" &&
   ! -e "$FAKE_SYSTEMD_STATE/paynani-logrotate.timer.active" ]] || {
    printf 'FAIL move-aside recovery did not preserve the edit, stop services, and clear ownership\n'
    fail=$((fail + 1))
}
reset_install

# The ownership reader fails closed on metadata and syntax before trusting any
# path. An attacker-controlled/symlinked record is never followed.
mkdir -p "$clone"
printf 'version\t1\nruntime\topenclaw\n' >"$clone/install.manifest"
chmod 0644 "$clone/install.manifest"
check_status 'insecure ownership manifest metadata fails closed' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'ownership manifest must be a user-owned mode-0600 regular file'* ]] || {
    printf 'FAIL insecure manifest refusal is not actionable\n'
    fail=$((fail + 1))
}
reset_install

mkdir -p "$clone"
manifest_target="$fixture_root/attacker.manifest"
printf 'version\t1\nruntime\topenclaw\n' >"$manifest_target"
chmod 0600 "$manifest_target"
ln -s "$manifest_target" "$clone/install.manifest"
check_status 'symlinked ownership manifest is never followed' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'ownership manifest must be a user-owned mode-0600 regular file'* ]] || {
    printf 'FAIL symlinked manifest refusal is not explicit\n'
    fail=$((fail + 1))
}
reset_install

mkdir -p "$clone"
printf 'version\t1\nruntime\topenclaw\nartifact\tfile\t%s\t%s\n' \
    "$fixture_root/outside-artifact" \
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
    >"$clone/install.manifest"
chmod 0600 "$clone/install.manifest"
check_status 'manifest cannot authorize paths outside the managed allowlist' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'unauthorized artifact record'* ]] || {
    printf 'FAIL unauthorized manifest path refusal is not explicit\n'
    fail=$((fail + 1))
}
reset_install

check_status 'dry-run reports planned OpenClaw changes' 10 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'runtime_cli='*"$fixture_bin/openclaw"* ]] || {
    printf 'FAIL dry-run reports resolved service-environment runtime CLI\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *'runtime_probe=deferred (dry-run never executes runtime code)'* ]] || {
    printf 'FAIL dry-run does not explain its inert runtime probe policy\n'; fail=$((fail + 1));
}
[[ ! -e "$sandbox/runtime-side-effect" ]] || {
    printf 'FAIL dry-run executed runtime code and mutated HOME\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *'systemd_user=available'* ]] || {
    printf 'FAIL dry-run reports systemd user availability\n'; fail=$((fail + 1));
}
for unit in paynani-idle.service paynani-idle@.service paynani-dispatch.service \
    paynani-logrotate.service paynani-logrotate.timer; do
    expected="inventory planned-managed-file=$sandbox/.config/systemd/user/$unit"
    [[ "$LAST_OUTPUT" == *"$expected"* ]] || {
        printf 'FAIL inventory omits managed unit %s\n' "$unit"
        fail=$((fail + 1))
    }
done
[[ "$LAST_OUTPUT" == *"inventory planned-managed-file=$clone/runtime.env"* ]] || {
    printf 'FAIL inventory omits planned runtime configuration\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *"inventory planned-ownership-manifest=$clone/install.manifest"* ]] || {
    printf 'FAIL inventory omits planned ownership manifest\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *"inventory container-directory=$sandbox/.config/systemd/user policy=never-own-directory"* ]] || {
    printf 'FAIL inventory claims the shared systemd directory\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *"inventory preserve-file=$clone/.env role=mailbox-credentials"* ]] || {
    printf 'FAIL inventory does not preserve mailbox credentials\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *"inventory preserve-tree=$clone/state"* ]] || {
    printf 'FAIL inventory does not preserve event and UID state\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *"inventory preserve-file=$clone/roster.md role=recipient-roster"* ]] || {
    printf 'FAIL inventory does not preserve the roster\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *'plan contains create, modify, or remove actions'* ]] || {
    printf 'FAIL dry-run does not explain successful drift status 10\n'; fail=$((fail + 1));
}

# Pre-existing artifacts without a secure ownership manifest are conflicts, not
# installer-owned files. Dry-run must preserve them and fail closed.
mkdir -p "$sandbox/.config/systemd/user"
printf 'operator-managed\n' >"$sandbox/.config/systemd/user/paynani-idle.service"
check_status 'dry-run preserves an unowned pre-existing unit and fails closed' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *"inventory conflict-preserve-file=$sandbox/.config/systemd/user/paynani-idle.service reason=unproven-ownership"* ]] || {
    printf 'FAIL unowned unit was not classified as a preserve conflict\n'
    fail=$((fail + 1))
}
reset_install

# A blocked managed artifact is a configuration refusal, never a change plan.
mkdir -p "$sandbox/.config/systemd/user"
chmod 0770 "$sandbox/.config/systemd/user"
check_status 'blocked unit container is a configuration refusal, not plan status 10' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *"inventory blocked-managed-file=$sandbox/.config/systemd/user/paynani-idle.service reason=unsafe-container"* ]] || {
    printf 'FAIL unsafe unit container did not block managed artifacts\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" != *'plan contains create, modify, or remove actions'* ]] || {
    printf 'FAIL blocked unit container was misreported as executable plan drift\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *'inventory result=blocked configuration-refusal=true'* ]] || {
    printf 'FAIL blocked artifacts did not propagate explicit refusal state\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *"install: unsafe managed container $sandbox/.config/systemd/user reason=group-or-world-writable; run: chmod go-w -- $sandbox/.config/systemd/user"* ]] || {
    printf 'FAIL refusal did not name the unsafe container, reason, and chmod remediation\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" != *'unproven pre-existing artifacts are preserved'* ]] || {
    printf 'FAIL unsafe-container refusal used the unrelated ownership-manifest explanation\n'
    fail=$((fail + 1))
}
reset_install

outside_systemd="$fixture_root/outside-systemd"
mkdir -p "$outside_systemd" "$sandbox/.config/systemd"
ln -s "$outside_systemd" "$sandbox/.config/systemd/user"
check_status 'symlinked managed container fails closed' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *"inventory conflict-container=$sandbox/.config/systemd/user reason=symlink"* ]] || {
    printf 'FAIL symlinked systemd container was not rejected\n'
    fail=$((fail + 1))
}
[[ -z "$(find "$outside_systemd" -mindepth 1 -print -quit)" ]] || {
    printf 'FAIL dry-run wrote through a symlinked container\n'
    fail=$((fail + 1))
}
reset_install
rm -rf "$sandbox/.config/systemd"

# The configuration container is the clone, and the clone is resolved with
# `pwd -P`. Reaching the installer through a symlinked path therefore converges
# on the physical directory rather than being refused: there is no symlink left
# in the chain to refuse. The symlink branch of validate_container_chain is
# still exercised, on the Hermes secret container, further down.
ln -s "$clone" "$sandbox/linked-clone"
output=$(env -u PAYNANI_ENV HOME="$sandbox" \
    PATH="$fixture_bin:/usr/bin:/bin" FAKE_SERVICE_PATH="$fixture_bin:/usr/bin:/bin" \
    "$sandbox/linked-clone/scripts/install.sh" --runtime openclaw --dry-run 2>&1)
[[ "$output" == *"inventory root=$clone "* && "$output" != *"linked-clone"* ]] || {
    printf 'FAIL a clone reached through a symlink did not resolve to its physical path\n'
    fail=$((fail + 1))
}
rm -f "$sandbox/linked-clone"
reset_install

# The OpenClaw workspace path is a read-only credentials probe. A symlink must
# be preserved and must never appear in the managed inventory.
mkdir -p "$sandbox/.openclaw/workspace"
credentials_target="$fixture_root/harness-env"
printf 'harness=true\n' >"$credentials_target"
ln -s "$credentials_target" "$sandbox/.openclaw/workspace/.env"
check_status 'harness credential symlink is detected as preserve-only' 10 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *"inventory preserve-file=$sandbox/.openclaw/workspace/.env role=mailbox-credentials"* ]] || {
    printf 'FAIL harness credential symlink was not preserved\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" != *"inventory managed-file=$sandbox/.openclaw/workspace/.env"* ]] || {
    printf 'FAIL harness credential probe became an owned write target\n'; fail=$((fail + 1));
}
rm -rf "$sandbox/.openclaw"

check_status 'Hermes dry-run validates secrets and reports planned changes' 10 \
    --runtime hermes --profile default --non-interactive --dry-run \
    --notify-secret-file "$notify_secret" --roster-secret-file "$roster_secret"
[[ "$LAST_OUTPUT" == *"inventory external-secret=$notify_secret role=notify validate-only=true"* ]] || {
    printf 'FAIL inventory claims ownership of external notify secret\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" == *"inventory external-secret=$roster_secret role=roster validate-only=true"* ]] || {
    printf 'FAIL inventory claims ownership of external roster secret\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" != *'notify-test-secret'* && "$LAST_OUTPUT" != *'roster-test-secret'* ]] || {
    printf 'FAIL dry-run disclosed route secret material\n'; fail=$((fail + 1));
}

chmod 644 "$notify_secret"
check_status 'Hermes dry-run rejects insecure supplied secret metadata' 78 \
    --runtime hermes --profile default --non-interactive --dry-run \
    --notify-secret-file "$notify_secret" --roster-secret-file "$roster_secret"
[[ "$LAST_OUTPUT" == *'non-symlink regular file'* && "$LAST_OUTPUT" == *'mode 0600'* ]] || {
    printf 'FAIL insecure-secret error omits the required metadata contract\n'
    fail=$((fail + 1))
}
chmod 600 "$notify_secret"

printf 'same-secret\n' >"$notify_secret"
printf 'same-secret\r\n' >"$roster_secret"
check_status 'Hermes dry-run rejects equal route secrets after line-ending trim' 78 \
    --runtime hermes --profile default --non-interactive --dry-run \
    --notify-secret-file "$notify_secret" --roster-secret-file "$roster_secret"
[[ "$LAST_OUTPUT" == *'route secrets must differ'* ]] || {
    printf 'FAIL equal-secret error is not actionable\n'; fail=$((fail + 1));
}
printf 'notify-test-secret\n' >"$notify_secret"
printf 'roster-test-secret\n' >"$roster_secret"

mkdir -p "$clone/hermes"
printf 'operator-secret\n' >"$clone/hermes/notify.secret"
chmod 600 "$clone/hermes/notify.secret"
check_status 'existing default-path Hermes secret is never claimed without provenance' 78 \
    --runtime hermes --profile default --dry-run
[[ "$LAST_OUTPUT" == *"inventory conflict-preserve-secret=$clone/hermes/notify.secret reason=unproven-ownership"* ]] || {
    printf 'FAIL existing default secret was claimed as installer-managed\n'
    fail=$((fail + 1))
}
reset_install

# This is where the symlink branch of validate_container_chain is exercised: the
# configuration container is the clone itself and resolves physically, but a
# nested container the installer would create is still a real symlink check.
outside_config="$fixture_root/outside-config"
mkdir -p "$outside_config" "$clone"
ln -s "$outside_config" "$clone/hermes"
check_status 'symlinked nested Hermes secret container fails closed' 78 \
    --runtime hermes --profile default --dry-run
[[ "$LAST_OUTPUT" == *"inventory conflict-container=$clone/hermes reason=symlink"* ]] || {
    printf 'FAIL symlinked nested Hermes container was not rejected\n'
    fail=$((fail + 1))
}
[[ -z "$(find "$outside_config" -mindepth 1 -print -quit)" ]] || {
    printf 'FAIL dry-run wrote through the nested Hermes symlink\n'
    fail=$((fail + 1))
}
reset_install
mkdir -p "$clone/hermes"
chmod 0770 "$clone/hermes"
check_status 'writable nested Hermes secret container fails closed' 78 \
    --runtime hermes --profile default --dry-run
[[ "$LAST_OUTPUT" == *"inventory conflict-container=$clone/hermes reason=group-or-world-writable"* ]] || {
    printf 'FAIL writable nested Hermes container was not rejected\n'
    fail=$((fail + 1))
}
reset_install

mv "$fixture_bin/openclaw" "$fixture_bin/openclaw.off"
check_status 'uninstall discovery does not require a removed runtime CLI' 0 \
    --runtime openclaw --uninstall --dry-run
[[ "$LAST_OUTPUT" == *'runtime_cli=not-required-for-uninstall'* ]] || {
    printf 'FAIL uninstall runtime discovery policy is unclear\n'; fail=$((fail + 1));
}
mv "$fixture_bin/openclaw.off" "$fixture_bin/openclaw"

FAKE_SERVICE_PATH=/usr/bin:/bin check_status \
    'runtime must exist in the systemd user service PATH' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'openclaw executable not found in the systemd user PATH'* ]] || {
    printf 'FAIL missing service-environment runtime error is actionable\n'
    fail=$((fail + 1))
}
FAKE_SERVICE_PATH=__NONE__ check_status \
    'missing systemd PATH fails closed instead of inventing one' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'systemd user environment does not report PATH'* ]] || {
    printf 'FAIL missing manager PATH did not fail closed\n'
    fail=$((fail + 1))
}

FAKE_SYSTEMD=no check_status 'unavailable systemd user session fails discovery' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'systemctl --user is unavailable'* ]] || {
    printf 'FAIL systemd failure is actionable\n'; fail=$((fail + 1));
}
FAKE_LINGER=no check_status 'disabled lingering fails with exact operator command' 78 \
    --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'sudo loginctl enable-linger test-user'* ]] || {
    printf 'FAIL linger failure prints the required command for id -un\n'; fail=$((fail + 1));
}
[[ "$LAST_OUTPUT" != *'victim; id'* ]] || {
    printf 'FAIL linger remediation interpolated inherited USER unsafely\n'
    fail=$((fail + 1))
}
FAKE_LINGER=no check_status 'uninstall continues when lingering is disabled' 0 \
    --runtime openclaw --uninstall --dry-run
[[ "$LAST_OUTPUT" == *'linger=disabled (informational; uninstall continues)'* ]] || {
    printf 'FAIL uninstall does not report disabled lingering informationally\n'
    fail=$((fail + 1))
}
FAKE_SYSTEMD=no check_status 'uninstall continues without the systemd user bus' 0 \
    --runtime openclaw --uninstall --dry-run
[[ "$LAST_OUTPUT" == *'systemd_user=unavailable (filesystem inventory continues)'* ]] || {
    printf 'FAIL degraded uninstall does not report unavailable service operations\n'
    fail=$((fail + 1))
}

mv "$fixture_bin/openclaw" "$fixture_bin/openclaw.off"
FAKE_SYSTEMD=no FAKE_LINGER=no check_status \
    'dry-run aggregates all prerequisite failures' 78 --runtime openclaw --dry-run
[[ "$LAST_OUTPUT" == *'systemctl --user is unavailable'* &&
   "$LAST_OUTPUT" == *'user lingering is disabled'* &&
   "$LAST_OUTPUT" == *'openclaw executable cannot be verified'* &&
   "$LAST_OUTPUT" == *'prerequisite failures (3)'* ]] || {
    printf 'FAIL dry-run did not report all prerequisite failures together\n'
    fail=$((fail + 1))
}
mv "$fixture_bin/openclaw.off" "$fixture_bin/openclaw"

after=$("$PYTHON" -c 'from pathlib import Path; print(sorted(str(p) for p in Path("'$sandbox'").rglob("*")))')
if [[ "$before" == "$after" ]]; then
    printf 'ok   skeleton leaves HOME untouched
'
    pass=$((pass + 1))
else
    printf 'FAIL skeleton changed HOME
'
    fail=$((fail + 1))
fi

# ---------------------------------------------------------------------------
# The installer reads back the runtime.env it wrote. #67.
#
# Every check above supplies the three Hermes URLs in the environment, which is
# how the defect stayed invisible: a re-run on a converged host has none of them,
# and the installer demanded values it had already recorded itself. The failure
# read as "this host was never configured" on a host that was configured,
# running and delivering mail.
#
# These run without the URLs, which is the case the harness above never covers.
# ---------------------------------------------------------------------------
recall_run() {   # runs the installer with no Hermes values in the environment
    env -u PAYNANI_ENV -u HERMES_NOTIFY_URL -u HERMES_ROSTER_URL \
        -u HERMES_HEALTH_URL -u HERMES_SIGNATURE_MODE \
        HOME="$sandbox" \
        XDG_CONFIG_HOME="$sandbox/ignored-config" \
        XDG_STATE_HOME="$sandbox/ignored-state" \
        FAKE_SERVICE_PATH="$fixture_bin:/usr/bin:/bin" \
        PATH="$fixture_bin:/usr/bin:/bin" \
        "$INSTALL" "$@" 2>&1
}

reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"

# Nothing recorded: the old failure, unchanged. An install that has never
# converged has nothing to recall and must still say so.
out=$(recall_run --runtime hermes --profile default --dry-run)
if [[ "$out" == *'HERMES_NOTIFY_URL is required'* ]]; then
    printf 'ok   with nothing recorded, the requirement is unchanged\n'
    pass=$((pass + 1))
else
    printf 'FAIL a host with no runtime.env should still demand the URLs\n%s\n' "$out"
    fail=$((fail + 1))
fi

# Recorded by a previous run, written exactly as render_artifact writes it:
# quoted values, secrets named by path and never by value.
install -m 600 /dev/null "$clone/hermes-notify.secret"
install -m 600 /dev/null "$clone/hermes-roster.secret"
printf 'notify-secret-value\n' >"$clone/hermes-notify.secret"
printf 'roster-secret-value\n' >"$clone/hermes-roster.secret"
cat >"$clone/runtime.env" <<RUNTIME_ENV
PAYNANI_RUNTIME="hermes"
HERMES_NOTIFY_URL="http://127.0.0.1:9/webhooks/paynani-notify"
HERMES_NOTIFY_SECRET_FILE="$clone/hermes-notify.secret"
HERMES_ROSTER_URL="http://127.0.0.1:9/webhooks/paynani-roster"
HERMES_ROSTER_SECRET_FILE="$clone/hermes-roster.secret"
HERMES_HEALTH_URL="http://127.0.0.1:9/health"
HERMES_SIGNATURE_MODE="v2"
RUNTIME_ENV

out=$(recall_run --runtime hermes --profile default --dry-run)
if [[ "$out" != *'HERMES_NOTIFY_URL is required'* ]]; then
    printf 'ok   a recorded runtime.env is enough to re-run\n'
    pass=$((pass + 1))
else
    printf 'FAIL the installer still demanded what it had already written\n%s\n' "$out"
    fail=$((fail + 1))
fi
for name in HERMES_NOTIFY_URL HERMES_ROSTER_URL HERMES_HEALTH_URL \
            HERMES_NOTIFY_SECRET_FILE HERMES_ROSTER_SECRET_FILE; do
    if [[ "$out" == *"inventory recalled=$name from=$clone/runtime.env"* ]]; then
        printf 'ok   %s is recalled, and says where from\n' "$name"
        pass=$((pass + 1))
    else
        printf 'FAIL %s was not recalled\n' "$name"
        fail=$((fail + 1))
    fi
done

# Quoting is undone rather than passed through: a value carrying its quotes
# would be a URL no request could be made to.
if [[ "$out" != *'"http://127.0.0.1:9'* ]]; then
    printf 'ok   recalled values are unquoted\n'
    pass=$((pass + 1))
else
    printf 'FAIL a recalled value kept its quotes\n'
    fail=$((fail + 1))
fi

# The environment outranks the file. An operator who names a value means it, and
# recall must not quietly overrule them.
# Spelled out rather than routed through recall_run: this one keeps a value in
# the environment, which is the whole point of the check.
out=$(env -u PAYNANI_ENV -u HERMES_ROSTER_URL -u HERMES_HEALTH_URL \
        HOME="$sandbox" HERMES_NOTIFY_URL=http://127.0.0.1:9/webhooks/chosen-by-hand \
        XDG_CONFIG_HOME="$sandbox/ignored-config" XDG_STATE_HOME="$sandbox/ignored-state" \
        FAKE_SERVICE_PATH="$fixture_bin:/usr/bin:/bin" \
        PATH="$fixture_bin:/usr/bin:/bin" \
        "$INSTALL" --runtime hermes --profile default --dry-run 2>&1)
if [[ "$out" != *'inventory recalled=HERMES_NOTIFY_URL'* &&
      "$out" == *'inventory recalled=HERMES_ROSTER_URL'* ]]; then
    printf 'ok   an explicit value outranks the recorded one\n'
    pass=$((pass + 1))
else
    printf 'FAIL recall overruled a value supplied by the operator\n%s\n' "$out"
    fail=$((fail + 1))
fi

reset_install; rm -f "$clone/hermes-notify.secret" "$clone/hermes-roster.secret"
rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"

# ---------------------------------------------------------------------------
# The SMS gateway unit (SRV-7) is optional: nothing about it is installed,
# upgraded or removed unless --with-sms asked for it or this installer already
# owns it.
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"
: >"$FAKE_SYSTEMD_LOG"
sms_unit="$sandbox/.config/systemd/user/paynani-sms.service"
# PaynaniWeb (PRD #434) goes with the gateway (#435, Q-T2-1): every check of the
# gateway below holds for it too.
web_unit="$sandbox/.config/systemd/user/paynani-web.service"

check_status '--with-sms does not apply to --uninstall' 64 --runtime codex --uninstall --with-sms
check_status 'a plain install does not plan the SMS gateway' 10 --runtime codex --dry-run
[[ "$LAST_OUTPUT" != *paynani-sms* && "$LAST_OUTPUT" != *paynani-web* ]] || {
    printf 'FAIL a dry-run without --with-sms mentioned the SMS gateway or PaynaniWeb\n'
    fail=$((fail + 1))
}
check_status 'a dry-run with --with-sms plans the SMS unit' 10 --runtime codex --dry-run --with-sms
[[ "$LAST_OUTPUT" == *paynani-sms.service* && ! -e "$sms_unit" ]] || {
    printf 'FAIL --with-sms --dry-run did not plan the unit, or wrote it\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *paynani-web.service* && ! -e "$web_unit" ]] || {
    printf 'FAIL --with-sms --dry-run did not plan the PaynaniWeb unit, or wrote it\n'
    fail=$((fail + 1))
}

check_status 'a plain install converges without the SMS gateway' 10 --runtime codex
[[ ! -e "$sms_unit" && ! -e "$web_unit" && "$(<"$clone/runtime.env")" == 'PAYNANI_RUNTIME=codex' ]] &&
    ! grep -q 'paynani-sms\|paynani-web' "$clone/install.manifest" "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL a plain install touched the SMS gateway (unit, runtime.env, manifest or services)\n'
    fail=$((fail + 1))
}
check_status 'a plain upgrade still does not install it' 0 --runtime codex --upgrade
[[ ! -e "$sms_unit" && ! -e "$web_unit" ]] || {
    printf 'FAIL an upgrade without --with-sms installed the SMS gateway or PaynaniWeb\n'
    fail=$((fail + 1))
}

# sms.env is the user's: the installer never creates, edits, records or removes it.
printf 'PAYNANI_SMS_PORT=8771\n' >"$clone/sms.env"
sms_env_bytes=$(<"$clone/sms.env")
plain_runtime_env=$(<"$clone/runtime.env")
check_status '--with-sms adds the gateway to a converged install' 10 --runtime codex --with-sms
[[ -f "$sms_unit" && "$(file_mode "$sms_unit")" == 644 ]] || {
    printf 'FAIL --with-sms did not write the unit as a 0644 file\n'
    fail=$((fail + 1))
}
if grep -q '/path/to' "$sms_unit"; then
    printf 'FAIL the rendered SMS unit still has placeholders\n'
    fail=$((fail + 1))
fi
grep -q "^ExecStart=/usr/bin/python3 $clone/scripts/sms_gateway.py\$" "$sms_unit" &&
grep -q "^EnvironmentFile=-$clone/runtime.env\$" "$sms_unit" &&
grep -q "^StandardOutput=append:$clone/state/sms.log\$" "$sms_unit" &&
grep -q "^StandardError=append:$clone/state/sms.err.log\$" "$sms_unit" || {
    printf 'FAIL the rendered SMS unit has the wrong ExecStart, EnvironmentFile or log paths\n'
    fail=$((fail + 1))
}
grep -q "$sms_unit" "$clone/install.manifest" || {
    printf 'FAIL the ownership manifest does not record the SMS unit\n'
    fail=$((fail + 1))
}
grep -q -- 'enable --now paynani-sms.service' "$FAKE_SYSTEMD_LOG" &&
grep -q -- "$sms_unit" "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL the SMS unit was not verified and enabled\n'
    fail=$((fail + 1))
}
[[ "$(<"$clone/runtime.env")" == "$plain_runtime_env" ]] || {
    printf 'FAIL --with-sms changed runtime.env: it must be identical to a plain install\n'
    fail=$((fail + 1))
}
if grep -q 'sms.env' "$clone/install.manifest"; then
    printf 'FAIL the ownership manifest records the user'"'"'s sms.env\n'
    fail=$((fail + 1))
fi
[[ "$LAST_OUTPUT" == *"verification_unit=$sandbox/.config/systemd/user/paynani-sms.service validated=true"* ]] || {
    printf 'FAIL the verification report does not list the SMS unit\n'
    fail=$((fail + 1))
}
[[ -f "$web_unit" && "$(file_mode "$web_unit")" == 644 ]] || {
    printf 'FAIL --with-sms did not write the PaynaniWeb unit as a 0644 file\n'
    fail=$((fail + 1))
}
if grep -q '/path/to' "$web_unit"; then
    printf 'FAIL the rendered PaynaniWeb unit still has placeholders\n'
    fail=$((fail + 1))
fi
grep -q "^ExecStart=/usr/bin/python3 $clone/scripts/paynani_web.py\$" "$web_unit" &&
grep -q "^EnvironmentFile=-$clone/runtime.env\$" "$web_unit" &&
grep -q "^StandardOutput=append:$clone/state/web.log\$" "$web_unit" &&
grep -q "^StandardError=append:$clone/state/web.err.log\$" "$web_unit" &&
grep -q "^RestartPreventExitStatus=2\$" "$web_unit" || {
    printf 'FAIL the rendered PaynaniWeb unit has the wrong ExecStart, EnvironmentFile, logs or restart rule\n'
    fail=$((fail + 1))
}
grep -q "$web_unit" "$clone/install.manifest" &&
grep -q -- 'enable --now paynani-web.service' "$FAKE_SYSTEMD_LOG" &&
grep -q -- "$web_unit" "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL the PaynaniWeb unit was not recorded, verified and enabled\n'
    fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *"verification_unit=$web_unit validated=true"* ]] || {
    printf 'FAIL the verification report does not list the PaynaniWeb unit\n'
    fail=$((fail + 1))
}
check_status 'the SMS gateway install is idempotent' 0 --runtime codex --with-sms

# A host that installed the gateway before PaynaniWeb existed: the manifest owns
# the gateway's unit and not PaynaniWeb's. A plain --upgrade adds it (#435).
grep -v "$web_unit" "$clone/install.manifest" >"$clone/install.manifest.tmp" &&
    cat "$clone/install.manifest.tmp" >"$clone/install.manifest" && rm -f "$clone/install.manifest.tmp"
rm -f "$web_unit" "$FAKE_SYSTEMD_STATE/paynani-web.service.enabled" "$FAKE_SYSTEMD_STATE/paynani-web.service.active"
: >"$FAKE_SYSTEMD_LOG"
check_status 'an upgrade of a host with the gateway adds PaynaniWeb' 10 --runtime codex --upgrade
[[ -f "$web_unit" ]] && grep -q "$web_unit" "$clone/install.manifest" &&
    grep -q -- 'enable --now paynani-web.service' "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL an upgrade of a host that owns the gateway did not install and enable PaynaniWeb\n'
    fail=$((fail + 1))
}

# The gateway runs send.sh for the email to the human on every roster change from
# PaynaniApp, and a user service does not get the login shell's PATH (#410). The unit
# carries Environment=PATH: the service manager's own, here the fixture's.
grep -q "^Environment=\"PATH=$fixture_bin:/usr/bin:/bin\"\$" "$sms_unit" || {
    printf 'FAIL the rendered SMS unit has no Environment=PATH with the service manager PATH\n'
    fail=$((fail + 1))
}
# With himalaya in a folder the service manager does not have, that folder goes first.
printf '#!/bin/sh\nexit 0\n' >"$fixture_bin/himalaya"
chmod 0755 "$fixture_bin/himalaya"
FAKE_SERVICE_PATH=/bin check_status \
    'an upgrade puts the folder of himalaya first in the gateway PATH' 10 --runtime codex --upgrade
grep -q "^Environment=\"PATH=$fixture_bin:/bin\"\$" "$sms_unit" || {
    printf 'FAIL the SMS unit does not start its PATH with the folder of himalaya: %s\n' \
        "$(grep '^Environment=' "$sms_unit")"
    fail=$((fail + 1))
}
rm -f "$fixture_bin/himalaya"
# Run with a PATH that does not have ~/.local/bin, the installer still finds a himalaya there.
mkdir -p "$sandbox/.local/bin"
printf '#!/bin/sh\nexit 0\n' >"$sandbox/.local/bin/himalaya"
chmod 0755 "$sandbox/.local/bin/himalaya"
check_status 'a himalaya in ~/.local/bin goes first even when the installer PATH lacks it' 10 \
    --runtime codex --upgrade
grep -q "^Environment=\"PATH=$sandbox/.local/bin:$fixture_bin:/usr/bin:/bin\"\$" "$sms_unit" || {
    printf 'FAIL the SMS unit does not put ~/.local/bin first: %s\n' "$(grep '^Environment=' "$sms_unit")"
    fail=$((fail + 1))
}
rm -rf "$sandbox/.local/bin"
check_status 'and an upgrade without it goes back to the service manager PATH' 10 --runtime codex --upgrade
grep -q "^Environment=\"PATH=$fixture_bin:/usr/bin:/bin\"\$" "$sms_unit" || {
    printf 'FAIL the SMS unit did not go back to the service manager PATH\n'
    fail=$((fail + 1))
}

check_status 'a later upgrade without the flag keeps handling the owned gateway' 0 --runtime codex --upgrade
[[ -f "$sms_unit" && "$(<"$clone/runtime.env")" == "$plain_runtime_env" ]] || {
    printf 'FAIL an upgrade without --with-sms dropped the owned SMS unit or changed runtime.env\n'
    fail=$((fail + 1))
}
[[ "$(cat "$clone/sms.env" 2>/dev/null)" == "$sms_env_bytes" ]] || {
    printf 'FAIL install or upgrade touched the user'"'"'s sms.env\n'
    fail=$((fail + 1))
}

check_status 'uninstall removes the owned SMS unit and stops it' 10 --runtime codex --uninstall
[[ ! -e "$sms_unit" && ! -e "$FAKE_SYSTEMD_STATE/paynani-sms.service.enabled" ]] &&
    grep -q -- 'disable --now paynani-sms.service' "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL uninstall left the SMS unit behind or did not stop it\n'
    fail=$((fail + 1))
}
[[ ! -e "$web_unit" && ! -e "$FAKE_SYSTEMD_STATE/paynani-web.service.enabled" ]] &&
    grep -q -- 'disable --now paynani-web.service' "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL uninstall left the PaynaniWeb unit behind or did not stop it\n'
    fail=$((fail + 1))
}
[[ "$(cat "$clone/sms.env" 2>/dev/null)" == "$sms_env_bytes" ]] || {
    printf 'FAIL uninstall removed or changed the user'"'"'s sms.env\n'
    fail=$((fail + 1))
}
rm -f "$clone/sms.env"
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"

# ---------------------------------------------------------------------------
# WhatsApp (WA-3 #555, PRD #550 FR-1, FR-3b, FR-10): like the SMS gateway, only
# with --with-whatsapp or when this installer owns the unit. Node 20+ and npm ci
# --ignore-scripts come first; whatsapp.env is written once and never recorded.
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"
: >"$FAKE_SYSTEMD_LOG"
wa_unit="$sandbox/.config/systemd/user/paynani-whatsapp.service"
npm_log="$sandbox/npm.log"
fake_node() {
    printf '#!/bin/sh\n[ "$1" = -p ] && { echo %s; exit 0; }\nexit 0\n' "$1" >"$fixture_bin/node"
    chmod 0755 "$fixture_bin/node"
}
printf '#!/bin/sh\necho "$*" >>"%s"\nexit ${FAKE_NPM_EXIT:-0}\n' "$npm_log" >"$fixture_bin/npm"
chmod 0755 "$fixture_bin/npm"

check_status '--with-whatsapp does not apply to --uninstall' 64 --runtime codex --uninstall --with-whatsapp
check_status 'a plain install does not plan WhatsApp' 10 --runtime codex --dry-run
[[ "$LAST_OUTPUT" != *paynani-whatsapp* ]] || {
    printf 'FAIL a dry-run without --with-whatsapp mentioned WhatsApp\n'; fail=$((fail + 1))
}
fake_node 22
check_status 'a dry-run with --with-whatsapp plans the unit and writes nothing' 10 --runtime codex --dry-run --with-whatsapp
[[ "$LAST_OUTPUT" == *paynani-whatsapp.service* && ! -e "$wa_unit" && ! -e "$clone/whatsapp.env" && ! -s "$npm_log" ]] || {
    printf 'FAIL --with-whatsapp --dry-run did not plan the unit, or wrote something\n'; fail=$((fail + 1))
}

# Without Node 20+ the installer downloads the release pinned in
# scripts/node_release.json into ~/.local/lib/paynani (Q197=B). Here the "release"
# is a fixture served with file://, and the clone's node_release.json pins its hash,
# so nothing goes to nodejs.org.
node_key=$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); import node_runtime as n; print(n.platform_key())' "$clone/scripts")
node_top="node-v22.23.4-$node_key"
node_dist="$fixture_root/node-dist"
node_private="$sandbox/.local/lib/paynani/$node_top/bin"
mkdir -p "$fixture_root/node-src/$node_top/bin" "$node_dist/v22.23.4"
printf '#!/bin/sh
case "$1" in --version) echo v22.23.4;; -p) echo 22;; esac
' \
    >"$fixture_root/node-src/$node_top/bin/node"
printf '#!/bin/sh
echo "private $*" >>"%s"
exit ${FAKE_NPM_EXIT:-0}
' "$npm_log" \
    >"$fixture_root/node-src/$node_top/bin/npm"
chmod 0755 "$fixture_root/node-src/$node_top/bin/node" "$fixture_root/node-src/$node_top/bin/npm"
tar -czf "$node_dist/v22.23.4/$node_top.tar.gz" -C "$fixture_root/node-src" "$node_top"
node_sha=$(sha256sum "$node_dist/v22.23.4/$node_top.tar.gz" | cut -d ' ' -f1)
cp "$clone/scripts/node_release.json" "$fixture_root/node_release.json.orig"
pin_node() {
    printf '{"version": "22.23.4", "sha256": {"%s": "%s"}}\n' "$node_key" "$1" >"$clone/scripts/node_release.json"
}
export PAYNANI_NODE_DIST="file://$node_dist"

pin_node "$node_sha"
fake_node 18
check_status 'with Node 18, a --with-whatsapp dry-run plans the pinned download' 10 --runtime codex --dry-run --with-whatsapp
[[ "$LAST_OUTPUT" == *"inventory whatsapp-node download file://$node_dist/v22.23.4/$node_top.tar.gz"* &&
   ! -e "$sandbox/.local/lib/paynani" && ! -s "$npm_log" ]] || {
    printf 'FAIL the dry-run did not plan the download, or downloaded or ran npm: %s\n' "$LAST_OUTPUT"; fail=$((fail + 1))
}
pin_node 0000000000000000000000000000000000000000000000000000000000000000
check_status 'a Node archive with another hash stops before writing anything' 78 --runtime codex --with-whatsapp
[[ "$LAST_OUTPUT" == *'SHA-256'* && ! -e "$wa_unit" && ! -e "$clone/whatsapp.env" && ! -s "$npm_log" &&
   -z "$(ls -A "$sandbox/.local/lib/paynani" 2>/dev/null)" ]] || {
    printf 'FAIL a hash mismatch did not stop cleanly: %s\n' "$LAST_OUTPUT"; fail=$((fail + 1))
}
pin_node "$node_sha"
check_status 'with Node 18, --with-whatsapp downloads the pinned Node and installs' 10 --runtime codex --with-whatsapp
[[ -x "$node_private/node" && "$(file_mode "$sandbox/.local/lib/paynani")" == 700 && -f "$wa_unit" ]] &&
    grep -q "^private ci --ignore-scripts --no-audit --no-fund --prefix $clone/scripts/whatsapp_bridge\$" "$npm_log" || {
    printf 'FAIL the pinned Node was not installed and used for npm ci: %s\n' "$(cat "$npm_log")"; fail=$((fail + 1))
}
grep -q "^Environment=\"PATH=$node_private:" "$wa_unit" || {
    printf 'FAIL the WhatsApp unit does not start its PATH with the pinned Node: %s\n' \
        "$(grep '^Environment=' "$wa_unit")"; fail=$((fail + 1))
}
: >"$npm_log"
check_status 'a second run uses the downloaded Node without downloading again' 0 --runtime codex --with-whatsapp
mv "$node_dist/v22.23.4/$node_top.tar.gz" "$fixture_root/node.tar.gz.away"
check_status 'and keeps working without the archive' 0 --runtime codex --with-whatsapp
mv "$fixture_root/node.tar.gz.away" "$node_dist/v22.23.4/$node_top.tar.gz"
cp "$fixture_root/node_release.json.orig" "$clone/scripts/node_release.json"
unset PAYNANI_NODE_DIST
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"
: >"$FAKE_SYSTEMD_LOG"; : >"$npm_log"; rm -f "$clone/whatsapp.env"

fake_node 22
FAKE_NPM_EXIT=1 check_status 'a failed npm ci stops before writing a unit' 78 --runtime codex --with-whatsapp
[[ ! -e "$wa_unit" ]] || { printf 'FAIL a failed npm ci still wrote the unit\n'; fail=$((fail + 1)); }
: >"$npm_log"

check_status 'a plain install first, to compare the other units against' 10 --runtime codex
: >"$npm_log"
: >"$FAKE_SYSTEMD_LOG"
units_before=$(cd "$sandbox/.config/systemd/user" && sha256sum paynani-idle.service paynani-dispatch.service paynani-logrotate.timer)
check_status '--with-whatsapp installs the service' 10 --runtime codex --with-whatsapp
[[ "$(cd "$sandbox/.config/systemd/user" && sha256sum paynani-idle.service paynani-dispatch.service paynani-logrotate.timer)" == "$units_before" ]] || {
    printf 'FAIL adding WhatsApp changed another unit file\n'; fail=$((fail + 1))
}
# What #567 promises, and no more: the other unit FILES stay byte for byte the same,
# but adding a unit restarts every enabled paynani service (runtime_filesystem_changed
# is global, the same as when --with-sms adds the gateway). Pinned so a change to
# that granularity is a deliberate one.
grep -qx -- '--user restart paynani-idle.service' "$FAKE_SYSTEMD_LOG" &&
grep -qx -- '--user restart paynani-dispatch.service' "$FAKE_SYSTEMD_LOG" &&
grep -qx -- '--user enable --now paynani-whatsapp.service' "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL adding WhatsApp did not enable it and restart the other enabled services as documented: %s\n' \
        "$(grep -E 'restart|enable' "$FAKE_SYSTEMD_LOG" | tr '\n' ';')"; fail=$((fail + 1))
}
[[ -f "$wa_unit" && "$(file_mode "$wa_unit")" == 644 ]] && ! grep -q '/path/to' "$wa_unit" || {
    printf 'FAIL --with-whatsapp did not write a rendered 0644 unit\n'; fail=$((fail + 1))
}
grep -q "^ExecStart=/usr/bin/python3 $clone/scripts/whatsapp_service.py\$" "$wa_unit" &&
grep -q "^StandardOutput=append:$clone/state/whatsapp.log\$" "$wa_unit" &&
grep -q "^UMask=0077\$" "$wa_unit" || {
    printf 'FAIL the rendered WhatsApp unit has the wrong ExecStart, log or UMask\n'; fail=$((fail + 1))
}
grep -q -- "ci --ignore-scripts --no-audit --no-fund --prefix $clone/scripts/whatsapp_bridge" "$npm_log" || {
    printf 'FAIL npm ci --ignore-scripts was not run for the bridge: %s\n' "$(cat "$npm_log")"; fail=$((fail + 1))
}
[[ -f "$clone/whatsapp.env" && "$(file_mode "$clone/whatsapp.env")" == 600 ]] &&
    grep -qx 'WHATSAPP_ENABLED=1' "$clone/whatsapp.env" || {
    printf 'FAIL whatsapp.env was not written 0600 with WHATSAPP_ENABLED=1\n'; fail=$((fail + 1))
}
grep -q "$wa_unit" "$clone/install.manifest" &&
grep -q -- 'enable --now paynani-whatsapp.service' "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL the WhatsApp unit was not recorded and enabled\n'; fail=$((fail + 1))
}
if grep -q 'whatsapp.env\|whatsapp/auth' "$clone/install.manifest"; then
    printf 'FAIL install.manifest records whatsapp.env or the account keys (FR-10)\n'; fail=$((fail + 1))
fi
[[ "$LAST_OUTPUT" == *"verification_unit=$wa_unit validated=true"* ]] || {
    printf 'FAIL the verification report does not list the WhatsApp unit\n'; fail=$((fail + 1))
}
# The bridge needs the Node this shell finds (node with npm next to it, as nvm and
# Homebrew have them); only the WhatsApp unit gets its folder.
mkdir -p "$sandbox/node/bin" && mv "$fixture_bin/node" "$fixture_bin/npm" "$sandbox/node/bin/"
PATH_EXTRA="$sandbox/node/bin" check_status 'an upgrade puts the folder of node first in the WhatsApp PATH' 10 \
    --runtime codex --upgrade
grep -q "^Environment=\"PATH=$sandbox/node/bin:$fixture_bin:/usr/bin:/bin\"\$" "$wa_unit" || {
    printf 'FAIL the WhatsApp unit does not start its PATH with the folder of node: %s\n' \
        "$(grep '^Environment=' "$wa_unit")"; fail=$((fail + 1))
}
mv "$sandbox/node/bin/node" "$sandbox/node/bin/npm" "$fixture_bin/"
[[ ! -e "$sandbox/.local/lib/paynani" ]] || {
    printf 'FAIL an install with a usable Node downloaded Node anyway\n'; fail=$((fail + 1))
}
check_status 'back to the plain PATH' 10 --runtime codex --upgrade

# whatsapp.env is the owner's after the first write: never rewritten, never removed.
printf 'WHATSAPP_ENABLED=0\n' >"$clone/whatsapp.env"
check_status 'the WhatsApp install is idempotent and keeps whatsapp.env' 0 --runtime codex --with-whatsapp
[[ "$(<"$clone/whatsapp.env")" == 'WHATSAPP_ENABLED=0' ]] || {
    printf 'FAIL an install rewrote the owner'"'"'s whatsapp.env\n'; fail=$((fail + 1))
}
check_status 'a later upgrade without the flag keeps handling the owned unit' 0 --runtime codex --upgrade
[[ -f "$wa_unit" ]] || { printf 'FAIL an upgrade dropped the owned WhatsApp unit\n'; fail=$((fail + 1)); }
check_status 'uninstall removes the owned WhatsApp unit and stops it' 10 --runtime codex --uninstall
[[ ! -e "$wa_unit" ]] && grep -q -- 'disable --now paynani-whatsapp.service' "$FAKE_SYSTEMD_LOG" &&
    [[ -f "$clone/whatsapp.env" ]] || {
    printf 'FAIL uninstall left the WhatsApp unit, did not stop it, or removed whatsapp.env\n'; fail=$((fail + 1))
}
rm -f "$fixture_bin/node" "$fixture_bin/npm" "$npm_log" "$clone/whatsapp.env"; rm -rf "$sandbox/node"
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"

# ---------------------------------------------------------------------------
# Telegram (TG-6 of #612, PRD #609 FR-1): only with --with-telegram or when this
# installer owns the unit. No Node and nothing downloaded. The token is never the
# installer's: without telegram.env the unit is enabled but left stopped.
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"
: >"$FAKE_SYSTEMD_LOG"
tg_unit="$sandbox/.config/systemd/user/paynani-telegram.service"
tg_env="$clone/telegram.env"
rm -f "$tg_env"
check_status '--with-telegram does not apply to --uninstall' 64 --runtime codex --uninstall --with-telegram
check_status 'a plain dry-run plans Telegram too (#635, Q281 = A)' 10 --runtime codex --dry-run
[[ "$LAST_OUTPUT" == *paynani-telegram* ]] || {
    printf 'FAIL a dry-run without --with-telegram did not plan Telegram (#635)\n'; fail=$((fail + 1))
}
check_status 'a dry-run with --with-telegram plans the unit and writes nothing' 10 --runtime codex --dry-run --with-telegram
[[ "$LAST_OUTPUT" == *paynani-telegram.service* && ! -e "$tg_unit" && ! -e "$tg_env" ]] || {
    printf 'FAIL --with-telegram --dry-run did not plan the unit, or wrote something\n'; fail=$((fail + 1))
}
check_status '--with-telegram without telegram.env installs the unit and leaves it stopped' 10 \
    --runtime codex --with-telegram
[[ -f "$tg_unit" && "$(file_mode "$tg_unit")" == 644 ]] && ! grep -q '/path/to' "$tg_unit" || {
    printf 'FAIL --with-telegram did not write a rendered 0644 unit\n'; fail=$((fail + 1))
}
grep -q "^ExecStart=/usr/bin/python3 $clone/scripts/telegram_service.py\$" "$tg_unit" &&
grep -q "^StandardOutput=append:$clone/state/telegram.log\$" "$tg_unit" &&
grep -q '^Restart=on-failure$' "$tg_unit" && grep -q '^UMask=0077$' "$tg_unit" &&
grep -q '^Environment="PATH=' "$tg_unit" || {
    printf 'FAIL the rendered Telegram unit has the wrong ExecStart, log, Restart, UMask or PATH\n'; fail=$((fail + 1))
}
grep -qx -- '--user enable paynani-telegram.service' "$FAKE_SYSTEMD_LOG" &&
! grep -q -- 'enable --now paynani-telegram.service' "$FAKE_SYSTEMD_LOG" &&
[[ ! -e "$FAKE_SYSTEMD_STATE/paynani-telegram.service.active" ]] || {
    printf 'FAIL without telegram.env the unit was not enabled-and-stopped: %s\n' \
        "$(grep telegram "$FAKE_SYSTEMD_LOG" | tr '\n' ';')"; fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" == *'service=paynani-telegram.service state=enabled-waiting-setup next="paynani telegram setup"'* &&
   "$LAST_OUTPUT" == *"verification_unit=$tg_unit validated=true"* ]] || {
    printf 'FAIL the report does not say Telegram waits for setup, or does not list its unit\n'; fail=$((fail + 1))
}
[[ ! -e "$tg_env" ]] && grep -q "$tg_unit" "$clone/install.manifest" &&
! grep -q 'telegram.env' "$clone/install.manifest" || {
    printf 'FAIL the installer wrote or recorded telegram.env, or did not record the unit\n'; fail=$((fail + 1))
}
# After `paynani telegram setup`: the next run starts it and requires it active.
(umask 077 && printf 'TELEGRAM_ENABLED=1\nTELEGRAM_TOKEN=123456789:fake_token_only_for_tests_x\n' >"$tg_env")
: >"$FAKE_SYSTEMD_LOG"
check_status 'with telegram.env, an upgrade starts the Telegram service' 10 --runtime codex --upgrade
grep -qx -- '--user restart paynani-telegram.service' "$FAKE_SYSTEMD_LOG" &&
[[ "$LAST_OUTPUT" == *'service=paynani-telegram.service state=enabled-active restarted=true'* ]] || {
    printf 'FAIL with telegram.env the Telegram service was not started\n'; fail=$((fail + 1))
}
[[ "$LAST_OUTPUT" != *fake_token_only_for_tests_x* ]] || {
    printf 'FAIL the installer printed the Telegram token\n'; fail=$((fail + 1))
}
check_status 'a second run with nothing new leaves it running' 0 --runtime codex --upgrade
[[ "$LAST_OUTPUT" == *'service=paynani-telegram.service state=enabled-active'* ]] || {
    printf 'FAIL an idempotent run did not report Telegram active\n'; fail=$((fail + 1))
}
# `paynani telegram disable` leaves TELEGRAM_ENABLED=0: the installer stops it again.
(umask 077 && printf 'TELEGRAM_ENABLED=0\nTELEGRAM_TOKEN=123456789:fake_token_only_for_tests_x\n' >"$tg_env")
: >"$FAKE_SYSTEMD_LOG"
check_status 'disabled in telegram.env: the unit is stopped, the run still passes' 0 --runtime codex --upgrade
grep -qx -- '--user stop paynani-telegram.service' "$FAKE_SYSTEMD_LOG" &&
[[ "$LAST_OUTPUT" == *'state=enabled-waiting-setup'* ]] || {
    printf 'FAIL a disabled Telegram was not stopped\n'; fail=$((fail + 1))
}
check_status 'uninstall removes the owned Telegram unit and keeps telegram.env' 10 --runtime codex --uninstall
[[ ! -e "$tg_unit" && -f "$tg_env" ]] && grep -q -- 'disable --now paynani-telegram.service' "$FAKE_SYSTEMD_LOG" || {
    printf 'FAIL uninstall left the Telegram unit, did not stop it, or removed telegram.env\n'; fail=$((fail + 1))
}
rm -f "$tg_env"
reset_install; rm -rf "$FAKE_SYSTEMD_STATE"; mkdir -p "$FAKE_SYSTEMD_STATE"

printf '
%d passed, %d failed
' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
