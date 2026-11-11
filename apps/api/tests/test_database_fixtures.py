from sqlalchemy import text
from sqlalchemy.orm import Session


def test_db_session_supports_transactional_seed_data(db_session: Session) -> None:
    db_session.execute(
        text("CREATE TEMP TABLE test_seed_probe (id integer PRIMARY KEY, value text NOT NULL)")
    )
    db_session.execute(
        text("INSERT INTO test_seed_probe (id, value) VALUES (:id, :value)"),
        {"id": 1, "value": "fixture-seed"},
    )

    result = db_session.execute(
        text("SELECT value FROM test_seed_probe WHERE id = :id"),
        {"id": 1},
    ).scalar_one()

    assert result == "fixture-seed"
