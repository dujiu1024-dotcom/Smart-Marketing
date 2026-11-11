import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.dependencies import (
    SESSION_COOKIE_NAME,
    AuthenticatedSession,
    get_current_session,
    require_csrf,
    validate_browser_origin,
)
from store_operator.auth.errors import ApiError
from store_operator.auth.schemas import (
    LoginRequest,
    LoginResponse,
    LogoutAllRequest,
    MeResponse,
    SessionSummary,
    StoreSummary,
    UserSummary,
)
from store_operator.auth.security import (
    csrf_token_verifier,
    dummy_password_hash,
    fingerprint,
    normalize_email,
    random_token,
    session_token_verifier,
    verify_password,
)
from store_operator.config import settings
from store_operator.db import get_db, redis_client
from store_operator.models.identity import AuthSession, Store, StoreMembership, User

router = APIRouter(tags=["identity"])


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_absolute_timeout_seconds,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )


def _login_rate_limit_keys(request: Request, email: str) -> tuple[str, str]:
    ip = request.client.host if request.client else "unknown"
    ip_hash = fingerprint(ip, settings.session_token_pepper)
    email_hash = fingerprint(email, settings.session_token_pepper)
    return f"auth:login:ip:{ip_hash}", f"auth:login:account:{email_hash}"


_LOGIN_RATE_LIMIT_SCRIPT = """
local ip_count = redis.call("INCR", KEYS[1])
if ip_count == 1 then redis.call("EXPIRE", KEYS[1], ARGV[1]) end
local account_count = redis.call("INCR", KEYS[2])
if account_count == 1 then redis.call("EXPIRE", KEYS[2], ARGV[1]) end
return {ip_count, account_count}
"""


def _consume_login_attempt(keys: tuple[str, str]) -> None:
    # Reserve both buckets atomically before password verification so concurrent
    # requests cannot all pass a stale MGET check.
    counts = redis_client.eval(
        _LOGIN_RATE_LIMIT_SCRIPT,
        2,
        keys[0],
        keys[1],
        settings.auth_login_window_seconds,
    )
    if any(int(value) > settings.auth_login_max_attempts for value in counts):
        raise ApiError(429, "RATE_LIMITED", "Too many login attempts")


@router.post("/auth/login", response_model=LoginResponse)
def login(
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
        valid_password = verify_password(candidate_hash, payload.password.get_secret_value())
        if user is None or not valid_password or user.status != "active":
            record_audit(
                db,
                request,
                action="auth.login",
                target_type="user",
                target_id=fingerprint(email, settings.session_token_pepper),
                actor_user_id=user.id if user else None,
                result="denied",
                metadata={"reason": "invalid_credentials"},
            )
            db.commit()
            raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password")

        try:
            redis_client.delete(rate_keys[1])
        except RedisError as exc:
            raise ApiError(
                503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
            ) from exc
        now = datetime.now(UTC)
        raw_token = random_token()
        csrf_token = random_token()
        expires_at = now + timedelta(seconds=settings.session_absolute_timeout_seconds)
        auth_session = AuthSession(
            id=uuid4(),
            user_id=user.id,
            token_hash=session_token_verifier(raw_token, settings.session_token_pepper),
            csrf_token_hash=csrf_token_verifier(csrf_token),
            auth_version=user.auth_version,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=min(
                now + timedelta(seconds=settings.session_idle_timeout_seconds), expires_at
            ),
            expires_at=expires_at,
            ip_fingerprint=fingerprint(
                request.client.host if request.client else "unknown",
                settings.session_token_pepper,
            ),
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
        db.add(auth_session)
        record_audit(
            db,
            request,
            action="auth.login",
            target_type="user",
            target_id=user.id,
            actor_user_id=user.id,
            metadata={"session_id": str(auth_session.id)},
        )
        db.commit()
        _set_session_cookie(response, raw_token)
        return LoginResponse(
            user=UserSummary(id=user.id, email=user.email_normalized),
            session=SessionSummary(expires_at=expires_at),
            csrf_token=csrf_token,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise ApiError(
            503, "AUTHORIZATION_UNAVAILABLE", "Authorization service unavailable"
        ) from exc


@router.get("/auth/me", response_model=MeResponse)
def me(
    auth: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> MeResponse:
    active_store = None
    if auth.session.active_store_id is not None:
        row = db.execute(
            select(Store, StoreMembership)
            .join(StoreMembership, StoreMembership.store_id == Store.id)
            .where(
                Store.id == auth.session.active_store_id,
                Store.status == "active",
                StoreMembership.user_id == auth.user.id,
                StoreMembership.status == "active",
            )
        ).first()
        if row:
            store, _membership = row
            active_store = StoreSummary(id=store.id, name=store.name)
        else:
            auth.session.active_store_id = None
            db.commit()
    return MeResponse(
        user=UserSummary(id=auth.user.id, email=auth.user.email_normalized),
        active_store=active_store,
        session=SessionSummary(expires_at=auth.session.expires_at),
    )


@router.post("/auth/csrf")
def refresh_csrf(
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    validate_browser_origin(request)
    token = random_token()
    auth.session.csrf_token_hash = csrf_token_verifier(token)
    db.commit()
    return {"csrf_token": token}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    validate_browser_origin(request)
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        verifier = session_token_verifier(raw_token, settings.session_token_pepper)
        auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == verifier))
        if auth_session is not None and auth_session.revoked_at is None:
            supplied_csrf = request.headers.get("x-csrf-token")
            if (
                not supplied_csrf
                or not hmac.compare_digest(
                    csrf_token_verifier(supplied_csrf), auth_session.csrf_token_hash
                )
            ):
                raise ApiError(403, "CSRF_INVALID", "CSRF token is invalid")
            auth_session.revoked_at = datetime.now(UTC)
            auth_session.revoke_reason = "logout"
            record_audit(
                db,
                request,
                action="auth.logout",
                target_type="session",
                target_id=auth_session.id,
                actor_user_id=auth_session.user_id,
            )
            db.commit()
    _clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/auth/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    payload: LogoutAllRequest,
    request: Request,
    response: Response,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not verify_password(auth.user.password_hash, payload.password.get_secret_value()):
        raise ApiError(401, "REAUTHENTICATION_REQUIRED", "Reauthentication required")
    now = datetime.now(UTC)
    auth.user.auth_version += 1
    sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == auth.user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    for item in sessions:
        item.revoked_at = now
        item.revoke_reason = "logout_all"
    record_audit(
        db,
        request,
        action="auth.logout_all",
        target_type="user",
        target_id=auth.user.id,
        actor_user_id=auth.user.id,
    )
    db.commit()
    _clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
