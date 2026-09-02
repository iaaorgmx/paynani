#!/usr/bin/env bash
# Serve the mailbox setup form, so a human who does not use a terminal can give
# this agent an account.
#
#   scripts/setup_web.sh [port]
#
# Binds 127.0.0.1 only. Prints a link containing a one-time key, and stops when
# you press Ctrl-C or when the env file has been written.
#
# The agent runs this. The human opens the link.

set -euo pipefail

PORT="${1:-8765}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# The paths are resolved here and handed to the server below, so the form and
# the tools it is configuring cannot disagree about which files matter. The rule
# lives in harness/paths.py; envpath.sh is the shell half of it.
# shellcheck source=envpath.sh
. "$ROOT/scripts/envpath.sh"
STATE="$(paynani_state_dir)"
TOKEN_FILE="$STATE/setup.token"
LOG="$STATE/setup-web.log"

php_bin=""
for candidate in php8.3 php8 php; do
    if command -v "$candidate" >/dev/null 2>&1; then
        php_bin="$candidate"
        break
    fi
done

if [ -z "$php_bin" ]; then
    echo "No PHP found. This page needs PHP 8.1 or newer:" >&2
    echo "  sudo apt-get install -y php8.3-cli" >&2
    exit 1
fi

# 8.1 is where enums and readonly landed; the code here needs 8.1 semantics and
# is developed against 8.3. Below that it parses and then misbehaves, which is
# worse than refusing.
version=$("$php_bin" -r 'echo PHP_MAJOR_VERSION * 100 + PHP_MINOR_VERSION;')
if [ "$version" -lt 801 ]; then
    echo "$php_bin is too old ($("$php_bin" -r 'echo PHP_VERSION;')). Need 8.1 or newer." >&2
    exit 1
fi

mkdir -p "$STATE"
chmod 700 "$STATE" 2>/dev/null || true

# A new key every run. An old link stops working the moment this restarts, which
# is the behaviour you want from something that writes a password to disk.
if command -v openssl >/dev/null 2>&1; then
    token=$(openssl rand -hex 24)
else
    token=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
fi

umask 077
printf '%s\n' "$token" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

# The built-in server writes a line per request to stderr, including the query
# string — which carries the key on the first click. Keep that out of the
# terminal and out of any shared log, in a file only this account can read.
: > "$LOG"
chmod 600 "$LOG"

cleanup() {
    rm -f "$TOKEN_FILE"
    if [ -n "${server_pid:-}" ] && kill -0 "$server_pid" 2>/dev/null; then
        kill "$server_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

PAYNANI_ENV="${PAYNANI_ENV:-$(paynani_env_file)}"
export PAYNANI_ENV
# The form writes its own token check against this tree, so it must be told the
# same answer rather than resolving it again from a different working directory.
PAYNANI_STATE="${PAYNANI_STATE:-$STATE}"
export PAYNANI_STATE

"$php_bin" -S "127.0.0.1:$PORT" -t "$ROOT/webapp" >>"$LOG" 2>&1 &
server_pid=$!

sleep 1
if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "The server did not start. Port $PORT may already be in use." >&2
    echo "Try:  scripts/setup_web.sh 8766" >&2
    exit 1
fi

url="http://127.0.0.1:$PORT/?t=$token"

cat <<EOF

  paynani — mailbox setup
  ────────────────────────────────────────────────────────────

  Send this link to whoever is setting up the mailbox:

      $url

  If they are not sitting at this machine, they run this first,
  on their own computer, and then open the same link there:

      ssh -L $PORT:127.0.0.1:$PORT $(id -un)@$(hostname -f 2>/dev/null || hostname)

  (that host name is this machine's idea of itself — replace it
   with whatever you normally ssh to, if they differ)

  The link works once, until this stops. Ctrl-C when finished.
  Server log: $LOG

EOF

# Stop once the file has been written. Compare against how it looked at startup
# rather than merely checking that it exists — this gets run again to *change*
# settings, and an existing file would otherwise end the script before the page
# had been opened.
target="$PAYNANI_ENV"
fingerprint() { [ -e "$target" ] && cat "$target" 2>/dev/null | cksum || echo absent; }
before=$(fingerprint)

while kill -0 "$server_pid" 2>/dev/null; do
    if [ "$(fingerprint)" != "$before" ]; then
        sleep 2   # let the confirmation page finish rendering
        echo "  Settings saved to $target — stopping."
        echo
        exit 0
    fi
    sleep 1
done
