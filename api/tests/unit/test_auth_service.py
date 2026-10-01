"""auth_service.register: atomic (one transaction) and duplicate-safe, against fake repos."""
from __future__ import annotations

import pytest

from repository import orgs_repository
from services import auth_service
from tests.fake_repos import FakeSqlDb


def _register(db, email="a@example.com"):
    return auth_service.register(db, email=email, password="pw12345678", full_name="A", org_name="Org")


def test_register_links_user_org_and_commits(sql_store):
    db = FakeSqlDb(sql_store)
    out = _register(db)
    assert out["user"]["org_id"] == out["org"]["id"] and out["org"]["owner_id"] == out["user"]["id"]
    assert out["user"]["role"] == "owner" and db.commits == 1 and db.rollbacks == 0


def test_register_failure_midway_leaves_no_orphan_user(sql_store, monkeypatch):
    def boom(db, **kw):
        raise RuntimeError("org insert failed")

    monkeypatch.setattr(orgs_repository, "create_org", boom)
    db = FakeSqlDb(sql_store)
    with pytest.raises(RuntimeError):
        _register(db)
    assert db.rollbacks == 1
    assert sql_store.users == {} and sql_store.orgs == {}


def test_register_failure_at_link_step_rolls_back_user_and_org(sql_store, monkeypatch):
    from repository import users_repository

    def boom(db, **kw):
        raise RuntimeError("link failed")

    monkeypatch.setattr(users_repository, "set_user_org", boom)
    with pytest.raises(RuntimeError):
        _register(FakeSqlDb(sql_store))
    assert sql_store.users == {} and sql_store.orgs == {}


def test_duplicate_email_precheck(sql_store):
    _register(FakeSqlDb(sql_store))
    with pytest.raises(auth_service.AuthError, match="Email already registered"):
        _register(FakeSqlDb(sql_store))
    assert len(sql_store.users) == 1


def test_duplicate_email_race_maps_unique_violation_to_autherror(sql_store, monkeypatch):
    """Both requests pass the pre-check; the UNIQUE constraint fires inside the transaction."""
    from repository import users_repository

    _register(FakeSqlDb(sql_store))
    monkeypatch.setattr(users_repository, "get_user_by_email", lambda db, email: None)  # pre-check misses
    db = FakeSqlDb(sql_store)
    with pytest.raises(auth_service.AuthError, match="Email already registered"):
        _register(db)
    assert db.rollbacks == 1 and len(sql_store.users) == 1 and len(sql_store.orgs) == 1
