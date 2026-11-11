from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_platform_admin,
)
from store_operator.auth.errors import ApiError
from store_operator.auth.schemas import MemberPatchRequest, MemberSummary
from store_operator.db import get_db
from store_operator.models.identity import Store, StoreMembership, User
from store_operator.models.job_runtime import Job, OutboxEvent

router = APIRouter(prefix="/admin", tags=["platform-admin"])


class OutboxRequeueRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)


@router.get("/stores/{store_id}/members", response_model=list[MemberSummary])
def list_store_members(
    store_id: UUID,
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MemberSummary]:
    if db.get(Store, store_id) is None:
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found")
    rows = db.execute(
        select(StoreMembership, User)
        .join(User, User.id == StoreMembership.user_id)
        .where(StoreMembership.store_id == store_id)
        .order_by(User.email_normalized, StoreMembership.id)
    ).all()
    return [
        MemberSummary(
            membership_id=membership.id,
            user_id=user.id,
            email=user.email_normalized,
            role=membership.role,
            status=membership.status,
        )
        for membership, user in rows
    ]


@router.patch(
    "/stores/{store_id}/members/{membership_id}", response_model=MemberSummary
)
def update_store_member(
    store_id: UUID,
    membership_id: UUID,
    payload: MemberPatchRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> MemberSummary:
    store = db.scalar(select(Store).where(Store.id == store_id).with_for_update())
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found")
    membership = db.scalar(
        select(StoreMembership)
        .where(
            StoreMembership.id == membership_id,
            StoreMembership.store_id == store_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")

    new_role = payload.role if payload.role is not None else membership.role
    new_status = payload.status if payload.status is not None else membership.status
    if membership.status in {"invited", "removed"} and new_status == "active":
        raise ApiError(
            409,
            "MEMBERSHIP_REINVITE_REQUIRED",
            "A new invitation is required to activate this membership",
        )
    removes_last_owner = (
        membership.role == "owner"
        and membership.status == "active"
        and (new_role != "owner" or new_status != "active")
    )
    if removes_last_owner:
        active_owner_count = db.scalar(
            select(func.count())
            .select_from(StoreMembership)
            .where(
                StoreMembership.store_id == store_id,
                StoreMembership.role == "owner",
                StoreMembership.status == "active",
            )
        ) or 0
        if active_owner_count <= 1:
            record_audit(
                db,
                request,
                action="store.membership.update",
                target_type="store_membership",
                target_id=membership.id,
                actor_user_id=auth.user.id,
                store_id=store_id,
                actor_type="platform_admin",
                result="denied",
                metadata={"attempted_role": new_role, "attempted_status": new_status},
            )
            db.commit()
            raise ApiError(409, "LAST_OWNER_REQUIRED", "At least one active owner is required")

    membership.role = new_role
    membership.status = new_status
    if new_status == "active":
        membership.joined_at = membership.joined_at or datetime.now(UTC)
        membership.revoked_at = None
    elif new_status in {"suspended", "removed"}:
        membership.revoked_at = datetime.now(UTC)
    record_audit(
        db,
        request,
        action="store.membership.updated",
        target_type="store_membership",
        target_id=membership.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        actor_type="platform_admin",
        metadata={
            "role": membership.role,
            "status": membership.status,
        },
    )
    db.commit()
    user = db.get(User, membership.user_id)
    if user is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    return MemberSummary(
        membership_id=membership.id,
        user_id=user.id,
        email=user.email_normalized,
        role=cast(Literal["owner", "member"], membership.role),
        status=cast(
            Literal["invited", "active", "suspended", "removed"], membership.status
        ),
    )



@router.post("/outbox-events/{event_id}/requeue")
def requeue_dead_outbox_event(
    event_id: UUID,
    payload: OutboxRequeueRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    event = db.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .with_for_update()
    )
    if event is None:
        raise ApiError(404, "OUTBOX_EVENT_NOT_FOUND", "Outbox event not found")
    if event.status != "dead":
        raise ApiError(
            409,
            "OUTBOX_EVENT_NOT_DEAD",
            "Only dead-lettered Outbox events can be requeued",
        )
    if event.event_type != "job.dispatch_requested" or event.aggregate_type != "job":
        raise ApiError(
            409,
            "OUTBOX_EVENT_UNSUPPORTED",
            "This Outbox event type cannot be manually requeued",
        )

    raw_job_id = event.payload_json.get("job_id")
    try:
        job_id = UUID(raw_job_id) if isinstance(raw_job_id, str) else None
    except ValueError as exc:
        raise ApiError(
            409, "OUTBOX_EVENT_INVALID", "Outbox event payload is invalid"
        ) from exc
    if job_id is None or job_id != event.aggregate_id:
        raise ApiError(
            409, "OUTBOX_EVENT_INVALID", "Outbox event payload is invalid"
        )

    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None or job.status not in {"queued", "retry_wait"}:
        raise ApiError(
            409,
            "OUTBOX_JOB_NOT_DISPATCHABLE",
            "The associated Job is no longer dispatchable",
        )

    now = datetime.now(UTC)
    previous_attempts = event.publish_attempts
    event.status = "pending"
    event.publish_attempts = 0
    event.available_at = now
    event.locked_by = None
    event.locked_until = None
    event.last_error = None
    event.published_at = None
    record_audit(
        db,
        request,
        action="outbox.event.requeued",
        target_type="outbox_event",
        target_id=event.id,
        actor_user_id=auth.user.id,
        store_id=job.store_id,
        actor_type="platform_admin",
        metadata={
            "reason": payload.reason,
            "job_id": str(job.id),
            "event_type": event.event_type,
            "previous_publish_attempts": previous_attempts,
        },
    )
    db.commit()
    return {
        "outbox_event_id": str(event.id),
        "job_id": str(job.id),
        "status": event.status,
        "previous_publish_attempts": previous_attempts,
        "available_at": event.available_at.isoformat(),
    }
