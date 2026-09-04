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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from idle_listener import KEEPALIVE_OPTIONS, describe, decode_hdr, keepalive
from roster import (notifier_headers, notifiers, roster_addresses,
                    roster_entries, sender_is_listed)


def message(from_header, **extra):
    msg = email.message.EmailMessage()
    msg["From"] = from_header
    for key, value in extra.items():
        msg[key.replace("_", "-")] = value
    return msg


def check(condition, label):
    if not condition:
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

        # A roster with no notifier section must behave exactly as before.
        check(notifiers(roster) == [],
              "a roster with no notifier section declares none")
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

    # Whichever platform this is, one of the two idle names must resolve. If
    # neither does, keepalive() runs, logs nothing, and protects nothing.
    idle_names = [n for n in ("TCP_KEEPIDLE", "TCP_KEEPALIVE") if hasattr(socket, n)]
    check(idle_names, "this platform exposes an idle timer under one of the two names")

    # And it has to reach the socket. Asserting on the table alone would pass on
    # a keepalive() that never called setsockopt.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        keepalive(probe)
        check(probe.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1,
              "SO_KEEPALIVE is on after keepalive()")
        for name, value in KEEPALIVE_OPTIONS:
            option = getattr(socket, name, None)
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
