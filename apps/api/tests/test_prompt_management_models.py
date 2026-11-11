from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from store_operator.models import PromptActivation, PromptTemplate, PromptVersion


def _named(table, kind, name: str):
    return next(
        item
        for item in table.constraints
        if isinstance(item, kind) and item.name == name
    )


def test_prompt_configuration_is_global_not_store_scoped() -> None:
    assert "store_id" not in PromptTemplate.__table__.c
    assert "store_id" not in PromptVersion.__table__.c
    assert "store_id" not in PromptActivation.__table__.c


def test_prompt_template_scope_key_and_published_pointer_are_constrained() -> None:
    table = PromptTemplate.__table__
    _named(table, UniqueConstraint, "uq_prompt_templates_scope_key")
    fk = _named(
        table,
        ForeignKeyConstraint,
        "fk_prompt_templates_current_version_same_template",
    )
    assert tuple(column.name for column in fk.columns) == (
        "id",
        "current_published_version_id",
    )


def test_prompt_versions_are_monotonic_per_template_and_publish_metadata_is_required() -> None:
    table = PromptVersion.__table__
    _named(table, UniqueConstraint, "uq_prompt_versions_template_version")
    checks = {
        item.name
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    assert "ck_prompt_versions_published_metadata_required" in checks
    assert "ck_prompt_versions_status" in checks


def test_prompt_activation_is_bound_to_versions_of_same_template_and_idempotent() -> None:
    table = PromptActivation.__table__
    _named(
        table,
        ForeignKeyConstraint,
        "fk_prompt_activations_activated_version_same_template",
    )
    _named(
        table,
        ForeignKeyConstraint,
        "fk_prompt_activations_previous_version_same_template",
    )
    _named(table, UniqueConstraint, "uq_prompt_activations_idempotency_hash")
    checks = {
        item.name
        for item in table.constraints
        if isinstance(item, CheckConstraint)
    }
    assert "ck_prompt_activations_hashes" in checks
