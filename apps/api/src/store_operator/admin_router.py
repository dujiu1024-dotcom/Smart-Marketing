from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

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
from store_operator.models.channel_spec import ChannelSpec, ChannelSpecVersion
from store_operator.models.identity import Store, StoreMembership, User
from store_operator.models.job_runtime import Job, OutboxEvent

router = APIRouter(prefix="/admin", tags=["platform-admin"])


class OutboxRequeueRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)

class ChannelSpecVersionPublishRequest(BaseModel):
    expected_current_version_id: UUID | None
    source_document_ref: str = Field(min_length=12, max_length=2048)
    text_constraints: dict[str, object] = Field(default_factory=dict)
    media_constraints: dict[str, object] = Field(default_factory=dict)
    hashtag_constraints: dict[str, object] = Field(default_factory=dict)
    link_constraints: dict[str, object] = Field(default_factory=dict)
    schedule_constraints: dict[str, object] = Field(default_factory=dict)
    draft_supported: bool = False
    publish_supported: bool = False



@router.post("/channel-specs/{channel_key}/versions")
def publish_channel_spec_version(
    channel_key: str,
    payload: ChannelSpecVersionPublishRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    if not payload.source_document_ref.startswith("https://"):
        raise ApiError(
            422,
            "CHANNEL_SPEC_SOURCE_REQUIRED",
            "A verified HTTPS official-source reference is required",
        )
    spec = db.scalar(
        select(ChannelSpec)
        .where(ChannelSpec.channel_key == channel_key, ChannelSpec.status == "active")
        .with_for_update()
    )
    if spec is None:
        raise ApiError(404, "CHANNEL_SPEC_NOT_FOUND", "Channel specification not found")
    if spec.current_version_id != payload.expected_current_version_id:
        raise ApiError(
            409,
            "STALE_CHANNEL_SPEC_VERSION",
            "Channel specification changed; refresh and retry",
        )
    latest_version = db.scalar(
        select(func.max(ChannelSpecVersion.spec_version)).where(
            ChannelSpecVersion.channel_spec_id == spec.id
        )
    ) or 0
    version = ChannelSpecVersion(
        id=uuid4(),
        channel_spec_id=spec.id,
        spec_version=latest_version + 1,
        text_constraints_json=payload.text_constraints,
        media_constraints_json=payload.media_constraints,
        hashtag_constraints_json=payload.hashtag_constraints,
        link_constraints_json=payload.link_constraints,
        schedule_constraints_json=payload.schedule_constraints,
        draft_supported=payload.draft_supported,
        publish_supported=payload.publish_supported,
        verification_status="verified",
        source_document_ref=payload.source_document_ref,
        published_at=datetime.now(UTC),
    )
    db.add(version)
    db.flush()
    spec.current_version_id = version.id
    record_audit(
        db,
        request,
        action="channel.spec_version.published",
        target_type="channel_spec_version",
        target_id=version.id,
        actor_user_id=auth.user.id,
        actor_type="platform_admin",
        metadata={
            "channel_key": channel_key,
            "spec_version": version.spec_version,
            "source_document_ref": payload.source_document_ref,
            "draft_supported": payload.draft_supported,
            "publish_supported": payload.publish_supported,
        },
    )
    db.commit()
    return {
        "id": str(version.id),
        "channel_spec_id": str(version.channel_spec_id),
        "spec_version": version.spec_version,
        "text_constraints": version.text_constraints_json,
        "media_constraints": version.media_constraints_json,
        "hashtag_constraints": version.hashtag_constraints_json,
        "link_constraints": version.link_constraints_json,
        "schedule_constraints": version.schedule_constraints_json,
        "draft_supported": version.draft_supported,
        "publish_supported": version.publish_supported,
        "verification_status": version.verification_status,
        "source_document_ref": version.source_document_ref,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "created_at": version.created_at.isoformat(),
    }


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
