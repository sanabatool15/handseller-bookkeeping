"""Real SQL Server tests (slice F3: sale items, cash ledger, usp_RecordSale / usp_VoidSale).
Run with: RUN_MSSQL=1 pytest tests/sqlserver/test_sales_items_sqlserver.py -v

Needs sql_server/01..05 applied and MSSQL_* env / .env pointing at HandsellerDB.
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
        out = auth_service.register(db, email=self.email, password="pw12345678", full_name="T", org_name="mssql-test-sales-items")
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
        for table in ("sale_items", "sales", "cash_ledger", "cash_accounts", "products"):
            real_db.execute(f"DELETE FROM {table} WHERE org_id = ?", (t.org_id,))  # test-only literal table names
        real_db.execute("UPDATE orgs SET owner_id = NULL WHERE id = ?", (t.org_id,))
        real_db.execute("DELETE FROM users WHERE org_id = ?", (t.org_id,))
        real_db.execute("DELETE FROM orgs WHERE id = ?", (t.org_id,))
    real_db.commit()


def _product(db, t, sku, stock=5, price=10.0, name="Mug"):
    from services import products_service

    p = products_service.create_product(db, org_id=t.org_id, user_id=t.user_id, name=name, sku=sku, price=price, stock_qty=stock)
    db.commit()
    return p


def _stock(db, t, pid):
    from services import products_service

    db.commit()  # fresh snapshot of committed data
    return products_service.get_product(db, org_id=t.org_id, product_id=pid)["stock_qty"]


def _balance(db, t):
    from repository import cash_repository

    db.commit()
    return cash_repository.get_balance(db, org_id=t.org_id)["balance"]


def _sell(db, t, items, **kw):
    from services import sales_service

    sale = sales_service.create_sale(db, org_id=t.org_id, user_id=t.user_id, category="retail", items=items, **kw)
    db.commit()
    return sale


def _count(db, table, t):
    db.commit()
    return db.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE org_id = ?", (t.org_id,))["n"]  # test-only literal table names


def test_commit_with_items_updates_stock_balance_and_ledger(real_db, tenants):
    t = tenants()
    mug, pen = _product(real_db, t, "M"), _product(real_db, t, "P", price=2.5, name="Pen", stock=10)
    sale = _sell(real_db, t, [{"product_id": mug["id"], "quantity": 2}, {"product_id": pen["id"], "quantity": 4, "unit_price": 3}])
    assert sale["amount"] == 32.0 and len(sale["items"]) == 2
    assert {i["line_total"] for i in sale["items"]} == {20.0, 12.0}  # computed persisted column
    assert _stock(real_db, t, mug["id"]) == 3 and _stock(real_db, t, pen["id"]) == 6
    assert _balance(real_db, t) == 32.0
    row = real_db.query_one("SELECT entry_type, amount, balance_after, ref_id FROM cash_ledger WHERE org_id = ?", (t.org_id,))
    assert row["entry_type"] == "sale" and row["amount"] == 32.0 and row["balance_after"] == 32.0 and row["ref_id"] == sale["id"]


def test_insufficient_stock_rolls_back_everything(real_db, tenants):
    from services import sales_service

    t = tenants()
    ok, scarce = _product(real_db, t, "A"), _product(real_db, t, "B", stock=1, name="Pen")
    with pytest.raises(sales_service.InsufficientStockError, match="Pen"):
        _sell(real_db, t, [{"product_id": ok["id"], "quantity": 2}, {"product_id": scarce["id"], "quantity": 3}])
    assert _stock(real_db, t, ok["id"]) == 5 and _stock(real_db, t, scarce["id"]) == 1
    assert _count(real_db, "sales", t) == 0 and _count(real_db, "sale_items", t) == 0 and _count(real_db, "cash_ledger", t) == 0
    assert _balance(real_db, t) == 0.0


def test_savepoint_partial_keeps_valid_items(real_db, tenants):
    t = tenants()
    ok, scarce = _product(real_db, t, "A"), _product(real_db, t, "B", stock=1, name="Pen")
    sale = _sell(real_db, t, [{"product_id": ok["id"], "quantity": 1}, {"product_id": scarce["id"], "quantity": 5},
                              {"product_id": str(uuid.uuid4()), "quantity": 1}], skip_invalid_items=True)
    assert len(sale["items"]) == 1 and sale["amount"] == 10.0
    assert sorted(s["error_number"] for s in sale["skipped_items"]) == [50001, 50002]
    assert _stock(real_db, t, ok["id"]) == 4 and _stock(real_db, t, scarce["id"]) == 1
    assert _balance(real_db, t) == 10.0


def test_procedure_commits_when_it_owns_the_transaction_but_not_when_nested(real_db, tenants):
    """EXEC with no open transaction => the procedure commits (durable even after db.rollback()).
    EXEC inside the caller's transaction => the caller decides (db.rollback() undoes the sale)."""
    from core.clients import get_db_connection
    from repository import sales_repository

    t = tenants()
    p = _product(real_db, t, "A")
    items = [{"product_id": p["id"], "quantity": 1}]
    kw = dict(org_id=t.org_id, created_by=t.user_id, customer_id=None, customer_name=None, category="c", description=None,
              amount=None, items=items, skip_invalid_items=False)

    own = get_db_connection()
    try:
        out = sales_repository.record_sale(own, **kw)  # first statement of the connection => @@TRANCOUNT = 0 => own
        assert out["status"] == "committed"
        own.rollback()  # too late: already committed by the procedure
    finally:
        own.close()
    assert _stock(real_db, t, p["id"]) == 4

    nested = get_db_connection()
    try:
        nested.query("SELECT 1 AS x FROM orgs WHERE id = ?", (t.org_id,))  # opens the implicit transaction
        out = sales_repository.record_sale(nested, **kw)
        assert out["status"] == "committed"
        nested.rollback()  # caller rolls back => the sale disappears
    finally:
        nested.close()
    assert _stock(real_db, t, p["id"]) == 4 and _count(real_db, "sales", t) == 1


