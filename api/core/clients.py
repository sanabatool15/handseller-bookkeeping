"""Client factories: SQL Server connections (`get_db_connection`) and the Redis singleton.

These are intentionally thin factory functions rather than module-level
globals so tests can inject fakes (`set_db_factory`, fakeredis) without
touching import machinery.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator, Optional, TypeVar

import redis.asyncio as aioredis

from core.config import build_mssql_connection_string, get_settings
from core.db import Db, connect, run_with_deadlock_retry, transaction

T = TypeVar("T")

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


@contextmanager
def db_session() -> Iterator[Db]:
    """One connection + one transaction for code that runs OUTSIDE a FastAPI request
    (Inngest job steps, the MCP server, scripts): commit on success, rollback on any
    exception (re-raised), always closed. Not for use inside request handlers (use
    `routers.deps.get_db` there)."""
    db = get_db_connection()
    try:
        with transaction(db):
            yield db
    finally:
        db.close()


def run_in_db(fn: Callable[[Db], T], *, on_event: Optional[Callable[..., None]] = None) -> T:
    """Run `fn(db)` in its own `db_session()`, retrying the WHOLE unit (new connection and
    transaction) if SQL Server picks it as a deadlock victim. `fn` must be safe to re-run."""
    def attempt() -> T:
        with db_session() as db:
            return fn(db)

    return run_with_deadlock_retry(attempt, on_event=on_event)


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
