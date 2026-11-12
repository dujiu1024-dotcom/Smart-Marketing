from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)


class UserSummary(BaseModel):
    id: UUID
    email: str


class SessionSummary(BaseModel):
    expires_at: datetime


class StoreSummary(BaseModel):
    id: UUID
    name: str


class LoginResponse(BaseModel):
    user: UserSummary
    session: SessionSummary
    csrf_token: str


class MeResponse(BaseModel):
    user: UserSummary
    active_store: StoreSummary | None
    session: SessionSummary


class StoreMembershipSummary(BaseModel):
    id: UUID
    name: str
    role: Literal["owner", "member"]


class StoresResponse(BaseModel):
    items: list[StoreMembershipSummary]
    active_store_id: UUID | None


class ActiveStoreRequest(BaseModel):
    store_id: UUID


class ActiveStoreResponse(BaseModel):
    active_store: StoreSummary
    membership: dict[str, str]


class MemberSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_id: UUID
    user_id: UUID
    email: str
    role: Literal["owner", "member"]
    status: Literal["invited", "active", "suspended", "removed"]


class MemberPatchRequest(BaseModel):
    role: Literal["owner", "member"] | None = None
    status: Literal["active", "suspended", "removed"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "MemberPatchRequest":
        if self.role is None and self.status is None:
            raise ValueError("At least one of role or status must be provided")
        return self


class LogoutAllRequest(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=1024)


class PasswordChangeRequest(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class PasswordChangeResponse(BaseModel):
    session: SessionSummary
    csrf_token: str
