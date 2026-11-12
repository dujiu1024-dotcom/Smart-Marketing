from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from store_operator_worker import tasks


class FakeSession:
    def __init__(self, row, scalar_values):
        self.row = row
        self.scalar_values = list(scalar_values)
        self.added = []

    def execute(self, _statement):
        return SimpleNamespace(first=lambda: self.row)

    def scalar(self, _statement):
        return self.scalar_values.pop(0)

    def add(self, item):
        self.added.append(item)

    def flush(self):
        return None


class FakeBegin(AbstractContextManager):
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def begin(self):
        return FakeBegin(self.session)


def test_verified_douyin_readback_registers_work_and_evidence_idempotently(monkeypatch):
    store_id = uuid4()
    operation_id = uuid4()
    package_id = uuid4()
    account_id = uuid4()
    operation = SimpleNamespace(
        id=operation_id,
        store_id=store_id,
        platform_item_id="douyin-item-123",
        published_at=None,
        status="processing",
        last_readback_at=None,
        next_attempt_at=datetime.now(UTC),
        last_error_code="DOUYIN_READBACK_PENDING",
        last_error_summary="Waiting for readback",
    )
    package = SimpleNamespace(id=package_id, task_id=uuid4())
    package_item = SimpleNamespace(
        publish_package_id=package_id,
        channel_key="douyin",
        channel_account_id=account_id,
    )
    account = SimpleNamespace(id=account_id, provider="douyin")
    row = (operation, package, package_item, account)
    first_session = FakeSession(row, [None, None])
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(first_session))

    work_id = tasks._register_douyin_verified_work(
        operation_id,
        store_id,
        platform_item_id="douyin-item-123",
        readback={
            "title": "Verified title",
            "share_url": "https://www.douyin.com/note/123",
        },
    )

    assert operation.status == "published"
    assert operation.published_at is not None
    assert operation.last_readback_at is not None
    assert operation.next_attempt_at is None
    assert operation.last_error_code is None
    assert len(first_session.added) == 2
    work, evidence = first_session.added
    assert work.id == work_id
    assert work.ownership_status == "verified_system_publish"
    assert work.publish_operation_id == operation_id
    assert work.task_id == package.task_id
    assert evidence.published_work_id == work_id
    assert evidence.evidence_type == "system_publish_readback"
    assert evidence.evidence_status == "verified"

    second_session = FakeSession(row, [work, evidence.id])
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(second_session))
    replayed_work_id = tasks._register_douyin_verified_work(
        operation_id,
        store_id,
        platform_item_id="douyin-item-123",
        readback={"title": "Verified title"},
    )
    assert replayed_work_id == work_id
    assert second_session.added == []
