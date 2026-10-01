"""DB Lab: gated 404s, validation, and the enabled flows with a deterministic fake lock engine (threads really contend)."""
import pytest

from core.config import get_settings
from services import db_lab_service
from tests.fake_repos import install_db_lab_fakes
from tests.integration.conftest import auth_headers, register_and_login

LAB_ROUTES = [("post", "/db-lab/race-sale", {"product_id": "x"}), ("post", "/db-lab/deadlock", {"product_a": "x", "product_b": "y"}),
              ("post", "/db-lab/deadlock-fixed", {"product_a": "x", "product_b": "y"})]


def _tok(client, email="lab@example.com"):
    return register_and_login(client, email)["access_token"]


def _product(client, tok, sku, stock=1):
    r = client.post("/products", json={"name": sku, "sku": sku, "price": 1.0, "stock_qty": stock}, headers=auth_headers(tok, f"p-{sku}"))
    assert r.status_code == 201, r.text
    return r.json()


def _post(client, tok, path, body, key="k"):
    return client.post(path, json=body, headers=auth_headers(tok, key))


@pytest.fixture
def lab(monkeypatch, sql_store):
    monkeypatch.setattr(db_lab_service, "is_enabled", lambda: True)
    monkeypatch.setattr(get_settings(), "lock_wait_suspect_ms", 10)  # the fake waits are ~40 ms per demo second
    return install_db_lab_fakes(monkeypatch, sql_store)


def _stock(client, tok, product):
    return client.get(f"/products/{product['id']}", headers=auth_headers(tok, "g")).json()["stock_qty"]


# ---- disabled (the default) -------------------------------------------------------------------------------------
def test_lab_is_off_by_default():
    assert get_settings().enable_db_lab is False


def test_disabled_lab_answers_404_everywhere_except_status(client):
    tok = _tok(client)
    for method, path, body in LAB_ROUTES:
        assert _post(client, tok, path, body).status_code == 404, path
        # invalid bodies must not leak the route's existence either
        assert _post(client, tok, path, {"clients": 99, "isolation_level": "NOPE"}).status_code == 404, path
    assert client.get("/db-lab/other", headers=auth_headers(tok, "g")).status_code == 404
    status = client.get("/db-lab/status", headers=auth_headers(tok, "g"))
    assert status.status_code == 200 and status.json() == {"enabled": False}


def test_status_reports_enabled(client, monkeypatch):
    monkeypatch.setattr(db_lab_service, "is_enabled", lambda: True)
    tok = _tok(client)
    assert client.get("/db-lab/status", headers=auth_headers(tok, "g")).json() == {"enabled": True}


def test_status_requires_authentication(client):
    assert client.get("/db-lab/status").status_code == 401


# ---- validation (enabled) ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("patch", [
    {"clients": 1}, {"clients": 11}, {"isolation_level": "CHAOS"}, {"isolation_level": "SERIALIZABLE; DROP TABLE products"},
    {"delay_seconds": 6}, {"delay_seconds": -1}, {"delay_seconds": "1; WAITFOR DELAY '23:00:00'"}, {"mode": "reckless"}, {"quantity": 0}, {"quantity": 11},
])
def test_race_validation_422(client, lab, patch):
    tok = _tok(client)
    p = _product(client, tok, "V1")
    r = _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], **patch})
    assert r.status_code == 422, r.text
    assert _stock(client, tok, p) == 1


def test_deadlock_validation(client, lab):
    tok = _tok(client)
    a = _product(client, tok, "A")
    assert _post(client, tok, "/db-lab/deadlock", {"product_a": a["id"], "product_b": a["id"]}).status_code == 422  # same product
    assert _post(client, tok, "/db-lab/deadlock", {"product_a": a["id"], "product_b": "not-a-uuid"}).status_code == 422
    assert _post(client, tok, "/db-lab/deadlock-fixed", {"product_a": a["id"], "product_b": a["id"], "delay_seconds": 9}).status_code == 422


