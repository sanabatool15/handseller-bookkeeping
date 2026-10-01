from __future__ import annotations

import fakeredis.aioredis
import pytest

from core.clients import set_autocommit_factory, set_db_factory, set_redis
from tests.fake_repos import FakeLogDb, FakeSqlDb, FakeSqlStore, install_fake_repos


@pytest.fixture
def sql_store() -> FakeSqlStore:
    return FakeSqlStore()


@pytest.fixture
def fake_db(sql_store) -> FakeSqlDb:
    """The Db handle services/tools receive in unit tests (repositories are faked, it never runs SQL)."""
    return FakeSqlDb(sql_store)


@pytest.fixture(autouse=True)
def _wire_fakes():
    """Injects fakeredis into the app's client singleton for every test, so nothing ever touches
    real network services."""
    set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))
    yield


@pytest.fixture(autouse=True)
def _wire_sql_fakes(monkeypatch, sql_store):
    """Every repository module is replaced by in-memory fakes that enforce id+org_id scoping,
    and `get_db_connection()` hands out a FakeSqlDb over the same store (what the FastAPI
    dependency, Inngest jobs and the MCP server receive)."""
    install_fake_repos(monkeypatch, sql_store)
    set_db_factory(lambda: FakeSqlDb(sql_store))
    set_autocommit_factory(lambda: FakeLogDb(sql_store))  # the SEPARATE connection the txn log is written on
    yield
    set_db_factory(None)
    set_autocommit_factory(None)
