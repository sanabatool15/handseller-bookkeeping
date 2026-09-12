"""Supabase client lifecycle. Only repository/ modules should import
`get_client` from here to actually run queries."""

from supabase import Client, create_client

from app.config import get_settings

_client: Client | None = None


def init_client() -> Client:
    """Create the process-wide Supabase client. Called on app startup."""
    global _client
    settings = get_settings()
    _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


def close_client() -> None:
    global _client
    _client = None


def get_client() -> Client:
    if _client is None:
        # Fallback for contexts (tests, scripts) where startup didn't run.
        return init_client()
    return _client
