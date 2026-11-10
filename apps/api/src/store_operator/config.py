from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI 门店运营官 API"
    environment: str = "local"
    database_url: str
    redis_url: str
    cors_origins: str = "http://localhost:5173"
    otel_exporter_otlp_traces_endpoint: str | None = None
    otel_exporter_otlp_traces_endpoint: str | None = None


settings = Settings()
