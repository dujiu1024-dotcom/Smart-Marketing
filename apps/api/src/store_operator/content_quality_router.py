from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
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
from store_operator.db import get_db
from store_operator.idempotency import begin_idempotency, complete_idempotency
from store_operator.jobs.service import JobIdempotencyConflict, create_job
from store_operator.models.channel_spec import (
    ChannelCapabilitySnapshot,
    ChannelSpec,
    ChannelSpecVersion,
)
from store_operator.models.channel_delivery import ChannelAccount
from store_operator.models.content_delivery import (
    Artifact,
    ArtifactVersion,
    ChannelContent,
    ChannelContentArtifactRef,
    QualityReport,
    QualityResolution,
    ReviewRecord,
    PublishConfirmation,
    PublishPackage,
    PublishPackageFactRef,
    PublishPackageItem,
)
from store_operator.models.marketing_task import (
    BusinessFactSnapshot,
    MarketingTask,
    RequirementSnapshot,
    StrategySnapshot,
)

router = APIRouter(prefix="/marketing-tasks", tags=["content-quality"])


class QualityReportRun(BaseModel):
    rule_version: str = Field(min_length=1, max_length=80)
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class QualityReportRunIdempotency(BaseModel):
    task_id: UUID
    content_id: UUID
    rule_version: str
    expected_fingerprint: str


class QualityResolutionCreate(BaseModel):
    decision: str = Field(pattern=r"^(accepted|rejected)$")
    reason: str = Field(min_length=1, max_length=5000)
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")



class PublishPackageItemCreate(BaseModel):
    channel_content_id: UUID
    quality_report_id: UUID
    delivery_mode: str = Field(pattern=r"^(official_api|manual_handoff)$")
    channel_account_id: UUID | None = None
    planned_publish_at: datetime | None = None


class PublishPackageCreate(BaseModel):
    items: list[PublishPackageItemCreate] = Field(min_length=1, max_length=10)


class PublishPackageConfirm(BaseModel):
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_note: str | None = Field(default=None, max_length=2000)


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
    resolutions: list[QualityResolution] | None = None,
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
                "resolutions": [
                    {
                        "id": str(resolution.id),
                        "decision": resolution.decision,
                        "reason": resolution.reason,
                        "created_at": resolution.created_at.isoformat(),
                    }
                    for resolution in resolutions or []
                    if resolution.quality_report_id == item.id
                ],
            }
            for item in reports
        ],
        "created_at": content.created_at.isoformat(),
        "updated_at": content.updated_at.isoformat(),
    }




def _publish_package_payload(
    package: PublishPackage,
    items: list[PublishPackageItem],
    fact_refs: list[PublishPackageFactRef],
    confirmation: PublishConfirmation | None = None,
) -> dict[str, object]:
    return {
        "id": str(package.id),
        "task_id": str(package.task_id),
        "package_version": package.package_version,
        "package_fingerprint": package.package_fingerprint,
        "frozen_at": package.frozen_at.isoformat(),
        "items": [
            {
                "id": str(item.id),
                "channel_key": item.channel_key,
                "channel_content_id": str(item.channel_content_id),
                "quality_report_id": str(item.quality_report_id),
                "channel_account_id": str(item.channel_account_id)
                if item.channel_account_id else None,
                "delivery_mode": item.delivery_mode,
                "planned_publish_at": item.planned_publish_at.isoformat()
                if item.planned_publish_at else None,
                "item_fingerprint": item.item_fingerprint,
            }
            for item in items
        ],
        "business_fact_snapshot_ids": [
            str(item.business_fact_snapshot_id) for item in fact_refs
        ],
        "confirmation": (
            {
                "id": str(confirmation.id),
                "package_fingerprint": confirmation.package_fingerprint,
                "confirmed_at": confirmation.confirmed_at.isoformat(),
                "confirmation_note": confirmation.confirmation_note,
            }
            if confirmation else None
        ),
    }


