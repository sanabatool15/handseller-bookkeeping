"""/db-logs: events are written for the money paths (also when the request was rolled back), org scoping, filters, paging,
X-Request-ID handling (in-memory fakes; the log fake models a separate autocommit connection)."""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from core.fastapi_app import app
from repository import sales_repository
from repository.base import ProcedureError
from tests.integration.conftest import auth_headers, register_and_login

ROUTERS = pathlib.Path(__file__).resolve().parents[2] / "routers"


def _tok(client, email="log@example.com"):
    return register_and_login(client, email)["access_token"]


def _product(client, tok, sku="M1", stock=5):
    r = client.post("/products", json={"name": "Mug", "sku": sku, "price": 10.0, "stock_qty": stock}, headers=auth_headers(tok, f"p-{sku}"))
    assert r.status_code == 201, r.text
    return r.json()


def _sell(client, tok, product, qty, key, **headers):
    return client.post("/sales", json={"items": [{"product_id": product["id"], "quantity": qty}]}, headers={**auth_headers(tok, key), **headers})


def _events(client, tok, **params):
    r = client.get("/db-logs", params=params, headers=auth_headers(tok, "g"))
    assert r.status_code == 200, r.text
    return r.json()


def test_successful_sale_is_logged_started_then_committed_with_the_request_id_header(client):
    tok = _tok(client)
    r = _sell(client, tok, _product(client, tok), 1, "s1")
    assert r.status_code == 201
    rid = r.headers["X-Request-ID"]
    rows = _events(client, tok, request_id=rid, order="asc")
    assert [e["step"] for e in rows] == ["txn_started", "committed"]
    assert {e["operation"] for e in rows} == {"record_sale"} and {e["request_id"] for e in rows} == {rid}
    assert rows[0]["isolation_level"] == "READ COMMITTED" and rows[-1]["duration_ms"] >= 0
    assert all(isinstance(e["id"], int) and e["retry_no"] == 0 for e in rows)


def test_insufficient_stock_409_is_business_rejected_and_the_body_carries_the_request_id(client):
    tok = _tok(client)
    mug = _product(client, tok, stock=1)
    r = _sell(client, tok, mug, 5, "s1")
    assert r.status_code == 409
    assert r.json()["request_id"] == r.headers["X-Request-ID"] and "Not enough stock" in r.json()["detail"]
    rows = _events(client, tok, request_id=r.headers["X-Request-ID"], order="asc")
    assert [e["step"] for e in rows] == ["txn_started", "business_rejected"]
    assert rows[-1]["error_number"] == 50001 and rows[-1]["status"] == "rejected"  # NOT labelled rolled_back


def test_log_survives_a_rolled_back_business_transaction(sql_store):
    """The request fails with an engine error AFTER changing stock: get_db rolls the business transaction back (stock is
    restored) but txn_log - written on a separate autocommit connection afterwards - keeps the story."""
    with TestClient(app, raise_server_exceptions=False) as client:
        tok = _tok(client, "rb@example.com")
        mug = _product(client, tok, stock=5)
        real = sales_repository.record_sale

        def work_then_fail(db, **kw):
            real(db, **kw)  # the sale really happens (stock 5 -> 4, cash posted) ...
            raise ProcedureError(547, "CHECK constraint conflict")  # ... then the engine fails

        sales_repository.record_sale = work_then_fail
        try:
            r = _sell(client, tok, mug, 1, "s1")
        finally:
            sales_repository.record_sale = real
        assert r.status_code == 500
        assert sql_store.products[mug["id"]]["stock_qty"] == 5 and not sql_store.sales  # rolled back
        rows = _events(client, tok, request_id=r.headers["X-Request-ID"], order="asc")
        assert [e["step"] for e in rows] == ["txn_started", "rolled_back"]
        assert rows[-1]["error_number"] == 547 and rows[-1]["status"] == "rolled_back"


def test_every_money_path_is_instrumented(client):
    tok = _tok(client)
    mug = _product(client, tok)
    sale = _sell(client, tok, mug, 1, "s1").json()
    e = client.post("/expenses", json={"amount": 5, "category": "c"}, headers=auth_headers(tok, "e1")).json()
    client.put(f"/expenses/{e['id']}", json={"amount": 6}, headers=auth_headers(tok, "e2"))
    client.delete(f"/expenses/{e['id']}", headers=auth_headers(tok, "e3"))
    q = client.post("/sales", json={"amount": 9}, headers=auth_headers(tok, "q1")).json()
    client.put(f"/sales/{q['id']}", json={"amount": 10}, headers=auth_headers(tok, "q2"))
    client.delete(f"/sales/{sale['id']}", headers=auth_headers(tok, "d1"))
    ops = {e["operation"] for e in _events(client, tok, step="committed", limit=200)}
    assert ops == {"record_sale", "record_expense", "adjust_entry_amount", "void_expense", "void_sale"}


