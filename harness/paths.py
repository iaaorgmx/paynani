#!/usr/bin/env python3
"""
Where this install keeps its files, decided in one place.

Everything lives in one directory, and that directory is the clone. So
"install it wherever you want" is answered by cloning where you want, and
nothing here has to be told where anything is: every consumer of this module
lives inside the clone and can find itself.

Recommended clone locations, by runtime — recommendations, not requirements,
because nothing in this file checks them:

    OpenClaw       ~/.openclaw/workspace/paynani
    Hermes Agent   ~/.hermes/workspace/paynani

The rule is deliberately boring, and it is the whole rule:

1. `PAYNANI_ENV` and `PAYNANI_STATE`, when set, win for the one file or tree
   they name. An install that said where its credentials or its state live
   meant it, and nothing here second-guesses that.
2. A harness keeps its agent's mail credentials in the workspace folder of its
   own installation directory — `~/.openclaw/workspace/.env`,
   `~/.hermes/workspace/.env` — and this reads that file where it lies. Only the
   credentials; state, `runtime.env`, the manifest and `hermes/` still hang off
   the clone. The harness owns that file, this project does not, and a password
   copied to a second location is a second thing to leak.
3. Otherwise everything hangs off the clone.

Nothing here creates, moves, or reads a file. It answers questions.
"""

import os
from pathlib import Path

# Every harness keeps its agent's mail credentials in the workspace folder of
# its own installation directory. That is the operator-facing rule, it is what
# the install prompt tells an agent, and it is one pattern rather than a list of
# special cases — a new runtime is a new root here and nothing else.
#
# Matched exactly, and only these names. `~/.hermes/.env` is Hermes' own
# configuration and holds its gateway token; adopting a file because it is
# nearby and mail-shaped is how an install reads credentials it was never given.
# scripts/test_paths.sh pins that one.
#
# The OpenClaw entry is an instance of the rule, not an exception to it.
HARNESS_ROOTS = ("~/.openclaw", "~/.hermes", "~/.claude")
HARNESS_ENV_RELATIVE = "workspace/.env"

def _under(relative, home=None):
    if home is None:
        return Path(relative).expanduser()
    return Path(home) / relative.replace("~/", "", 1)


def repo_root():
    """
    This checkout, found from this file.

    It used to be a hard-coded `~/.openclaw/workspace/paynani`, which is
    wrong everywhere except one harness and silently wrong at that: the session
    hook swallows its own errors so a session never blocks, so a clone anywhere
    else produced no version line, no pending mail, and no complaint.
    """
    return Path(__file__).resolve().parent.parent


def install_root(environ=None, home=None):
    """
    The single directory this install owns.

    Always the clone.
    """
    return repo_root()


def harness_env_files(home=None):
    """
    The harness credential files that exist on this host, in `HARNESS_ROOTS`
    order.

    A list rather than a single answer, because how many there are is what
    decides whether one can be used — see `env_file()`.
    """
    found = []
    for root in HARNESS_ROOTS:
        candidate = _under(root, home) / HARNESS_ENV_RELATIVE
        if candidate.is_file() or candidate.is_symlink():
            found.append(candidate)
    return found


def config_dir(environ=None, home=None):
    """Where `runtime.env`, `install.manifest` and `hermes/` live."""
    return install_root(environ, home)


def env_file(environ=None, home=None):
    """The credentials file this host should use, existing or not."""
    environ = os.environ if environ is None else environ

    override = (environ.get("PAYNANI_ENV") or "").strip()
    if override:
        return Path(override).expanduser()

    # Read the harness's file where it lies. Everything else — state,
    # runtime.env, the manifest, hermes/ — still hangs off the clone, and that
    # split is deliberate: the harness owns this file, this project does not,
    # and moving or copying it to satisfy the single-root convention would put
    # a second copy of a password on the disk.
    harness = harness_env_files(home)
    if len(harness) == 1:
        return harness[0]
    # Two of them means two agents share this host. Either could be the wrong
    # mailbox, and a listener on the wrong mailbox is indistinguishable from a
    # quiet one — so neither is adopted, and the answer falls back to the file
    # this install owns. Name the right one with PAYNANI_ENV.
    return install_root(environ, home) / ".env"


def state_dir(environ=None, home=None):
    """The queue state, cursors and logs."""
    environ = os.environ if environ is None else environ

    override = (environ.get("PAYNANI_STATE") or "").strip()
    if override:
        return Path(override).expanduser()

    return install_root(environ, home) / "state"


def runtime_env(environ=None, home=None):
    """The generated, installer-owned runtime configuration."""
    return config_dir(environ, home) / "runtime.env"


def manifest(environ=None, home=None):
    """The ownership manifest: what the installer may remove."""
    return config_dir(environ, home) / "install.manifest"


def hermes_dir(environ=None, home=None):
    """Where the two Hermes route secrets live."""
    return config_dir(environ, home) / "hermes"


ROSTER_NAME = "roster.md"


def roster(environ=None, home=None):
    """
    Who this agent may write to unattended.

    Always in the clone, and a `git pull` must never be able to change this
    list — see .gitignore. One name, `roster.md`: an allowlist resolved from
    two possible filenames is an allowlist that can be edited in the file
    nothing reads, and an empty allowlist does not announce itself — sending
    refuses everyone and inbound mail stops being tagged `roster`, which looks
    exactly like nobody having written.
    """
    return repo_root() / ROSTER_NAME


if __name__ == "__main__":
    import sys

    what = sys.argv[1] if len(sys.argv) > 1 else "env"
    answers = {
        "env": env_file,
        "state": state_dir,
        "root": install_root,
        "config": config_dir,
        "runtime-env": runtime_env,
        "manifest": manifest,
        "hermes": hermes_dir,
        "roster": roster,
    }
    if what not in answers:
        print(f"unknown path: {what}", file=sys.stderr)
        raise SystemExit(2)
    print(answers[what]())