def test_foreign_and_unknown_products_are_404(client, lab):
    ta, tb = _tok(client, "a@example.com"), _tok(client, "b@example.com")
    mine, theirs = _product(client, ta, "M"), _product(client, tb, "T")
    assert _post(client, ta, "/db-lab/race-sale", {"product_id": theirs["id"]}).status_code == 404
    assert _post(client, ta, "/db-lab/race-sale", {"product_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert _post(client, ta, "/db-lab/deadlock", {"product_a": mine["id"], "product_b": theirs["id"]}).status_code == 404
    assert _stock(client, tb, theirs) == 1  # untouched
    assert lab.connections == [] or all(c.closed for c in lab.connections)


# ---- race: safe vs unsafe ---------------------------------------------------------------------------------------
def test_safe_race_has_exactly_one_winner_for_the_last_unit(client, lab):
    tok = _tok(client)
    p = _product(client, tok, "S1", stock=1)
    r = _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], "clients": 5, "mode": "safe"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["demo_only"] is True and body["mode"] == "safe" and body["isolation_level"] == "READ COMMITTED"
    assert body["summary"] == {"committed": 1, "rejected": 4, "rolled_back": 0, "deadlock_victims": 0, "oversold_units": 0}
    assert body["stock_before"] == 1 and body["stock_after_race"] == 0 and body["restored"] is True and body["stock_after"] == 1
    assert _stock(client, tok, p) == 1  # harmless: put back
    assert sorted(x["client"] for x in body["results"]) == [1, 2, 3, 4, 5]
    assert {x["status"] for x in body["results"]} == {"committed", "rejected"}
    assert all(set(x) >= {"client", "request_id", "status", "retries", "duration_ms", "error_number", "message"} for x in body["results"])
    assert "No oversell" in body["verdict"]


def test_unsafe_race_at_read_committed_oversells_the_last_unit(client, lab):
    tok = _tok(client)
    p = _product(client, tok, "U1", stock=1)
    body = _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], "clients": 3, "mode": "unsafe", "isolation_level": "READ COMMITTED"}).json()
    assert body["summary"]["committed"] == 3 and body["summary"]["oversold_units"] == 2  # 3 sold, 1 existed: lost update
    assert body["stock_after_race"] == 0 and body["stock_after"] == 1 and "OVERSOLD" in body["verdict"]


def test_unsafe_race_at_serializable_is_serialised_and_deadlocks_are_retried(client, lab):
    tok = _tok(client)
    p = _product(client, tok, "U2", stock=1)
    body = _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], "clients": 3, "mode": "unsafe", "isolation_level": "SERIALIZABLE"}).json()
    assert body["summary"]["committed"] == 1 and body["summary"]["oversold_units"] == 0 and body["summary"]["rolled_back"] == 0
    assert body["summary"]["deadlock_victims"] >= 1 and lab.deadlocks >= 1  # the S -> X conversion deadlock
    assert any(x["retries"] >= 1 for x in body["results"]) and body["stock_after_race"] == 0


def test_restore_can_be_switched_off_to_show_the_effect(client, lab):
    tok = _tok(client)
    p = _product(client, tok, "R1", stock=3)
    body = _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], "clients": 2, "restore_stock": False}).json()
    assert body["restored"] is False and body["stock_after"] == 1 == _stock(client, tok, p)


def test_every_client_has_its_own_connection_and_all_are_closed(client, lab):
    tok = _tok(client)
    p = _product(client, tok, "C1", stock=1)
    _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], "clients": 4})
    conns = lab.connections
    assert len(conns) >= 5 and len({id(c) for c in conns}) == len(conns)  # 4 clients + the request's own
    assert all(c.closed for c in conns)
    client_conns = [c for c in conns if c.commits + c.rollbacks > 0 and c.isolation_level == "READ COMMITTED"]
    assert len(client_conns) >= 4


