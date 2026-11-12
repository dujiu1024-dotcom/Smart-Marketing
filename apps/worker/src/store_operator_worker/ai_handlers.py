from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.ai_gateway import (
    AIProviderExecutor,
    EnvironmentSecretResolver,
    HttpProviderEnvironmentConfig,
    ProviderCallContext,
    ProviderCapability,
    ProviderError,
    ProviderTaskType,
    SecretStoreProviderResolver,
    TextGenerateRequest,
    build_http_provider_registry,
    parse_and_validate_structured_output,
    render_published_prompt,
    validate_prompt_task_contract,
)
from store_operator.channels.secret_store import AwsSecretsManagerStore, SecretStoreError
from store_operator.models import (
    Artifact,
    ArtifactVersion,
    Job,
    MarketingTask,
    PromptTemplate,
    PromptVersion,
    RequirementSnapshot,
    StrategySnapshot,
    TaskStep,
)
from store_operator_worker.handlers import (
    JobExecutionContext,
    JobExecutionError,
    register_job_handler,
)
from store_operator_worker.tasks import SessionLocal


def _safe_error(code: str, summary: str) -> JobExecutionError:
    return JobExecutionError(code, summary, retryable=False)


def _provider_secret_resolver(secret_ref: str):
    if secret_ref.startswith("env://"):
        return EnvironmentSecretResolver()
    region = (
        os.environ.get("AI_SECRET_STORE_REGION")
        or os.environ.get("CHANNEL_SECRET_STORE_REGION")
        or os.environ.get("AWS_REGION")
        or ""
    )
    if not region:
        raise SecretStoreError("AI secret store region is not configured")
    return SecretStoreProviderResolver(AwsSecretsManagerStore(region_name=region))


def _load_executor() -> tuple[AIProviderExecutor, httpx.AsyncClient, str, str]:
    config = HttpProviderEnvironmentConfig.from_environment(os.environ)
    if config is None:
        raise _safe_error(
            "AI_PROVIDER_NOT_CONFIGURED",
            "AI provider configuration is not available to the Worker.",
        )
    resolver = _provider_secret_resolver(config.secret_ref)
    client = httpx.AsyncClient()
    try:
        registry = build_http_provider_registry(
            config,
            secret_resolver=resolver,
            client=client,
        )
    except Exception:
        asyncio.run(client.aclose())
        raise _safe_error(
            "AI_PROVIDER_CONFIGURATION_INVALID",
            "AI provider configuration or Secret reference could not be resolved.",
        )
    model_id = os.environ.get("AI_TEXT_MODEL_ID", "").strip()
    text_models = config.models.get(ProviderCapability.TEXT, ())
    if not model_id and len(text_models) == 1:
        model_id = text_models[0]
    if not model_id or model_id not in text_models:
        asyncio.run(client.aclose())
        raise _safe_error(
            "AI_TEXT_MODEL_NOT_CONFIGURED",
            "A supported AI_TEXT_MODEL_ID must be configured for text generation.",
        )
    executor = AIProviderExecutor(
        registry=registry,
        session_context_factory=SessionLocal.begin,
    )
    return executor, client, config.provider_id, model_id


def _published_prompt(
    db: Session,
    *,
    task_type: str,
) -> PromptVersion:
    template_key = os.environ.get(
        f"AI_PROMPT_TEMPLATE_KEY_{task_type.upper()}",
        "",
    ).strip()
    query = select(PromptTemplate).where(
        PromptTemplate.task_type == task_type,
        PromptTemplate.capability == "text",
        PromptTemplate.status == "active",
        PromptTemplate.current_published_version_id.is_not(None),
    )
    if template_key:
        query = query.where(PromptTemplate.template_key == template_key)
    templates = db.scalars(query.order_by(PromptTemplate.industry_key, PromptTemplate.id)).all()
    if len(templates) != 1:
        raise _safe_error(
            "AI_PROMPT_TEMPLATE_AMBIGUOUS",
            "Exactly one active published prompt template must match this generation task.",
        )
    version = db.get(PromptVersion, templates[0].current_published_version_id)
    if version is None or version.prompt_template_id != templates[0].id:
        raise _safe_error(
            "AI_PROMPT_VERSION_UNAVAILABLE",
            "The active published prompt version is unavailable.",
        )
    return version


