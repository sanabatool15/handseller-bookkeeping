"""POST /sales with line items, cash endpoints, void via DELETE, tenancy, idempotency (in-memory fakes)."""
import uuid

from tests.integration.conftest import auth_headers, register_and_login


def _setup(client, email="si@example.com"):
    org = register_and_login(client, email)
    return org["access_token"]


def _product(client, tok, sku, stock=5, price=10.0, name="Mug"):
    r = client.post("/products", json={"name": name, "sku": sku, "price": price, "stock_qty": stock}, headers=auth_headers(tok, f"p-{sku}"))
    assert r.status_code == 201, r.text
    return r.json()


def _get(client, tok, path):
    return client.get(path, headers=auth_headers(tok, "u"))


def _sell(client, tok, body, key):
    return client.post("/sales", json=body, headers=auth_headers(tok, key))


def test_commit_with_items_changes_stock_and_balance(client):
    tok = _setup(client)
    mug = _product(client, tok, "M1")
    r = _sell(client, tok, {"category": "retail", "items": [{"product_id": mug["id"], "quantity": 2}]}, "s1")
    assert r.status_code == 201, r.text
    sale = r.json()
    assert sale["amount"] == 20.0 and sale["customer_id"] is None and "skipped_items" not in sale
    item = sale["items"][0]
    assert item["product_id"] == mug["id"] and item["quantity"] == 2 and item["unit_price"] == 10.0 and item["line_total"] == 20.0
    assert item["product_name"] == "Mug" and isinstance(item["id"], str)
    assert _get(client, tok, f"/products/{mug['id']}").json()["stock_qty"] == 3
    assert _get(client, tok, "/cash/balance").json()["balance"] == 20.0
    ledger = _get(client, tok, "/cash/ledger?limit=10&offset=0").json()
    assert len(ledger) == 1 and ledger[0]["entry_type"] == "sale" and ledger[0]["amount"] == 20.0 and ledger[0]["balance_after"] == 20.0
    # GET and list include items
    assert _get(client, tok, f"/sales/{sale['id']}").json()["items"][0]["quantity"] == 2
    assert _get(client, tok, "/sales").json()[0]["items"][0]["product_name"] == "Mug"


def test_insufficient_stock_is_409_and_nothing_changed(client):
    tok = _setup(client, "si2@example.com")
    a, b = _product(client, tok, "A", stock=5), _product(client, tok, "B", stock=1, name="Pen")
    r = _sell(client, tok, {"items": [{"product_id": a["id"], "quantity": 2}, {"product_id": b["id"], "quantity": 3}]}, "s1")
    assert r.status_code == 409 and "Pen" in r.json()["detail"]
    assert _get(client, tok, f"/products/{a['id']}").json()["stock_qty"] == 5
    assert _get(client, tok, f"/products/{b['id']}").json()["stock_qty"] == 1
    assert _get(client, tok, "/sales").json() == []
    assert _get(client, tok, "/cash/balance").json()["balance"] == 0.0 and _get(client, tok, "/cash/ledger").json() == []


