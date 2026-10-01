"""Centralized application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQL Server (pyodbc). Either give a full ODBC string in MSSQL_CONNECTION_STRING
    # or let the parts below build one. Empty MSSQL_USER => Windows auth (Trusted_Connection).
    mssql_connection_string: str = ""
    mssql_server: str = "localhost"
    mssql_database: str = "HandsellerDB"
    mssql_user: str = ""
    mssql_password: str = ""
    mssql_driver: str = "ODBC Driver 18 for SQL Server"
    mssql_trust_server_certificate: bool = True

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

    # Transaction log + DB Lab (slice F5, specs/15 and specs/16)
    # A call whose elapsed time reaches this many ms is logged as "lock_wait_suspected". It is INFERRED from the
    # elapsed time: the application cannot observe lock waits directly.
    lock_wait_suspect_ms: int = 300
    # Demo-only concurrency lab (/db-lab/*). When False every /db-lab route except /db-lab/status answers 404.
    enable_db_lab: bool = False

    # App
    app_env: str = "development"
    log_level: str = "INFO"


def build_mssql_connection_string(settings: Settings) -> str:
    if settings.mssql_connection_string:
        return settings.mssql_connection_string
    parts = [
        f"DRIVER={{{settings.mssql_driver}}}",
        f"SERVER={settings.mssql_server}",
        f"DATABASE={settings.mssql_database}",
    ]
    if settings.mssql_user:
        parts += [f"UID={settings.mssql_user}", f"PWD={settings.mssql_password}"]
    else:
        parts.append("Trusted_Connection=yes")
    parts.append("TrustServerCertificate=" + ("yes" if settings.mssql_trust_server_certificate else "no"))
    return ";".join(parts) + ";"


@lru_cache
def get_settings() -> Settings:
    return Settings()
