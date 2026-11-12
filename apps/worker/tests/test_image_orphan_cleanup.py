from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://ci:ci@localhost:5432/ci")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from store_operator_worker import tasks


class FakeResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeDatabase:
    def __init__(self, invocations, protected: bool = False):
        self.invocations = invocations
        self.protected = protected

    def scalars(self, statement):
        return FakeResult(self.invocations)

    def scalar(self, statement):
        return object() if self.protected else None


class FakeSessionContext:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        return self.database

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeSessionFactory:
    def __init__(self, database):
        self.database = database

    def begin(self):
        return FakeSessionContext(self.database)


def test_orphan_image_cleanup_deletes_only_unreferenced_store_scoped_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_id = uuid4()
    invocation = SimpleNamespace(
        id=uuid4(),
        store_id=store_id,
        response_ref_json={
            "schema_version": 1,
            "object_key": f"stores/{store_id}/generated/image.png",
        },
    )
    database = FakeDatabase([invocation])
    deleted: list[str] = []
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(database))
    monkeypatch.setattr(
        tasks,
        "delete_object",
        lambda *, object_key: deleted.append(object_key),
    )

    result = tasks.cleanup_orphaned_ai_image_objects.run()

    assert result == 1
    assert deleted == [invocation.response_ref_json["object_key"]]
    assert invocation.response_ref_json["orphan_cleanup_result"] == "deleted"
    assert invocation.response_ref_json["orphan_cleanup_completed_at"]


def test_orphan_image_cleanup_protects_registered_or_referenced_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_id = uuid4()
    invocation = SimpleNamespace(
        id=uuid4(),
        store_id=store_id,
        response_ref_json={
            "schema_version": 1,
            "object_key": f"stores/{store_id}/generated/registered.png",
        },
    )
    database = FakeDatabase([invocation], protected=True)
    deleted: list[str] = []
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(database))
    monkeypatch.setattr(
        tasks,
        "delete_object",
        lambda *, object_key: deleted.append(object_key),
    )

    result = tasks.cleanup_orphaned_ai_image_objects.run()

    assert result == 0
    assert deleted == []
    assert invocation.response_ref_json["orphan_cleanup_result"] == "protected_referenced"


def test_orphan_image_cleanup_never_deletes_cross_store_or_traversal_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_id = uuid4()
    invocation = SimpleNamespace(
        id=uuid4(),
        store_id=store_id,
        response_ref_json={
            "schema_version": 1,
            "object_key": f"stores/{uuid4()}/../other-store/image.png",
        },
    )
    database = FakeDatabase([invocation])
    deleted: list[str] = []
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(database))
    monkeypatch.setattr(
        tasks,
        "delete_object",
        lambda *, object_key: deleted.append(object_key),
    )

    result = tasks.cleanup_orphaned_ai_image_objects.run()

    assert result == 0
    assert deleted == []
    assert invocation.response_ref_json["orphan_cleanup_result"] == "skipped_invalid_key"
