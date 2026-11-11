from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    get_current_session,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.channels.douyin import DouyinApiError, DouyinAppCredentials, DouyinOAuthClient
from store_operator.channels.oauth_state import consume_oauth_state, new_oauth_state
from store_operator.channels.secret_store import AwsSecretsManagerStore, SecretStoreError
from store_operator.config import settings
from store_operator.db import get_db
from store_operator.jobs.service import JobIdempotencyConflict, create_job
from store_operator.models.channel_delivery import (
    ChannelAccount,
    OAuthAuthorizationAttempt,
    PublishOperation,
)
from store_operator.models.content_delivery import (
    PublishConfirmation,
    PublishPackage,
    PublishPackageItem,
)
from store_operator.models.job_runtime import Job
from store_operator.models.identity import Store, StoreMembership

router = APIRouter(prefix="/channels/douyin", tags=["channel-accounts"])

DOUYIN_REQUIRED_SCOPES = frozenset({"user_info", "video.create", "video.list"})


def _require_oauth_configuration() -> tuple[DouyinAppCredentials, str]:
    if not (
        settings.douyin_client_key
        and settings.douyin_client_secret
        and settings.douyin_redirect_uri
    ):
        raise ApiError(503, "CHANNEL_NOT_CONFIGURED", "Douyin channel is not configured")
    return (
        DouyinAppCredentials(
            client_key=settings.douyin_client_key,
            client_secret=settings.douyin_client_secret,
        ),
        settings.douyin_redirect_uri,
    )


def _secret_store() -> AwsSecretsManagerStore:
    if not settings.channel_secret_store_region:
        raise ApiError(
            503, "SECRET_STORE_UNAVAILABLE", "Channel credential storage is not configured"
        )
    return AwsSecretsManagerStore(region_name=settings.channel_secret_store_region)