@router.post("/{task_id}/publish-packages", status_code=201)
def freeze_publish_package(
    task_id: UUID,
    payload: PublishPackageCreate,
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
        operation="content.publish_package.freeze",
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
    if task.current_requirement_snapshot_id is None or task.current_strategy_snapshot_id is None:
        raise ApiError(
            409,
            "TASK_SNAPSHOTS_REQUIRED",
            "Requirement and strategy must be confirmed before package freeze",
        )
    requirement = db.scalar(
        select(RequirementSnapshot).where(
            RequirementSnapshot.id == task.current_requirement_snapshot_id,
            RequirementSnapshot.store_id == store_id,
            RequirementSnapshot.task_id == task_id,
        )
    )
    strategy = db.scalar(
        select(StrategySnapshot).where(
            StrategySnapshot.id == task.current_strategy_snapshot_id,
            StrategySnapshot.store_id == store_id,
            StrategySnapshot.task_id == task_id,
        )
    )
    if requirement is None or strategy is None:
        raise ApiError(409, "TASK_SNAPSHOT_INVALID", "Current task snapshots are invalid")

    channel_keys = [item.channel_content_id for item in payload.items]
    if len(channel_keys) != len(set(channel_keys)):
        raise ApiError(422, "DUPLICATE_PACKAGE_CONTENT", "Package content references must be unique")
    channels: set[str] = set()
    frozen_items: list[PublishPackageItem] = []
    item_fingerprints: list[dict[str, object]] = []
    now = datetime.now(UTC)

    for item in payload.items:
        content = db.scalar(
            select(ChannelContent).where(
                ChannelContent.id == item.channel_content_id,
                ChannelContent.task_id == task_id,
                ChannelContent.store_id == store_id,
            )
        )
        if content is None:
            raise ApiError(404, "CHANNEL_CONTENT_NOT_FOUND", "Channel content not found")
        if content.status != "ready":
            raise ApiError(409, "CHANNEL_CONTENT_NOT_READY", "Stale or blocked content cannot be frozen")
        if content.channel_key in channels:
            raise ApiError(422, "DUPLICATE_PACKAGE_CHANNEL", "Only one item per channel is allowed")
        channels.add(content.channel_key)

        copy_is_current = db.scalar(
            select(Artifact.id)
            .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
            .where(
                Artifact.id == (
                    select(ArtifactVersion.artifact_id).where(
                        ArtifactVersion.id == content.copy_version_id
                    ).scalar_subquery()
                ),
                Artifact.store_id == store_id,
                Artifact.task_id == task_id,
                Artifact.artifact_type == "copy",
                Artifact.current_version_id == content.copy_version_id,
            )
        )
        if copy_is_current is None:
            raise ApiError(409, "CHANNEL_CONTENT_STALE", "Copy version is no longer current")
        image_refs = list(
            db.scalars(
                select(ChannelContentArtifactRef).where(
                    ChannelContentArtifactRef.store_id == store_id,
                    ChannelContentArtifactRef.channel_content_id == content.id,
                )
            ).all()
        )
        for image_ref in image_refs:
            image_is_current = db.scalar(
                select(Artifact.id)
                .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
                .where(
                    ArtifactVersion.id == image_ref.artifact_version_id,
                    Artifact.store_id == store_id,
                    Artifact.task_id == task_id,
                    Artifact.artifact_type == "image",
                    Artifact.current_version_id == image_ref.artifact_version_id,
                )
            )
            if image_is_current is None:
                raise ApiError(409, "CHANNEL_CONTENT_STALE", "Image version is no longer current")

        report = db.scalar(
            select(QualityReport).where(
                QualityReport.id == item.quality_report_id,
                QualityReport.store_id == store_id,
                QualityReport.task_id == task_id,
                QualityReport.channel_content_id == content.id,
                QualityReport.input_fingerprint == content.input_fingerprint,
            )
        )
        if report is None:
            raise ApiError(409, "QUALITY_REPORT_REQUIRED", "A current quality report is required")
        if report.result == "needs_human":
            resolution = db.scalar(
                select(QualityResolution).where(
                    QualityResolution.store_id == store_id,
                    QualityResolution.quality_report_id == report.id,
                    QualityResolution.quality_report_fingerprint == report.input_fingerprint,
                    QualityResolution.decision == "accepted",
                )
            )
            if resolution is None:
                raise ApiError(409, "QUALITY_HUMAN_REVIEW_REQUIRED", "Quality report requires an accepted human resolution")
        elif report.result != "pass":
            raise ApiError(409, "QUALITY_CHECK_FAILED", "Failed quality reports cannot be published")

        spec_version = db.scalar(
            select(ChannelSpecVersion)
            .join(ChannelSpec, ChannelSpec.id == ChannelSpecVersion.channel_spec_id)
            .where(
                ChannelSpecVersion.id == content.channel_spec_version_id,
                ChannelSpec.channel_key == content.channel_key,
                ChannelSpec.current_version_id == ChannelSpecVersion.id,
                ChannelSpecVersion.verification_status == "verified",
            )
        )
        if spec_version is None:
            raise ApiError(409, "CHANNEL_SPEC_STALE", "Content must use the current verified channel specification")

        if item.delivery_mode == "official_api":
            if item.channel_account_id is None:
                raise ApiError(422, "CHANNEL_ACCOUNT_REQUIRED", "Official API delivery requires a connected account")
            account = db.scalar(
                select(ChannelAccount).where(
                    ChannelAccount.id == item.channel_account_id,
                    ChannelAccount.store_id == store_id,
                    ChannelAccount.provider == content.channel_key,
                    ChannelAccount.status == "active",
                )
            )
            if account is None:
                raise ApiError(409, "CHANNEL_ACCOUNT_NOT_ACTIVE", "An active account for this channel is required")
            if not spec_version.publish_supported:
                raise ApiError(409, "CHANNEL_PUBLISH_UNSUPPORTED", "Official publishing is not verified for this channel")
            capability = db.scalar(
                select(ChannelCapabilitySnapshot)
                .where(
                    ChannelCapabilitySnapshot.store_id == store_id,
                    ChannelCapabilitySnapshot.channel_account_id == account.id,
                    ChannelCapabilitySnapshot.channel_spec_version_id == spec_version.id,
                    ChannelCapabilitySnapshot.capability_key == "publish_image_text",
                    ChannelCapabilitySnapshot.support_status == "supported",
                    (ChannelCapabilitySnapshot.expires_at.is_(None))
                    | (ChannelCapabilitySnapshot.expires_at > now),
                )
                .order_by(ChannelCapabilitySnapshot.checked_at.desc())
            )
            if capability is None:
                raise ApiError(409, "CHANNEL_PUBLISH_CAPABILITY_UNVERIFIED", "Publishing capability has not been verified for this account")
        elif item.channel_account_id is not None:
            raise ApiError(422, "MANUAL_HANDOFF_ACCOUNT_FORBIDDEN", "Manual handoff must not bind a platform account")

        item_fingerprint = _fingerprint(
            {
                "channel_content_id": str(content.id),
                "content_fingerprint": content.input_fingerprint,
                "quality_report_id": str(report.id),
                "quality_report_fingerprint": report.input_fingerprint,
                "channel_spec_version_id": str(spec_version.id),
                "channel_account_id": str(item.channel_account_id) if item.channel_account_id else None,
                "delivery_mode": item.delivery_mode,
                "planned_publish_at": item.planned_publish_at.isoformat() if item.planned_publish_at else None,
            }
        )
        frozen_items.append(
            PublishPackageItem(
                id=uuid4(),
                store_id=store_id,
                publish_package_id=uuid4(),
                channel_key=content.channel_key,
                channel_content_id=content.id,
                quality_report_id=report.id,
                channel_account_id=item.channel_account_id,
                delivery_mode=item.delivery_mode,
                planned_publish_at=item.planned_publish_at,
                item_fingerprint=item_fingerprint,
            )
        )
        item_fingerprints.append({"channel_key": content.channel_key, "fingerprint": item_fingerprint})

    facts = list(
        db.scalars(
            select(BusinessFactSnapshot)
            .where(
                BusinessFactSnapshot.store_id == store_id,
                BusinessFactSnapshot.task_id == task_id,
                BusinessFactSnapshot.confirmation_status == "confirmed",
            )
            .order_by(BusinessFactSnapshot.fact_key, BusinessFactSnapshot.version_no)
        ).all()
    )
    if not facts:
        raise ApiError(409, "CONFIRMED_FACTS_REQUIRED", "At least one confirmed business fact is required")
    package_version = db.scalar(
        select(func.max(PublishPackage.package_version)).where(
            PublishPackage.store_id == store_id,
            PublishPackage.task_id == task_id,
        )
    ) or 0
    fact_fingerprints = [
        {"fact_key": fact.fact_key, "version": fact.version_no, "fingerprint": fact.content_fingerprint}
        for fact in facts
    ]
    package_fingerprint = _fingerprint(
        {
            "task_id": str(task_id),
            "requirement_snapshot_id": str(requirement.id),
            "strategy_snapshot_id": str(strategy.id),
            "items": sorted(item_fingerprints, key=lambda value: str(value["channel_key"])),
            "facts": fact_fingerprints,
        }
    )
    package_id = uuid4()
    package = PublishPackage(
        id=package_id,
        store_id=store_id,
        task_id=task_id,
        package_version=package_version + 1,
        package_fingerprint=package_fingerprint,
        frozen_by_user_id=auth.user.id,
    )
    db.add(package)
    db.flush()
    for frozen_item in frozen_items:
        frozen_item.publish_package_id = package_id
        db.add(frozen_item)
    fact_refs = [
        PublishPackageFactRef(
            id=uuid4(),
            store_id=store_id,
            task_id=task_id,
            publish_package_id=package_id,
            business_fact_snapshot_id=fact.id,
            position=index,
        )
        for index, fact in enumerate(facts)
    ]
    db.add_all(fact_refs)
    db.flush()
    response = _publish_package_payload(package, frozen_items, fact_refs)
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="publish_package",
        resource_id=package.id,
    )
    record_audit(
        db,
        request,
        action="content.publish_package.frozen",
        target_type="publish_package",
        target_id=package.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "task_id": str(task_id),
            "package_version": package.package_version,
            "package_fingerprint": package_fingerprint,
            "item_count": len(frozen_items),
            "fact_count": len(fact_refs),
        },
    )
    db.commit()
    return response


