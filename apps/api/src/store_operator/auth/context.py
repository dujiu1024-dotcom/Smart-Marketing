from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuthContext:
    user_id: UUID
    session_id: UUID
    request_store_id: UUID | None
    membership_id: UUID | None
    role: str | None
    capabilities: frozenset[str]
    authorization_version: int
    request_id: str
