"""Thread-safe API authentication failures and per-token call limits."""
from __future__ import annotations

import collections
import threading
import time

PRUNE_ABOVE = 10_000


class Limits:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.failures = {}
        self.blocked = {}
        self.calls = {}

    def blocked_for(self, address: str) -> int:
        now = self.clock()
        with self.lock:
            remaining = self.blocked.get(address, 0) - now
            if remaining <= 0:
                self.blocked.pop(address, None)
            return max(0, int(remaining + 0.999))

    def fail(self, address: str) -> None:
        now = self.clock()
        with self.lock:
            if len(self.failures) > PRUNE_ABOVE or len(self.blocked) > PRUNE_ABOVE:
                self._prune(now)
            failures = self.failures.setdefault(address, collections.deque())
            while failures and now - failures[0] >= 900:
                failures.popleft()
            failures.append(now)
            if len(failures) >= 10:
                self.blocked[address] = now + 900
                failures.clear()

    def _prune(self, now: float) -> None:
        """Remove expired addresses under the same lock used by fail/admit."""
        for address in [key for key, entries in self.failures.items()
                        if not entries or now - entries[-1] >= 900]:
            del self.failures[address]
        for address in [key for key, until in self.blocked.items() if until <= now]:
            del self.blocked[address]

    def admit_call(self, sha256: str) -> int:
        """Zero when accepted, or seconds until the oldest of 60 calls ages out."""
        now = self.clock()
        with self.lock:
            calls = self.calls.setdefault(sha256, collections.deque())
            while calls and now - calls[0] >= 60:
                calls.popleft()
            if len(calls) >= 60:
                return max(1, int(60 - (now - calls[0]) + 0.999))
            calls.append(now)
            return 0
