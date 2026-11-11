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
from store_operator.db import get_db
from store_operator.idempotency import begin_idempotency, complete_idempotency
from store_operator.models import (
    Artifact,
    ArtifactVersion,
    BusinessFactSnapshot,
    ChannelContent,
    ChannelContentArtifactRef,
    PublishConfirmation,
    PublishPackage,
    PublishPackageFactRef,
    PublishPackageItem,
    QualityReport,
    QualityResolution,
    RequirementSnapshot,
    ReviewRecord,
    StoreRecordRevision,
    StrategySnapshot,
    MarketingTask,
)

router = APIRouter(prefix="/marketing-tasks", tags=["content-publishing"])


class PublishPackageItemInput(BaseModel):
    channel_content_id: UUID
    quality_report_id: UUID
    delivery_mode: Literal["manual_handoff"] = "manual_handoff"
    planned_publish_at: datetime | None = None

    @model_validator(mode="after")
    def require_timezone_for_schedule(self) -> PublishPackageItemInput:
        if self.planned_publish_at is not None and self.planned_publish_at.tzinfo is None:
            raise ValueError("planned_publish_at must include a timezone")
        return self


class PublishPackageFreezeRequest(BaseModel):
    expected_task_version: int = Field(ge=1)
    fact_snapshot_ids: list[UUID] = Field(min_length=1, max_length=30)
    items: list[PublishPackageItemInput] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_unique_references(self) -> PublishPackageFreezeRequest:
        if len(set(self.fact_snapshot_ids)) != len(self.fact_snapshot_ids):
            raise ValueError("fact_snapshot_ids must be unique")
        content_ids = [item.channel_content_id for item in self.items]
        if len(set(content_ids)) != len(content_ids):
            raise ValueError("channel_content_id values must be unique")
        return self


class PublishPackageConfirmRequest(BaseModel):
    package_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_note: str | None = Field(default=None, max_length=2000)


def _fingerprint(value: dict[str, object]) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _quality_report_fingerprint(content: ChannelContent, report: QualityReport) -> str:
    return _fingerprint(
        {
            "channel_content_id": str(content.id),
            "channel_content_fingerprint": content.input_fingerprint,
            "rule_version": report.rule_version,
        }
    )


def _require_approved_artifacts(
    db: Session, *, store_id: UUID, content: ChannelContent
) -> None:
    copy_version = db.scalar(
        select(ArtifactVersion)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(
            ArtifactVersion.id == content.copy_version_id,
            ArtifactVersion.store_id == store_id,
            Artifact.store_id == store_id,
            Artifact.task_id == content.task_id,
            Artifact.artifact_type == "copy",
            Artifact.current_version_id == ArtifactVersion.id,
        )
    )
    if copy_version is None:
        raise ApiError(409, "COPY_VERSION_STALE", "Channel copy version is no longer current")
    copy_review = db.scalar(
        select(ReviewRecord.id).where(
            ReviewRecord.store_id == store_id,
            ReviewRecord.artifact_id == copy_version.artifact_id,
            ReviewRecord.artifact_version_id == copy_version.id,
            ReviewRecord.review_type == "copy",
            ReviewRecord.decision == "approved",
        )
    )
    if copy_review is None:
        raise ApiError(422, "COPY_REVIEW_REQUIRED", "Channel copy version is not approved")

    image_refs = db.scalars(
        select(ChannelContentArtifactRef).where(
            ChannelContentArtifactRef.store_id == store_id,
            ChannelContentArtifactRef.channel_content_id == content.id,
        )
    ).all()
    for image_ref in image_refs:
        image_version = db.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ArtifactVersion.id == image_ref.artifact_version_id,
                ArtifactVersion.store_id == store_id,
                Artifact.store_id == store_id,
                Artifact.task_id == content.task_id,
                Artifact.artifact_type == "image",
                Artifact.current_version_id == ArtifactVersion.id,
            )
        )
        if image_version is None:
            raise ApiError(409, "IMAGE_VERSION_STALE", "A channel image version is no longer current")
        image_review = db.scalar(
            select(ReviewRecord.id).where(
                ReviewRecord.store_id == store_id,
                ReviewRecord.artifact_id == image_version.artifact_id,
                ReviewRecord.artifact_version_id == image_version.id,
                ReviewRecord.review_type == "image",
                ReviewRecord.decision == "approved",
            )
        )
        if image_review is None:
            raise ApiError(422, "IMAGE_REVIEW_REQUIRED", "A channel image version is not approved")


