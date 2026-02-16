from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    supabase_url: str
    supabase_service_role_key: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60
    smartlead_webhook_secret: str | None = None
    heyreach_webhook_secret: str | None = None
    internal_scheduler_secret: str | None = None
    heyreach_message_sync_mode: str = "webhook_only"  # webhook_only | pull_best_effort
    observability_export_url: str | None = None
    observability_export_bearer_token: str | None = None
    observability_export_timeout_seconds: float = 3.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