@router.post("/publish-packages/{package_id}/confirm", status_code=201)
def confirm_publish_package(
    package_id: UUID,
    payload: PublishPackageConfirm,
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
        operation="content.publish_package.confirm",
        payload=payload,
    )
    if replay is not None:
        return replay
    package = db.scalar(
        select(PublishPackage)
        .where(PublishPackage.id == package_id, PublishPackage.store_id == store_id)
        .with_for_update()
    )
    if package is None:
        raise ApiError(404, "PUBLISH_PACKAGE_NOT_FOUND", "Publish package not found")
    if package.package_fingerprint != payload.expected_fingerprint:
        raise ApiError(409, "PUBLISH_PACKAGE_STALE", "Publish package fingerprint has changed")
    existing = db.scalar(
        select(PublishConfirmation).where(
            PublishConfirmation.store_id == store_id,
            PublishConfirmation.publish_package_id == package.id,
            PublishConfirmation.package_fingerprint == package.package_fingerprint,
        )
    )
    if existing is not None:
        raise ApiError(409, "PUBLISH_PACKAGE_ALREADY_CONFIRMED", "This exact package was already confirmed")
    confirmation = PublishConfirmation(
        id=uuid4(),
        store_id=store_id,
        publish_package_id=package.id,
        package_fingerprint=package.package_fingerprint,
        confirmed_by_user_id=auth.user.id,
        confirmation_note=payload.confirmation_note.strip() if payload.confirmation_note else None,
    )
    db.add(confirmation)
    db.flush()
    response = {
        "id": str(confirmation.id),
        "publish_package_id": str(package.id),
        "package_fingerprint": confirmation.package_fingerprint,
        "confirmed_at": confirmation.confirmed_at.isoformat(),
        "confirmation_note": confirmation.confirmation_note,
    }
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="publish_confirmation",
        resource_id=confirmation.id,
    )
    record_audit(
        db,
        request,
        action="content.publish_package.confirmed",
        target_type="publish_package",
        target_id=package.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "confirmation_id": str(confirmation.id),
            "package_fingerprint": package.package_fingerprint,
        },
    )
    db.commit()
    return response


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

    spec_version = db.scalar(
        select(ChannelSpecVersion)
        .join(ChannelSpec, ChannelSpec.id == ChannelSpecVersion.channel_spec_id)
        .where(
            ChannelSpecVersion.id == payload.channel_spec_version_id,
            ChannelSpec.channel_key == payload.channel_key,
            ChannelSpec.status == "active",
        )
    )
    if spec_version is None:
        raise ApiError(
            404,
            "CHANNEL_SPEC_VERSION_NOT_FOUND",
            "Channel specification version not found for this channel",
        )
    if spec_version.verification_status != "verified":
        raise ApiError(
            409,
            "CHANNEL_SPEC_UNVERIFIED",
            "Channel specification version has not been verified against official sources",
        )

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
        report_ids = [item.id for item in reports]
        resolutions = (
            list(
                db.scalars(
                    select(QualityResolution).where(
                        QualityResolution.store_id == store_id,
                        QualityResolution.quality_report_id.in_(report_ids),
                    )
                ).all()
            )
            if report_ids
            else []
        )
        response = _content_payload(existing, existing_refs, reports, resolutions)
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
        report_ids = [item.id for item in reports]
        resolutions = (
            list(
                db.scalars(
                    select(QualityResolution).where(
                        QualityResolution.store_id == store_id,
                        QualityResolution.quality_report_id.in_(report_ids),
                    )
                ).all()
            )
            if report_ids
            else []
        )
        result.append(_content_payload(content, refs, reports, resolutions))
    return result