def _validate_confirmed_fact(
    db: Session, *, store_id: UUID, fact: BusinessFactSnapshot, now: datetime
) -> None:
    if (
        fact.confirmation_status != "confirmed"
        or fact.confirmed_by_user_id is None
        or fact.confirmed_at is None
        or fact.source_id is None
        or fact.source_version is None
    ):
        raise ApiError(
            422,
            "BUSINESS_FACT_NOT_CONFIRMED",
            "Every package fact must be confirmed and traceable to a store record revision",
        )
    revision = db.scalar(
        select(StoreRecordRevision).where(
            StoreRecordRevision.store_id == store_id,
            StoreRecordRevision.record_type == fact.source_type,
            StoreRecordRevision.record_id == fact.source_id,
            StoreRecordRevision.version_no == fact.source_version,
            StoreRecordRevision.fact_status == "confirmed",
        )
    )
    if (
        revision is None
        or revision.confirmed_at is None
        or (revision.valid_from is not None and revision.valid_from > now)
        or (revision.valid_until is not None and revision.valid_until <= now)
    ):
        raise ApiError(
            409,
            "BUSINESS_FACT_SOURCE_STALE",
            "A package fact no longer has a valid confirmed source revision",
        )
    latest_version = db.scalar(
        select(func.max(StoreRecordRevision.version_no)).where(
            StoreRecordRevision.store_id == store_id,
            StoreRecordRevision.record_type == fact.source_type,
            StoreRecordRevision.record_id == fact.source_id,
        )
    )
    if latest_version != fact.source_version:
        raise ApiError(
            409,
            "BUSINESS_FACT_SOURCE_STALE",
            "A newer store record revision exists; refresh task facts before freezing",
        )


def _package_payload(
    package: PublishPackage,
    items: list[PublishPackageItem],
    fact_refs: list[PublishPackageFactRef],
    confirmation: PublishConfirmation | None,
) -> dict[str, object]:
    return {
        "id": str(package.id),
        "task_id": str(package.task_id),
        "package_version": package.package_version,
        "package_fingerprint": package.package_fingerprint,
        "frozen_at": package.frozen_at.isoformat(),
        "frozen_by_user_id": (
            str(package.frozen_by_user_id) if package.frozen_by_user_id else None
        ),
        "items": [
            {
                "id": str(item.id),
                "channel_key": item.channel_key,
                "channel_content_id": str(item.channel_content_id),
                "quality_report_id": str(item.quality_report_id),
                "delivery_mode": item.delivery_mode,
                "planned_publish_at": (
                    item.planned_publish_at.isoformat()
                    if item.planned_publish_at
                    else None
                ),
                "item_fingerprint": item.item_fingerprint,
            }
            for item in items
        ],
        "fact_snapshot_ids": [
            str(item.business_fact_snapshot_id) for item in fact_refs
        ],
        "confirmation": (
            {
                "id": str(confirmation.id),
                "package_fingerprint": confirmation.package_fingerprint,
                "confirmed_by_user_id": str(confirmation.confirmed_by_user_id),
                "confirmed_at": confirmation.confirmed_at.isoformat(),
                "confirmation_note": confirmation.confirmation_note,
            }
            if confirmation is not None
            else None
        ),
    }


