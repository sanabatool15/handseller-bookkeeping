"""F4 over HTTP (in-memory fakes): expenses move cash, amount edits post adjustments, cash filters/summary, product delete 409."""
import datetime as dt

from tests.integration.conftest import auth_headers, register_and_login


def _tok(client, email):
    return register_and_login(client, email)["access_token"]


def _get(client, tok, path):
    return client.get(path, headers=auth_headers(tok, "u"))


def _exp(client, tok, amount, key, **extra):
    return client.post("/expenses", json={"amount": amount, "category": "rent", **extra}, headers=auth_headers(tok, key))


def _sale(client, tok, amount, key):
    return client.post("/sales", json={"amount": amount, "category": "retail"}, headers=auth_headers(tok, key))


def _balance(client, tok):
    return _get(client, tok, "/cash/balance").json()["balance"]


def test_expense_reduces_balance_and_writes_ledger_row(client):
    tok = _tok(client, "x1@example.com")
    assert _sale(client, tok, 100, "s1").status_code == 201
    r = _exp(client, tok, 30, "e1", voucher_reference="V-1")
    assert r.status_code == 201 and r.json()["amount"] == 30.0 and r.json()["voucher_reference"] == "V-1"
    assert _balance(client, tok) == 70.0
    row = _get(client, tok, "/cash/ledger?entry_type=expense").json()[0]
    assert row["amount"] == -30.0 and row["balance_after"] == 70.0 and row["ref_id"] == r.json()["id"] and row["ref_type"] == "expense"


def test_negative_balance_is_allowed(client):
    tok = _tok(client, "x2@example.com")
    assert _exp(client, tok, 12.5, "e1").status_code == 201
    assert _balance(client, tok) == -12.5


def test_delete_expense_restores_balance(client):
    tok = _tok(client, "x3@example.com")
    _sale(client, tok, 100, "s1")
    exp = _exp(client, tok, 30, "e1").json()
    assert client.delete(f"/expenses/{exp['id']}", headers=auth_headers(tok, "d1")).status_code == 204
    assert _balance(client, tok) == 100.0
    assert [e["entry_type"] for e in _get(client, tok, "/cash/ledger").json()] == ["expense_void", "expense", "sale"]
    assert _get(client, tok, f"/expenses/{exp['id']}").status_code == 404
    assert client.delete(f"/expenses/{exp['id']}", headers=auth_headers(tok, "d2")).status_code == 404


def test_put_amount_on_expense_and_sale_posts_the_right_delta(client):
    tok = _tok(client, "x4@example.com")
    sale = _sale(client, tok, 50, "s1").json()
    exp = _exp(client, tok, 20, "e1").json()
    assert _balance(client, tok) == 30.0
    r = client.put(f"/expenses/{exp['id']}", json={"amount": 25, "description": "bigger"}, headers=auth_headers(tok, "p1"))
    assert r.status_code == 200 and r.json()["amount"] == 25.0 and r.json()["description"] == "bigger"
    assert _balance(client, tok) == 25.0
    r = client.put(f"/sales/{sale['id']}", json={"amount": 60, "category": "market"}, headers=auth_headers(tok, "p2"))
    assert r.status_code == 200 and r.json()["amount"] == 60.0 and r.json()["category"] == "market"
    assert _balance(client, tok) == 35.0
    adj = _get(client, tok, "/cash/ledger?entry_type=adjustment").json()
    assert sorted((a["ref_type"], a["amount"]) for a in adj) == [("expense", -5.0), ("sale", 10.0)]
    assert sorted(a["balance_after"] for a in adj) == [25.0, 35.0]
    # metadata only: no new ledger row
    client.put(f"/expenses/{exp['id']}", json={"category": "fees"}, headers=auth_headers(tok, "p3"))
    assert len(_get(client, tok, "/cash/ledger?entry_type=adjustment").json()) == 2


def test_item_sale_amount_edit_is_422_and_other_fields_still_work(client):
    tok = _tok(client, "x5@example.com")
    p = client.post("/products", json={"name": "Mug", "sku": "M", "price": 10, "stock_qty": 5}, headers=auth_headers(tok, "pp")).json()
    sale = client.post("/sales", json={"items": [{"product_id": p["id"], "quantity": 1}]}, headers=auth_headers(tok, "s1")).json()
    assert client.put(f"/sales/{sale['id']}", json={"amount": 1}, headers=auth_headers(tok, "u1")).status_code == 422
    assert client.put(f"/sales/{sale['id']}", json={"amount": 1, "description": "x"}, headers=auth_headers(tok, "u2")).status_code == 422
    assert _get(client, tok, f"/sales/{sale['id']}").json()["description"] is None  # nothing half-applied
    assert _balance(client, tok) == 10.0


def test_cross_tenant_404_on_every_expense_verb(client):
    a, b = _tok(client, "xa@example.com"), _tok(client, "xb@example.com")
    exp = _exp(client, a, 80, "e1").json()
    assert _get(client, b, f"/expenses/{exp['id']}").status_code == 404
    assert client.put(f"/expenses/{exp['id']}", json={"amount": 1}, headers=auth_headers(b, "x1")).status_code == 404
    assert client.put(f"/expenses/{exp['id']}", json={"category": "z"}, headers=auth_headers(b, "x2")).status_code == 404
    assert client.delete(f"/expenses/{exp['id']}", headers=auth_headers(b, "x3")).status_code == 404
    assert _get(client, a, f"/expenses/{exp['id']}").json()["amount"] == 80.0
    assert _balance(client, a) == -80.0 and _balance(client, b) == 0.0 and _get(client, b, "/cash/ledger").json() == []
    sale = _sale(client, a, 10, "s1").json()
    assert client.put(f"/sales/{sale['id']}", json={"amount": 5}, headers=auth_headers(b, "x4")).status_code == 404
    assert _balance(client, a) == -70.0


