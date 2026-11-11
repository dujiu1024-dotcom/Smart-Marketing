from __future__ import annotations

from store_operator.models.channel_delivery import PublishOperation


def test_publish_operation_is_unique_per_frozen_package_item() -> None:
    constraint_names = {
        constraint.name for constraint in PublishOperation.__table__.constraints
    }

    assert "uq_publish_operations_package_item" in constraint_names
