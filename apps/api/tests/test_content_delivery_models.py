from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from store_operator.models import (
    Artifact,
    ArtifactVersion,
    ChannelContent,
    ChannelContentArtifactRef,
    PublishConfirmation,
    PublishPackage,
    PublishPackageFactRef,
    PublishPackageItem,
    QualityReport,
    QualityResolution,
    ReviewRecord,
)
from store_operator.models.base import Base


def _named_constraint(table, kind, name: str):
    return next(
        item
        for item in table.constraints
        if isinstance(item, kind) and item.name == name
    )


def test_content_delivery_tables_are_registered() -> None:
    assert {
        "artifacts",
        "artifact_versions",
        "review_records",
        "channel_contents",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    } <= set(Base.metadata.tables)


def test_artifact_versions_are_store_scoped_and_immutable_by_schema() -> None:
    table = ArtifactVersion.__table__
    _named_constraint(
        table,
        UniqueConstraint,
        "uq_artifact_versions_artifact_version",
    )
    fk = _named_constraint(
        table,
        ForeignKeyConstraint,
        "fk_artifact_versions_artifact_same_store",
    )
    assert tuple(column.name for column in fk.columns) == ("store_id", "artifact_id")
    checks = {
        item.name
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    assert "ck_artifact_versions_source_type" in checks
    assert "ck_artifact_versions_content_required" in checks


def test_reviews_reference_the_exact_artifact_version_in_same_store() -> None:
    table = ReviewRecord.__table__
    fk = _named_constraint(
        table,
        ForeignKeyConstraint,
        "fk_review_records_version_same_artifact",
    )
    assert tuple(column.name for column in fk.columns) == (
        "store_id",
        "artifact_id",
        "artifact_version_id",
    )
    checks = {
        item.name
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    assert "ck_review_records_revision_comment_required" in checks


def test_artifact_current_version_is_constrained_to_its_own_artifact() -> None:
    fk = _named_constraint(
        Artifact.__table__,
        ForeignKeyConstraint,
        "fk_artifacts_current_version_same_artifact",
    )
    assert tuple(column.name for column in fk.columns) == (
        "store_id",
        "id",
        "current_version_id",
    )


def test_artifact_versions_bind_prompt_version_and_have_store_unique_id() -> None:
    table = ArtifactVersion.__table__
    _named_constraint(
        table,
        UniqueConstraint,
        "uq_artifact_versions_store_id",
    )
    _named_constraint(
        table,
        ForeignKeyConstraint,
        "fk_artifact_versions_prompt_version",
    )


def test_channel_content_is_store_scoped_and_binds_exact_copy_version() -> None:
    table = ChannelContent.__table__
    _named_constraint(
        table,
        UniqueConstraint,
        "uq_channel_contents_input_fingerprint",
    )
    _named_constraint(
        table,
        ForeignKeyConstraint,
        "fk_channel_contents_copy_version_same_store",
    )
    _named_constraint(
        table,
        ForeignKeyConstraint,
        "fk_channel_contents_task_same_store",
    )


def test_channel_content_image_refs_bind_same_store_artifact_versions() -> None:
    table = ChannelContentArtifactRef.__table__
    _named_constraint(
        table,
        ForeignKeyConstraint,
        "fk_channel_content_artifact_refs_content_same_store",
    )
    _named_constraint(
        table,
        ForeignKeyConstraint,
        "fk_channel_content_artifact_refs_version_same_store",
    )
    _named_constraint(
        table,
        UniqueConstraint,
        "uq_channel_content_artifact_refs_position",
    )


def test_quality_report_and_resolution_preserve_exact_fingerprint() -> None:
    report = QualityReport.__table__
    _named_constraint(
        report,
        UniqueConstraint,
        "uq_quality_reports_store_id_fingerprint",
    )
    _named_constraint(
        report,
        UniqueConstraint,
        "uq_quality_reports_content_rule_fingerprint",
    )
    resolution = QualityResolution.__table__
    _named_constraint(
        resolution,
        ForeignKeyConstraint,
        "fk_quality_resolutions_report_fingerprint_same_store",
    )
    _named_constraint(
        resolution,
        UniqueConstraint,
        "uq_quality_resolutions_report_fingerprint",
    )


def test_publish_package_items_bind_matching_channel_and_quality_report() -> None:
    package = PublishPackage.__table__
    _named_constraint(
        package,
        UniqueConstraint,
        "uq_publish_packages_store_id_fingerprint",
    )
    _named_constraint(
        package,
        UniqueConstraint,
        "uq_publish_packages_task_version",
    )
    item = PublishPackageItem.__table__
    _named_constraint(
        item,
        ForeignKeyConstraint,
        "fk_publish_package_items_channel_content_same_store",
    )
    _named_constraint(
        item,
        ForeignKeyConstraint,
        "fk_publish_package_items_quality_report_same_content",
    )
    _named_constraint(
        item,
        UniqueConstraint,
        "uq_publish_package_items_channel",
    )


def test_publish_packages_require_confirmed_fact_refs_and_fingerprint_confirmation() -> None:
    facts = PublishPackageFactRef.__table__
    _named_constraint(
        facts,
        ForeignKeyConstraint,
        "fk_publish_package_fact_refs_fact_same_task",
    )
    _named_constraint(
        facts,
        ForeignKeyConstraint,
        "fk_publish_package_fact_refs_package_same_task",
    )
    confirmation = PublishConfirmation.__table__
    _named_constraint(
        confirmation,
        ForeignKeyConstraint,
        "fk_publish_confirmations_package_fingerprint_same_store",
    )
    _named_constraint(
        confirmation,
        UniqueConstraint,
        "uq_publish_confirmations_package_fingerprint",
    )
