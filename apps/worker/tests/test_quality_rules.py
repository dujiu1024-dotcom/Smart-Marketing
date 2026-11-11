from store_operator_worker.quality_rules import RULE_VERSION, evaluate_content


def test_quality_rules_pass_structurally_complete_neutral_content() -> None:
    result, issues = evaluate_content(
        {"title": "A lunch gathering", "body": "Visit us for a relaxed meal."}
    )
    assert RULE_VERSION == "content-structure-v1"
    assert result == "pass"
    assert issues == []


def test_quality_rules_fail_placeholder_copy() -> None:
    result, issues = evaluate_content(
        {"title": "TODO", "body": "A real description"}
    )
    assert result == "fail"
    assert issues == [{"code": "PLACEHOLDER_TEXT", "severity": "hard"}]


def test_quality_rules_require_human_fact_review_for_commercial_claims() -> None:
    result, issues = evaluate_content(
        {"title": "Special offer", "body": "20% discount this weekend"}
    )
    assert result == "needs_human"
    assert issues == [
        {"code": "BUSINESS_FACTS_REQUIRE_HUMAN_CHECK", "severity": "review"}
    ]


def test_quality_rules_reject_empty_payload() -> None:
    result, issues = evaluate_content({})
    assert result == "fail"
    assert issues == [{"code": "EMPTY_CHANNEL_CONTENT", "severity": "hard"}]
