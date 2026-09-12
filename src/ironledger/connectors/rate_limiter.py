"""Integer-based token-bucket rate limiter with millisecond timestamps."""

from __future__ import annotations

import time
from typing import Final


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter using integer arithmetic."""

    def __init__(
        self,
        rate_limit_rpm: int = 60,
        burst_capacity: int = 10,
        initial_time_ms: int | None = None,
    ):
        if rate_limit_rpm <= 0:
            raise ValueError("rate_limit_rpm must be strictly positive integer")
        if burst_capacity <= 0:
            raise ValueError("burst_capacity must be strictly positive integer")

        self.rate_limit_rpm: Final[int] = rate_limit_rpm
        self.burst_capacity: Final[int] = burst_capacity
        self._tokens: int = burst_capacity
        self._last_refill_ms: int = self._current_time_ms() if initial_time_ms is None else initial_time_ms

    @staticmethod
    def _current_time_ms() -> int:
        return time.monotonic_ns() // 1_000_000

    def _refill(self, now_ms: int) -> None:
        if now_ms < self._last_refill_ms:
            self._last_refill_ms = now_ms
            return

        elapsed_ms = now_ms - self._last_refill_ms
        if elapsed_ms > 0:
            refill = (elapsed_ms * self.rate_limit_rpm) // 60_000
            if refill > 0:
                self._tokens = min(self.burst_capacity, self._tokens + refill)
                consumed_elapsed_ms = (refill * 60_000) // self.rate_limit_rpm
                self._last_refill_ms += consumed_elapsed_ms

    def acquire(self, tokens: int = 1, now_ms: int | None = None) -> bool:
        """Attempt to acquire tokens. Returns True if acquired, False otherwise."""
        if tokens <= 0:
            raise ValueError("Tokens requested must be positive integer")
        t = self._current_time_ms() if now_ms is None else now_ms
        self._refill(t)
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def get_wait_time_ms(self, tokens: int = 1, now_ms: int | None = None) -> int:
        """Calculate millisecond wait required until requested tokens are available."""
        if tokens <= 0:
            raise ValueError("Tokens requested must be positive integer")
        t = self._current_time_ms() if now_ms is None else now_ms
        self._refill(t)
        if self._tokens >= tokens:
            return 0
        deficit = tokens - self._tokens
        return ((deficit * 60_000) + self.rate_limit_rpm - 1) // self.rate_limit_rpm

    def get_available_tokens(self, now_ms: int | None = None) -> int:
        t = self._current_time_ms() if now_ms is None else now_ms
        self._refill(t)
        return self._tokens