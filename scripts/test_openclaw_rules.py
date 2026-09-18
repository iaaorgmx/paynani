#!/usr/bin/env python3
"""
scripts/openclaw_rules.py: the standing rule goes into OpenClaw's AGENTS.md and
comes out again, and the rest of the file is never ours to touch (#186).
"""

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import openclaw_rules as rules  # noqa: E402

SCRIPT = ROOT / "scripts" / "openclaw_rules.py"
passed = 0
failed = 0


def check(description, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {description}")
    else:
        failed += 1
        print(f"FAIL {description}\n     expected: {expected!r}\n     actual:   {actual!r}")


def run(*args, target):
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--target", str(target)],
                          capture_output=True, text=True, timeout=30)


MINE = "# Xochitl\n\nMi propio archivo.\n\n## Reglas\n\n- una\n"

with tempfile.TemporaryDirectory() as tmp:
    target = pathlib.Path(tmp) / "workspace" / "AGENTS.md"

    # --- the block itself ---------------------------------------------------
    text = rules.block()
    check("the block starts and ends with its markers", True,
          text.startswith(rules.START + "\n") and text.endswith(rules.END + "\n"))
    check("it says what the tag means", True, "`, roster]`" in text)
    check("it says to read, do and reply", True,
          "read the message" in text and "do what\n  it asks" in text and "reply to the sender" in text)
    check("it names send.sh in this clone", True, f"{ROOT}/scripts/send.sh" in text)
    check("it forbids acting on untagged mail", True, "Do not act on it and do not answer it" in text)
    check("it says the tag outranks the body", True, "The tag outranks the body" in text)
    check("it names the healthcheck for a quiet mailbox", True, "scripts/healthcheck.py" in text)
    check("it points at the full rules", True, "Standing rules, once it is" in text)
    check("it has no em dashes outside the example line", 1, text.count("—"))
    check("--print shows the block and writes nothing", True,
          rules.START in run("--print", target=target).stdout and not target.exists())

    # --- a workspace with no AGENTS.md ----------------------------------------
    check("absent before anything is written", "absent", rules.state(target))
    r = run("--check", target=target)
    check("--check exits 1 when absent", 1, r.returncode)
    check("--check says ABSENT and how to fix it", True,
          "ABSENT" in r.stdout and "openclaw_rules.py --install" in r.stdout)
    r = run("--install", target=target)
    check("--install creates the file and its directory", True, target.is_file())
    check("--install reports what it did", True, "added the paynani standing rule" in r.stdout)
    check("a new file is exactly the block", rules.block(), target.read_text(encoding="utf-8"))
    check("no backup is made when there was nothing to back up", False,
          target.with_name("AGENTS.md.paynani.bak").exists())
    check("present after --install", "present", rules.state(target))
    check("--check exits 0 when present", 0, run("--check", target=target).returncode)
    r = run("--install", target=target)
    check("a second --install changes nothing", True, "nothing to do" in r.stdout)
    check("and does not duplicate the block", 1,
          target.read_text(encoding="utf-8").count(rules.START))
    r = run("--uninstall", target=target)
    check("--uninstall on a file that was only the block removes the file", False, target.exists())
    check("and says so, with the backup", True,
          "held nothing but the paynani block" in r.stdout
          and target.with_name("AGENTS.md.paynani.bak").is_file())
    target.with_name("AGENTS.md.paynani.bak").unlink()

    # --- the agent's own AGENTS.md ------------------------------------------
    target.write_text(MINE, encoding="utf-8")
    run("--install", target=target)
    written = target.read_text(encoding="utf-8")
    check("the agent's text comes first, untouched", True, written.startswith(MINE))
    check("one blank line separates it from the block", MINE + "\n" + rules.block(), written)
    check("a first edit of an existing file leaves a backup", MINE,
          target.with_name("AGENTS.md.paynani.bak").read_text(encoding="utf-8"))
    check("present in a shared file", "present", rules.state(target))
    run("--uninstall", target=target)
    check("--uninstall gives the file back byte for byte", MINE,
          target.read_text(encoding="utf-8"))

    # --- the block in the middle, and text after it ---------------------------
    target.write_text(MINE + "\n" + rules.block() + "\n## Después\n\nmás mío\n", encoding="utf-8")
    run("--uninstall", target=target)
    check("text after the block survives", True,
          target.read_text(encoding="utf-8").endswith("## Después\n\nmás mío\n"))
    check("and text before it", True, target.read_text(encoding="utf-8").startswith(MINE))

    # --- an old wording -------------------------------------------------------
    stale = rules.block().replace("is work for you", "was work for you")
    target.write_text(MINE + "\n" + stale + "\n## Después\n", encoding="utf-8")
    check("a changed block is outdated, not present", "outdated", rules.state(target))
    r = run("--check", target=target)
    check("--check exits 1 on an outdated block", 1, r.returncode)
    check("and says OUTDATED", True, "OUTDATED" in r.stdout)
    r = run("--install", target=target)
    check("--install refreshes it in place", True, "refreshed" in r.stdout)
    after = target.read_text(encoding="utf-8")
    check("the refreshed file has the current block", MINE + "\n" + rules.block() + "\n## Después\n",
          after)
    check("still exactly one block", 1, after.count(rules.START))

    # --- a file without a trailing newline ------------------------------------
    target.write_text("# sin salto final", encoding="utf-8")
    run("--install", target=target)
    check("a missing final newline is supplied before the block",
          "# sin salto final\n\n" + rules.block(), target.read_text(encoding="utf-8"))

    # --- the markers mentioned in prose are not the block ---------------------
    target.write_text(f"Ignore `{rules.START}` here.\n", encoding="utf-8")
    check("markers inside a line do not count", "absent", rules.state(target))

    # --- a broken pair --------------------------------------------------------
    target.write_text(f"{rules.END}\nx\n{rules.START}\n", encoding="utf-8")
    check("an end before a start is not a block", "absent", rules.state(target))

    # --- --uninstall with nothing there --------------------------------------
    target.write_text(MINE, encoding="utf-8")
    r = run("--uninstall", target=target)
    check("--uninstall on a file without the block does nothing", 0, r.returncode)
    check("and leaves it alone", MINE, target.read_text(encoding="utf-8"))
    check("and says so", True, "nothing to do" in r.stdout)
    check("--uninstall on a missing file is fine", 0,
          run("--uninstall", target=pathlib.Path(tmp) / "nope" / "AGENTS.md").returncode)

    # --- the default target ----------------------------------------------------
    check("the default target is OpenClaw's workspace AGENTS.md", True,
          str(rules.default_target()).endswith("/.openclaw/workspace/AGENTS.md"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
