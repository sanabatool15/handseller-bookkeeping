"""Scenario 2: cross-tenant isolation across the full product surface.

Real-infra e2e: two real orgs (A, B) each with a real user row, real sales,
real expenses, and a real agent_jobs row. Asserts org B gets 404 (never 403
or 200) reading/updating/deleting org A's records by exact id, and that
list endpoints never leak the other org's rows. Directly exercises the
`id`+`org_id` double-scoping rule in CLAUDE.md / specs/03-multi-tenancy-security.md
against the real Postgres RLS/repository layer, not FakeSupabase.
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


def test_cross_tenant_isolation(client, cleanup):
    token_a, org_a, _ = _register(client, cleanup, "tenant-a")
    token_b, org_b, _ = _register(client, cleanup, "tenant-b")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    sale_a = client.post(
        "/sales", json={"amount": 200.0, "category": "retail"},
        headers={**headers_a, "Idempotency-Key": "tenant-a-sale"},
    )
    assert sale_a.status_code == 201, sale_a.text
    sale_a_id = sale_a.json()["id"]
    cleanup.track_row("sales", sale_a_id, org_a)

    expense_a = client.post(
        "/expenses", json={"amount": 50.0, "category": "supplies"},
        headers={**headers_a, "Idempotency-Key": "tenant-a-expense"},
    )
    assert expense_a.status_code == 201, expense_a.text
    expense_a_id = expense_a.json()["id"]
    cleanup.track_row("expenses", expense_a_id, org_a)

    job_a = client.post(
        "/agent-jobs/financial-advice", headers={**headers_a, "Idempotency-Key": "tenant-a-job"}
    )
    assert job_a.status_code == 202, job_a.text
    job_a_id = job_a.json()["job_id"]
    cleanup.track_row("agent_jobs", job_a_id, org_a)

    # --- Org B must get 404 (never 403/200) touching org A's records by id ---
    assert client.get(f"/sales/{sale_a_id}", headers=headers_b).status_code == 404
    assert client.put(
        f"/sales/{sale_a_id}", json={"amount": 1.0},
        headers={**headers_b, "Idempotency-Key": "tenant-b-tries-sale-upd"},
    ).status_code == 404
    assert client.delete(
        f"/sales/{sale_a_id}", headers={**headers_b, "Idempotency-Key": "tenant-b-tries-sale-del"}
    ).status_code == 404

    assert client.get(f"/expenses/{expense_a_id}", headers=headers_b).status_code == 404
    assert client.put(
        f"/expenses/{expense_a_id}", json={"amount": 1.0},
        headers={**headers_b, "Idempotency-Key": "tenant-b-tries-exp-upd"},
    ).status_code == 404
    assert client.delete(
        f"/expenses/{expense_a_id}", headers={**headers_b, "Idempotency-Key": "tenant-b-tries-exp-del"}
    ).status_code == 404

    assert client.get(f"/agent-jobs/{job_a_id}", headers=headers_b).status_code == 404

    # --- Sale A row must survive the failed cross-tenant delete attempt ---
    assert client.get(f"/sales/{sale_a_id}", headers=headers_a).status_code == 200

    # --- List endpoints never leak the other org's rows ---
    b_sales = client.get("/sales", headers=headers_b).json()
    assert sale_a_id not in {s["id"] for s in b_sales}

    b_expenses = client.get("/expenses", headers=headers_b).json()
    assert expense_a_id not in {e["id"] for e in b_expenses}
