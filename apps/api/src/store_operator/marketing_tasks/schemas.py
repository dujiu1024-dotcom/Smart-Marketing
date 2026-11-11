from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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
    opportunity_applicable: bool | None = None
    selected_channel_keys: list[str] = Field(default_factory=list, max_length=20)
    requires_external_delivery: bool = False


class MarketingTaskCreate(BaseModel):
    task_type: MarketingTaskType
    title: str = Field(min_length=1, max_length=200)
    requirement_draft: dict[str, object] = Field(default_factory=dict)
    task_options: MarketingTaskOptions = Field(default_factory=MarketingTaskOptions)

    @model_validator(mode="after")
    def validate_task_scope(self) -> "MarketingTaskCreate":
        options = self.task_options
        if self.task_type is MarketingTaskType.COPY_ONLY:
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