def test_lab_clients_are_logged_like_any_request(client, lab):
    tok = _tok(client)
    p = _product(client, tok, "L1", stock=1)
    body = _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], "clients": 3, "mode": "safe", "isolation_level": "READ COMMITTED"}).json()
    ids = {x["request_id"]: x for x in body["results"]}
    rows = client.get("/db-logs/requests", params={"operation": "lab_race_sale_safe"}, headers=auth_headers(tok, "g")).json()
    assert {r["request_id"] for r in rows} == set(ids)
    outcome = {r["request_id"]: r["outcome"] for r in rows}
    assert sorted(outcome.values()) == ["committed", "rejected", "rejected"]
    for rid, x in ids.items():
        assert outcome[rid] == ("committed" if x["status"] == "committed" else "rejected")
    steps = {e["step"] for e in client.get("/db-logs", params={"operation": "lab_race_sale_safe", "limit": 200}, headers=auth_headers(tok, "g")).json()}
    assert {"txn_started", "committed", "business_rejected", "lock_wait_suspected"} <= steps  # the losers waited behind the lock (inferred)
    events = client.get("/db-logs", params={"request_id": next(iter(ids))}, headers=auth_headers(tok, "g")).json()
    assert {e["isolation_level"] for e in events} == {"READ COMMITTED"}
    # another org sees none of it
    other = _tok(client, "other@example.com")
    assert client.get("/db-logs/requests", headers=auth_headers(other, "g")).json() == []


def test_isolation_level_is_recorded(client, lab):
    tok = _tok(client)
    p = _product(client, tok, "I1", stock=1)
    _post(client, tok, "/db-lab/race-sale", {"product_id": p["id"], "clients": 2, "mode": "unsafe", "isolation_level": "SERIALIZABLE"})
    levels = {e["isolation_level"] for e in client.get("/db-logs", params={"operation": "lab_race_sale_unsafe", "limit": 200}, headers=auth_headers(tok, "g")).json()}
    assert levels == {"SERIALIZABLE"}


# ---- deadlock ---------------------------------------------------------------------------------------------------
def test_opposite_lock_order_deadlocks_one_victim_which_is_retried(client, lab):
    tok = _tok(client)
    a, b = _product(client, tok, "DA", stock=4), _product(client, tok, "DB", stock=7)
    r = _post(client, tok, "/db-lab/deadlock", {"product_a": a["id"], "product_b": b["id"], "delay_seconds": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["deadlock_victims"] == 1 and body["summary"]["committed"] == 2 and body["summary"]["retries"] == 1
    victim = next(x for x in body["results"] if x["error_number"] == 1205)
    assert victim["client"] == 2 and victim["status"] == "committed" and victim["retries"] == 1  # DEADLOCK_PRIORITY LOW client
    assert body["restored"] is True and body["stock_before"] == body["stock_after"] == {a["id"]: 4, b["id"]: 7}
    assert (_stock(client, tok, a), _stock(client, tok, b)) == (4, 7)  # net zero
    assert lab.deadlocks == 1 and "Deadlock" in body["verdict"]
    # the log tells the story of the victim: committed after a deadlock retry
    rid = victim["request_id"]
    steps = [e["step"] for e in client.get("/db-logs", params={"request_id": rid, "order": "asc"}, headers=auth_headers(tok, "g")).json()]
    assert "lock_wait_suspected" in steps  # it waited for the other client's lock before SQL Server chose it as the victim
    steps = [s for s in steps if s != "lock_wait_suspected"]
    assert steps[:4] == ["txn_started", "deadlock_1205_caught", "retry_triggered", "txn_started"] and steps[-1] == "committed"
    summary = client.get("/db-logs/requests", params={"request_id": rid}, headers=auth_headers(tok, "g")).json()[0]
    assert summary["outcome"] == "deadlock_retried" and summary["deadlocks"] == 1 and summary["operation"] == "lab_deadlock"


def test_consistent_lock_order_prevents_the_deadlock(client, lab):
    tok = _tok(client)
    a, b = _product(client, tok, "FA", stock=4), _product(client, tok, "FB", stock=7)
    body = _post(client, tok, "/db-lab/deadlock-fixed", {"product_a": a["id"], "product_b": b["id"]}).json()
    assert body["summary"]["deadlock_victims"] == 0 and body["summary"]["retries"] == 0 and body["summary"]["committed"] == 2
    assert lab.deadlocks == 0 and body["restored"] is True and "prevented" in body["verdict"]
    assert {r["error_number"] for r in body["results"]} == {None}
    ops = {r["operation"] for r in client.get("/db-logs/requests", headers=auth_headers(tok, "g")).json()}
    assert ops == {"lab_deadlock_fixed"}


def test_lab_requires_idempotency_key(client, lab):
    tok = _tok(client)
    r = client.post("/db-lab/deadlock", json={"product_a": "x", "product_b": "y"}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400