@router.post("/oauth/authorize")
async def begin_douyin_authorization(
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    credentials, redirect_uri = _require_oauth_configuration()
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")

    raw_state, state_hash = new_oauth_state()
    now = datetime.now(UTC)
    attempt = OAuthAuthorizationAttempt(
        id=uuid4(),
        provider="douyin",
        store_id=context.request_store_id,
        user_id=auth.user.id,
        session_id=auth.session.id,
        state_hash=state_hash,
        redirect_uri=redirect_uri,
        requested_scopes=sorted(DOUYIN_REQUIRED_SCOPES),
        expires_at=now + timedelta(minutes=10),
    )
    db.add(attempt)
    db.commit()

    client = DouyinOAuthClient(credentials)
    try:
        authorization_url = client.build_authorization_url(
            redirect_uri=redirect_uri,
            state=raw_state,
            scopes=DOUYIN_REQUIRED_SCOPES,
        )
    finally:
        await client.aclose()
    return {"authorization_url": authorization_url, "expires_in": "600"}


@router.get("/oauth/callback")
async def complete_douyin_authorization(
    auth: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
    code: Annotated[str, Query(min_length=1, max_length=2048)],
    state: Annotated[str, Query(min_length=32, max_length=256)],
) -> dict[str, str]:
    credentials, redirect_uri = _require_oauth_configuration()
    state_hash = hashlib.sha256(state.encode("utf-8")).digest()
    attempt = db.scalar(
        select(OAuthAuthorizationAttempt).where(
            OAuthAuthorizationAttempt.state_hash == state_hash,
            OAuthAuthorizationAttempt.provider == "douyin",
            OAuthAuthorizationAttempt.user_id == auth.user.id,
            OAuthAuthorizationAttempt.session_id == auth.session.id,
            OAuthAuthorizationAttempt.consumed_at.is_(None),
            OAuthAuthorizationAttempt.expires_at > datetime.now(UTC),
        )
    )
    if attempt is None:
        raise ApiError(400, "OAUTH_STATE_INVALID", "OAuth authorization state is invalid or expired")  # noqa: E501
    if attempt.redirect_uri != redirect_uri:
        raise ApiError(400, "OAUTH_REDIRECT_MISMATCH", "OAuth redirect URI does not match")
    store = db.scalar(
        select(Store).where(Store.id == attempt.store_id, Store.status == "active")
    )
    membership = db.scalar(
        select(StoreMembership).where(
            StoreMembership.store_id == attempt.store_id,
            StoreMembership.user_id == auth.user.id,
            StoreMembership.status == "active",
        )
    )
    if store is None or membership is None:
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found")

    consumed = consume_oauth_state(
        db,
        raw_state=state,
        provider="douyin",
        user_id=auth.user.id,
        store_id=attempt.store_id,
        session_id=auth.session.id,
    )
    if consumed is None:
        db.rollback()
        raise ApiError(400, "OAUTH_STATE_INVALID", "OAuth authorization state is invalid or expired")  # noqa: E501
    db.commit()

    client = DouyinOAuthClient(credentials)
    try:
        token_set = await client.exchange_code(code)
        profile = await client.get_account_profile(token_set.access_token)
    finally:
        await client.aclose()

    if profile["open_id"] != token_set.open_id:
        raise ApiError(502, "OAUTH_ACCOUNT_MISMATCH", "Douyin account identity could not be verified")  # noqa: E501
    if not DOUYIN_REQUIRED_SCOPES.issubset(token_set.scope):
        raise ApiError(
            403,
            "OAUTH_SCOPE_INSUFFICIENT",
            "Douyin authorization did not grant all required publishing and readback scopes",
        )

    try:
        secret_store = _secret_store()
        external_id_digest = hashlib.sha256(token_set.open_id.encode("utf-8")).hexdigest()
        secret_ref = secret_store.put_json(
            f"{settings.channel_secret_store_prefix}/{attempt.store_id}/douyin/{external_id_digest}",  # noqa: E501
            {
                "access_token": token_set.access_token,
                "refresh_token": token_set.refresh_token,
            },
        )
    except SecretStoreError as exc:
        raise ApiError(
            503, "SECRET_STORE_UNAVAILABLE", "Channel credentials could not be stored securely"
        ) from exc

    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.store_id == attempt.store_id,
            ChannelAccount.provider == "douyin",
            ChannelAccount.external_account_id == token_set.open_id,
        )
    )
    now = datetime.now(UTC)
    if account is None:
        account = ChannelAccount(
            id=uuid4(),
            store_id=attempt.store_id,
            provider="douyin",
            external_account_id=token_set.open_id,
            connected_by_user_id=auth.user.id,
            access_token_secret_ref=secret_ref,
            refresh_token_secret_ref=secret_ref,
            access_token_expires_at=now + timedelta(seconds=token_set.expires_in),
            refresh_token_expires_at=(
                now + timedelta(seconds=token_set.refresh_expires_in)
                if token_set.refresh_expires_in > 0
                else None
            ),
            granted_scopes=sorted(token_set.scope),
            display_name=profile.get("nickname"),
            avatar_url=profile.get("avatar"),
            status="active",
            last_verified_at=now,
        )
        db.add(account)
    else:
        account.access_token_secret_ref = secret_ref
        account.refresh_token_secret_ref = secret_ref
        account.access_token_expires_at = now + timedelta(seconds=token_set.expires_in)
        account.refresh_token_expires_at = (
            now + timedelta(seconds=token_set.refresh_expires_in)
            if token_set.refresh_expires_in > 0
            else None
        )
        account.granted_scopes = sorted(token_set.scope)
        account.display_name = profile.get("nickname")
        account.avatar_url = profile.get("avatar")
        account.status = "active"
        account.revoked_at = None
        account.last_verified_at = now
    db.commit()
    return {
        "status": "connected",
        "channel_account_id": str(account.id),
        "store_id": str(attempt.store_id),
        "external_account_id": token_set.open_id,
    }


