from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Callable, Protocol
from uuid import UUID

from store_operator.ai_gateway.errors import SideEffectState  # type: ignore[import-untyped]


class JobExecutionError(Exception):
    def __init__(
        self,
        code: str,
        safe_summary: str,
        *,
        retryable: bool,
        side_effect_state: SideEffectState = SideEffectState.NONE,
        retry_delay_seconds: int = 30,
    ) -> None:
        super().__init__(safe_summary)
        self.code = code
        self.safe_summary = safe_summary
        self.retryable = retryable
        self.side_effect_state = side_effect_state
        self.retry_delay_seconds = retry_delay_seconds


class JobCancelled(Exception):
    """Raised by a handler when the user requests cancellation."""


class JobTimedOut(Exception):
    """Raised when the persisted Job execution deadline has elapsed."""


class JobLeaseLost(Exception):
    """Raised when the Worker loses its fencing lease."""


@dataclass(frozen=True, slots=True)
class JobExecutionContext:
    job_id: UUID
    store_id: UUID | None
    attempt_id: UUID
    lease_token: UUID
    worker_id: str
    deadline_at: datetime
    cancellation_requested: Event
    lease_lost: Event
    update_progress_callback: Callable[[int | None, int | None], None]

    def check_control(self) -> None:
        if self.lease_lost.is_set():
            raise JobLeaseLost("Worker lease was lost")
        if self.cancellation_requested.is_set():
            raise JobCancelled("Job cancellation was requested")
        if datetime.now(UTC) >= self.deadline_at:
            raise JobTimedOut("Job execution deadline elapsed")

    def update_progress(
        self,
        *,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        self.check_control()
        self.update_progress_callback(current, total)
        self.check_control()


class JobHandler(Protocol):
    def __call__(
        self,
        context: JobExecutionContext,
        payload_ref: dict[str, object],
    ) -> dict[str, object]: ...


_HANDLERS: dict[str, JobHandler] = {}


def register_job_handler(job_type: str) -> Callable[[JobHandler], JobHandler]:
    normalized_type = job_type.strip()
    if not normalized_type or len(normalized_type) > 100:
        raise ValueError("job_type must contain 1-100 characters")

    def register(handler: JobHandler) -> JobHandler:
        if normalized_type in _HANDLERS:
            raise ValueError(f"A handler is already registered for {normalized_type}")
        _HANDLERS[normalized_type] = handler
        return handler

    return register


def resolve_job_handler(job_type: str) -> JobHandler | None:
    return _HANDLERS.get(job_type)


def clear_job_handlers_for_testing() -> None:
    """Clear registrations between isolated tests; never used by application startup."""
    _HANDLERS.clear()
