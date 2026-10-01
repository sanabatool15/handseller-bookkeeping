"""Real SQL Server tests (slice F2: customers). Run with: RUN_MSSQL=1 pytest tests/sqlserver -v

Needs sql_server/01..04 applied and MSSQL_* env / .env pointing at HandsellerDB.
Every test creates its own orgs/users (unique names) and removes them again.
"""
from __future__ import annotations

import os
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
        out = auth_service.register(db, email=self.email, password="pw12345678", full_name="T", org_name="mssql-test-customers")
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
        real_db.execute("DELETE FROM sales WHERE org_id = ?", (t.org_id,))
        real_db.execute("DELETE FROM customers WHERE org_id = ?", (t.org_id,))
        real_db.execute("UPDATE orgs SET owner_id = NULL WHERE id = ?", (t.org_id,))
        real_db.execute("DELETE FROM users WHERE org_id = ?", (t.org_id,))
        real_db.execute("DELETE FROM orgs WHERE id = ?", (t.org_id,))
    real_db.commit()


def _cust(db, t, name="Ana", phone=None, **kw):
    from services import customers_service

    c = customers_service.create_customer(db, org_id=t.org_id, user_id=t.user_id, name=name, phone=phone, **kw)
    db.commit()
    return c


def _sale(db, t, amount, customer_id=None):
    from services import sales_service

    s = sales_service.create_sale(db, org_id=t.org_id, user_id=t.user_id, amount=amount, category="g", customer_id=customer_id)
    db.commit()
    return s


def test_summary_join_correctness_and_org_scoping(real_db, tenants):
    from repository import customers_repository as repo

    a, b = tenants(), tenants()
    c1, c2 = _cust(real_db, a, "One"), _cust(real_db, a, "Two")
    _sale(real_db, a, 10.25, c1["id"])
    _sale(real_db, a, 5, c1["id"])
    _sale(real_db, a, 100, c2["id"])
    _sale(real_db, a, 1)                 # no customer
    _sale(real_db, b, 7)                 # other org
    sm = repo.get_customer_summary_scoped(real_db, customer_id=c1["id"], org_id=a.org_id)
    assert sm["total_sales"] == 15.25 and sm["sale_count"] == 2 and isinstance(sm["last_sale_date"], str)
    assert sm["customer"]["id"] == c1["id"] and "total_sales" not in sm["customer"]
    empty = _cust(real_db, a, "Empty")
    se = repo.get_customer_summary_scoped(real_db, customer_id=empty["id"], org_id=a.org_id)
    assert se["total_sales"] == 0 and se["sale_count"] == 0 and se["last_sale_date"] is None
    assert repo.get_customer_summary_scoped(real_db, customer_id=c1["id"], org_id=b.org_id) is None


def test_filtered_unique_phone_index(real_db, tenants):
    from services import customers_service as svc

    a, b = tenants(), tenants()
    _cust(real_db, a, "P1", phone="555")
    with pytest.raises(svc.DuplicatePhoneError):
        _cust(real_db, a, "P2", phone="555")
    real_db.rollback()
    _cust(real_db, b, "P3", phone="555")        # same phone, other org
    _cust(real_db, a, "N1")                      # NULL phones never collide (WHERE phone IS NOT NULL)
    _cust(real_db, a, "N2")
    n3 = _cust(real_db, a, "N3", phone="777")
    with pytest.raises(svc.DuplicatePhoneError):
        svc.update_customer(real_db, org_id=a.org_id, customer_id=n3["id"], updates={"phone": "555"})
    real_db.rollback()
    cleared = svc.update_customer(real_db, org_id=a.org_id, customer_id=n3["id"], updates={"phone": None})
    real_db.commit()
    assert cleared["phone"] is None


def test_delete_blocked_with_sales_then_allowed_after_unlink(real_db, tenants):
    from services import customers_service as svc
    from services import sales_service

    a, b = tenants(), tenants()
    c = _cust(real_db, a)
    s = _sale(real_db, a, 3, c["id"])
    with pytest.raises(svc.CustomerInUseError):
        svc.delete_customer(real_db, org_id=a.org_id, customer_id=c["id"])
    with pytest.raises(svc.NotFoundError):
        svc.delete_customer(real_db, org_id=b.org_id, customer_id=c["id"])
    sales_service.update_sale(real_db, org_id=a.org_id, sale_id=s["id"], updates={"customer_id": None})
    real_db.commit()
    svc.delete_customer(real_db, org_id=a.org_id, customer_id=c["id"])
    real_db.commit()
    with pytest.raises(svc.NotFoundError):
        svc.get_customer(real_db, org_id=a.org_id, customer_id=c["id"])


def test_composite_fk_rejects_cross_org_link_at_db_level(real_db, tenants):
    a, b = tenants(), tenants()
    c = _cust(real_db, a)
    with pytest.raises(Exception):  # FK_sales_customer (error 547): bypasses the service check, straight SQL
        real_db.execute("INSERT INTO sales (org_id, amount, customer_id) VALUES (?, 1, ?)", (b.org_id, c["id"]))
    real_db.rollback()


def test_search_wildcards_are_literal_and_trigger_and_isolation(real_db, tenants):
    import time

    from repository import customers_repository as repo

    a, b = tenants(), tenants()
    for n in ("100% Cotton", "1000 Shop", "a_b", "axb", "[x] Co"):
        _cust(real_db, a, n)
    _cust(real_db, b, "100 Other")
    names = lambda q: [c["name"] for c in repo.list_customers(real_db, org_id=a.org_id, q=q)]  # noqa: E731
    assert names("100%") == ["100% Cotton"]
    assert names("%") == [] and names("_") == []
    assert names("a_") == ["a_b"]
    assert names("[x") == ["[x] Co"]
    assert sorted(names("100")) == ["1000 Shop", "100% Cotton"]  # collation decides the order, not the set
    c = repo.list_customers(real_db, org_id=a.org_id, q="a_b")[0]
    time.sleep(1.1)
    upd = repo.update_customer_scoped(real_db, customer_id=c["id"], org_id=a.org_id, updates={"notes": "hi"})
    real_db.commit()
    assert upd["notes"] == "hi"
    fresh = repo.get_customer_scoped(real_db, customer_id=c["id"], org_id=a.org_id)
    assert fresh["updated_at"] > c["updated_at"]
    assert repo.get_customer_scoped(real_db, customer_id=c["id"], org_id=b.org_id) is None
    assert repo.update_customer_scoped(real_db, customer_id=c["id"], org_id=b.org_id, updates={"name": "x"}) is None
    assert repo.delete_customer_scoped(real_db, customer_id=c["id"], org_id=b.org_id) is False
