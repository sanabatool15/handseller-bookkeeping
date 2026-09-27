"""Centralized application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str = "https://example.supabase.co"
    supabase_service_key: str = "test-service-key"
    supabase_anon_key: str = "test-anon-key"

    # Auth
    jwt_secret: str = "change-me-super-secret-please-use-a-real-32-byte-value"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    idempotency_ttl_seconds: int = 86400

    # Inngest
    inngest_event_key: str = "local-dev-event-key"
    # Must satisfy the inngest SDK's hash_signing_key(): a "signkey-<word>-"
    # prefix (stripped) followed by a valid hex string, even in dev mode
    # (fetch_with_auth_fallback hashes it unconditionally whenever it's set).
    inngest_signing_key: str = "signkey-test-00000000000000000000000000000000000000000000000000000000000000"
    inngest_base_url: str = "http://localhost:8288"
    inngest_dev: bool = True

    # OpenAI
    openai_api_key: str = "sk-test"
    openai_model: str = "gpt-4o-mini"

    # App
    app_env: str = "development"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
