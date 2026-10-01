from __future__ import annotations

import fakeredis.aioredis
import pytest

from core.clients import set_db_factory, set_redis, set_supabase
from tests.fake_repos import FakeSqlDb, FakeSqlStore, install_fake_repos
from tests.fakes import FakeSupabase


@pytest.fixture
def fake_db() -> FakeSupabase:
    return FakeSupabase()


@pytest.fixture(autouse=True)
def _wire_fakes(fake_db):
    """Auto-injects fake Supabase + fakeredis into the app's client singletons
    for every test, so nothing ever touches real network services."""
    set_supabase(fake_db)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis(fake_redis)
    yield


@pytest.fixture
def sql_store() -> FakeSqlStore:
    return FakeSqlStore()


@pytest.fixture(autouse=True)
def _wire_sql_fakes(monkeypatch, sql_store):
    """SQL Server slices: users/orgs repositories are replaced by in-memory fakes and
    `get_db_connection()` hands out a FakeSqlDb. (More repos are added per slice.)"""
    install_fake_repos(monkeypatch, sql_store)
    set_db_factory(lambda: FakeSqlDb(sql_store))
    yield
    set_db_factory(None)
