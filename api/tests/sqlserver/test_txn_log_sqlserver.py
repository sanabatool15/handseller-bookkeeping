"""Real SQL Server tests (slice F5: txn_log + DB Lab).
Run with: RUN_MSSQL=1 pytest tests/sqlserver/test_txn_log_sqlserver.py -v

Needs sql_server/01..07 applied and MSSQL_* env / .env pointing at HandsellerDB. Every test creates its own org/user and removes
everything again (including its txn_log rows). The lab tests take several seconds (WAITFOR + the deadlock monitor).
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.environ.get("RUN_MSSQL") != "1", reason="set RUN_MSSQL=1 to run against SQL Server")


@pytest.fixture(autouse=True)
def _real_repos(monkeypatch):
    from core.clients import set_autocommit_factory, set_db_factory

    monkeypatch.undo()
    set_db_factory(None)
    set_autocommit_factory(None)


@pytest.fixture
def real_db():
    from core.clients import get_db_connection

    db = get_db_connection()
    yield db
    db.rollback()
    db.close()


@pytest.fixture
def lab_enabled(monkeypatch):
    from services import db_lab_service

    monkeypatch.setattr(db_lab_service, "is_enabled", lambda: True)


class Tenant:
    def __init__(self, db):
        from services import auth_service

        out = auth_service.register(db, email=f"mssql-{uuid.uuid4().hex[:8]}@example.com", password="pw12345678", full_name="T", org_name="mssql-test-txn-log")
        self.org_id, self.user_id = out["org"]["id"], out["user"]["id"]


@pytest.fixture
def tenants(real_db):
    made: list[str] = []

    def make():
        t = Tenant(real_db)
        made.append(t.org_id)
        return t

    yield make
    real_db.rollback()
    for org_id in made:
        for table in ("txn_log", "sale_items", "sales", "cash_ledger", "cash_accounts", "products"):
            real_db.execute(f"DELETE FROM {table} WHERE org_id = ?", (org_id,))  # test-only literal table names
        real_db.execute("UPDATE orgs SET owner_id = NULL WHERE id = ?", (org_id,))
        real_db.execute("DELETE FROM users WHERE org_id = ?", (org_id,))
        real_db.execute("DELETE FROM orgs WHERE id = ?", (org_id,))
    real_db.commit()


def _product(db, t, sku, stock=1):
    from services import products_service

    p = products_service.create_product(db, org_id=t.org_id, user_id=t.user_id, name=sku, sku=sku, price=5.0, stock_qty=stock)
    db.commit()
    return p


def _stock(db, t, pid):
    from services import products_service

    db.commit()
    return products_service.get_product(db, org_id=t.org_id, product_id=pid)["stock_qty"]


def test_isolation_level_round_trip_on_a_real_session(real_db):
    assert real_db.get_isolation_level() == "READ COMMITTED"
    for level in ("SERIALIZABLE", "REPEATABLE READ", "READ UNCOMMITTED", "READ COMMITTED"):
        real_db.set_isolation_level(level)
        assert real_db.get_isolation_level() == level
    with pytest.raises(ValueError):
        real_db.set_isolation_level("GARBAGE")
    real_db.rollback()


def test_txn_log_insert_and_reads_are_org_scoped_with_a_real_autocommit_connection(real_db, tenants):
    from core.clients import get_autocommit_connection
    from repository import txn_log_repository as repo

    a, b = tenants(), tenants()
    ev = [{"request_id": "req-real-0001", "operation": "record_sale", "step": s, "isolation_level": "READ COMMITTED", "status": "x",
           "error_number": None, "message": "m", "duration_ms": 3, "retry_no": 0, "created_at": "2026-05-01T10:00:00.123456"}
          for s in ("txn_started", "deadlock_1205_caught", "retry_triggered", "committed")]
    log_db = get_autocommit_connection()
    try:
        assert repo.insert_events(log_db, org_id=a.org_id, events=ev) == 4
    finally:
        log_db.close()
    rows = repo.list_events(real_db, org_id=a.org_id, request_id="req-real-0001", oldest_first=True)
    assert [r["step"] for r in rows] == ["txn_started", "deadlock_1205_caught", "retry_triggered", "committed"]  # identity order == seq
    assert isinstance(rows[0]["id"], int) and "2026-05-01T10:00:00.123456" in rows[0]["created_at"]
    assert repo.list_events(real_db, org_id=b.org_id) == [] and repo.list_requests(real_db, org_id=b.org_id) == []
    summary = repo.list_requests(real_db, org_id=a.org_id)
    assert len(summary) == 1 and summary[0]["outcome"] == "deadlock_retried" and summary[0]["retries"] == 1 and summary[0]["deadlocks"] == 1
    assert summary[0]["event_count"] == 4 and len(repo.list_events(real_db, org_id=a.org_id, limit=2, offset=3)) == 1
    from core.db import Db

    with pytest.raises(Exception):  # the CHECK constraint is the backstop for a bad step
        bad = get_autocommit_connection()
        try:
            bad.execute("INSERT INTO txn_log (request_id, org_id, operation, step) VALUES (?, ?, ?, ?)", ("req-real-0002", a.org_id, "x", "bogus"))
        finally:
            bad.close()
    assert isinstance(real_db, Db)


def test_a_rolled_back_request_still_leaves_its_log(real_db, tenants):
    """End to end through the API on SQL Server: the stock decrement is rolled back, the txn_log rows are not."""
    from core.fastapi_app import app
    from repository import sales_repository
    from repository.base import ProcedureError
    from tests.integration.conftest import auth_headers, register_and_login

    real_record = sales_repository.record_sale
    with TestClient(app, raise_server_exceptions=False) as client:
        out = register_and_login(client, f"rb-{uuid.uuid4().hex[:8]}@example.com")
        tok, org_id = out["access_token"], out["org"]["id"]
        owner = SimpleNamespace(org_id=org_id)  # just what _stock() needs
        try:
            p = client.post("/products", json={"name": "Mug", "sku": "M1", "price": 5.0, "stock_qty": 3}, headers=auth_headers(tok, "p1")).json()
            # 1) business rejection: 409 + business_rejected
            r409 = client.post("/sales", json={"items": [{"product_id": p["id"], "quantity": 9}]}, headers=auth_headers(tok, "s1"))
            assert r409.status_code == 409 and r409.json()["request_id"] == r409.headers["X-Request-ID"]
            # 2) engine failure AFTER the procedure committed its work inside the request transaction
            def work_then_fail(db, **kw):
                real_record(db, **kw)
                raise ProcedureError(547, "simulated engine failure")

            sales_repository.record_sale = work_then_fail
            try:
                r500 = client.post("/sales", json={"items": [{"product_id": p["id"], "quantity": 1}]}, headers=auth_headers(tok, "s2"))
            finally:
                sales_repository.record_sale = real_record
            assert r500.status_code == 500
            real_db.commit()
            assert _stock(real_db, owner, p["id"]) == 3  # nothing was sold
            steps = lambda rid: [e["step"] for e in client.get("/db-logs", params={"request_id": rid, "order": "asc"}, headers=auth_headers(tok, "g")).json()]  # noqa: E731
            assert steps(r409.headers["X-Request-ID"]) == ["txn_started", "business_rejected"]
            assert steps(r500.headers["X-Request-ID"]) == ["txn_started", "rolled_back"]
            ok = client.post("/sales", json={"items": [{"product_id": p["id"], "quantity": 1}]}, headers=auth_headers(tok, "s3"))
            assert ok.status_code == 201 and steps(ok.headers["X-Request-ID"]) == ["txn_started", "committed"]
        finally:
            real_db.rollback()
            for table in ("txn_log", "sale_items", "sales", "cash_ledger", "cash_accounts", "products"):
                real_db.execute(f"DELETE FROM {table} WHERE org_id = ?", (org_id,))
            real_db.execute("UPDATE orgs SET owner_id = NULL WHERE id = ?", (org_id,))
            real_db.execute("DELETE FROM users WHERE org_id = ?", (org_id,))
            real_db.execute("DELETE FROM orgs WHERE id = ?", (org_id,))
            real_db.commit()


def test_race_unsafe_can_oversell_but_safe_cannot(real_db, tenants, lab_enabled):
    from repository import txn_log_repository
    from services import db_lab_service

    t = tenants()
    p = _product(real_db, t, "LAST", stock=1)
    unsafe = db_lab_service.race_sale(real_db, org_id=t.org_id, product_id=p["id"], quantity=1, clients_n=3, mode="unsafe",
                                      isolation_level="READ COMMITTED", delay_seconds=1)
    assert unsafe["summary"]["committed"] == 3 and unsafe["summary"]["oversold_units"] == 2  # all three read stock = 1: lost update
    assert unsafe["stock_after_race"] == 0 and unsafe["stock_after"] == 1 and _stock(real_db, t, p["id"]) == 1  # restored

    safe = db_lab_service.race_sale(real_db, org_id=t.org_id, product_id=p["id"], quantity=1, clients_n=3, mode="safe",
                                    isolation_level="READ COMMITTED", delay_seconds=1)
    assert safe["summary"]["committed"] == 1 and safe["summary"]["rejected"] == 2 and safe["summary"]["oversold_units"] == 0
    assert safe["stock_after_race"] == 0 and _stock(real_db, t, p["id"]) == 1
    # losers waited behind the winner's lock for ~1 s: suspected (inferred) lock waits are in the log
    steps = {e["step"] for e in txn_log_repository.list_events(real_db, org_id=t.org_id, limit=200)}
    assert {"txn_started", "committed", "business_rejected", "lock_wait_suspected"} <= steps


def test_unsafe_race_at_serializable_never_oversells(real_db, tenants, lab_enabled):
    from services import db_lab_service

    t = tenants()
    p = _product(real_db, t, "LAST2", stock=1)
    out = db_lab_service.race_sale(real_db, org_id=t.org_id, product_id=p["id"], quantity=1, clients_n=2, mode="unsafe",
                                   isolation_level="SERIALIZABLE", delay_seconds=1)
    assert out["summary"]["committed"] == 1 and out["summary"]["oversold_units"] == 0 and out["stock_after_race"] == 0
    assert out["summary"]["deadlock_victims"] >= 1  # S -> X conversion deadlock; the victim retried and then saw 0
    assert _stock(real_db, t, p["id"]) == 1


def test_real_deadlock_has_exactly_one_victim_and_the_retry_succeeds(real_db, tenants, lab_enabled):
    from repository import txn_log_repository
    from services import db_lab_service

    t = tenants()
    a, b = _product(real_db, t, "DA", stock=4), _product(real_db, t, "DB", stock=7)
    out = db_lab_service.deadlock(real_db, org_id=t.org_id, product_a=a["id"], product_b=b["id"], delay_seconds=1)
    assert out["summary"]["deadlock_victims"] == 1 and out["summary"]["committed"] == 2 and out["summary"]["retries"] == 1
    victim = next(r for r in out["results"] if r["error_number"] == 1205)
    assert victim["status"] == "committed" and victim["retries"] == 1
    assert out["restored"] is True and (_stock(real_db, t, a["id"]), _stock(real_db, t, b["id"])) == (4, 7)
    outcomes = sorted(r["outcome"] for r in txn_log_repository.list_requests(real_db, org_id=t.org_id))
    assert outcomes == ["committed", "deadlock_retried"]
    steps = [e["step"] for e in txn_log_repository.list_events(real_db, org_id=t.org_id, request_id=victim["request_id"], oldest_first=True)]
    assert "deadlock_1205_caught" in steps and "retry_triggered" in steps and steps[-1] == "committed"

    fixed = db_lab_service.deadlock(real_db, org_id=t.org_id, product_a=a["id"], product_b=b["id"], delay_seconds=1, fixed=True)
    assert fixed["summary"]["deadlock_victims"] == 0 and fixed["summary"]["retries"] == 0 and fixed["summary"]["committed"] == 2
