from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from store_operator.ai_gateway.errors import ProviderCapability  # type: ignore[attr-defined]


class PromptTaskType(StrEnum):
    MARKETING_STRATEGY = "marketing_strategy"
    COPY_GENERATION = "copy_generation"
    COPY_REVISION = "copy_revision"
    VIDEO_SCRIPT = "video_script"
    IMAGE_PROMPT = "image_prompt"
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDIT = "image_edit"
    VISUAL_QUALITY_CHECK = "visual_quality_check"
    OCR_EXTRACTION = "ocr_extraction"


@dataclass(frozen=True, slots=True)
class PromptTaskContract:
    capability: str
    required_output_properties: frozenset[str]
    forced_true_properties: frozenset[str] = frozenset()


PROMPT_TASK_CONTRACTS: dict[PromptTaskType, PromptTaskContract] = {
    PromptTaskType.MARKETING_STRATEGY: PromptTaskContract(
        "text",
        frozenset({
            "strategy_summary",
            "target_audience",
            "key_message",
            "content_angles",
            "execution_plan",
            "risk_notes",
        }),
    ),
    PromptTaskType.COPY_GENERATION: PromptTaskContract(
        "text", frozenset({"title", "body", "hashtags", "call_to_action"})
    ),
    PromptTaskType.COPY_REVISION: PromptTaskContract(
        "text", frozenset({"title", "body", "change_summary"})
    ),
    PromptTaskType.VIDEO_SCRIPT: PromptTaskContract(
        "text",
        frozenset({"theme", "spoken_script", "storyboard", "shooting_guidance"}),
    ),
    PromptTaskType.IMAGE_PROMPT: PromptTaskContract(
        "text", frozenset({"prompt", "negative_prompt", "aspect_ratio"})
    ),
    PromptTaskType.IMAGE_GENERATION: PromptTaskContract(
        "image", frozenset({"asset_object_key", "sha256", "mime_type", "width", "height"})
    ),
    PromptTaskType.IMAGE_EDIT: PromptTaskContract(
        "image", frozenset({"asset_object_key", "sha256", "mime_type", "width", "height"})
    ),
    PromptTaskType.VISUAL_QUALITY_CHECK: PromptTaskContract(
        "vision",
        frozenset({"findings", "overall_severity", "revision_suggestions", "human_review_required"}),
        frozenset({"human_review_required"}),
    ),
    PromptTaskType.OCR_EXTRACTION: PromptTaskContract(
        "ocr", frozenset({"extracted_text", "structured_fields", "confidence"})
    ),
}


def validate_prompt_task_contract(
    task_type: str,
    capability: str,
    output_schema: dict[str, Any],
) -> None:
    """Require task-specific capability and output fields before a PromptVersion can publish."""
    try:
        task = PromptTaskType(task_type)
    except ValueError as exc:
        raise ValueError("Prompt task type has no executable contract") from exc
    contract = PROMPT_TASK_CONTRACTS[task]
    if capability != contract.capability:
        raise ValueError("Prompt capability does not match the task contract")
    if output_schema.get("type") != "object":
        raise ValueError("Task output schema must be a JSON object schema")
    properties = output_schema.get("properties")
    required = output_schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError("Task output schema must declare properties and required fields")
    missing = contract.required_output_properties - set(properties)
    if missing or not contract.required_output_properties.issubset(set(required)):
        raise ValueError("Task output schema is missing required contract fields")
    for property_name in contract.forced_true_properties:
        property_schema = properties.get(property_name)
        if (
            not isinstance(property_schema, dict)
            or property_schema.get("type") != "boolean"
            or property_schema.get("enum") != [True]
        ):
            raise ValueError("Visual quality checks must require human_review_required=true")
