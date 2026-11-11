from enum import StrEnum


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
