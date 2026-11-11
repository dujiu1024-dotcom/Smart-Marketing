import os

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@localhost:5432/test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_TOKEN_PEPPER", "test-only-session-token-pepper-32-bytes")


@pytest.fixture
def db_session():
    from store_operator.db import engine

    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture
def identity_client(db_session):
    from store_operator.db import get_db
    from store_operator.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, base_url="https://testserver")
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        client.close()
