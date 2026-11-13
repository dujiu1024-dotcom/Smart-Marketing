"""Repeatable seed for the published prompt templates used by AI generation jobs.

The Worker resolves exactly one active published PromptTemplate for each
(task_type, capability) scope. Running the seed repeatedly only creates a new
published version when the desired content is not already published.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.ai_gateway.prompt_contracts import validate_prompt_task_contract
from store_operator.models.prompt_management import (
    PromptActivation,
    PromptTemplate,
    PromptVersion,
)


@dataclass(frozen=True, slots=True)
class PromptSeed:
    template_key: str
    display_name: str
    task_type: str
    capability: str
    description: str
    system_prompt: str
    user_prompt_template: str
    variables_schema_json: dict[str, object]
    output_schema_json: dict[str, object]
    changelog: str

    def content(self) -> dict[str, object]:
        return {
            "system_prompt": self.system_prompt,
            "user_prompt_template": self.user_prompt_template,
            "variables_schema_json": self.variables_schema_json,
            "output_schema_json": self.output_schema_json,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.content())


def _fingerprint(content: dict[str, object]) -> str:
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _version_fingerprint(version: PromptVersion) -> str:
    return _fingerprint(
        {
            "system_prompt": version.system_prompt,
            "user_prompt_template": version.user_prompt_template,
            "variables_schema_json": version.variables_schema_json,
            "output_schema_json": version.output_schema_json,
        }
    )


def _object_schema(
    properties: dict[str, object],
    required: list[str],
) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_STRATEGY_SEED = PromptSeed(
    template_key="general_marketing_strategy",
    display_name="通用营销策略生成",
    task_type="marketing_strategy",
    capability="text",
    description="根据已确认需求与业务事实生成营销策略草稿。",
    system_prompt=(
        "你是资深本地生活营销策略师。只能使用用户提供的已确认需求与业务事实，"
        "不得编造门店、商品、价格或活动信息。"
        "输出必须是单个 JSON 对象，不要输出 Markdown 代码块或额外解释。"
    ),
    user_prompt_template=(
        "任务标题：{{task_title}}\n"
        "已确认需求：{{requirement}}\n"
        "已确认业务事实：{{business_facts}}\n\n"
        "请输出 JSON，字段为：strategy_summary（策略摘要，字符串）、"
        "target_audience（目标客群，字符串）、key_message（核心信息，字符串）、"
        "content_angles（内容角度，字符串数组）、execution_plan（执行计划，字符串数组）、"
        "risk_notes（风险提示，字符串数组）。"
    ),
    variables_schema_json=_object_schema(
        {
            "task_title": {"type": "string", "minLength": 1, "maxLength": 300},
            "requirement": {"type": "object"},
            "business_facts": {"type": "array", "items": {"type": "object"}},
        },
        ["task_title", "requirement", "business_facts"],
    ),
    output_schema_json=_object_schema(
        {
            "strategy_summary": {"type": "string", "minLength": 1},
            "target_audience": {"type": "string", "minLength": 1},
            "key_message": {"type": "string", "minLength": 1},
            "content_angles": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "execution_plan": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "risk_notes": {"type": "array", "items": {"type": "string"}},
        },
        [
            "strategy_summary",
            "target_audience",
            "key_message",
            "content_angles",
            "execution_plan",
            "risk_notes",
        ],
    ),
    changelog="初始版本：通用营销策略生成契约",
)

_COPY_GENERATION_SEED = PromptSeed(
    template_key="general_copy_generation",
    display_name="通用营销文案生成",
    task_type="copy_generation",
    capability="text",
    description="根据已确认策略生成可直接审核的营销文案。",
    system_prompt=(
        "你是本地生活商家营销文案编辑。只能使用已确认需求、策略与业务事实，"
        "不得虚构价格、折扣、资质或承诺。"
        "输出必须是单个 JSON 对象，不要输出 Markdown 代码块或额外解释。"
    ),
    user_prompt_template=(
        "任务标题：{{task_title}}\n"
        "已确认需求：{{requirement}}\n"
        "已确认策略：{{strategy}}\n"
        "已确认业务事实：{{business_facts}}\n\n"
        "请输出 JSON，字段为：title（标题，字符串）、body（正文，字符串）、"
        "hashtags（话题标签数组，不含 # 号也可）、call_to_action（行动号召，字符串）。"
    ),
    variables_schema_json=_object_schema(
        {
            "task_title": {"type": "string", "minLength": 1, "maxLength": 300},
            "requirement": {"type": "object"},
            "strategy": {"type": "object"},
            "business_facts": {"type": "array", "items": {"type": "object"}},
        },
        ["task_title", "requirement", "strategy", "business_facts"],
    ),
    output_schema_json=_object_schema(
        {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "body": {"type": "string", "minLength": 1},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "call_to_action": {"type": "string", "minLength": 1},
        },
        ["title", "body", "hashtags", "call_to_action"],
    ),
    changelog="初始版本：通用营销文案生成契约",
)

_COPY_REVISION_SEED = PromptSeed(
    template_key="general_copy_revision",
    display_name="通用营销文案修订",
    task_type="copy_revision",
    capability="text",
    description="根据审核意见修订已有营销文案。",
    system_prompt=(
        "你是本地生活商家营销文案编辑。根据修订意见修改现有文案，"
        "保留其中仍然正确的事实与卖点，不得编造新事实。"
        "输出必须是单个 JSON 对象，不要输出 Markdown 代码块或额外解释。"
    ),
    user_prompt_template=(
        "任务标题：{{task_title}}\n"
        "已确认需求：{{requirement}}\n"
        "已确认策略：{{strategy}}\n"
        "当前文案：{{previous_copy}}\n"
        "修订意见：{{revision_instruction}}\n\n"
        "请输出 JSON，字段为：title（标题，字符串）、body（正文，字符串）、"
        "change_summary（本次修改说明，字符串）。"
    ),
    variables_schema_json=_object_schema(
        {
            "task_title": {"type": "string", "minLength": 1, "maxLength": 300},
            "requirement": {"type": "object"},
            "strategy": {"type": "object"},
            "previous_copy": {"type": "object"},
            "revision_instruction": {"type": "string", "minLength": 1},
        },
        [
            "task_title",
            "requirement",
            "strategy",
            "previous_copy",
            "revision_instruction",
        ],
    ),
    output_schema_json=_object_schema(
        {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "body": {"type": "string", "minLength": 1},
            "change_summary": {"type": "string", "minLength": 1},
        },
        ["title", "body", "change_summary"],
    ),
    changelog="初始版本：通用营销文案修订契约",
)

_VIDEO_SCRIPT_SEED = PromptSeed(
    template_key="general_video_script",
    display_name="通用短视频脚本生成",
    task_type="video_script",
    capability="text",
    description="基于已生成的营销文案产出短视频脚本与拍摄指引。",
    system_prompt=(
        "你是本地生活商家短视频编导。基于给定文案与修订意见输出可执行脚本，"
        "不得编造门店事实。输出必须是单个 JSON 对象，不要输出 Markdown 代码块。"
    ),
    user_prompt_template=(
        "营销文案：{{copy}}\n"
        "修订意见（可能为空）：{{revision_instruction}}\n\n"
        "请输出 JSON，字段为：theme（主题，字符串）、spoken_script（口播文案，字符串）、"
        "storyboard（分镜数组，每个元素为字符串）、shooting_guidance（拍摄指引字符串数组）。"
    ),
    variables_schema_json=_object_schema(
        {
            "copy": {"type": "object"},
            "revision_instruction": {"type": "string"},
        },
        ["copy", "revision_instruction"],
    ),
    output_schema_json=_object_schema(
        {
            "theme": {"type": "string", "minLength": 1},
            "spoken_script": {"type": "string", "minLength": 1},
            "storyboard": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "shooting_guidance": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
        },
        ["theme", "spoken_script", "storyboard", "shooting_guidance"],
    ),
    changelog="初始版本：通用短视频脚本契约",
)

_IMAGE_PROMPT_SEED = PromptSeed(
    template_key="general_image_prompt",
    display_name="通用图片提示词生成",
    task_type="image_prompt",
    capability="text",
    description="根据已确认策略生成图片生成提示词与负面提示词。",
    system_prompt=(
        "你是商业视觉提示词设计师。根据策略与门店事实设计可执行的图片提示词，"
        "不得出现真实人物肖像、品牌侵权元素或医疗功效承诺。"
        "提示词中不要要求画面内生成任何文字、招牌文字、水印或 logo，"
        "需要后期排版时只描述留白区域。"
        "输出必须是单个 JSON 对象，不要输出 Markdown 代码块。"
    ),
    user_prompt_template=(
        "任务标题：{{task_title}}\n"
        "已确认策略：{{strategy}}\n"
        "是否有参考图：{{source_asset_available}}\n"
        "参考图信息：{{source_asset}}\n"
        "修订意见（可能为空）：{{revision_instruction}}\n\n"
        "请输出 JSON，字段为：prompt（正向提示词，字符串，不得包含画面内文字或水印要求）、"
        "negative_prompt（负面提示词，字符串，需包含画面文字、水印、logo）、"
        "aspect_ratio（画幅比例，只能是 1:1、4:5、3:4、16:9 或 9:16）。"
    ),
    variables_schema_json=_object_schema(
        {
            "task_title": {"type": "string", "minLength": 1, "maxLength": 300},
            "strategy": {"type": "object"},
            "source_asset_available": {"type": "boolean"},
            "source_asset": {"type": "object"},
            "revision_instruction": {"type": "string"},
        },
        [
            "task_title",
            "strategy",
            "source_asset_available",
            "source_asset",
            "revision_instruction",
        ],
    ),
    output_schema_json=_object_schema(
        {
            "prompt": {"type": "string", "minLength": 1},
            "negative_prompt": {"type": "string"},
            "aspect_ratio": {
                "type": "string",
                "enum": ["1:1", "4:5", "3:4", "16:9", "9:16"],
            },
        },
        ["prompt", "negative_prompt", "aspect_ratio"],
    ),
    changelog="初始版本：通用图片提示词契约",
)

_IMAGE_GENERATION_SEED = PromptSeed(
    template_key="general_image_generation",
    display_name="通用营销图片生成",
    task_type="image_generation",
    capability="image",
    description="根据图片提示词生成营销图片产物。",
    system_prompt=(
        "你是商业摄影与视觉设计生成器。遵循提示词与门店品牌风格，"
        "画面中不要出现不可读的乱码文字或真实个人信息。"
    ),
    user_prompt_template=(
        "画面主题：{{image_prompt}}\n"
        "负面提示词：{{negative_prompt}}\n"
        "画幅比例：{{aspect_ratio}}"
    ),
    variables_schema_json=_object_schema(
        {
            "image_prompt": {"type": "string", "minLength": 1},
            "negative_prompt": {"type": "string"},
            "aspect_ratio": {"type": "string"},
        },
        ["image_prompt", "negative_prompt", "aspect_ratio"],
    ),
    output_schema_json=_object_schema(
        {
            "asset_object_key": {"type": "string", "minLength": 1, "maxLength": 700},
            "sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "mime_type": {
                "type": "string",
                "enum": ["image/png", "image/jpeg", "image/webp"],
            },
            "width": {"type": "integer", "minimum": 1, "maximum": 8192},
            "height": {"type": "integer", "minimum": 1, "maximum": 8192},
        },
        ["asset_object_key", "sha256", "mime_type", "width", "height"],
    ),
    changelog="初始版本：通用营销图片生成契约",
)

_IMAGE_EDIT_SEED = PromptSeed(
    template_key="general_image_edit",
    display_name="通用营销图片改图",
    task_type="image_edit",
    capability="image",
    description="以已有素材为参考生成新的营销图片产物。",
    system_prompt=(
        "你是商业图片改图与重绘引擎。保留参考图的商品主体特征，"
        "按提示词调整构图、光线与背景，不要添加不可读文字。"
    ),
    user_prompt_template=(
        "画面主题：{{image_prompt}}\n"
        "负面提示词：{{negative_prompt}}\n"
        "画幅比例：{{aspect_ratio}}\n"
        "是否有参考图：{{source_asset_available}}\n"
        "参考图信息：{{source_asset}}"
    ),
    variables_schema_json=_object_schema(
        {
            "image_prompt": {"type": "string", "minLength": 1},
            "negative_prompt": {"type": "string"},
            "aspect_ratio": {"type": "string"},
            "source_asset_available": {"type": "boolean"},
            "source_asset": {"type": "object"},
        },
        [
            "image_prompt",
            "negative_prompt",
            "aspect_ratio",
            "source_asset_available",
            "source_asset",
        ],
    ),
    output_schema_json=_object_schema(
        {
            "asset_object_key": {"type": "string", "minLength": 1, "maxLength": 700},
            "sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "mime_type": {
                "type": "string",
                "enum": ["image/png", "image/jpeg", "image/webp"],
            },
            "width": {"type": "integer", "minimum": 1, "maximum": 8192},
            "height": {"type": "integer", "minimum": 1, "maximum": 8192},
        },
        ["asset_object_key", "sha256", "mime_type", "width", "height"],
    ),
    changelog="初始版本：通用营销图片改图契约",
)

_VISUAL_QUALITY_SEED = PromptSeed(
    template_key="general_visual_quality_check",
    display_name="通用图片质检",
    task_type="visual_quality_check",
    capability="vision",
    description="对生成图片做视觉质检并强制人工复核。",
    system_prompt=(
        "你是严格的商业图片质检员。检查画面是否出现乱码文字、畸形主体、"
        "侵权元素、虚假功效或与提示词明显不符的内容。"
        "输出必须是单个 JSON 对象，不要输出 Markdown 代码块。"
    ),
    user_prompt_template=(
        "图片提示词：{{image_prompt}}\n"
        "画幅比例：{{aspect_ratio}}\n"
        "图片尺寸：{{image_width}}x{{image_height}}\n\n"
        "请输出 JSON，字段为：passed（是否通过，布尔值）、"
        "findings（问题数组，每项包含 severity 与 description）、"
        "overall_severity（none/low/medium/high/critical 之一）、"
        "revision_suggestions（修改建议字符串数组）。"
    ),
    variables_schema_json=_object_schema(
        {
            "image_prompt": {"type": "string", "minLength": 1},
            "aspect_ratio": {"type": "string"},
            "image_width": {"type": "integer", "minimum": 1},
            "image_height": {"type": "integer", "minimum": 1},
        },
        ["image_prompt", "aspect_ratio", "image_width", "image_height"],
    ),
    output_schema_json=_object_schema(
        {
            "findings": {"type": "array", "items": {"type": "object"}},
            "overall_severity": {
                "type": "string",
                "enum": ["none", "low", "medium", "high", "critical"],
            },
            "revision_suggestions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "human_review_required": {"type": "boolean", "enum": [True]},
        },
        [
            "findings",
            "overall_severity",
            "revision_suggestions",
            "human_review_required",
        ],
    ),
    changelog="初始版本：通用图片质检契约",
)

PROMPT_SEEDS: tuple[PromptSeed, ...] = (
    _STRATEGY_SEED,
    _COPY_GENERATION_SEED,
    _COPY_REVISION_SEED,
    _VIDEO_SCRIPT_SEED,
    _IMAGE_PROMPT_SEED,
    _IMAGE_GENERATION_SEED,
    _IMAGE_EDIT_SEED,
    _VISUAL_QUALITY_SEED,
)


def _validate_seed(seed: PromptSeed) -> None:
    validate_prompt_task_contract(
        seed.task_type,
        seed.capability,
        dict(seed.output_schema_json),
    )
    properties = seed.variables_schema_json.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"{seed.template_key}: variables schema must declare properties")
    placeholders = {
        match.group(1)
        for match in re.finditer(
            r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", seed.user_prompt_template
        )
    }
    if placeholders != set(properties):
        raise ValueError(
            f"{seed.template_key}: placeholders must match declared variables"
        )


def seed_prompt_templates(
    db: Session,
    *,
    publisher_user_id: UUID,
    industry_key: str = "general",
) -> list[str]:
    """Create or publish seed templates; return a per-template outcome summary."""
    outcomes: list[str] = []
    for seed in PROMPT_SEEDS:
        _validate_seed(seed)
        conflicting = db.scalar(
            select(PromptTemplate).where(
                PromptTemplate.task_type == seed.task_type,
                PromptTemplate.capability == seed.capability,
                PromptTemplate.status == "active",
                PromptTemplate.template_key != seed.template_key,
            )
        )
        if conflicting is not None:
            raise ValueError(
                f"{seed.task_type}/{seed.capability} already has active template "
                f"{conflicting.template_key}; archive it before seeding"
            )
        template = db.scalar(
            select(PromptTemplate)
            .where(
                PromptTemplate.industry_key == industry_key,
                PromptTemplate.task_type == seed.task_type,
                PromptTemplate.capability == seed.capability,
                PromptTemplate.template_key == seed.template_key,
            )
            .with_for_update()
        )
        if template is None:
            template = PromptTemplate(
                template_key=seed.template_key,
                display_name=seed.display_name,
                industry_key=industry_key,
                task_type=seed.task_type,
                capability=seed.capability,
                description=seed.description,
                status="active",
                created_by_user_id=publisher_user_id,
            )
            db.add(template)
            db.flush()
            outcomes.append(f"{seed.template_key}: created template")

        desired = seed.fingerprint()
        versions = db.scalars(
            select(PromptVersion)
            .where(PromptVersion.prompt_template_id == template.id)
            .order_by(PromptVersion.version_no)
        ).all()
        matching = next(
            (
                version
                for version in versions
                if version.status == "published"
                and _version_fingerprint(version) == desired
            ),
            None,
        )
        if (
            matching is not None
            and template.current_published_version_id == matching.id
        ):
            outcomes.append(f"{seed.template_key}: unchanged")
            continue

        if matching is None:
            latest = max((version.version_no for version in versions), default=0)
            version = PromptVersion(
                prompt_template_id=template.id,
                version_no=latest + 1,
                system_prompt=seed.system_prompt,
                user_prompt_template=seed.user_prompt_template,
                variables_schema_json=seed.variables_schema_json,
                output_schema_json=seed.output_schema_json,
                schema_version=1,
                input_policy_json={"confirmed_facts_only": True},
                changelog=seed.changelog,
                status="published",
                created_by_user_id=publisher_user_id,
                published_by_user_id=publisher_user_id,
                published_at=datetime.now(UTC),
            )
            db.add(version)
            db.flush()
            matching = version
            new_version = True
            outcomes.append(
                f"{seed.template_key}: published v{version.version_no}"
            )
        else:
            new_version = False
            outcomes.append(
                f"{seed.template_key}: activated v{matching.version_no}"
            )

        previous_id = template.current_published_version_id
        template.current_published_version_id = matching.id
        if new_version:
            request_hash = hashlib.sha256(
                f"seed:{template.id}:{matching.id}".encode()
            ).hexdigest()
            db.add(
                PromptActivation(
                    prompt_template_id=template.id,
                    activated_version_id=matching.id,
                    previous_version_id=previous_id,
                    action="publish",
                    reason="seed: publish default prompt template",
                    actor_user_id=publisher_user_id,
                    idempotency_key_hash=request_hash,
                    request_hash=request_hash,
                )
            )
        db.flush()
    return outcomes
