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

    # Idempotency keys are kept in SQL Server (table idempotency_keys); answers are remembered this long
    idempotency_ttl_seconds: int = 86400

    # Transaction log + DB Lab (slice F5, docs/SQL_TRANSACTIONS.md and docs/FRONTEND.md)
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
