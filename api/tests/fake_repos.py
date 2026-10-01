"""In-memory fakes of the SQL Server repository functions.

Same function names/signatures as `repository/<mod>.py`; installed by the autouse
fixture in tests/conftest.py via `monkeypatch.setattr(repository.<mod>, name, fake)`.
Services must therefore call `module.func(...)` (never `from x import func`).

`FakeSqlDb` mimics `core.db.Db` transactionality for the fakes: it snapshots the
store when created and `rollback()` restores it, so atomicity tests are meaningful.
"""
from __future__ import annotations

import copy
import itertools
import uuid
from typing import Any, Optional

from repository import base as repo_base
from repository.base import DuplicateRecordError

# The REAL get_ownership, captured before install_fake_repos() patches the module attribute
# (lets a unit test exercise the real function's allow-list/SQL shape with a recording Db).
REAL_GET_OWNERSHIP = repo_base.get_ownership


class FakeSqlStore:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.orgs: dict[str, dict[str, Any]] = {}
        self.sales: dict[str, dict[str, Any]] = {}
        self.expenses: dict[str, dict[str, Any]] = {}
        self.agent_jobs: dict[str, dict[str, Any]] = {}
        self.agent_logs: dict[str, dict[str, Any]] = {}
        self.products: dict[str, dict[str, Any]] = {}

    _TABLES = ("users", "orgs", "sales", "expenses", "agent_jobs", "agent_logs", "products")

    def snapshot(self):
        return copy.deepcopy({t: getattr(self, t) for t in self._TABLES})

    def restore(self, snap) -> None:
        for t, rows in copy.deepcopy(snap).items():
            setattr(self, t, rows)


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


_tick = itertools.count(1)


def _now() -> str:
    """Strictly increasing fake timestamps, so "newest first" orderings are deterministic."""
    return f"2026-01-01T00:00:00.{next(_tick):06d}+00:00"


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


def _ledger_fakes(store: FakeSqlStore, *, table: str, singular: str, date_col: str, extra_col: str) -> dict[str, Any]:
    """Fakes for sales/expenses. They scope by id AND org_id exactly like the SQL does, so a
    cross-tenant id simply "does not exist" (=> 404 at the router), and they sum per date range."""
    def tbl() -> dict[str, dict[str, Any]]:
        return getattr(store, table)

    def create(db, *, org_id, created_by, amount, category, description, **extra) -> dict:
        row = {"id": str(uuid.uuid4()), "org_id": org_id, "created_by": created_by, "amount": float(amount),
               "category": category, extra_col: extra.get(extra_col), "description": description,
               date_col: repo_base.today_utc().isoformat(), "created_at": _now(), "updated_at": _now()}
        tbl()[row["id"]] = row
        return dict(row)

    def _ordered(org_id: str) -> list[dict]:
        mine = [r for r in tbl().values() if r["org_id"] == org_id]
        return sorted(mine, key=lambda r: (r[date_col], r["created_at"]), reverse=True)

    def list_(db, *, org_id, limit=100, offset=0) -> list[dict]:
        limit, offset = repo_base.clamp_page(limit, offset)
        return [dict(r) for r in _ordered(org_id)[offset:offset + limit]]

    def _in_month(r: dict, year: int, month: int) -> bool:
        start, end = repo_base.month_range(year, month)
        return start.isoformat() <= r[date_col] < end.isoformat()

    def list_for_month(db, *, org_id, year, month) -> list[dict]:
        return [dict(r) for r in _ordered(org_id) if _in_month(r, year, month)]

    def get_scoped(db, *, org_id, **ids) -> Optional[dict]:
        r = tbl().get(ids[f"{singular}_id"])
        return dict(r) if r and r["org_id"] == org_id else None

    def update_scoped(db, *, org_id, updates, **ids) -> Optional[dict]:
        allowed = {"amount", "category", extra_col, "description"}
        if set(updates) - allowed:
            raise ValueError(f"cannot update columns: {sorted(set(updates) - allowed)}")
        r = tbl().get(ids[f"{singular}_id"])
        if not r or r["org_id"] != org_id:
            return None
        r.update({k: (float(v) if k == "amount" else v) for k, v in updates.items() if v is not None})
        r["updated_at"] = _now()
        return dict(r)

    def delete_scoped(db, *, org_id, **ids) -> bool:
        r = tbl().get(ids[f"{singular}_id"])
        if not r or r["org_id"] != org_id:
            return False
        del tbl()[r["id"]]
        return True

    def sum_month(db, *, org_id, year, month) -> float:
        return float(sum(r["amount"] for r in _ordered(org_id) if _in_month(r, year, month)))

    def by_category(db, *, org_id, year, month) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in _ordered(org_id):
            if _in_month(r, year, month):
                out[r["category"] or "uncategorized"] = out.get(r["category"] or "uncategorized", 0.0) + r["amount"]
        return out

    plural = table
    return {
        f"create_{singular}": create, f"list_{plural}": list_, f"list_{plural}_for_month": list_for_month,
        f"get_{singular}_scoped": get_scoped, f"update_{singular}_scoped": update_scoped,
        f"delete_{singular}_scoped": delete_scoped, f"sum_{plural}_for_month": sum_month,
        f"sum_{plural}_by_category_for_month": by_category,
    }


