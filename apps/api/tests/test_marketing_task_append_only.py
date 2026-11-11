from uuid import uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from store_operator.models import MarketingTask, RequirementSnapshot, Store, TaskEvent, TaskStep


def create_task_with_store(db: Session) -> MarketingTask:
    store = Store(
        id=uuid4(),
        name="Marketing task persistence",
        timezone="Asia/Tokyo",
        status="active",
    )
    db.add(store)
    db.flush()
    task = MarketingTask(
        id=uuid4(),
        store_id=store.id,
        task_type="copy_only",
        lifecycle_status="draft",
        title="Seasonal promotion copy",
    )
    db.add(task)
    db.flush()
    return task


def test_requirement_snapshots_reject_updates(db_session: Session) -> None:
    task = create_task_with_store(db_session)
    snapshot = RequirementSnapshot(
        id=uuid4(),
        store_id=task.store_id,
        task_id=task.id,
        snapshot_no=1,
        payload_json={"goal": "increase weekday visits"},
        content_fingerprint="a" * 64,
    )
    db_session.add(snapshot)
    db_session.flush()

    with pytest.raises(DBAPIError):
        db_session.execute(
            update(RequirementSnapshot)
            .where(RequirementSnapshot.id == snapshot.id)
            .values(payload_json={"goal": "changed after confirmation"})
        )
    db_session.rollback()


def test_task_events_reject_deletes(db_session: Session) -> None:
    task = create_task_with_store(db_session)
    event = TaskEvent(
        id=uuid4(),
        store_id=task.store_id,
        task_id=task.id,
        event_type="task.created",
        aggregate_version=1,
        actor_type="system",
        payload_json={"source": "test"},
    )
    db_session.add(event)
    db_session.flush()

    with pytest.raises(DBAPIError):
        db_session.execute(delete(TaskEvent).where(TaskEvent.id == event.id))
    db_session.rollback()



@pytest.mark.parametrize(
    ("applicability", "status", "skip_reason"),
    [
        ("required", "skipped", "Required work cannot be skipped"),
        ("optional", "skipped", None),
        ("not_applicable", "pending", None),
    ],
)
def test_invalid_task_step_skip_states_are_rejected(
    db_session: Session,
    applicability: str,
    status: str,
    skip_reason: str | None,
) -> None:
    task = create_task_with_store(db_session)
    step = TaskStep(
        id=uuid4(),
        store_id=task.store_id,
        task_id=task.id,
        step_key="image_production_review",
        status=status,
        applicability=applicability,
        skip_reason=skip_reason,
    )
    db_session.add(step)
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()
