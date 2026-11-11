"""Bind store-scoped idempotency keys to the authenticated actor.

Revision ID: 0007_idempotency_actor_binding
Revises: 0006_ai_invocation_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_idempotency_actor_binding"
down_revision: str | None = "0006_ai_invocation_lifecycle"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "idempotency_records",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_idempotency_records_actor_user",
        "idempotency_records",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Preserve the owner of already completed responses where the created
    # resource is still present. These records remain replayable by that actor.
    backfills = (
        ("store_profile", "store_profiles"),
        ("product", "products"),
        ("offer", "offers"),
        ("audience_profile", "audience_profiles"),
        ("knowledge_item", "knowledge_items"),
        ("brand_guideline", "brand_guidelines"),
    )
    for resource_type, table_name in backfills:
        op.execute(
            sa.text(
                f"""
                UPDATE idempotency_records AS idem
                SET actor_user_id = resource.created_by_user_id
                FROM {table_name} AS resource
                WHERE idem.resource_type = :resource_type
                  AND idem.resource_id = resource.id
                  AND idem.store_id = resource.store_id
                  AND resource.created_by_user_id IS NOT NULL
                """
            ).bindparams(resource_type=resource_type)
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_idempotency_records_actor_user",
        "idempotency_records",
        type_="foreignkey",
    )
    op.drop_column("idempotency_records", "actor_user_id")
