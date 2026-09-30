#!/usr/bin/env python3
"""Regression coverage for per-account listener service helpers."""

from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from paynani_lib import account_service  # noqa: E402

passed = failed = 0


def check(desc, condition, detail=""):
    global passed, failed
    if condition:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}" + (f"\n       {detail}" if detail else ""))
        failed += 1


check("safe account ids are accepted", account_service.validate_id("iris-1") == "iris-1")
check("digit-start account ids are accepted", account_service.validate_id("2x") == "2x")
try:
    account_service.validate_id("../iris")
    rejected = False
except account_service.AccountServiceError:
    rejected = True
check("path-like account ids are rejected", rejected)
try:
    account_service.validate_id("iris_1")
    rejected = False
except account_service.AccountServiceError:
    rejected = True
check("ids outside accounts.json's pattern are rejected", rejected)
try:
    account_service.validate_id("main")
    rejected = False
except account_service.AccountServiceError:
    rejected = True
check("the main account id is reserved", rejected)
check("systemd instance unit uses the account id",
      account_service.systemd_unit("iris") == "paynani-idle@iris.service")
check("launchd label uses the account id",
      account_service.launchd_label("iris") == "com.paynani.idle.iris")

with tempfile.TemporaryDirectory() as td:
    state = pathlib.Path(td) / "state"
    env = pathlib.Path(td) / "mail.env"
    env.write_text("PAYNANI_EMAIL=agent@example.invalid\n", encoding="utf-8")
    old_env, old_state = account_service.env_file, account_service.state_dir
    try:
        account_service.env_file = lambda: env
        account_service.state_dir = lambda: state
        plist = account_service.launchd_plist("iris", python="/usr/bin/python3", runtime="openclaw")
    finally:
        account_service.env_file, account_service.state_dir = old_env, old_state

check("launchd plist points idle_listener at the selected account",
      plist["ProgramArguments"][:4]
      == ["/usr/bin/python3", str(ROOT / "scripts" / "idle_listener.py"), "--account", "iris"],
      str(plist["ProgramArguments"]))
check("launchd plist leaves account paths to idle_listener --account",
      "--state" not in plist["ProgramArguments"]
      and "--roster" not in plist["ProgramArguments"],
      str(plist["ProgramArguments"]))
check("launchd plist keeps the shared journal explicit",
      str(state / "events.jsonl") in plist["ProgramArguments"],
      str(plist["ProgramArguments"]))

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
