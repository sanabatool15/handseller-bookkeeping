"""Prompt v1 — Scenario 3: idempotent retry of a flaky mobile client.

Simulates the exact scenario `specs/04-idempotency-redis.md` calls out: a
handseller on a bad connection retries a "log this sale" POST. Covers the
cached-replay path, the missing-header rejection, and per-org key scoping
(same key, different orgs, must not collide) in one journey.
"""
from __future__ import annotations

from tests.integration.conftest import auth_headers, register_and_login


def test_retried_sale_submission_is_not_double_recorded(client):
    org = register_and_login(client, email="flaky-client@example.com")
    token = org["access_token"]
    headers = auth_headers(token, "flaky-retry-key")

    first = client.post("/sales", json={"amount": 75.0, "category": "retail"}, headers=headers)
    assert first.status_code == 201
    sale_id = first.json()["id"]

    # Client believes the first response was lost and retries with the SAME key.
    second = client.post("/sales", json={"amount": 75.0, "category": "retail"}, headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] == sale_id  # cached response replayed, not a new row

    listing = client.get("/sales", headers=auth_headers(token, "unused")).json()
    assert len([s for s in listing if s["id"] == sale_id]) == 1


def test_missing_idempotency_key_rejected_on_mutating_endpoint(client):
    org = register_and_login(client, email="no-key-client@example.com")
    resp = client.post(
        "/expenses",
        json={"amount": 15.0, "category": "supplies"},
        headers={"Authorization": f"Bearer {org['access_token']}"},
    )
    assert resp.status_code == 400


def test_same_idempotency_key_does_not_collide_across_orgs(client):
    org_a = register_and_login(client, email="idem-org-a@example.com")
    org_b = register_and_login(client, email="idem-org-b@example.com")

    resp_a = client.post(
        "/sales",
        json={"amount": 200.0, "category": "retail"},
        headers=auth_headers(org_a["access_token"], "shared-key-across-orgs"),
    )
    resp_b = client.post(
        "/sales",
        json={"amount": 300.0, "category": "retail"},
        headers=auth_headers(org_b["access_token"], "shared-key-across-orgs"),
    )

    assert resp_a.status_code == 201
    assert resp_b.status_code == 201
    assert resp_a.json()["id"] != resp_b.json()["id"]
    assert resp_a.json()["amount"] == 200.0
    assert resp_b.json()["amount"] == 300.0  # org B was not served org A's cached response
