"""Scenario 5: auth and input-validation edge cases, against real Supabase.

Real-infra e2e: registering the same email twice must hit the real `users`
table's uniqueness check (409); wrong password on login is rejected (401);
an unauthenticated request to a protected route is rejected (401); a
non-positive sale/expense amount is rejected by the service layer (422);
and a malformed bearer token is rejected (401). All rows this suite creates
are real and are torn down afterward.
"""
from __future__ import annotations

import uuid


def _unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, cleanup, tag: str, email: str | None = None):
    email = email or _unique_email(tag)
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-1", "full_name": "E2E Tester", "org_name": f"Org-{tag}"},
        headers={"Idempotency-Key": f"reg-{tag}"},
    )
    assert resp.status_code == 201, f"register failed: {resp.status_code} {resp.text}"
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    cleanup.track_row("users", user_id, org_id)
    cleanup.track_row("orgs", org_id)
    return email, body["access_token"], org_id, user_id


def test_duplicate_email_registration_is_rejected(client, cleanup):
    email, _token, _org_id, _user_id = _register(client, cleanup, "dup-email")

    dup = client.post(
        "/auth/register",
        json={"email": email, "password": "some-other-pass", "full_name": "Dup", "org_name": "Dup Co"},
        headers={"Idempotency-Key": "dup-email-attempt"},
    )
    assert dup.status_code == 409, dup.text


def test_login_with_wrong_password_is_rejected(client, cleanup):
    email, _token, _org_id, _user_id = _register(client, cleanup, "wrong-pw")

    bad_login = client.post("/auth/login", json={"email": email, "password": "definitely-not-it"})
    assert bad_login.status_code == 401, bad_login.text


def test_unauthenticated_request_to_protected_route_is_rejected(client):
    resp = client.get("/sales")
    assert resp.status_code == 401, resp.text


def test_malformed_bearer_token_is_rejected(client):
    resp = client.get("/sales", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401, resp.text


def test_non_positive_sale_amount_is_rejected(client, cleanup):
    _email, token, _org_id, _user_id = _register(client, cleanup, "nonpos-sale")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/sales", json={"amount": 0, "category": "retail"},
        headers={**headers, "Idempotency-Key": "nonpos-sale-attempt"},
    )
    assert resp.status_code == 422, resp.text

    resp_negative = client.post(
        "/sales", json={"amount": -5.0, "category": "retail"},
        headers={**headers, "Idempotency-Key": "nonpos-sale-attempt-2"},
    )
    assert resp_negative.status_code == 422, resp_negative.text


def test_non_positive_expense_amount_is_rejected(client, cleanup):
    _email, token, _org_id, _user_id = _register(client, cleanup, "nonpos-expense")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/expenses", json={"amount": 0, "category": "supplies"},
        headers={**headers, "Idempotency-Key": "nonpos-expense-attempt"},
    )
    assert resp.status_code == 422, resp.text
