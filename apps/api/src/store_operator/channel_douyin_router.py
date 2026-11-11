from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    get_current_session,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.channels.douyin import DouyinAppCredentials, DouyinOAuthClient
from store_operator.channels.oauth_state import consume_oauth_state, new_oauth_state
from store_operator.channels.secret_store import AwsSecretsManagerStore, SecretStoreError
from store_operator.config import settings
from store_operator.db import get_db
from store_operator.models.channel_delivery import ChannelAccount, OAuthAuthorizationAttempt
from store_operator.models.identity import Store, StoreMembership

router = APIRouter(prefix="/channels/douyin", tags=["channel-accounts"])

DOUYIN_REQUIRED_SCOPES = frozenset({"user_info", "video.create.bind", "video.list"})


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
def begin_douyin_authorization(
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
        import asyncio

        asyncio.run(client.aclose())
    return {"authorization_url": authorization_url, "expires_in": "600"}


@router.get("/oauth/callback")
async def complete_douyin_authorization(
    request: Request,
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
        raise ApiError(400, "OAUTH_STATE_INVALID", "OAuth authorization state is invalid or expired")
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
        raise ApiError(400, "OAUTH_STATE_INVALID", "OAuth authorization state is invalid or expired")
    db.commit()

    client = DouyinOAuthClient(credentials)
    try:
        token_set = await client.exchange_code(code)
        profile = await client.get_account_profile(token_set.access_token)
    finally:
        await client.aclose()

    if profile["open_id"] != token_set.open_id:
        raise ApiError(502, "OAUTH_ACCOUNT_MISMATCH", "Douyin account identity could not be verified")
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
            f"{settings.channel_secret_store_prefix}/{attempt.store_id}/douyin/{external_id_digest}",
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
