"""Small bounded login-failure throttle for single-process deployments."""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from threading import Lock


class LoginThrottle:
    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 300,
        max_entries: int = 1024,
    ) -> None:
        if max_failures < 1 or window_seconds < 1 or max_entries < 1:
            raise ValueError("Login throttle bounds must be positive")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float] | None:
        attempts = self._failures.get(key)
        if attempts is None:
            return None
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._failures.pop(key, None)
            return None
        return attempts

    def is_blocked(self, key: str, *, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._prune(key, current_time)
            if attempts is None:
                return False
            self._failures.move_to_end(key)
            return len(attempts) >= self.max_failures

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._prune(key, current_time)
            if attempts is None:
                attempts = deque()
                self._failures[key] = attempts
            attempts.append(current_time)
            self._failures.move_to_end(key)
            while len(self._failures) > self.max_entries:
                self._failures.popitem(last=False)

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
