from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@localhost:5432/test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from store_operator_worker.handlers import JobExecutionContext, JobExecutionError, resolve_job_handler
from store_operator_worker.tasks import execute_douyin_publish, execute_douyin_readback


def make_context() -> JobExecutionContext:
    return JobExecutionContext(
        job_id=uuid4(),
        store_id=uuid4(),
        attempt_id=uuid4(),
        lease_token=uuid4(),
        worker_id="worker-douyin-test",
        deadline_at=datetime.now(UTC) + timedelta(minutes=2),
        cancellation_requested=Event(),
        lease_lost=Event(),
        update_progress_callback=lambda _current, _total: None,
    )


def test_douyin_publish_and_readback_handlers_are_registered() -> None:
    assert resolve_job_handler("channel.douyin.publish") is execute_douyin_publish
    assert resolve_job_handler("channel.douyin.readback") is execute_douyin_readback


def test_douyin_publish_rejects_unsupported_payload_before_database_access() -> None:
    with pytest.raises(JobExecutionError, match="payload is invalid"):
        execute_douyin_publish(make_context(), {"schema_version": 2})


def test_douyin_readback_rejects_invalid_attempt_before_database_access() -> None:
    with pytest.raises(JobExecutionError, match="attempt is invalid"):
        execute_douyin_readback(
            make_context(),
            {
                "schema_version": 1,
                "publish_operation_id": str(uuid4()),
                "readback_attempt": 0,
            },
        )
