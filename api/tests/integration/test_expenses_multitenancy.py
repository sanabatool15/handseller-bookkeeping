from tests.integration.conftest import auth_headers, register_and_login


def test_expense_created_by_org_a_not_visible_to_org_b(client):
    org_a = register_and_login(client, email="ea@example.com")
    org_b = register_and_login(client, email="eb@example.com")
    token_a, token_b = org_a["access_token"], org_b["access_token"]

    created = client.post("/expenses", json={"amount": 80.0, "category": "rent"}, headers=auth_headers(token_a, "exp-create-1"))
    assert created.status_code == 201
    expense_id = created.json()["id"]

    assert client.get(f"/expenses/{expense_id}", headers=auth_headers(token_a, "u")).status_code == 200

    # Cross-tenant => 404 (never 403: 403 would leak that the record exists), and nothing changed.
    assert client.get(f"/expenses/{expense_id}", headers=auth_headers(token_b, "u")).status_code == 404
    put_b = client.put(f"/expenses/{expense_id}", json={"amount": 1.0}, headers=auth_headers(token_b, "exp-upd-x"))
    assert put_b.status_code == 404
    assert client.delete(f"/expenses/{expense_id}", headers=auth_headers(token_b, "u")).status_code == 404

    still = client.get(f"/expenses/{expense_id}", headers=auth_headers(token_a, "u")).json()
    assert still["amount"] == 80.0

    assert client.get("/expenses", headers=auth_headers(token_b, "u")).json() == []
    assert all(e["org_id"] == org_a["org"]["id"] for e in client.get("/expenses", headers=auth_headers(token_a, "u")).json())


def test_expense_update_and_delete_by_owner(client):
    org = register_and_login(client, email="eo@example.com")
    h = lambda k: auth_headers(org["access_token"], k)  # noqa: E731
    exp = client.post("/expenses", json={"amount": 10.0, "category": "rent", "voucher_reference": "V-1"}, headers=h("e1")).json()
    upd = client.put(f"/expenses/{exp['id']}", json={"amount": 12.5}, headers=h("e2"))
    assert upd.status_code == 200 and upd.json()["amount"] == 12.5 and upd.json()["voucher_reference"] == "V-1"
    assert client.delete(f"/expenses/{exp['id']}", headers=h("e3")).status_code == 204
    assert client.get(f"/expenses/{exp['id']}", headers=h("u")).status_code == 404


def test_expense_validation_rejects_non_positive_amount(client):
    org = register_and_login(client, email="ev@example.com")
    r = client.post("/expenses", json={"amount": 0, "category": "rent"}, headers=auth_headers(org["access_token"], "ev-1"))
    assert r.status_code == 422
    r2 = client.post("/expenses", json={"category": "rent"}, headers=auth_headers(org["access_token"], "ev-2"))
    assert r2.status_code == 422  # missing amount
