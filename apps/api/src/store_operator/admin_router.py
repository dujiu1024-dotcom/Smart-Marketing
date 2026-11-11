from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.dependencies import AuthenticatedSession, require_csrf, require_platform_admin
from store_operator.auth.errors import ApiError
from store_operator.auth.schemas import MemberPatchRequest, MemberSummary
from store_operator.db import get_db
from store_operator.models.identity import Store, StoreMembership, User

router = APIRouter(prefix="/admin", tags=["platform-admin"])


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
            raise ApiError(409, "LAST_OWNER_REQUIRED", "At least one active owner is required")

    membership.role = new_role
    membership.status = new_status
    if new_status == "active":
        membership.joined_at = membership.joined_at or func.now()
        membership.revoked_at = None
    elif new_status in {"suspended", "removed"}:
        from datetime import UTC, datetime

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
        role=membership.role,
        status=membership.status,
    )
