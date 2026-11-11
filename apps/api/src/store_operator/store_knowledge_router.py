import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4
import re

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel
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
from store_operator.idempotency import begin_idempotency, complete_idempotency
from store_operator.object_storage import (
    ObjectStorageNotConfigured,
    create_download_url,
    create_upload_url,
    head_object,
)
from store_operator.models.store_knowledge import (
    AudienceProfile,
    BrandGuideline,
    IdempotencyRecord,
    KnowledgeItem,
    MediaAsset,
    Offer,
    Product,
    StoreProfile,
    StoreRecordRevision,
    UploadIntent,
)
from store_operator.store_knowledge_schemas import (
    AssetUploadCompleteRead,
    AssetUploadIntentCreate,
    AssetUploadIntentRead,
    MediaAssetList,
    MediaAssetRead,
    AudienceProfileCreate,
    AudienceProfileList,
    AudienceProfileRead,
    AudienceProfileUpdate,
    BrandGuidelineCreate,
    BrandGuidelineRead,
    BrandGuidelineUpdate,
    FactConfirmationRequest,
    KnowledgeItemCreate,
    KnowledgeItemList,
    KnowledgeItemRead,
    KnowledgeItemUpdate,
    OfferCreate,
    OfferList,
    OfferRead,
    OfferUpdate,
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
    source_type: str | None = None,
    source_ref: str | None = None,
    confirmed_by_user_id: UUID | None = None,
    confirmed_at: datetime | None = None,
    change_reason: str | None = None,
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
            source_type=source_type,
            source_ref=source_ref,
            confirmed_by_user_id=confirmed_by_user_id,
            confirmed_at=confirmed_at,
            change_reason=change_reason,
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






def _begin_idempotency(
    db: Session,
    store_id: UUID,
    actor_user_id: UUID,
    key: str,
    operation: str,
    payload: BaseModel,
) -> tuple[IdempotencyRecord | None, dict[str, object] | None]:
    return begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=actor_user_id,
        key=key,
        operation=operation,
        payload=payload,
    )


def _complete_idempotency(
    record: IdempotencyRecord | None,
    response: dict[str, object],
    resource_type: str,
    resource_id: UUID,
) -> None:
    complete_idempotency(
        record,
        response=response,
        resource_type=resource_type,
        resource_id=resource_id,
    )


def _create_scoped_record(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    store_id: UUID,
    model: type[Any],
    read_schema: type[BaseModel],
    payload: BaseModel,
    record_type: str,
    idempotency_key: str,
    operation: str,
) -> dict[str, object]:
    idempotency_record, replay = _begin_idempotency(
        db, store_id, auth.user.id, idempotency_key, operation, payload
    )
    if replay is not None:
        return replay
    values = {
        "id": uuid4(),
        "store_id": store_id,
        **payload.model_dump(),
        "fact_status": "pending_confirmation",
        "current_version": 1,
    }
    if "created_by_user_id" in model.__table__.columns:
        values["created_by_user_id"] = auth.user.id
    if "updated_by_user_id" in model.__table__.columns:
        values["updated_by_user_id"] = auth.user.id
    record = model(**values)
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409, "RECORD_CONFLICT", "Record conflicts with an existing record"
        ) from exc
    snapshot = read_schema.model_validate(record).model_dump(mode="json")
    _record_revision(
        db,
        store_id=store_id,
        record_type=record_type,
        record_id=record.id,
        version=1,
        snapshot=snapshot,
        fact_status=record.fact_status,
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action=f"store.{record_type}.created",
        record_type=record_type,
        record_id=record.id,
        actor_id=auth.user.id,
        store_id=store_id,
    )
    _complete_idempotency(
        idempotency_record, snapshot, record_type, record.id
    )
    db.commit()
    db.refresh(record)
    return read_schema.model_validate(record).model_dump(mode="json")


def _get_scoped_record(
    db: Session,
    store_id: UUID,
    record_id: UUID,
    model: type[Any],
    read_schema: type[BaseModel],
) -> dict[str, object]:
    record = db.scalar(
        select(model).where(model.id == record_id, model.store_id == store_id)
    )
    if record is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    return read_schema.model_validate(record).model_dump(mode="json")


