#!/usr/bin/env python3
"""Unit tests for roster matching and the notification line.

The `roster` tag is the whole authorisation model: it is what tells the agent
a message may be acted on. A false positive here means acting on a stranger's
instructions, so most of these tests are about what must *not* be tagged.
"""

import email
import os
import pathlib
import socket
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import roster as roster_mod
from idle_listener import (KEEPALIVE_OPTIONS, PROCESS_COMMIT, PROCESS_VERSION, Listed,
                           decode_hdr, describe, fetch_since, keepalive,
                           record_imap_reconnect, resolve_keepalive_option,
                           save_state)
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


class FakeConn:
    """
    Just enough of imaplib's `.uid()` for fetch_since (#221): a search that
    returns every UID it holds, and a fetch that hands back one message's raw
    header bytes. No socket, no server -- fetch_since only ever calls `.uid()`,
    so that is the entire surface worth faking.
    """

    def __init__(self, messages):
        self.messages = messages   # {uid: email.message.Message}

    def uid(self, command, *args):
        if command == "search":
            uids = sorted(self.messages)
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if command == "fetch":
            uid = int(args[0])
            msg = self.messages.get(uid)
            if msg is None:
                return "NO", [None]
            return "OK", [(b"1 (BODY[HEADER.FIELDS ()] {0})", msg.as_bytes())]
        raise AssertionError(f"FakeConn does not implement uid({command!r})")


def envelope(from_addr="Someone <someone@example.org>", subject="Asunto",
            to=None, cc=None, date=None):
    msg = email.message.EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Date"] = date or "Fri, 19 Sep 2026 04:00:00 +0000"
    msg["Message-Id"] = "<x@example.org>"
    if to:
        msg["To"] = to
    if cc:
        msg["Cc"] = cc
    return msg


