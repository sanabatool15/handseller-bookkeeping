"""Shared fixtures for integration tests: a TestClient with the Supabase
client entirely replaced by an in-memory fake, so no network/credentials
are required.
"""
import uuid
from datetime import datetime, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


class _InMemoryTable:
    def __init__(self, store: dict, name: str):
        self.store = store
        self.name = name
        self._filters: list[tuple[str, str, object]] = []
        self._order = None
        self._limit = None
        self._insert_payload = None
        self._delete = False

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def delete(self):
        self._delete = True
        return self

    def eq(self, field, value):
        self._filters.append(("eq", field, value))
        return self

    def gte(self, field, value):
        self._filters.append(("gte", field, value))
        return self

    def lte(self, field, value):
        self._filters.append(("lte", field, value))
        return self

    def order(self, field, desc=False):
        self._order = (field, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row):
        for op, field, value in self._filters:
            row_val = row.get(field)
            if op == "eq" and row_val != value:
                return False
            if op == "gte" and (row_val is None or row_val < value):
                return False
            if op == "lte" and (row_val is None or row_val > value):
                return False
        return True

    def execute(self):
        rows = self.store.setdefault(self.name, [])

        if self._insert_payload is not None:
            row = dict(self._insert_payload)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            rows.append(row)
            return _Result([row])

        if self._delete:
            matched = [r for r in rows if self._matches(r)]
            self.store[self.name] = [r for r in rows if not self._matches(r)]
            return _Result(matched)

        result = [r for r in rows if self._matches(r)]
        if self._order:
            field, desc = self._order
            result.sort(key=lambda r: r.get(field), reverse=desc)
        if self._limit is not None:
            result = result[: self._limit]
        return _Result(result)


class _Result:
    def __init__(self, data):
        self.data = data


class FakeSupabaseClient:
    def __init__(self):
        self._store: dict = {}

    def table(self, name: str) -> _InMemoryTable:
        return _InMemoryTable(self._store, name)


@pytest.fixture
def fake_supabase(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr("app.core.db.get_client", lambda: client)
    return client


@pytest.fixture
def user_id():
    return str(uuid.uuid4())


@pytest.fixture
def org_id():
    return str(uuid.uuid4())


@pytest.fixture
def auth_token(user_id, org_id):
    settings = get_settings()
    payload = {"sub": user_id, "org_id": org_id}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def client(fake_supabase, org_id, user_id, monkeypatch):
    # Seed the org so get_ownership() passes for this user.
    fake_supabase.table("orgs").insert({"id": org_id, "owner_id": user_id, "name": "Test Org"}).execute()

    from app.main import app

    return TestClient(app)
