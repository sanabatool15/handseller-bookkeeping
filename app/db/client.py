"""Supabase client lifecycle management.

This is the ONLY place a Supabase client is constructed. Repository modules
import `get_client()` from here to run queries; nothing outside
`app/repository/` should import this module.
"""
from supabase import Client, create_client

from app.core.config import get_settings

_client: Client | None = None


def init_client() -> Client:
    """Create (or return the existing) Supabase client. Call on startup."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set (see .env.example)."
            )
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


def get_client() -> Client:
    """Return the initialized Supabase client, raising if startup didn't run."""
    if _client is None:
        return init_client()
    return _client


def close_client() -> None:
    """Reset the cached client. Call on shutdown."""
    global _client
    _client = None
