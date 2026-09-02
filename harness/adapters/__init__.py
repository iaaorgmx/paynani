"""
Runtime adapters: the only part of this repository that knows what a harness is.

An adapter takes one canonical envelope and reports one of three things. The
three are not decoration; the dispatcher's whole behaviour turns on which one
comes back:

- ACCEPTED  the event reached the runtime. The cursor may move past it.
- RETRY     it did not, and trying again might work. The cursor stays put.
- CONFIG    it did not, and trying again will not help until a human changes
            something. The cursor stays put, and the reason is said loudly.

The distinction that matters is between the last two. A wrong URL retried every
second forever is a silent failure wearing the costume of a working system, and
the operator has nothing to read that says otherwise.

Rules an adapter must not break:

- It must never touch the cursor or any listener state. It reports; the
  dispatcher decides.
- It must never print a credential, in an error message or anywhere else.
- Its errors must name the runtime and the command that would fix it. "delivery
  failed" tells an operator nothing they did not already know.
"""

ACCEPTED = "accepted"
RETRY = "retry"
CONFIG = "config"


class Result:
    """What an adapter reports back, and why."""

    __slots__ = ("status", "detail")

    def __init__(self, status, detail=""):
        self.status = status
        self.detail = detail

    @property
    def ok(self):
        return self.status == ACCEPTED

    def __repr__(self):
        return f"Result({self.status!r}, {self.detail!r})"


def accepted(detail=""):
    return Result(ACCEPTED, detail)


def retry(detail=""):
    return Result(RETRY, detail)


def config(detail=""):
    return Result(CONFIG, detail)