def build_sales_fakes(store: FakeSqlStore) -> dict[str, Any]:
    fakes = _ledger_fakes(store, table="sales", singular="sale", date_col="sale_date", extra_col="customer_name")
    inner = fakes["create_sale"]
    fakes["create_sale"] = lambda db, *, org_id, created_by, amount, category, description, customer_name: inner(
        db, org_id=org_id, created_by=created_by, amount=amount, category=category, description=description,
        customer_name=customer_name)
    return fakes


def build_expenses_fakes(store: FakeSqlStore) -> dict[str, Any]:
    fakes = _ledger_fakes(store, table="expenses", singular="expense", date_col="expense_date", extra_col="voucher_reference")
    inner = fakes["create_expense"]
    fakes["create_expense"] = lambda db, *, org_id, created_by, amount, category, voucher_reference, description: inner(
        db, org_id=org_id, created_by=created_by, amount=amount, category=category, description=description,
        voucher_reference=voucher_reference)
    return fakes


def build_products_fakes(store: FakeSqlStore) -> dict[str, Any]:
    """Fakes for products. Like the DB: id AND org_id scoping, UNIQUE (org_id, sku) (=> DuplicateRecordError),
    CHECK stock_qty >= 0 / price >= 0 / reorder_level >= 0 (=> IntegrityError-like AssertionError), and an
    adjust that only applies when stock + delta >= 0 (the WHERE guard of the real statement)."""
    def _check(row: dict) -> None:
        if row["stock_qty"] < 0 or row["price"] < 0 or row["reorder_level"] < 0:
            raise AssertionError("CHECK constraint violated (547)")

    def _sku_taken(org_id: str, sku: str, except_id: str | None = None) -> bool:
        return any(r["org_id"] == org_id and r["sku"].lower() == sku.lower() and r["id"] != except_id  # CI collation
                   for r in store.products.values())

    def create_product(db, *, org_id, created_by, name, sku, price, stock_qty, reorder_level) -> dict:
        if _sku_taken(org_id, sku):
            raise DuplicateRecordError("duplicate (org_id, sku) (2627)")
        row = {"id": str(uuid.uuid4()), "org_id": org_id, "created_by": created_by, "name": name, "sku": sku,
               "price": float(price), "stock_qty": int(stock_qty), "reorder_level": int(reorder_level),
               "is_active": True, "created_at": _now(), "updated_at": _now()}
        _check(row)
        store.products[row["id"]] = row
        return dict(row)

    def list_products(db, *, org_id, limit=100, offset=0, low_stock=False) -> list[dict]:
        limit, offset = repo_base.clamp_page(limit, offset)
        mine = [r for r in store.products.values() if r["org_id"] == org_id
                and (not low_stock or r["stock_qty"] <= r["reorder_level"])]
        mine.sort(key=lambda r: (r["name"], r["id"]))
        return [dict(r) for r in mine[offset:offset + limit]]

    def get_product_scoped(db, *, product_id, org_id) -> Optional[dict]:
        r = store.products.get(product_id)
        return dict(r) if r and r["org_id"] == org_id else None

    def update_product_scoped(db, *, product_id, org_id, updates) -> Optional[dict]:
        allowed = {"name", "sku", "price", "reorder_level", "is_active"}
        if set(updates) - allowed:
            raise ValueError(f"cannot update columns: {sorted(set(updates) - allowed)}")
        r = store.products.get(product_id)
        if not r or r["org_id"] != org_id:
            return None
        if updates.get("sku") is not None and _sku_taken(org_id, updates["sku"], except_id=product_id):
            raise DuplicateRecordError("duplicate (org_id, sku) (2627)")
        candidate = {**r, **{k: v for k, v in updates.items() if v is not None}}
        candidate["price"] = float(candidate["price"])
        _check(candidate)
        r.update(candidate)
        r["updated_at"] = _now()
        return dict(r)

    def delete_product_scoped(db, *, product_id, org_id) -> bool:
        r = store.products.get(product_id)
        if not r or r["org_id"] != org_id:
            return False
        del store.products[product_id]
        return True

    def adjust_stock_scoped(db, *, product_id, org_id, delta) -> Optional[dict]:
        r = store.products.get(product_id)
        if not r or r["org_id"] != org_id or r["stock_qty"] + int(delta) < 0:
            return None
        r["stock_qty"] += int(delta)
        r["updated_at"] = _now()
        return dict(r)

    return {k: v for k, v in locals().items() if callable(v) and k not in ("store", "_check", "_sku_taken")}


