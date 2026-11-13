from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.config import settings
from store_operator.db import get_db
from store_operator.domain.marketing_task import (
    InvalidTaskStepTransition,
    StepApplicability,
    TaskStepStatus,
    ensure_step_transition,
)
from store_operator.idempotency import begin_idempotency, complete_idempotency
from store_operator.jobs.service import JobIdempotencyConflict, create_job
from store_operator.models.content_delivery import Artifact, ArtifactVersion, ReviewRecord
from store_operator.models.job_runtime import OutboxEvent
from store_operator.models.marketing_task import (
    MarketingTask,
    RequirementSnapshot,
    StrategySnapshot,
    TaskEvent,
    TaskStep,
)
from store_operator.models.store_knowledge import MediaAsset
from store_operator.object_storage import (
    ObjectStorageNotConfigured,
    create_download_url,
)

router = APIRouter(prefix="/marketing-tasks", tags=["content-delivery"])


class ArtifactVersionInput(BaseModel):
    source_type: Literal["ai_generated", "merchant_upload", "manual_edit"]
    source_refs: list[dict[str, object]] = Field(default_factory=list, max_length=50)
    instruction: str | None = Field(default=None, max_length=10000)
    content_json: dict[str, object] | None = None
    media_asset_id: UUID | None = None
    provider_id: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=160)
    prompt_version_id: UUID | None = None

    @model_validator(mode="after")
    def require_content_reference(self) -> ArtifactVersionInput:
        if self.content_json is None and self.media_asset_id is None:
            raise ValueError("content_json or media_asset_id is required")
        if self.content_json is not None and self.media_asset_id is not None:
            raise ValueError("content_json and media_asset_id are mutually exclusive")
        if self.source_type == "ai_generated" and (
            not self.provider_id or not self.model_id
        ):
            raise ValueError("AI-generated versions require provider_id and model_id")
        return self


class ArtifactCreate(BaseModel):
    artifact_type: Literal["copy", "image"]
    version: ArtifactVersionInput


class ArtifactVersionCreate(ArtifactVersionInput):
    expected_version: int = Field(ge=1)


class ReviewCreate(BaseModel):
    expected_version: int = Field(ge=1)
    review_type: Literal["copy", "image"]
    decision: Literal["approved", "revision_requested", "rejected"]
    comment: str | None = Field(default=None, max_length=10000)
    target: dict[str, object] | None = None

    @model_validator(mode="after")
    def require_revision_comment(self) -> ReviewCreate:
        if self.decision == "revision_requested" and not (
            self.comment and self.comment.strip()
        ):
            raise ValueError("revision_requested requires a non-empty comment")
        return self


def _version_payload(
    version: ArtifactVersion,
    reviews: list[ReviewRecord] | None = None,
) -> dict[str, object]:
    return {
        "id": str(version.id),
        "artifact_id": str(version.artifact_id),
        "version_no": version.version_no,
        "source_type": version.source_type,
        "source_refs": version.source_refs_json,
        "instruction": version.instruction,
        "content_json": version.content_json,
        "content_hash": version.content_hash,
        "provider_id": version.provider_id,
        "model_id": version.model_id,
        "prompt_version_id": (
            str(version.prompt_version_id) if version.prompt_version_id else None
        ),
        "input_fingerprint": version.input_fingerprint,
        "created_at": version.created_at.isoformat(),
        "reviews": [
            {
                "id": str(review.id),
                "review_type": review.review_type,
                "decision": review.decision,
                "comment": review.comment,
                "target": review.target_json,
                "created_at": review.created_at.isoformat(),
            }
            for review in reviews or []
            if review.artifact_version_id == version.id
        ],
    }


def _artifact_payload(
    artifact: Artifact,
    versions: list[ArtifactVersion] | None = None,
    reviews: list[ReviewRecord] | None = None,
) -> dict[str, object]:
    return {
        "id": str(artifact.id),
        "task_id": str(artifact.task_id),
        "artifact_type": artifact.artifact_type,
        "current_version_id": (
            str(artifact.current_version_id) if artifact.current_version_id else None
        ),
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "versions": [_version_payload(item, reviews) for item in versions or []],
    }




