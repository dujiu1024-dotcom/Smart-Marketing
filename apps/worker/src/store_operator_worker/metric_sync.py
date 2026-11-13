"""指标同步 Worker：商家授权采集（D-01 路径 A）。

链路：Job → 商家授权采集器（持有本人已登录浏览器 profile）→ Easel 解析层
归一化 → 证据门禁落库 → 游标与状态回写。

真实性档固定为 `merchant_authorized_scrape`，不得标记为 `official_api`，
也不进入「已核验官方数据」汇总。采集器未配置时任务明确失败为配置缺口，
不生成任何占位数据。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from store_operator.config import settings
from store_operator.effects.easel_parsing import (
    READBACK_LOGIN_REQUIRED,
    READBACK_VERIFIED,
)
from store_operator.effects.metric_ingest import (
    get_or_create_cursor,
    ingest_snapshot,
    mark_cursor_failure,
    mark_cursor_running,
    mark_cursor_success,
)
from store_operator.models import ChannelAccount

from store_operator_worker.handlers import (
    JobExecutionContext,
    JobExecutionError,
    register_job_handler,
)

logger = logging.getLogger(__name__)

JOB_TYPE = "metrics.sync_channel_account.v1"
VALID_SCOPES = ("account", "work", "store")
COLLECTOR_SCHEMA_VERSION = 1


class CollectorError(Exception):
    def __init__(
        self,
        code: str,
        summary: str,
        *,
        retryable: bool,
        cursor_status: str = "failed",
    ) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary
        self.retryable = retryable
        self.cursor_status = cursor_status


class MerchantAuthorizedCollector:
    """商家授权采集器的内部 HTTP 契约客户端。"""

    def __init__(self) -> None:
        self.base_url = (settings.metric_collector_base_url or "").rstrip("/")
        self.token = settings.metric_collector_token
        self.timeout = settings.metric_collector_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(settings.metric_sync_enabled and self.base_url)

    def collect(
        self,
        *,
        platform: str,
        external_account_id: str,
        scope: str,
        since: datetime | None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = {
            "schema_version": COLLECTOR_SCHEMA_VERSION,
            "platform": platform,
            "account_external_id": external_account_id,
            "scope": scope,
            "since": since.isoformat() if since else None,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/collect",
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise CollectorError(
                "METRIC_COLLECTOR_TIMEOUT",
                "商家授权采集器响应超时。",
                retryable=True,
                cursor_status="unavailable",
            ) from exc
        except httpx.HTTPError as exc:
            raise CollectorError(
                "METRIC_COLLECTOR_UNAVAILABLE",
                "商家授权采集器暂时不可用。",
                retryable=True,
                cursor_status="unavailable",
            ) from exc
        if response.status_code in {401, 403}:
            raise CollectorError(
                "METRIC_COLLECTOR_LOGIN_REQUIRED",
                "商家授权已失效或未登录，请重新授权后再同步。",
                retryable=False,
                cursor_status="login_required",
            )
        if response.status_code == 404:
            raise CollectorError(
                "METRIC_SCOPE_UNSUPPORTED",
                "该渠道暂不支持此观测范围的采集。",
                retryable=False,
                cursor_status="unsupported",
            )
        if response.status_code == 429:
            raise CollectorError(
                "METRIC_COLLECTOR_RATE_LIMITED",
                "采集频率受限，请稍后重试。",
                retryable=True,
                cursor_status="unavailable",
            )
        if response.status_code >= 500:
            raise CollectorError(
                "METRIC_COLLECTOR_UNAVAILABLE",
                "商家授权采集器暂时不可用。",
                retryable=True,
                cursor_status="unavailable",
            )
        if response.status_code != 200:
            raise CollectorError(
                "METRIC_COLLECTOR_REJECTED",
                "商家授权采集器拒绝了本次采集请求。",
                retryable=False,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CollectorError(
                "METRIC_COLLECTOR_INVALID_RESPONSE",
                "商家授权采集器返回内容无法解析。",
                retryable=False,
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise CollectorError(
                "METRIC_COLLECTOR_INVALID_RESPONSE",
                "商家授权采集器返回内容不符合约定格式。",
                retryable=False,
            )
        return payload


def _captured_at(payload: dict[str, Any]) -> datetime:
    raw = payload.get("captured_at")
    if isinstance(raw, str):
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            value = None
        if value is not None:
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _snapshot_outcome(payload: dict[str, Any]) -> str:
    outcome = payload.get("outcome")
    if outcome in {READBACK_VERIFIED, READBACK_LOGIN_REQUIRED}:
        return str(outcome)
    if outcome in {"unverified", "readback_error"}:
        return str(outcome)
    return "unverified"


def _cursor_payload(
    previous: dict[str, object],
    *,
    captured_at: datetime,
    scope: str,
    result: dict[str, Any] | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "last_captured_at": captured_at.isoformat(),
        "last_scope": scope,
    }
    if result is not None:
        payload["last_created"] = result["created"]
        payload["last_observed"] = result["observed"]
    if previous.get("first_success_at"):
        payload["first_success_at"] = previous["first_success_at"]
    else:
        payload["first_success_at"] = captured_at.isoformat()
    return payload


def register_metric_sync_handlers(session_factory: sessionmaker[Session]) -> None:
    @register_job_handler(JOB_TYPE)
    def sync_channel_account(
        context: JobExecutionContext, payload_ref: dict[str, object]
    ) -> dict[str, object]:
        context.check_control()
        if context.store_id is None:
            raise JobExecutionError(
                "STORE_CONTEXT_REQUIRED",
                "指标同步任务缺少门店上下文。",
                retryable=False,
            )
        if payload_ref.get("schema_version") != 1:
            raise JobExecutionError(
                "INVALID_JOB_PAYLOAD", "指标同步任务参数版本不受支持。", retryable=False
            )
        try:
            account_id = UUID(str(payload_ref.get("channel_account_id")))
        except (TypeError, ValueError) as exc:
            raise JobExecutionError(
                "INVALID_JOB_PAYLOAD", "指标同步任务参数无效。", retryable=False
            ) from exc
        raw_scopes = payload_ref.get("scopes")
        if not isinstance(raw_scopes, list) or not raw_scopes:
            raise JobExecutionError(
                "INVALID_JOB_PAYLOAD", "指标同步任务缺少观测范围。", retryable=False
            )
        scopes = [str(value) for value in raw_scopes]
        if any(value not in VALID_SCOPES for value in scopes):
            raise JobExecutionError(
                "INVALID_JOB_PAYLOAD", "指标同步任务包含未知观测范围。", retryable=False
            )
        # 去重并保持稳定顺序
        scopes = list(dict.fromkeys(scopes))

        store_id = context.store_id
        with session_factory() as db:
            account = db.scalar(
                select(ChannelAccount).where(
                    ChannelAccount.id == account_id,
                    ChannelAccount.store_id == store_id,
                )
            )
            if account is None:
                raise JobExecutionError(
                    "CHANNEL_ACCOUNT_NOT_FOUND",
                    "未找到该渠道账号，无法同步指标。",
                    retryable=False,
                )
            platform = account.provider
            external_account_id = account.external_account_id
            account_status = account.status

        if account_status != "active":
            with session_factory.begin() as cursor_db:
                for scope in scopes:
                    cursor = get_or_create_cursor(
                        cursor_db,
                        store_id=store_id,
                        channel_account_id=account_id,
                        scope=scope,
                    )
                    mark_cursor_failure(
                        cursor,
                        status="login_required",
                        error_code="CHANNEL_ACCOUNT_NOT_ACTIVE",
                        error_summary="渠道账号未处于有效授权状态。",
                    )
            raise JobExecutionError(
                "CHANNEL_ACCOUNT_NOT_ACTIVE",
                "渠道账号授权已失效，请重新授权后再同步。",
                retryable=False,
            )

        collector = MerchantAuthorizedCollector()
        if not collector.configured:
            with session_factory.begin() as cursor_db:
                for scope in scopes:
                    cursor = get_or_create_cursor(
                        cursor_db,
                        store_id=store_id,
                        channel_account_id=account_id,
                        scope=scope,
                    )
                    mark_cursor_failure(
                        cursor,
                        status="unsupported",
                        error_code="METRIC_COLLECTOR_NOT_CONFIGURED",
                        error_summary="尚未接入商家授权采集器，暂时无法自动同步指标。",
                    )
            raise JobExecutionError(
                "METRIC_COLLECTOR_NOT_CONFIGURED",
                "尚未接入商家授权采集器，暂时无法自动同步指标。",
                retryable=False,
            )

        results: list[dict[str, object]] = []
        retryable_error: CollectorError | None = None
        for index, scope in enumerate(scopes):
            context.check_control()
            context.update_progress(current=index, total=len(scopes))
            with session_factory.begin() as db:
                cursor = get_or_create_cursor(
                    db,
                    store_id=store_id,
                    channel_account_id=account_id,
                    scope=scope,
                )
                previous_cursor = dict(cursor.cursor_json or {})
                mark_cursor_running(cursor)
            try:
                snapshot = collector.collect(
                    platform=platform,
                    external_account_id=external_account_id,
                    scope=scope,
                    since=_cursor_since(previous_cursor),
                )
            except CollectorError as exc:
                with session_factory.begin() as db:
                    cursor = get_or_create_cursor(
                        db,
                        store_id=store_id,
                        channel_account_id=account_id,
                        scope=scope,
                    )
                    mark_cursor_failure(
                        cursor,
                        status=exc.cursor_status,
                        error_code=exc.code,
                        error_summary=exc.summary,
                    )
                results.append(
                    {
                        "scope": scope,
                        "status": exc.cursor_status,
                        "error_code": exc.code,
                    }
                )
                if exc.retryable and retryable_error is None:
                    retryable_error = exc
                continue

            outcome = _snapshot_outcome(snapshot)
            if outcome == READBACK_LOGIN_REQUIRED:
                with session_factory.begin() as db:
                    cursor = get_or_create_cursor(
                        db,
                        store_id=store_id,
                        channel_account_id=account_id,
                        scope=scope,
                    )
                    mark_cursor_failure(
                        cursor,
                        status="login_required",
                        error_code="METRIC_COLLECTOR_LOGIN_REQUIRED",
                        error_summary="商家授权已失效或未登录，请重新授权后再同步。",
                    )
                results.append(
                    {
                        "scope": scope,
                        "status": "login_required",
                        "error_code": "METRIC_COLLECTOR_LOGIN_REQUIRED",
                    }
                )
                continue
            if outcome != READBACK_VERIFIED:
                with session_factory.begin() as db:
                    cursor = get_or_create_cursor(
                        db,
                        store_id=store_id,
                        channel_account_id=account_id,
                        scope=scope,
                    )
                    mark_cursor_failure(
                        cursor,
                        status="unavailable",
                        error_code="METRIC_COLLECTOR_UNVERIFIED",
                        error_summary="采集结果未能核验，本次不写入观测。",
                    )
                results.append(
                    {
                        "scope": scope,
                        "status": "unavailable",
                        "error_code": "METRIC_COLLECTOR_UNVERIFIED",
                    }
                )
                continue

            captured_at = _captured_at(snapshot)
            with session_factory.begin() as db:
                cursor = get_or_create_cursor(
                    db,
                    store_id=store_id,
                    channel_account_id=account_id,
                    scope=scope,
                )
                previous_cursor = dict(cursor.cursor_json or {})
                account_row = db.get(ChannelAccount, account_id)
                if account_row is None:
                    raise JobExecutionError(
                        "CHANNEL_ACCOUNT_NOT_FOUND",
                        "渠道账号在执行过程中被移除。",
                        retryable=False,
                    )
                result = ingest_snapshot(
                    db,
                    store_id=store_id,
                    account=account_row,
                    scope=scope,
                    payload=snapshot,
                    captured_at=captured_at,
                )
                mark_cursor_success(
                    cursor,
                    cursor_json=_cursor_payload(
                        previous_cursor,
                        captured_at=captured_at,
                        scope=scope,
                        result=result,
                    ),
                    now=datetime.now(UTC),
                )
            results.append({"scope": scope, "status": "succeeded", **result})

        context.update_progress(current=len(scopes), total=len(scopes))
        if retryable_error is not None:
            raise JobExecutionError(
                retryable_error.code,
                retryable_error.summary,
                retryable=True,
                retry_delay_seconds=120,
            )
        return {
            "schema_version": 1,
            "channel_account_id": str(account_id),
            "results": results,
        }


def _cursor_since(cursor: dict[str, object]) -> datetime | None:
    raw = cursor.get("last_captured_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
