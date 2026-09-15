from tests.integration.conftest import auth_headers, register_and_login


def test_sale_created_by_org_a_not_visible_to_org_b(client):
    org_a = register_and_login(client, email="a@example.com")
    org_b = register_and_login(client, email="b@example.com")

    token_a = org_a["access_token"]
    token_b = org_b["access_token"]

    create_resp = client.post(
        "/sales",
        json={"amount": 150.0, "category": "retail"},
        headers=auth_headers(token_a, "sale-create-1"),
    )
    assert create_resp.status_code == 201
    sale_id = create_resp.json()["id"]

    # Org A can fetch it.
    get_a = client.get(f"/sales/{sale_id}", headers=auth_headers(token_a, "unused"))
    assert get_a.status_code == 200

    # Org B must NOT be able to fetch, update, or delete org A's sale.
    get_b = client.get(f"/sales/{sale_id}", headers=auth_headers(token_b, "unused"))
    assert get_b.status_code == 404

    update_b = client.put(
        f"/sales/{sale_id}",
        json={"amount": 999.0},
        headers=auth_headers(token_b, "sale-update-cross-tenant"),
    )
    assert update_b.status_code == 404

    delete_b = client.delete(f"/sales/{sale_id}", headers=auth_headers(token_b, "unused"))
    assert delete_b.status_code == 404

    # Org A's list endpoint never shows org B's data either.
    list_a = client.get("/sales", headers=auth_headers(token_a, "unused"))
    assert all(s["org_id"] == org_a["org"]["id"] for s in list_a.json())


def test_sale_validation_rejects_non_positive_amount(client):
    org = register_and_login(client, email="c@example.com")
    resp = client.post(
        "/sales",
        json={"amount": -1, "category": "retail"},
        headers=auth_headers(org["access_token"], "sale-invalid-1"),
    )
    assert resp.status_code == 422
