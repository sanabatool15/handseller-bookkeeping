import uuid


def test_create_sale_requires_idempotency_key(client, auth_headers):
    resp = client.post(
        "/sales",
        json={"amount": 100, "sale_date": "2026-01-05"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "Idempotency-Key" in resp.json()["detail"]


def test_create_sale_success(client, auth_headers):
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    resp = client.post(
        "/sales",
        json={"amount": 100.5, "sale_date": "2026-01-05", "voucher_reference": "V-1"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["amount"] == 100.5
    assert body["voucher_reference"] == "V-1"


def test_create_sale_missing_field_returns_422(client, auth_headers):
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    resp = client.post("/sales", json={"sale_date": "2026-01-05"}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Validation failed"


def test_create_expense_success_and_report(client, auth_headers):
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    resp = client.post(
        "/expenses",
        json={"amount": 40, "category": "raw materials", "expense_date": "2026-02-10"},
        headers=headers,
    )
    assert resp.status_code == 201

    headers2 = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    client.post(
        "/sales", json={"amount": 100, "sale_date": "2026-02-11"}, headers=headers2
    )

    report_resp = client.get("/reports/monthly?month=2&year=2026", headers=auth_headers)
    assert report_resp.status_code == 200
    data = report_resp.json()
    assert data["total_sales"] == 100
    assert data["total_expenses"] == 40
    assert data["net_profit_loss"] == 60
    assert data["is_profitable"] is True


def test_expense_breakdown(client, auth_headers):
    for cat, amount in [("raw materials", 50), ("packaging", 10), ("raw materials", 20)]:
        headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
        client.post(
            "/expenses",
            json={"amount": amount, "category": cat, "expense_date": "2026-03-01"},
            headers=headers,
        )

    resp = client.get("/reports/expense-breakdown?month=3&year=2026", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_expenses"] == 80
    assert data["top_cost_drivers"][0] == "raw materials"


def test_idempotency_replay_returns_cached_response(client, auth_headers):
    key = str(uuid.uuid4())
    headers = {**auth_headers, "Idempotency-Key": key}
    payload = {"amount": 25, "sale_date": "2026-04-01"}

    first = client.post("/sales", json=payload, headers=headers)
    assert first.status_code == 201

    second = client.post(
        "/sales", json={"amount": 999, "sale_date": "2099-01-01"}, headers=headers
    )
    assert second.status_code == 201
    assert second.json() == first.json()


def test_sale_not_found_returns_404(client, auth_headers):
    resp = client.get(f"/sales/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


def test_missing_auth_returns_401(client):
    resp = client.get("/sales/some-id")
    assert resp.status_code == 401


def test_org_scoping_blocks_cross_tenant_access(client, auth_headers, fake_supabase):
    """A sale created under org A must not be readable via a token for org B,
    even if the attacker guesses the sale id (structural org_id scoping)."""
    headers = {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}
    create_resp = client.post(
        "/sales", json={"amount": 77, "sale_date": "2026-05-01"}, headers=headers
    )
    sale_id = create_resp.json()["id"]

    # Build a second token for a different, unrelated org/user with no membership seeded.
    import jwt

    from app.core.config import get_settings

    settings = get_settings()
    other_org_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    fake_supabase.table("orgs").insert(
        {"id": other_org_id, "owner_id": other_user_id, "name": "Other Org"}
    ).execute()
    other_token = jwt.encode(
        {"sub": other_user_id, "org_id": other_org_id},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    resp = client.get(f"/sales/{sale_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 404
