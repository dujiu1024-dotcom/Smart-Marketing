from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.db import get_db
from store_operator.idempotency import begin_idempotency, complete_idempotency
from store_operator.models.content_delivery import (
    Artifact,
    ArtifactVersion,
    ChannelContent,
    ChannelContentArtifactRef,
    QualityReport,
    ReviewRecord,
)
from store_operator.models.marketing_task import MarketingTask

router = APIRouter(prefix="/marketing-tasks", tags=["content-quality"])


class ChannelContentCreate(BaseModel):
    channel_key: str = Field(min_length=1, max_length=80)
    copy_version_id: UUID
    channel_spec_version_id: UUID
    payload: dict[str, object]
    image_version_ids: list[UUID] = Field(default_factory=list, max_length=20)


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _content_payload(
    content: ChannelContent,
    refs: list[ChannelContentArtifactRef],
    reports: list[QualityReport],
) -> dict[str, object]:
    return {
        "id": str(content.id),
        "task_id": str(content.task_id),
        "channel_key": content.channel_key,
        "copy_version_id": str(content.copy_version_id),
        "channel_spec_version_id": str(content.channel_spec_version_id),
        "payload": content.payload_json,
        "input_fingerprint": content.input_fingerprint,
        "status": content.status,
        "image_version_ids": [str(item.artifact_version_id) for item in refs],
        "quality_reports": [
            {
                "id": str(item.id),
                "rule_version": item.rule_version,
                "input_fingerprint": item.input_fingerprint,
                "result": item.result,
                "issues": item.issues_json,
                "created_at": item.created_at.isoformat(),
            }
            for item in reports
        ],
        "created_at": content.created_at.isoformat(),
        "updated_at": content.updated_at.isoformat(),
    }


