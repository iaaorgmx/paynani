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


import hashlib


def manifest_for(repo, *copies):
    """
    A manifest the installer would have left, naming `copies` as owned files
    with their current digests. The plan reads it on every run (#167, req. 2).
    """
    lines = ["runtime\tclaudecode"]
    for path in copies:
        digest = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
        lines.append(f"artifact\tfile\t{path}\t{digest}")
    (repo / "install.manifest").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    # The install's own data is ignored, the way the real .gitignore does it.
    write(repo, ".gitignore", "roster.md\n.env\ninstall.manifest\nstate/\n")
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

    # --- no manifest, no plan (#167 requirement 2; Ocelotl on PR #185) --------
    # Both tags exist and the diff is real, and the plan still refuses: the
    # manifest is what says which copies outside the clone this install owns.
    absent = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="claudecode", system="Linux")
    check("without a manifest the plan cannot be computed", absent["ok"] is False)
    check("and says the manifest is missing and where", "no install manifest at" in (absent["reason"] or ""))
    check("and sends the operator to UPGRADE.md", "UPGRADE.md" in (absent["reason"] or ""))
    check("and produces no commands", up.commands(absent) == [])
    check("and lists no files, so nothing reads as a plan", absent["files"] == [])
    check("render says could not compute", "could not compute" in up.render(absent))
    check("render never says nothing needs a restart", "no service needs a restart" not in up.render(absent))
    check("the manifest state is reported", absent["manifest"] == "absent")
    # Same with a diff that has no copied file at all: the check does not wait
    # for a reinstall action to look.
    write(repo, "README.md", "v2b\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "docs")
    sh(repo, "tag", "v2.0.0b")
    docs_absent = up.plan("v2.0.0", "v2.0.0b", repo=repo, runtime="claudecode", system="Linux")
    check("a docs-only diff without a manifest is still not a plan", docs_absent["ok"] is False)
    # Unreadable is its own word, not "absent": the file is there and something
    # is wrong with it, which is a different thing to fix.
    (repo / "install.manifest").write_text("runtime\tclaudecode\n", encoding="utf-8")
    (repo / "install.manifest").chmod(0)
    unreadable = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="claudecode", system="Linux")
    (repo / "install.manifest").chmod(0o600)
    if unreadable["manifest"] == "present":
        print("skip unreadable manifest: this user can read a mode-000 file (root?)")
    else:
        check("an unreadable manifest is reported as such", unreadable["manifest"] == "unreadable"
              and "could not be read" in (unreadable["reason"] or ""), unreadable["reason"])
        check("and is not a plan either", unreadable["ok"] is False)

    # An installer-owned copy, converged, so the plan below has a manifest to read.
    unit_copy = tmp / "paynani-idle.service"
    unit_copy.write_text("copied\n", encoding="utf-8")
    manifest_for(repo, unit_copy)

    p = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="claudecode", system="Linux")
    check("plan computes when both tags and the manifest exist", p["ok"], p["reason"])
    check("the manifest state is present", p["manifest"] == "present")
    verbs = {f["path"]: f["verb"] for f in p["files"]}
    check("dispatch.py -> restart", verbs.get("harness/dispatch.py") == "restart")
    # ledger.py (0.7.1) is imported by the listener, the dispatcher and the
    # session hook; the real v0.7.0 -> v0.7.1 plan listed it as unknown.
    check("ledger.py -> restart both", up.classify("harness/ledger.py")["unit"] == "both")
    check("systemd unit -> reinstall-and-restart", verbs.get("systemd/paynani-idle.service") == "reinstall-and-restart")
    check("opencode plugin -> reinstall-and-restart", verbs.get("harness/opencode/paynani.js") == "reinstall-and-restart")
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

    # --- the OpenCode plugin is re-registered, not merely announced (Ocelotl) --
    # The installer names the registration and does not perform it, so a plan
    # that collapsed every copy into `install.sh --upgrade` never re-registered
    # the shim. The acceptance case of #167: paynani.js changed between the two
    # versions, and the plan has to run the registration before OpenCode restarts.
    oc = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="opencode", system="Linux")
    oc_cmds = up.commands(oc)
    check("the plugin registration is its own command",
          "python3 scripts/opencode_plugin.py --install" in oc_cmds, str(oc_cmds))
    check("it comes after the installer",
          oc_cmds.index("python3 scripts/opencode_plugin.py --install")
          > oc_cmds.index("scripts/install.sh --runtime opencode --upgrade"), str(oc_cmds))
    check("and before the OpenCode restart",
          oc_cmds.index("python3 scripts/opencode_plugin.py --install")
          < oc_cmds.index("# OpenCode (close and reopen it)"), str(oc_cmds))
    check("the OpenCode restart is listed once", oc_cmds.count("# OpenCode (close and reopen it)") == 1, str(oc_cmds))
    check("the registration is not run on a Claude Code host",
          "python3 scripts/opencode_plugin.py --install" not in cmds, str(cmds))
    write(repo, "scripts/openclaw_rules.py", "v1\n")
    write(repo, "scripts/claude_hook.py", "v1\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "hooks")
    sh(repo, "tag", "v2.1.0")
    hooks = {rt: up.commands(up.plan("v2.0.0", "v2.1.0", repo=repo, runtime=rt, system="Linux"))
             for rt in ("openclaw", "claudecode", "hermes")}
    check("the OpenClaw standing rule has its own command on an OpenClaw host",
          "python3 scripts/openclaw_rules.py --install" in hooks["openclaw"], str(hooks["openclaw"]))
    check("the Claude Code hook has its own command on a Claude Code host",
          "python3 scripts/claude_hook.py --install" in hooks["claudecode"], str(hooks["claudecode"]))
    check("neither runs on a Hermes host", hooks["hermes"] == [], str(hooks["hermes"]))
    check("a registration alone does not call the installer",
          not any(c.startswith("scripts/install.sh") for c in hooks["openclaw"]), str(hooks["openclaw"]))

    # --- local overlays (Lisa's addendum on #167; Ocelotl point 3) ------------
    # A tracked file modified in the clone is an overlay; the plan names it,
    # says whether the upgrade also touches it, and how to keep a record. An
    # ignored roster.md is the install's data and must not appear.
    write(repo, "scripts/send.sh", "local signature feature\n")       # unchanged upstream
    write(repo, "harness/dispatch.py", "local patch\n")               # also changes v1 -> v2
    write(repo, "roster.md", "| Name | Email |\n|---|---|\n| A | a@example.org |\n")
    write(repo, "state/events.jsonl", "{}\n")
    ov = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="claudecode", system="Linux")
    found = {o["path"]: o for o in ov["overlays"]}
    check("two tracked modified files are overlays", sorted(found) == ["harness/dispatch.py", "scripts/send.sh"], str(found))
    check("the one that also changes upstream is flagged", found["harness/dispatch.py"]["upstream_changed"] is True)
    check("the one unchanged upstream is not", found["scripts/send.sh"]["upstream_changed"] is False)
    check("ignored roster.md is not an overlay", "roster.md" not in found)
    check("ignored state is not an overlay", not any(p.startswith("state/") for p in found))
    ov_text = up.render(ov)
    check("render names the overlays", "local overlays: 2 tracked file(s)" in ov_text, ov_text)
    check("render says which one conflicts", "harness/dispatch.py: also changes v1.0.0 -> v2.0.0: conflict likely" in ov_text, ov_text)
    check("render says which one carries over", "scripts/send.sh: unchanged upstream: carries over" in ov_text, ov_text)
    check("render gives the record and the stash", "git diff > state/overlay-v1.0.0-v2.0.0.patch" in ov_text
          and 'git stash push -m "paynani overlay before v2.0.0"' in ov_text, ov_text)
    check("render says ignored files are not listed", "not overlays" in ov_text)
    check("the plan itself is unaffected by overlays", ov["ok"] and up.commands(ov) == cmds, str(up.commands(ov)))
    sh(repo, "checkout", "--", "scripts/send.sh", "harness/dispatch.py")
    clean = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="claudecode", system="Linux")
    check("a clean clone has no overlays", clean["overlays"] == [])
    check("and render says nothing about them", "local overlays" not in up.render(clean))

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
    manifest_for(repo, unit_copy)
    quiet = up.plan("v2.1.0", "v2.0.1", repo=repo, runtime="claudecode", system="Linux")
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
    # The CLI from a clone with tags but no manifest: exit 2 and the reason,
    # end to end, since that is the state Ocelotl reproduced.
    (repo / "install.manifest").unlink()
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "upgrade_plan.py"), "--repo", str(repo),
                          "--from", "v1.0.0", "--to", "v2.0.0", "--runtime", "opencode"],
                         capture_output=True, text=True, cwd=str(tmp))
    check("CLI exits 2 without a manifest", run.returncode == 2, run.stdout + run.stderr)
    check("CLI names the missing manifest and UPGRADE.md",
          "no install manifest" in run.stdout and "UPGRADE.md" in run.stdout, run.stdout)
    check("CLI prints no commands without a manifest", "run, in this order" not in run.stdout, run.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
