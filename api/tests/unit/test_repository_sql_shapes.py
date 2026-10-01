"""The REAL repositories against a recording Db (no SQL Server): checks the statements/params
they send. T-SQL itself is not executed here; tests/sqlserver/ does that (RUN_MSSQL=1)."""
from __future__ import annotations

import datetime as dt
import decimal
import json

import pytest

from repository import agent_jobs_repository as jobs_repo
from repository import expenses_repository as exp_repo
from repository import sales_repository as sales_repo


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


def test_create_sale_params_and_output_into():
    db = RecDb([{"id": "s1"}])
    sales_repo.create_sale(db, org_id="o1", created_by="u1", amount=12.34, category="c", description="d", customer_name="n")
    sql, p = db.calls[0]
    assert "OUTPUT" in sql and "INTO @o" in sql and "SELECT * FROM @o" in sql  # trigger-safe
    assert p[:2] == ("o1", "u1") and p[2] == decimal.Decimal("12.34")
    assert p[3:6] == ("c", "n", "d") and isinstance(p[6], dt.date)


def test_scoped_statements_send_id_then_org_id():
    db = RecDb([{"id": "s1"}])
    sales_repo.get_sale_scoped(db, sale_id="s1", org_id="o1")
    assert db.calls[-1][1] == ("s1", "o1")
    sales_repo.update_sale_scoped(db, sale_id="s1", org_id="o1", updates={"amount": 5.0})
    sql, p = db.calls[-1]
    assert p[-2:] == ("s1", "o1") and p[0] == decimal.Decimal("5.0") and p[1:4] == (None, None, None)
    assert "WHERE id = ? AND org_id = ?" in sql
    assert sales_repo.delete_sale_scoped(db, sale_id="s1", org_id="o1") is True
    assert db.calls[-1][1] == ("s1", "o1")
    assert sales_repo.delete_sale_scoped(RecDb(rowcount=0), sale_id="s1", org_id="o2") is False


def test_update_rejects_unknown_columns_without_touching_db():
    db = RecDb()
    with pytest.raises(ValueError):
        exp_repo.update_expense_scoped(db, expense_id="e", org_id="o", updates={"org_id": "other"})
    assert db.calls == []


def test_expense_update_maps_voucher_reference():
    db = RecDb([{"id": "e"}])
    exp_repo.update_expense_scoped(db, expense_id="e", org_id="o", updates={"voucher_reference": "V-9"})
    assert db.calls[0][1][2] == "V-9"


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
