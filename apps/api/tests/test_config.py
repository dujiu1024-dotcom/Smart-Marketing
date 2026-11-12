import pytest
from pydantic import ValidationError

from store_operator.config import Settings


def test_production_rejects_local_development_session_pepper() -> None:
    with pytest.raises(ValidationError, match="local development placeholder"):
        Settings(
            database_url="postgresql+psycopg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
            environment="production",
            session_token_pepper="local-development-only-change-me",
            session_idle_timeout_seconds=3600,
            session_absolute_timeout_seconds=86400,
            object_storage_public_endpoint_url="https://assets.example.com",
            asset_scanner_host="clamav",
            object_storage_bucket="store-operator-private",
            object_storage_access_key_id="test-access-key",
            object_storage_secret_access_key="test-secret-key",
        )


def test_production_accepts_explicit_non_placeholder_session_pepper() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        environment="production",
        session_token_pepper="production-random-secret-value-32-bytes-minimum",
        session_idle_timeout_seconds=3600,
        session_absolute_timeout_seconds=86400,
        object_storage_public_endpoint_url="https://assets.example.com",
        asset_scanner_host="clamav",
        object_storage_bucket="store-operator-private",
        object_storage_access_key_id="test-access-key",
        object_storage_secret_access_key="test-secret-key",
    )
    assert settings.session_token_pepper == "production-random-secret-value-32-bytes-minimum"


def test_production_requires_https_public_object_storage_endpoint() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            database_url="postgresql+psycopg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
            environment="production",
            session_token_pepper="production-random-secret-value-32-bytes-minimum",
            session_idle_timeout_seconds=3600,
            session_absolute_timeout_seconds=86400,
            object_storage_public_endpoint_url="http://assets.example.com",
            object_storage_bucket="store-operator-private",
            object_storage_access_key_id="test-access-key",
            object_storage_secret_access_key="test-secret-key",
        )
