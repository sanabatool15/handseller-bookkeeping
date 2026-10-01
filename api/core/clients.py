"""Singleton clients for Supabase and Redis, created once at app startup.

These are intentionally thin factory functions rather than module-level
globals so tests can monkeypatch / inject fakes (fakeredis, mocked Supabase
client) without touching import machinery.
"""
from __future__ import annotations

from typing import Callable, Optional

import redis.asyncio as aioredis
from supabase import Client, create_client

from core.config import build_mssql_connection_string, get_settings
from core.db import Db, connect

_supabase_client: Optional[Client] = None
_redis_client: Optional[aioredis.Redis] = None
_db_factory: Optional[Callable[[], Db]] = None


def get_db_connection() -> Db:
    """Return a NEW SQL Server `Db` (one per request/unit of work; caller closes it)."""
    if _db_factory is not None:
        return _db_factory()
    return connect(build_mssql_connection_string(get_settings()))


def set_db_factory(factory: Optional[Callable[[], Db]]) -> None:
    """Test/dependency-injection hook; pass None to restore the real pyodbc factory."""
    global _db_factory
    _db_factory = factory


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


async def get_redis_checked() -> aioredis.Redis:
    """Like get_redis(), but discards and recreates the client if the
    existing connection is stale (e.g. reused across a serverless cold
    start where the underlying TCP socket has been dropped by the peer)."""
    global _redis_client
    client = get_redis()
    try:
        await client.ping()
    except Exception:  # noqa: BLE001
        await client.aclose()
        _redis_client = None
        client = get_redis()
    return client


def set_redis(client: aioredis.Redis) -> None:
    """Test/dependency-injection hook (e.g. fakeredis.aioredis)."""
    global _redis_client
    _redis_client = client


async def close_clients() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