def test_nested_business_failure_keeps_callers_earlier_work(real_db, tenants):
    from repository import sales_repository

    t = tenants()
    p = _product(real_db, t, "A", stock=1)
    real_db.query("SELECT 1 AS x FROM orgs WHERE id = ?", (t.org_id,))
    out = sales_repository.record_sale(real_db, org_id=t.org_id, created_by=t.user_id, customer_id=None, customer_name=None,
                                       category="c", description=None, amount=None,
                                       items=[{"product_id": p["id"], "quantity": 2}], skip_invalid_items=False)
    assert out["status"] == "rolled_back" and out["error_number"] == 50001 and "Mug" in out["message"]
    # connection still usable and its transaction still open (rolled back to the savepoint only)
    assert real_db.query_one("SELECT @@TRANCOUNT AS n")["n"] >= 1
    real_db.rollback()
    assert _count(real_db, "sales", t) == 0


def test_race_n_threads_buy_the_last_unit(real_db, tenants):
    from core.clients import get_db_connection
    from services import sales_service

    n = 10
    t = tenants()
    p = _product(real_db, t, "LAST", stock=1)
    outcomes: list[object] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker():
        db = get_db_connection()
        try:
            barrier.wait(timeout=30)
            try:
                sale = sales_service.create_sale(db, org_id=t.org_id, user_id=t.user_id, category="r",
                                                 items=[{"product_id": p["id"], "quantity": 1}])
                db.commit()
                res: object = sale["amount"]
            except sales_service.InsufficientStockError:
                db.rollback()
                res = "sold-out"
            with lock:
                outcomes.append(res)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    assert not errors, errors
    sold = [o for o in outcomes if o != "sold-out"]
    assert len(sold) == 1 and outcomes.count("sold-out") == n - 1
    assert _stock(real_db, t, p["id"]) == 0
    assert _balance(real_db, t) == sum(sold) == 10.0
    assert _count(real_db, "sales", t) == 1


