"""
Access control for the onboarding server. Port of webapp/lib/guard.php.

This collects a mail password. Three things keep that from being a liability,
and none of them is optional:

  1. It only answers requests from the loopback interface. Even if the server
     were started bound to 0.0.0.0 by mistake, a request from off the machine
     gets 403 and nothing else. An SSH tunnel arrives as 127.0.0.1, so the
     remote case still works.
  2. It requires a token that the CLI generated and printed. The token is
     never guessable and never long-lived.
  3. The password is only ever read from a POST body. It is never put in a
     URL, never echoed back into the response, and never written to a log.
"""

from __future__ import annotations

import hmac
import secrets

TOKEN_BASENAME = "setup.token"


def token_path(state_dir):
    return state_dir / TOKEN_BASENAME


def is_loopback(remote_addr: str) -> bool:
    return remote_addr in ("127.0.0.1", "::1")


def check_token(state_dir, given: str) -> bool:
    try:
        expected = token_path(state_dir).read_text(encoding="utf-8").strip()
    except OSError:
        expected = ""
    given = (given or "").strip()
    if not expected or not given:
        return False
    return hmac.compare_digest(expected, given)


def new_session_id() -> str:
    return secrets.token_hex(32)


def new_csrf_token() -> str:
    return secrets.token_hex(32)


def check_csrf(session: dict, given: str) -> bool:
    expected = session.get("csrf")
    if not expected:
        return False
    return hmac.compare_digest(expected, given or "")


SECURITY_HEADERS = [
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store, no-cache, must-revalidate"),
]

# No external anything: the page is a form on a machine that may have no route
# to the internet at all, and a CDN reference would silently break it.
# script-src 'self' and nothing more: same-origin files only, no
# 'unsafe-inline', no 'unsafe-eval', no remote origin. Inline handlers stay
# forbidden, so a string injected into this page still cannot execute.
CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; "
    "form-action 'self'; base-uri 'none'"
)