def _enqueue_content_event(
    db: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    store_id: UUID,
    task_id: UUID,
    artifact_id: UUID,
    artifact_version_id: UUID | None = None,
    review_id: UUID | None = None,
    decision: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "store_id": str(store_id),
        "task_id": str(task_id),
        "artifact_id": str(artifact_id),
    }
    if artifact_version_id is not None:
        payload["artifact_version_id"] = str(artifact_version_id)
    if review_id is not None:
        payload["review_id"] = str(review_id)
    if decision is not None:
        payload["decision"] = decision
    db.add(
        OutboxEvent(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            schema_version=1,
            payload_json=payload,
            dedupe_key=f"{event_type}:{aggregate_id}",
        )
    )


def _new_version(
    db: Session,
    *,
    store_id: UUID,
    artifact_id: UUID,
    artifact_type: str,
    task_version: int,
    requirement_snapshot_id: UUID | None,
    strategy_snapshot_id: UUID | None,
    version_no: int,
    payload: ArtifactVersionInput,
    actor_user_id: UUID,
) -> ArtifactVersion:
    content_ref = None
    source_refs = list(payload.source_refs)
    if payload.media_asset_id is not None:
        asset = db.scalar(
            select(MediaAsset).where(
                MediaAsset.id == payload.media_asset_id,
                MediaAsset.store_id == store_id,
            )
        )
        if (
            asset is None
            or asset.status != "ready"
            or asset.usage_rights_status != "confirmed_allowed"
            or (artifact_type == "image" and not asset.mime_type.startswith("image/"))
        ):
            raise ApiError(
                422,
                "MEDIA_ASSET_NOT_USABLE",
                "Media asset must belong to this store, be ready, and have confirmed usage rights",
            )
        content_ref = asset.object_key
        content_hash = asset.sha256
        source_refs.append({"type": "media_asset", "id": str(asset.id)})
    else:
        canonical = json.dumps(
            payload.content_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        content_hash = hashlib.sha256(canonical).hexdigest()
    fingerprint_payload = {
        "artifact_id": str(artifact_id),
        "artifact_type": artifact_type,
        "task_version": task_version,
        "requirement_snapshot_id": (
            str(requirement_snapshot_id) if requirement_snapshot_id else None
        ),
        "strategy_snapshot_id": (
            str(strategy_snapshot_id) if strategy_snapshot_id else None
        ),
        "source_type": payload.source_type,
        "source_refs": source_refs,
        "instruction": payload.instruction,
        "content_hash": content_hash,
        "provider_id": payload.provider_id,
        "model_id": payload.model_id,
        "prompt_version_id": (
            str(payload.prompt_version_id) if payload.prompt_version_id else None
        ),
    }
    input_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ArtifactVersion(
        id=uuid4(),
        store_id=store_id,
        artifact_id=artifact_id,
        version_no=version_no,
        source_type=payload.source_type,
        source_refs_json=source_refs,
        instruction=payload.instruction,
        content_json=payload.content_json,
        content_ref=content_ref,
        content_hash=content_hash,
        provider_id=payload.provider_id,
        model_id=payload.model_id,
        prompt_version_id=payload.prompt_version_id,
        input_fingerprint=input_fingerprint,
        created_by_user_id=actor_user_id,
    )


@router.post("/{task_id}/artifacts", status_code=201)
def create_artifact(
    task_id: UUID,
    payload: ArtifactCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    idempotency, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="content.artifact.create",
        payload=payload,
    )
    if replay is not None:
        return replay
    task = db.scalar(
        select(MarketingTask)
        .where(
            MarketingTask.id == task_id,
            MarketingTask.store_id == store_id,
        )
        .with_for_update()
    )
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", "Marketing task not found")
    artifact = Artifact(
        id=uuid4(),
        store_id=store_id,
        task_id=task.id,
        artifact_type=payload.artifact_type,
    )
    db.add(artifact)
    db.flush()
    if payload.artifact_type == "copy" and payload.version.content_json is None:
        raise ApiError(422, "COPY_CONTENT_REQUIRED", "Copy artifacts require content_json")
    if payload.artifact_type == "image" and payload.version.media_asset_id is None:
        raise ApiError(422, "IMAGE_ASSET_REQUIRED", "Image artifacts require a ready media asset")
    version = _new_version(
        db,
        store_id=store_id,
        artifact_id=artifact.id,
        artifact_type=artifact.artifact_type,
        task_version=task.version,
        requirement_snapshot_id=task.current_requirement_snapshot_id,
        strategy_snapshot_id=task.current_strategy_snapshot_id,
        version_no=1,
        payload=payload.version,
        actor_user_id=auth.user.id,
    )
    db.add(version)
    db.flush()
    artifact.current_version_id = version.id
    response = _artifact_payload(artifact, [version])
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="artifact",
        resource_id=artifact.id,
    )
    _enqueue_content_event(
        db,
        event_type="content.artifact_version_created",
        aggregate_type="artifact_version",
        aggregate_id=version.id,
        store_id=store_id,
        task_id=task_id,
        artifact_id=artifact.id,
        artifact_version_id=version.id,
    )
    record_audit(
        db,
        request,
        action="content.artifact.created",
        target_type="artifact",
        target_id=artifact.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={"task_id": str(task_id), "artifact_type": artifact.artifact_type},
    )
    db.commit()
    return response


