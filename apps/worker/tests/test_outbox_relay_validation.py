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
