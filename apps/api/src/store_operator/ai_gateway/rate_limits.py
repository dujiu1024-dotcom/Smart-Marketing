"""Per-model sliding-window rate limits for AI providers.

The upstream Token Plan enforces a per-minute window per model. ``insufficient_quota``
is a rate-limit signal for this vendor, not a billing signal. Requests are reserved
against a 60 second sliding window (tokens and request count) before they are sent,
and a Redis lease bounds in-flight concurrency across worker processes.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from store_operator.ai_gateway.errors import ProviderError, ProviderErrorCode


@dataclass(frozen=True, slots=True)
class ModelRateLimit:
    pool: str
    max_input_tokens: int
    tokens_per_minute: int
    requests_per_minute: int
    max_concurrency: int

    def __post_init__(self) -> None:
        if not self.pool:
            raise ValueError("Model rate-limit pool must not be empty")
        for name, value in (
            ("max_input_tokens", self.max_input_tokens),
            ("tokens_per_minute", self.tokens_per_minute),
            ("requests_per_minute", self.requests_per_minute),
            ("max_concurrency", self.max_concurrency),
        ):
            if value < 1:
                raise ValueError(f"Model rate-limit {name} must be positive")


# Conservative defaults measured against the Token Plan. Environment overrides via
# AI_MODEL_RATE_LIMITS (JSON object keyed by model id) take precedence.
DEFAULT_MODEL_RATE_LIMITS: dict[str, ModelRateLimit] = {
    "sensenova-6.8-flash-lite": ModelRateLimit(
        pool="sensenova", max_input_tokens=32_000,
        tokens_per_minute=18_000, requests_per_minute=60, max_concurrency=4,
    ),
    "glm-5.2": ModelRateLimit(
        pool="zhipu", max_input_tokens=24_000,
        tokens_per_minute=10_000, requests_per_minute=10, max_concurrency=2,
    ),
    "sensenova-6.8-flash": ModelRateLimit(
        pool="sensenova", max_input_tokens=8_000,
        tokens_per_minute=6_000, requests_per_minute=6, max_concurrency=2,
    ),
    "deepseek-v4-flash": ModelRateLimit(
        pool="deepseek", max_input_tokens=6_000,
        tokens_per_minute=4_000, requests_per_minute=4, max_concurrency=1,
    ),
    "deepseek-flash": ModelRateLimit(
        pool="deepseek", max_input_tokens=6_000,
        tokens_per_minute=4_000, requests_per_minute=4, max_concurrency=1,
    ),
}
_DEFAULT_LIMIT = ModelRateLimit(
    pool="default", max_input_tokens=8_000,
    tokens_per_minute=6_000, requests_per_minute=6, max_concurrency=2,
)
_WINDOW_SECONDS = 60.0
_CONCURRENCY_LEASE_SECONDS = 300
_COOLDOWN_SECONDS = 65.0

_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local rpm = tonumber(ARGV[3])
local tpm = tonumber(ARGV[4])
local tokens = tonumber(ARGV[5])
local member = ARGV[6]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local entries = redis.call('ZRANGE', key, 0, -1, 'WITHSCORES')
local count = #entries / 2
local used = 0
for i = 1, #entries, 2 do
  local value = tonumber(string.match(entries[i], '^(%d+)|'))
  used = used + (value or 0)
end
if count + 1 > rpm or used + tokens > tpm then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local oldest_score = oldest[2] and tonumber(oldest[2]) or now
  return {0, math.max(1, math.ceil((oldest_score + window - now) * 1000))}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return {1, 0}
"""

