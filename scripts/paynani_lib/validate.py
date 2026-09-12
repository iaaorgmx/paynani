"""
Form validation. Port of webapp/lib/validate.php.

The checks here are not generic form hygiene. Each one is a mistake this
project has actually seen, and every one of them produces a file that looks
correct and a listener that fails somewhere far away from the cause.
"""

from __future__ import annotations

import re

from .i18n import t

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HOST_CHARS_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")


def _ctype_digit(value: str) -> bool:
    """PHP's ctype_digit(): true only for one or more ASCII 0-9. Python's
    str.isdigit() is unicode-aware (superscripts, Arabic-Indic digits, ...)
    and would both misclassify a host string and crash int() on the port
    check, so this is deliberately not str.isdigit()."""
    return _ASCII_DIGITS_RE.match(value) is not None


def _looks_like_email(value: str) -> bool:
    # The same class of typo (missing @, missing dot, stray spaces) is what
    # this catches — a stricter RFC 5322 matcher would reject real addresses
    # users actually have.
    return _EMAIL_RE.match(value) is not None


def validate(values: dict) -> dict:
    """values (the effective, posted values) -> {field: message}, empty when
    everything passes."""
    errors: dict[str, str] = {}

    account = (values.get("AGENT_EMAIL_ACCOUNT") or "").strip()
    if account == "":
        errors["AGENT_EMAIL_ACCOUNT"] = t("v.account_missing")
    elif not _looks_like_email(account):
        errors["AGENT_EMAIL_ACCOUNT"] = t("v.account_bad")

    if (values.get("AGENT_EMAIL_PASSWORD") or "") == "":
        errors["AGENT_EMAIL_PASSWORD"] = t("v.password_missing")

    name = values.get("AGENT_EMAIL_FROM_NAME") or ""
    if "\n" in name or "\r" in name:
        errors["AGENT_EMAIL_FROM_NAME"] = t("v.fromname_oneline")

    for key, proto in (
        ("AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST", "IMAP"),
        ("AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST", "SMTP"),
    ):
        host = (values.get(key) or "").strip()
        if host == "":
            errors[key] = t("v.host_missing", proto=proto)
            continue
        # The trap this repo documents: a field named for a server holding a
        # port. Read literally it sends the listener somewhere that does not
        # exist, and the error arrives as a connection failure.
        if _ctype_digit(host):
            errors[key] = t("v.host_is_port")
            continue
        if "/" in host or " " in host or "@" in host:
            errors[key] = t("v.host_has_junk")
            continue
        if _HOST_CHARS_RE.match(host) is None:
            errors[key] = t("v.host_bad_chars")

    for key, proto in (
        ("AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT", "IMAP"),
        ("AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT", "SMTP"),
    ):
        port = (values.get(key) or "").strip()
        if port == "":
            errors[key] = t("v.port_missing", proto=proto)
            continue
        if not _ctype_digit(port) or not (1 <= int(port) <= 65535):
            errors[key] = t("v.port_range")

    return errors
