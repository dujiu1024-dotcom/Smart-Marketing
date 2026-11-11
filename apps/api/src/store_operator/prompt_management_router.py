from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_platform_admin,
)
from store_operator.auth.errors import ApiError
from store_operator.db import get_db
from store_operator.models.prompt_management import (
    PromptActivation,
    PromptTemplate,
    PromptVersion,
)

router = APIRouter(prefix="/admin/prompt-templates", tags=["platform-admin-prompts"])


class PromptTemplateCreate(BaseModel):
    template_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    industry_key: str = Field(min_length=1, max_length=80)
    task_type: str = Field(min_length=1, max_length=80)
    capability: Literal["text", "image", "vision", "ocr"]
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("template_key", "display_name", "industry_key", "task_type")
    @classmethod
    def trim_required_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace characters")
        return value.strip()


class PromptVersionCreate(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=100_000)
    user_prompt_template: str = Field(min_length=1, max_length=100_000)
    variables_schema_json: dict[str, object]
    output_schema_json: dict[str, object]
    schema_version: int = Field(default=1, ge=1)
    input_policy_json: dict[str, object] = Field(default_factory=dict)
    changelog: str = Field(min_length=1, max_length=4000)

    @field_validator("changelog")
    @classmethod
    def trim_changelog(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("changelog must contain non-whitespace characters")
        return value.strip()


class PromptActivationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must contain non-whitespace characters")
        return value.strip()


def _template_read(template: PromptTemplate) -> dict[str, object]:
    return {
        "id": str(template.id),
        "template_key": template.template_key,
        "display_name": template.display_name,
        "industry_key": template.industry_key,
        "task_type": template.task_type,
        "capability": template.capability,
        "description": template.description,
        "status": template.status,
        "current_published_version_id": (
            str(template.current_published_version_id)
            if template.current_published_version_id
            else None
        ),
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def _version_read(version: PromptVersion) -> dict[str, object]:
    return {
        "id": str(version.id),
        "prompt_template_id": str(version.prompt_template_id),
        "version_no": version.version_no,
        "system_prompt": version.system_prompt,
        "user_prompt_template": version.user_prompt_template,
        "variables_schema_json": version.variables_schema_json,
        "output_schema_json": version.output_schema_json,
        "schema_version": version.schema_version,
        "input_policy_json": version.input_policy_json,
        "changelog": version.changelog,
        "status": version.status,
        "created_by_user_id": (
            str(version.created_by_user_id) if version.created_by_user_id else None
        ),
        "created_at": version.created_at.isoformat(),
        "published_by_user_id": (
            str(version.published_by_user_id) if version.published_by_user_id else None
        ),
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }


def _activation_read(activation: PromptActivation) -> dict[str, object]:
    return {
        "id": str(activation.id),
        "prompt_template_id": str(activation.prompt_template_id),
        "activated_version_id": str(activation.activated_version_id),
        "previous_version_id": (
            str(activation.previous_version_id) if activation.previous_version_id else None
        ),
        "action": activation.action,
        "reason": activation.reason,
        "actor_user_id": str(activation.actor_user_id) if activation.actor_user_id else None,
        "created_at": activation.created_at.isoformat(),
    }


def _validate_prompt_version(version: PromptVersion) -> None:
    schema = version.variables_schema_json
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise ApiError(
            422,
            "PROMPT_VARIABLE_SCHEMA_INVALID",
            "variables_schema_json must be an object schema with properties",
        )
    properties = schema["properties"]
    assert isinstance(properties, dict)
    required = schema.get("required", [])
    if not isinstance(required, list) or any(
        not isinstance(key, str) or key not in properties for key in required
    ):
        raise ApiError(
            422,
            "PROMPT_VARIABLE_SCHEMA_INVALID",
            "required variables must reference declared properties",
        )
    placeholders = set(
        re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", version.user_prompt_template)
    )
    declared = set(properties)
    if placeholders != declared:
        raise ApiError(
            422,
            "PROMPT_PLACEHOLDER_MISMATCH",
            "Prompt placeholders must exactly match the declared variable properties",
        )
    if not isinstance(version.output_schema_json.get("type"), str):
        raise ApiError(
            422,
            "PROMPT_OUTPUT_SCHEMA_INVALID",
            "output_schema_json must declare a JSON Schema type",
        )


def _request_fingerprint(*parts: str) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _idempotency_hash(template_id: UUID, key: str) -> str:
    scoped_key = f"{template_id}:{key}"
    return hashlib.sha256(scoped_key.encode()).hexdigest()


def _existing_activation(
    db: Session, key_hash: str, request_hash: str
) -> PromptActivation | None:
    existing = db.scalar(
        select(PromptActivation).where(
            PromptActivation.idempotency_key_hash == key_hash
        )
    )
    if existing is not None and existing.request_hash != request_hash:
        raise ApiError(
            409,
            "IDEMPOTENCY_KEY_REUSED",
            "Idempotency key was already used for a different prompt activation",
        )
    return existing


@router.get("")
def list_prompt_templates(
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    industry_key: str | None = None,
    task_type: str | None = None,
    capability: str | None = None,
    status: Literal["active", "archived"] | None = None,
) -> list[dict[str, object]]:
    query = select(PromptTemplate).order_by(
        PromptTemplate.industry_key,
        PromptTemplate.task_type,
        PromptTemplate.template_key,
    )
    if industry_key:
        query = query.where(PromptTemplate.industry_key == industry_key)
    if task_type:
        query = query.where(PromptTemplate.task_type == task_type)
    if capability:
        query = query.where(PromptTemplate.capability == capability)
    if status:
        query = query.where(PromptTemplate.status == status)
    return [_template_read(item) for item in db.scalars(query).all()]


@router.post("", status_code=201)
def create_prompt_template(
    payload: PromptTemplateCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    template = PromptTemplate(**payload.model_dump(), created_by_user_id=auth.user.id)
    db.add(template)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409,
            "PROMPT_TEMPLATE_EXISTS",
            "A prompt template with this scope and key already exists",
        ) from exc
    record_audit(
        db,
        request,
        action="prompt.template.created",
        target_type="prompt_template",
        target_id=template.id,
        actor_user_id=auth.user.id,
        actor_type="platform_admin",
        metadata={"template_key": template.template_key, "capability": template.capability},
    )
    db.commit()
    db.refresh(template)
    return _template_read(template)


@router.get("/{template_id}")
def get_prompt_template(
    template_id: UUID,
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    template = db.get(PromptTemplate, template_id)
    if template is None:
        raise ApiError(404, "PROMPT_TEMPLATE_NOT_FOUND", "Prompt template not found")
    versions = db.scalars(
        select(PromptVersion)
        .where(PromptVersion.prompt_template_id == template_id)
        .order_by(PromptVersion.version_no.desc())
    ).all()
    activations = db.scalars(
        select(PromptActivation)
        .where(PromptActivation.prompt_template_id == template_id)
        .order_by(PromptActivation.created_at.desc())
    ).all()
    return {
        **_template_read(template),
        "versions": [_version_read(item) for item in versions],
        "activations": [_activation_read(item) for item in activations],
    }


@router.post("/{template_id}/versions", status_code=201)
def create_prompt_version(
    template_id: UUID,
    payload: PromptVersionCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.id == template_id).with_for_update()
    )
    if template is None:
        raise ApiError(404, "PROMPT_TEMPLATE_NOT_FOUND", "Prompt template not found")
    if template.status != "active":
        raise ApiError(409, "PROMPT_TEMPLATE_ARCHIVED", "Archived prompt templates are read-only")
    latest = db.scalar(
        select(PromptVersion.version_no)
        .where(PromptVersion.prompt_template_id == template_id)
        .order_by(PromptVersion.version_no.desc())
        .limit(1)
    ) or 0
    version = PromptVersion(
        prompt_template_id=template_id,
        version_no=latest + 1,
        **payload.model_dump(),
        created_by_user_id=auth.user.id,
    )
    db.add(version)
    db.flush()
    record_audit(
        db,
        request,
        action="prompt.version.draft_created",
        target_type="prompt_version",
        target_id=version.id,
        actor_user_id=auth.user.id,
        actor_type="platform_admin",
        metadata={"prompt_template_id": str(template_id), "version_no": version.version_no},
    )
    db.commit()
    db.refresh(version)
    return _version_read(version)


@router.post("/{template_id}/versions/{version_id}/publish")
def publish_prompt_version(
    template_id: UUID,
    version_id: UUID,
    payload: PromptActivationRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
) -> dict[str, object]:
    key_hash = _idempotency_hash(template_id, idempotency_key)
    request_hash = _request_fingerprint(
        str(template_id), str(version_id), "publish", payload.reason
    )
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.id == template_id).with_for_update()
    )
    if template is None:
        raise ApiError(404, "PROMPT_TEMPLATE_NOT_FOUND", "Prompt template not found")
    replay = _existing_activation(db, key_hash, request_hash)
    if replay is not None:
        return _activation_read(replay)
    version = db.scalar(
        select(PromptVersion)
        .where(
            PromptVersion.id == version_id,
            PromptVersion.prompt_template_id == template_id,
        )
        .with_for_update()
    )
    if version is None:
        raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "Prompt version not found")
    if template.status != "active" or version.status != "draft":
        raise ApiError(
            409,
            "PROMPT_VERSION_NOT_DRAFT",
            "Only active templates and draft versions can be published",
        )
    _validate_prompt_version(version)
    previous_id = template.current_published_version_id
    now = datetime.now(UTC)
    version.status = "published"
    version.published_by_user_id = auth.user.id
    version.published_at = now
    db.flush()
    template.current_published_version_id = version.id
    activation = PromptActivation(
        prompt_template_id=template_id,
        activated_version_id=version.id,
        previous_version_id=previous_id,
        action="publish",
        reason=payload.reason,
        actor_user_id=auth.user.id,
        idempotency_key_hash=key_hash,
        request_hash=request_hash,
    )
    db.add(activation)
    record_audit(
        db,
        request,
        action="prompt.version.published",
        target_type="prompt_version",
        target_id=version.id,
        actor_user_id=auth.user.id,
        actor_type="platform_admin",
        metadata={
            "prompt_template_id": str(template_id),
            "previous_version_id": str(previous_id) if previous_id else None,
        },
    )
    db.commit()
    db.refresh(activation)
    return _activation_read(activation)


