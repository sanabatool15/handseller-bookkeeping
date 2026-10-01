"""The REAL repositories against a recording Db (no SQL Server): checks the statements/params
they send. T-SQL itself is not executed here; tests/sqlserver/ does that (RUN_MSSQL=1)."""
from __future__ import annotations

import datetime as dt
import decimal
import json

import pytest

from repository import agent_jobs_repository as jobs_repo
from repository import customers_repository as cust_repo
from repository import expenses_repository as exp_repo
from repository import products_repository as prod_repo
from repository import sales_repository as sales_repo
from repository import txn_log_repository as log_repo
from repository import db_lab_repository as lab_repo


@pytest.fixture(autouse=True)
def _real_repos(monkeypatch):
    monkeypatch.undo()  # drop the in-memory fakes installed by tests/conftest.py


class RecDb:
    def __init__(self, rows=None, rowcount=1):
        self.rows, self.rowcount, self.calls = rows or [], rowcount, []

    def query(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return list(self.rows)

    def query_one(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return self.rows[0] if self.rows else None

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return self.rowcount


class ProcDb(RecDb):
    """Returns the OUTPUT row of the EXEC batch first, then whatever `rows` says for the read-backs."""

    def __init__(self, proc_row, rows=None):
        super().__init__(rows)
        self.proc_row, self.rollbacks = proc_row, 0

    def query_one(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        if "usp_" in sql:
            return self.proc_row
        return self.rows[0] if self.rows else None

    def rollback(self):
        self.rollbacks += 1


def _proc_row(**kw):
    base = {"sale_id": "s1", "total": 5, "status": "committed", "message": "ok", "error_number": None, "skipped_items": None}
    return {**base, **kw}


def test_record_sale_execs_procedure_with_json_items_and_reads_back_scoped():
    db = ProcDb(_proc_row(), [{"id": "s1", "org_id": "o1"}])
    out = sales_repo.record_sale(db, org_id="o1", created_by="u1", customer_id=None, customer_name="n", category="c",
                                description=None, amount=None, items=[{"product_id": "p1", "quantity": 2}], skip_invalid_items=False)
    sql, p = db.calls[0]
    assert "EXEC dbo.usp_RecordSale" in sql and "@sale_id = @sale_id OUTPUT" in sql and sql.count("?") == len(p) == 9
    assert p[0] == "o1" and p[6] is None and json.loads(p[7]) == [{"product_id": "p1", "quantity": 2}] and p[8] == 0
    assert out["status"] == "committed" and out["sale"]["id"] == "s1" and isinstance(out["sale"]["items"], list)
    assert db.calls[1][1] == ("s1", "o1")  # read-back scoped by id AND org_id


def test_record_sale_quick_sale_sends_decimal_amount_and_no_items():
    db = ProcDb(_proc_row(), [{"id": "s1"}])
    sales_repo.record_sale(db, org_id="o1", created_by="u1", customer_id="c1", customer_name=None, category="c",
                           description="d", amount=12.34, items=None, skip_invalid_items=True)
    p = db.calls[0][1]
    assert p[2] == "c1" and p[6] == decimal.Decimal("12.34") and p[7] is None and p[8] == 1


def test_record_sale_business_rollback_returns_outcome_without_sale():
    db = ProcDb(_proc_row(status="rolled_back", error_number=50001, message="Not enough stock for Mug", sale_id=None))
    out = sales_repo.record_sale(db, org_id="o1", created_by="u1", customer_id=None, customer_name=None, category="c",
                                description=None, amount=None, items=[{"product_id": "p", "quantity": 1}], skip_invalid_items=False)
    assert out["status"] == "rolled_back" and out["error_number"] == 50001 and out["sale"] is None and len(db.calls) == 1


def test_record_sale_partial_parses_skipped_json():
    skipped = json.dumps([{"product_id": "p2", "quantity": 9, "error_number": 50001, "reason": "Not enough stock for X"}])
    db = ProcDb(_proc_row(status="partial", skipped_items=skipped), [{"id": "s1"}])
    out = sales_repo.record_sale(db, org_id="o1", created_by="u1", customer_id=None, customer_name=None, category="c",
                                description=None, amount=None, items=[{"product_id": "p", "quantity": 1}], skip_invalid_items=True)
    assert out["status"] == "partial" and out["skipped_items"][0]["reason"] == "Not enough stock for X"


def test_record_sale_engine_error_rolls_back_and_raises_with_number_for_deadlock_detection():
    from core.db import is_deadlock

    db = ProcDb(_proc_row(status="rolled_back", error_number=1205, message="deadlock victim", sale_id=None))
    with pytest.raises(sales_repo.ProcedureError) as exc:
        sales_repo.record_sale(db, org_id="o1", created_by="u1", customer_id=None, customer_name=None, category="c",
                               description=None, amount=5, items=None, skip_invalid_items=False)
    assert db.rollbacks == 1 and is_deadlock(exc.value)


def test_void_sale_execs_procedure_scoped_and_maps_status():
    db = ProcDb({"status": "voided", "message": "m", "error_number": None})
    assert sales_repo.void_sale(db, org_id="o1", sale_id="s1", voided_by="u1") == {"status": "voided", "message": "m"}
    sql, p = db.calls[0]
    assert "EXEC dbo.usp_VoidSale" in sql and p == ("o1", "s1", "u1")
    nf = ProcDb({"status": "not_found", "message": "Sale not found", "error_number": 50006})
    assert sales_repo.void_sale(nf, org_id="o2", sale_id="s1", voided_by=None)["status"] == "not_found"
    bad = ProcDb({"status": "rolled_back", "message": "x", "error_number": 1205})
    with pytest.raises(sales_repo.ProcedureError):
        sales_repo.void_sale(bad, org_id="o1", sale_id="s1", voided_by=None)
    assert bad.rollbacks == 1


def test_scoped_statements_send_id_then_org_id():
    db = RecDb([{"id": "s1"}])
    sales_repo.get_sale_scoped(db, sale_id="s1", org_id="o1")
    assert db.calls[0][1] == ("s1", "o1") and db.calls[1][1] == ("s1", "o1")  # sale, then its items
    assert "si.sale_id = ? AND si.org_id = ?" in db.calls[1][0]
    db = RecDb([{"id": "s1"}])
    sales_repo.update_sale_scoped(db, sale_id="s1", org_id="o1", updates={"category": "c"})
    sql, p = db.calls[0]
    assert p == ("c", None, None, 0, None, "s1", "o1") and "WHERE id = ? AND org_id = ?" in sql
    assert "amount" not in sql[sql.index("UPDATE "):].split("OUTPUT")[0]  # amount is never written here (ledger!)
    with pytest.raises(ValueError):
        sales_repo.update_sale_scoped(RecDb(), sale_id="s1", org_id="o1", updates={"amount": 5.0})


def test_list_sales_attaches_items_with_one_scoped_json_query():
    class TwoDb(RecDb):
        def query(self, sql, params=()):
            self.calls.append((sql, tuple(params)))
            if "FROM sale_items" in sql:
                return [{"sale_id": "s2", "product_id": "p"}]
            return [{"id": "s1"}, {"id": "s2"}]

    db = TwoDb()
    out = sales_repo.list_sales(db, org_id="o1", limit=5, offset=0)
    assert out[0]["items"] == [] and out[1]["items"] == [{"sale_id": "s2", "product_id": "p"}]
    sql, p = db.calls[1]
    assert "OPENJSON(?)" in sql and "si.org_id = ?" in sql and p[0] == "o1" and json.loads(p[1]) == ["s1", "s2"]



def test_update_rejects_unknown_columns_without_touching_db():
    db = RecDb()
    with pytest.raises(ValueError):
        exp_repo.update_expense_scoped(db, expense_id="e", org_id="o", updates={"org_id": "other"})
    assert db.calls == []


def test_expense_update_maps_voucher_reference():
    db = RecDb([{"id": "e"}])
    exp_repo.update_expense_scoped(db, expense_id="e", org_id="o", updates={"voucher_reference": "V-9"})
    assert db.calls[0][1] == (None, "V-9", None, "e", "o")
    with pytest.raises(ValueError):  # amount only via usp_AdjustEntryAmount
        exp_repo.update_expense_scoped(RecDb(), expense_id="e", org_id="o", updates={"amount": 1.0})


def test_month_sum_is_computed_in_sql_with_half_open_date_range():
    db = RecDb([{"total": 150.5}])
    assert sales_repo.sum_sales_for_month(db, org_id="o1", year=2026, month=12) == 150.5
    sql, p = db.calls[0]
    assert "SUM(amount)" in sql and "sale_date >= ? AND sale_date < ?" in sql
    assert p == ("o1", dt.date(2026, 12, 1), dt.date(2027, 1, 1))  # December rolls into next year


def test_category_breakdown_is_group_by_in_sql():
    db = RecDb([{"category": "rent", "total": 50.0}, {"category": "packaging", "total": 25.0}])
    assert exp_repo.sum_expenses_by_category_for_month(db, org_id="o1", year=2026, month=2) == {"rent": 50.0, "packaging": 25.0}
    sql, p = db.calls[0]
    assert "GROUP BY category" in sql and p == ("o1", dt.date(2026, 2, 1), dt.date(2026, 3, 1))


def test_paging_uses_offset_fetch_and_clamps():
    db = RecDb()
    sales_repo.list_sales(db, org_id="o1", limit=0, offset=-5)
    sql, p = db.calls[0]
    assert "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in sql and p == ("o1", 0, 1)
    sales_repo.list_sales(db, org_id="o1", limit=25, offset=50)
    assert db.calls[1][1] == ("o1", 50, 25)


def test_job_json_is_serialised_on_write_and_parsed_on_read():
    stored = {"id": "j1", "input_payload": '{"question": "q"}', "result": None, "error_details": '{"m": 1}', "status": "pending"}
    db = RecDb([stored])
    job = jobs_repo.create_job(db, job_name="n", org_id="o1", requested_by="u1", input_payload={"question": "q"})
    assert json.loads(db.calls[0][1][3]) == {"question": "q"}
    assert job["input_payload"] == {"question": "q"} and job["result"] is None and job["error_details"] == {"m": 1}


def test_add_log_is_scoped_through_the_owning_job():
    db = RecDb([{"id": "l1", "insights_generated": '{"a": 1}'}])
    log = jobs_repo.add_log(db, job_id="j1", org_id="o1", step_name="s", action_summary="x", insights_generated={"a": 1})
    sql, p = db.calls[0]
    assert "FROM agent_jobs WHERE id = ? AND org_id = ?" in sql and p[-2:] == ("j1", "o1")
    assert log["insights_generated"] == {"a": 1}
    with pytest.raises(RuntimeError):
        jobs_repo.add_log(RecDb([]), job_id="j1", org_id="o2", step_name="s", action_summary="x")


def test_update_job_status_params():
    db = RecDb([{"id": "j1", "result": '{"r": 1}'}])
    jobs_repo.update_job_status(db, job_id="j1", org_id="o1", status="completed", current_step="finalize", result={"r": 1})
    p = db.calls[0][1]
    assert p[0] == "completed" and p[1] == "finalize" and json.loads(p[2]) == {"r": 1} and p[3] is None and p[-2:] == ("j1", "o1")


def test_create_product_params_and_output_into():
    db = RecDb([{"id": "p1"}])
    prod_repo.create_product(db, org_id="o1", created_by="u1", name="Mug", sku="S", price=9.99, stock_qty=3, reorder_level=1)
    sql, p = db.calls[0]
    assert "OUTPUT" in sql and "INTO @o" in sql and "SELECT * FROM @o" in sql
    assert p == ("o1", "u1", "Mug", "S", decimal.Decimal("9.99"), 3, 1)


def test_product_scoped_statements_send_id_then_org_id():
    db = RecDb([{"id": "p1"}])
    prod_repo.get_product_scoped(db, product_id="p1", org_id="o1")
    assert db.calls[-1][1] == ("p1", "o1")
    prod_repo.update_product_scoped(db, product_id="p1", org_id="o1", updates={"price": 5.0, "is_active": False})
    sql, p = db.calls[-1]
    assert "WHERE id = ? AND org_id = ?" in sql and "SET name = COALESCE" in sql and "stock_qty = " not in sql
    assert p == (None, None, decimal.Decimal("5.0"), None, 0, "p1", "o1")
    assert prod_repo.delete_product_scoped(db, product_id="p1", org_id="o1") is True
    assert prod_repo.delete_product_scoped(RecDb(rowcount=0), product_id="p1", org_id="o2") is False
    with pytest.raises(ValueError):
        prod_repo.update_product_scoped(RecDb(), product_id="p", org_id="o", updates={"stock_qty": 99})


def test_adjust_stock_is_single_guarded_statement():
    db = RecDb([{"id": "p1", "stock_qty": 4}])
    assert prod_repo.adjust_stock_scoped(db, product_id="p1", org_id="o1", delta=-3)["stock_qty"] == 4
    assert len(db.calls) == 1  # exactly one round trip, no read-then-write
    sql, p = db.calls[0]
    assert "stock_qty = stock_qty + ?" in sql and "WHERE id = ? AND org_id = ? AND stock_qty + ? >= 0" in sql
    assert "INTO @o" in sql and p == (-3, "p1", "o1", -3)
    assert prod_repo.adjust_stock_scoped(RecDb([]), product_id="p1", org_id="o1", delta=-99) is None


def test_product_listing_low_stock_variant_and_paging():
    db = RecDb()
    prod_repo.list_products(db, org_id="o1", limit=0, offset=-1)
    assert "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in db.calls[0][0] and "stock_qty <= reorder_level" not in db.calls[0][0]
    assert db.calls[0][1] == ("o1", 0, 1)
    prod_repo.list_products(db, org_id="o1", limit=10, offset=20, low_stock=True)
    assert "stock_qty <= reorder_level" in db.calls[1][0] and db.calls[1][1] == ("o1", 20, 10)


def test_sale_update_carries_customer_id_flag():
    db = RecDb([{"id": "s1"}])
    sales_repo.update_sale_scoped(db, sale_id="s1", org_id="o1", updates={"category": "x"})
    assert db.calls[0][1][3:5] == (0, None) and db.calls[0][1][-2:] == ("s1", "o1")  # flag 0 = leave customer_id alone
    sales_repo.update_sale_scoped(db, sale_id="s1", org_id="o1", updates={"customer_id": None})
    assert db.calls[2][1][3:5] == (1, None)  # present null = unlink
    sales_repo.update_sale_scoped(db, sale_id="s1", org_id="o1", updates={"customer_id": "c9"})
    assert db.calls[4][1][3:5] == (1, "c9")


def test_cash_repository_statements_are_org_scoped():
    from repository import cash_repository as cash_repo

    db = RecDb([{"balance": decimal.Decimal("12.50"), "updated_at": "t"}])
    assert cash_repo.get_balance(db, org_id="o1") == {"balance": 12.5, "updated_at": "t"}
    assert db.calls[0][1] == ("o1",) and "WHERE org_id = ?" in db.calls[0][0]
    assert cash_repo.get_balance(RecDb(), org_id="o1") == {"balance": 0.0, "updated_at": None}
    cash_repo.list_ledger(db, org_id="o1", limit=10, offset=20)
    assert db.calls[1][1] == ("o1", None, None, None, None, None, None, 20, 10) and "FROM cash_ledger WHERE org_id = ?" in db.calls[1][0]


def test_create_customer_params_and_output_into():
    db = RecDb([{"id": "c1"}])
    cust_repo.create_customer(db, org_id="o1", created_by="u1", name="Ana", phone="1", email=None, address=None, notes="n")
    sql, p = db.calls[0]
    assert "OUTPUT" in sql and "INTO @o" in sql and "SELECT * FROM @o" in sql
    assert p == ("o1", "u1", "Ana", "1", None, None, "n")


def test_customer_scoped_statements_and_update_flags():
    db = RecDb([{"id": "c1"}])
    cust_repo.get_customer_scoped(db, customer_id="c1", org_id="o1")
    assert db.calls[-1][1] == ("c1", "o1")
    cust_repo.update_customer_scoped(db, customer_id="c1", org_id="o1", updates={"phone": None, "notes": "x"})
    sql, p = db.calls[-1]
    assert "WHERE id = ? AND org_id = ?" in sql
    assert p == (None, 1, None, 0, None, 0, None, 1, "x", "c1", "o1")  # name, (flag,val) x phone/email/address/notes, id, org
    with pytest.raises(ValueError):
        cust_repo.update_customer_scoped(RecDb(), customer_id="c", org_id="o", updates={"org_id": "x"})


def test_customer_delete_passes_org_twice_and_reports_rowcount():
    db = RecDb(rowcount=1)
    assert cust_repo.delete_customer_scoped(db, customer_id="c1", org_id="o1") is True
    assert db.calls[0][1] == ("c1", "o1", "o1")
    assert cust_repo.delete_customer_scoped(RecDb(rowcount=0), customer_id="c1", org_id="o2") is False


def test_customer_search_escapes_like_wildcards():
    db = RecDb()
    cust_repo.list_customers(db, org_id="o1", q="50%_[x]\\", limit=0, offset=-1)
    sql, p = db.calls[0]
    assert "LIKE ? ESCAPE" in sql and p == ("o1", "50\\%\\_\\[x]\\\\%", "50\\%\\_\\[x]\\\\%", 0, 1)
    cust_repo.list_customers(db, org_id="o1")
    assert "LIKE" not in db.calls[1][0] and db.calls[1][1] == ("o1", 0, 100)
    assert cust_repo._like_prefix("a") == "a%"


def test_customer_summary_row_is_split_and_scoped_twice():
    row = {"id": "c1", "org_id": "o1", "name": "Ana", "total_sales": 15.5, "sale_count": 2, "last_sale_date": "2026-01-02"}
    db = RecDb([row])
    out = cust_repo.get_customer_summary_scoped(db, customer_id="c1", org_id="o1")
    assert out == {"customer": {"id": "c1", "org_id": "o1", "name": "Ana"}, "total_sales": 15.5, "sale_count": 2, "last_sale_date": "2026-01-02"}
    assert db.calls[0][1] == ("o1", "c1", "o1")
    assert cust_repo.get_customer_summary_scoped(RecDb([]), customer_id="c1", org_id="o2") is None


def test_ledger_filters_are_bound_parameters_not_sql_text():
    from repository import cash_repository as cash_repo

    db = RecDb()
    evil = "sale'; DROP TABLE cash_ledger;--"
    cash_repo.list_ledger(db, org_id="o1", limit=5, offset=0, entry_type=evil,
                          date_from=dt.date(2026, 1, 1), date_to=dt.date(2026, 1, 31))
    sql, p = db.calls[0]
    assert evil not in sql and "DROP" not in sql
    assert p == ("o1", evil, evil, dt.date(2026, 1, 1), dt.date(2026, 1, 1), dt.date(2026, 1, 31), dt.date(2026, 1, 31), 0, 5)
    assert sql.count("?") == len(p)


def test_month_summary_runs_two_scoped_aggregates_and_derives_totals():
    from repository import cash_repository as cash_repo

    class SumDb(RecDb):
        def query_one(self, sql, params=()):
            self.calls.append((sql, tuple(params)))
            return {"opening": 100.0}

        def query(self, sql, params=()):
            self.calls.append((sql, tuple(params)))
            return [{"entry_type": "sale", "net": 50.0, "total_in": 50.0, "total_out": 0.0},
                    {"entry_type": "expense", "net": -30.0, "total_in": 0.0, "total_out": 30.0}]

    db = SumDb()
    out = cash_repo.get_month_summary(db, org_id="o1", year=2026, month=12)
    assert out == {"opening_balance": 100.0, "total_in": 50.0, "total_out": 30.0, "closing_balance": 120.0,
                   "by_type": {"sale": 50.0, "expense": -30.0}}
    assert "SUM(amount)" in db.calls[0][0] and db.calls[0][1] == ("o1", dt.date(2026, 12, 1))  # opening: before the month
    assert "GROUP BY entry_type" in db.calls[1][0] and db.calls[1][1] == ("o1", dt.date(2026, 12, 1), dt.date(2027, 1, 1))


def test_adjust_entry_amount_execs_procedure_and_maps_statuses():
    from repository import cash_repository as cash_repo

    db = ProcDb({"status": "adjusted", "message": "m", "error_number": None})
    out = cash_repo.adjust_entry_amount(db, org_id="o1", ref_type="expense", ref_id="e1", new_amount=12.345, adjusted_by="u1")
    sql, p = db.calls[0]
    assert "EXEC dbo.usp_AdjustEntryAmount" in sql and p == ("o1", "expense", "e1", decimal.Decimal("12.35"), "u1") or p[3] == decimal.Decimal("12.34")
    assert out["status"] == "adjusted"
    for status, number in (("not_found", 50007), ("not_allowed", 50008), ("rolled_back", 50003)):  # business outcomes are returned
        assert cash_repo.adjust_entry_amount(ProcDb({"status": status, "message": "x", "error_number": number}),
                                             org_id="o", ref_type="sale", ref_id="s", new_amount=1, adjusted_by=None)["status"] == status
    bad = ProcDb({"status": "rolled_back", "message": "deadlock", "error_number": 1205})
    with pytest.raises(sales_repo.ProcedureError):
        cash_repo.adjust_entry_amount(bad, org_id="o", ref_type="sale", ref_id="s", new_amount=1, adjusted_by=None)
    assert bad.rollbacks == 1


def test_record_expense_execs_procedure_and_reads_back_scoped():
    db = ProcDb({"expense_id": "e1", "status": "committed", "message": "ok", "error_number": None}, [{"id": "e1", "org_id": "o1"}])
    out = exp_repo.record_expense(db, org_id="o1", created_by="u1", amount=19.99, category="rent", voucher_reference="V",
                                  description=None, expense_date=dt.date(2026, 3, 1))
    sql, p = db.calls[0]
    assert "EXEC dbo.usp_RecordExpense" in sql and "@expense_id = @expense_id OUTPUT" in sql and sql.count("?") == len(p) == 7
    assert p == ("o1", "u1", decimal.Decimal("19.99"), "rent", "V", None, dt.date(2026, 3, 1))
    assert out["status"] == "committed" and out["expense"]["id"] == "e1" and db.calls[1][1] == ("e1", "o1")
    rej = ProcDb({"expense_id": None, "status": "rolled_back", "message": "amount must be positive", "error_number": 50003})
    assert exp_repo.record_expense(rej, org_id="o1", created_by="u", amount=1, category="c", voucher_reference=None, description=None)["expense"] is None
    eng = ProcDb({"expense_id": None, "status": "rolled_back", "message": "deadlock victim", "error_number": 1205})
    with pytest.raises(sales_repo.ProcedureError):
        exp_repo.record_expense(eng, org_id="o1", created_by="u", amount=1, category="c", voucher_reference=None, description=None)
    assert eng.rollbacks == 1


def test_void_expense_execs_procedure_scoped_and_maps_status():
    db = ProcDb({"status": "voided", "message": "m", "error_number": None})
    assert exp_repo.void_expense(db, org_id="o1", expense_id="e1", voided_by="u1") == {"status": "voided", "message": "m"}
    sql, p = db.calls[0]
    assert "EXEC dbo.usp_VoidExpense" in sql and p == ("o1", "e1", "u1")
    nf = ProcDb({"status": "not_found", "message": "Expense not found", "error_number": 50007})
    assert exp_repo.void_expense(nf, org_id="o2", expense_id="e1", voided_by=None)["status"] == "not_found"


def test_foreign_key_violation_is_mapped_but_check_violation_is_not():
    from core.db import Db, ForeignKeyViolationError, is_foreign_key_violation

    fk = Exception("23000", "[42000] The DELETE statement conflicted with the REFERENCE constraint \"FK_sale_items_product\". (547)")
    chk = Exception("23000", "The UPDATE statement conflicted with the CHECK constraint \"CK_products_stock\". (547)")
    assert is_foreign_key_violation(fk) and not is_foreign_key_violation(chk)

    class Cur:
        def __init__(self, exc):
            self.exc = exc

        def execute(self, *_):
            raise self.exc

        def close(self):
            pass

    class Conn:
        def __init__(self, exc):
            self.exc = exc

        def cursor(self):
            return Cur(self.exc)

    with pytest.raises(ForeignKeyViolationError):
        prod_repo.delete_product_scoped(Db(Conn(fk)), product_id="p1", org_id="o1")
    with pytest.raises(Exception) as e:
        prod_repo.delete_product_scoped(Db(Conn(chk)), product_id="p1", org_id="o1")
    assert not isinstance(e.value, ForeignKeyViolationError)


# ---- F5 ------------------------------------------------------------------------------------------------------------
def test_txn_log_insert_sends_org_id_then_json_events_in_order():
    db = RecDb(rowcount=3)
    events = [{"request_id": "r1", "operation": "record_sale", "step": s, "isolation_level": "READ COMMITTED", "status": "x",
               "error_number": None, "message": "m", "duration_ms": None, "retry_no": 0, "created_at": "2026-01-01T00:00:00.123456"}
              for s in ("txn_started", "lock_wait_suspected", "committed")]
    assert log_repo.insert_events(db, org_id="ORG", events=events) == 3
    sql, params = db.calls[0]
    assert params[0] == "ORG" and len(params) == 2
    sent = json.loads(params[1])
    assert [e["seq"] for e in sent] == [0, 1, 2] and [e["step"] for e in sent] == ["txn_started", "lock_wait_suspected", "committed"]
    assert "?" in sql and "ORG" not in sql
    assert log_repo.insert_events(db, org_id="ORG", events=[]) == 0 and len(db.calls) == 1


def test_txn_log_insert_rejects_unknown_steps_before_sending_anything():
    db = RecDb()
    with pytest.raises(ValueError):
        log_repo.insert_events(db, org_id="ORG", events=[{"step": "drop_table"}])
    assert db.calls == []


def test_txn_log_list_params_org_first_filters_doubled_then_paging():
    db = RecDb()
    log_repo.list_events(db, org_id="ORG", request_id="r1", step="committed", limit=5, offset=10)
    sql, params = db.calls[0]
    assert params == ("ORG", "r1", "r1", None, None, "committed", "committed", None, None, 10, 5)
    assert "ORDER BY created_at DESC" in sql
    log_repo.list_events(db, org_id="ORG", oldest_first=True, limit=0, offset=-5)
    assert "ORDER BY created_at ASC" in db.calls[1][0] and db.calls[1][1][-2:] == (0, 1)  # clamped
    log_repo.list_requests(db, org_id="ORG", outcome="committed", operation="void_sale", limit=7, offset=2)
    assert db.calls[2][1] == ("ORG", None, None, "void_sale", "void_sale", "committed", "committed", 2, 7)


def test_lab_wait_uses_only_the_fixed_literals():
    db = RecDb()
    lab_repo.wait(db, 0)
    assert db.calls == []
    lab_repo.wait(db, 3)
    assert db.calls == [("WAITFOR DELAY '00:00:03'", ())]
    for bad in (6, -1, 1.5, "1", "1; DROP TABLE products", None, True):
        with pytest.raises(ValueError):
            lab_repo.wait(db, bad)  # type: ignore[arg-type]
    assert len(db.calls) == 1


def test_lab_statements_are_scoped_and_parameterised():
    db = RecDb(rows=[{"stock_qty": 4}])
    assert lab_repo.read_stock(db, org_id="O", product_id="P") == 4
    lab_repo.write_stock(db, org_id="O", product_id="P", new_qty=3)
    lab_repo.touch_stock(db, org_id="O", product_id="P", delta=-1)
    lab_repo.safe_decrement(db, org_id="O", product_id="P", quantity=2)
    assert [c[1] for c in db.calls] == [("P", "O"), (3, "P", "O"), (-1, "P", "O"), (2, "P", "O", 2)]


def test_lab_prepare_session_validates_the_isolation_level_through_the_allow_list():
    class Conn(RecDb):
        def set_isolation_level(self, level):
            from core.db import Db

            Db.set_isolation_level(self, level)

    db = Conn()
    lab_repo.prepare_session(db, isolation_level="SERIALIZABLE", deadlock_low=True)
    assert [c[0] for c in db.calls] == ["SET TRANSACTION ISOLATION LEVEL SERIALIZABLE", "SET LOCK_TIMEOUT 15000", "SET DEADLOCK_PRIORITY LOW"]
    with pytest.raises(ValueError):
        lab_repo.prepare_session(Conn(), isolation_level="READ COMMITTED; SHUTDOWN")
