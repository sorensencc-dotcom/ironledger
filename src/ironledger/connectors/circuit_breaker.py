"""Three-state circuit breaker with exponential backoff."""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from ironledger.connectors.models import CircuitBreakerOpenError, CircuitState

T = TypeVar("T")


class CircuitBreaker:
    """
    Three-state circuit breaker: CLOSED -> OPEN -> HALF_OPEN.
    Protects upstream banking endpoints from cascade failure.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        base_cooldown_ms: int = 10_000,
        max_cooldown_ms: int = 300_000,
    ):
        self.failure_threshold: int = failure_threshold
        self.base_cooldown_ms: int = base_cooldown_ms
        self.max_cooldown_ms: int = max_cooldown_ms

        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._current_cooldown_ms: int = base_cooldown_ms
        self._last_failure_time_ms: int = 0
        self._half_open_probe_in_flight: bool = False

    @staticmethod
    def _current_time_ms() -> int:
        return time.monotonic_ns() // 1_000_000

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def current_cooldown_ms(self) -> int:
        return self._current_cooldown_ms

    def allow_request(self, now_ms: int | None = None) -> bool:
        t = self._current_time_ms() if now_ms is None else now_ms

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            if t - self._last_failure_time_ms >= self._current_cooldown_ms:
                self._state = CircuitState.HALF_OPEN
                self._half_open_probe_in_flight = True
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            if not self._half_open_probe_in_flight:
                self._half_open_probe_in_flight = True
                return True
            return False

        return False

    def record_success(self, now_ms: int | None = None) -> None:
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._current_cooldown_ms = self.base_cooldown_ms
        self._half_open_probe_in_flight = False

    def record_failure(self, now_ms: int | None = None, error: Exception | None = None) -> None:
        t = self._current_time_ms() if now_ms is None else now_ms
        self._consecutive_failures += 1
        self._last_failure_time_ms = t
        self._half_open_probe_in_flight = False

        if self._state == CircuitState.HALF_OPEN:
            self._current_cooldown_ms = min(self.max_cooldown_ms, self._current_cooldown_ms * 2)
            self._state = CircuitState.OPEN
        elif self._state == CircuitState.CLOSED:
            if self._consecutive_failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._current_cooldown_ms = self.base_cooldown_ms

    def execute(self, func: Callable[..., T], *args: Any, now_ms: int | None = None, **kwargs: Any) -> T:
        t = self._current_time_ms() if now_ms is None else now_ms
        if not self.allow_request(now_ms=t):
            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN (failures: {self._consecutive_failures}, cooldown: {self._current_cooldown_ms}ms)"
            )
        try:
            result = func(*args, **kwargs)
            self.record_success(now_ms=t)
            return result
        except Exception as exc:
            self.record_failure(now_ms=t, error=exc)
            raise