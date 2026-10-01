"""TxnRecorder + its wiring into run_with_deadlock_retry / the services (event order for every outcome), flush, request ids."""
import time

import pytest

from core import clients
from repository import expenses_repository, sales_repository
from repository.base import ProcedureError
from services import expenses_service, products_service, sales_service, txn_log_service
from services.txn_log_service import TxnRecorder
from tests.fake_repos import FakeLogDb

ORG = "org-1"


def _rec(**kw):
    kw.setdefault("suspect_ms", 10_000)  # off unless a test wants it
    return TxnRecorder(request_id="req-0000001", org_id=ORG, **kw)


def _steps(rec):
    return [e["step"] for e in rec.events]


def _product(db, stock=5):
    return products_service.create_product(db, org_id=ORG, user_id="u", name="Mug", sku="MUG", price=10.0, stock_qty=stock)


def _sell(db, rec, product, qty=1):
    return sales_service.create_sale(db, org_id=ORG, user_id="u", items=[{"product_id": product["id"], "quantity": qty}], on_event=rec.on_event)


def _flaky(monkeypatch, failures, error=lambda: ProcedureError(1205, "deadlock victim")):
    real, calls = sales_repository.record_sale, []

    def flaky(db, **kw):
        calls.append(1)
        if len(calls) <= failures:
            raise error()
        return real(db, **kw)

    monkeypatch.setattr(sales_repository, "record_sale", flaky)
    monkeypatch.setattr("core.db.time.sleep", lambda s: None)  # no real backoff
    return calls


def test_success_path_started_then_committed(fake_db):
    rec = _rec()
    _sell(fake_db, rec, _product(fake_db))
    rec.committed()  # what routers.deps.get_db does after db.commit()
    assert _steps(rec) == ["txn_started", "committed"]
    started, committed = rec.events
    assert started["operation"] == committed["operation"] == "record_sale" and started["retry_no"] == 0
    assert committed["status"] == "committed" and committed["duration_ms"] >= 0 and committed["request_id"] == "req-0000001"


def test_committed_is_not_recorded_for_a_request_without_instrumented_work():
    rec = _rec()
    rec.committed()
    rec.rolled_back(RuntimeError("x"))
    assert rec.events == []


def test_business_rejection_is_labelled_business_rejected_not_rolled_back(fake_db):
    rec = _rec()
    mug = _product(fake_db, stock=1)
    with pytest.raises(sales_service.InsufficientStockError):
        _sell(fake_db, rec, mug, qty=2)
    # the router turns it into HTTP 409 and get_db rolls the (empty) request transaction back:
    class Http409(Exception):
        status_code = 409
        detail = "Not enough stock"

    rec.rolled_back(Http409())
    assert _steps(rec) == ["txn_started", "business_rejected"]
    rejected = rec.events[-1]
    assert rejected["error_number"] == 50001 and rejected["status"] == "rejected" and "not an engine rollback" in rejected["message"]


def test_deadlock_once_then_success(fake_db, monkeypatch):
    rec = _rec()
    calls = _flaky(monkeypatch, failures=1)
    _sell(fake_db, rec, _product(fake_db))
    rec.committed()
    assert len(calls) == 2
    assert _steps(rec) == ["txn_started", "deadlock_1205_caught", "retry_triggered", "txn_started", "committed"]
    by_step = {e["step"]: e for e in rec.events}
    assert by_step["deadlock_1205_caught"]["error_number"] == 1205 and by_step["retry_triggered"]["retry_no"] == 1
    assert [e["retry_no"] for e in rec.events if e["step"] == "txn_started"] == [0, 1]
    assert by_step["committed"]["retry_no"] == 1 and "after 1 retry" in by_step["committed"]["message"]


