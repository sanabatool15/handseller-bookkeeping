"""Prompt v1 — Scenario 5: auth and input-validation edge cases.

Covers the registration/login/mutation edges implied by `AuthError` and
`ValidationError` handling in `services/*_service.py` and the auth
dependency in `routers/deps.py`, as one sweep of a new user's early
mistakes (duplicate signup, wrong password, unauthenticated access, bad
input, bad token).
"""
from __future__ import annotations

from tests.integration.conftest import auth_headers, register_and_login


def test_duplicate_email_registration_rejected(client):
    register_and_login(client, email="sbatool6678@gmail.com")

    resp = client.post(
        "/auth/register",
        json={
            "email": "sbatool6678@gmail.com",
            "password": "anotherpass1",
            "full_name": "Someone Else",
            "org_name": "Another Co",
        },
        headers={"Idempotency-Key": "dup-register-2"},
    )
    assert resp.status_code == 409


def test_login_with_wrong_password_rejected(client):
    register_and_login(client, email="wrongpass@example.com")

    resp = client.post(
        "/auth/login",
        json={"email": "sbatool6678@gmail.com", "password": "not-the-right-password"},
        headers={"Idempotency-Key": "wrongpass-login"},
    )
    assert resp.status_code == 401


def test_unauthenticated_request_to_protected_routes_rejected(client):
    assert client.get("/sales").status_code == 401
    assert client.get("/expenses").status_code == 401
    assert client.post(
        "/agent-jobs/financial-advice", headers={"Idempotency-Key": "no-auth-job"}
    ).status_code == 401


def test_malformed_bearer_token_rejected(client):
    resp = client.get(
        "/sales",
        headers={"Authorization": "Bearer not-a-real-token", "Idempotency-Key": "unused"},
    )
    assert resp.status_code == 401


def test_non_positive_sale_and_expense_amounts_rejected(client):
    org = register_and_login(client, email="validation@example.com")
    token = org["access_token"]

    bad_sale = client.post(
        "/sales", json={"amount": 0, "category": "retail"}, headers=auth_headers(token, "bad-sale")
    )
    assert bad_sale.status_code == 422

    bad_expense = client.post(
        "/expenses", json={"amount": -5.0, "category": "supplies"}, headers=auth_headers(token, "bad-expense")
    )
    assert bad_expense.status_code == 422
