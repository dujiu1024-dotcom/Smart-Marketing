import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@localhost:5432/test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


import pytest
from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Provide a transaction-scoped database session; all test writes are rolled back."""

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            session = Session(bind=connection)
            try:
                yield session
            finally:
                session.close()
                if transaction.is_active:
                    transaction.rollback()
    finally:
        engine.dispose()
