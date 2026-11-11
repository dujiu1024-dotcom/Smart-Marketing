from collections.abc import Generator

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from store_operator.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=1)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
