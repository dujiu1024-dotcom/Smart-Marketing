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
        if self.environment == "production":
            if "session_token_pepper" not in self.model_fields_set:
                raise ValueError("SESSION_TOKEN_PEPPER must be explicitly configured in production")
            if len(self.session_token_pepper) < 32:
                raise ValueError("SESSION_TOKEN_PEPPER must contain at least 32 characters")
            if "session_idle_timeout_seconds" not in self.model_fields_set:
                raise ValueError("SESSION_IDLE_TIMEOUT_SECONDS must be explicitly configured")
            if "session_absolute_timeout_seconds" not in self.model_fields_set:
                raise ValueError("SESSION_ABSOLUTE_TIMEOUT_SECONDS must be explicitly configured")
        return self


settings = Settings()  # type: ignore[call-arg]  # Values are supplied by environment variables.