@router.post("/{task_id}/publish-packages/freeze", status_code=201)
def freeze_publish_package(
    task_id: UUID,
    payload: PublishPackageFreezeRequest,
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
        payload={"task_id": task_id, **payload.model_dump()},
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
    if task.version != payload.expected_task_version:
        raise ApiError(409, "TASK_VERSION_CONFLICT", "Marketing task version has changed")
    if task.lifecycle_status in {"cancelled", "archived", "failed"}:
        raise ApiError(409, "TASK_NOT_FREEZABLE", "Marketing task cannot be frozen")

    requirement = db.scalar(
        select(RequirementSnapshot).where(
            RequirementSnapshot.store_id == store_id,
            RequirementSnapshot.task_id == task.id,
            RequirementSnapshot.id == task.current_requirement_snapshot_id,
        )
    )
    strategy = db.scalar(
        select(StrategySnapshot).where(
            StrategySnapshot.store_id == store_id,
            StrategySnapshot.task_id == task.id,
            StrategySnapshot.id == task.current_strategy_snapshot_id,
        )
    )
    if (
        requirement is None
        or requirement.confirmed_at is None
        or strategy is None
        or strategy.confirmed_at is None
    ):
        raise ApiError(
            422,
            "TASK_SNAPSHOTS_NOT_CONFIRMED",
            "Requirement and strategy snapshots must both be confirmed before freezing",
        )

    facts = list(
        db.scalars(
            select(BusinessFactSnapshot)
            .where(
                BusinessFactSnapshot.store_id == store_id,
                BusinessFactSnapshot.task_id == task.id,
                BusinessFactSnapshot.id.in_(payload.fact_snapshot_ids),
            )
            .order_by(BusinessFactSnapshot.fact_key, BusinessFactSnapshot.version_no)
            .with_for_update()
        ).all()
    )
    if len(facts) != len(payload.fact_snapshot_ids):
        raise ApiError(404, "BUSINESS_FACT_NOT_FOUND", "A business fact snapshot was not found")
    now = datetime.now(UTC)
    for fact in facts:
        _validate_confirmed_fact(
            db, store_id=store_id, fact=fact, now=now
        )

    channel_keys: set[str] = set()
    package_items: list[tuple[ChannelContent, QualityReport, PublishPackageItemInput, str]] = []
    for item_input in payload.items:
        content = db.scalar(
            select(ChannelContent).where(
                ChannelContent.id == item_input.channel_content_id,
                ChannelContent.store_id == store_id,
                ChannelContent.task_id == task.id,
            )
        )
        if content is None:
            raise ApiError(
                404, "CHANNEL_CONTENT_NOT_FOUND", "A channel content snapshot was not found"
            )
        if content.status != "ready":
            raise ApiError(409, "CHANNEL_CONTENT_NOT_READY", "Channel content is not ready")
        if content.channel_key in channel_keys:
            raise ApiError(409, "DUPLICATE_PACKAGE_CHANNEL", "A package can contain one item per channel")
        channel_keys.add(content.channel_key)
        _require_approved_artifacts(db, store_id=store_id, content=content)

        report = db.scalar(
            select(QualityReport).where(
                QualityReport.id == item_input.quality_report_id,
                QualityReport.store_id == store_id,
                QualityReport.task_id == task.id,
                QualityReport.channel_content_id == content.id,
            )
        )
        if report is None:
            raise ApiError(404, "QUALITY_REPORT_NOT_FOUND", "A quality report was not found")
        if report.input_fingerprint != _quality_report_fingerprint(content, report):
            raise ApiError(409, "QUALITY_REPORT_STALE", "Quality report fingerprint is stale")
        if report.result == "fail":
            raise ApiError(422, "QUALITY_BLOCKED", "A hard-fail quality report blocks package freeze")
        if report.result == "needs_human":
            resolution = db.scalar(
                select(QualityResolution).where(
                    QualityResolution.store_id == store_id,
                    QualityResolution.quality_report_id == report.id,
                    QualityResolution.quality_report_fingerprint == report.input_fingerprint,
                )
            )
            if resolution is None or resolution.decision != "accepted":
                raise ApiError(
                    422,
                    "QUALITY_RESOLUTION_REQUIRED",
                    "A needs_human report requires an accepted human resolution",
                )

        item_fingerprint = _fingerprint(
            {
                "channel_key": content.channel_key,
                "channel_content_id": str(content.id),
                "channel_content_fingerprint": content.input_fingerprint,
                "quality_report_id": str(report.id),
                "quality_report_fingerprint": report.input_fingerprint,
                "delivery_mode": item_input.delivery_mode,
                "channel_account_id": None,
                "planned_publish_at": (
                    item_input.planned_publish_at.astimezone(UTC).isoformat()
                    if item_input.planned_publish_at
                    else None
                ),
            }
        )
        package_items.append((content, report, item_input, item_fingerprint))

    package_items.sort(key=lambda item: item[0].channel_key)
    fact_ids = [fact.id for fact in facts]
    package_fingerprint = _fingerprint(
        {
            "task_id": str(task.id),
            "task_version": task.version,
            "requirement_snapshot_id": str(requirement.id),
            "strategy_snapshot_id": str(strategy.id),
            "item_fingerprints": [item[3] for item in package_items],
            "fact_snapshot_ids": sorted(str(item) for item in fact_ids),
        }
    )
    package_version = (
        db.scalar(
            select(func.max(PublishPackage.package_version)).where(
                PublishPackage.store_id == store_id,
                PublishPackage.task_id == task.id,
            )
        )
        or 0
    ) + 1
    package = PublishPackage(
        id=uuid4(),
        store_id=store_id,
        task_id=task.id,
        package_version=package_version,
        package_fingerprint=package_fingerprint,
        frozen_by_user_id=auth.user.id,
    )
    db.add(package)
    db.flush()

    stored_items: list[PublishPackageItem] = []
    for content, report, item_input, item_fingerprint in package_items:
        stored = PublishPackageItem(
            id=uuid4(),
            store_id=store_id,
            publish_package_id=package.id,
            channel_key=content.channel_key,
            channel_content_id=content.id,
            quality_report_id=report.id,
            channel_account_id=None,
            delivery_mode=item_input.delivery_mode,
            planned_publish_at=item_input.planned_publish_at,
            item_fingerprint=item_fingerprint,
        )
        db.add(stored)
        stored_items.append(stored)
    stored_facts: list[PublishPackageFactRef] = []
    for position, fact in enumerate(facts):
        stored = PublishPackageFactRef(
            id=uuid4(),
            store_id=store_id,
            task_id=task.id,
            publish_package_id=package.id,
            business_fact_snapshot_id=fact.id,
            position=position,
        )
        db.add(stored)
        stored_facts.append(stored)
    db.flush()

    response = _package_payload(package, stored_items, stored_facts, None)
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
            "task_id": str(task.id),
            "package_version": package_version,
            "package_fingerprint": package_fingerprint,
            "channel_count": len(stored_items),
            "fact_count": len(stored_facts),
        },
    )
    db.commit()
    return response


