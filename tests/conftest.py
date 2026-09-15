from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.clients import set_redis, set_supabase
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
