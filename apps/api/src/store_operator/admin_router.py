from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import BaseModel, Field, SecretStr, model_validator
from redis.exceptions import RedisError
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.dependencies import (
    ADMIN_SESSION_COOKIE_NAME,
    AuthenticatedSession,
    get_admin_session,
    require_admin_csrf,
    require_admin_platform_admin,
    require_platform_admin,
    require_platform_admin_csrf,
    validate_browser_origin,
)
from store_operator.auth.errors import ApiError
from store_operator.auth.router import (
    _clear_session_cookie,
    _consume_login_attempt,
    _login_rate_limit_keys,
    _set_session_cookie,
    issue_session,
)
from store_operator.auth.schemas import (
    LoginRequest,
    LoginResponse,
    MemberPatchRequest,
    MemberSummary,
    SessionSummary,
    UserSummary,
)
from store_operator.auth.security import (
    csrf_token_verifier,
    dummy_password_hash,
    fingerprint,
    hash_password,
    normalize_email,
    random_token,
    verify_password,
)
from store_operator.config import settings
from store_operator.db import get_db, redis_client
from store_operator.jobs.service import JobIdempotencyConflict, create_job
from store_operator.models.channel_delivery import PublishOperation
from store_operator.models.channel_spec import ChannelSpec, ChannelSpecVersion
from store_operator.models.content_delivery import PublishPackageItem
from store_operator.models.identity import (
    AuthSession,
    PlatformAdminGrant,
    Store,
    StoreMembership,
    User,
)
from store_operator.models.job_runtime import Job, OutboxEvent
from store_operator.models.marketing_task import MarketingTask
from store_operator.models.opportunity_effects import (
    HotTopic,
    HotTopicSource,
    StoreOpportunity,
)

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
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    official_hosts = {
        "douyin": {"open.douyin.com"},
    }
    source = urlsplit(payload.source_document_ref)
    allowed_hosts = official_hosts.get(channel_key)
    if (
        source.scheme != "https"
        or source.hostname is None
        or allowed_hosts is None
        or source.hostname.lower() not in allowed_hosts
        or source.username is not None
        or source.password is not None
    ):
        raise ApiError(
            422,
            "CHANNEL_SPEC_SOURCE_REQUIRED",
            "A verified official HTTPS source for this channel is required",
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
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
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



STORES = ("active", "suspended", "closed")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ApiError(422, "INVALID_TIMEZONE", "A valid IANA time zone is required") from exc
    return value


def _store_member_rows(
    db: Session, store_ids: list[UUID]
) -> dict[UUID, list[tuple[StoreMembership, User]]]:
    if not store_ids:
        return {}
    rows = db.execute(
        select(StoreMembership, User)
        .join(User, User.id == StoreMembership.user_id)
        .where(
            StoreMembership.store_id.in_(store_ids),
            StoreMembership.status != "removed",
        )
        .order_by(User.email_normalized)
    ).all()
    grouped: dict[UUID, list[tuple[StoreMembership, User]]] = {}
    for membership, user in rows:
        grouped.setdefault(membership.store_id, []).append((membership, user))
    return grouped


@router.post("/auth/login", response_model=LoginResponse)
def admin_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    validate_browser_origin(request)
    email = normalize_email(payload.email)
    rate_keys = _login_rate_limit_keys(request, email)
    try:
        _consume_login_attempt(rate_keys)
    except RedisError as exc:
        raise ApiError(
            503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
        ) from exc

    try:
        user = db.scalar(select(User).where(User.email_normalized == email))
        candidate_hash = user.password_hash if user is not None else dummy_password_hash()
        valid_password = verify_password(
            candidate_hash, payload.password.get_secret_value()
        )
        if user is None or not valid_password or user.status != "active":
            record_audit(
                db,
                request,
                action="auth.login",
                target_type="user",
                target_id=user.id if user is not None else fingerprint(
                    email, settings.session_token_pepper
                ),
                actor_user_id=user.id if user is not None else None,
                result="denied",
                metadata={"portal": "admin", "reason": "invalid_credentials"},
            )
            db.commit()
            raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password")

        grant = db.scalar(
            select(PlatformAdminGrant).where(
                PlatformAdminGrant.user_id == user.id,
                PlatformAdminGrant.status == "active",
            )
        )
        if grant is None:
            record_audit(
                db,
                request,
                action="platform_admin.access",
                target_type="capability",
                target_id="platform.store_members.manage",
                actor_user_id=user.id,
                result="denied",
                metadata={"portal": "admin", "reason": "grant_missing"},
            )
            db.commit()
            raise ApiError(
                403,
                "PLATFORM_ADMIN_REQUIRED",
                "This account is not a platform administrator",
            )

        try:
            redis_client.delete(rate_keys[1])
        except RedisError as exc:
            raise ApiError(
                503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
            ) from exc
        auth_session, raw_token, csrf_token, expires_at = issue_session(
            db, request, user
        )
        record_audit(
            db,
            request,
            action="auth.login",
            target_type="user",
            target_id=user.id,
            actor_user_id=user.id,
            metadata={"session_id": str(auth_session.id), "portal": "admin"},
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise ApiError(
            503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
        ) from exc

    _set_session_cookie(response, raw_token, ADMIN_SESSION_COOKIE_NAME)
    return LoginResponse(
        user=UserSummary(id=user.id, email=user.email_normalized),
        session=SessionSummary(expires_at=expires_at),
        csrf_token=csrf_token,
    )


@router.post("/auth/csrf")
def admin_refresh_csrf(
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(get_admin_session)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    validate_browser_origin(request)
    token = random_token()
    auth.session.csrf_token_hash = csrf_token_verifier(token)
    db.commit()
    return {"csrf_token": token}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def admin_logout(
    request: Request,
    response: Response,
    auth: Annotated[AuthenticatedSession, Depends(require_admin_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    auth.session.revoked_at = datetime.now(UTC)
    auth.session.revoke_reason = "logout"
    record_audit(
        db,
        request,
        action="auth.logout",
        target_type="session",
        target_id=auth.session.id,
        actor_user_id=auth.user.id,
        metadata={"portal": "admin"},
    )
    db.commit()
    _clear_session_cookie(response, ADMIN_SESSION_COOKIE_NAME)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me")
def admin_identity(
    auth: Annotated[AuthenticatedSession, Depends(require_admin_platform_admin)],
) -> dict[str, object]:
    return {
        "user": {"id": str(auth.user.id), "email": auth.user.email_normalized},
        "capabilities": ["platform.store_members.manage"],
    }


@router.get("/overview")
def platform_overview(
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    now = datetime.now(UTC)
    day_ago = now - timedelta(days=1)

    store_counts = {item: 0 for item in STORES}
    for item, count in db.execute(
        select(Store.status, func.count()).group_by(Store.status)
    ).all():
        store_counts[str(item)] = int(count)

    active_members = db.scalar(
        select(func.count())
        .select_from(StoreMembership)
        .where(StoreMembership.status == "active")
    ) or 0
    task_counts: dict[str, int] = {}
    for item, count in db.execute(
        select(MarketingTask.lifecycle_status, func.count()).group_by(
            MarketingTask.lifecycle_status
        )
    ).all():
        task_counts[str(item)] = int(count)
    job_counts: dict[str, int] = {}
    for item, count in db.execute(
        select(Job.status, func.count()).group_by(Job.status)
    ).all():
        job_counts[str(item)] = int(count)
    failed_jobs_24h = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status.in_(("failed", "needs_human")), Job.updated_at >= day_ago)
    ) or 0
    opportunities_24h = db.scalar(
        select(func.count())
        .select_from(StoreOpportunity)
        .where(StoreOpportunity.matched_at >= day_ago)
    ) or 0
    hot_topics = db.scalar(
        select(func.count())
        .select_from(HotTopic)
        .where(HotTopic.evidence_status == "collected")
    ) or 0
    dispatch_counts: dict[str, int] = {}
    for item, count in db.execute(
        select(PublishOperation.status, func.count()).group_by(PublishOperation.status)
    ).all():
        dispatch_counts[str(item)] = int(count)

    return {
        "stores": {
            "total": sum(store_counts.values()),
            "by_status": store_counts,
        },
        "store_users": {"active": int(active_members)},
        "marketing_tasks": {"by_status": task_counts},
        "jobs": {
            "running": job_counts.get("running", 0),
            "queued": job_counts.get("queued", 0),
            "failed_or_needs_human_24h": int(failed_jobs_24h),
        },
        "hot_topics": {"collected": int(hot_topics), "matches_24h": int(opportunities_24h)},
        "dispatches": {"by_status": dispatch_counts},
    }


class StoreCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    timezone: str = Field(min_length=1, max_length=64)
    status: Literal["active", "suspended"] = "active"


class StorePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["active", "suspended", "closed"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "StorePatchRequest":
        if self.name is None and self.timezone is None and self.status is None:
            raise ValueError("At least one field must be provided")
        return self


def _store_payload(
    store: Store, members: list[tuple[StoreMembership, User]]
) -> dict[str, object]:
    return {
        "id": str(store.id),
        "name": store.name,
        "timezone": store.timezone,
        "status": store.status,
        "created_at": _iso(store.created_at),
        "updated_at": _iso(store.updated_at),
        "member_count": len(members),
        "owners": [
            user.email_normalized
            for membership, user in members
            if membership.role == "owner" and membership.status == "active"
        ],
    }


@router.get("/stores")
def list_stores(
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    query: str | None = None,
    store_status: Literal["active", "suspended", "closed"] | None = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = []
    if query:
        conditions.append(Store.name.ilike(f"%{query.strip()[:120]}%"))
    if store_status:
        conditions.append(Store.status == store_status)
    total = db.scalar(
        select(func.count()).select_from(Store).where(*conditions)
    ) or 0
    stores = db.scalars(
        select(Store)
        .where(*conditions)
        .order_by(Store.created_at.desc(), Store.id)
        .limit(limit)
        .offset(offset)
    ).all()
    grouped = _store_member_rows(db, [store.id for store in stores])
    return {
        "items": [_store_payload(store, grouped.get(store.id, [])) for store in stores],
        "total": int(total),
    }


@router.post("/stores", status_code=status.HTTP_201_CREATED)
def create_store(
    payload: StoreCreateRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    name = payload.name.strip()
    if not name:
        raise ApiError(422, "VALIDATION_ERROR", "Store name is required")
    store = Store(
        id=uuid4(),
        name=name,
        timezone=_validate_timezone(payload.timezone.strip()),
        status=payload.status,
    )
    db.add(store)
    db.flush()
    record_audit(
        db,
        request,
        action="store.created",
        target_type="store",
        target_id=store.id,
        actor_user_id=auth.user.id,
        store_id=store.id,
        actor_type="platform_admin",
        metadata={"status": store.status, "timezone": store.timezone},
    )
    db.commit()
    return _store_payload(store, [])


@router.patch("/stores/{store_id}")
def update_store(
    store_id: UUID,
    payload: StorePatchRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store = db.scalar(select(Store).where(Store.id == store_id).with_for_update())
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found")
    changed: dict[str, object] = {}
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise ApiError(422, "VALIDATION_ERROR", "Store name is required")
        store.name = name
        changed["name"] = name
    if payload.timezone is not None:
        store.timezone = _validate_timezone(payload.timezone.strip())
        changed["timezone"] = store.timezone
    if payload.status is not None:
        store.status = payload.status
        changed["status"] = store.status
    record_audit(
        db,
        request,
        action="store.updated",
        target_type="store",
        target_id=store.id,
        actor_user_id=auth.user.id,
        store_id=store.id,
        actor_type="platform_admin",
        metadata=changed,
    )
    db.commit()
    members = _store_member_rows(db, [store.id]).get(store.id, [])
    return _store_payload(store, members)


class StoreUserCreateRequest(BaseModel):
    store_id: UUID
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=12, max_length=128)
    role: Literal["owner", "member"] = "owner"


class StoreUserPasswordResetRequest(BaseModel):
    password: SecretStr = Field(min_length=12, max_length=128)


def _store_user_payload(
    membership: StoreMembership, user: User, store: Store
) -> dict[str, object]:
    return {
        "membership_id": str(membership.id),
        "user_id": str(user.id),
        "email": user.email_normalized,
        "role": membership.role,
        "status": membership.status,
        "created_at": _iso(membership.created_at),
        "joined_at": _iso(membership.joined_at),
        "store": {
            "id": str(store.id),
            "name": store.name,
            "status": store.status,
        },
    }


@router.get("/store-users")
def list_store_users(
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    store_id: UUID | None = None,
    query: str | None = None,
    user_status: Literal["invited", "active", "suspended", "removed"] | None = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = []
    if store_id is not None:
        conditions.append(StoreMembership.store_id == store_id)
    if query:
        conditions.append(User.email_normalized.ilike(f"%{query.strip()[:120]}%"))
    if user_status is not None:
        conditions.append(StoreMembership.status == user_status)
    base = (
        select(StoreMembership, User, Store)
        .join(User, User.id == StoreMembership.user_id)
        .join(Store, Store.id == StoreMembership.store_id)
        .where(*conditions)
    )
    total = db.scalar(
        select(func.count())
        .select_from(StoreMembership)
        .join(User, User.id == StoreMembership.user_id)
        .where(*conditions)
    ) or 0
    rows = db.execute(
        base.order_by(User.email_normalized, Store.name).limit(limit).offset(offset)
    ).all()
    return {
        "items": [
            _store_user_payload(membership, user, store)
            for membership, user, store in rows
        ],
        "total": int(total),
    }


@router.post("/store-users", status_code=status.HTTP_201_CREATED)
def create_store_user(
    payload: StoreUserCreateRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store = db.scalar(
        select(Store).where(Store.id == payload.store_id).with_for_update()
    )
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found")
    if store.status != "active":
        raise ApiError(
            409, "STORE_NOT_ACTIVE", "A store user can only be created for an active store"
        )
    email = normalize_email(payload.email)
    if not email or "@" not in email:
        raise ApiError(422, "VALIDATION_ERROR", "A valid email address is required")
    existing = db.scalar(select(User).where(User.email_normalized == email))
    if existing is not None:
        bound = db.scalar(
            select(StoreMembership).where(
                StoreMembership.user_id == existing.id,
                StoreMembership.status != "removed",
            )
        )
        if bound is not None and bound.store_id != store.id:
            raise ApiError(
                409,
                "STORE_USER_ALREADY_BOUND",
                "This account already belongs to another store",
            )
        raise ApiError(409, "EMAIL_ALREADY_EXISTS", "This email is already in use")

    user = User(
        id=uuid4(),
        email_normalized=email,
        password_hash=hash_password(payload.password.get_secret_value()),
        status="active",
    )
    db.add(user)
    db.flush()
    membership = StoreMembership(
        id=uuid4(),
        store_id=store.id,
        user_id=user.id,
        role=payload.role,
        status="active",
        invited_by_user_id=auth.user.id,
        joined_at=datetime.now(UTC),
    )
    db.add(membership)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "EMAIL_ALREADY_EXISTS", "This email is already in use") from exc
    record_audit(
        db,
        request,
        action="store.membership.created",
        target_type="store_membership",
        target_id=membership.id,
        actor_user_id=auth.user.id,
        store_id=store.id,
        actor_type="platform_admin",
        metadata={"role": membership.role},
    )
    db.commit()
    return _store_user_payload(membership, user, store)


@router.post(
    "/stores/{store_id}/members/{membership_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reset_store_user_password(
    store_id: UUID,
    membership_id: UUID,
    payload: StoreUserPasswordResetRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
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
    user = db.scalar(select(User).where(User.id == membership.user_id).with_for_update())
    if user is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    now = datetime.now(UTC)
    user.password_hash = hash_password(payload.password.get_secret_value())
    user.password_changed_at = now
    user.auth_version += 1
    sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    for item in sessions:
        item.revoked_at = now
        item.revoke_reason = "platform_admin_reset"
    record_audit(
        db,
        request,
        action="store.membership.password_reset",
        target_type="store_membership",
        target_id=membership.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        actor_type="platform_admin",
        metadata={"revoked_session_count": len(sessions)},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class OpportunityCollectRequest(BaseModel):
    store_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=200)


@router.get("/hot-topics")
def list_hot_topics(
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    query: str | None = None,
    evidence_status: Literal[
        "collected", "partial", "failed", "unverified", "expired"
    ] | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = []
    if query:
        conditions.append(HotTopic.title.ilike(f"%{query.strip()[:120]}%"))
    if evidence_status:
        conditions.append(HotTopic.evidence_status == evidence_status)
    total = db.scalar(
        select(func.count()).select_from(HotTopic).where(*conditions)
    ) or 0
    rows = db.execute(
        select(HotTopic, HotTopicSource)
        .join(HotTopicSource, HotTopicSource.id == HotTopic.source_id)
        .where(*conditions)
        .order_by(HotTopic.discovered_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [
            {
                "id": str(topic.id),
                "title": topic.title,
                "summary": topic.summary,
                "canonical_url": topic.canonical_url,
                "region": topic.region,
                "industry_tags": topic.industry_tags_json,
                "topic_tags": topic.topic_tags_json,
                "heat_value": (
                    str(topic.heat_value) if topic.heat_value is not None else None
                ),
                "heat_unit": topic.heat_unit,
                "evidence_status": topic.evidence_status,
                "published_at": _iso(topic.published_at),
                "discovered_at": _iso(topic.discovered_at),
                "expires_at": _iso(topic.expires_at),
                "source": {
                    "id": str(source.id),
                    "source_key": source.source_key,
                    "display_name": source.display_name,
                    "enabled": source.enabled,
                },
            }
            for topic, source in rows
        ],
        "total": int(total),
        "page": offset // limit + 1,
        "page_size": limit,
        "total_pages": (int(total) + limit - 1) // limit,
    }


@router.get("/opportunities")
def list_opportunity_matches(
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    store_id: UUID | None = None,
    query: str | None = None,
    eligibility: Literal[
        "eligible", "review_required", "ineligible", "unassessed"
    ] | None = None,
    match_source: Literal["rules", "ai_creative"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = []
    if store_id is not None:
        conditions.append(StoreOpportunity.store_id == store_id)
    if query:
        conditions.append(HotTopic.title.ilike(f"%{query.strip()[:120]}%"))
    if eligibility:
        conditions.append(StoreOpportunity.eligibility_status == eligibility)
    source_rows = db.execute(
        select(StoreOpportunity.match_source, func.count())
        .select_from(StoreOpportunity)
        .join(HotTopic, HotTopic.id == StoreOpportunity.hot_topic_id)
        .where(*conditions, StoreOpportunity.stale_at.is_(None))
        .group_by(StoreOpportunity.match_source)
    ).all()
    source_counts: dict[str, int] = {
        str(row[0]): int(row[1]) for row in source_rows
    }
    if match_source:
        conditions.append(StoreOpportunity.match_source == match_source)
    total = db.scalar(
        select(func.count())
        .select_from(StoreOpportunity)
        .join(HotTopic, HotTopic.id == StoreOpportunity.hot_topic_id)
        .where(*conditions)
    ) or 0
    rows = db.execute(
        select(StoreOpportunity, HotTopic, Store)
        .join(HotTopic, HotTopic.id == StoreOpportunity.hot_topic_id)
        .join(Store, Store.id == StoreOpportunity.store_id)
        .where(*conditions)
        .order_by(StoreOpportunity.matched_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [
            {
                "id": str(opportunity.id),
                "store": {
                    "id": str(store.id),
                    "name": store.name,
                    "status": store.status,
                },
                "title": topic.title,
                "canonical_url": topic.canonical_url,
                "relevance_score": (
                    str(opportunity.relevance_score)
                    if opportunity.relevance_score is not None
                    else None
                ),
                "match_method": opportunity.match_method,
                "matching_algorithm_version": opportunity.matching_algorithm_version,
                "match_source": opportunity.match_source,
                "ai_creative": opportunity.ai_creative_json,
                "ai_confidence": (
                    str(opportunity.ai_confidence)
                    if opportunity.ai_confidence is not None
                    else None
                ),
                "ai_prompt_version": opportunity.ai_prompt_version,
                "eligibility_status": opportunity.eligibility_status,
                "reason_summary": opportunity.reason_summary,
                "suggested_scenario": opportunity.suggested_scenario,
                "content_angle": opportunity.content_angle,
                "risk_flags": opportunity.risk_flags_json,
                "matched_at": _iso(opportunity.matched_at),
                "expires_at": _iso(opportunity.expires_at),
                "stale_at": _iso(opportunity.stale_at),
                "hot_topic": {
                    "id": str(topic.id),
                    "evidence_status": topic.evidence_status,
                    "published_at": _iso(topic.published_at),
                },
            }
            for opportunity, topic, store in rows
        ],
        "total": int(total),
        "source_counts": {
            "rules": int(source_counts.get("rules", 0)),
            "ai_creative": int(source_counts.get("ai_creative", 0)),
        },
    }


@router.post("/opportunities/collect", status_code=status.HTTP_202_ACCEPTED)
def collect_opportunities(
    payload: OpportunityCollectRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    sources = db.scalars(
        select(HotTopicSource).where(
            HotTopicSource.enabled.is_(True),
            HotTopicSource.source_type.in_(("rss", "public_feed")),
            HotTopicSource.terms_url.is_not(None),
            HotTopicSource.permitted_use.is_not(None),
        )
    ).all()
    if not sources:
        return {
            "status": "unavailable",
            "items": [],
            "message": "没有已启用且完成使用条款登记的热点来源；未创建采集任务。",
        }
    store_conditions = [Store.status == "active"]
    if payload.store_ids:
        store_conditions.append(Store.id.in_(payload.store_ids))
    stores = db.scalars(
        select(Store).where(*store_conditions).order_by(Store.created_at)
    ).all()
    if not stores:
        return {"status": "unavailable", "items": [], "message": "没有可执行采集的活跃门店。"}

    created: list[dict[str, object]] = []
    for store in stores:
        try:
            job = create_job(
                db,
                job_type="hot_topics.collect_and_match.v1",
                payload_ref={
                    "schema_version": 1,
                    "source_ids": sorted(str(item.id) for item in sources),
                },
                idempotency_key=idempotency_key,
                store_id=store.id,
                actor_type="platform_admin",
                actor_user_id=auth.user.id,
                queue_name="default",
                priority=0,
                max_attempts=3,
                timeout_seconds=300,
            )
        except JobIdempotencyConflict as exc:
            raise ApiError(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                "Collection key was used for a different request",
            ) from exc
        created.append(
            {
                "store_id": str(store.id),
                "store_name": store.name,
                "job_id": str(job.id),
                "status": job.status,
            }
        )
    record_audit(
        db,
        request,
        action="opportunity.collection.requested",
        target_type="job",
        target_id=str(created[0]["job_id"]),
        actor_user_id=auth.user.id,
        actor_type="platform_admin",
        metadata={
            "store_count": len(created),
            "source_count": len(sources),
        },
    )
    db.commit()
    return {
        "status": created[0]["status"] if len(created) == 1 else "queued",
        "items": created,
        "source_count": len(sources),
    }


@router.get("/jobs/{job_id}")
def get_job_status(
    job_id: UUID,
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    job = db.get(Job, job_id)
    if job is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Job not found")
    store_name = (
        db.scalar(select(Store.name).where(Store.id == job.store_id))
        if job.store_id
        else None
    )
    result = job.result_ref or {}
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "store_id": str(job.store_id) if job.store_id else None,
        "store_name": store_name,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "error_code": job.error_code,
        "error_summary": job.error_summary,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "topics_inserted": result.get("topics_inserted"),
        "opportunities_created": result.get("opportunities_created"),
        "source_results": result.get("source_results") or [],
        "source_failures": result.get("source_failures") or [],
        "match": result.get("match") or {},
    }


@router.get("/dispatches")
def list_dispatches(
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    store_id: UUID | None = None,
    dispatch_status: Literal[
        "queued",
        "uploading",
        "submitting",
        "processing",
        "published",
        "failed",
        "needs_human",
        "cancelled",
    ] | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    conditions: list[ColumnElement[bool]] = []
    if store_id is not None:
        conditions.append(PublishOperation.store_id == store_id)
    if dispatch_status is not None:
        conditions.append(PublishOperation.status == dispatch_status)
    total = db.scalar(
        select(func.count()).select_from(PublishOperation).where(*conditions)
    ) or 0
    rows = db.execute(
        select(PublishOperation, Store, PublishPackageItem.channel_key)
        .join(Store, Store.id == PublishOperation.store_id)
        .outerjoin(
            PublishPackageItem,
            and_(
                PublishPackageItem.store_id == PublishOperation.store_id,
                PublishPackageItem.id == PublishOperation.publish_package_item_id,
            ),
        )
        .where(*conditions)
        .order_by(PublishOperation.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [
            {
                "id": str(operation.id),
                "store": {"id": str(store.id), "name": store.name},
                "channel_key": channel_key,
                "status": operation.status,
                "attempt_count": operation.attempt_count,
                "platform_item_id": operation.platform_item_id,
                "last_error_code": operation.last_error_code,
                "last_error_summary": operation.last_error_summary,
                "created_at": _iso(operation.created_at),
                "updated_at": _iso(operation.updated_at),
                "submitted_at": _iso(operation.submitted_at),
                "published_at": _iso(operation.published_at),
                "last_readback_at": _iso(operation.last_readback_at),
            }
            for operation, store, channel_key in rows
        ],
        "total": int(total),
    }


@router.post("/outbox-events/{event_id}/requeue")
def requeue_dead_outbox_event(
    event_id: UUID,
    payload: OutboxRequeueRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_platform_admin_csrf)],
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
