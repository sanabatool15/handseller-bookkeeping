"""Real SQL Server tests (slice F4: usp_RecordExpense / usp_VoidExpense / usp_AdjustEntryAmount, ledger filters, summary).
Run with: RUN_MSSQL=1 pytest tests/sqlserver/test_expenses_cash_sqlserver.py -v

Needs sql_server/01..06 applied and MSSQL_* env / .env pointing at HandsellerDB.
Every test creates its own orgs/users (unique names) and removes them again.
"""
from __future__ import annotations

import datetime as dt
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
        out = auth_service.register(db, email=self.email, password="pw12345678", full_name="T", org_name="mssql-test-expenses-cash")
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
        for table in ("sale_items", "sales", "expenses", "cash_ledger", "cash_accounts", "products"):
            real_db.execute(f"DELETE FROM {table} WHERE org_id = ?", (t.org_id,))  # test-only literal table names
        real_db.execute("UPDATE orgs SET owner_id = NULL WHERE id = ?", (t.org_id,))
        real_db.execute("DELETE FROM users WHERE org_id = ?", (t.org_id,))
        real_db.execute("DELETE FROM orgs WHERE id = ?", (t.org_id,))
    real_db.commit()


def _balance(db, t):
    from repository import cash_repository

    db.commit()  # fresh snapshot of committed data
    return cash_repository.get_balance(db, org_id=t.org_id)["balance"]


def _ledger_sum(db, t):
    db.commit()
    return db.query_one("SELECT COALESCE(SUM(amount), 0) AS s FROM cash_ledger WHERE org_id = ?", (t.org_id,))["s"]


def _count(db, table, t):
    db.commit()
    return db.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE org_id = ?", (t.org_id,))["n"]  # test-only literal table names


def _types(db, t):
    db.commit()
    return [r["entry_type"] for r in db.query("SELECT entry_type FROM cash_ledger WHERE org_id = ? ORDER BY created_at, id", (t.org_id,))]


def _expense(db, t, amount=30.0, **kw):
    from services import expenses_service

    exp = expenses_service.create_expense(db, org_id=t.org_id, user_id=t.user_id, amount=amount, category=kw.pop("category", "rent"), **kw)
    db.commit()
    return exp


def _sale(db, t, amount=100.0):
    from services import sales_service

    sale = sales_service.create_sale(db, org_id=t.org_id, user_id=t.user_id, amount=amount, category="retail")
    db.commit()
    return sale


def test_expense_reduces_balance_and_writes_negative_ledger_row_even_below_zero(real_db, tenants):
    t = tenants()
    exp = _expense(real_db, t, 25.5)  # no cash yet: the balance goes negative, which is allowed
    assert _balance(real_db, t) == -25.5
    row = real_db.query_one("SELECT entry_type, amount, balance_after, ref_type, ref_id FROM cash_ledger WHERE org_id = ?", (t.org_id,))
    assert row["entry_type"] == "expense" and row["amount"] == -25.5 and row["balance_after"] == -25.5
    assert row["ref_type"] == "expense" and row["ref_id"] == exp["id"]
    _sale(real_db, t, 100)
    _expense(real_db, t, 4.5)
    assert _balance(real_db, t) == 70.0 == _ledger_sum(real_db, t)


def test_engine_error_after_the_balance_update_rolls_the_whole_expense_back(real_db, tenants):
    """The cash UPDATE overflows decimal(16,2) (error 8115) AFTER the expense row was inserted: nothing may survive."""
    from repository.base import ProcedureError
    from services import expenses_service

    t = tenants()
    _sale(real_db, t, 1)
    real_db.execute("UPDATE cash_accounts SET balance = -99999999999999.00 WHERE org_id = ?", (t.org_id,))
    real_db.commit()
    with pytest.raises(ProcedureError):
        expenses_service.create_expense(real_db, org_id=t.org_id, user_id=t.user_id, amount=999999999999.99, category="x")
    real_db.rollback()
    assert _count(real_db, "expenses", t) == 0 and _count(real_db, "cash_ledger", t) == 1  # only the earlier sale entry
    assert _balance(real_db, t) == -99999999999999.00


def test_business_validation_in_the_procedure_changes_nothing(real_db, tenants):
    from repository import expenses_repository

    t = tenants()
    out = expenses_repository.record_expense(real_db, org_id=t.org_id, created_by=t.user_id, amount=0, category="c",
                                             voucher_reference=None, description=None)
    assert out["status"] == "rolled_back" and out["error_number"] == 50003 and out["expense"] is None
    out = expenses_repository.record_expense(real_db, org_id=str(uuid.uuid4()), created_by=t.user_id, amount=5, category="c",
                                             voucher_reference=None, description=None)
    assert out["status"] == "rolled_back" and out["error_number"] == 50005
    real_db.rollback()
    assert _count(real_db, "expenses", t) == 0 and _count(real_db, "cash_ledger", t) == 0


