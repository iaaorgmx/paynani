#!/usr/bin/env python3
"""
upgrade_plan.py: the plan says what to restart, and says when it cannot say.

Runs against a throwaway git repository built here, so the table is exercised
on a known diff rather than on whatever this clone's tags happen to contain.
"""

import json
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
    # python_floor.py (#241) is imported by both services at start; the real
    # v0.7.2 -> main plan listed it as unknown, and --apply refused because of it.
    check("python_floor.py -> restart both", up.classify("harness/python_floor.py")["unit"] == "both")
    # The same miss twice (ledger.py, then python_floor.py): every harness module
    # that ships in this repository has a row, so the next one fails here instead
    # of in the fleet's upgrade plan.
    shipped = subprocess.run(["git", "-C", str(up.ROOT), "ls-files", "harness"],
                             capture_output=True, text=True).stdout.split()
    unclassified = [p for p in shipped if up.classify(p)["verb"] == "unknown"]
    check("every file under harness/ has a row in the upgrade table", not unclassified,
          ", ".join(unclassified))
    # SRV-7: the optional SMS gateway. What it imports restarts it; what only a
    # command reads does not. A unit that is not installed must never be named
    # outright (restarting it would fail the whole --apply), only by pattern.
    for path in ("scripts/sms_gateway.py", "scripts/paynani_lib/sms/gateway.py",
                 "scripts/paynani_lib/sms/store.py", "scripts/paynani_lib/sms/websocket.py"):
        c = up.classify(path)
        check(f"{path} -> restart the SMS gateway", (c["verb"], c["unit"]) == ("restart", "paynani-sms*.service"),
              str(c))
    for path in ("scripts/paynani_lib/sms/cli.py", "scripts/paynani_lib/sms/qr.py",
                 "scripts/paynani_lib/sms/pairing.py", "scripts/paynani_lib/sms/health.py"):
        check(f"{path} -> none (read on each call)", up.classify(path)["verb"] == "none")
    check("the gateway unit is a pattern, so a host without it is not asked to restart it",
          "*" in up.SMS_GATEWAY[0] and "*" in up.SMS_GATEWAY[1])
    check("roster.py and the shared harness modules restart the gateway too",
          all(up.classify(p)["verb"] == "restart" for p in ("scripts/roster.py", "harness/event.py", "harness/phone.py")))
    check("paynani-sms.service has its systemd row", up.classify("systemd/paynani-sms.service")["verb"] == "reinstall-and-restart")
    check("systemd unit -> reinstall-and-restart", verbs.get("systemd/paynani-idle.service") == "reinstall-and-restart")
    check("opencode plugin -> reinstall-and-restart", verbs.get("harness/opencode/paynani.js") == "reinstall-and-restart")
    check("session watcher -> next-session", verbs.get("harness/session_watch.sh") == "next-session")
    check("README -> none", verbs.get("README.md") == "none")
    check("bootstrap.sh (#335) -> none: it runs by hand and nothing loads it", up.classify("bootstrap.sh")["verb"] == "none")
    # WhatsApp (PRD #550, Ximena en #564): the bridge runs as a child of the service.
    for path in ("scripts/whatsapp_service.py", "scripts/paynani_lib/whatsapp/bridge.py",
                 "scripts/whatsapp_bridge/index.js", "scripts/whatsapp_bridge/lib.js"):
        c = up.classify(path)
        check(f"{path} -> restart the WhatsApp service",
              (c["verb"], c["unit"]) == ("restart", "paynani-whatsapp*.service"), str(c))
    for path in ("scripts/whatsapp_bridge/package.json", "scripts/whatsapp_bridge/package-lock.json"):
        c = up.classify(path)
        check(f"{path} -> the installer (npm ci with its Node, only if it owns WhatsApp) and restart",
              (c["verb"], c["command"], c["unit"]) == ("reinstall-and-restart", up.INSTALLER,
                                                         "paynani-whatsapp*.service"), str(c))
    for path in ("scripts/whatsapp_bridge/test/lib.test.js", "scripts/whatsapp_bridge/fake_bridge.py"):
        check(f"{path} -> none (tests)", up.classify(path)["verb"] == "none")
    # The gateway's §11 and §12 modules, and who reads whatsapp.env (WhatsApp from PaynaniApp).
    c = up.classify("scripts/paynani_lib/sms/whatsapp_api.py")
    check("sms/whatsapp_api.py -> restart the SMS gateway",
          (c["verb"], c["unit"]) == ("restart", "paynani-sms*.service"), str(c))
    for path in ("scripts/paynani_lib/sms/roster_api.py", "scripts/paynani_lib/sms/api_replies.py"):
        c = up.classify(path)
        check(f"{path} -> restart the gateway and PaynaniWeb (both import it)",
              (c["verb"], c["unit"]) == ("restart", "gateway-web"), str(c))
    for path in ("scripts/paynani_lib/whatsapp/config.py", "scripts/paynani_lib/whatsapp/media.py"):
        c = up.classify(path)
        check(f"{path} -> restart the WhatsApp service, the gateway and PaynaniWeb",
              (c["verb"], c["unit"]) == ("restart", "whatsapp-all")
              and up._units_of(c) == [up.WHATSAPP, up.SMS_GATEWAY, up.WEB], str(c))
    for path in ("scripts/node_runtime.py", "scripts/node_release.json"):
        check(f"{path} -> the installer again (the pinned Node of WhatsApp)",
              up.classify(path)["verb"] == "reinstall-and-restart")
    # Every file the repository tracks has a rule. bootstrap.sh reached main
    # without one (#351) and every plan to the next release would have said
    # `unknown` and refused --apply: a new file must fail here, in its own PR.
    tracked = subprocess.run(["git", "-C", str(up.ROOT), "ls-files"], capture_output=True, text=True).stdout.split()
    if tracked:
        untabled = [f for f in tracked if up.classify(f)["verb"] == "unknown"]
        check("every tracked file has a rule in the table", not untabled, str(untabled))
    else:
        print("skip tracked-file coverage: not a git checkout")
    check("a test file -> none", verbs.get("scripts/test_x.py") == "none")
    check("a file outside the table -> unknown", verbs.get("tools/new_thing.py") == "unknown")
    check("unknown files are listed by name", p["unknown"] == ["tools/new_thing.py"])
    check("VERSION restarts the listener, dispatcher, SMS gateway and PaynaniWeb",
          [u for u, _ in p["restart_units"]]
          == ["paynani-idle.service", "paynani-idle@*.service", "paynani-dispatch.service",
              "paynani-sms*.service", "paynani-web*.service"])
    check("a copied unit sets reinstall", p["reinstall"] is True)

    here = {f["path"]: f["here"] for f in p["files"]}
    check("an OpenCode file is not acted on for a Claude Code host", here["harness/opencode/paynani.js"] is False)
    check("the watcher is acted on for a Claude Code host", here["harness/session_watch.sh"] is True)
    cmds = up.commands(p)
    check("commands start with the installer when a copy changed",
          cmds and cmds[0] == "scripts/install.sh --runtime claudecode --upgrade", str(cmds))
    # v2 rewrites a systemd template. install.sh --upgrade restarts the two main
    # services only when it rewrote an artifact it owns, and the template can be for
    # a unit this host does not have, so the plan restarts them itself anyway (#410).
    check("a changed unit still asks for daemon-reload after the installer",
          cmds[:2] == ["scripts/install.sh --runtime claudecode --upgrade", "systemctl --user daemon-reload"],
          str(cmds))
    check("a changed unit still restarts both main services",
          "systemctl --user restart paynani-idle.service paynani-dispatch.service" in cmds, str(cmds))
    check("the plan never says the installer already restarted them",
          not any("already restarted" in c for c in cmds), str(cmds))
    check("commands restart account listener instances only when systemd lists them",
          any("paynani-idle@*.service" in c and "xargs -r systemctl --user restart" in c
              for c in cmds), str(cmds))
    check("commands do not mention OpenCode on a Claude Code host",
          not any("OpenCode" in c for c in cmds), str(cmds))
    text = up.render(p)
    check("render marks the other runtime's file", "(not on this host)" in text)
    check("render warns about unknown files and refuses the happy reading",
          "1 file(s) unknown" in text and "do not read their absence" in text)
    check("render collapses the quiet files into one line", "2 file(s) read on each call or not executed" in text, text)

    mac = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="opencode", system="Darwin")
    mac_cmds = up.commands(mac)
    check("on macOS the restart is launchctl kickstart",
          any(c.startswith('launchctl kickstart -k "gui/$(id -u)/com.paynani.dispatch"') for c in mac_cmds), str(mac_cmds))
    check("on macOS the systemd template is not acted on",
          {f["path"]: f["here"] for f in mac["files"]}["systemd/paynani-idle.service"] is False)
    check("on an OpenCode host the plugin is acted on", any("OpenCode" in c for c in mac_cmds), str(mac_cmds))
    check("on an OpenCode host the watcher is not", not any("watcher" in c for c in mac_cmds), str(mac_cmds))

    # 0.16.1 on Ximena's Mac: --apply passed 'com.paynani.idle.*' to launchctl
    # kickstart, which takes one exact label, and stopped with exit 113. A pattern
    # is now matched against `launchctl list`; an exact label is kicked as is.
    launchd_calls = []
    launchctl_list = ("PID\tStatus\tLabel\n"
                      "101\t0\tcom.paynani.idle\n"
                      "102\t0\tcom.paynani.idle.cuenta2\n"
                      "103\t0\tcom.paynani.idle.cuenta1\n"
                      "104\t0\tcom.paynani.dispatch\n"
                      "105\t0\tcom.paynani.sms\n"
                      "-\t0\tcom.apple.something\n")

    def launchd_runner(argv, cwd, text, capture_output):
        argv = [str(value) for value in argv]
        launchd_calls.append(argv)
        out = launchctl_list if argv == ["launchctl", "list"] else ""
        return subprocess.CompletedProcess(argv, 0, out, "")

    labels = [label for _, label in (up.LISTENER, up.LISTENER_INSTANCES, up.DISPATCHER, up.SMS_GATEWAY, up.WEB)]
    up._launchd_restart_labels(labels, repo, launchd_runner)
    kicked = [a[3].split("/", 2)[2] for a in launchd_calls if a[:3] == ["launchctl", "kickstart", "-k"]]
    check("macOS --apply never passes a pattern to launchctl kickstart",
          not any("*" in name for name in kicked), str(launchd_calls))
    check("... it restarts each loaded label once, in plan order, and nothing that is not loaded",
          kicked == ["com.paynani.idle", "com.paynani.idle.cuenta1", "com.paynani.idle.cuenta2",
                     "com.paynani.dispatch", "com.paynani.sms"], str(kicked))
    check("... and reads `launchctl list` only once",
          launchd_calls.count(["launchctl", "list"]) == 1, str(launchd_calls))
    printed = up.commands(dict(mac, ok=True, reinstall=False, reinstall_commands=[], restart_runtime=[],
                               next_session=False, restart_units=[up.LISTENER_INSTANCES]))
    check("the printed macOS step for a pattern is a command, not a comment",
          len(printed) == 1 and not printed[0].startswith("#") and "launchctl list" in printed[0]
          and "grep -xE 'com\\.paynani\\.idle\\..*'" in printed[0], str(printed))

    # --- the installer's restart is only counted when it is certain (#302) ----
    # install.sh restarts the two services only if it rewrote an artifact it owns,
    # so a release whose installer changed but whose units did not still needs the
    # plan's own restart; dropping it would leave both services on the old code.
    sh(repo, "checkout", "-q", "-b", "installer-only", "v1.0.0")
    write(repo, "VERSION", "1.0.1\n")
    write(repo, "scripts/install.sh", "#!/usr/bin/env bash\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "installer only")
    sh(repo, "tag", "v1.0.1")
    io = up.plan("v1.0.0", "v1.0.1", repo=repo, runtime="claudecode", system="Linux")
    io_cmds = up.commands(io)
    check("an installer change alone still sets reinstall", io["reinstall"] is True)
    check("then the plan keeps daemon-reload and the restart of both services",
          "systemctl --user daemon-reload" in io_cmds
          and "systemctl --user restart paynani-idle.service paynani-dispatch.service" in io_cmds, str(io_cmds))
    check("then no already-restarted note is printed",
          not any("already restarted" in c for c in io_cmds), str(io_cmds))
    sh(repo, "checkout", "-q", "-")
    plain = up.plan("v1.0.0", "v2.0.0", repo=repo, runtime="claudecode", system="Linux")
    nounit = dict(plain, reinstall=False)
    check("without an installer in the plan nothing is skipped",
          "systemctl --user restart paynani-idle.service paynani-dispatch.service" in up.commands(nounit))
    # #410: 0.13.1 changed only the SMS gateway's template (and VERSION). A host
    # without the gateway has nothing for the installer to rewrite, so it answers
    # "already converged" and restarts nothing; the plan has to restart both itself.
    sh(repo, "checkout", "-q", "-b", "sms-unit-only", "v1.0.0")
    write(repo, "VERSION", "1.0.2\n")
    write(repo, "systemd/paynani-sms.service", "[Service]\nEnvironment=\"PATH=/x\"\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "sms unit only")
    sh(repo, "tag", "v1.0.2")
    sms_only = up.commands(up.plan("v1.0.0", "v1.0.2", repo=repo, runtime="claudecode", system="Linux"))
    check("a release that only changes the gateway's unit still restarts both main services (#410)",
          "systemctl --user restart paynani-idle.service paynani-dispatch.service" in sms_only, str(sms_only))
    check("and its daemon-reload", "systemctl --user daemon-reload" in sms_only, str(sms_only))
    sh(repo, "checkout", "-q", "-")

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

    # #582: the Hermes routes are copied by hand into ~/.hermes/config.yaml, so a
    # changed example is a manual step on a Hermes host and nothing elsewhere.
    write(repo, "examples/hermes-routes.yaml", "{}\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "routes")
    sh(repo, "tag", "v2.1.1")
    routes = {rt: up.commands(up.plan("v2.1.0", "v2.1.1", repo=repo, runtime=rt, system="Linux"))
              for rt in ("hermes", "claudecode")}
    check("a changed Hermes route example asks a Hermes host to copy the routes and restart the gateway",
          any("hermes gateway restart" in c and "events lists" in c for c in routes["hermes"]),
          str(routes["hermes"]))
    check("and asks nothing of another runtime", routes["claudecode"] == [], str(routes["claudecode"]))

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
    check("render gives the record and the stash", "git diff HEAD --binary > state/overlay-v1.0.0-v2.0.0-<unique>.patch" in ov_text
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
    # #462: the PaynaniWeb notice sat between `if cmds:` and its `elif`, so a plan with
    # commands and no notice also printed "no service needs a restart".
    for missing in (False, True):
        shown = up.render(dict(quiet, web_user_missing=missing))
        check(f"docs-only, web user missing={missing}: still says no service needs a restart",
              "no service needs a restart" in shown and ("PaynaniWeb has no user yet" in shown) == missing, shown)
    check("docs-only diff has no commands", up.commands(quiet) == [])

    # Same refs: nothing differs, and that is said as such.
    same = up.plan("v2.0.1", "v2.0.1", repo=repo, runtime="claudecode", system="Linux")
    check("identical refs say no files differ", "no files differ" in up.render(same))

    # A target --apply cannot pull (a branch, a commit) still gets its plan (#297).
    # Before, render() called _fetch_argv() for it and died with a traceback.
    # v2.0.0 -> v2.0.1 is the docs-only step above: no unknown files and no drift, so
    # it reaches the apply block, which is where the traceback came from.
    sh(repo, "branch", "release-x", "v2.0.1")
    branch = up.plan("v2.0.0", "release-x", repo=repo, runtime="claudecode", system="Linux")
    branch_text = up.render(branch)
    check("a branch target renders its plan instead of raising",
          "upgrade plan: v2.0.0 -> release-x" in branch_text and "run, in this order" in branch_text, branch_text)
    check("... and says --apply refuses it, and why",
          "refused: release-x is neither a release tag nor origin/main" in branch_text, branch_text)
    check("... with no apply steps printed", "git fetch origin" not in branch_text
          and "git merge --ff-only" not in branch_text, branch_text)
    check("a tag target still prints its apply steps, unchanged",
          "git fetch origin tag v2.0.1" in up.render(
              up.plan("v2.0.0", "v2.0.1", repo=repo, runtime="claudecode", system="Linux")))
    check("apply_target_ok accepts a release tag and origin/main only",
          up.apply_target_ok("v0.9.0") and up.apply_target_ok("origin/main")
          and not up.apply_target_ok("release-x") and not up.apply_target_ok("v0.9.0-rc1")
          and not up.apply_target_ok("origin/release-0.9.0") and not up.apply_target_ok("5bd18f9"))
    try:
        up.apply_plan(branch, repo=repo, runner=lambda *a, **k: None, wait_seconds=0)
        apply_branch_error = ""
    except up.ApplyError as exc:
        apply_branch_error = str(exc)
    check("--apply of a branch is still refused, for the same reason (not by a side effect)",
          "release tag or origin/main" in apply_branch_error, apply_branch_error)
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "upgrade_plan.py"), "--repo", str(repo),
                          "--from", "v2.0.0", "--to", "release-x", "--runtime", "claudecode"],
                         capture_output=True, text=True, cwd=str(tmp))
    check("CLI with a branch target exits 0 and prints no traceback",
          run.returncode == 0 and "Traceback" not in run.stdout + run.stderr, run.stdout + run.stderr)

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

    # --- --apply: exact plan, overlays, restart and final verification --------
    remote = tmp / "apply-origin.git"
    seed = tmp / "apply-seed"
    applied = tmp / "apply-clone"
    sh(tmp, "init", "-q", "--bare", str(remote))
    seed.mkdir()
    sh(seed, "init", "-q")
    write(seed, ".gitignore", "install.manifest\nstate/\n")
    write(seed, "VERSION", "1.0.0\n")
    write(seed, "overlay.txt", "upstream\n")
    write(seed, "scripts/version.sh", "#!/usr/bin/env bash\n[ \"$1\" = --installed ] && tr -d '[:space:]' < VERSION\n")
    write(seed, "scripts/healthcheck.py", "#!/usr/bin/env python3\nraise SystemExit(0)\n")
    write(seed, "scripts/test_all.sh", "#!/usr/bin/env bash\nexit 0\n")
    for executable in ("scripts/version.sh", "scripts/healthcheck.py", "scripts/test_all.sh"):
        (seed / executable).chmod(0o755)
    sh(seed, "add", "-A")
    sh(seed, "commit", "-q", "-m", "one")
    sh(seed, "tag", "v1.0.0")
    sh(seed, "remote", "add", "origin", str(remote))
    sh(seed, "push", "-q", "origin", "HEAD:main", "--tags")
    write(seed, "VERSION", "2.0.0\n")
    sh(seed, "add", "VERSION")
    sh(seed, "commit", "-q", "-m", "two")
    sh(seed, "tag", "-a", "v2.0.0", "-m", "version 2.0.0")
    sh(seed, "push", "-q", "origin", "HEAD:main", "--tags")
    subprocess.run(["git", "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
                   check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(applied)], check=True)
    sh(applied, "checkout", "-q", "-b", "installed", "v1.0.0")
    manifest_for(applied)
    write(applied, "overlay.txt", "local overlay\n")
    state = applied / "state"
    state.mkdir()
    write(applied, "state/idle.json", json.dumps({"heartbeat_at": "old", "version": "1.0.0"}))
    write(applied, "state/idle.err.log", "old line\n")
    apply = up.plan("v1.0.0", "v2.0.0", repo=applied, runtime="claudecode", system="Linux")
    calls = []

    def apply_runner(argv, cwd, text, capture_output):
        argv = [str(value) for value in argv]
        calls.append(argv)
        if argv[:2] == ["systemctl", "--user"]:
            if argv[2:3] == ["restart"]:
                (state / "idle.json").write_text(json.dumps({
                    "heartbeat_at": "new", "version": "2.0.0", "last_uid": 7
                }), encoding="utf-8")
                with (state / "idle.err.log").open("a", encoding="utf-8") as handle:
                    handle.write("listening on INBOX, resuming from uid 7\n")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv and argv[0].endswith("scripts/healthcheck.py"):
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv and argv[0].endswith("scripts/test_all.sh"):
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.run(argv, cwd=cwd, text=text, capture_output=capture_output)

    result = up.apply_plan(apply, repo=applied, runner=apply_runner, wait_seconds=0)
    check("apply advances to the exact planned annotated tag",
          subprocess.run(["git", "-C", str(applied), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
          == subprocess.run(["git", "-C", str(applied), "rev-parse", "v2.0.0^{commit}"],
                            capture_output=True, text=True).stdout.strip())
    check("apply restores the tracked overlay", (applied / "overlay.txt").read_text() == "local overlay\n")
    for missing in (False, True):
        shown = up.render(dict(apply, web_user_missing=missing))
        check(f"a plan with restarts, web user missing={missing}: never says no service needs a restart (#462)",
              "run, in this order:" in shown and "no service needs a restart" not in shown
              and ("PaynaniWeb has no user yet" in shown) == missing, shown)
    check("apply records a binary-capable overlay patch",
          result["patch"] is not None and pathlib.Path(result["patch"]).read_text())
    check("apply runs the suite after restoring an overlay",
          any(argv and argv[0].endswith("scripts/test_all.sh") for argv in calls), str(calls))
    # The seed changes only VERSION, and both services record the version they
    # loaded, so both are restarted (the plan used to name only the listener,
    # which left doctor in `warning` after an exact apply; found preparing 0.9.1).
    check("apply restarts the services named by the plan, listener and dispatcher",
          ["systemctl", "--user", "restart", "paynani-idle.service", "paynani-dispatch.service"] in calls,
          str(calls))
    check("apply finishes with healthcheck",
          any(argv and argv[0].endswith("scripts/healthcheck.py") for argv in calls), str(calls))

    # With the installer in the plan, apply runs it and then daemon-reload and the
    # two main restarts anyway: the installer may have found nothing to rewrite
    # ("already converged") and restarted nothing (#410).
    via_installer = dict(apply, reinstall=True, runtime="claudecode")
    calls.clear()

    def installer_runner(argv, cwd, text, capture_output):
        argv = [str(value) for value in argv]
        if argv and argv[0].endswith("scripts/install.sh"):
            calls.append(argv)
            # What the real installer's restart leaves behind for the wait.
            with (state / "idle.err.log").open("a", encoding="utf-8") as handle:
                handle.write("listening on INBOX, resuming from uid 7\n")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return apply_runner(argv, cwd, text, capture_output)

    up.apply_plan(via_installer, repo=applied, runner=installer_runner, wait_seconds=0)
    check("apply runs the installer", any(a[0].endswith("scripts/install.sh") for a in calls), str(calls))
    installer_at = next(i for i, a in enumerate(calls) if a[0].endswith("scripts/install.sh"))
    check("apply runs daemon-reload after the installer, which may have restarted nothing (#410)",
          ["systemctl", "--user", "daemon-reload"] in calls[installer_at:], str(calls))
    check("and then restarts the two main services itself",
          ["systemctl", "--user", "restart", "paynani-idle.service", "paynani-dispatch.service"]
          in calls[installer_at:], str(calls))
    calls.clear()

    # install.sh --upgrade exits 10 (EX_CHANGED) when it succeeded and changed
    # something. --apply took it as a failure and stopped before the restarts, which
    # left the old gateway running (#435, found by Metis upgrading to e9cfada).
    def installer_exit(code):
        def runner(argv, cwd, text, capture_output):
            argv = [str(value) for value in argv]
            if argv and argv[0].endswith("scripts/install.sh"):
                calls.append(argv)
                with (state / "idle.err.log").open("a", encoding="utf-8") as handle:
                    handle.write("listening on INBOX, resuming from uid 7\n")
                return subprocess.CompletedProcess(argv, code, "", "")
            return apply_runner(argv, cwd, text, capture_output)
        return runner

    up.apply_plan(via_installer, repo=applied, runner=installer_exit(10), wait_seconds=0)
    installer_at = next(i for i, a in enumerate(calls) if a[0].endswith("scripts/install.sh"))
    check("installer exit 10 (EX_CHANGED) is success: apply goes on to restart the services",
          ["systemctl", "--user", "restart", "paynani-idle.service", "paynani-dispatch.service"]
          in calls[installer_at:], str(calls))
    for code in (1, 64, 78):
        calls.clear()
        try:
            up.apply_plan(via_installer, repo=applied, runner=installer_exit(code), wait_seconds=0)
            stopped = False
        except up.ApplyError as exc:
            stopped = f"exit {code}" in str(exc)
        check(f"installer exit {code} still stops apply before any restart",
              stopped is True and not any(a[:3] == ["systemctl", "--user", "restart"] for a in calls), str(calls))
    calls.clear()

    # #451: a plan that restarts only PaynaniWeb never restarts the listener, so no
    # fresh 'resuming from uid N' line is coming. --apply waited 40 s for one and
    # failed after a good upgrade; now it checks the disk version and healthcheck.
    def web_only_runner(argv, cwd, text, capture_output):
        argv = [str(value) for value in argv]
        calls.append(argv)
        if argv[:3] == ["systemctl", "--user", "list-units"]:
            return subprocess.CompletedProcess(argv, 0, "paynani-web.service loaded active running\n", "")
        if argv[:2] == ["systemctl", "--user"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return apply_runner(argv, cwd, text, capture_output)

    log_before = (state / "idle.err.log").read_text(encoding="utf-8")
    web_only = dict(apply, restart_units=[up.WEB], reinstall=False)
    try:
        up.apply_plan(web_only, repo=applied, runner=web_only_runner, wait_seconds=0)
        web_ok = True
    except up.ApplyError as exc:
        web_ok = str(exc)
    check("a plan that restarts only PaynaniWeb applies without waiting for the listener (#451)", web_ok is True, web_ok)
    check("... it restarted PaynaniWeb, not the listener",
          ["systemctl", "--user", "restart", "paynani-web.service"] in calls
          and not any("paynani-idle.service" in a for a in calls), str(calls))
    check("... and still ran healthcheck", any(a and a[0].endswith("scripts/healthcheck.py") for a in calls), str(calls))
    check("... with no new listener line written", log_before == (state / "idle.err.log").read_text(encoding="utf-8"))
    shown = up.render(web_only)
    check("... and the printed steps say the same: no listener line to wait for",
          "verify disk version and healthcheck (the plan does not restart the listener)" in shown
          and "resuming from uid N" not in shown, shown)
    calls.clear()
    listener_plan = dict(apply, restart_units=[up.LISTENER, up.WEB], reinstall=False)
    check("a plan that restarts the listener still prints the listener check",
          "verify disk and listener version, a new 'resuming from uid N', and healthcheck" in up.render(listener_plan))
    try:
        up.apply_plan(listener_plan, repo=applied, runner=web_only_runner, wait_seconds=0)
        waited = False
    except up.ApplyError as exc:
        waited = "listener verification timed out" in str(exc)
    check("a plan that does restart the listener still waits for its 'resuming from uid' line", waited is True)
    calls.clear()

    refused = dict(apply, unknown=["mystery.bin"])
    before_calls = len(calls)
    try:
        up.apply_plan(refused, repo=applied, runner=apply_runner, wait_seconds=0)
        refused_unknown = False
    except up.ApplyError:
        refused_unknown = True
    check("apply refuses unknown files before running a command",
          refused_unknown and len(calls) == before_calls)
    # --- a release that changes only VERSION restarts every service -------------
    # Both services record the version they loaded and version_drift compares
    # both, so a plan that restarted only the listener left doctor in `warning`
    # after following it exactly. Found preparing 0.9.1, whose only runtime
    # change was VERSION.
    only = tmp / "only-version"
    only.mkdir()
    sh(only, "init", "-q")
    write(only, "VERSION", "1.0.0\n")
    write(only, ".gitignore", "install.manifest\n")
    sh(only, "add", "-A")
    sh(only, "commit", "-q", "-m", "one")
    sh(only, "tag", "v1.0.0")
    write(only, "VERSION", "1.0.1\n")
    sh(only, "add", "-A")
    sh(only, "commit", "-q", "-m", "patch")
    sh(only, "tag", "v1.0.1")
    manifest_for(only)
    patch = up.plan("v1.0.0", "v1.0.1", repo=only, runtime="claudecode", system="Linux")
    check("a VERSION-only release restarts the listener, its instances, dispatcher, SMS gateway and PaynaniWeb",
          [u for u, _ in patch["restart_units"]]
          == ["paynani-idle.service", "paynani-idle@*.service", "paynani-dispatch.service",
              "paynani-sms*.service", "paynani-web*.service"],
          str(patch["restart_units"]))
    check("and names both services in the commands",
          any("paynani-dispatch.service" in c for c in up.commands(patch)))
    # --- #329: a planner run from the target's tree still honours PAYNANI_STATE --
    import os
    other = tmp / "other-clone"
    kept = os.environ.pop("PAYNANI_STATE", None)
    try:
        check("another repo's state dir is <repo>/state without an override",
              up._state_dir(other) == other / "state")
        os.environ["PAYNANI_STATE"] = str(tmp / "elsewhere")
        check("another repo's state dir follows PAYNANI_STATE when it is set",
              up._state_dir(other) == tmp / "elsewhere")
        check("and the installed clone's state dir is unchanged by that rule",
              up._state_dir(up.ROOT) == up.harness_paths.state_dir())
    finally:
        os.environ.pop("PAYNANI_STATE", None)
        if kept is not None:
            os.environ["PAYNANI_STATE"] = kept

    # --- a shared harness module restarts the account listeners too (#336) ------
    # harness/event.py is imported by paynani-idle@<id> as well; the 0c3c907
    # plan restarted only the main listener and doctor stayed in `warning` for
    # every account until they were restarted by hand.
    write(only, "harness/event.py", "# v1.0.2\n")
    write(only, "VERSION", "1.0.1\n")
    sh(only, "add", "-A")
    sh(only, "commit", "-q", "-m", "event")
    sh(only, "tag", "v1.0.2")
    shared = up.plan("v1.0.1", "v1.0.2", repo=only, runtime="claudecode", system="Linux")
    units = [u for u, _ in shared["restart_units"]]
    check("harness/event.py restarts the listener, its instances, the dispatcher and the gateway",
          all(u in units for u in ("paynani-idle.service", "paynani-idle@*.service",
                                   "paynani-dispatch.service", "paynani-sms*.service")), str(units))
    check("and the commands restart the account instances",
          any("paynani-idle@*.service" in c and "xargs -r systemctl --user restart" in c
              for c in up.commands(shared)), str(up.commands(shared)))

    # --- PaynaniWeb (PRD #434, T2 of #435) -------------------------------------
    for path in ("scripts/paynani_web.py", "scripts/paynani_lib/web/app.py", "scripts/paynani_lib/web/users.py",
                 "scripts/paynani_lib/i18n.py", "scripts/paynani_lib/guard.py", "scripts/paynani_lib/brand.py",
                 "scripts/paynani_lib/i18n_data/es_MX.py"):
        c = up.classify(path)
        check(f"{path} -> restart PaynaniWeb", (c["verb"], c["unit"], c["label"])
              == ("restart", "paynani-web*.service", "com.paynani.web*"), str(c))
    c = up.classify("scripts/paynani_lib/sms/config.py")
    check("sms/config.py restarts the gateway and PaynaniWeb (both read sms.env at start)",
          (c["verb"], c["unit"]) == ("restart", "gateway-web"), str(c))
    check("assets are read on each request: nothing restarts",
          up.classify("scripts/paynani_lib/assets/web.css")["verb"] == "none")
    check("paynani-web.service has its systemd row",
          up.classify("systemd/paynani-web.service")["verb"] == "reinstall-and-restart")

    # A host that already has the gateway, upgrading to a version with PaynaniWeb
    # and no user yet (#435: Metis asked for this one in Q-T2-2).
    web = tmp / "web-host"
    web.mkdir()
    sh(web, "init", "-q")
    write(web, "VERSION", "1.0.0\n")
    write(web, "scripts/sms_gateway.py", "# gateway\n")
    write(web, ".gitignore", "install.manifest\nweb/\n")
    sh(web, "add", "-A")
    sh(web, "commit", "-q", "-m", "one")
    sh(web, "tag", "v1.0.0")
    write(web, "VERSION", "1.1.0\n")
    write(web, "scripts/paynani_web.py", "# web\n")
    write(web, "scripts/paynani_lib/sms/config.py", "# web port\n")
    write(web, "systemd/paynani-web.service", "[Service]\n")
    sh(web, "add", "-A")
    sh(web, "commit", "-q", "-m", "web")
    sh(web, "tag", "v1.1.0")
    sms_unit = web / "paynani-sms.service"
    sms_unit.write_text("[Service]\n", encoding="utf-8")
    manifest_for(web, sms_unit)
    old_user = __import__("os").environ.pop("PAYNANI_WEB_USER", None)
    try:
        wp = up.plan("v1.0.0", "v1.1.0", repo=web, runtime="claudecode", system="Linux")
        check("a host with the gateway upgrading to PaynaniWeb: the plan is computed", wp["ok"], wp["reason"])
        check("it reinstalls (the new unit) and restarts the gateway and PaynaniWeb",
              wp["reinstall"] and {"paynani-sms*.service", "paynani-web*.service"}
              <= {u for u, _ in wp["restart_units"]}, str(wp["restart_units"]))
        check("and says PaynaniWeb has no user yet (FR-4)", wp["web_user_missing"] is True)
        text = up.render(wp)
        check("render names `paynani web user add`", "scripts/paynani web user add --email" in text, text)
        check("after the steps, not instead of them",
              text.index("run, in this order:") < text.index("PaynaniWeb has no user yet"), text)
        check("the Linux commands restart PaynaniWeb by pattern",
              any("'paynani-web*.service'" in c for c in up.commands(wp)), str(up.commands(wp)))
        (web / "web").mkdir()
        (web / "web" / "user.json").write_text("{}", encoding="utf-8")
        check("with the user file there, no warning",
              up.plan("v1.0.0", "v1.1.0", repo=web, runtime="claudecode", system="Linux")["web_user_missing"] is False)
        (web / "web" / "user.json").unlink()
        manifest_for(web)
        nogw = up.plan("v1.0.0", "v1.1.0", repo=web, runtime="claudecode", system="Linux")
        check("a host without the gateway gets no PaynaniWeb warning", nogw["web_user_missing"] is False)
        check("and render does not mention it", "PaynaniWeb has no user" not in up.render(nogw))
        manifest_for(web, sms_unit)
        check("a target without PaynaniWeb gives no warning either",
              up.plan("v1.0.0", "v1.0.0", repo=web, runtime="claudecode", system="Linux")["web_user_missing"] is False)
        mac = web / "com.paynani.sms.plist"
        mac.write_text("<plist/>", encoding="utf-8")
        manifest_for(web, mac)
        check("on macOS the gateway's LaunchAgent counts as having the gateway",
              up.plan("v1.0.0", "v1.1.0", repo=web, runtime="claudecode", system="Darwin")["web_user_missing"] is True)
    finally:
        if old_user is not None:
            __import__("os").environ["PAYNANI_WEB_USER"] = old_user
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- restarts_between: the table doctor asks before calling a commit drift (#451) ---
rb = pathlib.Path(tempfile.mkdtemp(prefix="paynani-restarts-"))
sh(rb, "init", "-q")
write(rb, "VERSION", "1.0.0\n")
write(rb, "README.md", "a\n")
sh(rb, "add", "-A")
sh(rb, "commit", "-q", "-m", "base")
sh(rb, "tag", "base")
steps = (("docs", "README.md", "b\n"), ("web", "scripts/paynani_lib/web/app.py", "x = 1\n"),
         ("dispatcher", "harness/dispatch.py", "x = 1\n"), ("mystery", "mystery.bin", "?\n"))
for tag, rel, text in steps:
    write(rb, rel, text)
    sh(rb, "add", "-A")
    sh(rb, "commit", "-q", "-m", tag)
    sh(rb, "tag", tag)
check("restarts_between: docs only -> nothing to restart", up.restarts_between("base", "docs", repo=rb, system="Linux") == set())
web_units = up.restarts_between("docs", "web", repo=rb, system="Linux")
check("restarts_between: a web file -> PaynaniWeb, not the listener nor the dispatcher",
      up.WEB in web_units and up.LISTENER not in web_units and up.DISPATCHER not in web_units, str(web_units))
check("restarts_between: harness/dispatch.py -> the dispatcher",
      up.DISPATCHER in up.restarts_between("web", "dispatcher", repo=rb, system="Linux"))
check("restarts_between: a file the table does not know -> cannot tell (None)",
      up.restarts_between("dispatcher", "mystery", repo=rb, system="Linux") is None)
check("restarts_between: a commit this clone does not have -> None",
      up.restarts_between("0" * 40, "docs", repo=rb, system="Linux") is None)

# #546: runtime.env as the installer writes it, with quotes, still names the runtime.
import os  # noqa: E402
_saved_env = os.environ.pop("PAYNANI_RUNTIME", None)
_real_runtime_env = up.harness_paths.runtime_env
_tmp_env = pathlib.Path(tempfile.mkdtemp()) / "runtime.env"
up.harness_paths.runtime_env = lambda *a, **k: _tmp_env
for text, want in (('PAYNANI_RUNTIME="openclaw"\n', "openclaw"),
                   ("PAYNANI_RUNTIME='hermes'\n", "hermes"),
                   ("PAYNANI_RUNTIME=codex\n", "codex"),
                   ('# generated\nPAYNANI_RUNTIME = "OpenClaw" \n', "openclaw"),
                   ('PAYNANI_RUNTIME="auto"\n', None),
                   ("OTHER=1\n", None)):
    _tmp_env.write_text(text, encoding="utf-8")
    check(f"selected_runtime: {text.strip()!r} -> {want!r}", up.selected_runtime() == want, repr(up.selected_runtime()))
# version.sh runs the target's planner from a temporary copy with --repo set to the
# clone: the runtime comes from that clone's runtime.env, not from the copy's own
# location (John, 0.18.0 upgrade: "selected runtime is unknown").
_tmp_env.write_text('PAYNANI_RUNTIME="hermes"\n', encoding="utf-8")
_other_repo = pathlib.Path(tempfile.mkdtemp())
(_other_repo / "runtime.env").write_text('PAYNANI_RUNTIME="openclaw"\n', encoding="utf-8")
check("selected_runtime(repo=<clone>) reads the clone's runtime.env",
      up.selected_runtime(repo=_other_repo) == "openclaw", repr(up.selected_runtime(repo=_other_repo)))
_empty_repo = pathlib.Path(tempfile.mkdtemp())
check("selected_runtime(repo=<clone>) without runtime.env is unknown, not this copy's",
      up.selected_runtime(repo=_empty_repo) is None, repr(up.selected_runtime(repo=_empty_repo)))
up.harness_paths.runtime_env = _real_runtime_env
if _saved_env is not None:
    os.environ["PAYNANI_RUNTIME"] = _saved_env

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
