import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.errors import ApiError
from store_operator.auth.security import csrf_token_verifier, session_token_verifier
from store_operator.config import settings
from store_operator.db import get_db
from store_operator.models.identity import (
    AuthSession,
    PlatformAdminGrant,
    Store,
    StoreMembership,
    User,
)

SESSION_COOKIE_NAME = "__Host-ai_store_session"
STORE_BUSINESS_CAPABILITIES = frozenset({"store.business.use"})


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user: User
    session: AuthSession


def validate_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            parsed = urlsplit(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed = {item.strip().rstrip("/") for item in settings.cors_origins.split(",") if item.strip()}
    if not origin or origin.rstrip("/") not in allowed:
        raise ApiError(403, "CSRF_INVALID", "Request origin is not allowed")


def get_current_session(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedSession:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise ApiError(401, "UNAUTHENTICATED", "Unauthenticated")

    verifier = session_token_verifier(raw_token, settings.session_token_pepper)
    try:
        auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == verifier))
        if auth_session is None or auth_session.revoked_at is not None:
            request.state.clear_session_cookie = True
            raise ApiError(401, "UNAUTHENTICATED", "Unauthenticated")
        user = db.get(User, auth_session.user_id)
        now = datetime.now(UTC)
        if (
            user is None
            or user.status != "active"
            or auth_session.auth_version != user.auth_version
            or auth_session.idle_expires_at <= now
            or auth_session.expires_at <= now
        ):
            if auth_session.revoked_at is None:
                auth_session.revoked_at = now
                auth_session.revoke_reason = "expired_or_invalidated"
                db.commit()
            request.state.clear_session_cookie = True
            raise ApiError(401, "UNAUTHENTICATED", "Unauthenticated")

        if auth_session.last_seen_at <= now - timedelta(
            seconds=settings.session_last_seen_update_seconds
        ):
            auth_session.last_seen_at = now
            auth_session.idle_expires_at = min(
                now + timedelta(seconds=settings.session_idle_timeout_seconds),
                auth_session.expires_at,
            )
            db.commit()
        request.state.auth_user_id = user.id
        request.state.auth_session_id = auth_session.id
        return AuthenticatedSession(user=user, session=auth_session)
    except SQLAlchemyError as exc:
        db.rollback()
        raise ApiError(
            503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
        ) from exc


def require_csrf(
    request: Request,
    auth: AuthenticatedSession = Depends(get_current_session),
) -> AuthenticatedSession:
    validate_browser_origin(request)
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        raise ApiError(403, "CSRF_INVALID", "CSRF token is required")
    supplied_hash = csrf_token_verifier(supplied)
    if not hmac.compare_digest(supplied_hash, auth.session.csrf_token_hash):
        raise ApiError(403, "CSRF_INVALID", "CSRF token is invalid")
    return auth


def require_store_context(
    request: Request,
    store_id_header: str | None = Header(default=None, alias="X-Store-ID"),
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not store_id_header:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    try:
        store_id = UUID(store_id_header)
        store = db.scalar(select(Store).where(Store.id == store_id, Store.status == "active"))
        membership = db.scalar(
            select(StoreMembership).where(
                StoreMembership.store_id == store_id,
                StoreMembership.user_id == auth.user.id,
                StoreMembership.status == "active",
            )
        )
    except ValueError as exc:
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise ApiError(
            503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
        ) from exc

    if store is None or membership is None:
        record_audit(
            db,
            request,
            action="store.context.access",
            target_type="store",
            target_id=store_id,
            actor_user_id=auth.user.id,
            result="denied",
            metadata={"reason": "not_member_or_inactive"},
        )
        db.commit()
        raise ApiError(404, "STORE_NOT_FOUND", "Store not found")
    context = AuthContext(
        user_id=auth.user.id,
        session_id=auth.session.id,
        request_store_id=store.id,
        membership_id=membership.id,
        role=membership.role,
        capabilities=STORE_BUSINESS_CAPABILITIES,
        authorization_version=auth.user.auth_version,
        request_id=getattr(request.state, "request_id", "unavailable"),
    )
    request.state.auth_context = context
    return context


def require_platform_admin(
    request: Request,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> AuthenticatedSession:
    try:
        grant = db.scalar(
            select(PlatformAdminGrant).where(
                PlatformAdminGrant.user_id == auth.user.id,
                PlatformAdminGrant.status == "active",
            )
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise ApiError(
            503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
        ) from exc
    if grant is None:
        record_audit(
            db,
            request,
            action="platform_admin.access",
            target_type="capability",
            target_id="platform.store_members.manage",
            actor_user_id=auth.user.id,
            result="denied",
        )
        db.commit()
        raise ApiError(403, "FORBIDDEN", "Forbidden")
    return auth