@router.get("/{task_id}/artifacts")
def list_task_artifacts(
    task_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, object]]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    task = db.scalar(
        select(MarketingTask.id).where(
            MarketingTask.id == task_id,
            MarketingTask.store_id == store_id,
        )
    )
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", "Marketing task not found")
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.store_id == store_id, Artifact.task_id == task_id)
        .order_by(Artifact.created_at, Artifact.id)
    ).all()
    result: list[dict[str, object]] = []
    for artifact in artifacts:
        versions = db.scalars(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.store_id == store_id,
                ArtifactVersion.artifact_id == artifact.id,
            )
            .order_by(ArtifactVersion.version_no)
        ).all()
        version_ids = [item.id for item in versions]
        reviews = (
            list(
                db.scalars(
                    select(ReviewRecord)
                    .where(
                        ReviewRecord.store_id == store_id,
                        ReviewRecord.artifact_version_id.in_(version_ids),
                    )
                    .order_by(ReviewRecord.created_at, ReviewRecord.id)
                ).all()
            )
            if version_ids
            else []
        )
        result.append(_artifact_payload(artifact, list(versions), reviews))
    return result


_IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
_EXTENSION_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _safe_download_stem(value: str) -> str:
    cleaned = "".join(char for char in value if char.isalnum() or char in "-_ ")
    return "_".join(cleaned.split())[:80] or "artifact"


