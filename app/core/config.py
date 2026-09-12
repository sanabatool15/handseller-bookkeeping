"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = "https://example.supabase.co"
    supabase_service_role_key: str = "test-service-role-key"
    supabase_anon_key: str = "test-anon-key"

    jwt_secret: str = "test-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    openai_api_key: str = ""
    openai_agent_model: str = "gpt-4o-mini"

    app_env: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
