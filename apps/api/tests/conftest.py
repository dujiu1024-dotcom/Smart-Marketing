import os

import pytest
from sqlalchemy import event
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
    session = Session(bind=connection, expire_on_commit=False)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(current_session, transaction):
        if transaction.nested and transaction._parent is not None and not transaction._parent.nested:
            current_session.begin_nested()

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