@router.get("/{task_id}/artifacts/{artifact_id}/versions/{version_id}/download-url")
def get_artifact_version_download_url(
    task_id: UUID,
    artifact_id: UUID,
    version_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Issue a short-lived read-only URL for a specific artifact version file."""
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    task = db.scalar(
        select(MarketingTask).where(
            MarketingTask.id == task_id,
            MarketingTask.store_id == store_id,
        )
    )
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", "Marketing task not found")
    artifact = db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.task_id == task_id,
            Artifact.store_id == store_id,
        )
    )
    if artifact is None:
        raise ApiError(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
    version = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.id == version_id,
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.store_id == store_id,
        )
    )
    if version is None:
        raise ApiError(404, "ARTIFACT_VERSION_NOT_FOUND", "Artifact version not found")
    object_key = version.content_ref
    mime_type = None
    if isinstance(version.content_json, dict):
        stored_mime = version.content_json.get("mime_type")
        if isinstance(stored_mime, str) and stored_mime:
            mime_type = stored_mime
    for reference in version.source_refs_json or []:
        if reference.get("type") != "media_asset":
            continue
        asset_id = reference.get("id")
        if not isinstance(asset_id, str):
            continue
        try:
            parsed_asset_id = UUID(asset_id)
        except ValueError:
            continue
        asset = db.scalar(
            select(MediaAsset).where(
                MediaAsset.id == parsed_asset_id,
                MediaAsset.store_id == store_id,
            )
        )
        if asset is not None:
            object_key = object_key or asset.object_key
            mime_type = mime_type or asset.mime_type
            break
    if not object_key:
        raise ApiError(
            404,
            "ARTIFACT_FILE_NOT_FOUND",
            "This artifact version has no downloadable file",
        )
    try:
        url = create_download_url(object_key=object_key)
    except ObjectStorageNotConfigured as exc:
        raise ApiError(
            503,
            "OBJECT_STORAGE_UNAVAILABLE",
            "Private object storage is not configured",
        ) from exc
    extension = ""
    if "." in object_key.rsplit("/", 1)[-1]:
        extension = object_key.rsplit(".", 1)[-1].lower()
    mime_type = mime_type or _EXTENSION_MIME.get(extension)
    extension = _IMAGE_EXTENSIONS.get(mime_type or "", extension) or "png"
    filename = (
        f"{_safe_download_stem(task.title)}-"
        f"{artifact.artifact_type}-V{version.version_no}.{extension}"
    )
    return {
        "url": url,
        "filename": filename,
        "mime_type": mime_type or "application/octet-stream",
        "expires_in": str(settings.object_storage_download_ttl_seconds),
    }


@router.post("/{task_id}/artifacts/{artifact_id}/versions", status_code=201)
def create_artifact_version(
    task_id: UUID,
    artifact_id: UUID,
    payload: ArtifactVersionCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    idempotency, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="content.artifact_version.create",
        payload=payload,
    )
    if replay is not None:
        return replay
    task = db.scalar(
        select(MarketingTask)
        .where(
            MarketingTask.id == task_id,
            MarketingTask.store_id == store_id,
        )
        .with_for_update()
    )
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", "Marketing task not found")
    artifact = db.scalar(
        select(Artifact)
        .where(
            Artifact.id == artifact_id,
            Artifact.task_id == task_id,
            Artifact.store_id == store_id,
        )
        .with_for_update()
    )
    if artifact is None:
        raise ApiError(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
    current = db.scalar(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.store_id == store_id,
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.id == artifact.current_version_id,
        )
    )
    current_version = current.version_no if current is not None else 0
    if current_version != payload.expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "Artifact version has changed")
    version_no = (
        db.scalar(
            select(func.max(ArtifactVersion.version_no)).where(
                ArtifactVersion.store_id == store_id,
                ArtifactVersion.artifact_id == artifact_id,
            )
        )
        or 0
    ) + 1
    if artifact.artifact_type == "copy" and payload.content_json is None:
        raise ApiError(422, "COPY_CONTENT_REQUIRED", "Copy artifacts require content_json")
    if artifact.artifact_type == "image" and payload.media_asset_id is None:
        raise ApiError(422, "IMAGE_ASSET_REQUIRED", "Image artifacts require a ready media asset")
    version = _new_version(
        db,
        store_id=store_id,
        artifact_id=artifact_id,
        artifact_type=artifact.artifact_type,
        task_version=task.version,
        requirement_snapshot_id=task.current_requirement_snapshot_id,
        strategy_snapshot_id=task.current_strategy_snapshot_id,
        version_no=version_no,
        payload=payload,
        actor_user_id=auth.user.id,
    )
    db.add(version)
    db.flush()
    artifact.current_version_id = version.id
    response = _version_payload(version)
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="artifact_version",
        resource_id=version.id,
    )
    _enqueue_content_event(
        db,
        event_type="content.artifact_version_created",
        aggregate_type="artifact_version",
        aggregate_id=version.id,
        store_id=store_id,
        task_id=task_id,
        artifact_id=artifact.id,
        artifact_version_id=version.id,
    )
    record_audit(
        db,
        request,
        action="content.artifact_version.created",
        target_type="artifact_version",
        target_id=version.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={"artifact_id": str(artifact_id), "version_no": version_no},
    )
    db.commit()
    return response


_REVIEW_STEP_KEYS = {
    "copy": "copy_production_review",
    "image": "image_production_review",
}


def _advance_review_step_after_approval(
    db: Session,
    *,
    store_id: UUID,
    task_id: UUID,
    artifact: Artifact,
    artifact_version: ArtifactVersion,
    actor_user_id: UUID,
) -> None:
    """Complete the matching production step once its current version is approved."""
    step_key = _REVIEW_STEP_KEYS.get(artifact.artifact_type)
    if step_key is None:
        return
    task = db.scalar(
        select(MarketingTask)
        .where(MarketingTask.id == task_id, MarketingTask.store_id == store_id)
        .with_for_update()
    )
    if task is None:
        return
    step = db.scalar(
        select(TaskStep)
        .where(
            TaskStep.store_id == store_id,
            TaskStep.task_id == task_id,
            TaskStep.step_key == step_key,
        )
        .with_for_update()
    )
    if step is None:
        return
    applicability = StepApplicability(step.applicability)
    if applicability is StepApplicability.NOT_APPLICABLE:
        return
    current = TaskStepStatus(step.status)
    if current is TaskStepStatus.SUCCEEDED or current is TaskStepStatus.SKIPPED:
        return
    # A running step belongs to an in-flight Worker job; that job owns the transition.
    if current is TaskStepStatus.RUNNING:
        return
    chain: tuple[TaskStepStatus, ...]
    if current is TaskStepStatus.PENDING:
        chain = (TaskStepStatus.RUNNING, TaskStepStatus.SUCCEEDED)
    elif current is TaskStepStatus.WAITING_FOR_USER:
        chain = (TaskStepStatus.RUNNING, TaskStepStatus.SUCCEEDED)
    elif current is TaskStepStatus.FAILED:
        chain = (TaskStepStatus.RUNNING, TaskStepStatus.SUCCEEDED)
    elif current is TaskStepStatus.STALE:
        chain = (
            TaskStepStatus.PENDING,
            TaskStepStatus.RUNNING,
            TaskStepStatus.SUCCEEDED,
        )
    else:
        return
    try:
        for target in chain:
            ensure_step_transition(
                current,
                target,
                applicability=applicability,
            )
            current = target
    except InvalidTaskStepTransition:
        return

    now = datetime.now(UTC)
    step.status = TaskStepStatus.SUCCEEDED.value
    step.version += 1
    step.started_at = step.started_at or now
    step.finished_at = now
    step.output_refs_json = [
        ref
        for ref in (step.output_refs_json or [])
        if not (
            isinstance(ref, dict)
            and ref.get("type") == "artifact_version"
            and ref.get("artifact_version_id") == str(artifact_version.id)
        )
    ] + [
        {
            "type": "artifact_version",
            "artifact_id": str(artifact.id),
            "artifact_version_id": str(artifact_version.id),
        }
    ]
    step.blocked_by_json = []
    step.block_code = None
    step.block_detail_json = None
    step.skip_reason = None
    if task.lifecycle_status in {"blocked", "waiting_for_user"}:
        task.lifecycle_status = "active"
    task.version += 1
    db.add(
        TaskEvent(
            id=uuid4(),
            store_id=store_id,
            task_id=task_id,
            event_type="task_step.completed",
            aggregate_version=task.version,
            actor_type="user",
            actor_user_id=actor_user_id,
            payload_json={
                "step_key": step_key,
                "artifact_id": str(artifact.id),
                "artifact_version_id": str(artifact_version.id),
                "source": "merchant_review",
            },
        )
    )


def _dispatch_image_revision_job(
    db: Session,
    *,
    store_id: UUID,
    task_id: UUID,
    artifact_version: ArtifactVersion,
    instruction: str,
    actor_user_id: UUID,
) -> UUID:
    """Move the image step back to running and enqueue a real regeneration job."""
    task = db.scalar(
        select(MarketingTask)
        .where(MarketingTask.id == task_id, MarketingTask.store_id == store_id)
        .with_for_update()
    )
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", "Marketing task not found")
    if (
        task.current_requirement_snapshot_id is None
        or task.current_strategy_snapshot_id is None
    ):
        raise ApiError(
            409,
            "IMAGE_REVISION_SNAPSHOTS_REQUIRED",
            "请先确认需求与策略，再要求修改图片",
        )
    requirement = db.scalar(
        select(RequirementSnapshot).where(
            RequirementSnapshot.id == task.current_requirement_snapshot_id,
            RequirementSnapshot.store_id == store_id,
            RequirementSnapshot.task_id == task.id,
        )
    )
    strategy = db.scalar(
        select(StrategySnapshot).where(
            StrategySnapshot.id == task.current_strategy_snapshot_id,
            StrategySnapshot.store_id == store_id,
            StrategySnapshot.task_id == task.id,
        )
    )
    if requirement is None or strategy is None:
        raise ApiError(
            409,
            "IMAGE_REVISION_SNAPSHOT_UNAVAILABLE",
            "当前确认的需求或策略快照不可用，请重新确认后再试",
        )
    step = db.scalar(
        select(TaskStep)
        .where(
            TaskStep.store_id == store_id,
            TaskStep.task_id == task_id,
            TaskStep.step_key == "image_production_review",
        )
        .with_for_update()
    )
    if step is None:
        raise ApiError(404, "IMAGE_STEP_NOT_FOUND", "Image production step not found")
    applicability = StepApplicability(step.applicability)
    if applicability is StepApplicability.NOT_APPLICABLE:
        raise ApiError(
            409,
            "IMAGE_REVISION_NOT_APPLICABLE",
            "该任务未包含图片制作，无法要求修改图片",
        )
    current = TaskStepStatus(step.status)
    if current is TaskStepStatus.RUNNING:
        raise ApiError(
            409,
            "IMAGE_REVISION_IN_FLIGHT",
            "图片正在重新生成，请等待完成后再操作",
        )
    if current in {TaskStepStatus.SUCCEEDED, TaskStepStatus.SKIPPED}:
        raise ApiError(
            409,
            "IMAGE_REVISION_STEP_CLOSED",
            "图片步骤已完成，不能再次要求修改",
        )
    chain: tuple[TaskStepStatus, ...]
    if current in {TaskStepStatus.PENDING, TaskStepStatus.WAITING_FOR_USER}:
        chain = (TaskStepStatus.RUNNING,)
    elif current is TaskStepStatus.FAILED:
        chain = (TaskStepStatus.RUNNING,)
    elif current is TaskStepStatus.STALE:
        chain = (TaskStepStatus.PENDING, TaskStepStatus.RUNNING)
    else:
        raise ApiError(
            409,
            "IMAGE_REVISION_STATE_CONFLICT",
            "当前步骤状态不支持要求修改，请刷新后重试",
        )
    try:
        for target in chain:
            ensure_step_transition(
                current,
                target,
                applicability=applicability,
            )
            current = target
    except InvalidTaskStepTransition as exc:
        raise ApiError(
            409,
            "IMAGE_REVISION_STATE_CONFLICT",
            "当前步骤状态不支持要求修改，请刷新后重试",
        ) from exc

    now = datetime.now(UTC)
    step.status = TaskStepStatus.RUNNING.value
    step.version += 1
    step.started_at = now
    step.finished_at = None
    step.input_fingerprint = strategy.content_fingerprint
    step.blocked_by_json = []
    step.block_code = None
    step.block_detail_json = None
    step.skip_reason = None
    if task.lifecycle_status in {"draft", "active", "waiting_for_user", "blocked"}:
        task.lifecycle_status = "active"
    task.version += 1
    db.add(
        TaskEvent(
            id=uuid4(),
            store_id=store_id,
            task_id=task_id,
            event_type="task_step.revision_requested",
            aggregate_version=task.version,
            actor_type="user",
            actor_user_id=actor_user_id,
            payload_json={
                "step_key": "image_production_review",
                "artifact_version_id": str(artifact_version.id),
                "instruction": " ".join(instruction.split())[:500],
            },
        )
    )
    source_asset_id = next(
        (
            str(ref["id"])
            for ref in (artifact_version.source_refs_json or [])
            if isinstance(ref, dict)
            and ref.get("type") == "source_media_asset"
            and isinstance(ref.get("id"), str)
        ),
        None,
    )
    job_payload: dict[str, object] = {
        "schema_version": 1,
        "marketing_task_id": str(task.id),
        "requirement_snapshot_id": str(requirement.id),
        "strategy_snapshot_id": str(strategy.id),
        "step_key": "image_production_review",
        "strategy_fingerprint": strategy.content_fingerprint,
        "revision_instruction": instruction,
    }
    if source_asset_id is not None:
        job_payload["source_media_asset_id"] = source_asset_id
    try:
        job = create_job(
            db,
            job_type="marketing_task.generate_image",
            payload_ref=job_payload,
            idempotency_key=(
                f"marketing-task:{task.id}:image-revision:{artifact_version.id}"
            ),
            store_id=store_id,
            actor_type="user",
            actor_user_id=actor_user_id,
            marketing_task_id=task.id,
            max_attempts=3,
            timeout_seconds=900,
        )
    except JobIdempotencyConflict as exc:
        raise ApiError(
            409,
            "IMAGE_REVISION_JOB_CONFLICT",
            "该图片版本已提交过修改，请刷新后查看最新状态",
        ) from exc
    return job.id


@router.post("/{task_id}/artifacts/{artifact_id}/versions/{version_id}/reviews", status_code=201)
def create_review_record(
    task_id: UUID,
    artifact_id: UUID,
    version_id: UUID,
    payload: ReviewCreate,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    store_id = context.request_store_id
    if store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    idempotency, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="content.review.create",
        payload=payload,
    )
    if replay is not None:
        return replay
    artifact = db.scalar(
        select(Artifact)
        .where(
            Artifact.id == artifact_id,
            Artifact.task_id == task_id,
            Artifact.store_id == store_id,
        )
        .with_for_update()
    )
    if artifact is None:
        raise ApiError(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
    version = db.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.id == version_id,
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.store_id == store_id,
        )
    )
    if version is None:
        raise ApiError(404, "ARTIFACT_VERSION_NOT_FOUND", "Artifact version not found")
    if payload.review_type != artifact.artifact_type:
        raise ApiError(
            422,
            "REVIEW_TYPE_MISMATCH",
            "Review type must match the artifact type",
        )
    if version.version_no != payload.expected_version:
        raise ApiError(
            409,
            "VERSION_CONFLICT",
            "Expected artifact version does not match the reviewed version",
        )
    if version.id != artifact.current_version_id:
        raise ApiError(
            409,
            "STALE_ARTIFACT_VERSION",
            "Only the current artifact version can be reviewed",
        )
    if (
        artifact.artifact_type == "image"
        and version.source_type == "ai_generated"
        and payload.decision == "approved"
    ):
        image_content = dict(version.content_json or {})
        vision_inspection = image_content.get("vision_inspection")
        vision_report = (
            vision_inspection.get("report")
            if isinstance(vision_inspection, dict)
            else None
        )
        if (
            not isinstance(vision_inspection, dict)
            or vision_inspection.get("passed") is not True
            or not isinstance(vision_report, dict)
            or vision_report.get("human_review_required") is not True
        ):
            raise ApiError(
                409,
                "VISION_INSPECTION_REQUIRED",
                (
                    "AI 生成的图片需先通过视觉质检才能审核通过"
                    "（错误码：VISION_INSPECTION_REQUIRED）"
                ),
            )
    latest = db.scalar(
        select(ReviewRecord)
        .where(
            ReviewRecord.store_id == store_id,
            ReviewRecord.artifact_version_id == version_id,
        )
        .order_by(ReviewRecord.created_at.desc())
        .limit(1)
    )
    if latest is not None:
        raise ApiError(
            409,
            "ARTIFACT_VERSION_ALREADY_REVIEWED",
            "A review already exists for this artifact version",
        )
    review = ReviewRecord(
        id=uuid4(),
        store_id=store_id,
        artifact_id=artifact_id,
        artifact_version_id=version_id,
        review_type=payload.review_type,
        decision=payload.decision,
        comment=payload.comment.strip() if payload.comment else None,
        target_json=payload.target,
        reviewer_user_id=auth.user.id,
    )
    db.add(review)
    db.flush()
    image_revision_job_id: str | None = None
    if payload.decision == "approved":
        _advance_review_step_after_approval(
            db,
            store_id=store_id,
            task_id=task_id,
            artifact=artifact,
            artifact_version=version,
            actor_user_id=auth.user.id,
        )
    elif (
        payload.decision == "revision_requested"
        and artifact.artifact_type == "image"
    ):
        image_revision_job_id = str(
            _dispatch_image_revision_job(
                db,
                store_id=store_id,
                task_id=task_id,
                artifact_version=version,
                instruction=review.comment or "请按审核意见调整画面",
                actor_user_id=auth.user.id,
            )
        )
    response: dict[str, object] = {
        "id": str(review.id),
        "artifact_id": str(artifact_id),
        "artifact_version_id": str(version_id),
        "review_type": review.review_type,
        "decision": review.decision,
        "comment": review.comment,
        "target": review.target_json,
        "created_at": review.created_at.isoformat(),
        "image_revision_job_id": image_revision_job_id,
    }
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="review_record",
        resource_id=review.id,
    )
    _enqueue_content_event(
        db,
        event_type="content.review_recorded",
        aggregate_type="review_record",
        aggregate_id=review.id,
        store_id=store_id,
        task_id=task_id,
        artifact_id=artifact_id,
        artifact_version_id=version_id,
        review_id=review.id,
        decision=review.decision,
    )
    record_audit(
        db,
        request,
        action="content.review.recorded",
        target_type="review_record",
        target_id=review.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "artifact_id": str(artifact_id),
            "artifact_version_id": str(version_id),
            "decision": review.decision,
        },
    )
    db.commit()
    return response
