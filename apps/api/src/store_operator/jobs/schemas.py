from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobEventRead(BaseModel):
    event_type: str
    created_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    marketing_task_id: UUID | None
    job_type: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    progress_current: int | None
    progress_total: int | None
    error_code: str | None
    error_summary: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    cancelled_at: datetime | None


class JobDetailRead(JobRead):
    events: list[JobEventRead]


class JobRetryRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    side_effects_confirmed_absent: bool


class JobResolveRequest(BaseModel):
    resolution: Literal["retry", "fail"]
    reason: str = Field(min_length=1, max_length=500)
    side_effects_confirmed_absent: bool = False


class AIUsageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    input_tokens: int | None
    output_tokens: int | None
    image_units: Decimal | None
    cost_amount: Decimal | None
    currency: str | None
    metering_source: str
    recorded_at: datetime


class AIInvocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID | None
    job_id: UUID | None
    provider_key: str
    model_key: str
    capability: str
    prompt_version_id: UUID | None
    provider_request_id: str | None
    request_fingerprint: str | None
    status: str
    duration_ms: int | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    usage: AIUsageRead | None
