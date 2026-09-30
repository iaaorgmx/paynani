#!/usr/bin/env python3
"""
Tests for `paynani doctor` with additional accounts (#276, #284 point 1).

Two properties matter. With no accounts.json the report is exactly what it
was, row for row (the PRD's criterion 7). With accounts, each one gets its own
rows under its own name, and an account that is down is a warning that says
which account, without touching the rows of the agent's own mailbox.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harness"))

home = Path(tempfile.mkdtemp())
os.environ["PAYNANI_ENV"] = str(home / ".env")
os.environ["PAYNANI_STATE"] = str(home / "state")

import healthcheck  # noqa: E402
from paynani_lib import diagnostics  # noqa: E402

passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        passed += 1
        print(f"ok   {label}")
    else:
        failed += 1
        print(f"FAIL {label}\n     expected {expected!r}\n     got      {actual!r}")


state = home / "state"
healthcheck.STATE_DIR = state
units = {}


def unit_state(unit):
    return units.get(unit, "inactive")


def rows():
    with mock.patch.object(healthcheck, "unit_state", unit_state), \
            mock.patch.object(diagnostics.sys, "platform", "linux"):
        return {c["name"]: c for c in diagnostics._account_checks()}


def account(aid, **kw):
    base = {"id": aid, "email": f"{aid}@d.example", "imap": {"host": "mail.d.example"},
            "password_env": f"PAYNANI_ACCOUNT_{aid.upper()}_PASSWORD"}
    base.update(kw)
    return base


def write(*items):
    (home / "accounts.json").write_text(json.dumps({"accounts": list(items)}), encoding="utf-8")


def heartbeat(aid, **kw):
    path = state / "accounts" / aid / "idle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"heartbeat_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "version": healthcheck.disk_version(), "commit": healthcheck.disk_commit(),
            "imap_current_backoff_seconds": 0}
    data.update(kw)
    path.write_text(json.dumps(data), encoding="utf-8")


# --- no accounts.json: nothing new ----------------------------------------------

check("no accounts.json adds no rows", {}, rows())

# --- a healthy account ------------------------------------------------------------

(home / "rosters").mkdir()
(home / "rosters" / "ventas.md").write_text("| Name | Email |\n|---|---|\n| Ana | ana@c.example |\n",
                                            encoding="utf-8")
write(account("ventas"))
units["paynani-idle@ventas.service"] = "active"
heartbeat("ventas")
r = rows()
check("each account gets four rows under its own name",
      ["account:ventas:imap_telemetry", "account:ventas:listener",
       "account:ventas:roster", "account:ventas:version_drift"], sorted(r))
check("a healthy account is ok everywhere", {"ok"}, {c["status"] for c in r.values()})
check("the listener row names the account's address", True,
      "ventas@d.example" in r["account:ventas:listener"]["summary"])
check("the roster row counts that account's roster", "roster has 1 address(es)",
      r["account:ventas:roster"]["summary"])

# --- an account that is down --------------------------------------------------------

units["paynani-idle@ventas.service"] = "failed"
r = rows()
check("a failed account listener is a warning, not blocked", "warning",
      r["account:ventas:listener"]["status"])
check("and its fix restarts that account's unit", "systemctl --user restart paynani-idle@ventas.service",
      r["account:ventas:listener"]["next_command"])
units["paynani-idle@ventas.service"] = "active"

heartbeat("ventas", imap_current_backoff_seconds=40)
check("an account retrying IMAP is a warning", "warning", rows()["account:ventas:imap_telemetry"]["status"])
heartbeat("ventas", version="0.0.1")
r = rows()
check("an account running another version is a warning", "warning", r["account:ventas:version_drift"]["status"])
check("whose fix restarts that account's unit", "systemctl --user restart paynani-idle@ventas.service",
      r["account:ventas:version_drift"]["next_command"])
heartbeat("ventas")

# --- rosters --------------------------------------------------------------------------

write(account("ventas"), account("soporte"))
units["paynani-idle@soporte.service"] = "active"
heartbeat("soporte")
r = rows()
check("a missing roster is a warning for that account only", ("warning", "ok"),
      (r["account:soporte:roster"]["status"], r["account:ventas:roster"]["status"]))
(home / "rosters" / "soporte.md").write_text("| Name | Email |\n|---|---|\n", encoding="utf-8")
check("an empty roster is a warning", "warning", rows()["account:soporte:roster"]["status"])

# --- disabled, never started, and a bad file ------------------------------------------------

write(account("ventas", enabled=False))
r = rows()
check("a disabled account is one ok row that says so", (["account:ventas"], "ok"),
      (list(r), r["account:ventas"]["status"]))

write(account("nuevo"))
r = rows()
check("an account whose listener never ran is unknown, not ok",
      ("unknown", "unknown"),
      (r["account:nuevo:imap_telemetry"]["status"], r["account:nuevo:version_drift"]["status"]))

(home / "accounts.json").write_text("{ roto", encoding="utf-8")
r = rows()
check("an unusable accounts.json is one blocked row", (["accounts"], "blocked"),
      (list(r), r["accounts"]["status"]))

# --- the main account's rows are untouched ---------------------------------------------------

check("the main imap_telemetry row keeps its name", "imap_telemetry",
      diagnostics._imap_telemetry_check({"heartbeat_at": None})["name"])
stale = {"heartbeat_at": "2026-01-01T00:00:00Z", "heartbeat_age_seconds": 10 ** 6}
check("and its fix still restarts the main listener",
      f"systemctl --user restart {healthcheck.LISTENER_UNIT}",
      diagnostics._imap_telemetry_check(stale)["next_command"])

# --- healthcheck.py ------------------------------------------------------------------------

(home / "accounts.json").unlink()
with mock.patch.object(healthcheck, "unit_state", unit_state), \
        mock.patch.object(healthcheck.platform, "system", lambda: "Linux"):
    check("healthcheck: no accounts.json, no accounts", {"accounts": [], "error": None},
          healthcheck.accounts_facts())
    write(account("ventas"), account("soporte"))
    units["paynani-idle@ventas.service"] = "active"
    units["paynani-idle@soporte.service"] = "failed"
    facts = {"accounts": healthcheck.accounts_facts()}
    warned = healthcheck.account_warnings(facts)
    check("healthcheck: a failed account is a warning naming it", True,
          "account soporte (soporte@d.example): listener is failed" in warned)
    check("healthcheck: a healthy account adds no warning", False,
          any("account ventas" in w and "listener" in w for w in warned))
    check("healthcheck: an empty roster is a warning", True,
          "account soporte (soporte@d.example): roster is missing or empty" in warned)
    (home / "accounts.json").write_text("{ roto", encoding="utf-8")
    facts = {"accounts": healthcheck.accounts_facts()}
    check("healthcheck: a bad accounts.json is a warning, not a crash", True,
          healthcheck.account_warnings(facts)[0].startswith("accounts.json is not usable"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
