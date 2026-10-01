"""Shared fixtures for the prompt-2 real-infra e2e suite.

Unlike `tests/e2e/prompt-1/conftest.py`, this suite does NOT wire
the in-memory fakes or fakeredis. `client` here is a plain `TestClient(app)` that
exercises the app exactly as `docker compose up` / `uvicorn app.main:app`
would: `core.clients.get_db_connection()` returns a a real SQL Server connection talking
the `MSSQL_*` settings from `.env`, and
`app.clients.get_redis()` returns a real `redis.asyncio` client talking to
`REDIS_URL`. If those endpoints are not reachable in the current
environment, requests will fail with connection errors (surfaced as 500s or
raised exceptions) rather than being silently faked — that failure is the
signal this suite is designed to report honestly as
"blocked: infra unreachable", not to hide.

Every fixture that creates data registers a teardown that deletes exactly
what it created, scoped by id + org_id (never a blanket table wipe), and
runs even if the test body raises.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")

from core.clients import get_redis, set_db_factory, set_redis  # noqa: E402
from core.fastapi_app import app  # noqa: E402
from tests.e2e import e2e_db  # noqa: E402
from core.config import get_settings  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture(autouse=True)
def _wire_fakes():
    """Overrides the repo-root `tests/conftest.py`'s autouse `_wire_fakes`
    fixture of the SAME NAME, which would otherwise silently inject
    in-memory fakes + fakeredis into every test under `tests/`, including this
    directory. pytest fixture resolution prefers the closest conftest, so
    this shadowing definition wins for every test collected under
    `tests/e2e/prompt-2/` and makes sure the app's client singletons point
    at REAL SQL Server/Redis clients built straight from `.env`, exactly as
    `docker compose up` / `uvicorn app.main:app` would construct them --
    never at fakes.
    """
    settings = get_settings()
    set_redis(aioredis.from_url(settings.redis_url, decode_responses=True))
    yield


@pytest.fixture(autouse=True)
def _wire_sql_fakes():
    """Shadows tests/conftest.py's autouse fixture of the same name: real SQL Server, real repositories."""
    set_db_factory(None)
    yield


@pytest.fixture
def client():
    """Real TestClient — no fakes wired. Talks to whatever MSSQL_* /
    REDIS_URL / INNGEST_BASE_URL are configured in the environment (.env)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    """Direct handle to a real SQL Server connection, for teardown-time deletes
    and for asserting on DB state the HTTP surface doesn't expose."""
    conn = e2e_db.connect()
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def redis_client():
    """Direct handle to the real (sync-friendly async) Redis client, for
    teardown-time key deletes."""
    return get_redis()


class Cleanup:
    """Accumulates (table, id, org_id) triples and Redis keys created during
    a test, and deletes them all in teardown -- even on failure -- scoped by
    id+org_id exactly like the production repository layer does, never a
    blanket delete."""

    def __init__(self, db):
        self._db = db
        self._rows: list[tuple[str, str, str | None]] = []
        self._redis_keys: list[str] = []

    def track_row(self, table: str, record_id: str, org_id: str | None = None) -> None:
        self._rows.append((table, record_id, org_id))

    def track_redis_key(self, key: str) -> None:
        self._redis_keys.append(key)

    def flush(self) -> list[str]:
        """Delete everything tracked. Returns a list of human-readable
        cleanup errors (never raises), so a teardown failure never masks the
        real test outcome or leaves other cleanup steps unrun."""
        errors: list[str] = []
        # Delete in reverse-creation order so children (sales/expenses/
        # agent_jobs/users) go before parents (orgs).
        for table, record_id, org_id in reversed(self._rows):
            try:
                e2e_db.delete_tracked(self._db, table, record_id, org_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"cleanup failed for {table}:{record_id}: {exc!r}")
        for key in self._redis_keys:
            try:
                import asyncio

                r = get_redis()
                asyncio.get_event_loop().run_until_complete(r.delete(key))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"redis cleanup failed for {key}: {exc!r}")
        return errors


@pytest.fixture
def cleanup(db):
    c = Cleanup(db)
    yield c
    errors = c.flush()
    if errors:
        # Surfaced as a warning, not a test failure: cleanup problems (e.g.
        # infra already unreachable) shouldn't mask the real assertion
        # result, but must not be silently swallowed either.
        import warnings

        warnings.warn("prompt-2 e2e cleanup issues: " + "; ".join(errors))
