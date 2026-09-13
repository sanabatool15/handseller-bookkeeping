from tests.integration.conftest import auth_headers, register_and_login


def test_missing_idempotency_key_rejected(client):
    org = register_and_login(client, email="idem1@example.com")
    resp = client.post(
        "/sales",
        json={"amount": 20.0, "category": "retail"},
        headers={"Authorization": f"Bearer {org['access_token']}"},
    )
    assert resp.status_code == 400


def test_repeated_idempotency_key_returns_cached_response_without_duplicate_row(client):
    org = register_and_login(client, email="idem2@example.com")
    headers = auth_headers(org["access_token"], "same-key-123")

    first = client.post("/sales", json={"amount": 30.0, "category": "retail"}, headers=headers)
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post("/sales", json={"amount": 30.0, "category": "retail"}, headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] == first_id  # same cached response, not a new row

    listing = client.get("/sales", headers=auth_headers(org["access_token"], "unused"))
    matching = [s for s in listing.json() if s["id"] == first_id]
    assert len(matching) == 1  # only one row was ever actually created
