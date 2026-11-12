from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import cast
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from store_operator.ai_gateway import (  # type: ignore[import-untyped]
    ImageEditRequest,
    ImageGenerateRequest,
    ProviderCallContext,
    ProviderCapability,
    VisionInspectRequest,
    render_published_prompt,
    validate_structured_output,
)
from store_operator.ai_gateway.schemas import ImageGenerateResponse  # type: ignore[import-untyped]
from store_operator.models import (  # type: ignore[import-untyped]
    Artifact,
    ArtifactVersion,
    BusinessFactSnapshot,
    Job,
    MarketingTask,
    MediaAsset,
    OutboxEvent,
    PromptVersion,
    RequirementSnapshot,
    StrategySnapshot,
    TaskStep,
)
from store_operator.models.store_knowledge import product_media_assets  # type: ignore[import-untyped]

from store_operator_worker.ai_handlers import (
    _business_fact_snapshots,
    _call_text_provider,
    _load_executor,
    _prompt_variables,
    _published_prompt,
    _safe_error,
    _session_factory,
)
from store_operator_worker.handlers import (
    JobExecutionContext,
    JobExecutionError,
    register_job_handler,
)
from store_operator_worker.media_scanner import (
    ClamAvError,
    MalwareDetected,
    image_dimensions,
    scan_with_clamd,
    validate_image_dimensions,
)

logger = logging.getLogger(__name__)
_MAX_IMAGE_BYTES = 25 * 1024 * 1024


def download_object_bytes(*, object_key: str, max_bytes: int) -> bytes:
    from store_operator.object_storage import download_object_bytes as download  # type: ignore[import-untyped]

    return cast(bytes, download(object_key=object_key, max_bytes=max_bytes))


def delete_object(*, object_key: str) -> None:
    from store_operator.object_storage import delete_object as delete  # type: ignore[import-untyped]

    delete(object_key=object_key)


def _delete_generated_object(object_key: str) -> None:
    try:
        delete_object(object_key=object_key)
    except (RuntimeError, BotoCoreError, OSError) as cleanup_error:
        logger.warning(
            "Could not clean up generated image object (%s)",
            type(cleanup_error).__name__,
        )


def _image_size(aspect_ratio: object) -> tuple[int, int]:
    ratios = {
        "1:1": (1024, 1024),
        "4:5": (1024, 1280),
        "3:4": (1024, 1365),
        "16:9": (1536, 864),
        "9:16": (864, 1536),
    }
    return ratios.get(str(aspect_ratio).strip(), (1024, 1024))


def _image_prompt_variables(
    version: PromptVersion,
    *,
    task: MarketingTask,
    requirement: RequirementSnapshot,
    strategy: StrategySnapshot,
    business_facts: list[BusinessFactSnapshot],
    revision_instruction: str,
    source_asset: MediaAsset | None,
    extra_variables: dict[str, object] | None = None,
) -> dict[str, object]:
    source_metadata: dict[str, object] = {}
    if source_asset is not None:
        source_metadata = {
            "mime_type": source_asset.mime_type,
            "width": source_asset.width or 0,
            "height": source_asset.height or 0,
            "sha256": source_asset.sha256,
            "asset_type": source_asset.asset_type,
        }
    extra: dict[str, object] = {
        "revision_instruction": revision_instruction,
        "source_asset": source_metadata,
        "source_asset_available": source_asset is not None,
    }
    if extra_variables:
        extra.update(extra_variables)
    return _prompt_variables(
        version,
        task=task,
        requirement=requirement,
        strategy=strategy,
        business_facts=business_facts,
        extra_variables=extra,
    )


