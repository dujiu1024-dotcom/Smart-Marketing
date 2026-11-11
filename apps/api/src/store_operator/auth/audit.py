from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from store_operator.models.identity import AuditEvent


def record_audit(
    db: Session,
    request: Request,
    *,
    action: str,
    target_type: str,
    target_id: str | UUID | None,
    actor_user_id: UUID | None,
    store_id: UUID | None = None,
    actor_type: str = "user",
    result: str = "success",
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_type=actor_type,
            actor_id=actor_user_id,
            actor_user_id=actor_user_id,
            store_id=store_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            result=result,
            request_id=getattr(request.state, "request_id", "unavailable"),
            metadata_json=metadata or {},
        )
    )
