#!/usr/bin/env bash
# Regression boundary for the first FR7 installer skeleton: it must be runnable,
# reject ambiguous input, and keep dry-run free of host and runtime side effects.

set -uo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
pass=0
fail=0

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
        PATH="$fixture_bin:/usr/bin:/bin" \
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
before=$(python3 -c 'from pathlib import Path; print(sorted(str(p) for p in Path("'$sandbox'").rglob("*")))')

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
check_status 'non-interactive cannot leak into OpenClaw flow' 64 \
    --runtime openclaw --non-interactive
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


# A fresh filesystem-only OpenClaw convergence creates each managed artifact,
# then atomically records ownership, verifies the installed units, proves the
# runtime through the user manager, and converges only required service state.
check_status 'fresh OpenClaw convergence creates managed artifacts' 10 \
    --runtime openclaw
manifest="$clone/install.manifest"
runtime_env="$clone/runtime.env"
[[ -f "$manifest" && ! -L "$manifest" && "$(stat -c %a "$manifest")" == 600 ]] || {
    printf 'FAIL ownership manifest is not a mode-0600 regular file\n'
    fail=$((fail + 1))
}
[[ "$(stat -c %a "$runtime_env")" == 600 ]] || {
    printf 'FAIL generated runtime configuration is not mode 0600\n'
    fail=$((fail + 1))
}
# systemd does not create the parent of a StandardOutput=append: path, it fails
# the unit. An install that converged the units and enabled them without this
# directory leaves both services dead, and the only symptom is a quiet mailbox.
[[ -d "$state_tree" && ! -L "$state_tree" && "$(stat -c %a "$state_tree")" == 700 ]] || {
    printf 'FAIL convergence did not create the state tree as a mode-0700 directory\n'
    fail=$((fail + 1))
}
[[ "$(grep -c '^artifact[[:space:]]' "$manifest")" == 5 ]] || {
    printf 'FAIL manifest does not record exactly five created artifacts\n'
    fail=$((fail + 1))
}
[[ "$(<"$runtime_env")" == 'PAYNANI_RUNTIME=openclaw' ]] || {
    printf 'FAIL generated runtime configuration selects OpenClaw\n'
    fail=$((fail + 1))
}
for unit in paynani-idle.service paynani-dispatch.service \
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
[[ "$(grep -c '^artifact[[:space:]]' "$manifest")" == 5 ]] || {
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
for unit in paynani-idle.service paynani-dispatch.service \
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

after=$(python3 -c 'from pathlib import Path; print(sorted(str(p) for p in Path("'$sandbox'").rglob("*")))')
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

printf '
%d passed, %d failed
' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