def _resolve_source_asset(
    db: Session,
    *,
    task: MarketingTask,
    store_id: UUID,
    business_facts: list[BusinessFactSnapshot],
    explicit_asset_id: object,
) -> MediaAsset | None:
    if explicit_asset_id is not None:
        if not isinstance(explicit_asset_id, str):
            raise _safe_error(
                "AI_IMAGE_SOURCE_INVALID",
                "The selected source image reference is invalid.",
            )
        try:
            asset_id = UUID(explicit_asset_id)
        except ValueError as exc:
            raise _safe_error(
                "AI_IMAGE_SOURCE_INVALID",
                "The selected source image reference is invalid.",
            ) from exc
        asset = db.scalar(
            select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.store_id == store_id,
                MediaAsset.status == "ready",
            )
        )
        if asset is None or (
            asset.source_type != "ai_generated"
            and asset.usage_rights_status != "confirmed_allowed"
        ):
            raise _safe_error(
                "AI_IMAGE_SOURCE_UNAVAILABLE",
                "The source image is unavailable or its usage rights are not confirmed.",
            )
        return asset

    product_ids = [
        fact.source_id
        for fact in business_facts
        if fact.source_type == "product" and fact.source_id is not None
    ]
    for product_id in product_ids:
        asset = db.scalar(
            select(MediaAsset)
            .join(
                product_media_assets,
                (product_media_assets.c.store_id == MediaAsset.store_id)
                & (product_media_assets.c.asset_id == MediaAsset.id),
            )
            .where(
                product_media_assets.c.store_id == store_id,
                product_media_assets.c.product_id == product_id,
                MediaAsset.store_id == store_id,
                MediaAsset.status == "ready",
                MediaAsset.usage_rights_status == "confirmed_allowed",
            )
            .order_by(product_media_assets.c.sort_order, MediaAsset.created_at)
            .limit(1)
        )
        if asset is not None:
            return asset
    if task.task_type == "image_optimization":
        raise _safe_error(
            "AI_IMAGE_SOURCE_REQUIRED",
            "Image optimization requires a ready product image with confirmed usage rights.",
        )
    return None