@router.post("/{task_id}/channel-contents/{content_id}/quality-reports/run", status_code=202)
def run_quality_report(
    task_id: UUID,
    content_id: UUID,
    payload: QualityReportRun,
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
        operation="content.quality_report.run",
        payload=QualityReportRunIdempotency(
            task_id=task_id,
            content_id=content_id,
            **payload.model_dump(),
        ),
    )
    if replay is not None:
        return replay

    content = db.scalar(
        select(ChannelContent).where(
            ChannelContent.id == content_id,
            ChannelContent.task_id == task_id,
            ChannelContent.store_id == store_id,
        )
    )
    if content is None:
        raise ApiError(404, "CHANNEL_CONTENT_NOT_FOUND", "Channel content not found")
    if content.input_fingerprint != payload.expected_fingerprint:
        raise ApiError(409, "CHANNEL_CONTENT_STALE", "Channel content fingerprint has changed")
    if payload.rule_version != "content-structure-v1":
        raise ApiError(
            422,
            "QUALITY_RULE_VERSION_UNSUPPORTED",
            "Quality rule version is not installed",
        )

    request_key = hashlib.sha256(
        f"{store_id}:{auth.user.id}:content.quality_report.run:{idempotency_key}".encode()
    ).hexdigest()
    try:
        job = create_job(
            db,
            job_type="content.quality_check",
            payload_ref={
                "schema_version": 1,
                "channel_content_id": str(content.id),
                "expected_fingerprint": content.input_fingerprint,
                "rule_version": payload.rule_version,
            },
            idempotency_key=request_key,
            store_id=store_id,
            actor_type="user",
            actor_user_id=auth.user.id,
            marketing_task_id=task_id,
            timeout_seconds=120,
        )
    except (JobIdempotencyConflict, ValueError) as exc:
        raise ApiError(
            409,
            "QUALITY_JOB_CONFLICT",
            "Quality check request conflicts with an existing job",
        ) from exc

    response: dict[str, object] = {
        "job_id": str(job.id),
        "job_status": job.status,
        "channel_content_id": str(content.id),
        "expected_fingerprint": content.input_fingerprint,
        "rule_version": payload.rule_version,
    }
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="job",
        resource_id=job.id,
    )
    record_audit(
        db,
        request,
        action="content.quality_report.requested",
        target_type="channel_content",
        target_id=content.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "job_id": str(job.id),
            "rule_version": payload.rule_version,
            "input_fingerprint": content.input_fingerprint,
        },
    )
    db.commit()
    return response



