from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from store_operator_worker.retention import retention_decision

NOW = datetime(2026, 11, 13, 3, 15, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=3)


def test_stale_topic_is_deleted_even_with_rising_heat() -> None:
    assert (
        retention_decision(
            last_seen_at=CUTOFF - timedelta(minutes=1),
            first_heat=Decimal("100"),
            last_heat=Decimal("900"),
            sample_count=5,
            cutoff=CUTOFF,
        )
        == "stale"
    )


def test_recent_topic_with_flat_or_falling_heat_is_deleted() -> None:
    assert (
        retention_decision(
            last_seen_at=NOW,
            first_heat=Decimal("500"),
            last_heat=Decimal("500"),
            sample_count=2,
            cutoff=CUTOFF,
        )
        == "trend"
    )
    assert (
        retention_decision(
            last_seen_at=NOW,
            first_heat=Decimal("500"),
            last_heat=Decimal("200"),
            sample_count=3,
            cutoff=CUTOFF,
        )
        == "trend"
    )


def test_recent_topic_with_rising_heat_is_kept() -> None:
    assert (
        retention_decision(
            last_seen_at=NOW,
            first_heat=Decimal("100"),
            last_heat=Decimal("700"),
            sample_count=4,
            cutoff=CUTOFF,
        )
        is None
    )


def test_unknown_trend_with_fewer_than_two_samples_is_kept() -> None:
    assert (
        retention_decision(
            last_seen_at=NOW,
            first_heat=Decimal("100"),
            last_heat=Decimal("100"),
            sample_count=1,
            cutoff=CUTOFF,
        )
        is None
    )
    assert (
        retention_decision(
            last_seen_at=NOW,
            first_heat=None,
            last_heat=None,
            sample_count=0,
            cutoff=CUTOFF,
        )
        is None
    )