def test_void_is_symmetric_and_scoped(real_db, tenants):
    from services import expenses_service

    a, b = tenants(), tenants()
    _sale(real_db, a, 100)
    exp = _expense(real_db, a, 30)
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.delete_expense(real_db, org_id=b.org_id, expense_id=exp["id"])
    real_db.commit()
    assert _balance(real_db, a) == 70.0
    expenses_service.delete_expense(real_db, org_id=a.org_id, expense_id=exp["id"], user_id=a.user_id)
    real_db.commit()
    assert _balance(real_db, a) == 100.0 == _ledger_sum(real_db, a) and _count(real_db, "expenses", a) == 0
    assert _types(real_db, a) == ["sale", "expense", "expense_void"]
    with pytest.raises(expenses_service.NotFoundError):
        expenses_service.delete_expense(real_db, org_id=a.org_id, expense_id=exp["id"])


def test_adjustment_posts_the_delta_for_sales_and_expenses(real_db, tenants):
    from services import expenses_service, sales_service

    t = tenants()
    sale, exp = _sale(real_db, t, 50), _expense(real_db, t, 20)
    assert _balance(real_db, t) == 30.0
    out = sales_service.update_sale(real_db, org_id=t.org_id, sale_id=sale["id"], updates={"amount": 80, "description": "d"}, user_id=t.user_id)
    assert out["amount"] == 80.0 and out["description"] == "d"
    expenses_service.update_expense(real_db, org_id=t.org_id, expense_id=exp["id"], updates={"amount": 25}, user_id=t.user_id)
    real_db.commit()
    assert _balance(real_db, t) == 55.0 == _ledger_sum(real_db, t)  # +30 (sale), -5 (expense)
    adj = real_db.query("SELECT ref_type, amount, balance_after FROM cash_ledger WHERE org_id = ? AND entry_type = N'adjustment' ORDER BY created_at", (t.org_id,))
    assert [(a["ref_type"], a["amount"]) for a in adj] == [("sale", 30.0), ("expense", -5.0)]
    assert adj[-1]["balance_after"] == 55.0
    sales_service.update_sale(real_db, org_id=t.org_id, sale_id=sale["id"], updates={"amount": 80})  # unchanged => no entry
    real_db.commit()
    assert _count(real_db, "cash_ledger", t) == 4
    # voiding after an edit reverses the sale AND its adjustment, so nothing drifts
    sales_service.delete_sale(real_db, org_id=t.org_id, sale_id=sale["id"])
    real_db.commit()
    assert _balance(real_db, t) == -25.0 == _ledger_sum(real_db, t)


def test_item_sale_amount_change_is_refused_and_foreign_ids_are_not_found(real_db, tenants):
    from services import products_service, sales_service

    t, other = tenants(), tenants()
    p = products_service.create_product(real_db, org_id=t.org_id, user_id=t.user_id, name="Mug", sku="M", price=10.0, stock_qty=5)
    real_db.commit()
    sale = sales_service.create_sale(real_db, org_id=t.org_id, user_id=t.user_id, items=[{"product_id": p["id"], "quantity": 2}])
    real_db.commit()
    with pytest.raises(sales_service.ValidationError):
        sales_service.update_sale(real_db, org_id=t.org_id, sale_id=sale["id"], updates={"amount": 1})
    real_db.rollback()
    with pytest.raises(sales_service.NotFoundError):
        sales_service.update_sale(real_db, org_id=other.org_id, sale_id=sale["id"], updates={"amount": 1})
    real_db.rollback()
    assert _balance(real_db, t) == 20.0 and _types(real_db, t) == ["sale"]


def test_procedure_commits_when_it_owns_the_transaction_but_not_when_nested(real_db, tenants):
    from core.clients import get_db_connection
    from repository import expenses_repository

    t = tenants()
    kw = dict(org_id=t.org_id, created_by=t.user_id, amount=10, category="c", voucher_reference=None, description=None)
    own = get_db_connection()
    try:
        assert expenses_repository.record_expense(own, **kw)["status"] == "committed"  # first statement => @@TRANCOUNT = 0 => own
        own.rollback()  # too late: already committed by the procedure
    finally:
        own.close()
    assert _balance(real_db, t) == -10.0
    nested = get_db_connection()
    try:
        nested.query("SELECT 1 AS x FROM orgs WHERE id = ?", (t.org_id,))  # opens the implicit transaction
        assert expenses_repository.record_expense(nested, **kw)["status"] == "committed"
        nested.rollback()  # the caller decides
    finally:
        nested.close()
    assert _balance(real_db, t) == -10.0 and _count(real_db, "expenses", t) == 1


