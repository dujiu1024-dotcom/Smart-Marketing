from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.models.job_runtime import (
    AIInvocation,
    AIUsageRecord,
    Job,
    JobAttempt,
)

_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_PARAMETER_KEYS = frozenset(
    {
        "temperature",
        "top_p",
        "max_output_tokens",
        "width",
        "height",
        "aspect_ratio",
        "output_mime_type",
        "quality",
        "seed",
        "steps",
        "guidance_scale",
        "num_images",
    }
)


class AIInvocationTransitionError(Exception):
    """An AI invocation cannot make the requested lifecycle transition."""


def _safe_parameter_snapshot(
    values: dict[str, object] | None,
) -> dict[str, object]:
    if not values:
        return {}
    safe: dict[str, object] = {}
    for key, value in values.items():
        if key not in _SAFE_PARAMETER_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value[:120] if isinstance(value, str) else value
    return safe

def _safe_response_ref(
    values: dict[str, object] | None,
) -> dict[str, object] | None:
    if not values:
        return None
    allowed = {"schema_version", "object_key", "sha256", "mime_type", "width", "height"}
    safe: dict[str, object] = {
        key: value
        for key, value in values.items()
        if key in allowed
        and (isinstance(value, (str, int, bool)) or value is None)
    }
    if not isinstance(safe.get("schema_version"), int) or isinstance(
        safe.get("schema_version"), bool
    ):
        raise ValueError("response_ref requires an integer schema_version")
    if not isinstance(safe.get("object_key"), str):
        raise ValueError("response_ref requires an object_key reference")
    return safe


def start_ai_invocation(
    db: Session,
    *,
    store_id: UUID | None,
    job_id: UUID | None,
    attempt_id: UUID | None,
    provider_key: str,
    model_key: str,
    capability: str,
    request_fingerprint: str,
    task_id: UUID | None = None,
    prompt_version_id: UUID | None = None,
    parameter_snapshot: dict[str, object] | None = None,
    now: datetime | None = None,
) -> AIInvocation:
    if not _FINGERPRINT_PATTERN.fullmatch(request_fingerprint):
        raise ValueError("request_fingerprint must be a lowercase SHA-256 hex digest")
    if not provider_key.strip() or len(provider_key) > 100:
        raise ValueError("provider_key must contain 1-100 characters")
    if not model_key.strip() or len(model_key) > 150:
        raise ValueError("model_key must contain 1-150 characters")
    if not capability.strip() or len(capability) > 24:
        raise ValueError("capability must contain 1-24 characters")
    if attempt_id is not None and job_id is None:
        raise ValueError("attempt_id requires job_id")
    if job_id is not None:
        job = db.get(Job, job_id)
        if job is None or job.store_id != store_id:
            raise LookupError("Job not found in the requested store")
        if task_id is None:
            task_id = job.marketing_task_id
        elif task_id != job.marketing_task_id:
            raise ValueError("task_id does not match the referenced Job")
    if attempt_id is not None:
        attempt = db.get(JobAttempt, attempt_id)
        if attempt is None or attempt.job_id != job_id:
            raise ValueError("attempt_id does not belong to job_id")
    current_time = now or datetime.now(UTC)
    invocation = AIInvocation(
        id=uuid4(),
        store_id=store_id,
        task_id=task_id,
        job_id=job_id,
        attempt_id=attempt_id,
        provider_key=provider_key.strip(),
        model_key=model_key.strip(),
        capability=capability.strip(),
        prompt_version_id=prompt_version_id,
        request_fingerprint=request_fingerprint,
        parameter_snapshot_json=_safe_parameter_snapshot(parameter_snapshot),
        status="running",
        created_at=current_time,
    )
    db.add(invocation)
    db.flush()
    return invocation