def test_reads_and_uninstrumented_writes_leave_no_log(client):
    tok = _tok(client)
    _product(client, tok)
    client.get("/products", headers=auth_headers(tok, "g1"))
    assert _events(client, tok) == []


def test_org_isolation_foreign_request_ids_are_invisible(client):
    a, b = _tok(client, "a@example.com"), _tok(client, "b@example.com")
    r = _sell(client, a, _product(client, a), 1, "s1")
    rid = r.headers["X-Request-ID"]
    assert len(_events(client, a, request_id=rid)) == 2
    assert _events(client, b, request_id=rid) == [] and _events(client, b) == []
    req_b = client.get("/db-logs/requests", params={"request_id": rid}, headers=auth_headers(b, "g"))
    assert req_b.status_code == 200 and req_b.json() == []
    assert len(client.get("/db-logs/requests", headers=auth_headers(a, "g")).json()) == 1


def test_requests_grouping_outcomes_and_filters(client, monkeypatch):
    tok = _tok(client)
    mug = _product(client, tok, stock=1)
    ok = _sell(client, tok, mug, 1, "s1").headers["X-Request-ID"]
    refused = _sell(client, tok, mug, 1, "s2").headers["X-Request-ID"]
    client.post("/expenses", json={"amount": 5}, headers=auth_headers(tok, "e1"))
    rows = client.get("/db-logs/requests", headers=auth_headers(tok, "g")).json()
    assert len(rows) == 3
    by_id = {r["request_id"]: r for r in rows}
    assert by_id[ok]["outcome"] == "committed" and by_id[ok]["event_count"] == 2 and by_id[ok]["operation"] == "record_sale"
    assert by_id[refused]["outcome"] == "rejected" and by_id[refused]["retries"] == 0
    assert set(by_id[ok]) >= {"request_id", "operation", "first_at", "last_at", "outcome", "retries", "deadlocks", "duration_ms", "isolation_level", "event_count"}
    assert [r["request_id"] for r in client.get("/db-logs/requests", params={"outcome": "rejected"}, headers=auth_headers(tok, "g")).json()] == [refused]
    assert [r["operation"] for r in client.get("/db-logs/requests", params={"operation": "record_expense"}, headers=auth_headers(tok, "g")).json()] == ["record_expense"]
    assert len(client.get("/db-logs/requests", params={"limit": 2}, headers=auth_headers(tok, "g")).json()) == 2
    assert len(client.get("/db-logs/requests", params={"limit": 2, "offset": 2}, headers=auth_headers(tok, "g")).json()) == 1


def test_a_deadlock_retried_request_gets_its_own_outcome(client, monkeypatch):
    tok = _tok(client)
    mug = _product(client, tok)
    real, calls = sales_repository.record_sale, []

    def flaky(db, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise ProcedureError(1205, "Transaction was deadlocked (1205)")
        return real(db, **kw)

    monkeypatch.setattr(sales_repository, "record_sale", flaky)
    monkeypatch.setattr("core.db.time.sleep", lambda s: None)
    r = _sell(client, tok, mug, 1, "s1")
    assert r.status_code == 201
    rid = r.headers["X-Request-ID"]
    assert [e["step"] for e in _events(client, tok, request_id=rid, order="asc")] == [
        "txn_started", "deadlock_1205_caught", "retry_triggered", "txn_started", "committed"]
    summary = client.get("/db-logs/requests", params={"request_id": rid}, headers=auth_headers(tok, "g")).json()[0]
    assert summary["outcome"] == "deadlock_retried" and summary["retries"] == 1 and summary["deadlocks"] == 1


def test_event_filters_and_paging(client):
    tok = _tok(client)
    mug = _product(client, tok, stock=3)
    for i in range(3):
        _sell(client, tok, mug, 1, f"s{i}")
    all_rows = _events(client, tok, limit=200)
    assert len(all_rows) == 6
    assert [e["step"] for e in _events(client, tok, step="committed")] == ["committed"] * 3
    assert len(_events(client, tok, status="started")) == 3 and len(_events(client, tok, operation="record_sale")) == 6
    assert _events(client, tok, operation="void_sale") == []
    newest = [e["id"] for e in all_rows]
    assert newest == sorted(newest, reverse=True)  # newest first by default
    assert [e["id"] for e in _events(client, tok, order="asc", limit=200)] == sorted(newest)
    page1, page2 = _events(client, tok, limit=4, offset=0), _events(client, tok, limit=4, offset=4)
    assert len(page1) == 4 and len(page2) == 2 and [e["id"] for e in page1 + page2] == newest


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"step": "drop_table"}, {"order": "sideways"}, {"request_id": "x" * 65}])
def test_event_validation_422(client, params):
    tok = _tok(client)
    assert client.get("/db-logs", params=params, headers=auth_headers(tok, "g")).status_code == 422