def _list_scoped_records(
    db: Session,
    store_id: UUID,
    model: type[Any],
    read_schema: type[BaseModel],
    limit: int,
    offset: int,
) -> dict[str, object]:
    if not 1 <= limit <= 200 or offset < 0:
        raise ApiError(400, "INVALID_PAGINATION", "Invalid pagination parameters")
    total = db.scalar(
        select(func.count()).select_from(model).where(model.store_id == store_id)
    ) or 0
    records = db.scalars(
        select(model)
        .where(model.store_id == store_id)
        .order_by(model.created_at.desc(), model.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [read_schema.model_validate(record).model_dump(mode="json") for record in records],
        "total": total,
    }


def _update_scoped_record(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    store_id: UUID,
    record_id: UUID,
    if_match: str | None,
    model: type[Any],
    read_schema: type[BaseModel],
    payload: BaseModel,
    record_type: str,
) -> dict[str, object]:
    expected = _expected_version(if_match)
    record = db.scalar(
        select(model)
        .where(model.id == record_id, model.store_id == store_id)
        .with_for_update()
    )
    if record is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if record.current_version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "Record has changed")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        column = record.__table__.columns.get(field)
        if value is None and column is not None and not column.nullable:
            raise ApiError(422, "NULL_NOT_ALLOWED", f"{field} cannot be null")
        setattr(record, field, value)
    if record_type == "knowledge_item":
        if not record.content_text and not record.content_ref:
            raise ApiError(
                422, "KNOWLEDGE_CONTENT_REQUIRED",
                "content_text or content_ref is required",
            )
        if record.effective_at and record.expires_at and record.expires_at <= record.effective_at:
            raise ApiError(422, "INVALID_VALIDITY_WINDOW", "expires_at must be later")
    if record_type == "offer":
        if record.starts_at and record.ends_at and record.ends_at <= record.starts_at:
            raise ApiError(422, "INVALID_OFFER_WINDOW", "ends_at must be later")
    record.current_version += 1
    record.fact_status = "pending_confirmation"
    if hasattr(record, "updated_by_user_id"):
        record.updated_by_user_id = auth.user.id
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409, "RECORD_CONFLICT", "Record conflicts with an existing record"
        ) from exc
    snapshot = read_schema.model_validate(record).model_dump(mode="json")
    _record_revision(
        db,
        store_id=store_id,
        record_type=record_type,
        record_id=record.id,
        version=record.current_version,
        snapshot=snapshot,
        fact_status=record.fact_status,
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action=f"store.{record_type}.updated",
        record_type=record_type,
        record_id=record.id,
        actor_id=auth.user.id,
        store_id=store_id,
        metadata={"version": record.current_version},
    )
    db.commit()
    db.refresh(record)
    return read_schema.model_validate(record).model_dump(mode="json")


