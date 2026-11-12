from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from store_operator.domain.marketing_task import (
    MarketingTaskStatus,
    MarketingTaskType,
    StepApplicability,
    TaskStepKey,
    TaskStepStatus,
)


class MarketingTaskOptions(BaseModel):
    includes_copy: bool | None = None
    includes_image: bool | None = None
    includes_video_script: bool = False
    opportunity_applicable: bool | None = None
    opportunity_snapshot: dict[str, object] | None = None
    selected_channel_keys: list[str] = Field(default_factory=list, max_length=20)
    requires_external_delivery: bool = False


class MarketingTaskCreate(BaseModel):
    task_type: MarketingTaskType
    title: str = Field(min_length=1, max_length=200)
    opportunity_id: UUID | None = None
    requirement_draft: dict[str, object] = Field(default_factory=dict)
    task_options: MarketingTaskOptions = Field(default_factory=MarketingTaskOptions)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("title must contain non-whitespace characters")
        return value.strip()

    @model_validator(mode="after")
    def validate_task_scope(self) -> "MarketingTaskCreate":
        options = self.task_options
        if self.task_type is MarketingTaskType.FULL_MARKETING:
            if options.includes_copy is False or options.includes_image is False:
                raise ValueError("full_marketing tasks must include both copy and image")
        elif self.task_type is MarketingTaskType.COPY_ONLY:
            if options.includes_copy is False or options.includes_image is True:
                raise ValueError("copy_only tasks must include copy and cannot include image")
        elif self.task_type in {
            MarketingTaskType.IMAGE_ONLY,
            MarketingTaskType.IMAGE_OPTIMIZATION,
        }:
            if options.includes_image is False or options.includes_copy is True:
                raise ValueError("image tasks must include image and cannot include copy")
        elif self.task_type is MarketingTaskType.MERCHANT_CONTENT:
            if options.includes_copy is None or options.includes_image is None:
                raise ValueError(
                    "merchant_content requires explicit includes_copy and includes_image"
                )
            if not options.includes_copy and not options.includes_image:
                raise ValueError("merchant_content must include copy, image, or both")
        if options.includes_video_script and (
            self.task_type in {
                MarketingTaskType.IMAGE_ONLY,
                MarketingTaskType.IMAGE_OPTIMIZATION,
            }
            or options.includes_copy is False
        ):
            raise ValueError("video scripts require a copy deliverable")
        return self


class TaskStepRead(BaseModel):
    id: UUID
    step_key: TaskStepKey
    status: TaskStepStatus
    applicability: StepApplicability
    version: int
    skip_reason: str | None
    input_fingerprint: str | None
    output_refs: list[dict[str, object]]
    blocked_by: list[dict[str, object]]
    block_code: str | None
    block_detail: dict[str, object] | None
    started_at: datetime | None
    finished_at: datetime | None


class MarketingTaskSummary(BaseModel):
    id: UUID
    store_id: UUID
    task_type: MarketingTaskType
    lifecycle_status: MarketingTaskStatus
    title: str
    version: int
    current_requirement_snapshot_id: UUID | None
    current_strategy_snapshot_id: UUID | None
    created_at: datetime
    updated_at: datetime
    pending_steps_count: int
    blocked_steps_count: int


class MarketingTaskDetail(MarketingTaskSummary):
    requirement_draft: dict[str, object]
    strategy_draft: dict[str, object]
    task_options: dict[str, object]
    steps: list[TaskStepRead]


class MarketingTaskList(BaseModel):
    items: list[MarketingTaskSummary]
    total: int



class BusinessFactReference(BaseModel):
    fact_key: str = Field(min_length=1, max_length=120)
    record_type: Literal[
        "store_profile",
        "product",
        "offer",
        "audience_profile",
        "brand_guideline",
        "knowledge_item",
    ]
    record_id: UUID
    expected_version_no: int | None = Field(default=None, ge=1)

    @field_validator("fact_key", mode="before")
    @classmethod
    def normalize_fact_key(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("fact_key must contain non-whitespace characters")
        return value.strip()


class MarketingTaskRequirementUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    requirement_draft: dict[str, object]
    task_options: MarketingTaskOptions | None = None


class MarketingTaskRequirementConfirm(BaseModel):
    expected_version: int = Field(ge=1)
    business_facts: list[BusinessFactReference] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def require_unique_fact_keys(self) -> "MarketingTaskRequirementConfirm":
        keys = [fact.fact_key for fact in self.business_facts]
        if len(keys) != len(set(keys)):
            raise ValueError("business_facts must have unique fact_key values")
        return self


class MarketingTaskStrategyUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    strategy: dict[str, object]

    @model_validator(mode="after")
    def require_non_empty_strategy(self) -> "MarketingTaskStrategyUpdate":
        if not self.strategy:
            raise ValueError("strategy must contain at least one field")
        return self


class MarketingTaskStrategyConfirm(BaseModel):
    expected_version: int = Field(ge=1)


class MarketingTaskStepSkip(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> str:
        if not isinstance(value, str) or len(value.strip()) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return value.strip()


class MarketingTaskRecover(BaseModel):
    expected_version: int = Field(ge=1)
    step_key: TaskStepKey
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> str:
        if not isinstance(value, str) or len(value.strip()) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return value.strip()


class MarketingTaskAction(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> str:
        if not isinstance(value, str) or len(value.strip()) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return value.strip()
