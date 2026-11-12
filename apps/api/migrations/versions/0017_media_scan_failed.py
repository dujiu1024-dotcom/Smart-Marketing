"""Add terminal scan_failed state to media assets and upload intents.

Revision ID: 0017_media_scan_failed
Revises: 0016_douyin_webhook_receipts
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_media_scan_failed"
down_revision: str | None = "0016_douyin_webhook_receipts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_media_assets_status", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_status",
        "media_assets",
        "status IN ('uploading', 'quarantined', 'scanning', 'ready', 'rejected', 'scan_failed', 'archived')",
    )
    op.drop_constraint("ck_upload_intents_status", "upload_intents", type_="check")
    op.create_check_constraint(
        "ck_upload_intents_status",
        "upload_intents",
        "status IN ('created', 'uploaded', 'scanning', 'completed', 'rejected', 'scan_failed', 'expired')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE media_assets SET status = 'rejected' WHERE status = 'scan_failed'"
    )
    op.execute(
        "UPDATE upload_intents SET status = 'rejected' WHERE status = 'scan_failed'"
    )
    op.drop_constraint("ck_upload_intents_status", "upload_intents", type_="check")
    op.create_check_constraint(
        "ck_upload_intents_status",
        "upload_intents",
        "status IN ('created', 'uploaded', 'scanning', 'completed', 'rejected', 'expired')",
    )
    op.drop_constraint("ck_media_assets_status", "media_assets", type_="check")
    op.create_check_constraint(
        "ck_media_assets_status",
        "media_assets",
        "status IN ('uploading', 'quarantined', 'scanning', 'ready', 'rejected', 'archived')",
    )
