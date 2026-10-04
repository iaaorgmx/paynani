#!/usr/bin/env python3
"""
A minimal IMAPS + SMTPS server for the bootstrap end-to-end job (paynani#343).

It speaks just enough of both protocols, over implicit TLS like the real ports
993 and 465, for the three clients bootstrap.sh exercises: the listener
(imaplib: CAPABILITY, LOGIN, STATUS, SELECT, UID SEARCH/FETCH, IDLE), himalaya
(AUTHENTICATE PLAIN, LIST, SELECT/EXAMINE, FETCH on an empty INBOX) and
send.sh (SMTP AUTH and one message). One account, an empty INBOX, and every
message received over SMTP is appended to a file so the job can read it.

It is a test fixture, not a mail server: a command it does not know gets a
tagged OK and a line on stderr, so a client that wanders off the expected path
shows up in the CI log instead of hanging the job.

    python3 scripts/fake_mail_server.py --cert c.pem --key k.pem \
        --user agente@example.com --password s3cret --imap-port 9993 --smtp-port 9465 \
        --spool /tmp/received.mbox
"""

import argparse
import base64
import re
import socketserver
import ssl
import sys
import threading

UIDVALIDITY = 1


def log(msg):
    print(f"fake-mail: {msg}", file=sys.stderr, flush=True)


def _plain(blob: str):
    """(user, password) from a SASL PLAIN response, or (None, None)."""
    try:
        parts = base64.b64decode(blob).split(b"\0")
        return parts[-2].decode(), parts[-1].decode()
    except Exception:
        return None, None


class TLSServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, handler, context, user, password, spool=None):
        self.context, self.user, self.password, self.spool = context, user, password, spool
        super().__init__(addr, handler)



class Lines(socketserver.StreamRequestHandler):
    # The handshake runs in the connection's own thread, so one client that never
    # finishes it cannot stall the accept loop for the others.
    def setup(self):
        self.request.settimeout(30)
        self.request = self.server.context.wrap_socket(self.request, server_side=True)
        self.request.settimeout(None)  # the listener holds IDLE open for many minutes
        super().setup()

    def send(self, line: str):
        self.wfile.write(line.encode() + b"\r\n")
        self.wfile.flush()

    def recv(self):
        raw = self.rfile.readline(65536)
        if not raw:
            return None
        return raw.decode(errors="replace").rstrip("\r\n")

    def handle(self):
        try:
            self.session()
        except (ssl.SSLError, ConnectionError, OSError) as exc:
            log(f"{type(self).__name__}: connection ended ({exc.__class__.__name__})")


class IMAP(Lines):
    CAPS = "IMAP4rev1 AUTH=PLAIN IDLE LITERAL+ ID ENABLE UIDPLUS"

    def ok(self, tag, text="completed"):
        self.send(f"{tag} OK {text}")

    def mailbox(self, tag, cmd, read_only):
        self.send("* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft)")
        self.send("* 0 EXISTS")
        self.send("* 0 RECENT")
        self.send(f"* OK [UIDVALIDITY {UIDVALIDITY}] UIDs valid")
        self.send("* OK [UIDNEXT 1] predicted next UID")
        self.ok(tag, f"[{'READ-ONLY' if read_only else 'READ-WRITE'}] {cmd} completed")

    def session(self):
        self.send(f"* OK [CAPABILITY {self.CAPS}] fake-mail ready")
        authed = False
        while True:
            line = self.recv()
            if line is None:
                return
            m = re.match(r"(\S+)\s+(\S+)\s*(.*)", line)
            if not m:
                continue
            tag, cmd, rest = m.group(1), m.group(2).upper(), m.group(3)
            if cmd == "UID":
                sub = rest.split(" ", 1)
                cmd, rest = "UID " + sub[0].upper(), sub[1] if len(sub) > 1 else ""
            if cmd == "CAPABILITY":
                self.send(f"* CAPABILITY {self.CAPS}")
                self.ok(tag)
            elif cmd == "LOGIN":
                args = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', rest)
                vals = [a or b for a, b in args]
                if len(vals) >= 2 and vals[0] == self.server.user and vals[1] == self.server.password:
                    authed = True
                    self.ok(tag, "LOGIN completed")
                else:
                    self.send(f"{tag} NO [AUTHENTICATIONFAILED] invalid credentials")
            elif cmd == "AUTHENTICATE":
                parts = rest.split()
                if not parts or parts[0].upper() != "PLAIN":
                    self.send(f"{tag} NO unsupported mechanism")
                    continue
                blob = parts[1] if len(parts) > 1 else None
                if blob is None:
                    self.send("+ ")
                    blob = self.recv() or ""
                user, password = _plain(blob)
                if user == self.server.user and password == self.server.password:
                    authed = True
                    self.ok(tag, "AUTHENTICATE completed")
                else:
                    self.send(f"{tag} NO [AUTHENTICATIONFAILED] invalid credentials")
            elif cmd in ("NOOP", "CHECK"):
                self.ok(tag)
            elif cmd == "LOGOUT":
                self.send("* BYE fake-mail logging out")
                self.ok(tag)
                return
            elif not authed:
                self.send(f"{tag} NO authenticate first")
            elif cmd == "ID":
                self.send('* ID ("name" "fake-mail")')
                self.ok(tag)
            elif cmd == "ENABLE":
                self.send("* ENABLED")
                self.ok(tag)
            elif cmd in ("LIST", "LSUB"):
                self.send(f'* {cmd} () "/" "INBOX"')
                self.ok(tag)
            elif cmd == "STATUS":
                self.send(f'* STATUS "INBOX" (MESSAGES 0 RECENT 0 UIDNEXT 1 UIDVALIDITY {UIDVALIDITY} UNSEEN 0)')
                self.ok(tag)
            elif cmd in ("SELECT", "EXAMINE"):
                self.mailbox(tag, cmd, cmd == "EXAMINE")
            elif cmd in ("SEARCH", "UID SEARCH"):
                self.send("* SEARCH")
                self.ok(tag)
            elif cmd in ("FETCH", "UID FETCH", "STORE", "UID STORE", "EXPUNGE", "CLOSE"):
                self.ok(tag)  # the INBOX is empty: nothing to fetch, store or expunge
            elif cmd == "IDLE":
                self.send("+ idling")
                while True:
                    done = self.recv()
                    if done is None:
                        return
                    if done.strip().upper() == "DONE":
                        break
                self.ok(tag, "IDLE terminated")
            else:
                log(f"IMAP command not modelled, answered OK: {cmd}")
                self.ok(tag)