@router.post("/{task_id}/channel-contents", status_code=201)
def create_channel_content(
    task_id: UUID,
    payload: ChannelContentCreate,
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
        operation="content.channel_content.create",
        payload=payload,
    )
    if replay is not None:
        return replay

    task = db.scalar(
        select(MarketingTask)
        .where(MarketingTask.id == task_id, MarketingTask.store_id == store_id)
        .with_for_update()
    )
    if task is None:
        raise ApiError(404, "TASK_NOT_FOUND", "Marketing task not found")

    copy_version = db.scalar(
        select(ArtifactVersion)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(
            ArtifactVersion.id == payload.copy_version_id,
            ArtifactVersion.store_id == store_id,
            ArtifactVersion.artifact_id == Artifact.id,
            Artifact.store_id == store_id,
            Artifact.task_id == task_id,
            Artifact.artifact_type == "copy",
            Artifact.current_version_id == ArtifactVersion.id,
        )
    )
    if copy_version is None:
        raise ApiError(404, "COPY_VERSION_NOT_FOUND", "Current copy version not found")
    approved_copy = db.scalar(
        select(ReviewRecord.id).where(
            ReviewRecord.store_id == store_id,
            ReviewRecord.artifact_id == copy_version.artifact_id,
            ReviewRecord.artifact_version_id == copy_version.id,
            ReviewRecord.review_type == "copy",
            ReviewRecord.decision == "approved",
        )
    )
    if approved_copy is None:
        raise ApiError(
            409, "COPY_REVIEW_REQUIRED", "Channel content requires an approved copy version"
        )

    image_versions: list[ArtifactVersion] = []
    seen_images: set[UUID] = set()
    for image_version_id in payload.image_version_ids:
        if image_version_id in seen_images:
            raise ApiError(422, "DUPLICATE_IMAGE_VERSION", "Image versions must be unique")
        seen_images.add(image_version_id)
        image_version = db.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ArtifactVersion.id == image_version_id,
                ArtifactVersion.store_id == store_id,
                Artifact.store_id == store_id,
                Artifact.task_id == task_id,
                Artifact.artifact_type == "image",
                Artifact.current_version_id == ArtifactVersion.id,
            )
        )
        if image_version is None:
            raise ApiError(404, "IMAGE_VERSION_NOT_FOUND", "Current image version not found")
        approved_image = db.scalar(
            select(ReviewRecord.id).where(
                ReviewRecord.store_id == store_id,
                ReviewRecord.artifact_id == image_version.artifact_id,
                ReviewRecord.artifact_version_id == image_version.id,
                ReviewRecord.review_type == "image",
                ReviewRecord.decision == "approved",
            )
        )
        if approved_image is None:
            raise ApiError(
                409,
                "IMAGE_REVIEW_REQUIRED",
                "Every referenced image version must be approved",
            )
        image_versions.append(image_version)

    fingerprint = _fingerprint(
        {
            "task_id": str(task_id),
            "channel_key": payload.channel_key,
            "copy_version_id": str(copy_version.id),
            "channel_spec_version_id": str(payload.channel_spec_version_id),
            "payload": payload.payload,
            "image_version_ids": [str(item.id) for item in image_versions],
        }
    )
    existing = db.scalar(
        select(ChannelContent).where(
            ChannelContent.store_id == store_id,
            ChannelContent.channel_key == payload.channel_key,
            ChannelContent.input_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        existing_refs = list(
            db.scalars(
                select(ChannelContentArtifactRef)
                .where(
                    ChannelContentArtifactRef.store_id == store_id,
                    ChannelContentArtifactRef.channel_content_id == existing.id,
                )
                .order_by(ChannelContentArtifactRef.position)
            ).all()
        )
        reports = list(
            db.scalars(
                select(QualityReport).where(
                    QualityReport.store_id == store_id,
                    QualityReport.channel_content_id == existing.id,
                )
            ).all()
        )
        response = _content_payload(existing, existing_refs, reports)
        complete_idempotency(
            idempotency,
            response=response,
            resource_type="channel_content",
            resource_id=existing.id,
        )
        db.commit()
        return response

    content = ChannelContent(
        id=uuid4(),
        store_id=store_id,
        task_id=task_id,
        channel_key=payload.channel_key,
        copy_version_id=copy_version.id,
        payload_json=payload.payload,
        channel_spec_version_id=payload.channel_spec_version_id,
        input_fingerprint=fingerprint,
        status="ready",
    )
    db.add(content)
    db.flush()

    refs: list[ChannelContentArtifactRef] = []
    for position, image_version in enumerate(image_versions):
        ref = ChannelContentArtifactRef(
            id=uuid4(),
            store_id=store_id,
            channel_content_id=content.id,
            artifact_version_id=image_version.id,
            role="image",
            position=position,
        )
        db.add(ref)
        refs.append(ref)
    db.flush()

    response = _content_payload(content, refs, [])
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="channel_content",
        resource_id=content.id,
    )
    record_audit(
        db,
        request,
        action="content.channel_content.created",
        target_type="channel_content",
        target_id=content.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "task_id": str(task_id),
            "channel_key": payload.channel_key,
            "input_fingerprint": fingerprint,
            "image_count": len(refs),
        },
    )
    db.commit()
    return response


@router.get("/{task_id}/channel-contents")
def list_channel_contents(
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
    contents = db.scalars(
        select(ChannelContent)
        .where(ChannelContent.store_id == store_id, ChannelContent.task_id == task_id)
        .order_by(ChannelContent.created_at, ChannelContent.id)
    ).all()
    result: list[dict[str, object]] = []
    for content in contents:
        refs = list(
            db.scalars(
                select(ChannelContentArtifactRef)
                .where(
                    ChannelContentArtifactRef.store_id == store_id,
                    ChannelContentArtifactRef.channel_content_id == content.id,
                )
                .order_by(ChannelContentArtifactRef.position)
            ).all()
        )
        reports = list(
            db.scalars(
                select(QualityReport)
                .where(
                    QualityReport.store_id == store_id,
                    QualityReport.channel_content_id == content.id,
                )
                .order_by(QualityReport.created_at, QualityReport.id)
            ).all()
        )
        result.append(_content_payload(content, refs, reports))
    return result
