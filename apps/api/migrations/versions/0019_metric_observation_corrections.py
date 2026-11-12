"""Ensure a metric observation can have only one direct correction.

Revision ID: 0019_metric_observation_corrections
Revises: 0018_opportunity_effects
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0019_metric_obs_corrections"
down_revision: str | None = "0018_opportunity_effects"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_metric_observations_single_successor",
        "metric_observations",
        ["supersedes_observation_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_metric_observations_single_successor",
        "metric_observations",
        type_="unique",
    )
