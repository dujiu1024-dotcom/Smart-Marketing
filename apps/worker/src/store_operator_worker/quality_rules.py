from __future__ import annotations

from collections.abc import Iterator
from typing import Any

RULE_VERSION = "content-structure-v1"
_PLACEHOLDERS = ("lorem ipsum", "todo", "tbd", "待填写", "待补充", "示例文案", "占位")
_FACT_TERMS = (
    "price", "discount", "offer", "promotion", "stock", "inventory",
    "address", "opening hours", "phone", "价格", "优惠", "折扣", "库存",
    "地址", "营业时间", "电话",
)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def evaluate_content(payload: dict[str, object]) -> tuple[str, list[dict[str, str]]]:
    """Run deterministic structural checks; never claim semantic/visual AI validation."""
    if not payload:
        return "fail", [{"code": "EMPTY_CHANNEL_CONTENT", "severity": "hard"}]

    issues: list[dict[str, str]] = []
    for field in ("title", "body"):
        if field in payload and (
            not isinstance(payload[field], str) or not str(payload[field]).strip()
        ):
            issues.append({"code": f"EMPTY_{field.upper()}", "severity": "hard"})

    text_values = list(_strings(payload))
    if any(
        marker in value.casefold()
        for value in text_values
        for marker in _PLACEHOLDERS
    ):
        issues.append({"code": "PLACEHOLDER_TEXT", "severity": "hard"})

    combined = " ".join(text_values).casefold()
    if any(term in combined for term in _FACT_TERMS):
        issues.append({"code": "BUSINESS_FACTS_REQUIRE_HUMAN_CHECK", "severity": "review"})

    if any(issue["severity"] == "hard" for issue in issues):
        return "fail", issues
    if issues:
        return "needs_human", issues
    return "pass", []