def test_race_many_sales_keep_balance_equal_to_ledger(real_db, tenants):
    from core.clients import get_db_connection
    from services import sales_service

    n, t = 8, tenants()
    p = _product(real_db, t, "BULK", stock=5)  # 8 buyers, 5 units: exactly 5 succeed
    done: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker():
        db = get_db_connection()
        try:
            barrier.wait(timeout=30)
            try:
                sales_service.create_sale(db, org_id=t.org_id, user_id=t.user_id, category="r", items=[{"product_id": p["id"], "quantity": 1}])
                db.commit()
                ok = True
            except sales_service.InsufficientStockError:
                db.rollback()
                ok = False
            with lock:
                done.append(ok)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    assert sum(done) == 5 and len(done) == n
    assert _stock(real_db, t, p["id"]) == 0
    real_db.commit()
    ledger_sum = real_db.query_one("SELECT SUM(amount) AS s FROM cash_ledger WHERE org_id = ?", (t.org_id,))["s"]
    assert _balance(real_db, t) == ledger_sum == 50.0


def test_void_restores_stock_and_balance_and_is_scoped(real_db, tenants):
    from services import sales_service

    a, b = tenants(), tenants()
    p = _product(real_db, a, "P")
    sale = _sell(real_db, a, [{"product_id": p["id"], "quantity": 3}])
    with pytest.raises(sales_service.NotFoundError):
        sales_service.delete_sale(real_db, org_id=b.org_id, sale_id=sale["id"])
    real_db.commit()
    assert _stock(real_db, a, p["id"]) == 2 and _balance(real_db, a) == 30.0
    sales_service.delete_sale(real_db, org_id=a.org_id, sale_id=sale["id"], user_id=a.user_id)
    real_db.commit()
    assert _stock(real_db, a, p["id"]) == 5 and _balance(real_db, a) == 0.0
    assert _count(real_db, "sale_items", a) == 0 and _count(real_db, "sales", a) == 0
    types = [r["entry_type"] for r in real_db.query("SELECT entry_type FROM cash_ledger WHERE org_id = ? ORDER BY created_at", (a.org_id,))]
    assert sorted(types) == ["sale", "sale_void"]
    with pytest.raises(sales_service.NotFoundError):
        sales_service.delete_sale(real_db, org_id=a.org_id, sale_id=sale["id"])


def test_plain_sale_posts_cash_and_foreign_product_is_404(real_db, tenants):
    from services import sales_service

    a, b = tenants(), tenants()
    sale = sales_service.create_sale(real_db, org_id=a.org_id, user_id=a.user_id, amount=19.99, category="retail")
    real_db.commit()
    assert sale["items"] == [] and _balance(real_db, a) == 19.99
    foreign = _product(real_db, b, "F")
    with pytest.raises(sales_service.NotFoundError):
        _sell(real_db, a, [{"product_id": foreign["id"], "quantity": 1}])
    real_db.rollback()
    assert _stock(real_db, b, foreign["id"]) == 5


def test_table_constraints_protect_the_data_even_without_the_procedure(real_db, tenants):
    t, other = tenants(), tenants()
    mine, theirs = _product(real_db, t, "A"), _product(real_db, other, "B")
    sale = _sell(real_db, t, [{"product_id": mine["id"], "quantity": 1}])
    ins = "INSERT INTO sale_items (org_id, sale_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?, ?)"
    for params in (
        (t.org_id, sale["id"], mine["id"], 0, 1),            # CK quantity > 0
        (t.org_id, sale["id"], mine["id"], 1, -1),           # CK unit_price >= 0
        (t.org_id, sale["id"], theirs["id"], 1, 1),          # composite FK: other org's product
        (other.org_id, sale["id"], theirs["id"], 1, 1),      # composite FK: sale belongs to another org
    ):
        with pytest.raises(Exception):
            real_db.execute(ins, params)
        real_db.rollback()
    with pytest.raises(Exception):  # CK_cash_ledger_entry_type
        real_db.execute("INSERT INTO cash_ledger (org_id, entry_type, amount, balance_after) VALUES (?, N'bogus', 1, 1)", (t.org_id,))
    real_db.rollback()