@router.post("/{template_id}/rollback/{version_id}")
def rollback_prompt_version(
    template_id: UUID,
    version_id: UUID,
    payload: PromptActivationRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    _admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    key_hash = _idempotency_hash(template_id, idempotency_key)
    request_hash = _request_fingerprint(
        str(template_id), str(version_id), "rollback", payload.reason
    )
    template = db.scalar(
        select(PromptTemplate).where(PromptTemplate.id == template_id).with_for_update()
    )
    if template is None:
        raise ApiError(404, "PROMPT_TEMPLATE_NOT_FOUND", "Prompt template not found")
    replay = _existing_activation(db, key_hash, request_hash)
    if replay is not None:
        return _activation_read(replay)
    target = db.scalar(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.prompt_template_id == template_id,
            PromptVersion.status == "published",
        )
    )
    if target is None:
        raise ApiError(404, "PROMPT_VERSION_NOT_FOUND", "Published prompt version not found")
    previous_id = template.current_published_version_id
    if previous_id == target.id:
        raise ApiError(409, "PROMPT_VERSION_ALREADY_ACTIVE", "Prompt version is already active")
    template.current_published_version_id = target.id
    activation = PromptActivation(
        prompt_template_id=template_id,
        activated_version_id=target.id,
        previous_version_id=previous_id,
        action="rollback",
        reason=payload.reason,
        actor_user_id=auth.user.id,
        idempotency_key_hash=key_hash,
        request_hash=request_hash,
    )
    db.add(activation)
    record_audit(
        db,
        request,
        action="prompt.version.rolled_back",
        target_type="prompt_version",
        target_id=target.id,
        actor_user_id=auth.user.id,
        actor_type="platform_admin",
        metadata={
            "prompt_template_id": str(template_id),
            "previous_version_id": str(previous_id) if previous_id else None,
        },
    )
    db.commit()
    db.refresh(activation)
    return _activation_read(activation)