def _delete_scoped_record(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    store_id: UUID,
    record_id: UUID,
    if_match: str | None,
    model: type[Any],
    read_schema: type[BaseModel],
    record_type: str,
) -> None:
    expected = _expected_version(if_match)
    record = db.scalar(
        select(model)
        .where(model.id == record_id, model.store_id == store_id)
        .with_for_update()
    )
    if record is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if record.current_version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "Record has changed")
    snapshot = read_schema.model_validate(record).model_dump(mode="json")
    _record_revision(
        db,
        store_id=store_id,
        record_type=record_type,
        record_id=record.id,
        version=record.current_version + 1,
        snapshot=snapshot,
        fact_status="expired",
        actor_id=auth.user.id,
    )
    _audit(
        db,
        request,
        action=f"store.{record_type}.deleted",
        record_type=record_type,
        record_id=record.id,
        actor_id=auth.user.id,
        store_id=store_id,
    )
    db.delete(record)
    db.commit()


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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> StoreProfileRead:
    store_id = _store_id(context)
    idempotency_record, replay = _begin_idempotency(
        db, store_id, auth.user.id, idempotency_key, "store.profile.create", payload
    )
    if replay is not None:
        return StoreProfileRead.model_validate(replay)
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
    _complete_idempotency(
        idempotency_record,
        StoreProfileRead.model_validate(profile).model_dump(mode="json"),
        "store_profile",
        profile.id,
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ProductRead:
    store_id = _store_id(context)
    idempotency_record, replay = _begin_idempotency(
        db, store_id, auth.user.id, idempotency_key, "store.product.create", payload
    )
    if replay is not None:
        return ProductRead.model_validate(replay)
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
    _complete_idempotency(
        idempotency_record, result.model_dump(mode="json"), "product", product.id
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


@router.get("/offers", response_model=OfferList)
def list_offers(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
    offset: int = 0,
) -> OfferList:
    result = _list_scoped_records(
        db, _store_id(context), Offer, OfferRead, limit, offset
    )
    return OfferList.model_validate(result)


@router.post("/offers", response_model=OfferRead, status_code=status.HTTP_201_CREATED)
def create_offer(
    payload: OfferCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> OfferRead:
    result = _create_scoped_record(
        db, request, auth, _store_id(context), Offer, OfferRead, payload, "offer",
        idempotency_key, "store.offer.create",
    )
    return OfferRead.model_validate(result)


@router.get("/offers/{record_id}", response_model=OfferRead)
def get_offer(
    record_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> OfferRead:
    result = _get_scoped_record(
        db, _store_id(context), record_id, Offer, OfferRead
    )
    return OfferRead.model_validate(result)


@router.patch("/offers/{record_id}", response_model=OfferRead)
def update_offer(
    record_id: UUID,
    payload: OfferUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> OfferRead:
    result = _update_scoped_record(
        db, request, auth, _store_id(context), record_id, if_match,
        Offer, OfferRead, payload, "offer",
    )
    return OfferRead.model_validate(result)


@router.delete("/offers/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_offer(
    record_id: UUID,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Response:
    _delete_scoped_record(
        db, request, auth, _store_id(context), record_id, if_match,
        Offer, OfferRead, "offer",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audiences", response_model=AudienceProfileList)
def list_audience_profiles(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
    offset: int = 0,
) -> AudienceProfileList:
    result = _list_scoped_records(
        db, _store_id(context), AudienceProfile, AudienceProfileRead, limit, offset
    )
    return AudienceProfileList.model_validate(result)


@router.post(
    "/audiences",
    response_model=AudienceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_audience_profile(
    payload: AudienceProfileCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> AudienceProfileRead:
    result = _create_scoped_record(
        db, request, auth, _store_id(context),
        AudienceProfile, AudienceProfileRead, payload, "audience_profile",
        idempotency_key, "store.audience_profile.create",
    )
    return AudienceProfileRead.model_validate(result)


@router.get("/audiences/{record_id}", response_model=AudienceProfileRead)
def get_audience_profile(
    record_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> AudienceProfileRead:
    result = _get_scoped_record(
        db, _store_id(context), record_id, AudienceProfile, AudienceProfileRead
    )
    return AudienceProfileRead.model_validate(result)


@router.patch("/audiences/{record_id}", response_model=AudienceProfileRead)
def update_audience_profile(
    record_id: UUID,
    payload: AudienceProfileUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AudienceProfileRead:
    result = _update_scoped_record(
        db, request, auth, _store_id(context), record_id, if_match,
        AudienceProfile, AudienceProfileRead, payload, "audience_profile",
    )
    return AudienceProfileRead.model_validate(result)


@router.delete("/audiences/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_audience_profile(
    record_id: UUID,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Response:
    _delete_scoped_record(
        db, request, auth, _store_id(context), record_id, if_match,
        AudienceProfile, AudienceProfileRead, "audience_profile",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/knowledge", response_model=KnowledgeItemList)
def list_knowledge_items(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
    offset: int = 0,
) -> KnowledgeItemList:
    result = _list_scoped_records(
        db, _store_id(context), KnowledgeItem, KnowledgeItemRead, limit, offset
    )
    return KnowledgeItemList.model_validate(result)


@router.post(
    "/knowledge",
    response_model=KnowledgeItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_item(
    payload: KnowledgeItemCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> KnowledgeItemRead:
    result = _create_scoped_record(
        db, request, auth, _store_id(context),
        KnowledgeItem, KnowledgeItemRead, payload, "knowledge_item",
        idempotency_key, "store.knowledge_item.create",
    )
    return KnowledgeItemRead.model_validate(result)


@router.get("/knowledge/{record_id}", response_model=KnowledgeItemRead)
def get_knowledge_item(
    record_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> KnowledgeItemRead:
    result = _get_scoped_record(
        db, _store_id(context), record_id, KnowledgeItem, KnowledgeItemRead
    )
    return KnowledgeItemRead.model_validate(result)


@router.patch("/knowledge/{record_id}", response_model=KnowledgeItemRead)
def update_knowledge_item(
    record_id: UUID,
    payload: KnowledgeItemUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> KnowledgeItemRead:
    result = _update_scoped_record(
        db, request, auth, _store_id(context), record_id, if_match,
        KnowledgeItem, KnowledgeItemRead, payload, "knowledge_item",
    )
    return KnowledgeItemRead.model_validate(result)


@router.delete("/knowledge/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_item(
    record_id: UUID,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Response:
    _delete_scoped_record(
        db, request, auth, _store_id(context), record_id, if_match,
        KnowledgeItem, KnowledgeItemRead, "knowledge_item",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/brand-guideline", response_model=BrandGuidelineRead)
def get_brand_guideline(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> BrandGuidelineRead:
    store_id = _store_id(context)
    record = db.scalar(
        select(BrandGuideline).where(BrandGuideline.store_id == store_id)
    )
    if record is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    return BrandGuidelineRead.model_validate(record)


@router.post(
    "/brand-guideline",
    response_model=BrandGuidelineRead,
    status_code=status.HTTP_201_CREATED,
)
def create_brand_guideline(
    payload: BrandGuidelineCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> BrandGuidelineRead:
    store_id = _store_id(context)
    result = _create_scoped_record(
        db, request, auth, store_id,
        BrandGuideline, BrandGuidelineRead, payload, "brand_guideline",
        idempotency_key, "store.brand_guideline.create",
    )
    return BrandGuidelineRead.model_validate(result)


@router.patch("/brand-guideline", response_model=BrandGuidelineRead)
def update_brand_guideline(
    payload: BrandGuidelineUpdate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> BrandGuidelineRead:
    store_id = _store_id(context)
    record = db.scalar(
        select(BrandGuideline)
        .where(BrandGuideline.store_id == store_id)
        .with_for_update()
    )
    if record is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    result = _update_scoped_record(
        db, request, auth, store_id, record.id, if_match,
        BrandGuideline, BrandGuidelineRead, payload, "brand_guideline",
    )
    return BrandGuidelineRead.model_validate(result)


@router.post("/{resource_type}/{record_id}/confirm-facts")
def confirm_store_facts(
    resource_type: str,
    record_id: UUID,
    payload: FactConfirmationRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> dict[str, object]:
    resources: dict[str, tuple[type[Any], type[BaseModel], str]] = {
        "profile": (StoreProfile, StoreProfileRead, "store_profile"),
        "products": (Product, ProductRead, "product"),
        "offers": (Offer, OfferRead, "offer"),
        "audiences": (AudienceProfile, AudienceProfileRead, "audience_profile"),
        "knowledge": (KnowledgeItem, KnowledgeItemRead, "knowledge_item"),
        "brand-guideline": (BrandGuideline, BrandGuidelineRead, "brand_guideline"),
    }
    resource = resources.get(resource_type)
    if resource is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    model, read_schema, record_type = resource
    store_id = _store_id(context)
    expected = _expected_version(if_match)
    record = db.scalar(
        select(model)
        .where(model.id == record_id, model.store_id == store_id)
        .with_for_update()
    )
    if record is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if record.current_version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "Record has changed")
    if record.fact_status == "confirmed":
        raise ApiError(409, "FACT_ALREADY_CONFIRMED", "Facts are already confirmed")
    now = datetime.now(UTC)
    record.fact_status = "confirmed"
    record.current_version += 1
    if hasattr(record, "updated_by_user_id"):
        record.updated_by_user_id = auth.user.id
    db.flush()
    snapshot = read_schema.model_validate(record).model_dump(mode="json")
    _record_revision(
        db,
        store_id=store_id,
        record_type=record_type,
        record_id=record.id,
        version=record.current_version,
        snapshot=snapshot,
        fact_status="confirmed",
        actor_id=auth.user.id,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        confirmed_by_user_id=auth.user.id,
        confirmed_at=now,
        change_reason=payload.confirmation_note,
    )
    _audit(
        db,
        request,
        action=f"store.{record_type}.facts_confirmed",
        record_type=record_type,
        record_id=record.id,
        actor_id=auth.user.id,
        store_id=store_id,
        metadata={
            "version": record.current_version,
            "source_type": payload.source_type,
        },
    )
    db.commit()
    db.refresh(record)
    return read_schema.model_validate(record).model_dump(mode="json")


def _safe_filename(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (cleaned or "upload").slice(0, 255) if hasattr(cleaned, "slice") else (cleaned or "upload")[:255]


@router.post(
    "/assets/upload-intents",
    response_model=AssetUploadIntentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_asset_upload_intent(
    payload: AssetUploadIntentCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> AssetUploadIntentRead:
    store_id = _store_id(context)
    idempotency_record, replay = _begin_idempotency(
        db, store_id, auth.user.id, idempotency_key, "store.asset.upload_intent", payload
    )
    if replay is not None:
        intent_id = UUID(str(replay["id"]))
        intent = db.scalar(
            select(UploadIntent).where(
                UploadIntent.id == intent_id, UploadIntent.store_id == store_id
            )
        )
        if intent is None or intent.status != "created":
            raise ApiError(409, "UPLOAD_INTENT_NOT_AVAILABLE", "Upload intent is no longer available")
    else:
        now = datetime.now(UTC)
        object_key = f"stores/{store_id}/quarantine/{uuid4()}"
        intent = UploadIntent(
            id=uuid4(),
            store_id=store_id,
            created_by_user_id=auth.user.id,
            object_key=object_key,
            expected_mime_type=payload.expected_mime_type,
            expected_byte_size=payload.expected_byte_size,
            expected_sha256=payload.expected_sha256.lower(),
            status="created",
            expires_at=now + timedelta(minutes=15),
        )
        db.add(intent)
        db.flush()
    try:
        upload_url = create_upload_url(
            object_key=intent.object_key,
            mime_type=intent.expected_mime_type,
            sha256=intent.expected_sha256 or "",
        )
    except ObjectStorageNotConfigured as exc:
        db.rollback()
        raise ApiError(503, "OBJECT_STORAGE_UNAVAILABLE", "Private object storage is not configured") from exc
    except Exception as exc:
        db.rollback()
        raise ApiError(503, "OBJECT_STORAGE_UNAVAILABLE", "Could not create a secure upload URL") from exc
    if idempotency_record is not None:
        _complete_idempotency(
            idempotency_record,
            {"id": str(intent.id)},
            "upload_intent",
            intent.id,
        )
    _audit(
        db, request, action="store.asset.upload_intent_created",
        record_type="upload_intent", record_id=intent.id,
        actor_id=auth.user.id, store_id=store_id,
        metadata={"mime_type": intent.expected_mime_type, "byte_size": intent.expected_byte_size},
    )
    db.commit()
    return AssetUploadIntentRead(
        id=intent.id,
        upload_url=upload_url,
        required_headers={
            "Content-Type": intent.expected_mime_type,
            "x-amz-meta-sha256": intent.expected_sha256 or "",
        },
        expires_at=intent.expires_at,
    )


@router.post(
    "/assets/upload-intents/{intent_id}/complete",
    response_model=AssetUploadCompleteRead,
)
def complete_asset_upload(
    intent_id: UUID,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> AssetUploadCompleteRead:
    store_id = _store_id(context)
    intent = db.scalar(
        select(UploadIntent)
        .where(
            UploadIntent.id == intent_id,
            UploadIntent.store_id == store_id,
            UploadIntent.created_by_user_id == auth.user.id,
        )
        .with_for_update()
    )
    if intent is None:
        raise ApiError(404, "UPLOAD_INTENT_NOT_FOUND", "Upload intent not found")
    existing_asset = db.scalar(
        select(MediaAsset).where(
            MediaAsset.store_id == store_id,
            MediaAsset.object_key == intent.object_key,
        )
    )
    if existing_asset is not None:
        return AssetUploadCompleteRead(
            asset=MediaAssetRead.model_validate(existing_asset),
            status=intent.status,
        )
    if intent.status != "created":
        raise ApiError(409, "UPLOAD_INTENT_NOT_AVAILABLE", "Upload intent cannot be completed")
    now = datetime.now(UTC)
    if intent.expires_at <= now:
        intent.status = "expired"
        db.commit()
        raise ApiError(410, "UPLOAD_INTENT_EXPIRED", "Upload intent has expired")
    try:
        stored = head_object(object_key=intent.object_key)
    except ObjectStorageNotConfigured as exc:
        raise ApiError(503, "OBJECT_STORAGE_UNAVAILABLE", "Private object storage is not configured") from exc
    except Exception as exc:
        raise ApiError(409, "UPLOAD_OBJECT_NOT_FOUND", "Uploaded object could not be verified") from exc
    metadata = stored.get("Metadata") or {}
    actual_size = int(stored.get("ContentLength") or 0)
    actual_mime = str(stored.get("ContentType") or "")
    actual_sha256 = str(metadata.get("sha256") or "").lower()
    if (
        actual_size != intent.expected_byte_size
        or actual_mime != intent.expected_mime_type
        or actual_sha256 != (intent.expected_sha256 or "").lower()
    ):
        intent.status = "rejected"
        intent.rejection_reason = "Uploaded object metadata did not match the signed upload intent"
        db.commit()
        raise ApiError(422, "UPLOAD_OBJECT_MISMATCH", "Uploaded file failed server-side verification")
    asset = MediaAsset(
        id=uuid4(),
        store_id=store_id,
        object_key=intent.object_key,
        sha256=actual_sha256,
        mime_type=actual_mime,
        byte_size=actual_size,
        original_filename_sanitized=_safe_filename("upload"),
        asset_type="image",
        source_type="merchant_upload",
        usage_rights_status="unknown",
        status="quarantined",
        version_no=1,
        created_by_user_id=auth.user.id,
    )
    db.add(asset)
    intent.status = "scanning"
    intent.completed_at = now
    _audit(
        db, request, action="store.asset.upload_quarantined",
        record_type="media_asset", record_id=asset.id,
        actor_id=auth.user.id, store_id=store_id,
        metadata={"sha256": actual_sha256, "byte_size": actual_size},
    )
    db.commit()
    db.refresh(asset)
    return AssetUploadCompleteRead(
        asset=MediaAssetRead.model_validate(asset),
        status="scanning",
    )


@router.get("/assets", response_model=MediaAssetList)
def list_media_assets(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 50,
    offset: int = 0,
) -> MediaAssetList:
    store_id = _store_id(context)
    query = select(MediaAsset).where(MediaAsset.store_id == store_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    assets = db.scalars(
        query.order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
    ).all()
    return MediaAssetList(
        items=[MediaAssetRead.model_validate(item) for item in assets],
        total=total,
    )


@router.get("/assets/{asset_id}/download-url")
def get_media_asset_download_url(
    asset_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    store_id = _store_id(context)
    asset = db.scalar(
        select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.store_id == store_id,
        )
    )
    if asset is None:
        raise ApiError(404, "MEDIA_ASSET_NOT_FOUND", "Media asset not found")
    if asset.status != "ready" or asset.usage_rights_status != "confirmed_allowed":
        raise ApiError(409, "MEDIA_ASSET_NOT_READY", "Only scanned, rights-confirmed assets can be downloaded")
    try:
        url = create_download_url(object_key=asset.object_key)
    except ObjectStorageNotConfigured as exc:
        raise ApiError(503, "OBJECT_STORAGE_UNAVAILABLE", "Private object storage is not configured") from exc
    return {"url": url}
