import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.db import get_db
from store_operator.models.store_knowledge import (
    Product,
    StoreProfile,
    StoreRecordRevision,
)
from store_operator.store_knowledge_schemas import (
    ProductCreate,
    ProductList,
    ProductRead,
    ProductUpdate,
    StoreProfileCreate,
    StoreProfileRead,
    StoreProfileUpdate,
)

router = APIRouter(prefix="/store", tags=["store-knowledge"])


def _store_id(context: AuthContext) -> UUID:
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    return context.request_store_id


def _expected_version(value: str | None) -> int:
    if value is None:
        raise ApiError(428, "VERSION_REQUIRED", "If-Match version is required")
    try:
        version = int(value.strip().strip('"'))
    except ValueError as exc:
        raise ApiError(400, "INVALID_VERSION", "If-Match must contain a version number") from exc
    if version < 1:
        raise ApiError(400, "INVALID_VERSION", "If-Match version must be positive")
    return version


def _record_revision(
    db: Session,
    *,
    store_id: UUID,
    record_type: str,
    record_id: UUID,
    version: int,
    snapshot: dict[str, object],
    fact_status: str,
    actor_id: UUID,
) -> None:
    fingerprint = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    db.add(
        StoreRecordRevision(
            id=uuid4(),
            store_id=store_id,
            record_type=record_type,
            record_id=record_id,
            version_no=version,
            snapshot_json=snapshot,
            schema_version=1,
            content_fingerprint=fingerprint,
            fact_status=fact_status,
            created_by_user_id=actor_id,
        )
    )


def _audit(
    db: Session,
    request: Request,
    *,
    action: str,
    record_type: str,
    record_id: UUID,
    actor_id: UUID,
    store_id: UUID,
    metadata: dict[str, object] | None = None,
) -> None:
    record_audit(
        db,
        request,
        action=action,
        target_type=record_type,
        target_id=record_id,
        actor_user_id=actor_id,
        store_id=store_id,
        metadata=metadata,
    )


