from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4


class AttemptSession:
    def __init__(self, operation, attempts):
        self.operation = operation
        self.attempts = attempts
        self.scalar_calls = 0

    def scalar(self, _statement):
        self.scalar_calls += 1
        return self.operation if self.scalar_calls == 1 else None

    def add(self, attempt):
        self.attempts[attempt.id] = attempt

    def flush(self):
        return None

    def get(self, _model, attempt_id):
        return self.attempts.get(attempt_id)


class AttemptSessionFactory:
    def __init__(self, operation):
        self.operation = operation
        self.attempts = {}

    @contextmanager
    def begin(self):
        yield AttemptSession(self.operation, self.attempts)


def test_publish_api_attempt_is_persisted_and_finished(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    store_id = uuid4()
    operation_id = uuid4()
    operation = SimpleNamespace(
        id=operation_id,
        store_id=store_id,
        request_fingerprint="a" * 64,
    )
    factory = AttemptSessionFactory(operation)
    monkeypatch.setattr(tasks, "SessionLocal", factory)

    attempt_id = tasks._begin_douyin_publish_attempt(
        operation_id, store_id, action="publish_image_text"
    )
    attempt = factory.attempts[attempt_id]
    assert attempt.normalized_status == "started"
    assert attempt.request_fingerprint == "a" * 64

    tasks._finish_douyin_publish_attempt(
        attempt_id,
        normalized_status="accepted",
        retryable=False,
        external_request_id="douyin-request-123",
    )

    assert attempt.normalized_status == "accepted"
    assert attempt.external_request_id == "douyin-request-123"
    assert attempt.retryable is False
    assert attempt.finished_at is not None
