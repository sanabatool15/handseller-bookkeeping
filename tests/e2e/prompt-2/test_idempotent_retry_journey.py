"""Scenario 3: idempotent retry of a flaky mobile client, against real Redis.

Real-infra e2e: exercises `middleware/idempotency.py` against the real Redis
instance configured via REDIS_URL (no fakeredis). Covers:
  (a) same Idempotency-Key posted twice -> exactly one `sales` row created,
      second response is the cached replay of the first.
  (b) missing Idempotency-Key header on a mutating request -> 400.
  (c) same Idempotency-Key reused across two different orgs -> no cross-org
      cache collision (each org gets its own row; keys are scoped
      `idempotency:{org_id}:{key}`).
"""
from __future__ import annotations

import uuid


def _unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, cleanup, tag: str):
    email = _unique_email(tag)
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
    return body["access_token"], org_id, user_id


def test_same_key_retried_creates_exactly_one_row_and_replays_response(client, cleanup):
    token, org_id, _ = _register(client, cleanup, "idem-retry")
    headers = {"Authorization": f"Bearer {token}"}
    idem_key = f"retry-{uuid.uuid4().hex[:8]}"

    first = client.post(
        "/sales", json={"amount": 42.0, "category": "retail"},
        headers={**headers, "Idempotency-Key": idem_key},
    )
    assert first.status_code == 201, first.text
    sale_id = first.json()["id"]
    cleanup.track_row("sales", sale_id, org_id)

    # Simulate the client not seeing the first response and retrying with
    # the exact same key.
    second = client.post(
        "/sales", json={"amount": 42.0, "category": "retail"},
        headers={**headers, "Idempotency-Key": idem_key},
    )
    assert second.status_code == 201, second.text
    assert second.json() == first.json(), "retry must replay the exact cached response, not re-run the handler"

    all_sales = client.get("/sales", headers=headers).json()
    matching = [s for s in all_sales if s["id"] == sale_id]
    assert len(matching) == 1, "retry with the same Idempotency-Key must not create a second row"


def test_missing_idempotency_key_is_rejected(client, cleanup):
    token, org_id, _ = _register(client, cleanup, "idem-missing")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/sales", json={"amount": 10.0, "category": "retail"}, headers=headers)
    assert resp.status_code == 400, resp.text
    assert "Idempotency-Key" in resp.text


def test_same_key_across_two_orgs_does_not_collide(client, cleanup):
    token_a, org_a, _ = _register(client, cleanup, "idem-org-a")
    token_b, org_b, _ = _register(client, cleanup, "idem-org-b")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    shared_key = f"shared-{uuid.uuid4().hex[:8]}"

    resp_a = client.post(
        "/sales", json={"amount": 11.0, "category": "retail"},
        headers={**headers_a, "Idempotency-Key": shared_key},
    )
    assert resp_a.status_code == 201, resp_a.text
    sale_a_id = resp_a.json()["id"]
    cleanup.track_row("sales", sale_a_id, org_a)

    resp_b = client.post(
        "/sales", json={"amount": 22.0, "category": "wholesale"},
        headers={**headers_b, "Idempotency-Key": shared_key},
    )
    assert resp_b.status_code == 201, resp_b.text
    sale_b_id = resp_b.json()["id"]
    cleanup.track_row("sales", sale_b_id, org_b)

    # Different orgs, same key -> must be two distinct rows with the values
    # each org actually posted, not org A's cached response replayed for B.
    assert sale_a_id != sale_b_id
    assert float(resp_a.json()["amount"]) == 11.0
    assert float(resp_b.json()["amount"]) == 22.0