@pytest.mark.parametrize("params", [{"outcome": "exploded"}, {"limit": 0}, {"offset": -3}])
def test_request_validation_422(client, params):
    tok = _tok(client)
    assert client.get("/db-logs/requests", params=params, headers=auth_headers(tok, "g")).status_code == 422


def test_sql_injection_in_filters_is_just_a_non_matching_string(client):
    tok = _tok(client)
    assert _events(client, tok, operation="x'; DROP TABLE txn_log; --") == []


def test_db_logs_require_authentication(client):
    assert client.get("/db-logs").status_code == 401 and client.get("/db-logs/requests").status_code == 401


# ---- X-Request-ID ------------------------------------------------------------------------------------------------
def test_request_id_header_is_always_present_and_unique(client):
    ids = {client.get("/health").headers["X-Request-ID"], client.get("/health").headers["X-Request-ID"], client.get("/db-logs").headers["X-Request-ID"]}  # 401 too
    assert len(ids) == 3 and all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


def test_safe_incoming_request_id_is_honoured_and_logged(client):
    tok = _tok(client)
    r = _sell(client, tok, _product(client, tok), 1, "s1", **{"X-Request-ID": "trace-abc_123.xyz"})
    assert r.headers["X-Request-ID"] == "trace-abc_123.xyz"
    assert len(_events(client, tok, request_id="trace-abc_123.xyz")) == 2


@pytest.mark.parametrize("evil", ["x'; DROP TABLE txn_log;--", "short", "a" * 200, "<script>alert(1)</script>", "bad id with spaces"])
def test_unsafe_incoming_request_id_is_ignored(client, evil):
    tok = _tok(client)
    r = client.get("/products", headers={**auth_headers(tok, "g"), "X-Request-ID": evil})
    assert r.headers["X-Request-ID"] != evil and re.fullmatch(r"[0-9a-f]{32}", r.headers["X-Request-ID"])


def test_idempotent_replay_does_not_log_twice(client):
    tok = _tok(client)
    mug = _product(client, tok)
    first = _sell(client, tok, mug, 1, "same-key")
    second = _sell(client, tok, mug, 1, "same-key")
    assert second.status_code == 201 and second.json() == first.json()
    assert second.headers["X-Request-ID"] != first.headers["X-Request-ID"]  # a new HTTP request, but no new transaction
    assert len(_events(client, tok, step="committed")) == 1


# ---- structure guards --------------------------------------------------------------------------------------------
def test_every_router_uses_the_function_scoped_db_dependency():
    """`Depends(get_db)` would run commit/rollback + the log flush AFTER the response was sent (FastAPI default scope)."""
    offenders = [p.name for p in ROUTERS.glob("*_router.py") if re.search(r"Depends\(\s*get_db\s*\)", p.read_text())]
    assert not offenders, offenders
    deps = (ROUTERS / "deps.py").read_text()
    assert 'DB = Depends(get_db, scope="function")' in deps


def test_commit_and_log_flush_happen_before_the_response_is_sent(sql_store):
    """The log row exists the moment the client has the response (no race for the Activity page)."""
    with TestClient(app) as client:
        tok = _tok(client, "order@example.com")
        mug = _product(client, tok)
        r = _sell(client, tok, mug, 1, "s1")
        assert [row["step"] for row in sql_store.txn_log if row["request_id"] == r.headers["X-Request-ID"]] == ["txn_started", "committed"]
        assert sql_store.products[mug["id"]]["stock_qty"] == 4
