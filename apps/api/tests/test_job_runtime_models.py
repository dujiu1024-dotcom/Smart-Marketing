from store_operator.models import Base


def test_job_runtime_tables_are_registered() -> None:
    expected = {
        "jobs",
        "job_attempts",
        "job_events",
        "outbox_events",
        "ai_invocations",
        "ai_usage_records",
    }

    assert expected.issubset(Base.metadata.tables)


def test_job_idempotency_scope_is_non_nullable_and_store_aware() -> None:
    jobs = Base.metadata.tables["jobs"]

    assert jobs.c.idempotency_scope_id.nullable is False
    assert jobs.c.store_id.nullable is True
    assert any(
        {"idempotency_scope_type", "idempotency_scope_id", "idempotency_key"}
        == {column.name for column in constraint.columns}
        for constraint in jobs.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
    assert any(
        "idempotency_scope_type" in str(constraint.sqltext)
        for constraint in jobs.constraints
        if hasattr(constraint, "sqltext")
    )


def test_job_attempt_history_is_append_only_and_unique_per_attempt_number() -> None:
    attempts = Base.metadata.tables["job_attempts"]

    assert attempts.c.lease_token.nullable is False
    assert any(
        {column.name for column in constraint.columns} == {"job_id", "attempt_no"}
        for constraint in attempts.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )


def test_outbox_has_dedupe_and_recovery_indexes() -> None:
    outbox = Base.metadata.tables["outbox_events"]

    assert outbox.c.dedupe_key.nullable is False
    assert any(
        {column.name for column in constraint.columns} == {"dedupe_key"}
        for constraint in outbox.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
    index_names = {index.name for index in outbox.indexes}
    assert "ix_outbox_events_status_available" in index_names
    assert "ix_outbox_events_lock_expiry" in index_names


def test_ai_usage_cost_requires_explicit_currency_pair() -> None:
    usage = Base.metadata.tables["ai_usage_records"]

    assert usage.c.cost_amount.type.precision == 18
    assert usage.c.cost_amount.type.scale == 6
    assert any(
        "cost_amount" in str(constraint.sqltext) and "currency" in str(constraint.sqltext)
        for constraint in usage.constraints
        if hasattr(constraint, "sqltext")
    )