def test_expense_validation_and_idempotency(client):
    tok = _tok(client, "x6@example.com")
    for i, body in enumerate([{"amount": 0}, {"amount": -3}, {"amount": 1e13}, {"category": "x"}, {"amount": 1, "category": "c" * 101}]):
        assert client.post("/expenses", json=body, headers=auth_headers(tok, f"bad{i}")).status_code == 422, body
    exp = _exp(client, tok, 10, "e1").json()
    assert client.put(f"/expenses/{exp['id']}", json={"amount": 0}, headers=auth_headers(tok, "b1")).status_code == 422
    r1, r2 = _exp(client, tok, 7, "same"), _exp(client, tok, 7, "same")
    assert r1.status_code == r2.status_code == 201 and r1.json() == r2.json()
    assert _balance(client, tok) == -17.0  # 10 + 7, the replay did not post twice
    assert client.post("/expenses", json={"amount": 1}, headers={"Authorization": f"Bearer {tok}"}).status_code == 400
    assert client.delete(f"/expenses/{exp['id']}", headers={"Authorization": f"Bearer {tok}"}).status_code == 204  # DELETE needs no key


def test_product_with_sales_cannot_be_deleted_409_but_unsold_can(client):
    tok = _tok(client, "x7@example.com")
    sold = client.post("/products", json={"name": "Mug", "sku": "M", "price": 10, "stock_qty": 5}, headers=auth_headers(tok, "p1")).json()
    unsold = client.post("/products", json={"name": "Pen", "sku": "P", "price": 1, "stock_qty": 5}, headers=auth_headers(tok, "p2")).json()
    sale = client.post("/sales", json={"items": [{"product_id": sold["id"], "quantity": 1}]}, headers=auth_headers(tok, "s1")).json()
    r = client.delete(f"/products/{sold['id']}", headers=auth_headers(tok, "d1"))
    assert r.status_code == 409 and r.json()["detail"] == "Product has sales and cannot be deleted; deactivate it instead"
    assert _get(client, tok, f"/products/{sold['id']}").status_code == 200
    assert client.put(f"/products/{sold['id']}", json={"is_active": False}, headers=auth_headers(tok, "u1")).json()["is_active"] is False
    assert client.delete(f"/products/{unsold['id']}", headers=auth_headers(tok, "d2")).status_code == 204
    # once the sale is voided nothing references the product any more
    client.delete(f"/sales/{sale['id']}", headers=auth_headers(tok, "d3"))
    assert client.delete(f"/products/{sold['id']}", headers=auth_headers(tok, "d4")).status_code == 204


def test_cash_ledger_filters_over_http(client, sql_store):
    from tests.fake_repos import post_cash

    tok = _tok(client, "x8@example.com")
    org = next(iter(sql_store.orgs))
    post_cash(sql_store, org, "sale", 100.0, "sale", "a", "u", "2026-01-10")
    post_cash(sql_store, org, "expense", -20.0, "expense", "b", "u", "2026-01-20")
    post_cash(sql_store, org, "sale", 50.0, "sale", "c", "u", "2026-02-05")
    amounts = lambda q: [e["amount"] for e in _get(client, tok, f"/cash/ledger{q}").json()]  # noqa: E731
    assert amounts("?entry_type=sale") == [50.0, 100.0]
    assert amounts("?from=2026-01-15") == [50.0, -20.0]
    assert amounts("?to=2026-01-20") == [-20.0, 100.0]
    assert amounts("?entry_type=sale&from=2026-01-01&to=2026-01-31") == [100.0]
    assert amounts("?entry_type=expense_void") == []
    assert _get(client, tok, "/cash/ledger?entry_type=bogus").status_code == 422
    assert _get(client, tok, "/cash/ledger?from=not-a-date").status_code == 422
    assert _get(client, tok, "/cash/ledger?from=2026-02-01&to=2026-01-01").status_code == 422
    assert client.get("/cash/ledger?entry_type=sale").status_code == 401


def test_cash_summary_endpoint(client, sql_store):
    from tests.fake_repos import post_cash

    tok = _tok(client, "x9@example.com")
    other = _tok(client, "x10@example.com")
    org = next(o for o in sql_store.orgs)  # first registered org belongs to x9
    post_cash(sql_store, org, "sale", 100.0, "sale", "a", "u", "2026-01-10")
    post_cash(sql_store, org, "sale", 60.0, "sale", "b", "u", "2026-02-10")
    post_cash(sql_store, org, "expense", -10.0, "expense", "c", "u", "2026-02-11")
    s = _get(client, tok, "/cash/summary?year=2026&month=2").json()
    assert (s["opening_balance"], s["total_in"], s["total_out"], s["closing_balance"]) == (100.0, 60.0, 10.0, 150.0)
    assert s["by_type"]["sale"] == 60.0 and s["by_type"]["expense"] == -10.0 and s["by_type"]["adjustment"] == 0.0
    empty = _get(client, tok, "/cash/summary?year=2026&month=7").json()
    assert empty["opening_balance"] == empty["closing_balance"] == 150.0 and empty["total_in"] == empty["total_out"] == 0.0
    assert _get(client, other, "/cash/summary?year=2026&month=2").json()["closing_balance"] == 0.0  # tenant isolation
    assert _get(client, tok, "/cash/summary?year=2026&month=13").status_code == 422
    assert _get(client, tok, "/cash/summary?year=abc").status_code == 422
    this = dt.datetime.now(dt.timezone.utc)
    cur = _get(client, tok, "/cash/summary").json()
    assert (cur["year"], cur["month"]) == (this.year, this.month)
    assert client.get("/cash/summary").status_code == 401
