from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.db import get_db
from store_operator.domain.marketing_task import (
    MarketingTaskStatus,
    MarketingTaskType,
    TaskStepKey,
)
from store_operator.models.marketing_task import BusinessFactSnapshot, MarketingTask
from store_operator.marketing_tasks.schemas import (
    MarketingTaskAction,
    MarketingTaskCreate,
    MarketingTaskDetail,
    MarketingTaskList,
    MarketingTaskRecover,
    MarketingTaskRequirementConfirm,
    MarketingTaskRequirementUpdate,
    MarketingTaskStepSkip,
    MarketingTaskStrategyConfirm,
    MarketingTaskStrategyUpdate,
)
from store_operator.marketing_tasks.service import (
    archive_marketing_task,
    cancel_marketing_task,
    confirm_requirement,
    confirm_strategy,
    create_marketing_task,
    get_marketing_task,
    list_marketing_tasks,
    recover_marketing_task,
    skip_task_step,
    update_requirement_draft,
    update_strategy_draft,
)

router = APIRouter(prefix="/marketing-tasks", tags=["marketing-tasks"])


@router.post(
    "",
    response_model=MarketingTaskDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    payload: MarketingTaskCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return create_marketing_task(
        db,
        request,
        auth,
        context,
        payload,
        idempotency_key,
    )


@router.get("", response_model=MarketingTaskList)
def list_tasks(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    lifecycle_status: MarketingTaskStatus | None = None,
    task_type: MarketingTaskType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MarketingTaskList:
    return list_marketing_tasks(
        db,
        context,
        lifecycle_status=lifecycle_status,
        task_type=task_type,
        limit=limit,
        offset=offset,
    )



@router.get("/{task_id}/business-facts")
def list_task_business_facts(
    task_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    task = db.scalar(
        select(BusinessFactSnapshot.task_id).where(
            BusinessFactSnapshot.task_id == task_id,
            BusinessFactSnapshot.store_id == store_id,
        ).limit(1)
    )
    if task is None:
        task_exists = db.scalar(
            select(MarketingTask.id).where(
                MarketingTask.id == task_id,
                MarketingTask.store_id == store_id,
            )
        )
        if task_exists is None:
            raise ApiError(404, "TASK_NOT_FOUND", "Marketing task not found")
    facts = db.scalars(
        select(BusinessFactSnapshot)
        .where(
            BusinessFactSnapshot.task_id == task_id,
            BusinessFactSnapshot.store_id == store_id,
        )
        .order_by(BusinessFactSnapshot.fact_key, BusinessFactSnapshot.version_no.desc())
    ).all()
    latest: dict[str, BusinessFactSnapshot] = {}
    for fact in facts:
        latest.setdefault(fact.fact_key, fact)
    return [
        {
            "id": str(fact.id),
            "fact_key": fact.fact_key,
            "version_no": fact.version_no,
            "value": fact.value_json,
            "content_fingerprint": fact.content_fingerprint,
            "confirmation_status": fact.confirmation_status,
            "confirmed_at": fact.confirmed_at.isoformat() if fact.confirmed_at else None,
        }
        for fact in latest.values()
    ]


@router.get("/{task_id}", response_model=MarketingTaskDetail)
def get_task(
    task_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> MarketingTaskDetail:
    return get_marketing_task(db, context, task_id)



@router.patch("/{task_id}/requirement", response_model=MarketingTaskDetail)
def patch_requirement(
    task_id: UUID,
    payload: MarketingTaskRequirementUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return update_requirement_draft(
        db, request, auth, context, task_id, payload, idempotency_key
    )


@router.post("/{task_id}/requirement/confirm", response_model=MarketingTaskDetail)
def confirm_task_requirement(
    task_id: UUID,
    payload: MarketingTaskRequirementConfirm,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return confirm_requirement(
        db, request, auth, context, task_id, payload, idempotency_key
    )


@router.patch("/{task_id}/strategy", response_model=MarketingTaskDetail)
def patch_strategy(
    task_id: UUID,
    payload: MarketingTaskStrategyUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return update_strategy_draft(
        db, request, auth, context, task_id, payload, idempotency_key
    )


@router.post("/{task_id}/strategy/confirm", response_model=MarketingTaskDetail)
def confirm_task_strategy(
    task_id: UUID,
    payload: MarketingTaskStrategyConfirm,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return confirm_strategy(
        db, request, auth, context, task_id, payload, idempotency_key
    )


@router.post(
    "/{task_id}/steps/{step_key}/skip",
    response_model=MarketingTaskDetail,
)
def skip_step(
    task_id: UUID,
    step_key: TaskStepKey,
    payload: MarketingTaskStepSkip,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return skip_task_step(
        db,
        request,
        auth,
        context,
        task_id,
        step_key,
        payload,
        idempotency_key,
    )


@router.post("/{task_id}/recover", response_model=MarketingTaskDetail)
def recover_task(
    task_id: UUID,
    payload: MarketingTaskRecover,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return recover_marketing_task(
        db, request, auth, context, task_id, payload, idempotency_key
    )


@router.post("/{task_id}/cancel", response_model=MarketingTaskDetail)
def cancel_task(
    task_id: UUID,
    payload: MarketingTaskAction,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return cancel_marketing_task(
        db, request, auth, context, task_id, payload, idempotency_key
    )


@router.post("/{task_id}/archive", response_model=MarketingTaskDetail)
def archive_task(
    task_id: UUID,
    payload: MarketingTaskAction,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> MarketingTaskDetail:
    return archive_marketing_task(
        db, request, auth, context, task_id, payload, idempotency_key
    )