def _verify_and_scan_image(result: ImageGenerateResponse) -> tuple[bytes, int, int]:
    key = result.asset_object_key
    path = PurePosixPath(key)
    if (
        not key
        or key.startswith("/")
        or "\\" in key
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise _safe_error(
            "AI_IMAGE_OBJECT_KEY_INVALID",
            "The AI provider returned an invalid image storage reference.",
        )
    try:
        content = download_object_bytes(object_key=key, max_bytes=_MAX_IMAGE_BYTES)
    except RuntimeError as exc:
        raise _safe_error(
            "AI_IMAGE_STORAGE_NOT_CONFIGURED",
            "Private image storage is not configured for the Worker.",
        ) from exc
    except BotoCoreError as exc:
        raise JobExecutionError(
            "AI_IMAGE_STORAGE_UNAVAILABLE",
            "Private image storage is temporarily unavailable.",
            retryable=True,
        ) from exc
    except ValueError as exc:
        _delete_generated_object(key)
        raise _safe_error(
            "AI_IMAGE_STORAGE_INVALID",
            "The generated image could not be read within the safety limit.",
        ) from exc
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != result.sha256:
        _delete_generated_object(key)
        raise _safe_error(
            "AI_IMAGE_INTEGRITY_FAILED",
            "The generated image failed SHA-256 integrity verification.",
        )
    try:
        width, height = image_dimensions(content, result.mime_type)
        validate_image_dimensions(width, height)
    except ValueError as exc:
        delete_object(object_key=key)
        raise _safe_error(
            "AI_IMAGE_FORMAT_INVALID",
            "The generated image is not a supported safe image.",
        ) from exc
    if width != result.width or height != result.height:
        delete_object(object_key=key)
        raise _safe_error(
            "AI_IMAGE_DIMENSIONS_MISMATCH",
            "The generated image dimensions do not match provider metadata.",
        )
    try:
        scan_with_clamd(
            content,
            host=os.environ.get("CLAMD_HOST", "clamav"),
            port=int(os.environ.get("CLAMD_PORT", "3310")),
        )
    except MalwareDetected as exc:
        delete_object(object_key=key)
        raise _safe_error(
            "AI_IMAGE_MALWARE_DETECTED",
            "The generated image was rejected by malware scanning.",
        ) from exc
    except ClamAvError as exc:
        raise JobExecutionError(
            "AI_IMAGE_SCAN_UNAVAILABLE",
            "Image malware scanning is temporarily unavailable.",
            retryable=True,
        ) from exc
    return content, width, height


def _operation_idempotency_key(job: Job, operation: str) -> str:
    return hashlib.sha256(
        f"{job.idempotency_key}:{operation}".encode()
    ).hexdigest()


def _vision_report(
    *,
    context: JobExecutionContext,
    task: MarketingTask,
    job: Job,
    version: PromptVersion,
    variables: dict[str, object],
    asset_object_key: str,
) -> dict[str, object]:
    system_instruction, user_input = render_published_prompt(version, variables)
    executor, client, provider_id, model_id = _load_executor(
        ProviderCapability.VISION, "AI_VISION_MODEL_ID"
    )
    try:
        request = VisionInspectRequest(
            context=ProviderCallContext(
                request_id=str(uuid4()),
                store_id=task.store_id,
                job_id=job.id,
                attempt_id=context.attempt_id,
                idempotency_key=_operation_idempotency_key(job, "vision-inspection"),
                marketing_task_id=task.id,
                prompt_version_id=version.id,
            ),
            model_id=model_id,
            asset_object_key=asset_object_key,
            inspection_criteria=(system_instruction, user_input),
        )
        response = asyncio.run(executor.inspect_image(request, provider_id=provider_id))
    finally:
        asyncio.run(client.aclose())

    severity_rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    severities = [
        str(finding.get("severity", "medium")).strip().lower()
        for finding in response.findings
    ]
    if any(severity not in severity_rank for severity in severities):
        overall_severity = "high"
    else:
        overall_severity = max(
            severities,
            key=lambda value: severity_rank[value],
            default="none" if response.passed else "high",
        )
    suggestions = [
        suggestion
        for finding in response.findings
        for suggestion in (
            finding.get("revision_suggestion")
            or finding.get("suggestion")
            or finding.get("recommended_action"),
        )
        if isinstance(suggestion, str) and suggestion.strip()
    ]
    report = validate_structured_output(
        {
            "findings": [dict(finding) for finding in response.findings],
            "overall_severity": overall_severity,
            "revision_suggestions": suggestions,
            "human_review_required": True,
        },
        dict(version.output_schema_json),
    )
    passed = response.passed and overall_severity not in {"high", "critical"}
    return {
        "passed": passed,
        "report": report,
        "provider_id": provider_id,
        "model_id": model_id,
        "prompt_version_id": str(version.id),
    }


def _complete_image(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    task_id_value = payload_ref.get("marketing_task_id")
    requirement_id_value = payload_ref.get("requirement_snapshot_id")
    strategy_id_value = payload_ref.get("strategy_snapshot_id")
    strategy_fingerprint = payload_ref.get("strategy_fingerprint")
    if not all(
        isinstance(value, str)
        for value in (
            task_id_value,
            requirement_id_value,
            strategy_id_value,
            strategy_fingerprint,
        )
    ):
        raise _safe_error("AI_IMAGE_PAYLOAD_INVALID", "Image generation payload is invalid.")
    try:
        task_id = UUID(str(task_id_value))
        requirement_id = UUID(str(requirement_id_value))
        strategy_id = UUID(str(strategy_id_value))
    except ValueError as exc:
        raise _safe_error("AI_IMAGE_PAYLOAD_INVALID", "Image generation payload is invalid.") from exc
    revision_instruction = payload_ref.get("revision_instruction", "")
    if not isinstance(revision_instruction, str) or len(revision_instruction) > 4000:
        raise _safe_error(
            "AI_IMAGE_REVISION_INVALID",
            "Image revision instruction is invalid.",
        )
    revision_instruction = revision_instruction.strip() or (
        "Create a new promotional image that follows the confirmed marketing strategy."
    )

    with _session_factory()() as db:
        job = db.get(Job, context.job_id)
        task = db.scalar(
            select(MarketingTask)
            .where(
                MarketingTask.id == task_id,
                MarketingTask.store_id == context.store_id,
            )
            .with_for_update()
        )
        requirement = db.scalar(
            select(RequirementSnapshot).where(
                RequirementSnapshot.id == requirement_id,
                RequirementSnapshot.task_id == task_id,
                RequirementSnapshot.store_id == context.store_id,
            )
        )
        strategy = db.scalar(
            select(StrategySnapshot).where(
                StrategySnapshot.id == strategy_id,
                StrategySnapshot.task_id == task_id,
                StrategySnapshot.store_id == context.store_id,
            )
        )
        if (
            job is None
            or job.marketing_task_id != task_id
            or task is None
            or requirement is None
            or strategy is None
            or task.current_requirement_snapshot_id != requirement_id
            or task.current_strategy_snapshot_id != strategy_id
            or strategy.content_fingerprint != strategy_fingerprint
        ):
            raise _safe_error(
                "AI_IMAGE_INPUT_STALE",
                "The confirmed strategy or requirement changed before image generation.",
            )
        step = db.scalar(
            select(TaskStep).where(
                TaskStep.store_id == task.store_id,
                TaskStep.task_id == task.id,
                TaskStep.step_key == "image_production_review",
            )
        )
        if step is None or step.status != "running":
            raise _safe_error(
                "AI_IMAGE_STEP_NOT_RUNNING",
                "The image production step is not running.",
            )
        business_facts = _business_fact_snapshots(
            db, task=task, requirement=requirement
        )
        source_asset = _resolve_source_asset(
            db,
            task=task,
            store_id=task.store_id,
            business_facts=business_facts,
            explicit_asset_id=payload_ref.get("source_media_asset_id"),
        )
        image_prompt_version = _published_prompt(
            db, task_type="image_prompt", capability="text"
        )
        image_task_type = "image_edit" if source_asset is not None else "image_generation"
        image_version = _published_prompt(
            db, task_type=image_task_type, capability="image"
        )
        vision_version = _published_prompt(
            db, task_type="visual_quality_check", capability="vision"
        )
        base_variables = _image_prompt_variables(
            image_prompt_version,
            task=task,
            requirement=requirement,
            strategy=strategy,
            business_facts=business_facts,
            revision_instruction=revision_instruction,
            source_asset=source_asset,
        )
        store_id = task.store_id

    text_executor, text_client, text_provider_id, text_model_id = _load_executor()
    try:
        image_prompt_output = _call_text_provider(
            context=context,
            job=job,
            task=task,
            version=image_prompt_version,
            variables=base_variables,
            provider_id=text_provider_id,
            model_id=text_model_id,
            executor=text_executor,
            idempotency_key=_operation_idempotency_key(job, "image-prompt"),
        )
    finally:
        asyncio.run(text_client.aclose())

    visual_prompt_value = image_prompt_output.get("prompt")
    negative_prompt_value = image_prompt_output.get("negative_prompt")
    visual_prompt = (
        visual_prompt_value.strip() if isinstance(visual_prompt_value, str) else ""
    )
    negative_prompt = (
        negative_prompt_value.strip()
        if isinstance(negative_prompt_value, str)
        else ""
    )
    aspect_ratio = image_prompt_output.get("aspect_ratio", "1:1")
    if not visual_prompt:
        raise _safe_error(
            "AI_IMAGE_PROMPT_EMPTY",
            "The published image prompt returned an empty visual prompt.",
        )
    image_variables = _image_prompt_variables(
        image_version,
        task=task,
        requirement=requirement,
        strategy=strategy,
        business_facts=business_facts,
        revision_instruction=revision_instruction,
        source_asset=source_asset,
        extra_variables={
            "image_prompt": visual_prompt,
            "prompt": visual_prompt,
            "negative_prompt": negative_prompt,
            "aspect_ratio": aspect_ratio,
        },
    )
    image_system, image_user = render_published_prompt(image_version, image_variables)
    provider_prompt = "\n\n".join(
        part for part in (
            image_system,
            image_user,
            f"Visual direction: {visual_prompt}",
            f"Avoid: {negative_prompt}" if negative_prompt else "",
        ) if part
    )
    if len(provider_prompt) > 30000:
        raise _safe_error(
            "AI_IMAGE_PROMPT_TOO_LONG",
            "The rendered image generation prompt exceeds the provider limit.",
        )
    width, height = _image_size(aspect_ratio)
    output_mime_type = os.environ.get("AI_IMAGE_OUTPUT_MIME_TYPE", "image/png").strip()
    if output_mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise _safe_error(
            "AI_IMAGE_MIME_TYPE_INVALID",
            "AI_IMAGE_OUTPUT_MIME_TYPE must be PNG, JPEG or WebP.",
        )

    image_executor, image_client, image_provider_id, image_model_id = _load_executor(
        ProviderCapability.IMAGE, "AI_IMAGE_MODEL_ID"
    )
    try:
        image_context = ProviderCallContext(
            request_id=str(uuid4()),
            store_id=store_id,
            job_id=job.id,
            attempt_id=context.attempt_id,
            idempotency_key=_operation_idempotency_key(job, "image-generation"),
            marketing_task_id=task_id,
            prompt_version_id=image_version.id,
        )
        if source_asset is None:
            image_request = ImageGenerateRequest(
                context=image_context,
                model_id=image_model_id,
                prompt=provider_prompt,
                width=width,
                height=height,
                output_mime_type=output_mime_type,
            )
            image_result = asyncio.run(
                image_executor.generate_image(
                    image_request, provider_id=image_provider_id
                )
            )
        else:
            image_request = ImageEditRequest(
                context=image_context,
                model_id=image_model_id,
                prompt=provider_prompt,
                width=width,
                height=height,
                output_mime_type=output_mime_type,
                source_asset_object_key=source_asset.object_key,
            )
            image_result = asyncio.run(
                image_executor.edit_image(
                    image_request, provider_id=image_provider_id
                )
            )
    finally:
        asyncio.run(image_client.aclose())

    validate_structured_output(
        {
            "asset_object_key": image_result.asset_object_key,
            "sha256": image_result.sha256,
            "mime_type": image_result.mime_type,
            "width": image_result.width,
            "height": image_result.height,
        },
        dict(image_version.output_schema_json),
    )
    content, actual_width, actual_height = _verify_and_scan_image(image_result)
    context.check_control()

    vision_variables = _image_prompt_variables(
        vision_version,
        task=task,
        requirement=requirement,
        strategy=strategy,
        business_facts=business_facts,
        revision_instruction=revision_instruction,
        source_asset=source_asset,
        extra_variables={
            "image_prompt": visual_prompt,
            "negative_prompt": negative_prompt,
            "aspect_ratio": aspect_ratio,
            "image_width": actual_width,
            "image_height": actual_height,
            "image_mime_type": image_result.mime_type,
        },
    )
    vision = _vision_report(
        context=context,
        task=task,
        job=job,
        version=vision_version,
        variables=vision_variables,
        asset_object_key=image_result.asset_object_key,
    )
    context.check_control()

    content_hash = hashlib.sha256(content).hexdigest()
    input_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "task_id": str(task_id),
                "requirement_fingerprint": requirement.content_fingerprint,
                "strategy_fingerprint": strategy.content_fingerprint,
                "image_prompt_version_id": str(image_prompt_version.id),
                "image_version_id": str(image_version.id),
                "vision_version_id": str(vision_version.id),
                "source_asset_sha256": source_asset.sha256 if source_asset else None,
                "revision_instruction": revision_instruction,
                "job_idempotency_key": job.idempotency_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    try:
        with _session_factory().begin() as db:
            task = db.scalar(
                select(MarketingTask)
                .where(
                    MarketingTask.id == task_id,
                    MarketingTask.store_id == store_id,
                )
                .with_for_update()
            )
            step = db.scalar(
                select(TaskStep).where(
                    TaskStep.store_id == store_id,
                    TaskStep.task_id == task_id,
                    TaskStep.step_key == "image_production_review",
                ).with_for_update()
            )
            if (
                task is None
                or task.current_requirement_snapshot_id != requirement_id
                or task.current_strategy_snapshot_id != strategy_id
                or step is None
                or step.status != "running"
            ):
                raise _safe_error(
                    "AI_IMAGE_INPUT_STALE",
                    "The image step changed before generated output could be saved.",
                )
            artifact = db.scalar(
                select(Artifact)
                .where(
                    Artifact.store_id == store_id,
                    Artifact.task_id == task_id,
                    Artifact.artifact_type == "image",
                )
                .with_for_update()
            )
            if artifact is None:
                artifact = Artifact(
                    id=uuid4(),
                    store_id=store_id,
                    task_id=task_id,
                    artifact_type="image",
                )
                db.add(artifact)
                db.flush()
            artifact_version = db.scalar(
                select(ArtifactVersion).where(
                    ArtifactVersion.store_id == store_id,
                    ArtifactVersion.artifact_id == artifact.id,
                    ArtifactVersion.input_fingerprint == input_fingerprint,
                )
            )
            media_asset: MediaAsset | None = None
            if artifact_version is None:
                media_asset = db.scalar(
                    select(MediaAsset).where(
                        MediaAsset.object_key == image_result.asset_object_key
                    )
                )
                if media_asset is None:
                    child_version = 1
                    if source_asset is not None:
                        child_version = (
                            db.scalar(
                                select(func.max(MediaAsset.version_no)).where(
                                    MediaAsset.store_id == store_id,
                                    MediaAsset.parent_asset_id == source_asset.id,
                                )
                            )
                            or 0
                        ) + 1
                    media_asset = MediaAsset(
                        id=uuid4(),
                        store_id=store_id,
                        object_key=image_result.asset_object_key,
                        sha256=content_hash,
                        mime_type=image_result.mime_type,
                        byte_size=len(content),
                        width=actual_width,
                        height=actual_height,
                        asset_type="generated_image",
                        source_type="ai_generated",
                        source_ref=str(job.id),
                        parent_asset_id=source_asset.id if source_asset else None,
                        version_no=child_version,
                        derivation_instruction=revision_instruction or None,
                        status="ready",
                        created_by_user_id=task.created_by_user_id,
                    )
                    db.add(media_asset)
                    db.flush()
                elif (
                    media_asset.store_id != store_id
                    or media_asset.sha256 != content_hash
                    or media_asset.status != "ready"
                ):
                    raise _safe_error(
                        "AI_IMAGE_OBJECT_KEY_CONFLICT",
                        "The generated image storage key is already bound to another asset.",
                    )

                latest_version = db.scalar(
                    select(ArtifactVersion.version_no)
                    .where(
                        ArtifactVersion.store_id == store_id,
                        ArtifactVersion.artifact_id == artifact.id,
                    )
                    .order_by(ArtifactVersion.version_no.desc())
                    .limit(1)
                ) or 0
                artifact_version = ArtifactVersion(
                    id=uuid4(),
                    store_id=store_id,
                    artifact_id=artifact.id,
                    version_no=latest_version + 1,
                    source_type="ai_generated",
                    source_refs_json=[
                        {"type": "requirement_snapshot", "id": str(requirement_id)},
                        {"type": "strategy_snapshot", "id": str(strategy_id)},
                        {"type": "media_asset", "id": str(media_asset.id)},
                        {"type": "image_prompt_version", "id": str(image_prompt_version.id)},
                        {"type": "vision_prompt_version", "id": str(vision_version.id)},
                        *(
                            [{"type": "source_media_asset", "id": str(source_asset.id)}]
                            if source_asset is not None
                            else []
                        ),
                    ],
                    instruction=revision_instruction or "Generate image from confirmed strategy.",
                    content_json={
                        "media_asset_id": str(media_asset.id),
                        "mime_type": image_result.mime_type,
                        "width": actual_width,
                        "height": actual_height,
                        "byte_size": len(content),
                        "sha256": content_hash,
                        "vision_inspection": vision,
                        "image_prompt": visual_prompt,
                        "negative_prompt": negative_prompt,
                        "aspect_ratio": str(aspect_ratio),
                    },
                    content_ref=image_result.asset_object_key,
                    content_hash=content_hash,
                    provider_id=image_provider_id,
                    model_id=image_model_id,
                    prompt_version_id=image_version.id,
                    input_fingerprint=input_fingerprint,
                    created_by_user_id=task.created_by_user_id,
                )
                db.add(artifact_version)
                db.flush()
            if media_asset is None:
                content_metadata = dict(artifact_version.content_json or {})
                media_asset_id_value = content_metadata.get("media_asset_id")
                vision_value = content_metadata.get("vision_inspection")
                if not isinstance(media_asset_id_value, str) or not isinstance(vision_value, dict):
                    raise _safe_error(
                        "AI_IMAGE_REPLAY_METADATA_INVALID",
                        "The persisted image artifact is missing media or inspection metadata.",
                    )
                try:
                    media_asset_id = UUID(media_asset_id_value)
                except ValueError as exc:
                    raise _safe_error(
                        "AI_IMAGE_REPLAY_METADATA_INVALID",
                        "The persisted image artifact references an invalid media asset.",
                    ) from exc
                media_asset = db.get(MediaAsset, media_asset_id)
                if media_asset is None or media_asset.store_id != store_id:
                    raise _safe_error(
                        "AI_IMAGE_REPLAY_ASSET_MISSING",
                        "The persisted image artifact references an unavailable media asset.",
                    )
                vision = vision_value
            artifact.current_version_id = artifact_version.id
            task.version += 1
            step.status = "waiting_for_user"
            step.version += 1
            step.finished_at = datetime.now(UTC)
            step.output_refs_json = [
                {
                    "type": "artifact_version",
                    "artifact_id": str(artifact.id),
                    "artifact_version_id": str(artifact_version.id),
                },
                {
                    "type": "media_asset",
                    "id": str(media_asset.id),
                },
                {
                    "type": "vision_inspection",
                    "passed": bool(vision["passed"]),
                    "prompt_version_id": str(vision_version.id),
                },
            ]
            step.blocked_by_json = []
            step.block_code = None if vision["passed"] else "VISION_ISSUES_FOUND"
            step.block_detail_json = None if vision["passed"] else vision
            db.add(
                OutboxEvent(
                    aggregate_type="artifact_version",
                    aggregate_id=artifact_version.id,
                    event_type="content.artifact_version_created",
                    schema_version=1,
                    payload_json={
                        "schema_version": 1,
                        "store_id": str(store_id),
                        "task_id": str(task_id),
                        "artifact_id": str(artifact.id),
                        "artifact_version_id": str(artifact_version.id),
                    },
                    dedupe_key=f"content.artifact_version_created:{artifact_version.id}",
                )
            )
    except (JobExecutionError, SQLAlchemyError):
        _delete_generated_object(image_result.asset_object_key)
        raise

    return {
        "schema_version": 1,
        "marketing_task_id": str(task_id),
        "artifact_id": str(artifact.id),
        "artifact_version_id": str(artifact_version.id),
        "media_asset_id": str(media_asset.id),
        "vision_passed": bool(vision["passed"]),
        "prompt_version_id": str(image_version.id),
        "vision_prompt_version_id": str(vision_version.id),
        "output_type": "image",
    }


@register_job_handler("marketing_task.generate_image")
def execute_marketing_image(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    if context.store_id is None or payload_ref.get("schema_version") != 1:
        raise _safe_error("AI_IMAGE_PAYLOAD_INVALID", "Image generation payload is invalid.")
    return _complete_image(context, payload_ref)