@router.post("/publish-packages/{package_id}/confirm", status_code=201)
def confirm_publish_package(
    package_id: UUID,
    payload: PublishPackageConfirmRequest,
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
        payload={"package_id": package_id, **payload.model_dump()},
    )
    if replay is not None:
        return replay

    package = db.scalar(
        select(PublishPackage)
        .where(
            PublishPackage.id == package_id,
            PublishPackage.store_id == store_id,
        )
        .with_for_update()
    )
    if package is None:
        raise ApiError(404, "PUBLISH_PACKAGE_NOT_FOUND", "Publish package not found")
    if package.package_fingerprint != payload.package_fingerprint:
        raise ApiError(409, "PACKAGE_STALE", "Publish package fingerprint has changed")
    latest_version = db.scalar(
        select(func.max(PublishPackage.package_version)).where(
            PublishPackage.store_id == store_id,
            PublishPackage.task_id == package.task_id,
        )
    )
    if latest_version != package.package_version:
        raise ApiError(409, "PACKAGE_STALE", "A newer package version exists")
    existing = db.scalar(
        select(PublishConfirmation).where(
            PublishConfirmation.store_id == store_id,
            PublishConfirmation.publish_package_id == package.id,
            PublishConfirmation.package_fingerprint == package.package_fingerprint,
        )
    )
    if existing is not None:
        raise ApiError(
            409,
            "PACKAGE_ALREADY_CONFIRMED",
            "This package fingerprint has already been confirmed",
        )
    confirmation = PublishConfirmation(
        id=uuid4(),
        store_id=store_id,
        publish_package_id=package.id,
        package_fingerprint=package.package_fingerprint,
        confirmed_by_user_id=auth.user.id,
        confirmation_note=(
            payload.confirmation_note.strip() if payload.confirmation_note else None
        ),
    )
    db.add(confirmation)
    db.flush()
    response: dict[str, object] = {
        "id": str(confirmation.id),
        "publish_package_id": str(package.id),
        "package_fingerprint": confirmation.package_fingerprint,
        "confirmed_by_user_id": str(auth.user.id),
        "confirmed_at": confirmation.confirmed_at.isoformat(),
        "confirmation_note": confirmation.confirmation_note,
        "delivery_mode": "manual_handoff",
        "published": False,
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


@router.get("/{task_id}/publish-packages")
def list_publish_packages(
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
    packages = db.scalars(
        select(PublishPackage)
        .where(PublishPackage.store_id == store_id, PublishPackage.task_id == task_id)
        .order_by(PublishPackage.package_version.desc())
    ).all()
    result: list[dict[str, object]] = []
    for package in packages:
        items = db.scalars(
            select(PublishPackageItem)
            .where(
                PublishPackageItem.store_id == store_id,
                PublishPackageItem.publish_package_id == package.id,
            )
            .order_by(PublishPackageItem.channel_key)
        ).all()
        facts = db.scalars(
            select(PublishPackageFactRef)
            .where(
                PublishPackageFactRef.store_id == store_id,
                PublishPackageFactRef.publish_package_id == package.id,
            )
            .order_by(PublishPackageFactRef.position)
        ).all()
        confirmation = db.scalar(
            select(PublishConfirmation).where(
                PublishConfirmation.store_id == store_id,
                PublishConfirmation.publish_package_id == package.id,
                PublishConfirmation.package_fingerprint == package.package_fingerprint,
            )
        )
        result.append(_package_payload(package, list(items), list(facts), confirmation))
    return result
