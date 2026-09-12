"""Supabase client factory. This is the ONLY module allowed to construct the
Supabase client; the repository layer imports get_client() from here.
"""
from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings


@lru_cache
def get_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
