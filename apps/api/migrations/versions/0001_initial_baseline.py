"""Initial database migration baseline.

This marker establishes the first Alembic revision. Domain-owned tables are
introduced in subsequent migrations by their respective implementation issues.
"""

revision: str = "0001_initial_baseline"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    """Establish the initial schema baseline."""


def downgrade() -> None:
    """Return to the pre-baseline state."""
