from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from store_operator_worker.tasks import (
    _normalize_outbox_batch_size,
    _parse_dispatch_job_id,
    celery_app,
    relay_outbox,
)


def test_outbox_batch_size_is_bounded() -> None:
    assert _normalize_outbox_batch_size(1) == 1
    assert _normalize_outbox_batch_size(50) == 50
    assert _normalize_outbox_batch_size(10_000) == 500


@pytest.mark.parametrize("batch_size", [0, -1])
def test_outbox_batch_size_rejects_non_positive_values(batch_size: int) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        _normalize_outbox_batch_size(batch_size)


@pytest.mark.parametrize("batch_size", [True, 1.5, "10"])
def test_outbox_batch_size_rejects_non_integer_values(batch_size: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        _normalize_outbox_batch_size(batch_size)  # type: ignore[arg-type]


def test_outbox_dispatch_payload_requires_object_and_uuid() -> None:
    job_id = uuid4()
    assert _parse_dispatch_job_id({"job_id": str(job_id)}) == job_id

    with pytest.raises(TypeError, match="JSON object"):
        _parse_dispatch_job_id([])

    with pytest.raises(TypeError, match="job_id"):
        _parse_dispatch_job_id({"job_id": 123})

    with pytest.raises(ValueError, match="UUID"):
        _parse_dispatch_job_id({"job_id": "not-a-uuid"})


def test_outbox_relay_is_registered_as_celery_task() -> None:
    assert celery_app.tasks["jobs.relay_outbox"] is relay_outbox


class RelaySession:
    def __init__(self, event):
        self.event = event

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: [self.event])

    def get(self, _model, event_id):
        return self.event if self.event.id == event_id else None

    def scalar(self, _statement):
        return self.event


class RelaySessionFactory:
    def __init__(self, event):
        self.event = event

    @contextmanager
    def begin(self):
        yield RelaySession(self.event)

    @contextmanager
    def __call__(self):
        yield RelaySession(self.event)


def make_outbox_event(*, attempts: int = 0):
    return SimpleNamespace(
        id=uuid4(),
        status="pending",
        event_type="job.dispatch_requested",
        payload_json={"job_id": str(uuid4())},
        publish_attempts=attempts,
        available_at=datetime.now(UTC),
        locked_by=None,
        locked_until=None,
        published_at=None,
        last_error=None,
    )


def test_outbox_relay_publishes_and_clears_lease(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    event = make_outbox_event()
    monkeypatch.setattr(tasks, "SessionLocal", RelaySessionFactory(event))
    sent = []
    monkeypatch.setattr(
        tasks.celery_app,
        "send_task",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    assert tasks.relay_outbox() == 1
    assert len(sent) == 1
    assert sent[0][0][0] == "jobs.execute"
    assert sent[0][1]["task_id"] == str(event.id)
    assert event.status == "published"
    assert event.published_at is not None
    assert event.locked_by is None
    assert event.locked_until is None
    assert event.last_error is None


def test_outbox_relay_releases_lease_and_schedules_retry_on_broker_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    event = make_outbox_event()
    monkeypatch.setattr(tasks, "SessionLocal", RelaySessionFactory(event))

    def fail_send(*_args, **_kwargs):
        raise RuntimeError("broker credentials must not leak")

    monkeypatch.setattr(tasks.celery_app, "send_task", fail_send)

    assert tasks.relay_outbox() == 0
    assert event.status == "pending"
    assert event.publish_attempts == 1
    assert event.available_at > datetime.now(UTC)
    assert event.locked_by is None
    assert event.locked_until is None
    assert "broker credentials" not in (event.last_error or "")


@pytest.mark.parametrize("lease_state", ["missing", "expired"])
def test_outbox_relay_reclaims_stale_publishing_lease(monkeypatch, lease_state: str) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    event = make_outbox_event()
    event.status = "publishing"
    event.locked_by = "previous-relay"
    event.locked_until = (
        None
        if lease_state == "missing"
        else datetime.now(UTC) - timedelta(seconds=1)
    )
    monkeypatch.setattr(tasks, "SessionLocal", RelaySessionFactory(event))
    sent = []
    monkeypatch.setattr(
        tasks.celery_app,
        "send_task",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    assert tasks.relay_outbox() == 1
    assert len(sent) == 1
    assert event.status == "published"
    assert event.locked_by is None


def test_outbox_relay_dead_letters_after_retry_budget_and_alerts(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    event = make_outbox_event(attempts=tasks.OUTBOX_MAX_ATTEMPTS - 1)
    monkeypatch.setattr(tasks, "SessionLocal", RelaySessionFactory(event))
    alerts = []
    monkeypatch.setattr(
        tasks,
        "emit_operational_alert",
        lambda **kwargs: alerts.append(kwargs),
    )
    monkeypatch.setattr(
        tasks.celery_app,
        "send_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret")),
    )

    assert tasks.relay_outbox() == 0
    assert event.status == "dead"
    assert event.publish_attempts == tasks.OUTBOX_MAX_ATTEMPTS
    assert event.locked_by is None
    assert len(alerts) == 1
    assert alerts[0]["event"] == "outbox.dead_letter"
    assert alerts[0]["correlation_id"] == str(event.id)
