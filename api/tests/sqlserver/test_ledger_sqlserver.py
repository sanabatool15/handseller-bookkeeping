"""Real SQL Server tests (slice F0b). Run with: RUN_MSSQL=1 pytest tests/sqlserver -v

Needs sql_server/01_foundation.sql AND 02_sales_expenses_agents.sql applied and MSSQL_* env / .env
pointing at HandsellerDB. Every test creates its own org/user (unique names) and removes them again.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_MSSQL") != "1", reason="set RUN_MSSQL=1 to run against SQL Server")


@pytest.fixture(autouse=True)
def _real_repos(monkeypatch):
    """Undo the in-memory fakes installed by tests/conftest.py: use the real repositories."""
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
        out = auth_service.register(db, email=self.email, password="pw12345678", full_name="T", org_name="mssql-test-ledger")
        self.org_id, self.user_id = out["org"]["id"], out["user"]["id"]


def _purge(db, tenants):
    """Delete everything the tenants created (children first), scoped by org_id."""
    db.rollback()
    for t in tenants:
        for table in ("agent_logs", "agent_jobs", "sales", "expenses"):
            db.execute(f"DELETE FROM {table} WHERE org_id = ?", (t.org_id,))  # test-only literal table names
        db.execute("UPDATE orgs SET owner_id = NULL WHERE id = ?", (t.org_id,))
        db.execute("DELETE FROM users WHERE org_id = ?", (t.org_id,))
        db.execute("DELETE FROM orgs WHERE id = ?", (t.org_id,))
    db.commit()


@pytest.fixture
def tenants(real_db):
    made: list[Tenant] = []

    def make():
        t = Tenant(real_db)
        made.append(t)
        return t

    yield make
    _purge(real_db, made)


def test_create_sale_and_expense_json_shape(real_db, tenants):
    from services import expenses_service, sales_service

    t = tenants()
    sale = sales_service.create_sale(real_db, org_id=t.org_id, user_id=t.user_id, amount=19.99, category="retail", customer_name="Zed")
    exp = expenses_service.create_expense(real_db, org_id=t.org_id, user_id=t.user_id, amount=5.25, category="rent", voucher_reference="V-1")
    real_db.commit()
    assert isinstance(sale["id"], str) and sale["amount"] == 19.99 and isinstance(sale["amount"], float)
    assert sale["sale_date"] == dt.datetime.now(dt.timezone.utc).date().isoformat()
    assert isinstance(sale["created_at"], str) and exp["voucher_reference"] == "V-1" and isinstance(exp["expense_date"], str)


def test_tenant_isolation_by_id_and_org(real_db, tenants):
    from repository import base, expenses_repository, sales_repository
    from services import sales_service

    a, b = tenants(), tenants()
    sale = sales_service.create_sale(real_db, org_id=a.org_id, user_id=a.user_id, amount=10, category="retail")
    real_db.commit()
    assert sales_repository.get_sale_scoped(real_db, sale_id=sale["id"], org_id=b.org_id) is None
    assert sales_repository.update_sale_scoped(real_db, sale_id=sale["id"], org_id=b.org_id, updates={"amount": 999}) is None
    assert sales_repository.delete_sale_scoped(real_db, sale_id=sale["id"], org_id=b.org_id) is False
    real_db.commit()
    assert sales_repository.get_sale_scoped(real_db, sale_id=sale["id"], org_id=a.org_id)["amount"] == 10.0
    assert base.get_ownership(real_db, table="sales", record_id=sale["id"], org_id=a.org_id) is True
    assert base.get_ownership(real_db, table="sales", record_id=sale["id"], org_id=b.org_id) is False
    assert sales_repository.list_sales(real_db, org_id=b.org_id) == []
    assert expenses_repository.list_expenses(real_db, org_id=b.org_id) == []


def test_update_returns_row_and_trigger_bumps_updated_at(real_db, tenants):
    import time

    from repository import sales_repository
    from services import sales_service

    t = tenants()
    sale = sales_service.create_sale(real_db, org_id=t.org_id, user_id=t.user_id, amount=10, category="retail")
    real_db.commit()
    time.sleep(1.1)
    upd = sales_repository.update_sale_scoped(real_db, sale_id=sale["id"], org_id=t.org_id, updates={"category": "wholesale"})
    real_db.commit()
    assert upd["category"] == "wholesale" and upd["amount"] == 10.0  # untouched columns keep their values
    fresh = sales_repository.get_sale_scoped(real_db, sale_id=sale["id"], org_id=t.org_id)
    assert fresh["updated_at"] > sale["updated_at"]  # (the OUTPUT row itself holds the pre-trigger value)


def test_month_sums_and_breakdown_computed_in_sql(real_db, tenants):
    from repository import expenses_repository, sales_repository
    from services import financial_report_service as fin

    t = tenants()
    # Explicit dates: one inside Feb 2026, two just outside (Jan 31 / Mar 1) - boundaries of the half-open range.
    for d, amount, cat in (("2026-02-01", 100.10, "retail"), ("2026-02-28", 50.20, "retail"), ("2026-01-31", 7.0, "retail"), ("2026-03-01", 9.0, "retail")):
        real_db.execute("INSERT INTO sales (org_id, created_by, amount, category, sale_date) VALUES (?, ?, ?, ?, ?)", (t.org_id, t.user_id, amount, cat, d))
    real_db.execute("INSERT INTO sales (org_id, created_by, amount, category, sale_date) VALUES (?, ?, ?, ?, ?)", (t.org_id, t.user_id, 1.0, "gifts", "2026-02-10"))
    for amount, cat in ((40.0, "rent"), (10.0, "rent"), (25.0, "packaging")):
        real_db.execute("INSERT INTO expenses (org_id, created_by, amount, category, expense_date) VALUES (?, ?, ?, ?, ?)", (t.org_id, t.user_id, amount, cat, "2026-02-15"))
    real_db.commit()

    assert sales_repository.sum_sales_for_month(real_db, org_id=t.org_id, year=2026, month=2) == pytest.approx(151.30)
    assert sales_repository.sum_sales_by_category_for_month(real_db, org_id=t.org_id, year=2026, month=2) == {"retail": pytest.approx(150.30), "gifts": 1.0}
    assert expenses_repository.sum_expenses_by_category_for_month(real_db, org_id=t.org_id, year=2026, month=2) == {"rent": 50.0, "packaging": 25.0}
    assert sales_repository.sum_sales_for_month(real_db, org_id=t.org_id, year=2026, month=4) == 0.0  # no rows => 0, not NULL
    summary = fin.monthly_summary(real_db, org_id=t.org_id, year=2026, month=2)
    assert summary["net_profit"] == pytest.approx(151.30 - 75.0)
    assert "2026-02-28" in fin.monthly_ledger_csv(real_db, org_id=t.org_id, year=2026, month=2)


def test_agent_job_lifecycle_and_json_columns(real_db, tenants):
    from repository import agent_jobs_repository as repo

    a, b = tenants(), tenants()
    job = repo.create_job(real_db, job_name="financial_advisor", org_id=a.org_id, requested_by=a.user_id, input_payload={"question": "q"})
    real_db.commit()
    assert job["status"] == "pending" and job["input_payload"] == {"question": "q"} and job["result"] is None

    repo.add_log(real_db, job_id=job["id"], org_id=a.org_id, step_name="gather_data", action_summary="x", insights_generated={"total_sales": 1.5})
    done = repo.update_job_status(real_db, job_id=job["id"], org_id=a.org_id, status="completed", current_step="finalize", result={"advice": {"summary": "ok"}})
    real_db.commit()
    assert done["status"] == "completed" and done["result"] == {"advice": {"summary": "ok"}}
    assert [l["step_name"] for l in repo.list_logs_for_job(real_db, job_id=job["id"], org_id=a.org_id)] == ["gather_data"]
    assert repo.get_completed_steps(real_db, job_id=job["id"], org_id=a.org_id) == {"gather_data"}

    # Another org: invisible, cannot be updated, cannot receive logs.
    assert repo.get_job_scoped(real_db, job_id=job["id"], org_id=b.org_id) is None
    assert repo.update_job_status(real_db, job_id=job["id"], org_id=b.org_id, status="failed") is None
    with pytest.raises(RuntimeError):
        repo.add_log(real_db, job_id=job["id"], org_id=b.org_id, step_name="evil", action_summary="x")
    real_db.rollback()
    assert repo.list_logs_for_job(real_db, job_id=job["id"], org_id=b.org_id) == []


def test_db_constraints_reject_bad_status_and_bad_json(real_db, tenants):
    t = tenants()
    with pytest.raises(Exception):  # CK_agent_jobs_status
        real_db.execute("INSERT INTO agent_jobs (job_name, org_id, status) VALUES (N'x', ?, N'bogus')", (t.org_id,))
    real_db.rollback()
    with pytest.raises(Exception):  # CK_agent_jobs_input_json (ISJSON)
        real_db.execute("INSERT INTO agent_jobs (job_name, org_id, input_payload) VALUES (N'x', ?, N'not json')", (t.org_id,))
    real_db.rollback()


def test_job_steps_end_to_end_with_real_db(tenants, real_db, monkeypatch):
    import asyncio

    from jobs import financial_agent_job as job
    from repository import agent_jobs_repository as repo

    t = tenants()
    created = repo.create_job(real_db, job_name="financial_advisor", org_id=t.org_id, requested_by=t.user_id)
    real_db.commit()

    async def no_llm(*a, **k):
        raise RuntimeError("force rule-based fallback")

    monkeypatch.setattr(job, "run_bookkeeping_agent", no_llm)

    async def run():
        summary = await job._step_gather_data(created["id"], t.org_id)
        result = await job._step_run_agent(created["id"], t.org_id, t.user_id, None, summary)
        await job._step_finalize(created["id"], t.org_id, result)

    asyncio.run(run())
    final = repo.get_job_scoped(real_db, job_id=created["id"], org_id=t.org_id)
    real_db.commit()
    assert final["status"] == "completed" and final["result"]["source"] == "rule_based_fallback"
    assert repo.get_completed_steps(real_db, job_id=created["id"], org_id=t.org_id) == {"gather_data", "run_agent", "finalize"}


def test_health_ping(real_db):
    from repository import health_repository

    assert health_repository.ping(real_db) is True