def _prompt_variables(
    version: PromptVersion,
    *,
    task: MarketingTask,
    requirement: RequirementSnapshot,
    strategy: StrategySnapshot | None,
) -> dict[str, object]:
    requirement_payload = dict(requirement.payload_json)
    values: dict[str, object] = {
        "task_title": task.title,
        "task_type": task.task_type,
        "requirement": requirement_payload.get("requirement", {}),
        "requirements": requirement_payload.get("requirement", {}),
        "business_facts": requirement_payload.get("business_facts", []),
        "task_options": dict(task.task_options_json),
        "strategy": (
            dict(strategy.payload_json).get("strategy", {})
            if strategy is not None
            else dict(task.strategy_draft_json)
        ),
        "selected_channels": dict(task.task_options_json).get(
            "selected_channel_keys", []
        ),
    }
    schema = version.variables_schema_json
    properties = schema.get("properties")
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise _safe_error(
            "AI_PROMPT_VARIABLE_SCHEMA_INVALID",
            "The published prompt variable schema is invalid.",
        )
    unknown = set(required) - set(values)
    if unknown:
        raise _safe_error(
            "AI_PROMPT_VARIABLE_UNSUPPORTED",
            "The published prompt requires variables not supplied by the marketing task.",
        )
    return {key: values[key] for key in properties if key in values}


def _call_text_provider(
    *,
    context: JobExecutionContext,
    job: Job,
    task: MarketingTask,
    version: PromptVersion,
    variables: dict[str, object],
    provider_id: str,
    model_id: str,
    executor: AIProviderExecutor,
) -> dict[str, object]:
    system_instruction, user_input = render_published_prompt(version, variables)
    request = TextGenerateRequest(
        context=ProviderCallContext(
            request_id=str(uuid4()),
            store_id=task.store_id,
            job_id=job.id,
            attempt_id=context.attempt_id,
            idempotency_key=job.idempotency_key,
            marketing_task_id=task.id,
            prompt_version_id=version.id,
        ),
        model_id=model_id,
        system_instruction=system_instruction,
        user_input=user_input,
        output_schema=dict(version.output_schema_json),
    )
    response = asyncio.run(executor.generate_text(request, provider_id=provider_id))
    if response.structured_output is not None:
        from store_operator.ai_gateway import validate_structured_output

        return validate_structured_output(
            response.structured_output,
            dict(version.output_schema_json),
        )
    return parse_and_validate_structured_output(
        response.text,
        dict(version.output_schema_json),
    )