@router.post("/quality-reports/{report_id}/resolutions", status_code=201)
def create_quality_resolution(
    report_id: UUID,
    payload: QualityResolutionCreate,
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
        operation="content.quality_resolution.create",
        payload=payload,
    )
    if replay is not None:
        return replay

    report = db.scalar(
        select(QualityReport)
        .where(
            QualityReport.id == report_id,
            QualityReport.store_id == store_id,
        )
        .with_for_update()
    )
    if report is None:
        raise ApiError(404, "QUALITY_REPORT_NOT_FOUND", "Quality report not found")
    if report.input_fingerprint != payload.expected_fingerprint:
        raise ApiError(409, "QUALITY_REPORT_STALE", "Quality report fingerprint has changed")
    if report.result != "needs_human":
        raise ApiError(
            422,
            "QUALITY_RESOLUTION_NOT_ALLOWED",
            "Only needs_human quality reports can receive a human resolution",
        )
    if not payload.reason.strip():
        raise ApiError(422, "QUALITY_RESOLUTION_REASON_REQUIRED", "A resolution reason is required")

    existing = db.scalar(
        select(QualityResolution).where(
            QualityResolution.store_id == store_id,
            QualityResolution.quality_report_id == report.id,
            QualityResolution.quality_report_fingerprint == report.input_fingerprint,
        )
    )
    if existing is not None:
        raise ApiError(
            409,
            "QUALITY_REPORT_ALREADY_RESOLVED",
            "A resolution already exists for this quality report",
        )

    resolution = QualityResolution(
        id=uuid4(),
        store_id=store_id,
        quality_report_id=report.id,
        quality_report_fingerprint=report.input_fingerprint,
        decision=payload.decision,
        reviewer_user_id=auth.user.id,
        reason=payload.reason.strip(),
    )
    db.add(resolution)
    db.flush()
    response: dict[str, object] = {
        "id": str(resolution.id),
        "quality_report_id": str(report.id),
        "quality_report_fingerprint": resolution.quality_report_fingerprint,
        "decision": resolution.decision,
        "reason": resolution.reason,
        "created_at": resolution.created_at.isoformat(),
    }
    complete_idempotency(
        idempotency,
        response=response,
        resource_type="quality_resolution",
        resource_id=resolution.id,
    )
    record_audit(
        db,
        request,
        action="content.quality_resolution.recorded",
        target_type="quality_report",
        target_id=report.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "resolution_id": str(resolution.id),
            "decision": resolution.decision,
            "report_fingerprint": report.input_fingerprint,
        },
    )
    db.commit()
    return response
