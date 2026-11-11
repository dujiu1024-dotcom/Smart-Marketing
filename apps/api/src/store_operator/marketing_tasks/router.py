from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_store_context,
)
from store_operator.db import get_db
from store_operator.domain.marketing_task import MarketingTaskStatus, MarketingTaskType
from store_operator.marketing_tasks.schemas import (
    MarketingTaskCreate,
    MarketingTaskDetail,
    MarketingTaskList,
)
from store_operator.marketing_tasks.service import (
    create_marketing_task,
    get_marketing_task,
    list_marketing_tasks,
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


@router.get("/{task_id}", response_model=MarketingTaskDetail)
def get_task(
    task_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> MarketingTaskDetail:
    return get_marketing_task(db, context, task_id)
