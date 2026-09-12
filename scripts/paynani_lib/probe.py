"""
Live checks against the mail server, before anything is written to disk. Port
of webapp/lib/probe.php, using imaplib/smtplib (standard library) instead of
hand-rolled sockets.

This is the reason the onboarding flow is worth more than a text editor. The
failures this project sees are not typos in a key name; they are a hostname
that resolves but is not on the server's TLS certificate, a port that belongs
to the other protocol, or a password that works in a webmail login and not
over IMAP. Every one of those produces a file that looks perfect.

Worse, a certificate mismatch reaches the listener as a network error, so it
retries forever with "connection lost" and nothing that names the cause. That
is a bad afternoon. Ten seconds here removes it.

Nothing in this file ever puts the password into a message, a log, or a
returned value.
"""

from __future__ import annotations

import imaplib
import smtplib
import socket
import ssl

from .i18n import t

PROBE_TIMEOUT = 10


def step(ok: bool, text: str, detail: str = "") -> dict:
    return {"ok": ok, "text": text, "detail": detail}


def _tls_context() -> ssl.SSLContext:
    # Verification on, deliberately. Turning it off here would let the
    # onboarder certify a configuration the listener will then refuse to use.
    return ssl.create_default_context()


def _explain_socket_error(exc: Exception, host: str) -> str:
    """Turn a socket/ssl exception into something a non-technical reader can
    act on. The certificate case is singled out because it is both the most
    common and the least self-explanatory."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return t("p.cert_mismatch", host=host)
    if isinstance(exc, socket.gaierror):
        return t("p.no_dns", host=host)
    if isinstance(exc, ConnectionRefusedError):
        return t("p.refused", host=host)
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return t("p.timed_out", host=host, seconds=PROBE_TIMEOUT)
    msg = str(exc).strip()
    return msg if msg else t("p.failed_silent")


def probe_imap(host: str, port: int, user: str, password: str) -> dict:
    steps = []

    if port == 143:
        steps.append(step(False, t("p.imap143"), t("p.imap143_detail")))
        return {"ok": False, "steps": steps}

    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=PROBE_TIMEOUT, ssl_context=_tls_context())
    except Exception as exc:  # noqa: BLE001 - translated into a user-facing step below
        steps.append(step(False, t("p.no_tls", host=host, port=port), _explain_socket_error(exc, host)))
        return {"ok": False, "steps": steps}
    steps.append(step(True, t("p.tls_ok", host=host, port=port)))

    # IMAP4_SSL's constructor already consumed the greeting; a socket that
    # accepted TLS but is not an IMAP server raises inside the constructor
    # above (bad response) rather than here, so reaching this point already
    # answers "is this speaking IMAP".
    steps.append(step(True, t("p.is_imap")))

    try:
        conn.login(user, password)
    except imaplib.IMAP4.error:
        steps.append(step(False, t("p.auth_rejected"), t("p.auth_rejected_d")))
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "steps": steps}
    steps.append(step(True, t("p.signed_in")))

    # IDLE is the whole design. Ask after logging in; plenty of servers only
    # advertise it to an authenticated session.
    try:
        caps = " ".join(c.decode() if isinstance(c, bytes) else c for c in conn.capabilities).upper()
    except Exception:  # noqa: BLE001
        caps = ""
    if "IDLE" in caps:
        steps.append(step(True, t("p.idle_yes")))
    else:
        steps.append(step(False, t("p.idle_no"), t("p.idle_no_detail")))
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "steps": steps}

    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "steps": steps}


def probe_smtp(host: str, port: int, user: str, password: str) -> dict:
    """
    Try the encryption style the port suggests, and if the server turns out to
    speak the other one, try that before giving up.

    465 means TLS from the first byte and 587 means STARTTLS, by convention,
    but it is only a convention. A mismatch here looks exactly like "that port
    is not speaking SMTP", which would send someone off to check a setting
    that was right all along.
    """
    preferred_implicit = port not in (587, 25, 2525)

    result = _probe_smtp_mode(host, port, user, password, preferred_implicit)
    if result["ok"] or result["authenticated"]:
        return result  # it spoke SMTP; the other mode will not help

    fallback = _probe_smtp_mode(host, port, user, password, not preferred_implicit)
    return fallback if fallback["ok"] else result


def _probe_smtp_mode(host: str, port: int, user: str, password: str, implicit: bool) -> dict:
    steps = []
    smtp_cls = smtplib.SMTP_SSL if implicit else smtplib.SMTP

    try:
        # host is passed to the constructor, not to a later .connect(): with
        # check_hostname on (the default from create_default_context()), TLS
        # wrapping needs server_hostname for SNI, and SMTP_SSL only carries
        # that through when it learns the host at construction time.
        conn = (
            smtp_cls(host, port, timeout=PROBE_TIMEOUT, context=_tls_context())
            if implicit
            else smtp_cls(host, port, timeout=PROBE_TIMEOUT)
        )
    except Exception as exc:  # noqa: BLE001
        steps.append(step(False, t("p.no_reach", host=host, port=port), _explain_socket_error(exc, host)))
        return {"ok": False, "authenticated": False, "steps": steps}

    try:
        code, _ = conn.ehlo("localhost")
        if code < 200 or code >= 300:
            code, _ = conn.helo("localhost")
        if code < 200 or code >= 300:
            steps.append(step(False, t("p.no_session")))
            return {"ok": False, "authenticated": False, "steps": steps}

        if implicit:
            steps.append(step(True, t("p.tls_ok", host=host, port=port)))
        else:
            if not conn.has_extn("starttls"):
                steps.append(step(False, t("p.no_encryption"), t("p.no_encryption_d")))
                return {"ok": False, "authenticated": False, "steps": steps}
            try:
                conn.starttls(context=_tls_context())
            except smtplib.SMTPResponseException:
                steps.append(step(False, t("p.starttls_refused")))
                return {"ok": False, "authenticated": False, "steps": steps}
            except ssl.SSLError as exc:
                steps.append(step(False, t("p.tls_failed"), _explain_socket_error(exc, host)))
                return {"ok": False, "authenticated": False, "steps": steps}
            steps.append(step(True, t("p.tls_upgraded", host=host, port=port)))
            conn.ehlo("localhost")

        if not conn.has_extn("auth"):
            steps.append(step(False, t("p.no_auth_offered"), t("p.no_auth_offered_d")))
            return {"ok": False, "authenticated": False, "steps": steps}

        try:
            conn.login(user, password)
        except smtplib.SMTPAuthenticationError:
            steps.append(step(False, t("p.send_auth_bad"), t("p.send_auth_bad_d")))
            return {"ok": False, "authenticated": False, "steps": steps}
        except smtplib.SMTPNotSupportedError:
            steps.append(step(False, t("p.auth_method_bad")))
            return {"ok": False, "authenticated": False, "steps": steps}
        except smtplib.SMTPResponseException:
            steps.append(step(False, t("p.address_rejected")))
            return {"ok": False, "authenticated": False, "steps": steps}

        steps.append(step(True, t("p.signed_in_smtp")))
        conn.quit()
        return {"ok": True, "authenticated": True, "steps": steps}
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
