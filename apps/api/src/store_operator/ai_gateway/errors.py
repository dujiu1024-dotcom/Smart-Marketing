from enum import StrEnum

_FAILURE_SUMMARIES_ZH = {
    "PROVIDER_UNAVAILABLE": "AI 服务暂时不可用，请稍后重试。",
    "PROVIDER_RATE_LIMITED": "AI 服务当前请求过多（触发限流），请稍后重试。",
    "PROVIDER_TIMEOUT": "AI 服务响应超时，请稍后重试。",
    "PROVIDER_AUTH_FAILED": "AI 服务凭证无效或已过期，请联系管理员检查配置。",
    "PROVIDER_INVALID_REQUEST": "AI 服务拒绝了本次请求，请检查输入内容后重试。",
    "PROVIDER_OUTPUT_INVALID": "AI 返回内容格式不正确，系统已阻止写入。",
    "PROVIDER_CONTENT_REJECTED": "AI 服务判定内容不合规，请调整后重试。",
    "PROVIDER_BUDGET_EXCEEDED": "AI 调用额度已用尽，请联系管理员。",
    "PROVIDER_CAPABILITY_UNSUPPORTED": "当前 AI 模型不支持该能力，请联系管理员。",
    "PROVIDER_REGION_NOT_ALLOWED": "当前区域不允许调用该 AI 服务。",
    "AI_PROVIDER_NOT_CONFIGURED": "AI 服务尚未配置，请联系管理员。",
    "AI_PROVIDER_CONFIGURATION_INVALID": "AI 服务配置无效，请联系管理员。",
    "AI_PROVIDER_MODEL_NOT_CONFIGURED": "未配置可用的 AI 模型，请联系管理员。",
    "AI_PROMPT_TEMPLATE_AMBIGUOUS": "AI 生成模板配置冲突，请联系管理员。",
    "AI_PROMPT_TEMPLATE_NOT_FOUND": "AI 生成模板缺失，请联系管理员。",
    "AI_PROMPT_TEMPLATE_NOT_PUBLISHED": "AI 生成模板尚未发布，请联系管理员。",
    "AI_PROMPT_TEMPLATE_CONTRACT_MISMATCH": "AI 生成模板与输出契约不一致，请联系管理员。",
    "AI_INVOCATION_AUDIT_MISSING": "AI 调用审计缺失，系统已阻止写入。",
    "AI_STRATEGY_INPUT_STALE": "任务内容已变化，本次策略结果已过期，请重新生成。",
    "AI_COPY_INPUT_STALE": "任务内容已变化，本次文案结果已过期，请重新生成。",
    "AI_IMAGE_INPUT_STALE": "任务内容已变化，本次图片结果已过期，请重新生成。",
    "AI_IMAGE_STEP_NOT_RUNNING": "图片步骤当前不在执行中，请刷新页面后重试。",
    "AI_IMAGE_OBJECT_KEY_CONFLICT": "生成图片与已有素材冲突，系统已阻止写入。",
    "AI_IMAGE_PAYLOAD_INVALID": "图片生成参数无效，请重新发起。",
    "AI_IMAGE_REVISION_INVALID": "图片修改要求无效，请重新填写。",
    "VISION_ISSUES_FOUND": "AI 质检发现图片问题，请修改或重新生成后再审核。",
    "JOB_TIMEOUT": "任务执行超时，请重试。",
    "WORKER_UNEXPECTED_ERROR": "系统执行出现异常，已停止并等待人工处理。",
}


def localized_failure_summary(code: str, fallback: str) -> str:
    """Return a merchant-readable Chinese summary while keeping the error code."""
    message = _FAILURE_SUMMARIES_ZH.get(code)
    if message is None:
        return fallback
    return f"{message}（错误码：{code}）"


class ProviderErrorCode(StrEnum):
    UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    TIMEOUT = "PROVIDER_TIMEOUT"
    AUTH_FAILED = "PROVIDER_AUTH_FAILED"
    INVALID_REQUEST = "PROVIDER_INVALID_REQUEST"
    OUTPUT_INVALID = "PROVIDER_OUTPUT_INVALID"
    CONTENT_REJECTED = "PROVIDER_CONTENT_REJECTED"
    BUDGET_EXCEEDED = "PROVIDER_BUDGET_EXCEEDED"
    CAPABILITY_UNSUPPORTED = "PROVIDER_CAPABILITY_UNSUPPORTED"
    REGION_NOT_ALLOWED = "PROVIDER_REGION_NOT_ALLOWED"


class SideEffectState(StrEnum):
    NONE = "none"
    KNOWN = "known"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    """Sanitized, provider-neutral failure suitable for retry policy decisions."""

    def __init__(
        self,
        code: ProviderErrorCode,
        *,
        retryable: bool,
        user_safe_summary: str,
        retry_after_seconds: float | None = None,
        side_effect_state: SideEffectState = SideEffectState.NONE,
    ) -> None:
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds cannot be negative")
        super().__init__(user_safe_summary)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.side_effect_state = side_effect_state
        self.user_safe_summary = user_safe_summary
