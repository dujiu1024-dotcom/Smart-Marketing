from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from store_operator.models.channel_delivery import OAuthAuthorizationAttempt


def new_oauth_state() -> tuple[str, bytes]:
    """Return a high-entropy browser state and its one-way database representation."""
    raw_state = secrets.token_urlsafe(48)
    return raw_state, hashlib.sha256(raw_state.encode("utf-8")).digest()


def consume_oauth_state(
    db: Session,
    *,
    raw_state: str,
    provider: str,
    user_id: UUID,
    store_id: UUID,
    session_id: UUID,
    now: datetime | None = None,
) -> OAuthAuthorizationAttempt | None:
    """Atomically consume a state bound to the initiating user, store and session."""
    if not raw_state or len(raw_state) > 256:
        return None
    consumed_at = now or datetime.now(UTC)
    state_hash = hashlib.sha256(raw_state.encode("utf-8")).digest()
    statement = (
        update(OAuthAuthorizationAttempt)
        .where(
            OAuthAuthorizationAttempt.state_hash == state_hash,
            OAuthAuthorizationAttempt.provider == provider,
            OAuthAuthorizationAttempt.user_id == user_id,
            OAuthAuthorizationAttempt.store_id == store_id,
            OAuthAuthorizationAttempt.session_id == session_id,
            OAuthAuthorizationAttempt.consumed_at.is_(None),
            OAuthAuthorizationAttempt.expires_at > consumed_at,
        )
        .values(consumed_at=consumed_at)
        .returning(OAuthAuthorizationAttempt.id)
    )
    attempt_id = db.scalar(statement)
    if attempt_id is None:
        return None
    db.flush()
    return db.get(OAuthAuthorizationAttempt, attempt_id)