@router.get("/profile", response_model=StoreProfileRead)
def get_store_profile(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> StoreProfileRead:
    store_id = _store_id(context)
    profile = db.scalar(
        select(StoreProfile).where(StoreProfile.store_id == store_id)
    )
    if profile is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    return StoreProfileRead.model_validate(profile)


@router.post(
    "/profile",
    response_model=StoreProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_store_profile(
    payload: StoreProfileCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> StoreProfileRead:
    store_id = _store_id(context)
    if db.scalar(select(StoreProfile.id).where(StoreProfile.store_id == store_id)):
        raise ApiError(409, "RESOURCE_ALREADY_EXISTS", "Store profile already exists")
    profile = StoreProfile(
        id=uuid4(),
        store_id=store_id,
        **payload.model_dump(),
        fact_status="pending_confirmation",
        current_version=1,
        created_by_user_id=auth.user.id,
        updated_by_user_id=auth.user.id,
    )
    db.add(profile)
    db.flush()
    _record_revision(
        db,
        store_id=store_id,
        record_type="store_profile",
        record_id=profile.id,
        version=1,
        snapshot=StoreProfileRead.model_validate(profile).model_dump(mode="json"),
        fact_status=profile.fact_status,
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action="store.profile.created",
        record_type="store_profile",
        record_id=profile.id,
        actor_id=auth.user.id,
        store_id=store_id,
    )
    db.commit()
    db.refresh(profile)
    return StoreProfileRead.model_validate(profile)


@router.patch("/profile", response_model=StoreProfileRead)
def update_store_profile(
    payload: StoreProfileUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> StoreProfileRead:
    store_id = _store_id(context)
    expected = _expected_version(if_match)
    profile = db.scalar(
        select(StoreProfile)
        .where(StoreProfile.store_id == store_id)
        .with_for_update()
    )
    if profile is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if profile.current_version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "Store profile has changed")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    profile.current_version += 1
    profile.fact_status = "pending_confirmation"
    profile.updated_by_user_id = auth.user.id
    db.flush()
    _record_revision(
        db,
        store_id=store_id,
        record_type="store_profile",
        record_id=profile.id,
        version=profile.current_version,
        snapshot=StoreProfileRead.model_validate(profile).model_dump(mode="json"),
        fact_status=profile.fact_status,
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action="store.profile.updated",
        record_type="store_profile",
        record_id=profile.id,
        actor_id=auth.user.id,
        store_id=store_id,
        metadata={"version": profile.current_version},
    )
    db.commit()
    db.refresh(profile)
    return StoreProfileRead.model_validate(profile)


@router.get("/products", response_model=ProductList)
def list_products(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
    offset: int = 0,
) -> ProductList:
    store_id = _store_id(context)
    if not 1 <= limit <= 200 or offset < 0:
        raise ApiError(400, "INVALID_PAGINATION", "Invalid pagination parameters")
    total = db.scalar(
        select(func.count()).select_from(Product).where(Product.store_id == store_id)
    ) or 0
    products = db.scalars(
        select(Product)
        .where(Product.store_id == store_id)
        .order_by(Product.created_at.desc(), Product.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return ProductList(
        items=[ProductRead.model_validate(item) for item in products],
        total=total,
    )


@router.post(
    "/products",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    payload: ProductCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> ProductRead:
    store_id = _store_id(context)
    product = Product(
        id=uuid4(),
        store_id=store_id,
        **payload.model_dump(),
        fact_status="pending_confirmation",
        current_version=1,
        created_by_user_id=auth.user.id,
        updated_by_user_id=auth.user.id,
    )
    db.add(product)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409, "PRODUCT_CONFLICT", "Product conflicts with an existing record"
        ) from exc
    result = ProductRead.model_validate(product)
    _record_revision(
        db,
        store_id=store_id,
        record_type="product",
        record_id=product.id,
        version=1,
        snapshot=result.model_dump(mode="json"),
        fact_status=product.fact_status,
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action="store.product.created",
        record_type="product",
        record_id=product.id,
        actor_id=auth.user.id,
        store_id=store_id,
    )
    db.commit()
    db.refresh(product)
    return ProductRead.model_validate(product)


@router.get("/products/{product_id}", response_model=ProductRead)
def get_product(
    product_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> ProductRead:
    product = db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.store_id == _store_id(context),
        )
    )
    if product is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    return ProductRead.model_validate(product)


@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProductRead:
    store_id = _store_id(context)
    expected = _expected_version(if_match)
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id, Product.store_id == store_id)
        .with_for_update()
    )
    if product is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if product.current_version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "Product has changed")
    changes = payload.model_dump(exclude_unset=True)
    merged_price = changes.get("price_amount", product.price_amount)
    merged_currency = changes.get("currency", product.currency)
    if (merged_price is None) != (merged_currency is None):
        raise ApiError(
            422,
            "PRICE_CURRENCY_MISMATCH",
            "price_amount and currency must be provided together",
        )
    for field, value in changes.items():
        setattr(product, field, value)
    product.current_version += 1
    product.fact_status = "pending_confirmation"
    product.updated_by_user_id = auth.user.id
    db.flush()
    result = ProductRead.model_validate(product)
    _record_revision(
        db,
        store_id=store_id,
        record_type="product",
        record_id=product.id,
        version=product.current_version,
        snapshot=result.model_dump(mode="json"),
        fact_status=product.fact_status,
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action="store.product.updated",
        record_type="product",
        record_id=product.id,
        actor_id=auth.user.id,
        store_id=store_id,
        metadata={"version": product.current_version},
    )
    db.commit()
    db.refresh(product)
    return ProductRead.model_validate(product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: UUID,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Response:
    store_id = _store_id(context)
    expected = _expected_version(if_match)
    product = db.scalar(
        select(Product)
        .where(Product.id == product_id, Product.store_id == store_id)
        .with_for_update()
    )
    if product is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if product.current_version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "Product has changed")
    snapshot = ProductRead.model_validate(product).model_dump(mode="json")
    _record_revision(
        db,
        store_id=store_id,
        record_type="product",
        record_id=product.id,
        version=product.current_version + 1,
        snapshot=snapshot,
        fact_status="expired",
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action="store.product.deleted",
        record_type="product",
        record_id=product.id,
        actor_id=auth.user.id,
        store_id=store_id,
    )
    db.delete(product)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