def test_deadlock_exhausting_retries_ends_in_rolled_back(fake_db, monkeypatch):
    rec = _rec()
    _flaky(monkeypatch, failures=99)
    with pytest.raises(ProcedureError):
        _sell(fake_db, rec, _product(fake_db))
    rec.rolled_back(ProcedureError(1205, "deadlock victim"))  # get_db after the exception escaped the handler
    assert _steps(rec) == (["txn_started", "deadlock_1205_caught", "retry_triggered"] * 3 + ["txn_started", "deadlock_1205_caught", "rolled_back"])
    last = rec.events[-1]
    assert last["status"] == "rolled_back" and last["error_number"] == 1205 and "retries exhausted" in last["message"]


def test_lock_timeout_1222_is_its_own_step(fake_db, monkeypatch):
    rec = _rec()
    _flaky(monkeypatch, failures=1, error=lambda: ProcedureError(1222, "Lock request time out period exceeded"))
    _sell(fake_db, rec, _product(fake_db))
    assert _steps(rec)[:3] == ["txn_started", "lock_timeout_caught", "retry_triggered"]
    assert rec.events[1]["error_number"] == 1222


def test_engine_error_rolls_back_without_retry(fake_db, monkeypatch):
    rec = _rec()
    calls = _flaky(monkeypatch, failures=99, error=lambda: ProcedureError(547, "CHECK constraint conflict"))
    with pytest.raises(ProcedureError):
        _sell(fake_db, rec, _product(fake_db))
    rec.rolled_back(ProcedureError(547, "CHECK constraint conflict"))
    assert len(calls) == 1 and _steps(rec) == ["txn_started", "rolled_back"]
    assert rec.events[-1]["error_number"] == 547 and rec.events[-1]["status"] == "rolled_back"


def test_lock_wait_suspected_is_inferred_from_elapsed_time(fake_db, monkeypatch):
    real = sales_repository.record_sale

    def slow(db, **kw):
        time.sleep(0.05)
        return real(db, **kw)

    monkeypatch.setattr(sales_repository, "record_sale", slow)
    rec = _rec(suspect_ms=20)
    _sell(fake_db, rec, _product(fake_db))
    assert _steps(rec) == ["txn_started", "lock_wait_suspected"]
    waited = rec.events[-1]
    assert waited["duration_ms"] >= 20 and waited["status"] == "suspected" and "SUSPECTED" in waited["message"] and "not observed" in waited["message"]


def test_fast_calls_are_not_suspected(fake_db):
    rec = _rec(suspect_ms=10_000)
    _sell(fake_db, rec, _product(fake_db))
    assert "lock_wait_suspected" not in _steps(rec)


def test_other_money_paths_report_their_operation(fake_db):
    rec = _rec()
    exp = expenses_service.create_expense(fake_db, org_id=ORG, user_id="u", amount=5.0, category="c", on_event=rec.on_event)
    expenses_service.update_expense(fake_db, org_id=ORG, expense_id=exp["id"], updates={"amount": 6.0}, user_id="u", on_event=rec.on_event)
    expenses_service.delete_expense(fake_db, org_id=ORG, expense_id=exp["id"], user_id="u", on_event=rec.on_event)
    sale = sales_service.create_sale(fake_db, org_id=ORG, user_id="u", amount=3.0, on_event=rec.on_event)
    sales_service.update_sale(fake_db, org_id=ORG, sale_id=sale["id"], updates={"amount": 4.0}, user_id="u", on_event=rec.on_event)
    sales_service.delete_sale(fake_db, org_id=ORG, sale_id=sale["id"], user_id="u", on_event=rec.on_event)
    assert [e["operation"] for e in rec.events if e["step"] == "txn_started"] == [
        "record_expense", "adjust_entry_amount", "void_expense", "record_sale", "adjust_entry_amount", "void_sale"]


def test_not_found_void_is_a_business_rejection(fake_db):
    rec = _rec()
    with pytest.raises(sales_service.NotFoundError):
        sales_service.delete_sale(fake_db, org_id=ORG, sale_id="nope", user_id="u", on_event=rec.on_event)
    assert _steps(rec) == ["txn_started", "business_rejected"] and rec.events[-1]["operation"] == "void_sale"


