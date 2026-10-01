"""Real SQL Server tests (slice F1: products & stock). Run with: RUN_MSSQL=1 pytest tests/sqlserver -v

Needs sql_server/01, 02 and 03_products.sql applied and MSSQL_* env / .env pointing at HandsellerDB.
Every test creates its own orgs/users (unique names) and removes them again.
"""
from __future__ import annotations

import os
import threading
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_MSSQL") != "1", reason="set RUN_MSSQL=1 to run against SQL Server")


@pytest.fixture(autouse=True)
def _real_repos(monkeypatch):
    from core.clients import set_db_factory

    monkeypatch.undo()
    set_db_factory(None)


@pytest.fixture
def real_db():
    from core.clients import get_db_connection

    db = get_db_connection()
    yield db
    db.rollback()
    db.close()


class Tenant:
    def __init__(self, db):
        from services import auth_service

        self.email = f"mssql-{uuid.uuid4().hex[:8]}@example.com"
        out = auth_service.register(db, email=self.email, password="pw12345678", full_name="T", org_name="mssql-test-products")
        self.org_id, self.user_id = out["org"]["id"], out["user"]["id"]


@pytest.fixture
def tenants(real_db):
    made: list[Tenant] = []

    def make():
        t = Tenant(real_db)
        made.append(t)
        return t

    yield make
    real_db.rollback()
    for t in made:
        real_db.execute("DELETE FROM products WHERE org_id = ?", (t.org_id,))
        real_db.execute("UPDATE orgs SET owner_id = NULL WHERE id = ?", (t.org_id,))
        real_db.execute("DELETE FROM users WHERE org_id = ?", (t.org_id,))
        real_db.execute("DELETE FROM orgs WHERE id = ?", (t.org_id,))
    real_db.commit()


def _create(db, t, sku="SKU-1", stock=5, **kw):
    from services import products_service

    p = products_service.create_product(db, org_id=t.org_id, user_id=t.user_id, name="Mug", sku=sku, price=9.99, stock_qty=stock, **kw)
    db.commit()
    return p


def test_check_constraint_rejects_negative_stock(real_db, tenants):
    t = tenants()
    p = _create(real_db, t)
    with pytest.raises(Exception):  # CK_products_stock_qty (error 547): bypasses the app, straight SQL
        real_db.execute("UPDATE products SET stock_qty = -1 WHERE id = ? AND org_id = ?", (p["id"], t.org_id))
    real_db.rollback()
    with pytest.raises(Exception):  # CK_products_price
        real_db.execute("UPDATE products SET price = -1 WHERE id = ? AND org_id = ?", (p["id"], t.org_id))
    real_db.rollback()
    with pytest.raises(Exception):  # CK_products_reorder_level
        real_db.execute("UPDATE products SET reorder_level = -1 WHERE id = ? AND org_id = ?", (p["id"], t.org_id))
    real_db.rollback()


def test_unique_sku_per_org_but_allowed_in_other_org(real_db, tenants):
    from repository.base import DuplicateRecordError
    from services import products_service

    a, b = tenants(), tenants()
    _create(real_db, a, sku="DUP")
    with pytest.raises(products_service.DuplicateSkuError):
        _create(real_db, a, sku="DUP")
    real_db.rollback()
    _create(real_db, b, sku="DUP")  # same SKU in another org is fine
    from repository import products_repository

    with pytest.raises(DuplicateRecordError):
        products_repository.create_product(real_db, org_id=a.org_id, created_by=a.user_id, name="x", sku="DUP", price=1, stock_qty=0, reorder_level=0)
    real_db.rollback()


def test_json_shape_and_trigger(real_db, tenants):
    import time

    from repository import products_repository

    t = tenants()
    p = _create(real_db, t, stock=3, reorder_level=1)
    assert isinstance(p["id"], str) and p["price"] == 9.99 and isinstance(p["price"], float)
    assert p["stock_qty"] == 3 and p["is_active"] in (True, 1) and isinstance(p["created_at"], str)
    time.sleep(1.1)
    upd = products_repository.update_product_scoped(real_db, product_id=p["id"], org_id=t.org_id, updates={"name": "Big"})
    real_db.commit()
    assert upd["name"] == "Big" and upd["stock_qty"] == 3
    fresh = products_repository.get_product_scoped(real_db, product_id=p["id"], org_id=t.org_id)
    assert fresh["updated_at"] > p["updated_at"]


def test_tenant_isolation(real_db, tenants):
    from repository import base, products_repository as repo

    a, b = tenants(), tenants()
    p = _create(real_db, a)
    assert repo.get_product_scoped(real_db, product_id=p["id"], org_id=b.org_id) is None
    assert repo.update_product_scoped(real_db, product_id=p["id"], org_id=b.org_id, updates={"name": "x"}) is None
    assert repo.adjust_stock_scoped(real_db, product_id=p["id"], org_id=b.org_id, delta=1) is None
    assert repo.delete_product_scoped(real_db, product_id=p["id"], org_id=b.org_id) is False
    real_db.commit()
    assert repo.get_product_scoped(real_db, product_id=p["id"], org_id=a.org_id)["stock_qty"] == 5
    assert base.get_ownership(real_db, table="products", record_id=p["id"], org_id=b.org_id) is False
    assert base.get_ownership(real_db, table="products", record_id=p["id"], org_id=a.org_id) is True


def test_adjust_stock_insufficient_and_not_found(real_db, tenants):
    from services import products_service as svc

    t = tenants()
    p = _create(real_db, t, stock=2)
    assert svc.adjust_stock(real_db, org_id=t.org_id, product_id=p["id"], delta=-2)["stock_qty"] == 0
    with pytest.raises(svc.InsufficientStockError):
        svc.adjust_stock(real_db, org_id=t.org_id, product_id=p["id"], delta=-1)
    with pytest.raises(svc.NotFoundError):
        svc.adjust_stock(real_db, org_id=t.org_id, product_id=str(uuid.uuid4()), delta=1)
    real_db.commit()


def test_adjust_stock_race_never_goes_below_zero(real_db, tenants):
    """N threads each try -1 on a stock of N-3: exactly N-3 succeed, 3 get 'insufficient', final stock is 0."""
    from core.clients import get_db_connection
    from repository import products_repository as repo

    n, stock = 12, 9
    t = tenants()
    p = _create(real_db, t, stock=stock)
    results: list[bool] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker():
        db = get_db_connection()  # one connection per thread
        try:
            barrier.wait(timeout=30)
            row = repo.adjust_stock_scoped(db, product_id=p["id"], org_id=t.org_id, delta=-1)
            db.commit()
            with lock:
                results.append(row is not None)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not errors, errors
    assert sum(results) == stock and results.count(False) == n - stock
    final = repo.get_product_scoped(real_db, product_id=p["id"], org_id=t.org_id)
    assert final["stock_qty"] == 0