_ACQUIRE_CONCURRENCY_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
local expires = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, 0, now)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, expires, member)
redis.call('PEXPIRE', key, math.ceil((expires - now) * 1000))
return 1
"""


def estimate_text_tokens(
    *, system_instruction: str, user_input: str, max_output_tokens: int
) -> int:
    """Conservative token estimate; Chinese prompts are roughly one token per character."""
    prompt_tokens = math.ceil((len(system_instruction) + len(user_input)) / 1.5)
    return max(1, prompt_tokens + max_output_tokens)


def _load_env_limits() -> dict[str, ModelRateLimit]:
    raw = os.environ.get("AI_MODEL_RATE_LIMITS", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError("AI_MODEL_RATE_LIMITS must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("AI_MODEL_RATE_LIMITS must be a JSON object")
    overrides: dict[str, ModelRateLimit] = {}
    for model_id, value in payload.items():
        if not isinstance(model_id, str) or not isinstance(value, dict):
            raise ValueError("AI_MODEL_RATE_LIMITS entries must be objects keyed by model id")
        overrides[model_id] = ModelRateLimit(
            pool=str(value["pool"]),
            max_input_tokens=int(value["max_input_tokens"]),
            tokens_per_minute=int(value["tokens_per_minute"]),
            requests_per_minute=int(value["requests_per_minute"]),
            max_concurrency=int(value["max_concurrency"]),
        )
    return overrides


class ModelRateLimiter:
    """Redis-backed sliding window plus in-flight concurrency leases."""

    def __init__(
        self,
        *,
        redis: Redis | None = None,
        window_seconds: float = _WINDOW_SECONDS,
        cooldown_seconds: float = _COOLDOWN_SECONDS,
        limits: Mapping[str, ModelRateLimit] | None = None,
    ) -> None:
        self._redis = redis
        self._window = window_seconds
        self._cooldown = cooldown_seconds
        self._limits = dict(DEFAULT_MODEL_RATE_LIMITS)
        self._limits.update(limits or {})

    def _client(self) -> Redis:
        if self._redis is None:
            redis_url = os.environ.get("REDIS_URL", "").strip()
            if not redis_url:
                raise ProviderError(
                    ProviderErrorCode.RATE_LIMITED,
                    retryable=True,
                    retry_after_seconds=self._cooldown,
                    user_safe_summary=(
                        "AI rate limiter is unavailable because Redis is not configured."
                    ),
                )
            self._redis = Redis.from_url(redis_url, decode_responses=True)
        return self._redis

    def _enabled(self) -> bool:
        return self._redis is not None or bool(os.environ.get("REDIS_URL", "").strip())

    def limits_for(self, model_id: str) -> ModelRateLimit:
        return self._limits.get(model_id, _DEFAULT_LIMIT)

    def pool_for(self, model_id: str) -> str:
        return self.limits_for(model_id).pool

    def _cooldown_key(self, model_id: str) -> str:
        return f"ai:rate:cooldown:{model_id}"

    def record_rate_limited(self, model_id: str, retry_after_seconds: float | None) -> None:
        if not self._enabled():
            return
        delay = max(self._cooldown, retry_after_seconds or 0)
        try:
            self._client().set(self._cooldown_key(model_id), "1", ex=math.ceil(delay))
        except RedisError:
            pass

    def cooldown_remaining(self, model_id: str) -> float:
        if not self._enabled():
            return 0.0
        try:
            ttl = self._client().ttl(self._cooldown_key(model_id))
        except RedisError:
            return 0.0
        return float(max(0, ttl))

    async def acquire(self, model_id: str, tokens: int) -> str:
        if not self._enabled():
            return ""
        limit = self.limits_for(model_id)
        if tokens > limit.tokens_per_minute:
            raise ProviderError(
                ProviderErrorCode.RATE_LIMITED,
                retryable=True,
                retry_after_seconds=self._cooldown,
                user_safe_summary="The AI request exceeds the model token window.",
            )
        member = f"{max(1, tokens)}|{uuid.uuid4().hex}"
        concurrency_member = uuid.uuid4().hex
        redis = self._client()
        while True:
            remaining = self.cooldown_remaining(model_id)
            if remaining > 0:
                raise ProviderError(
                    ProviderErrorCode.RATE_LIMITED,
                    retryable=True,
                    retry_after_seconds=remaining,
                    user_safe_summary="The AI model is cooling down after a rate limit.",
                )
            now = time.time()
            try:
                acquired = redis.eval(
                    _ACQUIRE_CONCURRENCY_SCRIPT, 1,
                    f"ai:rate:inflight:{model_id}",
                    now, limit.max_concurrency, concurrency_member,
                    now + _CONCURRENCY_LEASE_SECONDS,
                )
            except RedisError as exc:
                raise ProviderError(
                    ProviderErrorCode.UNAVAILABLE,
                    retryable=True,
                    retry_after_seconds=60,
                    user_safe_summary="AI rate limiter storage is temporarily unavailable.",
                ) from exc
            if int(acquired) != 1:
                await asyncio.sleep(0.25)
                continue
            try:
                allowed, wait_ms = redis.eval(
                    _WINDOW_SCRIPT, 1,
                    f"ai:rate:window:{model_id}:{math.ceil(self._window)}",
                    now, self._window, limit.requests_per_minute,
                    limit.tokens_per_minute, tokens, member,
                )
            except RedisError as exc:
                redis.zrem(f"ai:rate:inflight:{model_id}", concurrency_member)
                raise ProviderError(
                    ProviderErrorCode.UNAVAILABLE,
                    retryable=True,
                    retry_after_seconds=60,
                    user_safe_summary="AI rate limiter storage is temporarily unavailable.",
                ) from exc
            if int(allowed) == 1:
                return concurrency_member
            redis.zrem(f"ai:rate:inflight:{model_id}", concurrency_member)
            await asyncio.sleep(min(max(wait_ms, 250), 5_000) / 1000)

    def release(self, model_id: str, concurrency_member: str) -> None:
        if not concurrency_member or not self._enabled():
            return
        try:
            self._client().zrem(f"ai:rate:inflight:{model_id}", concurrency_member)
        except RedisError:
            pass


@lru_cache(maxsize=1)
def get_model_rate_limiter() -> ModelRateLimiter:
    return ModelRateLimiter(limits=_load_env_limits())


def model_fallback_candidates(
    primary_model_id: str,
    *,
    capability: str,
) -> tuple[str, ...]:
    """Return configured fallbacks from other pools only."""
    env_key = "AI_TEXT_MODEL_IDS" if capability == "text" else "AI_VISION_MODEL_IDS"
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return ()
    limiter = get_model_rate_limiter()
    primary_pool = limiter.pool_for(primary_model_id)
    candidates: list[str] = []
    for model_id in (item.strip() for item in raw.split(",")):
        if not model_id or model_id == primary_model_id or model_id in candidates:
            continue
        if limiter.pool_for(model_id) == primary_pool:
            continue
        candidates.append(model_id)
    return tuple(candidates)