def test_failure_after_work_in_a_4xx_without_prior_rejection_is_a_rollback(fake_db):
    rec = _rec()
    _sell(fake_db, rec, _product(fake_db))

    class Http422(Exception):
        status_code = 422
        detail = "bad things"

    rec.rolled_back(Http422())
    assert _steps(rec) == ["txn_started", "rolled_back"] and "HTTP 422" in rec.events[-1]["message"]


def test_isolation_level_is_read_once_lazily_and_failures_are_tolerated(fake_db):
    calls = []
    rec = _rec(isolation_provider=lambda: calls.append(1) or "SERIALIZABLE")
    assert calls == []
    _sell(fake_db, rec, _product(fake_db))
    rec.committed()
    assert calls == [1] and {e["isolation_level"] for e in rec.events} == {"SERIALIZABLE"}
    broken = _rec(isolation_provider=lambda: 1 / 0)
    broken.on_event("txn_started", operation="record_sale", attempt=1)
    assert broken.events[0]["isolation_level"] is None


def test_messages_are_clipped_and_a_broken_hook_input_never_raises():
    rec = _rec()
    rec.on_event("deadlock_retry", operation="record_sale", attempt=1, elapsed_ms=1, error="x" * 5000, error_number=1205)
    assert all(len(e["message"] or "") <= 400 for e in rec.events)
    rec.on_event("deadlock_retry", attempt="not-a-number")  # swallowed
    rec.on_event("something_unknown")  # ignored
    assert len(rec.events) == 2


def test_request_id_pattern():
    ok = ["abcDEF12", "a1b2c3d4-e5f6.7890_x", "x" * 64]
    bad = ["", None, "short", "x" * 65, "has space 123", "semi;colon12", "new\nline1234", "<script>12345", "ünïcode123"]
    assert all(txn_log_service.is_safe_request_id(v) for v in ok)
    assert not any(txn_log_service.is_safe_request_id(v) for v in bad)


# ---- flush: separate autocommit connection, never raises ----------------------------------------------------------
def test_flush_writes_through_a_separate_autocommit_connection(sql_store, fake_db):
    opened = []
    clients.set_autocommit_factory(lambda: opened.append(FakeLogDb(sql_store)) or opened[-1])
    rec = _rec()
    _sell(fake_db, rec, _product(fake_db))
    rec.committed()
    assert txn_log_service.flush(rec) == 2
    assert len(opened) == 1 and opened[0].closed and opened[0] is not fake_db
    assert [r["step"] for r in sql_store.txn_log] == ["txn_started", "committed"] and {r["org_id"] for r in sql_store.txn_log} == {ORG}
    assert rec.events == []  # drained: a second flush writes nothing
    assert txn_log_service.flush(rec) == 0 and len(opened) == 1


def test_flush_without_events_or_org_does_not_even_connect(sql_store):
    clients.set_autocommit_factory(lambda: pytest.fail("must not connect"))
    assert txn_log_service.flush(_rec()) == 0
    anon = TxnRecorder(request_id="req-0000002", org_id=None)
    anon.on_event("txn_started", operation="x", attempt=1)
    assert txn_log_service.flush(anon) == 0


def test_a_failing_log_write_never_raises(sql_store, fake_db):
    def boom():
        raise RuntimeError("log database is down")

    clients.set_autocommit_factory(boom)
    rec = _rec()
    _sell(fake_db, rec, _product(fake_db))
    assert txn_log_service.flush(rec) == 0


def test_events_survive_a_rolled_back_business_connection(sql_store, fake_db):
    """The model of the whole design: business rows are restored by rollback, the log (separate connection) is not."""
    mug = _product(fake_db, stock=5)
    fake_db.commit()
    rec = _rec()
    _sell(fake_db, rec, mug, qty=2)
    assert sql_store.products[mug["id"]]["stock_qty"] == 3
    fake_db.rollback()  # the request fails after the work
    rec.rolled_back(RuntimeError("boom"))
    txn_log_service.flush(rec)
    assert sql_store.products[mug["id"]]["stock_qty"] == 5  # business change undone ...
    assert [r["step"] for r in sql_store.txn_log] == ["txn_started", "rolled_back"]  # ... the log was not