def complete_ai_invocation(
    db: Session,
    *,
    invocation_id: UUID,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    image_units: Decimal | None = None,
    cost_amount: Decimal | None = None,
    currency: str | None = None,
    metering_source: str = "provider_reported",
    provider_request_id: str | None = None,
    response_ref: dict[str, object] | None = None,
    duration_ms: int | None = None,
    now: datetime | None = None,
) -> AIInvocation:
    current_time = now or datetime.now(UTC)
    if input_tokens is not None and input_tokens < 0:
        raise ValueError("input_tokens cannot be negative")
    if output_tokens is not None and output_tokens < 0:
        raise ValueError("output_tokens cannot be negative")
    if image_units is not None and image_units < 0:
        raise ValueError("image_units cannot be negative")
    if cost_amount is not None and cost_amount < 0:
        raise ValueError("cost_amount cannot be negative")
    if (cost_amount is None) != (currency is None):
        raise ValueError("cost_amount and currency must be supplied together")
    if currency is not None and (
        len(currency) != 3 or not currency.isalpha() or not currency.isupper()
    ):
        raise ValueError("currency must be a three-letter uppercase code")
    if not metering_source.strip() or len(metering_source) > 40:
        raise ValueError("metering_source must contain 1-40 characters")
    if provider_request_id is not None and len(provider_request_id) > 200:
        raise ValueError("provider_request_id cannot exceed 200 characters")
    safe_response_ref = _safe_response_ref(response_ref) if response_ref else None

    invocation = db.scalar(
        select(AIInvocation)
        .where(AIInvocation.id == invocation_id)
        .with_for_update()
    )
    if invocation is None:
        raise LookupError("AI invocation not found")
    elapsed_ms = duration_ms
    if elapsed_ms is None:
        elapsed_ms = max(
            0, int((current_time - invocation.created_at).total_seconds() * 1000)
        )
    if elapsed_ms < 0:
        raise ValueError("duration_ms cannot be negative")

    values = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "image_units": image_units,
        "cost_amount": cost_amount,
        "currency": currency,
        "metering_source": metering_source.strip(),
    }
    usage = db.get(AIUsageRecord, invocation.id)
    if invocation.status == "succeeded":
        if (
            usage is None
            or any(getattr(usage, key) != value for key, value in values.items())
            or invocation.provider_request_id != provider_request_id
            or invocation.response_ref_json != safe_response_ref
        ):
            raise AIInvocationTransitionError(
                "A completed AI invocation cannot be completed with different usage"
            )
        return invocation
    if invocation.status != "running":
        raise AIInvocationTransitionError("Only running AI invocations can succeed")
    if usage is not None and any(
        getattr(usage, key) != value for key, value in values.items()
    ):
        raise AIInvocationTransitionError(
            "Existing AI usage cannot be overwritten with different values"
        )

    invocation.status = "succeeded"
    invocation.provider_request_id = provider_request_id
    invocation.response_ref_json = safe_response_ref
    invocation.duration_ms = elapsed_ms
    invocation.finished_at = current_time
    if usage is None:
        db.add(AIUsageRecord(invocation_id=invocation.id, **values))
    db.flush()
    return invocation


def fail_ai_invocation(
    db: Session,
    *,
    invocation_id: UUID,
    error_code: str,
    duration_ms: int | None = None,
    now: datetime | None = None,
) -> AIInvocation:
    current_time = now or datetime.now(UTC)
    if not re.fullmatch(r"[A-Z0-9_.-]{1,100}", error_code.strip()):
        raise ValueError("error_code must be a normalized error identifier")
    invocation = db.scalar(
        select(AIInvocation)
        .where(AIInvocation.id == invocation_id)
        .with_for_update()
    )
    if invocation is None:
        raise LookupError("AI invocation not found")
    if invocation.status == "failed" and invocation.error_code == error_code:
        return invocation
    if invocation.status != "running":
        raise AIInvocationTransitionError("Only running AI invocations can fail")
    elapsed_ms = duration_ms
    if elapsed_ms is None:
        elapsed_ms = max(
            0, int((current_time - invocation.created_at).total_seconds() * 1000)
        )
    if elapsed_ms < 0:
        raise ValueError("duration_ms cannot be negative")
    invocation.status = "failed"
    invocation.error_code = error_code.strip()
    invocation.duration_ms = elapsed_ms
    invocation.finished_at = current_time
    db.flush()
    return invocation


def cancel_ai_invocation(
    db: Session,
    *,
    invocation_id: UUID,
    now: datetime | None = None,
) -> AIInvocation:
    current_time = now or datetime.now(UTC)
    invocation = db.scalar(
        select(AIInvocation)
        .where(AIInvocation.id == invocation_id)
        .with_for_update()
    )
    if invocation is None:
        raise LookupError("AI invocation not found")
    if invocation.status == "cancelled":
        return invocation
    if invocation.status not in {"queued", "running"}:
        raise AIInvocationTransitionError(
            "Only queued or running AI invocations can be cancelled"
        )
    invocation.status = "cancelled"
    invocation.finished_at = current_time
    db.flush()
    return invocation
