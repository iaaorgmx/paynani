#!/usr/bin/env python3
"""
What has to restart after a pull, computed rather than remembered.

    upgrade_plan.py                 installed tag -> newest local tag
    upgrade_plan.py --to REF        installed tag -> REF (a tag, origin/main, ...)
    upgrade_plan.py --from REF --to REF
    upgrade_plan.py --json          the same plan as one JSON object

Exit: 0 plan printed, 2 the plan could not be computed (and says why), 64 usage.

The CHANGELOG used to carry a "restart the listener" sentence when whoever wrote
the entry remembered that `scripts/idle_listener.py` had moved. The 0.7.0 entry
needed a `git diff` by hand to learn that `harness/dispatch.py` had changed and
the dispatcher wanted a restart, and ten hosts upgrading that night each decided
on their own what to restart (#167). The information is mechanical: which files
changed between the two versions, and which long-running process or copied
artifact loads each one. This script owns the second half as a table, so the
first half is `git diff --name-only` and nothing else.

Every changed file lands in exactly one of these verbs:

    restart               a running service reads it at start; restart the service
    reinstall-and-restart a copy of it lives outside the clone (systemd unit,
                          LaunchAgent, OpenCode plugin shim); re-run the
                          installer, then restart
    restart-runtime       the harness itself loads it at start (OpenCode plugin);
                          close and reopen the harness
    next-session          read when a session starts or a watch is armed; the
                          next session gets it, nothing to restart now
    none                  read on every call, or not executed at all (docs,
                          tests, translations)
    unknown               not in the table; this script does not know

`unknown` is a verb, not a gap. So is "could not compute": with the installed
tag or the target ref missing from this clone there is no diff to read, and the
answer is that, never "nothing needs a restart". The absence of data must not
read like the presence of good news (#167, Ocelotl).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import paths as harness_paths  # noqa: E402

VERBS = ("restart", "reinstall-and-restart", "restart-runtime", "next-session",
         "none", "unknown")

# What loads each file. Order matters: the first matching rule wins, so the
# specific rules go before the catch-alls. A rule is (regex on the repo-relative
# path, verb, loader label, systemd unit or None, launchd label or None, scope,
# command). Scope is None for every host, or a set of runtime names and/or
# "Darwin"/"Linux" for the hosts the file matters on; elsewhere the line is
# shown but not acted on. Command is what re-copies a `reinstall-and-restart`
# file: None means the installer itself; a string is the registration step the
# installer deliberately leaves to the agent, the OpenCode plugin shim, the two
# session hooks and the OpenClaw standing rule. Those are copies too, and a
# plan that collapsed all of them into `install.sh --upgrade` announced a
# reinstallation it never carried out (Ocelotl, PR #185).
#
# The listener and the dispatcher are long-running: `idle_listener.py` imports
# roster.py, event.py and paths.py; dispatch.py imports the adapters, event.py
# and paths.py through importlib. Both are read once at start.
LISTENER = ("paynani-idle.service", "com.paynani.idle")
DISPATCHER = ("paynani-dispatch.service", "com.paynani.dispatch")
INSTALLER = None
OPENCODE_PLUGIN = "python3 scripts/opencode_plugin.py --install"
OPENCODE_RESTART = "OpenCode (close and reopen it)"
RULES = (
    # Copies that live outside the clone: templates and the installers that
    # write them. `install.sh --upgrade` converges every artifact it owns.
    (r"^systemd/", "reinstall-and-restart", "systemd units (copied)", None, None, {"Linux"}, INSTALLER),
    (r"^scripts/install_macos\.py$", "reinstall-and-restart", "LaunchAgents (written by the installer)", None, None, {"Darwin"}, INSTALLER),
    (r"^scripts/(install\.sh|install_manifest\.py)$", "reinstall-and-restart", "the installer", None, None, None, INSTALLER),
    # Copies the installer names but does not write: each has its own command.
    (r"^scripts/opencode_plugin\.py$|^harness/opencode/.*\.js$", "reinstall-and-restart", "OpenCode plugin (~/.config/opencode/plugins/paynani.js)", None, None, {"opencode"}, OPENCODE_PLUGIN),
    (r"^scripts/claude_hook\.py$", "reinstall-and-restart", "Claude Code session hook (settings.json)", None, None, {"claudecode"}, "python3 scripts/claude_hook.py --install"),
    (r"^scripts/codex_hook\.py$", "reinstall-and-restart", "Codex session hooks", None, None, {"codex"}, "python3 scripts/codex_hook.py --install"),
    (r"^scripts/openclaw_rules\.py$", "reinstall-and-restart", "OpenClaw standing rule (~/.openclaw/workspace/AGENTS.md)", None, None, {"openclaw"}, "python3 scripts/openclaw_rules.py --install"),
    # Long-running services.
    (r"^scripts/idle_listener\.py$", "restart", "listener", *LISTENER, None, None),
    (r"^scripts/roster\.py$", "restart", "listener", *LISTENER, None, None),
    (r"^harness/dispatch\.py$", "restart", "dispatcher", *DISPATCHER, None, None),
    (r"^harness/adapters/.*\.py$", "restart", "dispatcher", *DISPATCHER, None, None),
    (r"^harness/(event|paths|ledger)\.py$", "restart", "listener and dispatcher", "both", "both", None, None),
    # Read when a session starts or a watch is armed.
    (r"^harness/(session_start\.py|session_watch\.sh)$", "next-session", "session hook and watcher", None, None, {"claudecode", "codex"}, None),
    # Runs fresh on every timer tick or every call.
    (r"^harness/rotate_logs\.py$", "none", "logrotate (runs fresh on each timer tick)", None, None, None, None),
    (r"^harness/capabilities\.py$", "none", "capability data (read on each call)", None, None, None, None),
    (r"^scripts/test_.*|^harness/.*\.test\.mjs$|^harness/opencode/.*\.test\..*$", "none", "tests", None, None, None, None),
    (r"^scripts/paynani_lib/|^scripts/paynani$|^scripts/.*\.(sh|py)$", "none", "command-line scripts (read on each call)", None, None, None, None),
    (r"^(i18n/|\.github/|examples/)|\.md$|^VERSION$|^LICENSE$|^\.gitignore$|^roster\.md\.example$", "none", "documentation and repository files", None, None, None, None),
)

VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def git(*args, repo=ROOT, strip=True):
    """Run git in the clone; return (returncode, stdout) and never raise."""
    try:
        run = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return run.returncode, run.stdout.strip() if strip else run.stdout


def installed_version(repo=ROOT):
    try:
        text = (repo / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if VERSION_RE.match(text) else None


def version_key(tag):
    return tuple(int(part) for part in tag[1:].split("."))


def local_tags(repo=ROOT):
    code, out = git("tag", "--list", "v*", repo=repo)
    if code != 0:
        return []
    return sorted((t for t in out.splitlines() if VERSION_RE.match(t[1:])), key=version_key)


def ref_exists(ref, repo=ROOT):
    code, _ = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", repo=repo)
    return code == 0


def classify(path, runtime=None, system=None):
    """
    One file -> one verb. `here` is False when the rule is for another runtime
    or another OS: the line still prints, so nobody wonders why a file that
    changed is missing, but it adds nothing to the commands for this host.
    """
    for pattern, verb, loader, unit, label, scope, command in RULES:
        if re.search(pattern, path):
            here = True
            if scope is not None:
                here = (system in scope) or (runtime in scope)
                if runtime is None and system not in scope and not (scope & {"Linux", "Darwin"}):
                    here = None  # runtime unknown: cannot say, so keep it in the commands
            return {"path": path, "verb": verb, "loader": loader,
                    "unit": unit, "label": label, "here": here, "command": command}
    return {"path": path, "verb": "unknown", "loader": "not in the table",
            "unit": None, "label": None, "here": True, "command": None}


def selected_runtime(repo=ROOT):
    """The runtime this host installed, from runtime.env; None when unknown."""
    env = os.environ.get("PAYNANI_RUNTIME")
    if env and env != "auto":
        return env
    try:
        text = harness_paths.runtime_env().read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^PAYNANI_RUNTIME=(\S+)", text, re.M)
    return match.group(1) if match else None


def manifest_path(repo=ROOT):
    """
    The ownership manifest of this clone. `harness.paths.manifest()` resolves
    it for the clone this file lives in; another repo (the tests') keeps it at
    the same place relative to its root.
    """
    if pathlib.Path(repo) == ROOT:
        return harness_paths.manifest()
    return pathlib.Path(repo) / "install.manifest"


def read_manifest(repo=ROOT):
    """
    ("present", lines) when the installer's manifest is readable, else
    ("absent", reason) or ("unreadable", reason).

    Read on every plan, whether or not a copied file changed. Requirement 2 of
    #167 is that missing data is never reported as "nothing to restart", and
    the manifest is the data that says which copies outside the clone this
    install owns. Without it the plan cannot know what `install.sh --upgrade`
    would converge, so it refuses to be a plan at all (Ocelotl, PR #185).
    """
    path = manifest_path(repo)
    try:
        return "present", path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return "absent", (f"no install manifest at {path}: the installer never ran here, "
                          "or this is a manual install")
    except OSError as exc:
        return "unreadable", f"install manifest at {path} could not be read: {exc}"


def manifest_drift(lines):
    """
    Artifacts the installer copied whose bytes no longer match the manifest.

    A unit somebody edited by hand is not going to be converged by
    `install.sh --upgrade` without losing that edit, so the operator has to know
    before running it. Returned as a list of (path, reason).
    """
    drift = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 4 or fields[0] != "artifact" or fields[1] != "file":
            continue
        target, digest = pathlib.Path(fields[2]), fields[3]
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            drift.append((str(target), "recorded in the manifest but missing"))
            continue
        if actual != digest:
            drift.append((str(target), "modified since the installer wrote it"))
    return drift


def overlays(from_ref, to_ref, repo=ROOT):
    """
    Tracked files modified in this clone, and whether the upgrade touches them.

    Lisa's host had two: `send.sh` and `test_roster.sh` carrying a local
    signature feature. A pull onto a modified tracked file either fails or
    merges, and the operator finds out mid-upgrade. Ignored files (`roster.md`,
    `.env`, `state/`) are the install's own data, not overlays: git status
    without untracked files never lists them, so they cannot dirty this list or
    block anything. Returned as [{path, status, upstream_changed}], where
    upstream_changed means the same file also differs between the two refs,
    which is where a conflict comes from.
    """
    # Unstripped: porcelain's first column is the index status, and a leading
    # space there is data. Stripping it once turned "scripts/x" into "cripts/x".
    code, out = git("status", "--porcelain", "--untracked-files=no", repo=repo, strip=False)
    if code != 0:
        return []
    _, diff = git("diff", "--name-only", from_ref, to_ref, repo=repo)
    upstream = set(diff.splitlines())
    found = []
    for line in out.splitlines():
        if len(line) < 4 or line[:2] in ("??", "!!"):
            continue
        status, path = line[:2].strip(), line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        found.append({"path": path, "status": status, "upstream_changed": path in upstream})
    return sorted(found, key=lambda o: o["path"])


def plan(from_ref, to_ref, repo=ROOT, runtime=None, system=None):
    """
    The plan as data. `ok` False means it could not be computed; `reason` says why.
    """
    system = system or platform.system()
    out = {"from": from_ref, "to": to_ref, "ok": False, "reason": None, "runtime": runtime,
           "system": system, "files": [], "restart_units": [], "reinstall": False,
           "reinstall_commands": [], "restart_runtime": [], "next_session": False,
           "unknown": [], "drift": [], "manifest": None, "overlays": []}
    for ref in (from_ref, to_ref):
        if not ref_exists(ref, repo=repo):
            out["reason"] = (f"{ref} is not in this clone; run `git fetch --tags origin` "
                             f"and try again. Without both ends there is no diff to read, "
                             f"so nothing here says what needs a restart.")
            return out
    state, manifest = read_manifest(repo)
    out["manifest"] = state
    if state != "present":
        out["reason"] = (f"{manifest}. The manifest is what says which copies outside the "
                         "clone this install owns, so without it no plan is reliable: "
                         "follow UPGRADE.md by hand for this upgrade.")
        return out
    code, diff = git("diff", "--name-only", from_ref, to_ref, repo=repo)
    if code != 0:
        out["reason"] = f"git diff {from_ref} {to_ref} failed: {diff}"
        return out
    out["ok"] = True
    files = [classify(p, runtime=runtime, system=system) for p in diff.splitlines() if p]
    out["files"] = files
    units = []
    for f in files:
        if f["here"] is False:
            continue
        if f["verb"] == "restart":
            if f["unit"] == "both":
                units.extend([LISTENER, DISPATCHER])
            else:
                units.append((f["unit"], f["label"]))
        elif f["verb"] == "reinstall-and-restart":
            if f["command"] is INSTALLER:
                out["reinstall"] = True
            elif f["command"] not in out["reinstall_commands"]:
                out["reinstall_commands"].append(f["command"])
            # A re-registered plugin is loaded by the harness at its own start.
            if f["command"] == OPENCODE_PLUGIN and OPENCODE_RESTART not in out["restart_runtime"]:
                out["restart_runtime"].append(OPENCODE_RESTART)
        elif f["verb"] == "restart-runtime":
            if f["loader"] not in out["restart_runtime"]:
                out["restart_runtime"].append(f["loader"])
        elif f["verb"] == "next-session":
            out["next_session"] = True
        elif f["verb"] == "unknown":
            out["unknown"].append(f["path"])
    seen = []
    for u in units:
        if u not in seen:
            seen.append(u)
    out["restart_units"] = seen
    out["drift"] = manifest_drift(manifest) if out["reinstall"] else []
    out["overlays"] = overlays(from_ref, to_ref, repo=repo)
    return out


def commands(p):
    """The shell lines that carry the plan out, in the order to run them."""
    lines = []
    if not p["ok"]:
        return lines
    if p["reinstall"]:
        runtime = p["runtime"] or "<runtime>"
        lines.append(f"scripts/install.sh --runtime {runtime} --upgrade")
    # Registration steps come after the installer, which they may depend on,
    # and before any restart, so what restarts is the re-registered copy.
    lines.extend(p["reinstall_commands"])
    if p["restart_units"]:
        if p["system"] == "Darwin":
            for _, label in p["restart_units"]:
                lines.append(f'launchctl kickstart -k "gui/$(id -u)/{label}"')
        else:
            lines.append("systemctl --user daemon-reload")
            lines.append("systemctl --user restart " + " ".join(u for u, _ in p["restart_units"]))
    for loader in p["restart_runtime"]:
        lines.append(f"# {loader}")
    if p["next_session"]:
        lines.append("# session hook or watcher changed: the next session picks it up; re-arm the watch there")
    return lines


def render(p):
    head = f"upgrade plan: {p['from']} -> {p['to']}"
    if not p["ok"]:
        return f"{head}\n  could not compute: {p['reason']}\n"
    lines = [head]
    if not p["files"]:
        lines.append("  no files differ between these two refs")
        return "\n".join(lines) + "\n"
    width = max(len(v) for v in VERBS)
    acted = [f for f in p["files"] if f["verb"] != "none"]
    for f in sorted(acted, key=lambda f: (VERBS.index(f["verb"]), f["path"])):
        target = f["loader"]
        if f["verb"] == "restart" and f["unit"] != "both":
            target = f["unit"] if p["system"] != "Darwin" else f["label"]
        note = "" if f["here"] is not False else "  (not on this host)"
        lines.append(f"  {f['verb']:<{width}}  {f['path']} -> {target}{note}")
    quiet = [f for f in p["files"] if f["verb"] == "none"]
    if quiet:
        by_loader = {}
        for f in quiet:
            by_loader[f["loader"]] = by_loader.get(f["loader"], 0) + 1
        detail = ", ".join(f"{loader} ({n})" for loader, n in sorted(by_loader.items(), key=lambda kv: -kv[1]))
        lines.append(f"  {'none':<{width}}  {len(quiet)} file(s) read on each call or not executed: {detail}")
    if p["unknown"]:
        lines.append(f"  {len(p['unknown'])} file(s) unknown: this table does not know what loads them. "
                     "Read UPGRADE.md for those; do not read their absence above as 'nothing to restart'.")
    for target, reason in p["drift"]:
        lines.append(f"  warning: {target}: {reason}; the installer would overwrite it")
    if p["overlays"]:
        lines.append(f"local overlays: {len(p['overlays'])} tracked file(s) modified in this clone")
        for o in p["overlays"]:
            risk = (f"also changes {p['from']} -> {p['to']}: conflict likely on pull"
                    if o["upstream_changed"] else "unchanged upstream: carries over")
            lines.append(f"  {o['path']}: {risk}")
        lines.append("  before pulling, keep a record and set them aside:")
        lines.append(f"    git diff > state/overlay-{p['from']}-{p['to']}.patch")
        lines.append(f'    git stash push -m "paynani overlay before {p["to"]}"')
        lines.append("  after the steps below: git stash pop, then scripts/test_all.sh; "
                     "a conflict on pop is the risk named above, and the patch is the way back")
        lines.append("  ignored files (roster.md, .env, state/) are the install's data, not overlays, "
                     "and are not listed")
    cmds = commands(p)
    if cmds:
        lines.append("run, in this order:")
        lines.extend(f"  {c}" for c in cmds)
    elif not p["unknown"]:
        lines.append("no service needs a restart: every changed file is read on each call or not executed")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="What has to restart between two paynani versions.")
    parser.add_argument("--from", dest="from_ref", help="installed ref (default: v<VERSION>)")
    parser.add_argument("--to", dest="to_ref", help="target ref (default: newest local v* tag)")
    parser.add_argument("--runtime", help="runtime for the install command (default: runtime.env)")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    parser.add_argument("--repo", default=None, help=argparse.SUPPRESS)  # tests plan another clone
    args = parser.parse_args(argv)
    repo = pathlib.Path(args.repo).resolve() if args.repo else ROOT

    from_ref = args.from_ref
    if not from_ref:
        inst = installed_version(repo=repo)
        if not inst:
            print("upgrade plan: could not compute: no readable VERSION file, so the installed tag is unknown", file=sys.stderr)
            return 2
        from_ref = f"v{inst}"
    to_ref = args.to_ref
    if not to_ref:
        tags = local_tags(repo=repo)
        newer = [t for t in tags if ref_exists(from_ref, repo=repo) and version_key(t) > version_key(from_ref)] if VERSION_RE.match(from_ref[1:]) else []
        if not newer:
            print(f"upgrade plan: no local tag newer than {from_ref}. Run `git fetch --tags origin`; "
                  f"if none appears, this clone is on the newest release and there is no upgrade to plan. "
                  f"To plan against unreleased code: --to origin/main", file=sys.stderr)
            return 2
        to_ref = newer[-1]

    p = plan(from_ref, to_ref, repo=repo, runtime=args.runtime or selected_runtime(repo=repo))
    p["commands"] = commands(p)
    if args.json:
        print(json.dumps(p, indent=2, sort_keys=True))
    else:
        sys.stdout.write(render(p))
    return 0 if p["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
