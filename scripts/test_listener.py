#!/usr/bin/env python3
"""Unit tests for roster matching and the notification line.

The `roster` tag is the whole authorisation model: it is what tells the agent
a message may be acted on. A false positive here means acting on a stranger's
instructions, so most of these tests are about what must *not* be tagged.
"""

import email
import pathlib
import socket
import sys
import tempfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import idle_listener
from idle_listener import (KEEPALIVE_OPTIONS, decode_hdr, describe, keepalive,
                           note_reconnect, resolve_keepalive_option, save_state)
from roster import (notifier_headers, notifiers, roster_addresses,
                    roster_entries, sender_is_listed)
from failure_diagnostics import print_diagnostics


def message(from_header, **extra):
    msg = email.message.EmailMessage()
    msg["From"] = from_header
    for key, value in extra.items():
        msg[key.replace("_", "-")] = value
    return msg


def check(condition, label):
    if not condition:
        print_diagnostics()
        raise AssertionError(label)


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)

        roster = tmp / "roster.md"
        roster.write_text(
            "# Addresses this agent may write to unattended.\n"
            "\n"
            "| Name | Email | Type |\n"
            "| --- | --- | --- |\n"
            "| Julian Flores | jjulianfe@gmail.com | Human |\n"
            "| Spaced Out |  Spaced@Example.COM | AI Agent |\n"
            "| AI Agent | Reordered Contact | reordered@example.net |\n"
            "bare@example.com\n",
            encoding="utf-8",
        )
        allowed = roster_addresses(roster)

        check(allowed == {"jjulianfe@gmail.com", "spaced@example.com",
                          "reordered@example.net", "bare@example.com"},
              f"roster parsed to {allowed}")

        # --- the file is roster.md, with a Type column ----------------------
        #
        # The address is no longer the last field. Every earlier parser took the
        # field after the last pipe, which held for `Name | email` and breaks the
        # moment anything follows the address -- the Type column does. Taking
        # `Human` yields a non-address, the row contributes nobody, and that
        # person is silently off the list: sending to them is refused and their
        # mail stops being tagged `roster`, which is indistinguishable from them
        # never having written.
        table = tmp / "roster-table.md"
        table.write_text(
            "# Roster\n"
            "\n"
            "| Name | Email | Type |\n"
            "|---|---|---|\n"
            "| Julian Flores | jjulianfe@gmail.com | Human |\n"
            "| Metis Claude-Tob | metis.claude.tob@gmail.com | AI Agent |\n"
            "Legacy Plain | legacy@example.com\n",
            encoding="utf-8",
        )
        from_table = roster_addresses(table)
        check(from_table == {"jjulianfe@gmail.com", "metis.claude.tob@gmail.com",
                             "legacy@example.com"},
              f"typed markdown table parsed to {from_table}")
        check("human" not in from_table and "aiagent" not in from_table,
              "the Type column must not become an allowlist entry")
        check("email" not in from_table,
              "a table header row must not become an allowlist entry")
        check(sender_is_listed(message("Julian Flores <jjulianfe@gmail.com>"), from_table),
              "a row with a trailing Type column is still authorised")

        entries = roster_entries(table)
        check([e["type"] for e in entries] == ["Human", "AI Agent", ""],
              f"types read back as {[e['type'] for e in entries]}")
        check(entries[0]["name"] == "Julian Flores",
              "the name is the field before the address")

        # --- must be tagged -------------------------------------------------
        check(sender_is_listed(message("Julian Flores <jjulianfe@gmail.com>"), allowed),
              "listed sender with display name")
        check(sender_is_listed(message("<JJulianFe@Gmail.com>"), allowed),
              "matching is case-insensitive")
        check(sender_is_listed(message("bare@example.com"), allowed),
              "roster line holding only an address")
        check(sender_is_listed(message("reordered@example.net"), allowed),
              "reordered table row still finds the address")

        # --- must not be tagged ---------------------------------------------
        check(not sender_is_listed(message("stranger@example.com"), allowed),
              "unlisted sender")


        # --- notifiers (#16) -------------------------------------------------
        # A coordination platform mails on behalf of many people, and names the
        # one it is acting for in a header. Declaring it says which address, which
        # header, and which column of the roster to compare against. It grants
        # nothing on its own: the handle must already be recorded for somebody on
        # the list.
        notifier_roster = pathlib.Path(tmp) / "notifiers.md"
        notifier_roster.write_text(
            "| Name | Email | Type | GitHub |\n"
            "|---|---|---|---|\n"
            "| Julian Flores | jjulianfe@gmail.com | Human | julianflores |\n"
            "| Xochitl | xochitl@example.org | AI Agent | xochitl-iaamx |\n"
            "\n"
            "## Notifiers\n"
            "\n"
            "| Address | Header | Column |\n"
            "|---|---|---|\n"
            "| notifications@github.com | X-GitHub-Sender | GitHub |\n",
            encoding="utf-8")
        n_allowed = roster_addresses(notifier_roster)
        n_entries = roster_entries(notifier_roster)
        n_list = notifiers(notifier_roster)

        check(len(n_list) == 1 and n_list[0]["header"] == "X-GitHub-Sender",
              "the notifier is read with its header and column")
        check(notifier_headers(n_list) == ["X-GitHub-Sender"],
              "and the header is what the listener will ask the server for")
        check("notifications@github.com" not in n_allowed,
              "a notifier address is never a send destination")
        check(n_allowed == {"jjulianfe@gmail.com", "xochitl@example.org"},
              "and the contacts above it are unaffected")

        def listed(from_header, **extra):
            return sender_is_listed(message(from_header, **extra),
                                    n_allowed, n_entries, n_list)

        check(listed("notifications@github.com", **{"X-GitHub-Sender": "xochitl-iaamx"}),
              "a declared notifier speaks for a handle recorded on the roster")
        check(listed("notifications@github.com", **{"X-GitHub-Sender": "XoChitl-IaaMx"}),
              "and handles compare case-insensitively")
        check(listed("notifications@github.com", **{"X-GitHub-Sender": "@julianflores"}),
              "and a leading @ on the handle is tolerated")
        check(not listed("notifications@github.com", **{"X-GitHub-Sender": "a-stranger"}),
              "an unrecorded handle grants nothing, notifier or not")
        check(not listed("notifications@github.com"),
              "and the notifier address alone grants nothing without the header")
        check(not listed("noreply@jira.example.com", **{"X-GitHub-Sender": "julianflores"}),
              "an undeclared sender carrying the header grants nothing")
        check(listed("Julian Flores <jjulianfe@gmail.com>"),
              "and a person on the list is unaffected by any of it")

        # A roster with no notifier section and no GitHub column behaves as before.
        check(notifiers(roster) == [],
              "a roster with no notifier section and no GitHub column declares none")

        # --- the GitHub column is the declaration (#188) ---------------------
        # Nine of ten hosts had handles in a GitHub column and no `## Notifiers`
        # row, so every GitHub notification, the team's channel, arrived untagged.
        # A handle in that column has no other purpose; recording it is the
        # decision, and the notifier follows from it.
        column_only = pathlib.Path(tmp) / "column_only.md"
        column_only.write_text(
            "| Name | Email | Type | GitHub |\n"
            "|---|---|---|---|\n"
            "| Metis Claude-Tob | metis.claude.tob@gmail.com | AI Agent | metisclaudetob |\n"
            "| Zeus Claude-Tob | zeus.claude.tob@gmail.com | AI Agent |  |\n",
            encoding="utf-8")
        c_list = notifiers(column_only)
        check(len(c_list) == 1 and c_list[0]["address"] == "notifications@github.com"
              and c_list[0]["header"] == "X-GitHub-Sender" and c_list[0]["column"] == "github",
              "a GitHub column with no Notifiers section declares GitHub's notifier")
        check(c_list[0].get("implied_by") == "github column",
              "and says where it came from")
        check(notifier_headers(c_list) == ["X-GitHub-Sender"],
              "so the listener asks the server for the header")
        c_allowed, c_entries = roster_addresses(column_only), roster_entries(column_only)
        check(sender_is_listed(message("Metis <notifications@github.com>",
                                       **{"X-GitHub-Sender": "metisclaudetob"}),
                               c_allowed, c_entries, c_list),
              "Xochitl's case: a GitHub notification from a recorded handle is roster mail")
        check(not sender_is_listed(message("notifications@github.com",
                                           **{"X-GitHub-Sender": "zeusclaudetob"}),
                                   c_allowed, c_entries, c_list),
              "an empty GitHub cell matches nobody")
        check(not sender_is_listed(message("notifications@github.com",
                                           **{"X-GitHub-Sender": "a-stranger"}),
                                   c_allowed, c_entries, c_list),
              "an unrecorded handle still grants nothing")
        check("notifications@github.com" not in c_allowed,
              "the implied notifier is not a send destination either")
        check(len(n_list) == 1, "an explicit GitHub row is not duplicated by the column")
        check("implied_by" not in n_list[0], "and the explicit row is the one kept")

        # The column is the declaration; a Notifiers section that declares
        # something else does not switch GitHub off, and no column implies nothing.
        other = pathlib.Path(tmp) / "other.md"
        other.write_text(
            "| Name | Email | GitHub |\n|---|---|---|\n| Ana | ana@example.org | ana-gh |\n\n"
            "## Notifiers\n\n| Address | Header | Column |\n|---|---|---|\n"
            "| jira@example.org | X-Jira-Author | Name |\n", encoding="utf-8")
        check([n["address"] for n in notifiers(other)]
              == ["jira@example.org", "notifications@github.com"],
              "a Notifiers table for another platform adds to the GitHub column, not instead of it")
        no_column = pathlib.Path(tmp) / "no_column.md"
        no_column.write_text("| Name | Email | Type |\n|---|---|---|\n| Ana | ana@example.org | Human |\n",
                             encoding="utf-8")
        check(notifiers(no_column) == [], "no GitHub column implies no notifier")
        check(not sender_is_listed(message("notifications@github.com",
                                           **{"X-GitHub-Sender": "ana-gh"}),
                                   roster_addresses(no_column), roster_entries(no_column),
                                   notifiers(no_column)),
              "and GitHub mail to such a roster stays untagged")
        spelled = pathlib.Path(tmp) / "spelled.md"
        spelled.write_text("| Nombre | Correo | github |\n|---|---|---|\n| Ana | ana@example.org | ana-gh |\n",
                           encoding="utf-8")
        check(len(notifiers(spelled)) == 1, "the column name is matched case-insensitively")
        check(not sender_is_listed(message("evil-jjulianfe@gmail.com"), allowed),
              "substring of a listed address must not match")
        check(not sender_is_listed(message("jjulianfe@gmail.com.attacker.net"), allowed),
              "listed address as a subdomain prefix must not match")
        check(not sender_is_listed(message(""), allowed), "empty From")
        check(not sender_is_listed(email.message.EmailMessage(), allowed), "absent From")

        # Reply-To is sender-controlled: a stranger must not borrow trust with it.
        check(not sender_is_listed(
                  message("stranger@example.com", Reply_To="jjulianfe@gmail.com"), allowed),
              "Reply-To must not confer roster status")

        # A missing roster tags nobody rather than everybody.
        check(roster_addresses(tmp / "absent.txt") == set(), "missing roster is empty")
        check(not sender_is_listed(message("jjulianfe@gmail.com"), set()),
              "empty roster tags nobody")

        # A comment naming an address must not authorise it.
        commented = tmp / "commented.txt"
        commented.write_text("# Julian Flores | jjulianfe@gmail.com\n", encoding="utf-8")
        check(roster_addresses(commented) == set(), "commented-out entry is not an entry")

        # --- the emitted line -----------------------------------------------
        trusted = describe("Julian Flores <jjulianfe@gmail.com>", "Prueba #3", "", trusted=True)
        plain = describe("Stranger <stranger@example.com>", "Prueba #3", "", trusted=False)

        check(", roster]" in trusted, f"trusted line must carry the tag: {trusted}")
        check("roster" not in plain, f"untrusted line must not: {plain}")
        check(trusted.startswith("[mail ") and plain.startswith("[mail "),
              "both lines keep the [mail ...] prefix the harness greps for")
        check("Prueba #3" in trusted, "subject survives into the line")

        # An RFC 2047 subject must not break the line the harness parses.
        encoded = decode_hdr("=?utf-8?B?UHJ1ZWJhIGRlIGNvcnJlbyDigJQgw7EsIMOhLCDCv3F1w6kgdGFsPw==?=")
        check(encoded == "Prueba de correo — ñ, á, ¿qué tal?", f"decoded to {encoded!r}")
        check("\n" not in describe("a@b.c", encoded, "", trusted=True),
              "one message is always one line")

        state = save_state(tmp / "idle.json", "INBOX", "42", 117)
        check(state["mailbox"] == "INBOX" and state["uidvalidity"] == "42"
              and state["last_uid"] == 117,
              "listener state still records mailbox, uidvalidity and uid")
        check("heartbeat_at" in state and state["heartbeat_at"].endswith("Z"),
              "listener state records a UTC heartbeat")

        telemetry = idle_listener.fresh_telemetry()
        state = note_reconnect(tmp / "idle.json", "INBOX", "42", 117, telemetry,
                               "connection lost (ConnectionError: fake server cut connection)", 5)
        check(state["reconnects"] == 1 and state["reconnects_last_hour"] == 1,
              "listener state counts reconnects in the current process and hour")
        check(state["last_reconnect_at"] and state["last_error"].startswith("connection lost"),
              "listener state records the latest reconnect time and error")
        check(state["backoff_seconds"] == 5,
              "listener state records the current IMAP reconnect backoff")

        class FakeIMAP:
            capabilities = ("IDLE",)

            def select(self, mailbox):
                return "OK", []

            def status(self, mailbox, fields):
                return "OK", [b"INBOX (UIDVALIDITY 42)"]

            def uid(self, command, *args):
                if command.lower() == "search":
                    return "OK", [b""]
                return "OK", []

            def logout(self):
                return "OK", []

        fake_env = tmp / "env"
        fake_env.write_text(
            "PAYNANI_IMAP_HOST=imap.example.test\n"
            "PAYNANI_IMAP_PORT=993\n"
            "PAYNANI_EMAIL=agent@example.test\n"
            "PAYNANI_PASSWORD=secret\n",
            encoding="utf-8",
        )
        cut_state = tmp / "cut-state.json"
        journal = tmp / "events.jsonl"
        original_save = idle_listener.save_state

        def save_and_stop(path, mailbox, validity, last_uid, telemetry=None):
            written = original_save(path, mailbox, validity, last_uid, telemetry)
            if telemetry and telemetry.get("reconnects"):
                idle_listener._stop = True
            return written

        idle_listener._stop = False
        try:
            with mock.patch.object(idle_listener, "connect", return_value=FakeIMAP()), \
                 mock.patch.object(idle_listener, "idle", side_effect=ConnectionError("fake server cut connection")), \
                 mock.patch.object(idle_listener, "save_state", side_effect=save_and_stop), \
                 mock.patch.object(idle_listener, "BACKOFF_MIN", 5), \
                 mock.patch.object(idle_listener, "BACKOFF_MAX", 5):
                idle_listener.run(fake_env, "INBOX", False, cut_state, tmp / "roster.md", journal)
        finally:
            idle_listener._stop = False
        recorded = idle_listener.load_state(cut_state)
        check(recorded["reconnects"] == 1 and recorded["reconnects_last_hour"] == 1,
              "a fake IMAP connection cut during IDLE is recorded as one reconnect")
        check(recorded["last_error"] == "connection lost (ConnectionError: fake server cut connection)",
              "the fake IMAP cut records the exact reconnect error")
        check(recorded["backoff_seconds"] == 5,
              "the fake IMAP cut records the retry backoff")

    # --- keepalive, the thing that makes a dead connection announce itself ----
    #
    # Behind NAT an idle connection is dropped without a FIN and the socket still
    # reads ESTAB, so nothing notices until something writes. These probes are
    # what write. The failure this guards is not a crash: naming only Linux's
    # TCP_KEEPIDLE leaves macOS with SO_KEEPALIVE on and the system default of
    # two hours, so no probe fires inside any useful window and the protection
    # silently falls back to IDLE_REFRESH. Silence is the failure mode the whole
    # feature exists to remove, so it has to be asserted, not assumed.
    names = [name for name, _ in KEEPALIVE_OPTIONS]
    check("TCP_KEEPIDLE" in names, "the Linux idle-timer name is asked for")
    check("TCP_KEEPALIVE" in names, "the macOS idle-timer name is asked for too")
    check(len(names) == len(set(names)), f"no option is set twice: {names}")

    # Whichever platform this is, one of the two idle names must resolve. Use
    # the product's resolver rather than hasattr(socket, ...): Apple Python 3.9
    # omits TCP_KEEPALIVE even though Darwin exposes it as numeric option 0x10.
    # If neither resolves, keepalive() runs, logs nothing, and protects nothing.
    idle_names = [n for n in ("TCP_KEEPIDLE", "TCP_KEEPALIVE")
                  if resolve_keepalive_option(n) is not None]
    check(idle_names, "this platform exposes an idle timer under one of the two names")

    # And it has to reach the socket. Asserting on the table alone would pass on
    # a keepalive() that never called setsockopt.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        keepalive(probe)
        # BSD returns the SO_KEEPALIVE flag bit (8), while Linux normalises it
        # to 1. Both are true; zero is the only disabled value.
        check(probe.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0,
              "SO_KEEPALIVE is on after keepalive()")
        for name, value in KEEPALIVE_OPTIONS:
            option = resolve_keepalive_option(name)
            if option is None:
                continue
            got = probe.getsockopt(socket.IPPROTO_TCP, option)
            check(got == value, f"{name} is {value} after keepalive(), got {got}")
    finally:
        probe.close()

    print("listener tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