def test_partial_with_skip_invalid_items(client):
    tok = _setup(client, "si3@example.com")
    a, b = _product(client, tok, "A"), _product(client, tok, "B", stock=0, name="Pen")
    r = _sell(client, tok, {"skip_invalid_items": True, "items": [{"product_id": a["id"], "quantity": 1}, {"product_id": b["id"], "quantity": 1}]}, "s1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["items"]) == 1 and body["amount"] == 10.0
    assert body["skipped_items"][0]["product_id"] == b["id"] and "Pen" in body["skipped_items"][0]["reason"]
    assert _get(client, tok, "/cash/balance").json()["balance"] == 10.0


def test_foreign_product_is_404(client):
    a, b = _setup(client, "sa@example.com"), _setup(client, "sb@example.com")
    foreign = _product(client, a, "F")
    r = _sell(client, b, {"items": [{"product_id": foreign["id"], "quantity": 1}]}, "s1")
    assert r.status_code == 404 and r.json()["detail"] == "Product not found"
    assert _get(client, a, f"/products/{foreign['id']}").json()["stock_qty"] == 5
    assert _sell(client, b, {"items": [{"product_id": str(uuid.uuid4()), "quantity": 1}]}, "s2").status_code == 404


def test_cross_tenant_get_and_delete_sale_are_404_and_cash_is_private(client):
    a, b = _setup(client, "ta@example.com"), _setup(client, "tb@example.com")
    p = _product(client, a, "P")
    sale = _sell(client, a, {"items": [{"product_id": p["id"], "quantity": 1}]}, "s1").json()
    assert _get(client, b, f"/sales/{sale['id']}").status_code == 404
    assert client.delete(f"/sales/{sale['id']}", headers=auth_headers(b, "d")).status_code == 404
    assert _get(client, a, f"/sales/{sale['id']}").status_code == 200  # untouched
    assert _get(client, a, f"/products/{p['id']}").json()["stock_qty"] == 4
    assert _get(client, b, "/cash/balance").json()["balance"] == 0.0 and _get(client, b, "/cash/ledger").json() == []
    assert _get(client, a, "/cash/balance").json()["balance"] == 10.0


def test_void_restores_stock_and_balance(client):
    tok = _setup(client, "v@example.com")
    p = _product(client, tok, "P")
    sale = _sell(client, tok, {"items": [{"product_id": p["id"], "quantity": 3}]}, "s1").json()
    assert client.delete(f"/sales/{sale['id']}", headers=auth_headers(tok, "d1")).status_code == 204
    assert _get(client, tok, f"/products/{p['id']}").json()["stock_qty"] == 5
    assert _get(client, tok, "/cash/balance").json()["balance"] == 0.0
    assert [e["entry_type"] for e in _get(client, tok, "/cash/ledger").json()] == ["sale_void", "sale"]
    assert _get(client, tok, f"/sales/{sale['id']}").status_code == 404
    assert client.delete(f"/sales/{sale['id']}", headers=auth_headers(tok, "d2")).status_code == 404


def test_backcompat_plain_sale(client):
    tok = _setup(client, "bc@example.com")
    r = _sell(client, tok, {"amount": 12.5, "category": "retail", "customer_name": "Zed"}, "s1")
    assert r.status_code == 201 and r.json()["amount"] == 12.5 and r.json()["items"] == [] and r.json()["customer_name"] == "Zed"
    assert _get(client, tok, "/cash/balance").json()["balance"] == 12.5
    up = client.put(f"/sales/{r.json()['id']}", json={"amount": 15}, headers=auth_headers(tok, "u1"))
    assert up.status_code == 200 and up.json()["amount"] == 15 and up.json()["items"] == []


def test_put_amount_on_item_sale_is_422(client):
    tok = _setup(client, "pu@example.com")
    p = _product(client, tok, "P")
    sale = _sell(client, tok, {"items": [{"product_id": p["id"], "quantity": 1}]}, "s1").json()
    assert client.put(f"/sales/{sale['id']}", json={"amount": 1}, headers=auth_headers(tok, "u1")).status_code == 422
    ok = client.put(f"/sales/{sale['id']}", json={"description": "gift"}, headers=auth_headers(tok, "u2"))
    assert ok.status_code == 200 and ok.json()["description"] == "gift" and ok.json()["amount"] == 10.0


def test_validation_422(client):
    tok = _setup(client, "val@example.com")
    p = _product(client, tok, "P")
    for i, body in enumerate([
        {},                                                                    # neither amount nor items
        {"amount": 0},
        {"items": [{"product_id": p["id"], "quantity": 0}]},
        {"items": [{"product_id": p["id"], "quantity": -2}]},
        {"items": [{"product_id": p["id"], "quantity": 1, "unit_price": -1}]},
        {"items": [{"product_id": "not-a-uuid", "quantity": 1}]},
        {"items": [{"quantity": 1}]},
    ]):
        r = _sell(client, tok, body, f"bad-{i}")
        assert r.status_code == 422, (body, r.text)
    assert _get(client, tok, f"/products/{p['id']}").json()["stock_qty"] == 5


def test_idempotent_replay_does_not_sell_twice(client):
    tok = _setup(client, "id@example.com")
    p = _product(client, tok, "P")
    body = {"items": [{"product_id": p["id"], "quantity": 1}]}
    r1, r2 = _sell(client, tok, body, "same-key"), _sell(client, tok, body, "same-key")
    assert r1.status_code == r2.status_code == 201 and r1.json() == r2.json()
    assert _get(client, tok, f"/products/{p['id']}").json()["stock_qty"] == 4
    assert _get(client, tok, "/cash/balance").json()["balance"] == 10.0
    assert client.post("/sales", json=body, headers={"Authorization": f"Bearer {tok}"}).status_code == 400  # key required


def test_cash_balance_for_new_org_is_zero_and_unauthenticated_is_401(client):
    tok = _setup(client, "cz@example.com")
    assert _get(client, tok, "/cash/balance").json() == {"balance": 0.0, "updated_at": None}
    assert client.get("/cash/balance").status_code == 401
