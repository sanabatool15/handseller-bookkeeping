"""Singleton clients for Supabase and Redis, created once at app startup.

These are intentionally thin factory functions rather than module-level
globals so tests can monkeypatch / inject fakes (fakeredis, mocked Supabase
client) without touching import machinery.
"""
from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis
from supabase import Client, create_client

from app.config import get_settings

_supabase_client: Optional[Client] = None
_redis_client: Optional[aioredis.Redis] = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


def set_supabase(client: Client) -> None:
    """Test/dependency-injection hook."""
    global _supabase_client
    _supabase_client = client


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def set_redis(client: aioredis.Redis) -> None:
    """Test/dependency-injection hook (e.g. fakeredis.aioredis)."""
    global _redis_client
    _redis_client = client


async def close_clients() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
