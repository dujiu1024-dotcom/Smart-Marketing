from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from store_operator.models import Artifact, ArtifactVersion, ReviewRecord
from store_operator.models.base import Base


def _named_constraint(table, kind, name: str):
    return next(
        item
        for item in table.constraints
        if isinstance(item, kind) and item.name == name
    )


def test_content_delivery_tables_are_registered() -> None:
    assert {"artifacts", "artifact_versions", "review_records"} <= set(Base.metadata.tables)


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
