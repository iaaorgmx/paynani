"""Thread-safe API authentication failures and per-token call limits."""
from __future__ import annotations

import collections
import threading
import time


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
            return max(0, int(remaining + 0.999))

    def fail(self, address: str) -> None:
        now = self.clock()
        with self.lock:
            failures = self.failures.setdefault(address, collections.deque())
            while failures and now - failures[0] >= 900:
                failures.popleft()
            failures.append(now)
            if len(failures) >= 10:
                self.blocked[address] = now + 900
                failures.clear()

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
