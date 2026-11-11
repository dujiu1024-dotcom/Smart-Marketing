from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from store_operator.ai_gateway.errors import SideEffectState
from store_operator_worker.handlers import JobExecutionContext, JobExecutionError


class FakeSession:
    def __init__(self, operation):
        self.operation = operation

    def scalar(self, _statement):
        return self.operation

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeSessionFactory:
    def __init__(self, operation):
        self.operation = operation

    def __call__(self):
        return FakeSession(self.operation)

    @contextmanager
    def begin(self):
        yield FakeSession(self.operation)


def test_uncertain_create_state_is_never_submitted_twice(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    store_id = uuid4()
    operation = SimpleNamespace(
        id=uuid4(),
        store_id=store_id,
        status="submitting",
        platform_item_id=None,
        last_error_code=None,
        last_error_summary=None,
    )
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(operation))
    context = JobExecutionContext(
        job_id=uuid4(),
        store_id=store_id,
        attempt_id=uuid4(),
        lease_token=uuid4(),
        worker_id="douyin-publish-test",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        cancellation_requested=Event(),
        lease_lost=Event(),
        update_progress_callback=lambda _current, _total: None,
    )

    with pytest.raises(JobExecutionError) as error:
        tasks.execute_douyin_image_text_publish(
            context,
            {
                "schema_version": 1,
                "publish_operation_id": str(operation.id),
            },
        )

    assert error.value.code == "DOUYIN_CREATE_RESULT_UNKNOWN"
    assert error.value.side_effect_state is SideEffectState.UNKNOWN
    assert operation.status == "needs_human"