def _complete_strategy(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    task_id_value = payload_ref.get("marketing_task_id")
    requirement_id_value = payload_ref.get("requirement_snapshot_id")
    expected_fingerprint = payload_ref.get("requirement_fingerprint")
    if not all(isinstance(value, str) for value in (
        task_id_value, requirement_id_value, expected_fingerprint
    )):
        raise _safe_error("AI_STRATEGY_PAYLOAD_INVALID", "Strategy generation payload is invalid.")
    try:
        task_id = UUID(str(task_id_value))
        requirement_id = UUID(str(requirement_id_value))
    except ValueError as exc:
        raise _safe_error("AI_STRATEGY_PAYLOAD_INVALID", "Strategy generation payload is invalid.") from exc

    with SessionLocal() as db:
        job = db.get(Job, context.job_id)
        task = db.scalar(
            select(MarketingTask)
            .where(MarketingTask.id == task_id, MarketingTask.store_id == context.store_id)
            .with_for_update()
        )
        requirement = db.scalar(
            select(RequirementSnapshot).where(
                RequirementSnapshot.id == requirement_id,
                RequirementSnapshot.task_id == task_id,
                RequirementSnapshot.store_id == context.store_id,
            )
        )
        if (
            job is None or job.marketing_task_id != task_id
            or task is None or task.current_requirement_snapshot_id != requirement_id
            or requirement is None or requirement.content_fingerprint != expected_fingerprint
        ):
            raise _safe_error(
                "AI_STRATEGY_INPUT_STALE",
                "The confirmed requirement snapshot changed before strategy generation.",
            )
        version = _published_prompt(db, task_type="marketing_strategy")
        variables = _prompt_variables(
            version, task=task, requirement=requirement, strategy=None
        )
        task_id = task.id
        store_id = task.store_id

    executor, client, provider_id, model_id = _load_executor()
    try:
        output = _call_text_provider(
            context=context, job=job, task=task, version=version,
            variables=variables, provider_id=provider_id, model_id=model_id,
            executor=executor,
        )
    finally:
        asyncio.run(client.aclose())

    context.check_control()
    with SessionLocal.begin() as db:
        task = db.scalar(
            select(MarketingTask)
            .where(MarketingTask.id == task_id, MarketingTask.store_id == store_id)
            .with_for_update()
        )
        step = db.scalar(
            select(TaskStep).where(
                TaskStep.store_id == store_id,
                TaskStep.task_id == task_id,
                TaskStep.step_key == "strategy_confirmation",
            ).with_for_update()
        )
        if (
            task is None or task.current_requirement_snapshot_id != requirement_id
            or step is None or step.status != "running"
        ):
            raise _safe_error(
                "AI_STRATEGY_INPUT_STALE",
                "The strategy step changed before generated output could be saved.",
            )
        task.strategy_draft_json = output
        task.lifecycle_status = "waiting_for_user"
        task.version += 1
        step.status = "waiting_for_user"
        step.version += 1
        step.finished_at = datetime.now(UTC)
        step.output_refs_json = [{
            "type": "strategy_draft",
            "prompt_version_id": str(version.id),
        }]
        step.blocked_by_json = []
        step.block_code = None
        step.block_detail_json = None
    return {
        "schema_version": 1,
        "marketing_task_id": str(task_id),
        "prompt_version_id": str(version.id),
        "output_type": "strategy_draft",
    }


def _complete_copy(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    task_id_value = payload_ref.get("marketing_task_id")
    requirement_id_value = payload_ref.get("requirement_snapshot_id")
    strategy_id_value = payload_ref.get("strategy_snapshot_id")
    strategy_fingerprint = payload_ref.get("strategy_fingerprint")
    if not all(isinstance(value, str) for value in (
        task_id_value, requirement_id_value, strategy_id_value, strategy_fingerprint
    )):
        raise _safe_error("AI_COPY_PAYLOAD_INVALID", "Copy generation payload is invalid.")
    try:
        task_id = UUID(str(task_id_value))
        requirement_id = UUID(str(requirement_id_value))
        strategy_id = UUID(str(strategy_id_value))
    except ValueError as exc:
        raise _safe_error("AI_COPY_PAYLOAD_INVALID", "Copy generation payload is invalid.") from exc

    with SessionLocal() as db:
        job = db.get(Job, context.job_id)
        task = db.scalar(
            select(MarketingTask)
            .where(MarketingTask.id == task_id, MarketingTask.store_id == context.store_id)
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
            job is None or job.marketing_task_id != task_id
            or task is None or requirement is None or strategy is None
            or task.current_requirement_snapshot_id != requirement_id
            or task.current_strategy_snapshot_id != strategy_id
            or strategy.content_fingerprint != strategy_fingerprint
        ):
            raise _safe_error(
                "AI_COPY_INPUT_STALE",
                "The confirmed strategy or requirement snapshot changed before copy generation.",
            )
        version = _published_prompt(db, task_type="copy_generation")
        variables = _prompt_variables(
            version, task=task, requirement=requirement, strategy=strategy
        )
        store_id = task.store_id

    executor, client, provider_id, model_id = _load_executor()
    try:
        output = _call_text_provider(
            context=context, job=job, task=task, version=version,
            variables=variables, provider_id=provider_id, model_id=model_id,
            executor=executor,
        )
    finally:
        asyncio.run(client.aclose())

    context.check_control()
    canonical = json.dumps(
        output, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    content_hash = hashlib.sha256(canonical).hexdigest()
    input_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "task_id": str(task_id),
                "requirement_fingerprint": requirement.content_fingerprint,
                "strategy_fingerprint": strategy.content_fingerprint,
                "prompt_version_id": str(version.id),
                "job_idempotency_key": job.idempotency_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with SessionLocal.begin() as db:
        task = db.scalar(
            select(MarketingTask)
            .where(MarketingTask.id == task_id, MarketingTask.store_id == store_id)
            .with_for_update()
        )
        step = db.scalar(
            select(TaskStep).where(
                TaskStep.store_id == store_id,
                TaskStep.task_id == task_id,
                TaskStep.step_key == "copy_production_review",
            ).with_for_update()
        )
        if (
            task is None or task.current_requirement_snapshot_id != requirement_id
            or task.current_strategy_snapshot_id != strategy_id
            or step is None or step.status != "running"
        ):
            raise _safe_error(
                "AI_COPY_INPUT_STALE",
                "The copy step changed before generated output could be saved.",
            )
        artifact = db.scalar(
            select(Artifact).where(
                Artifact.store_id == store_id,
                Artifact.task_id == task_id,
                Artifact.artifact_type == "copy",
            ).with_for_update()
        )
        if artifact is None:
            artifact = Artifact(
                id=uuid4(), store_id=store_id, task_id=task_id,
                artifact_type="copy",
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
        if artifact_version is None:
            latest_version = db.scalar(
                select(ArtifactVersion.version_no).where(
                    ArtifactVersion.store_id == store_id,
                    ArtifactVersion.artifact_id == artifact.id,
                ).order_by(ArtifactVersion.version_no.desc()).limit(1)
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
                ],
                instruction="Generate marketing copy from confirmed task strategy.",
                content_json=output,
                content_hash=content_hash,
                provider_id=provider_id,
                model_id=model_id,
                prompt_version_id=version.id,
                input_fingerprint=input_fingerprint,
            )
            db.add(artifact_version)
            db.flush()
        artifact.current_version_id = artifact_version.id
        task.version += 1
        step.status = "waiting_for_user"
        step.version += 1
        step.finished_at = datetime.now(UTC)
        step.output_refs_json = [{
            "type": "artifact_version",
            "artifact_id": str(artifact.id),
            "artifact_version_id": str(artifact_version.id),
        }]
        step.blocked_by_json = []
        step.block_code = None
        step.block_detail_json = None
    return {
        "schema_version": 1,
        "marketing_task_id": str(task_id),
        "artifact_id": str(artifact.id),
        "artifact_version_id": str(artifact_version.id),
        "prompt_version_id": str(version.id),
        "output_type": "copy",
    }


@register_job_handler("marketing_task.generate_strategy")
def execute_marketing_strategy(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    if context.store_id is None or payload_ref.get("schema_version") != 1:
        raise _safe_error("AI_STRATEGY_PAYLOAD_INVALID", "Strategy generation payload is invalid.")
    return _complete_strategy(context, payload_ref)


@register_job_handler("marketing_task.generate_copy")
def execute_marketing_copy(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    if context.store_id is None or payload_ref.get("schema_version") != 1:
        raise _safe_error("AI_COPY_PAYLOAD_INVALID", "Copy generation payload is invalid.")
    return _complete_copy(context, payload_ref)
