#!/usr/bin/env python3
"""
upgrade_plan.py: the plan says what to restart, and says when it cannot say.

Runs against a throwaway git repository built here, so the table is exercised
on a known diff rather than on whatever this clone's tags happen to contain.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import upgrade_plan as up  # noqa: E402

passed = failed = 0


def check(desc, condition, detail=""):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}" + (f"\n       {detail}" if detail else ""))
        failed += 1


def sh(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                        "PATH": "/usr/bin:/bin:/usr/local/bin"})


def write(repo, rel, text):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# No manifest lookups against the real host from inside these checks.
up.manifest_drift = lambda repo=None: []

tmp = pathlib.Path(tempfile.mkdtemp(prefix="paynani-plan-"))
try:
    repo = tmp / "clone"
    repo.mkdir()
    sh(repo, "init", "-q")
    for rel in ("VERSION", "README.md", "harness/dispatch.py", "harness/paths.py",
                "scripts/idle_listener.py", "scripts/send.sh", "systemd/paynani-idle.service",
                "harness/opencode/paynani.js", "harness/session_watch.sh", "scripts/test_x.py",
                "tools/new_thing.py"):
        write(repo, rel, "v1\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "one")
    sh(repo, "tag", "v1.0.0")

    # v2 touches one file per verb, plus one the table has never heard of.
    for rel in ("README.md", "harness/dispatch.py", "systemd/paynani-idle.service",
                "harness/opencode/paynani.js", "harness/session_watch.sh", "scripts/test_x.py",
                "tools/new_thing.py"):
        write(repo, rel, "v2\n")
    write(repo, "VERSION", "2.0.0\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "two")
    sh(repo, "tag", "v2.0.0")

    p = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="claudecode", system="Linux")
    check("plan computes when both tags exist", p["ok"], p["reason"])
    verbs = {f["path"]: f["verb"] for f in p["files"]}
    check("dispatch.py -> restart", verbs.get("harness/dispatch.py") == "restart")
    check("systemd unit -> reinstall-and-restart", verbs.get("systemd/paynani-idle.service") == "reinstall-and-restart")
    check("opencode plugin -> restart-runtime", verbs.get("harness/opencode/paynani.js") == "restart-runtime")
    check("session watcher -> next-session", verbs.get("harness/session_watch.sh") == "next-session")
    check("README -> none", verbs.get("README.md") == "none")
    check("a test file -> none", verbs.get("scripts/test_x.py") == "none")
    check("a file outside the table -> unknown", verbs.get("tools/new_thing.py") == "unknown")
    check("unknown files are listed by name", p["unknown"] == ["tools/new_thing.py"])
    check("the dispatcher is the only unit to restart",
          [u for u, _ in p["restart_units"]] == ["paynani-dispatch.service"])
    check("a copied unit sets reinstall", p["reinstall"] is True)

    here = {f["path"]: f["here"] for f in p["files"]}
    check("an OpenCode file is not acted on for a Claude Code host", here["harness/opencode/paynani.js"] is False)
    check("the watcher is acted on for a Claude Code host", here["harness/session_watch.sh"] is True)
    cmds = up.commands(p)
    check("commands start with the installer when a copy changed",
          cmds and cmds[0] == "scripts/install.sh --runtime claudecode --upgrade", str(cmds))
    check("commands restart the dispatcher with systemctl",
          any(c == "systemctl --user restart paynani-dispatch.service" for c in cmds), str(cmds))
    check("commands do not mention OpenCode on a Claude Code host",
          not any("OpenCode" in c for c in cmds), str(cmds))
    text = up.render(p)
    check("render marks the other runtime's file", "(not on this host)" in text)
    check("render warns about unknown files and refuses the happy reading",
          "1 file(s) unknown" in text and "do not read their absence" in text)
    check("render collapses the quiet files into one line", "3 file(s) read on each call or not executed" in text, text)

    mac = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="opencode", system="Darwin")
    mac_cmds = up.commands(mac)
    check("on macOS the restart is launchctl kickstart",
          any(c.startswith('launchctl kickstart -k "gui/$(id -u)/com.paynani.dispatch"') for c in mac_cmds), str(mac_cmds))
    check("on macOS the systemd template is not acted on",
          {f["path"]: f["here"] for f in mac["files"]}["systemd/paynani-idle.service"] is False)
    check("on an OpenCode host the plugin is acted on", any("OpenCode" in c for c in mac_cmds), str(mac_cmds))
    check("on an OpenCode host the watcher is not", not any("watcher" in c for c in mac_cmds), str(mac_cmds))

    missing = up.plan("v1.0.0", "v9.9.9", repo=repo, runtime="claudecode", system="Linux")
    check("a missing target ref cannot be computed", missing["ok"] is False)
    check("and says to fetch tags, not that nothing needs a restart",
          "git fetch --tags" in (missing["reason"] or "") and "nothing" in (missing["reason"] or ""))
    check("render of an uncomputable plan says could not compute", "could not compute" in up.render(missing))
    check("an uncomputable plan has no commands", up.commands(missing) == [])

    # Only quiet files between the refs: the one case allowed to say "no restart".
    write(repo, "README.md", "v3\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "docs only")
    sh(repo, "tag", "v2.0.1")
    quiet = up.plan("v2.0.0", "v2.0.1", repo=repo, runtime="claudecode", system="Linux")
    check("docs-only diff says no service needs a restart", "no service needs a restart" in up.render(quiet))
    check("docs-only diff has no commands", up.commands(quiet) == [])

    # Same refs: nothing differs, and that is said as such.
    same = up.plan("v2.0.1", "v2.0.1", repo=repo, runtime="claudecode", system="Linux")
    check("identical refs say no files differ", "no files differ" in up.render(same))

    # The CLI end to end, from inside the throwaway clone.
    script = tmp / "scripts" / "upgrade_plan.py"
    (tmp / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "upgrade_plan.py", script)
    shutil.copytree(ROOT / "harness", tmp / "harness", ignore=shutil.ignore_patterns("__pycache__"))
    run = subprocess.run([sys.executable, str(script), "--from", "v1.0.0", "--to", "v9.9.9"],
                         capture_output=True, text=True, cwd=str(tmp))
    check("CLI exits 2 when the plan cannot be computed", run.returncode == 2, run.stdout + run.stderr)
    check("CLI says could not compute", "could not compute" in run.stdout, run.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