def check_phone_numbers():
    """SRV-2: the `Phone` column, normalised and matched the way mail is."""
    # How a number is normalised (the table in SMS_GATEWAY.md and its edges) is
    # tested where it lives, in test_phone.py. Here: what the roster does with it.
    saved = os.environ.pop("PAYNANI_SMS_DEFAULT_REGION", None)
    try:
        os.environ["PAYNANI_SMS_DEFAULT_REGION"] = " us "
        with tempfile.TemporaryDirectory() as envdir:
            by_env = pathlib.Path(envdir) / "roster.md"
            by_env.write_text("| Name | Email | Phone |\n|---|---|---|\n"
                              "| Ana | ana@example.org | (555) 000-1111 |\n", encoding="utf-8")
            check(roster_mod.roster_phones(by_env) == {"+15550001111"},
                  "the roster reads a national number in the region from PAYNANI_SMS_DEFAULT_REGION")
            check(roster_mod.roster_phones(by_env, "MX") == {"+525550001111"},
                  "a region passed by the caller wins over the environment")
    finally:
        os.environ.pop("PAYNANI_SMS_DEFAULT_REGION", None)
        if saved is not None:
            os.environ["PAYNANI_SMS_DEFAULT_REGION"] = saved

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = pathlib.Path(tmpdir)
        roster = tmp / "roster.md"
        roster.write_text(
            "# 1. Approved contacts\n"
            "| Name | Email | Type | Phone |\n"
            "|---|---|---|---|\n"
            "| Ana López | ana@example.org | Human | +52 1 55 1111 2222, 55 3333 4444 |\n"
            "| Solo Teléfono | | Human | (555) 000-1111 |\n"
            "| Sin Teléfono | sin@example.org | Human | |\n"
            "| Basura | basura@example.org | AI Agent | AMAZON, 26262, no es número |\n"
            "| Fuera de región | lejos@example.org | Human | +33 6 12 34 56 78 |\n",
            encoding="utf-8")
        phones = roster_mod.roster_phones(roster, "MX")
        check(phones == {"+525511112222", "+525533334444", "+525550001111", "+33612345678"},
              f"the Phone column parsed to {sorted(phones)}")
        check("+15550001111" not in phones,
              "a national number is read in the region's country: under MX it is not a US number")
        check(roster_mod.roster_phones(roster, "US") == {"+525511112222", "+15533334444", "+15550001111", "+33612345678"},
              "the same roster read under region US")

        entries = roster_mod.roster_phone_entries(roster, "US")
        solo = [e for e in entries if e["phone"] == "+15550001111"]
        check(len(solo) == 1 and solo[0]["name"] == "Solo Teléfono" and solo[0]["address"] == "",
              "a row with a phone and no email is a valid contact, with an empty address")
        mx = roster_mod.roster_phone_entries(roster, "MX")
        two = [e["phone"] for e in mx if e["address"] == "ana@example.org"]
        check(sorted(two) == ["+525511112222", "+525533334444"],
              "an email row keeps its address next to its phones, several in one cell separated by commas")
        check(not any(e["name"] == "Basura" for e in entries),
              "an alphanumeric sender, a short code and text in the cell contribute nobody")

        # Mail is exactly what it was: a phone-only row has no address, a Phone column changes nothing.
        check(roster_addresses(roster) == {"ana@example.org", "sin@example.org", "basura@example.org",
                                           "lejos@example.org"},
              f"mail addresses are untouched by the Phone column: {sorted(roster_addresses(roster))}")
        check(not any(e["address"] == "" for e in roster_entries(roster)),
              "roster_entries() still lists only contacts with an email")

        # Exact matching, never a prefix or a substring, and `None` never matches.
        check(roster_mod.phone_listed("+525511112222", phones), "a listed number matches")
        check(not roster_mod.phone_listed("+52551111222", phones), "a prefix of a listed number does not match")
        check(not roster_mod.phone_listed("+5255111122223", phones), "a listed number plus a digit does not match")
        check(not roster_mod.phone_listed(None, phones), "None (an alphanumeric sender) never matches")
        check(not roster_mod.phone_listed("", phones), "an empty number never matches")

        # The explanation says why, for the person debugging a message that was not tagged.
        why = roster_mod.explain_phone("+52 1 55 1111 2222", phones, entries, "MX")
        check(why["matched"] and why["e164"] == "+525511112222" and why["entry"]["name"] == "Ana López",
              f"explain_phone matches the legacy +521 form to its contact: {why}")
        why = roster_mod.explain_phone("AMAZON", phones, entries, "MX")
        check(not why["matched"] and why["e164"] is None and "alphanumeric" in why["reason"],
              f"explain_phone says an alphanumeric sender can never match: {why}")
        why = roster_mod.explain_phone("5599998888", phones, entries, "MX")
        check(not why["matched"] and why["e164"] == "+525599998888" and "not on the roster" in why["reason"],
              f"explain_phone says an unlisted number is not on the roster: {why}")

        # `paynani roster list` shows the numbers next to their contact, and a phone-only
        # row is a contact too. A roster with neither still says there is nobody.
        import contextlib
        import io
        from paynani_lib import roster_cli

        def listed(path):
            real = roster_cli.roster_file
            roster_cli.roster_file = lambda: path
            out, err = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    roster_cli.run_list(None)
            finally:
                roster_cli.roster_file = real
            listed.stderr = err.getvalue()
            return out.getvalue()

        shown = listed(roster)
        problems = roster_mod.roster_phone_problems(roster, "MX")
        check({(x["name"], x["value"]) for x in problems} == {("Basura", "AMAZON"), ("Basura", "26262"),
                                                              ("Basura", "no es número")},
              f"roster_phone_problems names the cells that are not numbers: {problems}")
        check(roster_mod.roster_phone_problems(tmp / "missing.md") == [], "a missing roster has no phone problems")
        listed(roster)
        check("Basura has a Phone value that is not a phone number and is ignored: 'AMAZON'" in listed.stderr,
              f"roster list warns about a Phone value it ignores: {listed.stderr!r}")
        check("Ana López <ana@example.org> (Human) phone: +525511112222, +525533334444" in shown,
              f"roster list shows an email contact's numbers: {shown!r}")
        check("Solo Teléfono <no email> (Human) phone: +525550001111" in shown,
              f"roster list shows a contact that has only a phone: {shown!r}")
        check("Sin Teléfono <sin@example.org> (Human)\n" in shown and "Sin Teléfono <sin@example.org> (Human) phone" not in shown,
              "roster list adds nothing to a contact with no numbers")
        empty = tmp / "empty.md"
        empty.write_text("| Name | Email | Phone |\n|---|---|---|\n", encoding="utf-8")
        check(listed(empty).strip() == "No contacts on the roster.", "an empty roster still says so")

        # Rosters written before the column existed keep working exactly as they did.
        legacy = tmp / "legacy.md"
        legacy.write_text("| Name | Email | Type |\n|---|---|---|\n"
                          "| Ana | ana@example.org | Human |\n", encoding="utf-8")
        check(roster_mod.roster_phones(legacy) == set() and roster_mod.roster_phone_entries(legacy) == [],
              "a roster with no Phone column has no phones")
        check(roster_mod.roster_phones(tmp / "missing.md") == set(), "a missing roster has no phones")

        # Not a roster column to guess at: add_contact leaves Phone blank, like any column it does not know.
        ok, new_text = roster_mod.add_contact(roster.read_text(encoding="utf-8"), "Nuevo", "nuevo@example.org")
        check(ok and "| Nuevo | nuevo@example.org |  |  |" in new_text,
              f"add_contact leaves the Phone cell blank: {new_text.splitlines()[-1]!r}")


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
        [(_, notifier_fields)] = fetch_since(
            FakeConn({1: envelope(
                from_addr="notifications@github.com",
                to="iris.claude.tob@agenteiamail.com",
                subject="[iaaorgmx/paynani] notifier test",
            )}), 0, Listed(notifier_roster), "iris.claude.tob@agenteiamail.com")
        check("notifier_headers" not in notifier_fields,
              "a missing notifier header is not invented in the envelope")
        notifier_message = envelope(
            from_addr="notifications@github.com",
            to="iris.claude.tob@agenteiamail.com",
            subject="[iaaorgmx/paynani] notifier test",
        )
        notifier_message["X-GitHub-Sender"] = "a-stranger"
        [(_, notifier_fields)] = fetch_since(
            FakeConn({1: notifier_message}), 0, Listed(notifier_roster),
            "iris.claude.tob@agenteiamail.com")
        check(notifier_fields["notifier_headers"] == {"X-GitHub-Sender": "a-stranger"},
              "the listener preserves declared notifier headers for later diagnostics")
        legacy_notifier_roster = pathlib.Path(tmp) / "legacy-notifiers.md"
        legacy_notifier_roster.write_text(
            "| Name | Email | Type | Username |\n"
            "|---|---|---|---|\n"
            "| Julian Flores | jjulianfe@gmail.com | Human | julianflores |\n"
            "\n"
            "## Notifiers\n"
            "\n"
            "| Address | Header | Column |\n"
            "|---|---|---|\n"
            "| notifications@github.com | X-GitHub-Sender | GitHub |\n",
            encoding="utf-8")
        legacy_entries = roster_entries(legacy_notifier_roster)
        legacy_notifiers = notifiers(legacy_notifier_roster)
        check(legacy_entries[0]["columns"]["github"] == "julianflores",
              "Username is a read-only alias for the canonical GitHub column")
        check(sender_is_listed(message("notifications@github.com", **{"X-GitHub-Sender": "julianflores"}),
                               roster_addresses(legacy_notifier_roster), legacy_entries, legacy_notifiers),
              "a GitHub notifier keeps working on a legacy Username roster")
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

        # --- recipient role (#221): To/Cc/undisclosed, via a fake IMAP fetch -
        account = "iris.claude.tob@agenteiamail.com"
        listed = Listed(roster)

        # The line carries the time the mail was noticed, to the second (parts() calls
        # time.strftime("%H:%M:%S")), and this check builds two lines one after the other:
        # whenever the clock crossed a second between them they differed, and the test
        # failed with nothing wrong in the code (it did so in CI, under the load of an
        # install). The clock is held still for the two lines that are compared.
        import time as _time
        real_strftime = _time.strftime
        _time.strftime = lambda fmt, *args: "12:00:00" if fmt == "%H:%M:%S" else real_strftime(fmt, *args)
        try:
            [(_, to_fields)] = fetch_since(FakeConn({1: envelope(to=account)}), 0, listed, account)
            control = describe("Someone <someone@example.org>", "Asunto",
                               "Fri, 19 Sep 2026 04:00:00 +0000", trusted=False)
        finally:
            _time.strftime = real_strftime
        check(to_fields["recipient_role"] == "to",
              f"the account in To gives 'to', got {to_fields['recipient_role']!r}")
        check(to_fields["notification_text"] == control,
              "the 'to' role leaves the notification line exactly as before (#221's PRD)")
        check(", cc]" not in control and "undisclosed" not in control,
              "...and the control line itself carries neither role marker")

        [(_, cc_fields)] = fetch_since(
            FakeConn({1: envelope(to="other@example.org", cc=account)}), 0, listed, account)
        check(cc_fields["recipient_role"] == "cc",
              f"the account only in Cc gives 'cc', got {cc_fields['recipient_role']!r}")
        check(", cc]" in cc_fields["notification_text"],
              f"the cc role must show in the line: {cc_fields['notification_text']!r}")

        [(_, undisclosed_fields)] = fetch_since(
            FakeConn({1: envelope(to="other@example.org")}), 0, listed, account)
        check(undisclosed_fields["recipient_role"] == "undisclosed",
              f"the account in neither header gives 'undisclosed', got {undisclosed_fields['recipient_role']!r}")
        check(", undisclosed]" in undisclosed_fields["notification_text"],
              f"the undisclosed role must show in the line: {undisclosed_fields['notification_text']!r}")

        [(_, bcc_fields)] = fetch_since(FakeConn({1: envelope()}), 0, listed, account)
        check(bcc_fields["recipient_role"] == "undisclosed",
              "no To and no Cc at all (BCC or a list) is undisclosed too")

        [(_, three_to_fields)] = fetch_since(
            FakeConn({1: envelope(to=f"a@example.org, {account}, b@example.org")}), 0, listed, account)
        check(three_to_fields["recipient_role"] == "to",
              "one of several direct To addresses is still 'to'")

        [(_, ci_fields)] = fetch_since(
            FakeConn({1: envelope(to=f'"Metis" <{account.upper()}>')}), 0, listed, account)
        check(ci_fields["recipient_role"] == "to",
              "matching ignores case and a display name ahead of the address")

        legacy_batch = (
            "# keep this comment\n"
            "| Name | Email | Type | Username |\n"
            "|---|---|---|---|\n"
            "| Ximena | ximena@example.org | Human | ximenasalazartob |\n"
        )
        rows = [
            {"name": f"Agent {i}", "address": f"agent{i}@example.org", "type": "AI Agent", "github": f"agent{i}"}
            for i in range(1, 10)
        ]
        bad_rows = list(rows)
        bad_rows[4] = {**bad_rows[4], "github": "bad_login_underscore"}
        ok, failed_text, why = roster_mod.batch_add_contacts(legacy_batch, bad_rows)
        check(not ok and failed_text == legacy_batch and "invalid GitHub login" in why[0],
              "an invalid row rejects the batch without changing the returned text")
        ok, migrated_batch, notes = roster_mod.batch_add_contacts(legacy_batch, rows)
        check(ok, f"valid batch accepted: {notes}")
        check("Username" not in migrated_batch and "| Name | Email | Type | GitHub |" in migrated_batch,
              "batch apply migrates the legacy header in the same logical plan")
        check("# keep this comment" in migrated_batch, "migration preserves comments")
        for row in rows:
            check(row["address"] in roster_mod._addresses_from_text(migrated_batch),
                  f"{row['address']} was added")

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
        check(state.get("version") == PROCESS_VERSION,
              "listener state records the version loaded by this process")
        check(state.get("commit") == PROCESS_COMMIT,
              "listener state records the commit loaded by this process")
        check(state.get("pid") == os.getpid(),
              "listener state records the process that wrote it")
        check(PROCESS_COMMIT is None or
              (len(PROCESS_COMMIT) == 40 and all(c in "0123456789abcdef" for c in PROCESS_COMMIT)),
              "a real checkout's commit is a 40-char hex SHA")
        check(state.get("python", {}).get("supported") is True
              and state.get("python", {}).get("executable"),
              "listener state records the service Python interpreter")

        telemetry = {}
        record_imap_reconnect(telemetry, "2026-09-19T04:00:00Z")
        check(telemetry["imap_reconnect_window"] == ["2026-09-19T04:00:00Z"]
              and telemetry["imap_reconnects_last_hour"] == 1,
              "one IMAP reconnect adds exactly one timestamp to the hourly window")
        telemetry = {"imap_reconnect_window": [
            "2026-09-19T02:59:59Z",
            "2026-09-19T03:00:01Z",
        ]}
        record_imap_reconnect(telemetry, "2026-09-19T04:00:01Z")
        check(telemetry["imap_reconnect_window"] == [
            "2026-09-19T03:00:01Z",
            "2026-09-19T04:00:01Z",
        ], "IMAP reconnect timestamps older than 3600 seconds are pruned")
        check(telemetry["imap_reconnects_last_hour"] == 2,
              "hourly reconnect count follows the pruned window length")

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

    check_phone_numbers()

    print("listener tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
