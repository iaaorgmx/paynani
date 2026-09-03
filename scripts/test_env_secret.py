#!/usr/bin/env python3
"""
What `env_secret.py` reads out of an env file, and what it refuses to.

Himalaya's `password.cmd` is the one place in this project where the byte-level
shape of the `.env` reaches a server. Everything else strips and normalises on
the way in; this prints a value and something else authenticates with it. A
trailing carriage return here comes back as a bad credential, which sends the
reader to check the password rather than the file (#14).

    python3 scripts/test_env_secret.py
"""

import pathlib
import subprocess
import sys
import tempfile

SCRIPT = pathlib.Path(__file__).resolve().parent / "env_secret.py"
passed = failed = 0


def check(desc, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"ok   {desc}")
        passed += 1
    else:
        print(f"FAIL {desc}\n       expected: {expected!r}\n       actual:   {actual!r}")
        failed += 1


def read(content: bytes, key="PAYNANI_PASSWORD"):
    """Run it as Himalaya does — a subprocess whose stdout is the secret.

    Bytes, not text: `subprocess` with `text=True` translates newlines, which
    silently removes the very character these tests are about.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "env"
        path.write_bytes(content)
        run = subprocess.run([sys.executable, str(SCRIPT), str(path), key],
                             capture_output=True)
        return run.returncode, run.stdout.rstrip(b"\n")


rc, value = read(b"PAYNANI_PASSWORD=hunter2\n")
check("a plain LF file reads clean", (0, b"hunter2"), (rc, value))

rc, value = read(b"PAYNANI_EMAIL=a@b.c\r\nPAYNANI_PASSWORD=hunter2\r\n")
check("CRLF does not leave a carriage return on the value", (0, b"hunter2"), (rc, value))

rc, value = read(b"\xef\xbb\xbfPAYNANI_PASSWORD=hunter2\n")
check("a UTF-8 BOM does not become part of the first key", (0, b"hunter2"), (rc, value))

rc, value = read(b"\xef\xbb\xbfPAYNANI_PASSWORD=hunter2\r\n")
check("BOM and CRLF together still read clean", (0, b"hunter2"), (rc, value))

rc, value = read(b'PAYNANI_PASSWORD="hunter2"\r\n')
check("surrounding quotes are not part of the password", (0, b"hunter2"), (rc, value))

# The failure this replaced, pinned so the reason stays visible: the documented
# sed returns the carriage return that the server then rejects.
with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / "env"
    path.write_bytes(b"PAYNANI_PASSWORD=hunter2\r\n")
    sed = subprocess.run(["sed", "-n", "s/^PAYNANI_PASSWORD=//p", str(path)],
                         capture_output=True)
    check("the sed this replaced really does return the carriage return",
          True, sed.stdout.rstrip(b"\n").endswith(b"\r"))

rc, value = read(b"PAYNANI_PASSWORD=hunter2\n", key="NOT_THERE")
check("a missing key fails rather than printing nothing successfully", 1, rc)
check("and prints no value at all", b"", value)

rc, value = read(b"# PAYNANI_PASSWORD=commented-out\nPAYNANI_PASSWORD=real\n")
check("a commented line is not the answer", (0, b"real"), (rc, value))

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
