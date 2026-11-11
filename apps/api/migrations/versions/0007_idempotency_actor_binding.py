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

    # StoreRecordRevision is the common source for all store-knowledge
    # create operations, including singleton BrandGuideline records.
    op.execute(
        """
        UPDATE idempotency_records AS idem
        SET actor_user_id = revision.created_by_user_id
        FROM store_record_revisions AS revision
        WHERE idem.store_id = revision.store_id
          AND idem.resource_id = revision.record_id
          AND idem.resource_type = revision.record_type
          AND revision.version_no = 1
          AND revision.created_by_user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_idempotency_records_actor_user",
        "idempotency_records",
        type_="foreignkey",
    )
    op.drop_column("idempotency_records", "actor_user_id")
