"""Prevent duplicate platform publication for one frozen package item.

Revision ID: 0014_publish_operation_item_unique
Revises: 0013_douyin_channel_delivery
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_publish_operation_item_unique"
down_revision: str | None = "0013_douyin_channel_delivery"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_publish_operations_package_item",
        "publish_operations",
        ["store_id", "publish_package_item_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_publish_operations_package_item",
        "publish_operations",
        type_="unique",
    )
