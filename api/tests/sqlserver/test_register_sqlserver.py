"""Real SQL Server tests (slice F0a). Run with: RUN_MSSQL=1 pytest tests/sqlserver -v

Needs sql_server/01_foundation.sql applied and MSSQL_* env / .env pointing at HandsellerDB.
"""
from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_MSSQL") != "1", reason="set RUN_MSSQL=1 to run against SQL Server")


@pytest.fixture
def real_db():
    from core.clients import get_db_connection, set_db_factory

    set_db_factory(None)
    db = get_db_connection()
    yield db
    db.rollback()
    db.close()


@pytest.fixture(autouse=True)
def _real_repos(monkeypatch):
    """Undo the in-memory fakes installed by tests/conftest.py: use the real repositories."""
    from core.clients import set_db_factory

    monkeypatch.undo()
    set_db_factory(None)


def _cleanup(db, email):
    db.execute("UPDATE orgs SET owner_id = NULL WHERE owner_id IN (SELECT id FROM users WHERE email = ?)", (email,))
    db.execute("DELETE FROM users WHERE email = ?", (email,))
    db.execute("DELETE FROM orgs WHERE owner_id IS NULL AND name LIKE N'mssql-test-%'")
    db.commit()


def test_register_atomic_and_linked(real_db):
    from services import auth_service

    email = f"mssql-{uuid.uuid4().hex[:8]}@example.com"
    try:
        out = auth_service.register(real_db, email=email, password="pw12345678", full_name="T", org_name="mssql-test-org")
        assert out["user"]["org_id"] == out["org"]["id"] and out["org"]["owner_id"] == out["user"]["id"]
        assert isinstance(out["user"]["id"], str) and isinstance(out["user"]["created_at"], str)
    finally:
        _cleanup(real_db, email)


def test_register_rollback_leaves_no_orphan(real_db, monkeypatch):
    from repository import orgs_repository
    from services import auth_service

    email = f"mssql-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(orgs_repository, "create_org", lambda db, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        auth_service.register(real_db, email=email, password="pw12345678", full_name="T", org_name="mssql-test-org")
    assert real_db.query_one("SELECT 1 AS x FROM users WHERE email = ?", (email,)) is None


def test_unique_email_enforced_by_constraint(real_db):
    from repository import base, users_repository

    email = f"mssql-{uuid.uuid4().hex[:8]}@example.com"
    try:
        users_repository.create_user(real_db, email=email, hashed_password="h", full_name=None, org_id=None)
        real_db.commit()
        with pytest.raises(base.DuplicateRecordError):
            users_repository.create_user(real_db, email=email, hashed_password="h", full_name=None, org_id=None)
    finally:
        real_db.rollback()
        _cleanup(real_db, email)
