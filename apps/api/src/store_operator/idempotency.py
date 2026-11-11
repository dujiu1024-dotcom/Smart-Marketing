import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.auth.errors import ApiError
from store_operator.models.store_knowledge import IdempotencyRecord


def begin_idempotency(
    db: Session,
    *,
    store_id: UUID,
    actor_user_id: UUID,
    key: str,
    operation: str,
    payload: BaseModel,
    ttl: timedelta = timedelta(hours=24),
) -> tuple[IdempotencyRecord | None, dict[str, object] | None]:
    normalized_key = key.strip()
    if not normalized_key or len(normalized_key) > 255:
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key is invalid")

    request_hash = hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    now = datetime.now(UTC)
    existing = db.scalar(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.store_id == store_id,
            IdempotencyRecord.idempotency_key == normalized_key,
        )
        .with_for_update()
    )
    if existing is not None and existing.expires_at <= now:
        db.delete(existing)
        db.flush()
        existing = None

    if existing is not None:
        if existing.actor_user_id != actor_user_id:
            raise ApiError(
                409,
                "IDEMPOTENCY_KEY_SCOPE_MISMATCH",
                "Idempotency-Key belongs to a different actor",
            )
        if existing.operation != operation or existing.request_hash != request_hash:
            raise ApiError(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency-Key was already used for a different request",
            )
        if existing.status == "completed" and existing.response_json is not None:
            return None, existing.response_json
        raise ApiError(
            409, "IDEMPOTENCY_IN_PROGRESS", "An identical request is still processing"
        )

    record = IdempotencyRecord(
        id=uuid4(),
        store_id=store_id,
        idempotency_key=normalized_key,
        actor_user_id=actor_user_id,
        operation=operation,
        request_hash=request_hash,
        status="in_progress",
        expires_at=now + ttl,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        winner = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.store_id == store_id,
                IdempotencyRecord.idempotency_key == normalized_key,
            )
        )
        if winner is not None and winner.actor_user_id != actor_user_id:
            raise ApiError(
                409,
                "IDEMPOTENCY_KEY_SCOPE_MISMATCH",
                "Idempotency-Key belongs to a different actor",
            ) from exc
        if (
            winner is not None
            and winner.operation == operation
            and winner.request_hash == request_hash
            and winner.status == "completed"
            and winner.response_json is not None
        ):
            return None, winner.response_json
        raise ApiError(
            409, "IDEMPOTENCY_IN_PROGRESS", "An identical request is still processing"
        ) from exc
    return record, None


def complete_idempotency(
    record: IdempotencyRecord | None,
    *,
    response: dict[str, object],
    resource_type: str,
    resource_id: UUID,
    response_status: int = 201,
) -> None:
    if record is None:
        return
    record.status = "completed"
    record.response_status = response_status
    record.response_json = response
    record.resource_type = resource_type
    record.resource_id = resource_id