def build_agent_jobs_fakes(store: FakeSqlStore) -> dict[str, Any]:
    def create_job(db, *, job_name, org_id, requested_by, input_payload=None) -> dict:
        row = {"id": str(uuid.uuid4()), "job_name": job_name, "org_id": org_id, "requested_by": requested_by,
               "status": "pending", "current_step": None, "input_payload": input_payload or {}, "result": None,
               "error_details": None, "created_at": _now(), "updated_at": _now()}
        store.agent_jobs[row["id"]] = row
        return copy.deepcopy(row)

    def get_job_scoped(db, *, job_id, org_id) -> Optional[dict]:
        j = store.agent_jobs.get(job_id)
        return copy.deepcopy(j) if j and j["org_id"] == org_id else None

    def update_job_status(db, *, job_id, org_id, status, current_step=None, result=None, error_details=None) -> Optional[dict]:
        j = store.agent_jobs.get(job_id)
        if not j or j["org_id"] != org_id:
            return None
        j["status"] = status
        for k, v in (("current_step", current_step), ("result", result), ("error_details", error_details)):
            if v is not None:
                j[k] = copy.deepcopy(v)
        j["updated_at"] = _now()
        return copy.deepcopy(j)

    def add_log(db, *, job_id, org_id, step_name, action_summary, insights_generated=None) -> dict:
        j = store.agent_jobs.get(job_id)
        if not j or j["org_id"] != org_id:  # INSERT ... SELECT FROM agent_jobs WHERE id AND org_id => no row
            raise RuntimeError("Failed to write agent log (job not found for this org)")
        row = {"id": str(uuid.uuid4()), "job_id": job_id, "org_id": org_id, "step_name": step_name,
               "action_summary": action_summary, "insights_generated": copy.deepcopy(insights_generated or {}),
               "executed_at": _now(), "created_at": _now(), "updated_at": _now()}
        store.agent_logs[row["id"]] = row
        return copy.deepcopy(row)

    def list_logs_for_job(db, *, job_id, org_id) -> list[dict]:
        logs = [l for l in store.agent_logs.values() if l["job_id"] == job_id and l["org_id"] == org_id]
        return [copy.deepcopy(l) for l in sorted(logs, key=lambda l: l["executed_at"])]

    def get_completed_steps(db, *, job_id, org_id) -> set[str]:
        return {l["step_name"] for l in list_logs_for_job(db, job_id=job_id, org_id=org_id)}

    return {k: v for k, v in locals().items() if callable(v) and k != "store"}


def build_ownership_fake(store: FakeSqlStore):
    def get_ownership(db, *, table: str, record_id: str, org_id: str) -> bool:
        if table not in ("users", "sales", "expenses", "agent_jobs", "products"):
            raise repo_base.RepositoryError(f"ownership check not supported for table {table!r}")
        r = getattr(store, table).get(record_id)
        return bool(r and r.get("org_id") == org_id)

    return get_ownership


def install_fake_repos(monkeypatch, store: FakeSqlStore) -> None:
    from repository import (agent_jobs_repository, expenses_repository, health_repository, orgs_repository,
                            products_repository, sales_repository, users_repository)

    for name, fn in build_sales_fakes(store).items():
        monkeypatch.setattr(sales_repository, name, fn)
    for name, fn in build_expenses_fakes(store).items():
        monkeypatch.setattr(expenses_repository, name, fn)
    for name, fn in build_products_fakes(store).items():
        monkeypatch.setattr(products_repository, name, fn)
    for name, fn in build_agent_jobs_fakes(store).items():
        monkeypatch.setattr(agent_jobs_repository, name, fn)
    monkeypatch.setattr(repo_base, "get_ownership", build_ownership_fake(store))
    monkeypatch.setattr(health_repository, "ping", lambda db: True)

    for name, fn in build_users_fakes(store).items():
        monkeypatch.setattr(users_repository, name, fn)
    for name, fn in build_orgs_fakes(store).items():
        monkeypatch.setattr(orgs_repository, name, fn)