@router.get("/accounts")
def list_douyin_accounts(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    accounts = db.scalars(
        select(ChannelAccount)
        .where(
            ChannelAccount.store_id == store_id,
            ChannelAccount.provider == "douyin",
        )
        .order_by(ChannelAccount.connected_at.desc())
    ).all()
    return [
        {
            "id": str(account.id),
            "provider": account.provider,
            "external_account_id": account.external_account_id,
            "display_name": account.display_name,
            "avatar_url": account.avatar_url,
            "granted_scopes": account.granted_scopes,
            "access_token_expires_at": account.access_token_expires_at.isoformat(),
            "refresh_token_expires_at": (
                account.refresh_token_expires_at.isoformat()
                if account.refresh_token_expires_at
                else None
            ),
            "status": account.status,
            "connected_at": account.connected_at.isoformat(),
            "last_verified_at": (
                account.last_verified_at.isoformat() if account.last_verified_at else None
            ),
        }
        for account in accounts
    ]


@router.post("/accounts/{account_id}/refresh")
async def refresh_douyin_account_token(
    account_id: UUID,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    credentials, _ = _require_oauth_configuration()
    account = db.scalar(
        select(ChannelAccount)
        .where(
            ChannelAccount.id == account_id,
            ChannelAccount.store_id == store_id,
            ChannelAccount.provider == "douyin",
            ChannelAccount.status == "active",
        )
    )
    if account is None:
        raise ApiError(404, "CHANNEL_ACCOUNT_NOT_FOUND", "Active Douyin account not found")
    secret_ref = account.access_token_secret_ref
    expected_open_id = account.external_account_id
    db.commit()

    try:
        secret_store = _secret_store()
        secrets = secret_store.get_json(secret_ref)
        refresh_token = secrets.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise SecretStoreError("Stored refresh credential is invalid")
        client = DouyinOAuthClient(credentials)
        try:
            token_set = await client.refresh_access_token(refresh_token)
        finally:
            await client.aclose()
        if token_set.open_id != expected_open_id:
            raise ApiError(
                502,
                "OAUTH_ACCOUNT_MISMATCH",
                "Refreshed credentials do not match the connected Douyin account",
            )
        required_scopes = DOUYIN_REQUIRED_SCOPES
        if not required_scopes.issubset(token_set.scope):
            raise ApiError(
                403,
                "OAUTH_SCOPE_INSUFFICIENT",
                "Refreshed credentials lack required publishing or readback scopes",
            )
        new_secret_ref = secret_store.put_json(
            f"{settings.channel_secret_store_prefix}/{store_id}/douyin/"
            f"{hashlib.sha256(expected_open_id.encode('utf-8')).hexdigest()}",
            {
                "access_token": token_set.access_token,
                "refresh_token": token_set.refresh_token,
            },
        )
    except SecretStoreError as exc:
        raise ApiError(
            503, "SECRET_STORE_UNAVAILABLE", "Channel credentials could not be refreshed"
        ) from exc
    except DouyinApiError as exc:
        raise ApiError(
            502, "CHANNEL_TOKEN_REFRESH_FAILED", "Douyin token refresh failed"
        ) from exc

    current = db.scalar(
        select(ChannelAccount)
        .where(
            ChannelAccount.id == account_id,
            ChannelAccount.store_id == store_id,
        )
        .with_for_update()
    )
    if (
        current is None
        or current.status != "active"
        or current.access_token_secret_ref != secret_ref
    ):
        db.rollback()
        raise ApiError(
            409,
            "CHANNEL_ACCOUNT_CHANGED",
            "Channel account changed while credentials were refreshing; retry",
        )
    now = datetime.now(UTC)
    current.access_token_secret_ref = new_secret_ref
    current.refresh_token_secret_ref = new_secret_ref
    current.access_token_expires_at = now + timedelta(seconds=token_set.expires_in)
    current.refresh_token_expires_at = (
        now + timedelta(seconds=token_set.refresh_expires_in)
        if token_set.refresh_expires_in > 0
        else None
    )
    current.granted_scopes = sorted(token_set.scope)
    current.last_verified_at = now
    current.updated_at = now
    db.commit()
    return {
        "id": str(current.id),
        "status": current.status,
        "access_token_expires_at": current.access_token_expires_at.isoformat(),
        "refresh_token_expires_at": (
            current.refresh_token_expires_at.isoformat()
            if current.refresh_token_expires_at
            else None
        ),
        "last_verified_at": current.last_verified_at.isoformat(),
    }


class DouyinPublishOperationRequest(BaseModel):
    publish_package_id: UUID
    publish_package_item_id: UUID
    package_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/publish-operations", status_code=202)
def create_douyin_publish_operation(
    payload: DouyinPublishOperationRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > 200:
        raise ApiError(400, "IDEMPOTENCY_KEY_INVALID", "A valid idempotency key is required")

    package = db.scalar(
        select(PublishPackage)
        .where(
            PublishPackage.id == payload.publish_package_id,
            PublishPackage.store_id == store_id,
        )
        .with_for_update()
    )
    if package is None:
        raise ApiError(404, "PUBLISH_PACKAGE_NOT_FOUND", "Publish package not found")
    if package.package_fingerprint != payload.package_fingerprint:
        raise ApiError(409, "PACKAGE_STALE", "Publish package fingerprint has changed")

    item = db.scalar(
        select(PublishPackageItem).where(
            PublishPackageItem.id == payload.publish_package_item_id,
            PublishPackageItem.store_id == store_id,
            PublishPackageItem.publish_package_id == package.id,
        )
    )
    if item is None:
        raise ApiError(404, "PUBLISH_PACKAGE_ITEM_NOT_FOUND", "Publish package item not found")
    if item.delivery_mode != "official_api" or item.channel_key != "douyin":
        raise ApiError(
            409,
            "DOUYIN_OFFICIAL_DELIVERY_REQUIRED",
            "Only a frozen Douyin official-API package item can be published here",
        )
    if item.channel_account_id is None:
        raise ApiError(409, "DOUYIN_ACCOUNT_REQUIRED", "A Douyin account is required")

    if item.planned_publish_at is not None and item.planned_publish_at > datetime.now(UTC):
        raise ApiError(
            409,
            "SCHEDULED_PUBLISH_NOT_SUPPORTED",
            "Scheduled Douyin publishing is not enabled in this pilot; publish the confirmed package manually.",
        )

    latest_version = db.scalar(
        select(func.max(PublishPackage.package_version)).where(
            PublishPackage.store_id == store_id,
            PublishPackage.task_id == package.task_id,
        )
    )
    if latest_version != package.package_version:
        raise ApiError(409, "PACKAGE_STALE", "A newer publish package exists")

    confirmation = db.scalar(
        select(PublishConfirmation).where(
            PublishConfirmation.store_id == store_id,
            PublishConfirmation.publish_package_id == package.id,
            PublishConfirmation.package_fingerprint == package.package_fingerprint,
        )
    )
    if confirmation is None:
        raise ApiError(
            422,
            "MERCHANT_CONFIRMATION_REQUIRED",
            "The exact frozen package must be confirmed by a merchant before publishing",
        )

    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == item.channel_account_id,
            ChannelAccount.store_id == store_id,
            ChannelAccount.provider == "douyin",
            ChannelAccount.status == "active",
        )
    )
    if account is None:
        raise ApiError(
            409,
            "DOUYIN_ACCOUNT_NOT_ACTIVE",
            "The bound Douyin account is no longer active; reconnect it before publishing",
        )

    request_fingerprint = hashlib.sha256(
        "|".join(
            (
                str(store_id),
                str(package.id),
                str(item.id),
                package.package_fingerprint,
                str(account.id),
            )
        ).encode("utf-8")
    ).hexdigest()

    existing = db.scalar(
        select(PublishOperation)
        .where(
            PublishOperation.store_id == store_id,
            PublishOperation.idempotency_key == normalized_key,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise ApiError(
                409,
                "PUBLISH_IDEMPOTENCY_CONFLICT",
                "Idempotency key was used for a different publish request",
            )
        existing_job = db.scalar(
            select(Job).where(
                Job.idempotency_scope_type == "store",
                Job.idempotency_scope_id == store_id,
                Job.idempotency_key == f"douyin-publish-operation:{existing.id}",
            )
        )
        return {
            "publish_operation_id": str(existing.id),
            "job_id": str(existing_job.id) if existing_job else None,
            "status": existing.status,
            "platform_item_id": existing.platform_item_id,
            "idempotent_replay": True,
        }

    existing_item_operation = db.scalar(
        select(PublishOperation).where(
            PublishOperation.store_id == store_id,
            PublishOperation.publish_package_item_id == item.id,
        )
    )
    if existing_item_operation is not None:
        raise ApiError(
            409,
            "PUBLISH_OPERATION_ALREADY_EXISTS",
            "This frozen package item already has a publish operation",
        )

    operation = PublishOperation(
        id=uuid4(),
        store_id=store_id,
        publish_package_id=package.id,
        publish_package_item_id=item.id,
        publish_confirmation_id=confirmation.id,
        channel_account_id=account.id,
        idempotency_key=normalized_key,
        request_fingerprint=request_fingerprint,
        status="queued",
        attempt_count=0,
        confirmed_by_user_id=confirmation.confirmed_by_user_id,
        confirmed_package_fingerprint=package.package_fingerprint,
    )
    try:
        with db.begin_nested():
            db.add(operation)
            db.flush()
    except IntegrityError as exc:
        winner = db.scalar(
            select(PublishOperation).where(
                PublishOperation.store_id == store_id,
                PublishOperation.idempotency_key == normalized_key,
            )
        )
        if winner is not None and winner.request_fingerprint == request_fingerprint:
            winner_job = db.scalar(
                select(Job).where(
                    Job.idempotency_scope_type == "store",
                    Job.idempotency_scope_id == store_id,
                    Job.idempotency_key == f"douyin-publish-operation:{winner.id}",
                )
            )
            return {
                "publish_operation_id": str(winner.id),
                "job_id": str(winner_job.id) if winner_job else None,
                "status": winner.status,
                "platform_item_id": winner.platform_item_id,
                "idempotent_replay": True,
            }
        raise ApiError(
            409,
            "PUBLISH_OPERATION_ALREADY_EXISTS",
            "This frozen package item or idempotency key already has a publish operation.",
        ) from exc

    try:
        job = create_job(
            db,
            job_type="channel.douyin.publish",
            payload_ref={
                "schema_version": 1,
                "publish_operation_id": str(operation.id),
            },
            idempotency_key=f"douyin-publish-operation:{operation.id}",
            store_id=store_id,
            actor_type="user",
            actor_user_id=auth.user.id,
            marketing_task_id=package.task_id,
            max_attempts=3,
            timeout_seconds=600,
        )
    except JobIdempotencyConflict as exc:
        raise ApiError(
            409,
            "PUBLISH_JOB_IDEMPOTENCY_CONFLICT",
            "A conflicting publish job already exists",
        ) from exc

    record_audit(
        db,
        request,
        action="channel.douyin.publish_operation.created",
        target_type="publish_operation",
        target_id=operation.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "publish_package_id": str(package.id),
            "publish_package_item_id": str(item.id),
            "channel_account_id": str(account.id),
            "confirmation_id": str(confirmation.id),
            "job_id": str(job.id),
        },
    )
    db.commit()
    return {
        "publish_operation_id": str(operation.id),
        "job_id": str(job.id),
        "status": operation.status,
        "platform_item_id": operation.platform_item_id,
        "idempotent_replay": False,
    }