class SMTP(Lines):
    def session(self):
        self.send("220 fake-mail ESMTP ready")
        authed = False
        while True:
            line = self.recv()
            if line is None:
                return
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                self.send("250-fake-mail")
                self.send("250-AUTH PLAIN LOGIN")
                self.send("250 8BITMIME")
            elif verb == "AUTH":
                parts = line.split()
                mech = parts[1].upper() if len(parts) > 1 else ""
                if mech == "PLAIN":
                    blob = parts[2] if len(parts) > 2 else None
                    if blob is None:
                        self.send("334 ")
                        blob = self.recv() or ""
                    user, password = _plain(blob)
                elif mech == "LOGIN":
                    self.send("334 VXNlcm5hbWU6")
                    user = base64.b64decode(self.recv() or "").decode(errors="replace")
                    self.send("334 UGFzc3dvcmQ6")
                    password = base64.b64decode(self.recv() or "").decode(errors="replace")
                else:
                    self.send("504 unsupported mechanism")
                    continue
                if user == self.server.user and password == self.server.password:
                    authed = True
                    self.send("235 authenticated")
                else:
                    self.send("535 invalid credentials")
            elif verb in ("MAIL", "RCPT"):
                self.send("250 OK" if authed else "530 authenticate first")
            elif verb == "DATA":
                if not authed:
                    self.send("530 authenticate first")
                    continue
                self.send("354 end with <CRLF>.<CRLF>")
                body = []
                while True:
                    data = self.recv()
                    if data is None or data == ".":
                        break
                    body.append(data[1:] if data.startswith("..") else data)
                if self.server.spool:
                    with open(self.server.spool, "a", encoding="utf-8") as f:
                        f.write("\n".join(body) + "\n\n")
                log(f"SMTP message received ({len(body)} lines)")
                self.send("250 queued")
            elif verb in ("RSET", "NOOP"):
                self.send("250 OK")
            elif verb == "QUIT":
                self.send("221 bye")
                return
            else:
                self.send("502 not implemented")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cert", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--imap-port", type=int, default=9993)
    ap.add_argument("--smtp-port", type=int, default=9465)
    ap.add_argument("--spool", default=None, help="file that collects the messages received over SMTP")
    args = ap.parse_args()

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(args.cert, args.key)
    imap = TLSServer((args.host, args.imap_port), IMAP, ctx, args.user, args.password)
    smtp = TLSServer((args.host, args.smtp_port), SMTP, ctx, args.user, args.password, args.spool)
    for server in (imap, smtp):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"IMAPS on {args.host}:{args.imap_port}, SMTPS on {args.host}:{args.smtp_port}, user {args.user}")
    threading.Event().wait()


if __name__ == "__main__":
    main()
