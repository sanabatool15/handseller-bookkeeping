"""In-memory fakes of the SQL Server repository functions.

Same function names/signatures as `repository/<mod>.py`; installed by the autouse
fixture in tests/conftest.py via `monkeypatch.setattr(repository.<mod>, name, fake)`.
Services must therefore call `module.func(...)` (never `from x import func`).

`FakeSqlDb` mimics `core.db.Db` transactionality for the fakes: it snapshots the
store when created and `rollback()` restores it, so atomicity tests are meaningful.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Optional

from repository.base import DuplicateRecordError


class FakeSqlStore:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.orgs: dict[str, dict[str, Any]] = {}

    def snapshot(self):
        return copy.deepcopy((self.users, self.orgs))

    def restore(self, snap) -> None:
        self.users, self.orgs = copy.deepcopy(snap)


class FakeSqlDb:
    """Stand-in for core.db.Db handed to services/routers in tests."""

    def __init__(self, store: FakeSqlStore) -> None:
        self.store = store
        self._snap = store.snapshot()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1
        self._snap = self.store.snapshot()

    def rollback(self) -> None:
        self.rollbacks += 1
        self.store.restore(self._snap)

    def close(self) -> None:
        self.closed = True

    def query(self, *a, **k):  # pragma: no cover - guard: fakes never run SQL
        raise AssertionError("FakeSqlDb does not execute SQL; repositories must be faked")

    query_one = execute = query


def _now() -> str:
    return "2026-01-01T00:00:00+00:00"


def build_users_fakes(store: FakeSqlStore) -> dict[str, Any]:
    def get_user_by_email(db, email: str) -> Optional[dict]:
        for u in store.users.values():
            if u["email"].lower() == email.lower():  # SQL Server default collation is CI
                return dict(u)
        return None

    def get_user_by_id_scoped(db, *, user_id: str, org_id: str) -> Optional[dict]:
        u = store.users.get(user_id)
        return dict(u) if u and u["org_id"] == org_id else None

    def create_user(db, *, email, hashed_password, full_name, org_id, role="member") -> dict:
        if get_user_by_email(db, email):
            raise DuplicateRecordError("duplicate email (2627)")
        row = {"id": str(uuid.uuid4()), "org_id": org_id, "email": email, "full_name": full_name,
               "hashed_password": hashed_password, "role": role, "created_at": _now(), "updated_at": _now()}
        store.users[row["id"]] = row
        return dict(row)

    def set_user_org(db, *, user_id: str, org_id: str) -> dict:
        u = store.users.get(user_id)
        if u is None or u["org_id"] is not None:
            raise RuntimeError("Failed to link user to org")
        u["org_id"] = org_id
        return dict(u)

    return {k: v for k, v in locals().items() if callable(v) and k != "store"}


def build_orgs_fakes(store: FakeSqlStore) -> dict[str, Any]:
    def create_org(db, *, name: str, owner_id: str) -> dict:
        row = {"id": str(uuid.uuid4()), "name": name, "owner_id": owner_id, "created_at": _now(), "updated_at": _now()}
        store.orgs[row["id"]] = row
        return dict(row)

    def get_org_scoped(db, *, org_id: str, owner_id: str) -> Optional[dict]:
        o = store.orgs.get(org_id)
        return dict(o) if o and o["owner_id"] == owner_id else None

    return {k: v for k, v in locals().items() if callable(v) and k != "store"}


def install_fake_repos(monkeypatch, store: FakeSqlStore) -> None:
    from repository import orgs_repository, users_repository

    for name, fn in build_users_fakes(store).items():
        monkeypatch.setattr(users_repository, name, fn)
    for name, fn in build_orgs_fakes(store).items():
        monkeypatch.setattr(orgs_repository, name, fn)
