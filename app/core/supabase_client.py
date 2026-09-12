"""Supabase client connection management.

Provides a single, lazily-created Supabase client shared across the app,
plus a FastAPI dependency for use in route handlers.
"""

from supabase import Client, create_client

from app.core.config import get_settings

_client: Client | None = None


def init_supabase() -> Client:
    """Create (or return the existing) Supabase client. Call on app startup."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set (see .env.example)."
            )
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


def close_supabase() -> None:
    """Release the Supabase client reference. Call on app shutdown."""
    global _client
    _client = None


def get_supabase() -> Client:
    """FastAPI dependency that yields the shared Supabase client."""
    if _client is None:
        return init_supabase()
    return _client
