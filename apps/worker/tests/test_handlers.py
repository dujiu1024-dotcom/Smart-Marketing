from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest

from store_operator_worker.handlers import (
    JobCancelled,
    JobExecutionContext,
    JobExecutionError,
    JobLeaseLost,
    JobTimedOut,
    clear_job_handlers_for_testing,
    register_job_handler,
    resolve_job_handler,
)


def test_handler_registry_registers_explicit_job_types() -> None:
    clear_job_handlers_for_testing()

    @register_job_handler("test.generate")
    def handler(context, payload):
        return {"schema_version": 1, "artifact_ref": "test"}

    assert resolve_job_handler("test.generate") is handler
    assert resolve_job_handler("unregistered") is None
    clear_job_handlers_for_testing()


def test_handler_registry_rejects_duplicate_job_type() -> None:
    clear_job_handlers_for_testing()

    @register_job_handler("test.duplicate")
    def first(context, payload):
        return {"schema_version": 1}

    with pytest.raises(ValueError):
        @register_job_handler("test.duplicate")
        def second(context, payload):
            return {"schema_version": 1}

    clear_job_handlers_for_testing()


def make_context(
    *,
    cancelled: bool = False,
    lease_lost: bool = False,
    deadline_at: datetime | None = None,
) -> JobExecutionContext:
    cancellation_event = Event()
    lease_lost_event = Event()
    if cancelled:
        cancellation_event.set()
    if lease_lost:
        lease_lost_event.set()
    return JobExecutionContext(
        job_id=uuid4(),
        store_id=uuid4(),
        attempt_id=uuid4(),
        lease_token=uuid4(),
        worker_id="worker-test",
        deadline_at=deadline_at or datetime.now(UTC) + timedelta(minutes=1),
        cancellation_requested=cancellation_event,
        lease_lost=lease_lost_event,
        update_progress_callback=lambda current, total: None,
    )


def test_execution_context_checks_cancellation_lease_and_deadline() -> None:
    with pytest.raises(JobCancelled):
        make_context(cancelled=True).check_control()

    with pytest.raises(JobLeaseLost):
        make_context(lease_lost=True).check_control()

    with pytest.raises(JobTimedOut):
        make_context(deadline_at=datetime.now(UTC) - timedelta(seconds=1)).check_control()


def test_execution_error_requires_safe_retry_metadata() -> None:
    error = JobExecutionError(
        "PROVIDER_TIMEOUT",
        "Provider request timed out",
        retryable=True,
        retry_delay_seconds=15,
    )
    assert error.code == "PROVIDER_TIMEOUT"
    assert error.retryable is True
    assert error.retry_delay_seconds == 15

    with pytest.raises(ValueError):
        JobExecutionError("", "missing code", retryable=False)
