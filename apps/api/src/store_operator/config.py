from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI 门店运营官 API"
    environment: str = "local"
    database_url: str
    redis_url: str
    cors_origins: str = "http://localhost:5173"
    otel_exporter_otlp_traces_endpoint: str | None = None
    session_token_pepper: str = "local-development-only-change-me"
    # Local-only defaults. Production must set both values explicitly after security review.
    session_idle_timeout_seconds: int = 3600
    session_absolute_timeout_seconds: int = 86400
    session_last_seen_update_seconds: int = 60
    auth_login_max_attempts: int = 10
    auth_login_window_seconds: int = 900
    object_storage_endpoint_url: str | None = None
    object_storage_public_endpoint_url: str | None = None
    asset_scanner_host: str | None = None
    asset_scanner_port: int = 3310
    asset_scanner_timeout_seconds: int = 120
    object_storage_region: str = "us-east-1"
    object_storage_bucket: str | None = None
    object_storage_access_key_id: str | None = None
    object_storage_secret_access_key: str | None = None
    object_storage_upload_ttl_seconds: int = 600
    object_storage_download_ttl_seconds: int = 300
    douyin_client_key: str | None = None
    douyin_client_secret: str | None = None
    douyin_redirect_uri: str | None = None
    channel_secret_store_region: str | None = None
    channel_secret_store_prefix: str = "ai-store-operator/channel-accounts"

    @model_validator(mode="after")
    def validate_auth_settings(self) -> "Settings":
        if self.session_idle_timeout_seconds <= 0:
            raise ValueError("SESSION_IDLE_TIMEOUT_SECONDS must be positive")
        if self.session_absolute_timeout_seconds <= self.session_idle_timeout_seconds:
            raise ValueError(
                "SESSION_ABSOLUTE_TIMEOUT_SECONDS must exceed SESSION_IDLE_TIMEOUT_SECONDS"
            )
        if self.session_last_seen_update_seconds <= 0:
            raise ValueError("SESSION_LAST_SEEN_UPDATE_SECONDS must be positive")
        if self.auth_login_max_attempts <= 0 or self.auth_login_window_seconds <= 0:
            raise ValueError("Login rate-limit settings must be positive")
        if (
            self.object_storage_upload_ttl_seconds <= 0
            or self.object_storage_download_ttl_seconds <= 0
        ):
            raise ValueError("Object storage URL TTL values must be positive")
        douyin_configured = any(
            (self.douyin_client_key, self.douyin_client_secret, self.douyin_redirect_uri)
        )
        if douyin_configured and not all(
            (self.douyin_client_key, self.douyin_client_secret, self.douyin_redirect_uri)
        ):
            raise ValueError(
                "DOUYIN_CLIENT_KEY, DOUYIN_CLIENT_SECRET and DOUYIN_REDIRECT_URI "
                "must be configured together"
            )
        if self.douyin_redirect_uri and not self.douyin_redirect_uri.startswith("https://"):
            raise ValueError("DOUYIN_REDIRECT_URI must use HTTPS")
        if self.environment == "production":
            if not self.object_storage_public_endpoint_url:
                raise ValueError(
                    "OBJECT_STORAGE_PUBLIC_ENDPOINT_URL must be explicitly configured in production"
                )
            if not self.object_storage_public_endpoint_url.startswith("https://"):
                raise ValueError("OBJECT_STORAGE_PUBLIC_ENDPOINT_URL must use HTTPS in production")
            if not self.asset_scanner_host:
                raise ValueError("ASSET_SCANNER_HOST must be explicitly configured in production")
            if not 1 <= self.asset_scanner_port <= 65535:
                raise ValueError("ASSET_SCANNER_PORT must be between 1 and 65535")
            if self.asset_scanner_timeout_seconds <= 0:
                raise ValueError("ASSET_SCANNER_TIMEOUT_SECONDS must be positive")
            if not self.object_storage_bucket:
                raise ValueError(
                    "OBJECT_STORAGE_BUCKET must be explicitly configured in production"
                )
            if (
                not self.object_storage_access_key_id
                or not self.object_storage_secret_access_key
            ):
                raise ValueError(
                    "Object storage credentials must be explicitly configured in production"
                )
            if "session_token_pepper" not in self.model_fields_set:
                raise ValueError("SESSION_TOKEN_PEPPER must be explicitly configured in production")
            if len(self.session_token_pepper) < 32:
                raise ValueError("SESSION_TOKEN_PEPPER must contain at least 32 characters")
            if self.session_token_pepper == "local-development-only-change-me":
                raise ValueError(
                    "SESSION_TOKEN_PEPPER must not use the local development placeholder"
                )
            if "session_idle_timeout_seconds" not in self.model_fields_set:
                raise ValueError("SESSION_IDLE_TIMEOUT_SECONDS must be explicitly configured")
            if "session_absolute_timeout_seconds" not in self.model_fields_set:
                raise ValueError("SESSION_ABSOLUTE_TIMEOUT_SECONDS must be explicitly configured")
        return self


settings = Settings()  # type: ignore[call-arg]  # Values are supplied by environment variables.