def test_concurrent_expenses_keep_balance_equal_to_ledger_sum(real_db, tenants):
    from core.clients import get_db_connection
    from services import expenses_service

    n, t = 10, tenants()
    _sale(real_db, t, 1000)
    barrier, errors = threading.Barrier(n), []
    lock = threading.Lock()

    def worker(i):
        db = get_db_connection()
        try:
            barrier.wait(timeout=30)
            expenses_service.create_expense(db, org_id=t.org_id, user_id=t.user_id, amount=10 + i, category="r")
            db.commit()
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    assert not errors, errors
    total = sum(10 + i for i in range(n))
    assert _count(real_db, "expenses", t) == n
    assert _balance(real_db, t) == 1000 - total == _ledger_sum(real_db, t)
    # every ledger row saw a distinct running balance (the hot-row update serialised the writers)
    balances = [r["balance_after"] for r in real_db.query("SELECT balance_after FROM cash_ledger WHERE org_id = ? AND entry_type = N'expense'", (t.org_id,))]
    assert len(set(balances)) == n


def test_concurrent_adjustments_of_one_expense_serialise(real_db, tenants):
    from core.clients import get_db_connection
    from services import expenses_service

    n, t = 6, tenants()
    exp = _expense(real_db, t, 10)
    barrier, errors = threading.Barrier(n), []
    lock = threading.Lock()

    def worker(i):
        db = get_db_connection()
        try:
            barrier.wait(timeout=30)
            expenses_service.update_expense(db, org_id=t.org_id, expense_id=exp["id"], updates={"amount": 20 + i}, user_id=t.user_id)
            db.commit()
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    assert not errors, errors
    real_db.commit()
    final = expenses_service.get_expense(real_db, org_id=t.org_id, expense_id=exp["id"])["amount"]
    assert _balance(real_db, t) == -final == _ledger_sum(real_db, t)  # deltas were computed from committed values


def test_ledger_filters_and_month_summary_against_real_data(real_db, tenants):
    from services import cash_service

    t = tenants()
    _sale(real_db, t, 100)
    _expense(real_db, t, 30)
    today = dt.datetime.now(dt.timezone.utc).date()
    assert [e["entry_type"] for e in cash_service.list_ledger(real_db, org_id=t.org_id, entry_type="expense")] == ["expense"]
    assert len(cash_service.list_ledger(real_db, org_id=t.org_id, date_from=today, date_to=today)) == 2
    assert cash_service.list_ledger(real_db, org_id=t.org_id, date_from=today + dt.timedelta(days=1)) == []
    with pytest.raises(cash_service.ValidationError):  # unknown types never reach SQL (and would be a bound parameter anyway)
        cash_service.list_ledger(real_db, org_id=t.org_id, entry_type="sale'; DROP TABLE cash_ledger;--")
    s = cash_service.get_summary(real_db, org_id=t.org_id, year=today.year, month=today.month)
    assert s["total_in"] == 100.0 and s["total_out"] == 30.0 and s["closing_balance"] == 70.0 and s["opening_balance"] == 0.0
    assert s["by_type"]["sale"] == 100.0 and s["by_type"]["expense"] == -30.0
    nxt = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    quiet = cash_service.get_summary(real_db, org_id=t.org_id, year=nxt.year, month=nxt.month)
    assert quiet["opening_balance"] == quiet["closing_balance"] == 70.0 and quiet["total_in"] == quiet["total_out"] == 0.0


def test_deleting_a_product_with_sales_maps_the_fk_error_to_409(real_db, tenants):
    """Verifies on a real server that error 547 (REFERENCE constraint) is recognised by core.db and mapped by the service."""
    from services import products_service, sales_service

    t = tenants()
    p = products_service.create_product(real_db, org_id=t.org_id, user_id=t.user_id, name="Mug", sku="M", price=10.0, stock_qty=5)
    real_db.commit()
    sales_service.create_sale(real_db, org_id=t.org_id, user_id=t.user_id, items=[{"product_id": p["id"], "quantity": 1}])
    real_db.commit()
    with pytest.raises(products_service.ProductInUseError, match="deactivate it instead"):
        products_service.delete_product(real_db, org_id=t.org_id, product_id=p["id"])
    real_db.rollback()
    assert products_service.get_product(real_db, org_id=t.org_id, product_id=p["id"])["stock_qty"] == 4


def test_ledger_check_constraint_allows_expense_void_but_not_bogus(real_db, tenants):
    t = tenants()
    ok = "INSERT INTO cash_ledger (org_id, entry_type, amount, balance_after) VALUES (?, ?, 1, 1)"
    real_db.execute(ok, (t.org_id, "expense_void"))
    real_db.commit()
    with pytest.raises(Exception):
        real_db.execute(ok, (t.org_id, "bogus"))
    real_db.rollback()
