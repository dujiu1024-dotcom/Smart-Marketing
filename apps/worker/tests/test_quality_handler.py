from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from store_operator.models import ArtifactVersion, ChannelContent, QualityReport

from store_operator_worker.handlers import JobExecutionContext, JobExecutionError


class FakeSession:
    def __init__(self, scalar_values):
        self.scalar_values = iter(scalar_values)
        self.added = []

    def scalar(self, _statement):
        return next(self.scalar_values)

    def scalars(self, _statement):
        return type("Rows", (), {"all": lambda self: []})()

    def add(self, value):
        self.added.append(value)

    def flush(self):
        return None


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    @contextmanager
    def begin(self):
        yield self.session


def make_context():
    now = datetime.now(UTC)
    return JobExecutionContext(
        job_id=uuid4(),
        store_id=uuid4(),
        attempt_id=uuid4(),
        lease_token=uuid4(),
        worker_id="quality-test-worker",
        deadline_at=now + timedelta(minutes=1),
        cancellation_requested=Event(),
        lease_lost=Event(),
        update_progress_callback=lambda _current, _total: None,
    )


def load_tasks_module(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    return tasks


def test_quality_handler_revalidates_and_persists_immutable_report(monkeypatch) -> None:
    tasks = load_tasks_module(monkeypatch)
    context = make_context()
    content_id = uuid4()
    copy_version_id = uuid4()
    channel_content = ChannelContent(
        id=content_id,
        store_id=context.store_id,
        task_id=uuid4(),
        channel_key="douyin",
        copy_version_id=copy_version_id,
        channel_spec_version_id=uuid4(),
        payload_json={"title": "Lunch gathering", "body": "Join us this week."},
        input_fingerprint="a" * 64,
        status="ready",
    )
    copy_version = ArtifactVersion(
        id=copy_version_id,
        artifact_id=uuid4(),
        content_json={"title": "Lunch gathering", "body": "Join us this week."},
    )
    session = FakeSession([channel_content, copy_version, uuid4(), None])
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(session))

    result = tasks.execute_content_quality_check(
        context,
        {
            "schema_version": 1,
            "channel_content_id": str(content_id),
            "expected_fingerprint": "a" * 64,
            "rule_version": "content-structure-v1",
        },
    )

    assert result["result"] == "pass"
    assert result["rule_version"] == "content-structure-v1"
    report = next(item for item in session.added if isinstance(item, QualityReport))
    assert report.channel_content_id == content_id
    assert report.input_fingerprint == result["input_fingerprint"]
    assert report.result == "pass"


def test_quality_handler_rejects_stale_channel_content(monkeypatch) -> None:
    tasks = load_tasks_module(monkeypatch)
    context = make_context()
    channel_content = ChannelContent(
        id=uuid4(),
        store_id=context.store_id,
        task_id=uuid4(),
        channel_key="douyin",
        copy_version_id=uuid4(),
        channel_spec_version_id=uuid4(),
        payload_json={"title": "Lunch"},
        input_fingerprint="b" * 64,
        status="ready",
    )
    session = FakeSession([channel_content])
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(session))

    with pytest.raises(JobExecutionError) as error:
        tasks.execute_content_quality_check(
            context,
            {
                "schema_version": 1,
                "channel_content_id": str(channel_content.id),
                "expected_fingerprint": "c" * 64,
                "rule_version": "content-structure-v1",
            },
        )
    assert error.value.code == "CHANNEL_CONTENT_STALE"
    assert session.added == []
