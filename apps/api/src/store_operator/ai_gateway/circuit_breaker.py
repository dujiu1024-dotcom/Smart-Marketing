from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock

from store_operator.ai_gateway.errors import ProviderError, ProviderErrorCode


class CircuitBreaker:
    """Thread-safe closed/open/half-open breaker for transient provider failures."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout_seconds: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("Circuit breaker failure threshold must be positive")
        if reset_timeout_seconds <= 0:
            raise ValueError("Circuit breaker reset timeout must be positive")
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout_seconds
        self._clock = clock
        self._lock = Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._half_open_probe:
                return "half_open"
            return "open"

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            elapsed = max(0.0, self._clock() - self._opened_at)
            remaining = self._reset_timeout - elapsed
            if remaining > 0:
                raise ProviderError(
                    ProviderErrorCode.UNAVAILABLE,
                    retryable=True,
                    retry_after_seconds=remaining,
                    user_safe_summary="The AI provider circuit is open; retry after its cooldown.",
                )
            if self._half_open_probe:
                raise ProviderError(
                    ProviderErrorCode.UNAVAILABLE,
                    retryable=True,
                    retry_after_seconds=self._reset_timeout,
                    user_safe_summary="The AI provider recovery probe is already in progress.",
                )
            self._half_open_probe = True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_probe = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._opened_at is not None or self._failures >= self._failure_threshold:
                self._opened_at = self._clock()
                self._half_open_probe = False
