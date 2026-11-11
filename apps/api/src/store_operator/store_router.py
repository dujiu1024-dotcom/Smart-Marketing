from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.dependencies import AuthenticatedSession, require_csrf, get_current_session
from store_operator.auth.errors import ApiError
from store_operator.auth.schemas import (
    ActiveStoreRequest,
    ActiveStoreResponse,
    StoreMembershipSummary,
    StoreSummary,
    StoresResponse,
)
from store_operator.db import get_db
from store_operator.models.identity import Store, StoreMembership

router = APIRouter(tags=["store-context"])


@router.get("/me/stores", response_model=StoresResponse)
def list_my_stores(
    auth: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> StoresResponse:
    rows = db.execute(
        select(Store, StoreMembership)
        .join(StoreMembership, StoreMembership.store_id == Store.id)
        .where(
            StoreMembership.user_id == auth.user.id,
            StoreMembership.status == "active",
            Store.status == "active",
        )
        .order_by(Store.name, Store.id)
    ).all()
    active_store_id = auth.session.active_store_id
    if active_store_id and not any(store.id == active_store_id for store, _ in rows):
        active_store_id = None
        auth.session.active_store_id = None
        db.commit()
    return StoresResponse(
        items=[
            StoreMembershipSummary(id=store.id, name=store.name, role=membership.role)
            for store, membership in rows
        ],
        active_store_id=active_store_id,
    )


@router.post("/session/active-store", response_model=ActiveStoreResponse)
def set_active_store(
    payload: ActiveStoreRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ActiveStoreResponse:
    row = db.execute(
        select(Store, StoreMembership)
        .join(StoreMembership, StoreMembership.store_id == Store.id)
        .where(
            Store.id == payload.store_id,
            Store.status == "active",
            StoreMembership.user_id == auth.user.id,
            StoreMembership.status == "active",
        )
    ).first()
    if row is None:
        record_audit(
            db,
            request,
            action="store.active_store.select",
            target_type="store",
            target_id=payload.store_id,
            actor_user_id=auth.user.id,
            result="denied",
        )
        db.commit()
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found")
    store, membership = row
    auth.session.active_store_id = store.id
    record_audit(
        db,
        request,
        action="store.active_store.select",
        target_type="store",
        target_id=store.id,
        actor_user_id=auth.user.id,
        store_id=store.id,
        metadata={"membership_id": str(membership.id)},
    )
    db.commit()
    return ActiveStoreResponse(
        active_store=StoreSummary(id=store.id, name=store.name),
        membership={"role": membership.role},
    )


@router.delete("/session/active-store", status_code=status.HTTP_204_NO_CONTENT)
def clear_active_store(
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    auth.session.active_store_id = None
    record_audit(
        db,
        request,
        action="store.active_store.clear",
        target_type="session",
        target_id=auth.session.id,
        actor_user_id=auth.user.id,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
